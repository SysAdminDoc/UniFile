import sqlite3

import pytest
from sqlalchemy import text

from unifile.tagging import db as tag_db


def _create_legacy_tag_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                shorthand TEXT,
                color_slug TEXT,
                is_category BOOLEAN,
                is_hidden BOOLEAN,
                icon TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY,
                folder_id INTEGER,
                path TEXT UNIQUE,
                filename TEXT,
                suffix TEXT,
                date_created DATETIME,
                date_modified DATETIME,
                date_added DATETIME
            )
            """
        )
        conn.execute(
            "INSERT INTO tags (name, color_slug, is_category, is_hidden) VALUES (?, ?, ?, ?)",
            ("legacy", "blue", 1, 0),
        )
        conn.execute(
            "INSERT INTO entries (id, folder_id, path, filename, suffix) VALUES (?, ?, ?, ?, ?)",
            (1, 1, "/tmp/legacy.txt", "legacy.txt", "txt"),
        )
        conn.execute("PRAGMA user_version = 0")


def _columns(path, table):
    with sqlite3.connect(path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _user_version(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def _quick_check(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA quick_check").fetchone()[0]


def test_make_tables_migrates_legacy_db_with_backup(tmp_path):
    db_path = tmp_path / "unifile_tags.sqlite"
    _create_legacy_tag_db(db_path)

    engine = tag_db.make_engine(str(db_path))
    tag_db.make_tables(engine)
    engine.dispose()

    assert _user_version(db_path) == tag_db.TAG_DB_SCHEMA_VERSION
    assert _quick_check(db_path) == "ok"
    assert {
        "namespace",
        "description",
        "rating",
        "is_inbox",
        "source_url",
        "media_width",
        "media_height",
        "media_duration",
        "word_count",
    } <= (_columns(db_path, "tags") | _columns(db_path, "entries"))
    backups = list(tmp_path.glob("unifile_tags.sqlite.v0-backup-*.bak"))
    assert len(backups) == 1
    assert _user_version(backups[0]) == 0
    assert "namespace" not in _columns(backups[0], "tags")


def test_make_tables_stamps_new_db_without_backup(tmp_path):
    db_path = tmp_path / "unifile_tags.sqlite"
    engine = tag_db.make_engine(str(db_path))
    tag_db.make_tables(engine)
    engine.dispose()

    assert _user_version(db_path) == tag_db.TAG_DB_SCHEMA_VERSION
    assert _quick_check(db_path) == "ok"
    assert list(tmp_path.glob("*.bak")) == []


def test_failed_migration_restores_backup(monkeypatch, tmp_path):
    db_path = tmp_path / "unifile_tags.sqlite"
    _create_legacy_tag_db(db_path)

    def failing_migration(conn):
        conn.execute(text("ALTER TABLE tags ADD COLUMN should_rollback TEXT"))
        raise RuntimeError("forced failure")

    monkeypatch.setattr(
        tag_db,
        "MIGRATIONS",
        (tag_db.Migration(1, "forced failure", failing_migration),),
    )
    engine = tag_db.make_engine(str(db_path))

    with pytest.raises(tag_db.MigrationError):
        tag_db.migrate_db(engine)
    engine.dispose()

    assert _user_version(db_path) == 0
    assert "should_rollback" not in _columns(db_path, "tags")
    assert _quick_check(db_path) == "ok"
    backups = list(tmp_path.glob("unifile_tags.sqlite.v0-backup-*.bak"))
    assert len(backups) == 1
