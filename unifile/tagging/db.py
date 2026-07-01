"""UniFile — Tag Library database engine and base model."""
import hashlib
import json
import logging
import os
import shutil
import sqlite3
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

from sqlalchemy import Dialect, Engine, String, TypeDecorator, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase

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
    return create_engine(f"sqlite:///{db_path}")


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


TAG_DB_SCHEMA_VERSION = 2

MIGRATIONS = (
    Migration(1, "legacy tag and entry metadata columns", _migration_1),
    Migration(2, "FTS5 search indexes for tags and entries", _migration_2),
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
        with sqlite3.connect(str(db_path)) as source, \
             sqlite3.connect(str(backup_path)) as target:
            source.backup(target)
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
        with sqlite3.connect(str(db_path)) as src, \
             sqlite3.connect(str(tmp_db)) as dst:
            src.backup(dst)

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
            with sqlite3.connect(str(db_path)) as conn:
                current_ver = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
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
