"""UniFile — Tag Library database engine and base model."""
import logging
import shutil
import sqlite3
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

TAG_DB_SCHEMA_VERSION = 1
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


MIGRATIONS = (
    Migration(1, "legacy tag and entry metadata columns", _migration_1),
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
    with sqlite3.connect(str(db_path)) as source, sqlite3.connect(str(backup_path)) as target:
        source.backup(target)
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
