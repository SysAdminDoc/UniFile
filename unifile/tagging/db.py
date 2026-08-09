"""UniFile — Tag Library database engine and base model."""
import hashlib
import json
import logging
import os
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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

_BACKUP_MANIFEST_VERSION = 1


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def export_library_backup(engine: Engine, dest_path: Path,
                          config_dir: Path | None = None) -> Path:
    """Export a full tag library backup as a timestamped ZIP.

    Contents: tag DB snapshot, config files, SHA-256 manifest.
    Returns the path of the created ZIP file.
    """
    db_path = _engine_db_path(engine)
    if not db_path or not db_path.exists():
        raise FileNotFoundError("No tag library database found to back up")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_name = f"unifile-backup-{timestamp}.zip"
    zip_path = dest_path / zip_name if dest_path.is_dir() else dest_path

    # Snapshot the DB via SQLite backup API (safe against WAL)
    tmp_db = db_path.with_suffix('.backup_tmp')
    try:
        src = connect_sqlite(str(db_path), check_same_thread=True)
        dst = connect_sqlite(
            str(tmp_db),
            check_same_thread=True,
            journal_mode="DELETE",
        )
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()

        manifest = {'version': _BACKUP_MANIFEST_VERSION,
                    'created': datetime.now().isoformat(),
                    'files': {}}

        with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(str(tmp_db), 'unifile_tags.sqlite')
            manifest['files']['unifile_tags.sqlite'] = _sha256_file(tmp_db)

            if config_dir:
                for name in ('settings.json', 'ai_providers.json',
                             'tag_packs.json', 'profiles.json'):
                    cfg = config_dir / name
                    if cfg.is_file():
                        zf.write(str(cfg), f'config/{name}')
                        manifest['files'][f'config/{name}'] = _sha256_file(cfg)

            zf.writestr('manifest.json', json.dumps(manifest, indent=2))

        logger.info("Library backup exported to %s", zip_path)
        return zip_path
    finally:
        try:
            tmp_db.unlink(missing_ok=True)
        except OSError:
            pass


def verify_library_backup(zip_path: Path) -> tuple[bool, str]:
    """Validate a backup ZIP's integrity and manifest checksums.

    Returns (ok, message).
    """
    try:
        with zipfile.ZipFile(str(zip_path), 'r') as zf:
            names = zf.namelist()
            if 'manifest.json' not in names:
                return False, "Missing manifest.json"
            if 'unifile_tags.sqlite' not in names:
                return False, "Missing tag library database"
            manifest = json.loads(zf.read('manifest.json'))
            if manifest.get('version', 0) > _BACKUP_MANIFEST_VERSION:
                return False, (f"Backup version {manifest['version']} is "
                               f"newer than supported v{_BACKUP_MANIFEST_VERSION}")
            for fname, expected_hash in manifest.get('files', {}).items():
                if fname not in names:
                    return False, f"Missing file: {fname}"
                actual = hashlib.sha256(zf.read(fname)).hexdigest()
                if actual != expected_hash:
                    return False, f"Checksum mismatch: {fname}"
        return True, "Backup is valid"
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        return False, f"Corrupt backup: {e}"


def restore_library_backup(engine: Engine, zip_path: Path,
                           config_dir: Path | None = None) -> None:
    """Restore a full tag library from a backup ZIP.

    Creates a pre-restore backup of the current DB before overwriting.
    """
    ok, msg = verify_library_backup(zip_path)
    if not ok:
        raise MigrationError(f"Backup verification failed: {msg}")

    db_path = _engine_db_path(engine)
    if not db_path:
        raise MigrationError("Cannot restore to in-memory database")

    # Pre-restore safety backup
    if db_path.exists():
        current_ver = 0
        try:
            conn = connect_sqlite(str(db_path), check_same_thread=True)
            try:
                current_ver = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
            finally:
                conn.close()
        except Exception:
            pass
        _backup_database(db_path, current_ver)

    engine.dispose()

    with zipfile.ZipFile(str(zip_path), 'r') as zf:
        # Restore DB
        with open(str(db_path), 'wb') as f:
            f.write(zf.read('unifile_tags.sqlite'))
        # Clean WAL/SHM
        for suffix in ('-wal', '-shm'):
            try:
                Path(str(db_path) + suffix).unlink()
            except FileNotFoundError:
                pass
        # Restore config files
        if config_dir:
            config_dir.mkdir(parents=True, exist_ok=True)
            for name in zf.namelist():
                if name.startswith('config/'):
                    dest = config_dir / os.path.basename(name)
                    with open(str(dest), 'wb') as f:
                        f.write(zf.read(name))

    logger.info("Library restored from %s", zip_path)
