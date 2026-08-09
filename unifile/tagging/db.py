"""UniFile — Tag Library database engine and base model."""
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    from typing import override
except ImportError:  # Python 3.10/3.11 compatibility
    try:
        from typing_extensions import override
    except ImportError:
        def override(func):
            return func

from sqlalchemy import Dialect, Engine, String, TypeDecorator, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase

from unifile import __version__
from unifile.sqlite_policy import (
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_TIMEOUT_SECONDS,
    SQLITE_WAL_AUTOCHECKPOINT,
    configure_sqlite_connection,
    connect_sqlite,
    ensure_supported_storage,
)

logger = logging.getLogger(__name__)

RESERVED_TAG_END = 999
TAG_ARCHIVED = 0
TAG_FAVORITE = 1


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


class PathType(TypeDecorator):
    impl = String
    cache_ok = True

    @override
    def process_bind_param(self, value, dialect: Dialect):
        if value is not None:
            return Path(value).as_posix()
        return None

    @override
    def process_result_value(self, value, dialect: Dialect):
        if value is not None:
            return Path(value)
        return None


class Base(DeclarativeBase):
    type_annotation_map = {Path: PathType}


def make_engine(db_path: str) -> Engine:
    if db_path != ":memory:":
        ensure_supported_storage(db_path)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={
            "timeout": SQLITE_TIMEOUT_SECONDS,
            "check_same_thread": False,
        },
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _configure_connection(dbapi_connection, _connection_record) -> None:
        configure_sqlite_connection(
            dbapi_connection,
            busy_timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            wal_autocheckpoint=SQLITE_WAL_AUTOCHECKPOINT,
            register=False,
        )

    return engine


def _engine_db_path(engine: Engine) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


def _table_columns(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _add_column_if_missing(conn: Connection, table: str, column: str, ddl: str) -> None:
    if column not in _table_columns(conn, table):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _table_exists(conn: Connection, table: str) -> bool:
    return bool(conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table"),
        {"table": table},
    ).scalar())


def _migration_1(conn: Connection) -> None:
    _add_column_if_missing(conn, "tags", "namespace", "namespace TEXT")
    _add_column_if_missing(conn, "tags", "description", "description TEXT")
    _add_column_if_missing(conn, "entries", "rating", "rating INTEGER")
    _add_column_if_missing(conn, "entries", "is_inbox", "is_inbox INTEGER DEFAULT 1")
    _add_column_if_missing(conn, "entries", "source_url", "source_url TEXT")
    _add_column_if_missing(conn, "entries", "media_width", "media_width INTEGER")
    _add_column_if_missing(conn, "entries", "media_height", "media_height INTEGER")
    _add_column_if_missing(conn, "entries", "media_duration", "media_duration REAL")
    _add_column_if_missing(conn, "entries", "word_count", "word_count INTEGER")


def _fts5_available(conn: Connection) -> bool:
    """Check if the SQLite build includes FTS5."""
    try:
        conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)"))
        conn.execute(text("DROP TABLE IF EXISTS _fts5_probe"))
        return True
    except OperationalError:
        return False


def _migration_2(conn: Connection) -> None:
    """Add FTS5 virtual tables and sync triggers for tag/entry search.

    Silently skips on SQLite builds without FTS5 — search falls back to LIKE.
    """
    if not _fts5_available(conn):
        logger.warning("SQLite FTS5 not available; search will use LIKE fallback")
        return
    conn.execute(text("""
        CREATE VIRTUAL TABLE IF NOT EXISTS tags_fts USING fts5(
            name, content='tags', content_rowid='id'
        )
    """))
    conn.execute(text("""
        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
            filename, suffix, content='entries', content_rowid='id'
        )
    """))
    # Populate FTS from existing data
    conn.execute(text(
        "INSERT OR IGNORE INTO tags_fts(rowid, name) SELECT id, name FROM tags"
    ))
    conn.execute(text(
        "INSERT OR IGNORE INTO entries_fts(rowid, filename, suffix) "
        "SELECT id, filename, suffix FROM entries"
    ))
    # Sync triggers — keep FTS in lockstep with main tables
    for trig in (
        """CREATE TRIGGER IF NOT EXISTS tags_fts_insert AFTER INSERT ON tags BEGIN
            INSERT INTO tags_fts(rowid, name) VALUES (new.id, new.name);
        END""",
        """CREATE TRIGGER IF NOT EXISTS tags_fts_delete AFTER DELETE ON tags BEGIN
            INSERT INTO tags_fts(tags_fts, rowid, name) VALUES ('delete', old.id, old.name);
        END""",
        """CREATE TRIGGER IF NOT EXISTS tags_fts_update AFTER UPDATE OF name ON tags BEGIN
            INSERT INTO tags_fts(tags_fts, rowid, name) VALUES ('delete', old.id, old.name);
            INSERT INTO tags_fts(rowid, name) VALUES (new.id, new.name);
        END""",
        """CREATE TRIGGER IF NOT EXISTS entries_fts_insert AFTER INSERT ON entries BEGIN
            INSERT INTO entries_fts(rowid, filename, suffix) VALUES (new.id, new.filename, new.suffix);
        END""",
        """CREATE TRIGGER IF NOT EXISTS entries_fts_delete AFTER DELETE ON entries BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, filename, suffix) VALUES ('delete', old.id, old.filename, old.suffix);
        END""",
        """CREATE TRIGGER IF NOT EXISTS entries_fts_update AFTER UPDATE OF filename, suffix ON entries BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, filename, suffix) VALUES ('delete', old.id, old.filename, old.suffix);
            INSERT INTO entries_fts(rowid, filename, suffix) VALUES (new.id, new.filename, new.suffix);
        END""",
    ):
        conn.execute(text(trig))


def _migration_3(conn: Connection) -> None:
    """Add the normalized image palette index used by color search."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS entry_colors (
            entry_id INTEGER NOT NULL,
            color_name TEXT NOT NULL,
            hex_color TEXT NOT NULL,
            weight REAL NOT NULL,
            rank INTEGER NOT NULL,
            PRIMARY KEY (entry_id, color_name),
            FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_entry_colors_name ON entry_colors(color_name)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_entry_colors_entry ON entry_colors(entry_id)"
    ))


def _migration_4(conn: Connection) -> None:
    """Store JSON validation rules alongside per-library value types."""
    if _table_exists(conn, "value_type"):
        _add_column_if_missing(conn, "value_type", "schema_json", "schema_json TEXT")


def _migration_5(conn: Connection) -> None:
    """Add covering indexes used by bounded Tag Library search plans."""
    indexes = (
        ("entries", "CREATE INDEX IF NOT EXISTS ix_entries_filename ON entries(filename)"),
        ("entries", "CREATE INDEX IF NOT EXISTS ix_entries_suffix_filename ON entries(suffix, filename)"),
        ("entries", "CREATE INDEX IF NOT EXISTS ix_entries_rating_filename ON entries(rating, filename)"),
        ("entries", "CREATE INDEX IF NOT EXISTS ix_entries_inbox_filename ON entries(is_inbox, filename)"),
        ("entries", "CREATE INDEX IF NOT EXISTS ix_entries_modified_filename "
         "ON entries(date_modified, filename)"),
        ("tags", "CREATE INDEX IF NOT EXISTS ix_tags_namespace_name ON tags(namespace, name)"),
        ("tag_entries", "CREATE INDEX IF NOT EXISTS ix_tag_entries_entry_tag ON tag_entries(entry_id, tag_id)"),
        ("entry_group_members", "CREATE INDEX IF NOT EXISTS ix_group_members_entry_group "
         "ON entry_group_members(entry_id, group_id)"),
        ("text_fields", "CREATE INDEX IF NOT EXISTS ix_text_fields_key_value_entry "
         "ON text_fields(type_key, value, entry_id)"),
        ("datetime_fields", "CREATE INDEX IF NOT EXISTS ix_datetime_fields_key_value_entry "
         "ON datetime_fields(type_key, value, entry_id)"),
        ("boolean_fields", "CREATE INDEX IF NOT EXISTS ix_boolean_fields_key_value_entry "
         "ON boolean_fields(type_key, value, entry_id)"),
        ("entry_colors", "CREATE INDEX IF NOT EXISTS ix_entry_colors_name_rank_entry "
         "ON entry_colors(color_name, rank, entry_id)"),
    )
    for table, statement in indexes:
        if _table_exists(conn, table):
            conn.execute(text(statement))


TAG_DB_SCHEMA_VERSION = 5

MIGRATIONS = (
    Migration(1, "legacy tag and entry metadata columns", _migration_1),
    Migration(2, "FTS5 search indexes for tags and entries", _migration_2),
    Migration(3, "normalized image palette color index", _migration_3),
    Migration(4, "custom field schema validation rules", _migration_4),
    Migration(5, "bounded search planner indexes", _migration_5),
)


def _get_user_version(conn: Connection) -> int:
    return int(conn.execute(text("PRAGMA user_version")).scalar() or 0)


def _set_user_version(conn: Connection, version: int) -> None:
    conn.execute(text(f"PRAGMA user_version = {int(version)}"))


def _quick_check(conn: Connection) -> None:
    result = conn.execute(text("PRAGMA quick_check")).scalar()
    if result != "ok":
        raise MigrationError(f"SQLite integrity check failed: {result}")


def _backup_database(db_path: Path, current_version: int) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(
        f"{db_path.name}.v{current_version}-backup-{timestamp}.bak"
    )
    try:
        source = connect_sqlite(str(db_path), check_same_thread=True)
        target = connect_sqlite(
            str(backup_path),
            check_same_thread=True,
            journal_mode="DELETE",
        )
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
    except Exception:
        try:
            backup_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return backup_path


def _restore_database(db_path: Path, backup_path: Path) -> None:
    shutil.copy2(backup_path, db_path)
    for suffix in ("-wal", "-shm"):
        try:
            Path(str(db_path) + suffix).unlink()
        except FileNotFoundError:
            pass


def migrate_db(engine: Engine, *, create_backup: bool = True) -> None:
    """Run deterministic SQLite migrations and record PRAGMA user_version."""
    db_path = _engine_db_path(engine)
    backup_path: Path | None = None

    with engine.connect() as conn:
        current = _get_user_version(conn)
        if current > TAG_DB_SCHEMA_VERSION:
            raise MigrationError(
                f"Tag DB schema v{current} is newer than supported v{TAG_DB_SCHEMA_VERSION}"
            )
        _quick_check(conn)
        pending = [migration for migration in MIGRATIONS if migration.version > current]

    if not pending:
        return

    if create_backup and db_path and db_path.exists():
        backup_path = _backup_database(db_path, current)

    try:
        with engine.begin() as conn:
            for migration in pending:
                logger.info("Applying tag DB migration v%s: %s", migration.version, migration.name)
                migration.apply(conn)
                _set_user_version(conn, migration.version)
            _quick_check(conn)
    except Exception as exc:
        engine.dispose()
        if backup_path and db_path:
            _restore_database(db_path, backup_path)
        raise MigrationError(f"Tag DB migration failed; restored backup {backup_path}") from exc


def make_tables(engine: Engine) -> None:
    logger.info("Creating tag library tables...")
    import unifile.tagging.models  # noqa: F401  -- registers ORM tables on Base.metadata

    db_path = _engine_db_path(engine)
    existing_db = bool(db_path and db_path.exists() and db_path.stat().st_size > 0)
    if existing_db:
        migrate_db(engine, create_backup=True)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # Legacy databases may have reached v5 before their missing ORM tables
        # were created.  Re-running this idempotent pass completes those indexes.
        _migration_5(conn)
    if not existing_db:
        migrate_db(engine, create_backup=False)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT SEQ FROM sqlite_sequence WHERE name='tags'"))
        autoincrement_val = result.scalar()
        if not autoincrement_val or autoincrement_val <= RESERVED_TAG_END:
            try:
                conn.execute(
                    text(
                        "INSERT INTO tags "
                        "(id, name, color_slug, is_category, is_hidden) VALUES "
                        f"({RESERVED_TAG_END}, 'temp', NULL, false, false)"
                    )
                )
                conn.execute(text(f"DELETE FROM tags WHERE id = {RESERVED_TAG_END}"))
                conn.commit()
            except OperationalError as e:
                logger.error("Could not initialize tag sequence: %s", e)
                conn.rollback()


# ── Full Library Backup / Restore ────────────────────────────────────────────

_BACKUP_FORMAT = 'unifile.library-backup'
_BACKUP_MANIFEST_VERSION = 2
_SUPPORTED_BACKUP_MANIFEST_VERSIONS = frozenset({1, 2})
_BACKUP_CONFIG_NAMES = ('settings.json', 'ai_providers.json', 'tag_packs.json', 'profiles.json')
_SENSITIVE_CONFIG_KEY = re.compile(
    r'(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|credential|authorization|bearer)',
    re.IGNORECASE,
)
_MAX_MANIFEST_BYTES = 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _sha256_stream(stream) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _redact_backup_value(value):
    """Remove credential-like JSON keys before config data enters a backup."""
    if isinstance(value, dict):
        return {
            str(key): _redact_backup_value(item)
            for key, item in value.items()
            if not _SENSITIVE_CONFIG_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_redact_backup_value(item) for item in value]
    return value


def _safe_config_payload(path: Path) -> bytes | None:
    try:
        with path.open('r', encoding='utf-8') as handle:
            data = json.load(handle)
        return json.dumps(
            _redact_backup_value(data),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ).encode('utf-8')
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _safe_zip_member(name: str) -> bool:
    """Reject absolute, parent-traversal, Windows, and directory entries."""
    if not name or '\x00' in name or '\\' in name or name.startswith('/'):
        return False
    if len(name) >= 2 and name[1] == ':' and name[0].isalpha():
        return False
    if name.endswith('/'):
        return False
    parts = PurePosixPath(name).parts
    return bool(parts) and all(part not in ('.', '..', '') for part in parts)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_IFMT(mode) == stat.S_IFLNK


def _allowed_backup_member(name: str) -> bool:
    return name == 'unifile_tags.sqlite' or (
        name.startswith('config/') and name.count('/') == 1 and Path(name).name in _BACKUP_CONFIG_NAMES
    )


def _invalid_backup(report: dict, message: str) -> dict:
    report['ok'] = False
    report['message'] = message
    return report


def _validate_sqlite_file(path: Path) -> None:
    """Fail closed on a payload that is not a readable, internally valid DB."""
    connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    try:
        result = connection.execute('PRAGMA quick_check').fetchone()
        if not result or result[0] != 'ok':
            raise MigrationError(f'SQLite integrity check failed: {result[0] if result else "no result"}')
    finally:
        connection.close()


def _manifest_records(manifest: dict) -> tuple[dict[str, tuple[str, int | None]], list[str]]:
    raw_files = manifest.get('files')
    if not isinstance(raw_files, dict):
        return {}, ['Manifest files must be an object']
    records: dict[str, tuple[str, int | None]] = {}
    errors: list[str] = []
    for name, raw_record in raw_files.items():
        if not isinstance(name, str) or not _safe_zip_member(name):
            errors.append(f'Unsafe manifest file name: {name!r}')
            continue
        if isinstance(raw_record, str):
            # Version 1 stored only the checksum; retain read compatibility.
            checksum, size = raw_record, None
        elif isinstance(raw_record, dict):
            checksum, size = raw_record.get('sha256'), raw_record.get('size')
            if size is not None and (not isinstance(size, int) or size < 0):
                errors.append(f'Invalid file size: {name}')
                continue
        else:
            errors.append(f'Invalid manifest file record: {name}')
            continue
        if not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', checksum):
            errors.append(f'Invalid SHA-256 checksum: {name}')
            continue
        records[name] = (checksum.lower(), size)
    return records, errors


def inspect_library_backup(zip_path: Path) -> dict:
    """Return a machine-readable integrity and compatibility report."""
    report = {
        'ok': False,
        'format': _BACKUP_FORMAT,
        'version': None,
        'message': '',
        'warnings': [],
        'manifest': None,
        'files': [],
    }
    try:
        with zipfile.ZipFile(str(zip_path), 'r') as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                return _invalid_backup(report, 'Duplicate archive member names are not allowed')
            if any(not _safe_zip_member(name) for name in names):
                return _invalid_backup(report, 'Archive contains an unsafe member name')
            if any(_is_zip_symlink(info) for info in infos):
                return _invalid_backup(report, 'Archive symlink members are not allowed')
            if 'manifest.json' not in names:
                return _invalid_backup(report, 'Missing manifest.json')
            if any(name != 'manifest.json' and not _allowed_backup_member(name) for name in names):
                return _invalid_backup(report, 'Archive contains an unexpected member')

            manifest_info = archive.getinfo('manifest.json')
            if manifest_info.file_size > _MAX_MANIFEST_BYTES:
                return _invalid_backup(report, 'Manifest exceeds the 1 MiB safety limit')
            manifest = json.loads(archive.read(manifest_info).decode('utf-8'))
            if not isinstance(manifest, dict):
                return _invalid_backup(report, 'Manifest root must be an object')
            report['manifest'] = manifest
            version = manifest.get('version')
            report['version'] = version
            if not isinstance(version, int) or version not in _SUPPORTED_BACKUP_MANIFEST_VERSIONS:
                return _invalid_backup(report, f'Unsupported backup manifest version: {version!r}')
            if version == 1:
                report['warnings'].append('Legacy v1 manifest: app, schema, feature, and platform metadata unavailable')
            else:
                if manifest.get('format') != _BACKUP_FORMAT:
                    return _invalid_backup(report, 'Manifest format is missing or unsupported')
                for key in ('app', 'schema', 'features', 'platform'):
                    if not isinstance(manifest.get(key), dict):
                        return _invalid_backup(report, f'Manifest metadata field must be an object: {key}')
                schema_version = manifest['schema'].get('tag_library')
                if not isinstance(schema_version, int) or schema_version < 0:
                    return _invalid_backup(report, 'Manifest tag-library schema is invalid')
                if schema_version > TAG_DB_SCHEMA_VERSION:
                    return _invalid_backup(
                        report,
                        f'Backup tag-library schema v{schema_version} is newer than supported v{TAG_DB_SCHEMA_VERSION}',
                    )

            records, record_errors = _manifest_records(manifest)
            if record_errors:
                return _invalid_backup(report, '; '.join(record_errors))
            payload_names = set(names) - {'manifest.json'}
            if 'unifile_tags.sqlite' not in payload_names:
                return _invalid_backup(report, 'Missing tag library database')
            if set(records) != payload_names:
                missing = sorted(payload_names - set(records))
                extra = sorted(set(records) - payload_names)
                detail = []
                if missing:
                    detail.append(f'unlisted archive members: {", ".join(missing)}')
                if extra:
                    detail.append(f'missing archive members: {", ".join(extra)}')
                return _invalid_backup(report, '; '.join(detail))

            db_info = archive.getinfo('unifile_tags.sqlite')
            with tempfile.TemporaryDirectory(prefix='unifile-backup-verify-') as temp_dir:
                temp_db = Path(temp_dir) / 'unifile_tags.sqlite'
                with archive.open(db_info, 'r') as source, temp_db.open('wb') as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                _validate_sqlite_file(temp_db)

            for name, (expected_hash, expected_size) in sorted(records.items()):
                info = archive.getinfo(name)
                with archive.open(info, 'r') as source:
                    actual_hash, actual_size = _sha256_stream(source)
                if expected_size is not None and expected_size != actual_size:
                    return _invalid_backup(report, f'Size mismatch: {name}')
                if expected_hash != actual_hash:
                    return _invalid_backup(report, f'Checksum mismatch: {name}')
                report['files'].append({
                    'name': name,
                    'size': actual_size,
                    'sha256': actual_hash,
                })
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError,
            ValueError, sqlite3.DatabaseError, zipfile.BadZipFile, MigrationError) as exc:
        return _invalid_backup(report, f'Corrupt backup: {exc}')
    report['ok'] = True
    report['message'] = 'Backup is valid'
    return report


def _backup_zip_path(dest_path: Path) -> Path:
    destination = Path(dest_path)
    if (destination.exists() and destination.is_dir()) or destination.suffix.lower() != '.zip':
        destination.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        candidate = destination / f'unifile-backup-{timestamp}.zip'
        suffix = 1
        while candidate.exists():
            candidate = destination / f'unifile-backup-{timestamp}-{suffix}.zip'
            suffix += 1
        return candidate
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _backup_file_record(path: Path) -> dict[str, int | str]:
    return {
        'sha256': _sha256_file(path),
        'size': path.stat().st_size,
    }


def export_library_backup(engine: Engine, dest_path: Path,
                          config_dir: Path | None = None) -> Path:
    """Export a versioned, checksum-protected, secret-redacted ZIP backup."""
    db_path = _engine_db_path(engine)
    if not db_path or not db_path.exists():
        raise FileNotFoundError('No tag library database found to back up')

    zip_path = _backup_zip_path(Path(dest_path))
    temp_db_fd, temp_db_name = tempfile.mkstemp(
        prefix=f'.{db_path.name}.', suffix='.backup_tmp', dir=str(db_path.parent)
    )
    os.close(temp_db_fd)
    tmp_db = Path(temp_db_name)
    tmp_db.unlink(missing_ok=True)
    temp_zip_fd, temp_zip_name = tempfile.mkstemp(
        prefix=f'.{zip_path.name}.', suffix='.tmp', dir=str(zip_path.parent)
    )
    os.close(temp_zip_fd)
    tmp_zip = Path(temp_zip_name)
    try:
        src = connect_sqlite(str(db_path), check_same_thread=True)
        dst = connect_sqlite(
            str(tmp_db),
            check_same_thread=True,
            journal_mode='DELETE',
        )
        try:
            src.backup(dst)
            snapshot_schema = int(dst.execute('PRAGMA user_version').fetchone()[0] or 0)
        finally:
            src.close()
            dst.close()
        if snapshot_schema > TAG_DB_SCHEMA_VERSION:
            raise MigrationError(
                f'Tag DB schema v{snapshot_schema} is newer than supported v{TAG_DB_SCHEMA_VERSION}'
            )

        config_payloads: dict[str, bytes] = {}
        skipped_config: list[str] = []
        if config_dir:
            for name in _BACKUP_CONFIG_NAMES:
                cfg = Path(config_dir) / name
                if not cfg.is_file():
                    continue
                payload = _safe_config_payload(cfg)
                if payload is None:
                    skipped_config.append(name)
                else:
                    config_payloads[f'config/{name}'] = payload

        manifest = {
            'format': _BACKUP_FORMAT,
            'version': _BACKUP_MANIFEST_VERSION,
            'created': _utc_now(),
            'app': {'name': 'UniFile', 'version': __version__},
            'schema': {'tag_library': snapshot_schema, 'supported_max': TAG_DB_SCHEMA_VERSION},
            'features': {
                'sqlite_snapshot': 'online-backup-api',
                'config_files': sorted(config_payloads),
                'secrets': 'excluded; resolve from OS keyring or environment on restore',
                'skipped_config_files': skipped_config,
            },
            'platform': {
                'system': platform.system(),
                'release': platform.release(),
                'machine': platform.machine(),
                'python': platform.python_version(),
            },
            'files': {},
        }
        manifest['files']['unifile_tags.sqlite'] = _backup_file_record(tmp_db)
        for name, payload in config_payloads.items():
            manifest['files'][name] = {
                'sha256': hashlib.sha256(payload).hexdigest(),
                'size': len(payload),
            }

        with zipfile.ZipFile(str(tmp_zip), 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(str(tmp_db), 'unifile_tags.sqlite')
            for name, payload in sorted(config_payloads.items()):
                archive.writestr(name, payload)
            archive.writestr(
                'manifest.json',
                json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
            )
        os.replace(tmp_zip, zip_path)
        logger.info('Library backup exported to %s', zip_path)
        return zip_path
    finally:
        try:
            tmp_db.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            pass


def verify_library_backup(zip_path: Path) -> tuple[bool, str]:
    """Validate a backup ZIP while retaining the historical tuple API."""
    report = inspect_library_backup(Path(zip_path))
    return bool(report['ok']), str(report['message'])


def _stage_zip_member(archive: zipfile.ZipFile, name: str, directory: Path) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix='.unifile-restore-', dir=str(directory))
    staged = Path(raw_path)
    try:
        with os.fdopen(fd, 'wb') as target, archive.open(name, 'r') as source:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        return staged
    except Exception:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _restore_original_file(path: Path, payload: bytes | None) -> None:
    if payload is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix='.unifile-rollback-', dir=str(path.parent))
    staged = Path(raw_path)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def restore_library_backup(engine: Engine, zip_path: Path,
                           config_dir: Path | None = None) -> None:
    """Restore a backup atomically, migrate older schemas, and roll back on failure."""
    report = inspect_library_backup(Path(zip_path))
    if not report['ok']:
        raise MigrationError(f"Backup verification failed: {report['message']}")

    db_path = _engine_db_path(engine)
    if not db_path:
        raise MigrationError('Cannot restore to in-memory database')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    archive_config_names = sorted(
        item['name'] for item in report['files'] if item['name'].startswith('config/')
    )
    config_targets = {
        name: Path(config_dir) / Path(name).name
        for name in archive_config_names
        if config_dir is not None
    }
    original_config = {
        path: path.read_bytes() if path.is_file() else None
        for path in config_targets.values()
    }
    had_database = db_path.is_file()
    pre_restore_backup: Path | None = None
    if had_database:
        current_version = 0
        try:
            connection = connect_sqlite(str(db_path), check_same_thread=True)
            try:
                current_version = int(connection.execute('PRAGMA user_version').fetchone()[0] or 0)
            finally:
                connection.close()
        except (OSError, sqlite3.DatabaseError):
            pass
        pre_restore_backup = _backup_database(db_path, current_version)

    staged_paths: list[Path] = []
    restored_engine = None
    try:
        engine.dispose()
        with zipfile.ZipFile(str(zip_path), 'r') as archive:
            staged_db = _stage_zip_member(archive, 'unifile_tags.sqlite', db_path.parent)
            staged_paths.append(staged_db)
            _validate_sqlite_file(staged_db)
            staged_configs: dict[str, Path] = {}
            for name, destination in config_targets.items():
                destination.parent.mkdir(parents=True, exist_ok=True)
                staged_config = _stage_zip_member(archive, name, destination.parent)
                staged_paths.append(staged_config)
                staged_configs[name] = staged_config

        os.replace(staged_db, db_path)
        staged_paths.remove(staged_db)
        for name, destination in config_targets.items():
            os.replace(staged_configs[name], destination)
            staged_paths.remove(staged_configs[name])
        for suffix in ('-wal', '-shm'):
            Path(str(db_path) + suffix).unlink(missing_ok=True)

        # Opening through the normal migration path upgrades supported older
        # backups before callers see the restored library.
        restored_engine = make_engine(str(db_path))
        make_tables(restored_engine)
        restored_engine.dispose()
        restored_engine = None
    except Exception as exc:
        if restored_engine is not None:
            restored_engine.dispose()
        rollback_errors: list[str] = []
        try:
            if pre_restore_backup is not None:
                _restore_database(db_path, pre_restore_backup)
            elif not had_database:
                db_path.unlink(missing_ok=True)
                for suffix in ('-wal', '-shm'):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)
        except Exception as rollback_exc:
            rollback_errors.append(f'database: {rollback_exc}')
        for path, payload in original_config.items():
            try:
                _restore_original_file(path, payload)
            except Exception as rollback_exc:
                rollback_errors.append(f'{path.name}: {rollback_exc}')
        detail = f'Restore failed and was rolled back: {exc}'
        if rollback_errors:
            detail += '; rollback errors: ' + '; '.join(rollback_errors)
        raise MigrationError(detail) from exc
    finally:
        for staged in staged_paths:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
        engine.dispose()

    logger.info('Library restored from %s', zip_path)
