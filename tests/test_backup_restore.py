"""Versioned tag-library backup, restore, and archive-safety coverage."""

import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text

from unifile.tagging import db as tag_db


def _make_database(path: Path, tag_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = tag_db.make_engine(str(path))
    tag_db.make_tables(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tags (name, color_slug, is_category, is_hidden) "
                "VALUES (:name, NULL, 0, 0)"
            ),
            {'name': tag_name},
        )
    engine.dispose()


def _tag_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {row[0] for row in connection.execute('SELECT name FROM tags')}


def test_export_manifest_redacts_secrets_and_restore_migrates_empty_target(tmp_path):
    source_db = tmp_path / 'source' / '.unifile' / 'unifile_tags.sqlite'
    _make_database(source_db, 'from-backup')
    with sqlite3.connect(source_db) as connection:
        connection.execute('PRAGMA user_version = 1')

    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    (config_dir / 'settings.json').write_text(
        json.dumps({'theme': 'Nord', 'api_key': 'must-not-ship', 'nested': {'password': 'secret'}}),
        encoding='utf-8',
    )
    (config_dir / 'tag_packs.json').write_text(json.dumps({'packs': ['starter']}), encoding='utf-8')

    source_engine = tag_db.make_engine(str(source_db))
    backup_path = tag_db.export_library_backup(source_engine, tmp_path / 'backups', config_dir)
    source_engine.dispose()

    report = tag_db.inspect_library_backup(backup_path)
    assert report['ok'] is True
    assert report['version'] == 2
    assert report['manifest']['app']['name'] == 'UniFile'
    assert report['manifest']['schema']['tag_library'] == 1
    assert report['manifest']['features']['secrets'].startswith('excluded')
    with zipfile.ZipFile(backup_path) as archive:
        settings = archive.read('config/settings.json').decode('utf-8')
        assert 'must-not-ship' not in settings
        assert 'password' not in settings

    target_db = tmp_path / 'target' / '.unifile' / 'unifile_tags.sqlite'
    target_config = tmp_path / 'target-config'
    target_engine = tag_db.make_engine(str(target_db))
    tag_db.restore_library_backup(target_engine, backup_path, target_config)
    target_engine.dispose()

    assert _tag_names(target_db) >= {'from-backup'}
    with sqlite3.connect(target_db) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == tag_db.TAG_DB_SCHEMA_VERSION
    restored_settings = json.loads((target_config / 'settings.json').read_text(encoding='utf-8'))
    assert restored_settings == {'nested': {}, 'theme': 'Nord'}


def test_inspection_rejects_traversal_checksum_and_malformed_archives(tmp_path):
    traversal = tmp_path / 'traversal.zip'
    with zipfile.ZipFile(traversal, 'w') as archive:
        archive.writestr('manifest.json', '{}')
        archive.writestr('../outside.txt', b'nope')
    traversal_report = tag_db.inspect_library_backup(traversal)
    assert traversal_report['ok'] is False
    assert 'unsafe' in traversal_report['message'].lower()

    malformed = tmp_path / 'malformed.zip'
    with zipfile.ZipFile(malformed, 'w') as archive:
        archive.writestr('manifest.json', '{not-json')
    malformed_report = tag_db.inspect_library_backup(malformed)
    assert malformed_report['ok'] is False
    assert 'corrupt' in malformed_report['message'].lower()

    source_db = tmp_path / 'source' / '.unifile' / 'unifile_tags.sqlite'
    _make_database(source_db, 'checksum-source')
    engine = tag_db.make_engine(str(source_db))
    valid = tag_db.export_library_backup(engine, tmp_path / 'valid')
    engine.dispose()
    corrupt = tmp_path / 'corrupt.zip'
    with zipfile.ZipFile(valid) as source, zipfile.ZipFile(corrupt, 'w') as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == 'unifile_tags.sqlite':
                payload += b'corruption'
            target.writestr(info, payload)
    corrupt_report = tag_db.inspect_library_backup(corrupt)
    assert corrupt_report['ok'] is False
    assert any(
        marker in corrupt_report['message'].lower()
        for marker in ('checksum mismatch', 'size mismatch', 'integrity')
    )


def test_legacy_v1_manifest_remains_readable(tmp_path):
    source_db = tmp_path / 'source' / '.unifile' / 'unifile_tags.sqlite'
    _make_database(source_db, 'legacy-format')
    engine = tag_db.make_engine(str(source_db))
    current = tag_db.export_library_backup(engine, tmp_path / 'current')
    engine.dispose()

    legacy = tmp_path / 'legacy-v1.zip'
    with zipfile.ZipFile(current) as source:
        manifest = json.loads(source.read('manifest.json'))
        manifest = {
            'version': 1,
            'created': manifest['created'],
            'files': {
                name: record['sha256']
                for name, record in manifest['files'].items()
            },
        }
        with zipfile.ZipFile(legacy, 'w') as target:
            for info in source.infolist():
                if info.filename == 'manifest.json':
                    target.writestr(info, json.dumps(manifest))
                else:
                    target.writestr(info, source.read(info.filename))

    report = tag_db.inspect_library_backup(legacy)
    assert report['ok'] is True
    assert report['version'] == 1
    assert report['warnings']


def test_restore_rolls_back_database_and_config_after_post_write_failure(monkeypatch, tmp_path):
    source_db = tmp_path / 'source' / '.unifile' / 'unifile_tags.sqlite'
    target_db = tmp_path / 'target' / '.unifile' / 'unifile_tags.sqlite'
    _make_database(source_db, 'new-data')
    _make_database(target_db, 'old-data')
    source_config = tmp_path / 'source-config'
    target_config = tmp_path / 'target-config'
    source_config.mkdir()
    target_config.mkdir()
    (source_config / 'tag_packs.json').write_text(json.dumps({'source': True}), encoding='utf-8')
    (target_config / 'tag_packs.json').write_text(json.dumps({'source': False}), encoding='utf-8')

    source_engine = tag_db.make_engine(str(source_db))
    backup_path = tag_db.export_library_backup(source_engine, tmp_path / 'backups', source_config)
    source_engine.dispose()
    target_engine = tag_db.make_engine(str(target_db))

    def fail_migration(_engine):
        raise RuntimeError('forced post-write failure')

    monkeypatch.setattr(tag_db, 'make_tables', fail_migration)
    with pytest.raises(tag_db.MigrationError, match='rolled back'):
        tag_db.restore_library_backup(target_engine, backup_path, target_config)

    assert _tag_names(target_db) >= {'old-data'}
    assert 'new-data' not in _tag_names(target_db)
    assert json.loads((target_config / 'tag_packs.json').read_text(encoding='utf-8')) == {'source': False}


def test_backup_verify_cli_and_dry_run_are_machine_readable(tmp_path):
    source_db = tmp_path / 'source' / '.unifile' / 'unifile_tags.sqlite'
    _make_database(source_db, 'cli-source')
    engine = tag_db.make_engine(str(source_db))
    backup_path = tag_db.export_library_backup(engine, tmp_path / 'backups')
    engine.dispose()
    env = os.environ.copy()
    env['APPDATA'] = str(tmp_path / 'appdata')

    for command in (
        ['backup-verify', str(backup_path), '--json'],
        ['restore', str(backup_path), str(tmp_path / 'dry-run-target'), '--dry-run', '--json'],
    ):
        completed = subprocess.run(
            [sys.executable, '-m', 'unifile', *command],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)
        assert payload['ok'] is True
        assert payload['version'] == 2

    assert not (tmp_path / 'dry-run-target').exists()
