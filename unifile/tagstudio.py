"""TagStudio SQLite interoperability.

The adapter deliberately treats a TagStudio database as an external data source:
imports open it in SQLite read-only mode, while exports write an additive
TagStudio database without modifying the UniFile database or library files.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime as dt
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from unifile.sqlite_policy import connect_sqlite
from unifile.tagging.library import TagLibrary
from unifile.tagging.models import (
    DatetimeField,
    Entry,
    FieldTypeEnum,
    Tag,
    TagAlias,
    TagParent,
    TextField,
    ValueType,
)

TAGSTUDIO_FOLDER_NAME = ".TagStudio"
TAGSTUDIO_THUMB_CACHE_NAME = "thumbs"
TAGSTUDIO_DATABASE_NAMES = (
    "ts_library.sqlite",
    "ts_library.db",
    "tagstudio.sqlite",
    "tagstudio.db",
    "library.sqlite",
    "library.db",
)
TAGSTUDIO_DB_VERSION = 300
_FIELD_KEY_RE = re.compile(r"[^a-z0-9]+")


class TagStudioInteropError(RuntimeError):
    """Raised when a TagStudio database cannot be safely interoperated with."""


@dataclass
class TagStudioResult:
    """Machine-readable result shared by the CLI and GUI integration."""

    operation: str
    source: str
    target: str
    database: str = ""
    tags: int = 0
    entries: int = 0
    fields: int = 0
    thumbnails: int = 0
    merged: int = 0
    skipped: int = 0
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _library_root_for_database(database: Path) -> Path:
    if database.parent.name.casefold() == TAGSTUDIO_FOLDER_NAME.casefold():
        return database.parent.parent
    return database.parent


def _database_candidates(source: str | os.PathLike[str]) -> tuple[Path, list[Path]]:
    path = Path(source).expanduser()
    if path.is_file():
        return _library_root_for_database(path), [path]

    root = path
    if root.name.casefold() == TAGSTUDIO_FOLDER_NAME.casefold():
        root = root.parent
    tagstudio_dirs = [root / TAGSTUDIO_FOLDER_NAME]
    if root.is_dir():
        tagstudio_dirs.extend(
            child
            for child in root.iterdir()
            if child.is_dir() and child.name.casefold() == TAGSTUDIO_FOLDER_NAME.casefold()
        )
    candidates = [directory / name for directory in tagstudio_dirs for name in TAGSTUDIO_DATABASE_NAMES]
    candidates.extend(root / name for name in TAGSTUDIO_DATABASE_NAMES)
    return root, _unique_paths(candidates)


def locate_tagstudio_database(source: str | os.PathLike[str]) -> tuple[Path, Path]:
    """Return ``(library_root, database_path)`` for a TagStudio source."""
    root, candidates = _database_candidates(source)
    for candidate in candidates:
        if candidate.is_file():
            return root if root.exists() else _library_root_for_database(candidate), candidate
    raise FileNotFoundError(
        f"No TagStudio SQLite database found under {Path(source).expanduser()}"
    )


def _readonly_connection(database: Path) -> sqlite3.Connection:
    """Open a database without granting SQLite any write capability."""
    path_uri = database.resolve().as_posix()
    try:
        connection = connect_sqlite(
            f"file:{path_uri}?mode=ro",
            uri=True,
            timeout=5,
            check_same_thread=True,
            read_only=True,
            query_only=True,
        )
    except sqlite3.OperationalError as exc:
        raise TagStudioInteropError(f"Could not open TagStudio database read-only: {database}") from exc
    connection.row_factory = sqlite3.Row
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if table not in _table_names(connection):
        return set()
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _read_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    columns = sorted(_table_columns(connection, table))
    if not columns:
        return []
    quoted = ", ".join(f'"{column}"' for column in columns)
    return [dict(row) for row in connection.execute(f'SELECT {quoted} FROM "{table}"')]


def _value(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return default if value is None else int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_datetime(value: Any) -> dt | None:
    if value is None or isinstance(value, dt):
        return value
    if isinstance(value, (int, float)):
        try:
            return dt.fromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _entry_path(library_root: Path, raw_path: Any, filename: Any) -> Path | None:
    raw = str(raw_path or "").strip()
    name = str(filename or "").strip()
    if not raw and not name:
        return None
    path = Path(raw) if raw else Path(name)
    if not path.is_absolute():
        path = library_root / path
    if name and path.name.casefold() != name.casefold():
        path = path / name
    return path


def _field_key(name: str, used: set[str]) -> str:
    base = _FIELD_KEY_RE.sub("_", name.strip().casefold()).strip("_") or "imported_field"
    if base[0].isdigit():
        base = f"field_{base}"
    key = base
    suffix = 2
    while key in used:
        key = f"{base}_{suffix}"
        suffix += 1
    used.add(key)
    return key


def _find_child(parent: Path, name: str) -> Path | None:
    if not parent.is_dir():
        return None
    for child in parent.iterdir():
        if child.name.casefold() == name.casefold() and child.is_dir():
            return child
    return None


def _tagstudio_thumbs(library_root: Path) -> Path | None:
    folder = _find_child(library_root, TAGSTUDIO_FOLDER_NAME)
    if folder is None:
        return None
    return _find_child(folder, TAGSTUDIO_THUMB_CACHE_NAME)


def _copy_thumbnail_tree(source: Path | None, destination: Path) -> tuple[int, int]:
    if source is None or not source.is_dir():
        return 0, 0
    try:
        if source.resolve() == destination.resolve():
            return 0, 0
    except OSError:
        pass
    copied = 0
    skipped = 0
    for item in source.rglob("*"):
        if item.is_symlink() or not item.is_file():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        if target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied += 1
    return copied, skipped


def _tagstudio_version(connection: sqlite3.Connection) -> int:
    if "versions" in _table_names(connection):
        row = connection.execute(
            "SELECT value FROM versions WHERE key = 'CURRENT' LIMIT 1"
        ).fetchone()
        if row:
            return _as_int(row[0], 0) or 0
    if "preferences" in _table_names(connection):
        row = connection.execute(
            "SELECT value FROM preferences WHERE key = 'DB_VERSION' LIMIT 1"
        ).fetchone()
        if row:
            return _as_int(row[0], 0) or 0
    return 0


def inspect_tagstudio(source: str | os.PathLike[str]) -> dict[str, Any]:
    """Inspect a TagStudio database without changing it."""
    root, database = locate_tagstudio_database(source)
    with _readonly_connection(database) as connection:
        tables = _table_names(connection)
        if not {"tags", "entries", "tag_entries"}.issubset(tables):
            raise TagStudioInteropError(
                f"TagStudio database is missing required tables: {database}"
            )
        text_fields = len(_read_rows(connection, "text_fields"))
        datetime_fields = len(_read_rows(connection, "datetime_fields"))
        thumbnails = _tagstudio_thumbs(root)
        thumbnail_count = sum(1 for item in thumbnails.rglob("*") if item.is_file()) if thumbnails else 0
        return {
            "library_root": str(root),
            "database": str(database),
            "schema_version": _tagstudio_version(connection),
            "tags": len(_read_rows(connection, "tags")),
            "entries": len(_read_rows(connection, "entries")),
            "fields": text_fields + datetime_fields,
            "thumbnails": thumbnail_count,
        }


def _ensure_value_type(
    session,
    value_types: dict[str, ValueType],
    used_keys: set[str],
    name: str,
    field_type: FieldTypeEnum,
) -> ValueType:
    normalized = name.casefold()
    existing = next((item for item in value_types.values() if item.name.casefold() == normalized), None)
    if existing:
        return existing
    key = _field_key(name, used_keys)
    value_type = ValueType(
        key=key,
        name=name,
        type=field_type,
        is_default=False,
        position=max((item.position for item in value_types.values()), default=0) + 1,
    )
    session.add(value_type)
    session.flush()
    value_types[key] = value_type
    return value_type


def import_tagstudio(
    source: str | os.PathLike[str],
    target_library: str | os.PathLike[str],
    *,
    copy_thumbnails: bool = True,
    dry_run: bool = False,
) -> TagStudioResult:
    """Import a TagStudio library into a UniFile library.

    The source database is always read-only. Existing UniFile tags, entries,
    fields, and relationships are retained; imported values are unioned into
    them and never replace existing metadata.
    """
    source_root, database = locate_tagstudio_database(source)
    target_root = Path(target_library).expanduser().resolve()
    result = TagStudioResult(
        operation="import",
        source=str(database),
        target=str(target_root),
        database=str(database),
        dry_run=dry_run,
    )

    with _readonly_connection(database) as connection:
        tables = _table_names(connection)
        required = {"tags", "entries", "tag_entries"}
        if not required.issubset(tables):
            raise TagStudioInteropError(
                f"TagStudio database is missing required tables: {', '.join(sorted(required - tables))}"
            )
        tag_rows = _read_rows(connection, "tags")
        entry_rows = _read_rows(connection, "entries")
        parent_rows = _read_rows(connection, "tag_parents")
        alias_rows = _read_rows(connection, "tag_aliases")
        tag_entry_rows = _read_rows(connection, "tag_entries")
        text_rows = _read_rows(connection, "text_fields")
        datetime_rows = _read_rows(connection, "datetime_fields")
        result.tags = len(tag_rows)
        result.entries = len(entry_rows)
        result.fields = len(text_rows) + len(datetime_rows)
        source_thumbs = _tagstudio_thumbs(source_root)

        if dry_run:
            result.warnings.append("dry-run: no UniFile database or thumbnail files were changed")
            return result

        target_root.mkdir(parents=True, exist_ok=True)
        library = TagLibrary(str(target_root))
        if not library.open():
            raise TagStudioInteropError(f"Could not open UniFile library: {target_root}")
        try:
            session = library._session
            source_name_counts = Counter(
                str(_value(row, "name", default="")).strip().casefold()
                for row in tag_rows
            )
            source_name_seen: Counter[str] = Counter()
            target_tags = list(session.execute(select(Tag)).scalars())
            target_tags_by_name = {
                tag.name.casefold(): tag for tag in target_tags if tag.name
            }
            tag_map: dict[int, Tag] = {}
            session.commit()

            with session.begin():
                for row in tag_rows:
                    source_id = _as_int(_value(row, "id"))
                    name = str(_value(row, "name", default="")).strip()
                    if source_id is None or not name:
                        result.skipped += 1
                        result.warnings.append("Skipped a TagStudio tag without an id or name")
                        continue
                    normalized = name.casefold()
                    source_name_seen[normalized] += 1
                    existing = target_tags_by_name.get(normalized)
                    if existing is not None and source_name_seen[normalized] == 1:
                        tag_map[source_id] = existing
                        result.merged += 1
                        continue

                    imported_name = name
                    if normalized in target_tags_by_name or source_name_counts[normalized] > 1:
                        imported_name = f"{name} (TagStudio {source_id})"
                        suffix = 2
                        while imported_name.casefold() in target_tags_by_name:
                            imported_name = f"{name} (TagStudio {source_id}-{suffix})"
                            suffix += 1
                        result.conflicts.append(
                            f"Tag '{name}' was imported as '{imported_name}' to preserve a duplicate"
                        )

                    desired_id = source_id if source_id >= 0 and session.get(Tag, source_id) is None else None
                    tag = Tag(
                        name=imported_name,
                        id=desired_id,
                        shorthand=_value(row, "shorthand"),
                        color_slug=_value(row, "color_slug", "color"),
                        is_category=_as_bool(_value(row, "is_category")),
                        is_hidden=_as_bool(_value(row, "is_hidden")),
                        icon=_value(row, "icon"),
                        namespace=_value(row, "namespace"),
                        description=_value(row, "description"),
                    )
                    session.add(tag)
                    session.flush()
                    target_tags_by_name[imported_name.casefold()] = tag
                    tag_map[source_id] = tag

                for row in alias_rows:
                    source_tag_id = _as_int(_value(row, "tag_id"))
                    alias_name = str(_value(row, "name", default="")).strip()
                    tag = tag_map.get(source_tag_id) if source_tag_id is not None else None
                    if not tag or not alias_name:
                        continue
                    exists = session.execute(
                        select(TagAlias).where(TagAlias.tag_id == tag.id, TagAlias.name == alias_name)
                    ).scalars().first()
                    if not exists:
                        session.add(TagAlias(name=alias_name, tag_id=tag.id))

                for row in parent_rows:
                    parent_id = _as_int(_value(row, "parent_id"))
                    child_id = _as_int(_value(row, "child_id"))
                    parent = tag_map.get(parent_id) if parent_id is not None else None
                    child = tag_map.get(child_id) if child_id is not None else None
                    if not parent or not child or parent.id == child.id:
                        continue
                    if session.get(TagParent, (parent.id, child.id)) is None:
                        session.add(TagParent(parent_id=parent.id, child_id=child.id))

                target_entries = list(session.execute(select(Entry)).scalars())
                target_entries_by_path = {_path_key(entry.path): entry for entry in target_entries}
                entry_map: dict[int, Entry] = {}
                for row in entry_rows:
                    source_id = _as_int(_value(row, "id"))
                    path = _entry_path(source_root, _value(row, "path"), _value(row, "filename"))
                    if source_id is None or path is None:
                        result.skipped += 1
                        result.warnings.append("Skipped a TagStudio entry without a usable path")
                        continue
                    key = _path_key(path)
                    entry = target_entries_by_path.get(key)
                    if entry is not None:
                        result.merged += 1
                    else:
                        desired_id = source_id if source_id >= 0 and session.get(Entry, source_id) is None else None
                        entry = Entry(
                            id=desired_id,
                            folder=library._folder_for_path(path),
                            path=path,
                            filename=path.name,
                            suffix=(path.suffix.lstrip(".") or str(_value(row, "suffix", default=""))).lower(),
                            date_created=_parse_datetime(_value(row, "date_created")),
                            date_modified=_parse_datetime(_value(row, "date_modified")),
                            date_added=_parse_datetime(_value(row, "date_added")) or dt.now(),
                        )
                        session.add(entry)
                        session.flush()
                        target_entries_by_path[key] = entry
                    entry_map[source_id] = entry

                for row in tag_entry_rows:
                    source_tag_id = _as_int(_value(row, "tag_id"))
                    source_entry_id = _as_int(_value(row, "entry_id"))
                    tag = tag_map.get(source_tag_id) if source_tag_id is not None else None
                    entry = entry_map.get(source_entry_id) if source_entry_id is not None else None
                    if tag and entry:
                        entry.tags.add(tag)

                value_types = {
                    value_type.key: value_type
                    for value_type in session.execute(select(ValueType)).scalars()
                }
                used_keys = set(value_types)
                for row in text_rows:
                    source_entry_id = _as_int(_value(row, "entry_id"))
                    entry = entry_map.get(source_entry_id) if source_entry_id is not None else None
                    name = str(_value(row, "name", "type_key", default="Imported Field")).strip()
                    if not entry or not name:
                        continue
                    value_type = _ensure_value_type(
                        session, value_types, used_keys, name,
                        FieldTypeEnum.TEXT_BOX if _as_bool(_value(row, "is_multiline")) else FieldTypeEnum.TEXT_LINE,
                    )
                    value = _value(row, "value")
                    if value is None:
                        continue
                    exists = session.execute(
                        select(TextField).where(
                            TextField.entry_id == entry.id,
                            TextField.type_key == value_type.key,
                        )
                    ).scalars().first()
                    if not exists:
                        session.add(TextField(
                            type_key=value_type.key,
                            entry_id=entry.id,
                            position=value_type.position,
                            value=str(value),
                        ))

                for row in datetime_rows:
                    source_entry_id = _as_int(_value(row, "entry_id"))
                    entry = entry_map.get(source_entry_id) if source_entry_id is not None else None
                    name = str(_value(row, "name", "type_key", default="Imported Date")).strip()
                    if not entry or not name:
                        continue
                    value_type = _ensure_value_type(
                        session, value_types, used_keys, name, FieldTypeEnum.DATETIME
                    )
                    value = _value(row, "value")
                    if value is None:
                        continue
                    exists = session.execute(
                        select(DatetimeField).where(
                            DatetimeField.entry_id == entry.id,
                            DatetimeField.type_key == value_type.key,
                        )
                    ).scalars().first()
                    if not exists:
                        session.add(DatetimeField(
                            type_key=value_type.key,
                            entry_id=entry.id,
                            position=value_type.position,
                            value=str(value),
                        ))

            if copy_thumbnails and source_thumbs:
                destination = target_root / ".unifile" / "tagstudio-thumbs"
                copied, skipped = _copy_thumbnail_tree(source_thumbs, destination)
                result.thumbnails = copied
                result.skipped += skipped
        finally:
            library.close()

    return result


_TAGSTUDIO_SCHEMA = """
CREATE TABLE IF NOT EXISTS namespaces (
    namespace TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tag_colors (
    slug TEXT NOT NULL,
    namespace TEXT NOT NULL,
    name TEXT,
    "primary" TEXT NOT NULL,
    secondary TEXT,
    color_border BOOLEAN NOT NULL DEFAULT 0,
    PRIMARY KEY (slug, namespace)
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    shorthand TEXT,
    color_namespace TEXT,
    color_slug TEXT,
    is_category BOOLEAN NOT NULL DEFAULT 0,
    is_hidden BOOLEAN NOT NULL DEFAULT 0,
    icon TEXT,
    disambiguation_id INTEGER
);
CREATE TABLE IF NOT EXISTS tag_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    tag_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tag_parents (
    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    PRIMARY KEY (parent_id, child_id)
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL DEFAULT '',
    suffix TEXT NOT NULL DEFAULT '',
    date_created DATETIME,
    date_modified DATETIME,
    date_added DATETIME
);
CREATE TABLE IF NOT EXISTS tag_entries (
    tag_id INTEGER NOT NULL,
    entry_id INTEGER NOT NULL,
    PRIMARY KEY (tag_id, entry_id)
);
CREATE TABLE IF NOT EXISTS text_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    entry_id INTEGER NOT NULL,
    value TEXT,
    is_multiline BOOLEAN NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS datetime_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    entry_id INTEGER NOT NULL,
    value TEXT
);
CREATE TABLE IF NOT EXISTS text_field_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    is_multiline BOOLEAN NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS datetime_field_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS versions (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _table_columns(connection, table):
        connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')


def _prepare_export_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_TAGSTUDIO_SCHEMA)
    for table, column, definition in (
        ("tags", "shorthand", "TEXT"),
        ("tags", "color_namespace", "TEXT"),
        ("tags", "color_slug", "TEXT"),
        ("tags", "is_category", "BOOLEAN NOT NULL DEFAULT 0"),
        ("tags", "is_hidden", "BOOLEAN NOT NULL DEFAULT 0"),
        ("tags", "icon", "TEXT"),
        ("tags", "disambiguation_id", "INTEGER"),
        ("entries", "filename", "TEXT NOT NULL DEFAULT ''"),
        ("entries", "suffix", "TEXT NOT NULL DEFAULT ''"),
        ("entries", "date_created", "DATETIME"),
        ("entries", "date_modified", "DATETIME"),
        ("entries", "date_added", "DATETIME"),
        ("text_fields", "is_multiline", "BOOLEAN NOT NULL DEFAULT 0"),
    ):
        _ensure_column(connection, table, column, definition)


def _export_database_path(destination: str | os.PathLike[str]) -> tuple[Path, Path]:
    path = Path(destination).expanduser()
    if path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"} or path.is_file():
        database = path.resolve()
        root = _library_root_for_database(database)
    else:
        root = path.resolve()
        database = root / TAGSTUDIO_FOLDER_NAME / "ts_library.sqlite"
    return root, database


def _iso_datetime(value: dt | None) -> str | None:
    return value.isoformat(sep=" ") if value else None


def export_tagstudio(
    source_library: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    copy_thumbnails: bool = True,
) -> TagStudioResult:
    """Export UniFile metadata to an additive TagStudio SQLite library."""
    source_root = Path(source_library).expanduser().resolve()
    source_db = source_root / ".unifile" / "unifile_tags.sqlite"
    if not source_db.is_file():
        raise FileNotFoundError(f"No UniFile tag database found at {source_db}")
    output_root, output_db = _export_database_path(destination)
    result = TagStudioResult(
        operation="export",
        source=str(source_root),
        target=str(output_root),
        database=str(output_db),
    )

    library = TagLibrary(str(source_root))
    if not library.open():
        raise TagStudioInteropError(f"Could not open UniFile library: {source_root}")
    try:
        session = library._session
        tags = list(session.execute(
            select(Tag).options(selectinload(Tag.aliases), selectinload(Tag.parent_tags))
        ).scalars())
        entries = list(session.execute(
            select(Entry).options(
                selectinload(Entry.tags),
                selectinload(Entry.text_fields).selectinload(TextField.type),
                selectinload(Entry.datetime_fields).selectinload(DatetimeField.type),
            )
        ).scalars())
        result.tags = len(tags)
        result.entries = len(entries)
        result.fields = sum(len(entry.text_fields) + len(entry.datetime_fields) for entry in entries)

        output_db.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = connect_sqlite(str(output_db), check_same_thread=True)
        except sqlite3.OperationalError as exc:
            raise TagStudioInteropError(f"Could not open TagStudio export database: {output_db}") from exc
        connection.row_factory = sqlite3.Row
        try:
            _prepare_export_schema(connection)
            connection.execute("BEGIN IMMEDIATE")

            target_tags = {
                str(row["name"]).casefold(): int(row["id"])
                for row in connection.execute("SELECT id, name FROM tags")
            }
            target_tag_ids = {
                int(row[0]) for row in connection.execute("SELECT id FROM tags")
            }
            tag_map: dict[int, int] = {}
            for tag in tags:
                name = str(tag.name or "").strip()
                if not name:
                    result.skipped += 1
                    continue
                existing_id = target_tags.get(name.casefold())
                if existing_id is not None:
                    tag_map[tag.id] = existing_id
                    result.merged += 1
                    continue
                desired_id = tag.id if tag.id >= 0 and tag.id not in target_tag_ids else None
                values = (
                    name,
                    tag.shorthand,
                    tag.color_slug,
                    int(bool(tag.is_category)),
                    int(bool(tag.is_hidden)),
                    tag.icon,
                )
                if desired_id is not None:
                    connection.execute(
                        "INSERT INTO tags (id, name, shorthand, color_slug, is_category, is_hidden, icon) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (desired_id, *values),
                    )
                    target_id = desired_id
                    target_tag_ids.add(desired_id)
                else:
                    cursor = connection.execute(
                        "INSERT INTO tags (name, shorthand, color_slug, is_category, is_hidden, icon) "
                        "VALUES (?, ?, ?, ?, ?, ?)", values
                    )
                    target_id = int(cursor.lastrowid)
                    target_tag_ids.add(target_id)
                target_tags[name.casefold()] = target_id
                tag_map[tag.id] = target_id

            existing_aliases = {
                (int(row["tag_id"]), str(row["name"]))
                for row in connection.execute("SELECT tag_id, name FROM tag_aliases")
            }
            for tag in tags:
                target_id = tag_map.get(tag.id)
                if target_id is None:
                    continue
                for alias in tag.aliases:
                    alias_name = str(alias.name or "").strip()
                    if alias_name and (target_id, alias_name) not in existing_aliases:
                        connection.execute(
                            "INSERT INTO tag_aliases (name, tag_id) VALUES (?, ?)",
                            (alias_name, target_id),
                        )
                        existing_aliases.add((target_id, alias_name))

            existing_parents = {
                (int(row["parent_id"]), int(row["child_id"]))
                for row in connection.execute("SELECT parent_id, child_id FROM tag_parents")
            }
            for tag in tags:
                child_id = tag_map.get(tag.id)
                if child_id is None:
                    continue
                for parent in tag.parent_tags:
                    parent_id = tag_map.get(parent.id)
                    if parent_id is None or parent_id == child_id:
                        continue
                    relation = (parent_id, child_id)
                    if relation not in existing_parents:
                        connection.execute(
                            "INSERT INTO tag_parents (parent_id, child_id) VALUES (?, ?)", relation
                        )
                        existing_parents.add(relation)

            target_entries = {
                _path_key(Path(str(row["path"]))): int(row["id"])
                for row in connection.execute("SELECT id, path FROM entries")
            }
            target_entry_ids = {
                int(row[0]) for row in connection.execute("SELECT id FROM entries")
            }
            entry_map: dict[int, int] = {}
            for entry in entries:
                path = Path(entry.path)
                key = _path_key(path)
                target_id = target_entries.get(key)
                if target_id is not None:
                    entry_map[entry.id] = target_id
                    result.merged += 1
                    continue
                desired_id = entry.id if entry.id >= 0 and entry.id not in target_entry_ids else None
                values = (
                    str(path.as_posix()),
                    path.name,
                    path.suffix.lstrip(".").lower(),
                    _iso_datetime(entry.date_created),
                    _iso_datetime(entry.date_modified),
                    _iso_datetime(entry.date_added),
                )
                if desired_id is not None:
                    connection.execute(
                        "INSERT INTO entries "
                        "(id, path, filename, suffix, date_created, date_modified, date_added) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (desired_id, *values),
                    )
                    target_id = desired_id
                    target_entry_ids.add(desired_id)
                else:
                    cursor = connection.execute(
                        "INSERT INTO entries "
                        "(path, filename, suffix, date_created, date_modified, date_added) "
                        "VALUES (?, ?, ?, ?, ?, ?)", values
                    )
                    target_id = int(cursor.lastrowid)
                    target_entry_ids.add(target_id)
                target_entries[key] = target_id
                entry_map[entry.id] = target_id

            existing_tag_entries = {
                (int(row["tag_id"]), int(row["entry_id"]))
                for row in connection.execute("SELECT tag_id, entry_id FROM tag_entries")
            }
            for entry in entries:
                target_entry_id = entry_map.get(entry.id)
                if target_entry_id is None:
                    continue
                for tag in entry.tags:
                    target_tag_id = tag_map.get(tag.id)
                    if target_tag_id is None:
                        continue
                    relation = (target_tag_id, target_entry_id)
                    if relation not in existing_tag_entries:
                        connection.execute(
                            "INSERT INTO tag_entries (tag_id, entry_id) VALUES (?, ?)", relation
                        )
                        existing_tag_entries.add(relation)

            existing_text_fields = {
                (int(row["entry_id"]), str(row["name"]), row["value"])
                for row in connection.execute("SELECT entry_id, name, value FROM text_fields")
            }
            existing_datetime_fields = {
                (int(row["entry_id"]), str(row["name"]), row["value"])
                for row in connection.execute("SELECT entry_id, name, value FROM datetime_fields")
            }
            for entry in entries:
                target_entry_id = entry_map.get(entry.id)
                if target_entry_id is None:
                    continue
                for text_field in entry.text_fields:
                    name = text_field.type.name if text_field.type else text_field.type_key
                    value = text_field.value
                    key = (target_entry_id, name, value)
                    if key not in existing_text_fields:
                        connection.execute(
                            "INSERT INTO text_fields (name, entry_id, value, is_multiline) VALUES (?, ?, ?, ?)",
                            (name, target_entry_id, value, int(text_field.type and text_field.type.type == FieldTypeEnum.TEXT_BOX)),
                        )
                        existing_text_fields.add(key)
                for datetime_field in entry.datetime_fields:
                    name = datetime_field.type.name if datetime_field.type else datetime_field.type_key
                    value = datetime_field.value
                    key = (target_entry_id, name, value)
                    if key not in existing_datetime_fields:
                        connection.execute(
                            "INSERT INTO datetime_fields (name, entry_id, value) VALUES (?, ?, ?)",
                            (name, target_entry_id, value),
                        )
                        existing_datetime_fields.add(key)

            connection.execute(
                "INSERT INTO versions (key, value) VALUES ('INITIAL', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = max(value, excluded.value)",
                (TAGSTUDIO_DB_VERSION,),
            )
            connection.execute(
                "INSERT INTO versions (key, value) VALUES ('CURRENT', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = max(value, excluded.value)",
                (TAGSTUDIO_DB_VERSION,),
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            if isinstance(exc, TagStudioInteropError):
                raise
            raise TagStudioInteropError(f"TagStudio export failed for {output_db}") from exc
        finally:
            connection.close()

        if copy_thumbnails:
            source_thumbs = source_root / ".unifile" / "tagstudio-thumbs"
            if not source_thumbs.is_dir():
                source_thumbs = _tagstudio_thumbs(source_root) or source_thumbs
            destination_thumbs = output_root / TAGSTUDIO_FOLDER_NAME / TAGSTUDIO_THUMB_CACHE_NAME
            copied, skipped = _copy_thumbnail_tree(source_thumbs, destination_thumbs)
            result.thumbnails = copied
            result.skipped += skipped
    finally:
        library.close()

    return result


__all__ = [
    "TagStudioInteropError",
    "TagStudioResult",
    "export_tagstudio",
    "import_tagstudio",
    "inspect_tagstudio",
    "locate_tagstudio_database",
]
