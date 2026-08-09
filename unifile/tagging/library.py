"""UniFile — Tag Library Manager (core API for tag operations)."""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime as dt
from pathlib import Path
from typing import Any, cast

from sqlalchemy import and_, delete, false, func, or_, select, text, true
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

# Sentinel for "not passed" (distinct from None, which means "clear the field")
_UNSET = object()

from unifile.field_schemas import (  # noqa: E402  -- sentinel above
    normalize_field_type,
    normalize_schema,
    validate_field_value,
)
from unifile.tagging.db import make_engine, make_tables  # noqa: E402  -- sentinel above
from unifile.tagging.models import (  # noqa: E402
    DEFAULT_FIELDS,
    BooleanField,
    DatetimeField,
    Entry,
    EntryColor,
    EntryGroup,
    EntryGroupMember,
    FieldTypeEnum,
    Folder,
    Tag,
    TagAlias,
    TagEntry,
    TagImplication,
    TagParent,
    TagSibling,
    TextField,
    ValueType,
)

logger = logging.getLogger(__name__)

_FTS5_SPECIAL = re.compile(r'[*():\-\^]')
_FTS5_KEYWORDS = re.compile(r'\b(AND|OR|NOT|NEAR)\b')
MAX_SEARCH_PAGE_SIZE = 1000


class SearchError(RuntimeError):
    """Base class for deterministic, user-visible search failures."""


class SearchIndexError(SearchError):
    """The configured FTS/index path is unavailable or corrupt."""


class SearchCancelled(SearchError):
    """A search was interrupted by its caller."""


@dataclass(frozen=True)
class SearchPage:
    """One bounded search page plus stable count and planner diagnostics."""

    entries: list[Any]
    total: int
    offset: int
    limit: int
    index_mode: str
    elapsed_ms: float


def _sanitize_fts(query: str) -> str:
    """Escape FTS5 special characters/operators and wrap in phrase quotes."""
    q = _FTS5_SPECIAL.sub(' ', query)
    q = _FTS5_KEYWORDS.sub(' ', q)
    q = q.replace('"', '""')
    return f'"{q.strip()}"*'


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcard characters."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

DB_FILENAME = "unifile_tags.sqlite"


class TagLibrary:
    """Manages a tag-based file library stored in SQLite via SQLAlchemy."""

    def __init__(self, library_dir: str | None = None):
        self.library_dir = library_dir
        # These values are initialized by ``open``.  Keeping the closed-state
        # sentinel explicit lets the rest of the API use SQLAlchemy's typed
        # Session/Engine interfaces without weakening every query to Any.
        self.engine: Engine = cast(Engine, None)
        self._session: Session = cast(Session, None)
        self._folder: Folder = cast(Folder, None)
        self.last_field_error: str | None = None
        self.last_search_diagnostic: dict[str, Any] = {}

    @property
    def is_open(self) -> bool:
        return self.engine is not None

    def open(self, library_dir: str | None = None) -> bool:
        if library_dir:
            self.library_dir = library_dir
        if not self.library_dir:
            return False

        db_dir = os.path.join(self.library_dir, ".unifile")
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, DB_FILENAME)

        self.engine = make_engine(db_path)
        make_tables(self.engine)
        self._session = Session(self.engine)

        # Ensure default field types exist
        self._init_default_fields()

        # Ensure folder record exists
        self._folder = self._get_or_create_folder(self.library_dir)

        logger.info("Tag library opened: %s", db_path)
        return True

    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = cast(Session, None)
        if self.engine:
            self.engine.dispose()
            self.engine = cast(Engine, None)
        self._folder = cast(Folder, None)

    def _init_default_fields(self) -> None:
        for field_def in DEFAULT_FIELDS:
            existing = self._session.get(ValueType, field_def["key"])
            if not existing:
                vt = ValueType(
                    key=field_def["key"],
                    name=field_def["name"],
                    type=field_def["type"],
                    is_default=field_def["is_default"],
                    position=field_def["position"],
                )
                self._session.add(vt)
        self._session.commit()

    def _get_or_create_folder(self, path: str) -> Folder:
        p = Path(os.path.abspath(path))
        normalized = os.path.normcase(str(p))
        folder = next(
            (
                candidate
                for candidate in self._session.execute(select(Folder)).scalars().all()
                if os.path.normcase(os.path.abspath(str(candidate.path))) == normalized
            ),
            None,
        )
        if not folder:
            folder = Folder(path=p, uuid=str(uuid.uuid4()))
            self._session.add(folder)
            self._session.commit()
        return folder

    def _folder_for_path(self, path: Path) -> Folder:
        """Choose the most specific configured root containing *path*."""
        absolute_path = os.path.abspath(str(path))
        candidates = []
        for folder in self._session.execute(select(Folder)).scalars().all():
            root_path = os.path.abspath(str(folder.path))
            try:
                relative = os.path.relpath(absolute_path, root_path)
            except (OSError, ValueError):
                continue
            if relative == os.curdir or (
                relative != os.pardir and not relative.startswith(os.pardir + os.sep)
            ):
                candidates.append((len(os.path.normcase(root_path)), folder))
        if candidates:
            return max(candidates, key=lambda pair: pair[0])[1]
        return self._folder

    # ── Tag CRUD ──────────────────────────────────────────────────────────────

    def add_tag(self, name: str, shorthand: str | None = None,
                color_slug: str | None = None, is_category: bool = False,
                parent_id: int | None = None, namespace: str | None = None,
                description: str | None = None) -> Tag | None:
        existing = self._session.execute(
            select(Tag).where(func.lower(Tag.name) == name.lower())
        ).scalar_one_or_none()
        if existing:
            return existing

        tag = Tag(name=name, shorthand=shorthand, color_slug=color_slug,
                  is_category=is_category, namespace=namespace,
                  description=description)
        self._session.add(tag)
        self._session.flush()

        if parent_id is not None:
            parent = self._session.get(Tag, parent_id)
            if parent:
                tag.parent_tags.add(parent)

        self._session.commit()
        return tag

    def get_tag(self, tag_id: int) -> Tag | None:
        return self._session.get(Tag, tag_id)

    def get_tag_by_name(self, name: str) -> Tag | None:
        return self._session.execute(
            select(Tag).where(func.lower(Tag.name) == name.lower())
        ).scalar_one_or_none()

    def search_tags(self, query: str, limit: int = 20) -> list[Tag]:
        try:
            rows = self._session.execute(
                text("SELECT rowid FROM tags_fts WHERE name MATCH :q LIMIT :lim"),
                {"q": _sanitize_fts(query), "lim": limit},
            ).fetchall()
            if rows:
                ids = [r[0] for r in rows]
                return list(self._session.execute(
                    select(Tag).where(Tag.id.in_(ids))
                ).scalars().all())
        except Exception:
            pass
        escaped = _escape_like(query)
        return list(self._session.execute(
            select(Tag).where(Tag.name.ilike(f"%{escaped}%", escape='\\'))
            .limit(limit)
        ).scalars().all())

    def get_all_tags(self) -> list[Tag]:
        return list(self._session.execute(
            select(Tag).order_by(Tag.name)
        ).scalars().all())

    def get_category_tags(self) -> list[Tag]:
        return list(self._session.execute(
            select(Tag).where(Tag.is_category.is_(True)).order_by(Tag.name)
        ).scalars().all())

    def update_tag(self, tag_id: int, name: str | None = None,
                   color_slug: str | None = None,
                   is_category: bool | None = None,
                   namespace: Any = _UNSET,
                   is_hidden: bool | None = None,
                   description: Any = _UNSET,
                   icon: Any = _UNSET) -> bool:
        tag = self._session.get(Tag, tag_id)
        if not tag:
            return False
        if name is not None:
            tag.name = name
        if color_slug is not None:
            tag.color_slug = color_slug
        if is_category is not None:
            tag.is_category = is_category
        # Nullable fields: use sentinel so None means "clear the value"
        if namespace is not _UNSET:
            tag.namespace = namespace
        if is_hidden is not None:
            tag.is_hidden = is_hidden
        if description is not _UNSET:
            tag.description = description
        if icon is not _UNSET:
            tag.icon = icon
        self._session.commit()
        return True

    def delete_tag(self, tag_id: int) -> bool:
        tag = self._session.get(Tag, tag_id)
        if not tag:
            return False
        # Remove graph and junction rows explicitly so deletion remains safe
        # when SQLite foreign-key enforcement is enabled by the host process.
        self._session.execute(delete(TagImplication).where(or_(
            TagImplication.antecedent_id == tag_id,
            TagImplication.consequent_id == tag_id,
        )))
        self._session.execute(delete(TagSibling).where(or_(
            TagSibling.bad_tag_id == tag_id,
            TagSibling.good_tag_id == tag_id,
        )))
        self._session.execute(delete(TagParent).where(or_(
            TagParent.child_id == tag_id,
            TagParent.parent_id == tag_id,
        )))
        self._session.execute(delete(TagEntry).where(TagEntry.tag_id == tag_id))
        self._session.execute(delete(TagAlias).where(TagAlias.tag_id == tag_id))
        self._session.delete(tag)
        self._session.commit()
        return True

    def add_alias(self, tag_id: int, alias_name: str) -> bool:
        tag = self._session.get(Tag, tag_id)
        if not tag:
            return False
        alias = TagAlias(name=alias_name, tag_id=tag_id)
        self._session.add(alias)
        self._session.commit()
        return True

    def add_parent_tag(self, child_id: int, parent_id: int) -> bool:
        child = self._session.get(Tag, child_id)
        parent = self._session.get(Tag, parent_id)
        if not child or not parent:
            return False
        child.parent_tags.add(parent)
        self._session.commit()
        return True

    def remove_parent_tag(self, child_id: int, parent_id: int) -> bool:
        child = self._session.get(Tag, child_id)
        parent = self._session.get(Tag, parent_id)
        if not child or not parent:
            return False
        child.parent_tags.discard(parent)
        self._session.commit()
        return True

    # ── Tag implication and sibling rules ─────────────────────────────────

    def get_implied_tag_ids(self, tag_id: int) -> set[int]:
        """Return *tag_id* and every consequent reachable from it."""
        implied = {tag_id}
        queue = [tag_id]
        while queue:
            current = queue.pop()
            next_ids = self._session.execute(
                select(TagImplication.consequent_id).where(
                    TagImplication.antecedent_id == current
                )
            ).scalars().all()
            for next_id in next_ids:
                if next_id not in implied:
                    implied.add(next_id)
                    queue.append(next_id)
        return implied

    def get_tag_implication_ids(self, tag_id: int) -> set[int]:
        """Return every transitive consequent of a tag."""
        return self.get_implied_tag_ids(tag_id) - {tag_id}

    def get_direct_tag_implication_ids(self, tag_id: int) -> set[int]:
        """Return only the consequents directly configured for a tag."""
        return set(self._session.execute(
            select(TagImplication.consequent_id).where(
                TagImplication.antecedent_id == tag_id
            )
        ).scalars().all())

    def get_tags_implying(self, tag_id: int) -> set[int]:
        """Return tags whose implication chain reaches *tag_id*."""
        antecedents = {tag_id}
        queue = [tag_id]
        while queue:
            current = queue.pop()
            previous_ids = self._session.execute(
                select(TagImplication.antecedent_id).where(
                    TagImplication.consequent_id == current
                )
            ).scalars().all()
            for previous_id in previous_ids:
                if previous_id not in antecedents:
                    antecedents.add(previous_id)
                    queue.append(previous_id)
        antecedents.discard(tag_id)
        return antecedents

    def add_tag_implication(self, antecedent_id: int, consequent_id: int) -> bool:
        """Add a directed implication, rejecting self-links and graph cycles."""
        if antecedent_id == consequent_id:
            return False
        antecedent = self._session.get(Tag, antecedent_id)
        consequent = self._session.get(Tag, consequent_id)
        if not antecedent or not consequent:
            return False
        existing = self._session.execute(
            select(TagImplication).where(
                TagImplication.antecedent_id == antecedent_id,
                TagImplication.consequent_id == consequent_id,
            )
        ).scalar_one_or_none()
        if existing:
            return True
        if antecedent_id in self.get_implied_tag_ids(consequent_id):
            return False
        self._session.add(TagImplication(
            antecedent_id=antecedent_id,
            consequent_id=consequent_id,
        ))
        self._session.commit()
        return True

    def remove_tag_implication(self, antecedent_id: int, consequent_id: int) -> bool:
        result = self._session.execute(
            delete(TagImplication).where(
                TagImplication.antecedent_id == antecedent_id,
                TagImplication.consequent_id == consequent_id,
            )
        )
        self._session.commit()
        return bool(result.rowcount)

    def get_tag_sibling_ids(self, tag_id: int) -> set[int]:
        """Return all tags linked as symmetric siblings of *tag_id*."""
        rows = self._session.execute(
            select(TagSibling.bad_tag_id, TagSibling.good_tag_id).where(
                or_(
                    TagSibling.bad_tag_id == tag_id,
                    TagSibling.good_tag_id == tag_id,
                )
            )
        ).all()
        sibling_ids = set()
        for bad_id, good_id in rows:
            sibling_ids.add(good_id if bad_id == tag_id else bad_id)
        return sibling_ids

    def get_tag_siblings(self, tag_id: int) -> list[Tag]:
        sibling_ids = self.get_tag_sibling_ids(tag_id)
        if not sibling_ids:
            return []
        return list(self._session.execute(
            select(Tag).where(Tag.id.in_(sibling_ids)).order_by(Tag.name)
        ).scalars().all())

    def add_tag_sibling(self, first_id: int, second_id: int) -> bool:
        """Link two tags as symmetric sibling suggestions."""
        if first_id == second_id:
            return False
        first = self._session.get(Tag, first_id)
        second = self._session.get(Tag, second_id)
        if not first or not second:
            return False
        if second_id in self.get_tag_sibling_ids(first_id):
            return True
        self._session.add_all([
            TagSibling(bad_tag_id=first_id, good_tag_id=second_id),
            TagSibling(bad_tag_id=second_id, good_tag_id=first_id),
        ])
        self._session.commit()
        return True

    def remove_tag_sibling(self, first_id: int, second_id: int) -> bool:
        result = self._session.execute(
            delete(TagSibling).where(
                or_(
                    (TagSibling.bad_tag_id == first_id) &
                    (TagSibling.good_tag_id == second_id),
                    (TagSibling.bad_tag_id == second_id) &
                    (TagSibling.good_tag_id == first_id),
                )
            )
        )
        self._session.commit()
        return bool(result.rowcount)

    # ── Entry CRUD ────────────────────────────────────────────────────────────

    def add_entry(self, file_path: str) -> Entry | None:
        p = Path(file_path)
        existing = self._session.execute(
            select(Entry).where(Entry.path == p)
        ).scalar_one_or_none()
        if existing:
            return existing

        stat = p.stat() if p.exists() else None
        entry = Entry(
            path=p,
            folder=self._folder_for_path(p),
            filename=p.name,
            suffix=p.suffix.lstrip(".").lower(),
            date_created=dt.fromtimestamp(stat.st_ctime) if stat else None,
            date_modified=dt.fromtimestamp(stat.st_mtime) if stat else None,
            date_added=dt.now(),
        )
        self._session.add(entry)
        self._session.flush()
        self._replace_entry_colors(entry.id, p, commit=False)
        self._session.commit()
        return entry

    def add_entries_bulk(self, file_paths: list[str], batch_size: int = 200) -> int:
        count = 0
        for i in range(0, len(file_paths), batch_size):
            batch = file_paths[i:i + batch_size]
            batch_paths = [Path(fp) for fp in batch]
            # Fetch all already-present paths in one query (avoids N+1)
            existing_paths: set[Path] = set(
                self._session.execute(
                    select(Entry.path).where(Entry.path.in_(batch_paths))
                ).scalars().all()
            )
            new_entries = []
            for fp in batch:
                p = Path(fp)
                if p in existing_paths:
                    continue
                stat = p.stat() if p.exists() else None
                entry = Entry(
                    path=p,
                    folder=self._folder_for_path(p),
                    filename=p.name,
                    suffix=p.suffix.lstrip(".").lower(),
                    date_created=dt.fromtimestamp(stat.st_ctime) if stat else None,
                    date_modified=dt.fromtimestamp(stat.st_mtime) if stat else None,
                    date_added=dt.now(),
                )
                self._session.add(entry)
                new_entries.append((entry, p))
                count += 1
            self._session.flush()
            for entry, path in new_entries:
                self._replace_entry_colors(entry.id, path, commit=False)
            self._session.commit()
        return count

    def _replace_entry_colors(self, entry_id: int, file_path: Path, *, commit: bool = True) -> int:
        """Replace one entry's palette rows without failing the file import."""
        from unifile.color_extraction import extract_color_palette

        self._session.execute(delete(EntryColor).where(EntryColor.entry_id == entry_id))
        palette = extract_color_palette(file_path)
        if palette:
            self._session.add_all([
                EntryColor(
                    entry_id=entry_id,
                    color_name=color["name"],
                    hex_color=color["hex"],
                    weight=color["weight"],
                    rank=color["rank"],
                )
                for color in palette
            ])
        if commit:
            self._session.commit()
        return len(palette)

    def get_entry_colors(self, entry_id: int) -> list[EntryColor]:
        """Return an entry's palette ordered from most to least prominent."""
        return list(self._session.execute(
            select(EntryColor)
            .where(EntryColor.entry_id == entry_id)
            .order_by(EntryColor.rank, EntryColor.color_name)
        ).scalars().all())

    def reindex_colors(self, batch_size: int = 100) -> int:
        """Rebuild palette rows for existing image entries."""
        from unifile.color_extraction import IMAGE_EXTENSIONS

        entries = list(self._session.execute(
            select(Entry.id, Entry.path).order_by(Entry.id)
        ).all())
        indexed = 0
        size = max(1, int(batch_size))
        for offset in range(0, len(entries), size):
            for entry_id, path in entries[offset:offset + size]:
                count = self._replace_entry_colors(entry_id, Path(path), commit=False)
                if Path(path).suffix.lower() in IMAGE_EXTENSIONS and count:
                    indexed += 1
            self._session.commit()
        return indexed

    def get_entry(self, entry_id: int) -> Entry | None:
        return self._session.execute(
            select(Entry).options(joinedload(Entry.tags)).where(Entry.id == entry_id)
        ).unique().scalar_one_or_none()

    def get_entry_by_path(self, path: str) -> Entry | None:
        return self._session.execute(
            select(Entry).options(joinedload(Entry.tags)).where(Entry.path == Path(path))
        ).unique().scalar_one_or_none()

    def get_all_entries(self, limit: int = 1000, offset: int = 0) -> list[Entry]:
        return list(self._session.execute(
            select(Entry).options(joinedload(Entry.tags))
            .order_by(Entry.filename)
            .limit(limit).offset(offset)
        ).unique().scalars().all())

    def get_entry_count(self) -> int:
        result = self._session.execute(select(func.count(Entry.id)))
        return result.scalar() or 0

    def remove_entry(self, entry_id: int) -> bool:
        entry = self._session.get(Entry, entry_id)
        if not entry:
            return False
        self._session.execute(delete(EntryColor).where(EntryColor.entry_id == entry_id))
        # Delete every typed row because entry removal has no field key filter.
        for model in (TextField, DatetimeField, BooleanField):
            self._session.execute(delete(model).where(model.entry_id == entry_id))
        self._session.delete(entry)
        self._session.commit()
        return True

    # ── Tag ↔ Entry Operations ────────────────────────────────────────────────

    def add_tags_to_entry(self, entry_id: int, tag_ids: list[int]) -> bool:
        entry = self._session.execute(
            select(Entry).options(joinedload(Entry.tags)).where(Entry.id == entry_id)
        ).unique().scalar_one_or_none()
        if not entry:
            return False
        expanded_ids = set()
        for tid in tag_ids:
            if not self._session.get(Tag, tid):
                continue
            sibling_ids = self.get_tag_sibling_ids(tid)
            for candidate_id in {tid, *sibling_ids}:
                expanded_ids.update(self.get_implied_tag_ids(candidate_id))
        for tid in expanded_ids:
            tag = self._session.get(Tag, tid)
            if tag:
                entry.tags.add(tag)
        self._session.commit()
        return True

    def remove_tags_from_entry(self, entry_id: int, tag_ids: list[int]) -> bool:
        entry = self._session.execute(
            select(Entry).options(joinedload(Entry.tags)).where(Entry.id == entry_id)
        ).unique().scalar_one_or_none()
        if not entry:
            return False
        for tid in tag_ids:
            tag = self._session.get(Tag, tid)
            if tag:
                entry.tags.discard(tag)
        self._session.commit()
        return True

    def get_entries_by_tag(self, tag_id: int) -> list[Entry]:
        return list(self._session.execute(
            select(Entry).join(Entry.tags).where(Tag.id == tag_id)
            .order_by(Entry.filename)
        ).scalars().all())

    def get_tag_entry_counts(self) -> dict[int, int]:
        """Return {tag_id: entry_count} for all tags in one query."""
        from unifile.tagging.models import TagEntry as _TE
        rows = self._session.execute(
            select(_TE.tag_id, func.count(_TE.entry_id))
            .group_by(_TE.tag_id)
        ).all()
        return {tag_id: count for tag_id, count in rows}

    def get_untagged_entries(self) -> list[Entry]:
        subq = select(TagEntry.entry_id)
        return list(self._session.execute(
            select(Entry).where(~Entry.id.in_(subq)).order_by(Entry.filename)
        ).scalars().all())

    # ── Field Schemas and Entry Field Operations ──────────────────────────────

    @staticmethod
    def _schema_for_value_type(value_type: ValueType) -> dict[str, Any]:
        if not value_type.schema_json:
            return {}
        try:
            value = json.loads(value_type.schema_json)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _field_schema_record(cls, value_type: ValueType) -> dict[str, Any]:
        schema = cls._schema_for_value_type(value_type)
        record = {
            "key": value_type.key,
            "name": value_type.name,
            "type": getattr(value_type.type, "value", str(value_type.type)),
            "is_default": bool(value_type.is_default),
            "position": value_type.position,
            "schema": schema,
        }
        for key in ("options", "min", "max"):
            if key in schema:
                record[key] = schema[key]
        return record

    def get_field_schemas(self) -> list[dict[str, Any]]:
        """Return this library's ordered built-in and custom field definitions."""
        value_types = self._session.execute(
            select(ValueType).order_by(ValueType.position, ValueType.name)
        ).scalars().all()
        return [self._field_schema_record(value_type) for value_type in value_types]

    def get_field_schema(self, field_key: str) -> dict[str, Any] | None:
        value_type = self._session.get(ValueType, field_key)
        return self._field_schema_record(value_type) if value_type else None

    @staticmethod
    def _slug_field_key(value: str) -> str:
        import re

        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "custom_field"

    def add_field_schema(
        self,
        name: str,
        field_type: FieldTypeEnum | str,
        schema: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a custom field definition scoped to this library database."""
        self.last_field_error = None
        clean_name = str(name or "").strip()
        if not clean_name:
            self.last_field_error = "Field name is required"
            return None
        normalized_type = normalize_field_type(field_type)
        normalized_schema, error = normalize_schema(normalized_type or "", schema)
        if error:
            self.last_field_error = error
            return None
        duplicate_name = self._session.execute(
            select(ValueType).where(func.lower(ValueType.name) == clean_name.casefold())
        ).scalar_one_or_none()
        if duplicate_name:
            self.last_field_error = "A field with that name already exists"
            return None

        base_key = self._slug_field_key(str(key or clean_name))
        candidate = base_key
        suffix = 2
        while self._session.get(ValueType, candidate):
            if key:
                self.last_field_error = "A field with that key already exists"
                return None
            candidate = f"{base_key}_{suffix}"
            suffix += 1

        max_position = self._session.execute(select(func.max(ValueType.position))).scalar()
        value_type = ValueType(
            key=candidate,
            name=clean_name,
            type=normalized_type,
            is_default=False,
            position=(int(max_position) + 1) if max_position is not None else 0,
            schema_json=json.dumps(normalized_schema or {}, sort_keys=True),
        )
        self._session.add(value_type)
        self._session.commit()
        return self._field_schema_record(value_type)

    def update_field_schema(
        self,
        field_key: str,
        *,
        name: str | None = None,
        field_type: FieldTypeEnum | str | None = None,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Update a custom definition; built-in field contracts remain immutable."""
        self.last_field_error = None
        value_type = self._session.get(ValueType, field_key)
        if not value_type:
            self.last_field_error = "Field was not found"
            return None
        if value_type.is_default:
            self.last_field_error = "Built-in fields cannot be changed"
            return None
        clean_name = value_type.name if name is None else str(name).strip()
        if not clean_name:
            self.last_field_error = "Field name is required"
            return None
        duplicate = self._session.execute(
            select(ValueType).where(
                func.lower(ValueType.name) == clean_name.casefold(),
                ValueType.key != field_key,
            )
        ).scalar_one_or_none()
        if duplicate:
            self.last_field_error = "A field with that name already exists"
            return None
        normalized_type = normalize_field_type(field_type or value_type.type)
        effective_schema = schema
        if effective_schema is None:
            effective_schema = self._schema_for_value_type(value_type)
        normalized_schema, error = normalize_schema(normalized_type or "", effective_schema)
        if error:
            self.last_field_error = error
            return None
        old_type = normalize_field_type(value_type.type)
        value_type.name = clean_name
        value_type.type = normalized_type
        value_type.schema_json = json.dumps(normalized_schema or {}, sort_keys=True)
        if old_type is not normalized_type:
            self._delete_entry_field_rows(self._session, None, field_key)
        self._session.commit()
        return self._field_schema_record(value_type)

    def delete_field_schema(self, field_key: str) -> bool:
        """Delete a custom definition and all values stored under it."""
        self.last_field_error = None
        value_type = self._session.get(ValueType, field_key)
        if not value_type:
            self.last_field_error = "Field was not found"
            return False
        if value_type.is_default:
            self.last_field_error = "Built-in fields cannot be deleted"
            return False
        self._delete_entry_field_rows(self._session, None, field_key)
        self._session.delete(value_type)
        self._session.commit()
        return True

    remove_field_schema = delete_field_schema

    def validate_field_value(
        self, field_key: str, value: Any
    ) -> tuple[str | None, str | None]:
        """Validate one value using the schema stored for this library."""
        self.last_field_error = None
        value_type = self._session.get(ValueType, field_key)
        if not value_type:
            self.last_field_error = "Field was not found"
            return None, self.last_field_error
        normalized, error = validate_field_value(
            value_type.type,
            value,
            self._schema_for_value_type(value_type),
        )
        self.last_field_error = error
        return normalized, error

    @staticmethod
    def _delete_entry_field_rows(
        session: Session, entry_id: int | None, field_key: str
    ) -> None:
        for model in (TextField, DatetimeField, BooleanField):
            conditions = [model.type_key == field_key]
            if entry_id is not None:
                conditions.append(model.entry_id == entry_id)
            session.execute(delete(model).where(*conditions))

    @classmethod
    def _set_entry_field_in_session(
        cls, session: Session, entry_id: int, field_key: str, value: Any
    ) -> tuple[bool, str | None]:
        entry = session.get(Entry, entry_id)
        value_type = session.get(ValueType, field_key)
        if not entry or not value_type:
            return False, "Entry or field was not found"
        if value is None or (isinstance(value, str) and not value.strip()):
            cls._delete_entry_field_rows(session, entry_id, field_key)
            session.commit()
            return True, None
        normalized, error = validate_field_value(
            value_type.type,
            value,
            cls._schema_for_value_type(value_type),
        )
        if error:
            return False, error
        assert normalized is not None
        cls._delete_entry_field_rows(session, entry_id, field_key)
        field_model = {
            FieldTypeEnum.DATETIME: DatetimeField,
            FieldTypeEnum.BOOLEAN: BooleanField,
        }.get(normalize_field_type(value_type.type), TextField)
        stored_value: Any = normalized
        if field_model is BooleanField:
            stored_value = normalized == "true"
        session.add(field_model(
            type_key=field_key,
            entry_id=entry_id,
            value=stored_value,
            position=value_type.position,
        ))
        session.commit()
        return True, None

    def set_entry_field(self, entry_id: int, field_key: str, value: Any) -> bool:
        """Set, validate, or clear a typed entry field."""
        self.last_field_error = None
        success, error = self._set_entry_field_in_session(
            self._session, entry_id, field_key, value)
        self.last_field_error = error
        return success

    @staticmethod
    def set_entry_field_with_session(
        session: Session, entry_id: int, field_key: str, value: Any
    ) -> bool:
        """Thread-safe variant: caller provides an explicit SQLAlchemy session."""
        success, _ = TagLibrary._set_entry_field_in_session(
            session, entry_id, field_key, value)
        return success

    def clear_entry_field(self, entry_id: int, field_key: str) -> bool:
        """Remove all typed storage rows for an entry field."""
        self.last_field_error = None
        if not self._session.get(Entry, entry_id) or not self._session.get(ValueType, field_key):
            self.last_field_error = "Entry or field was not found"
            return False
        self._delete_entry_field_rows(self._session, entry_id, field_key)
        self._session.commit()
        return True

    def get_entry_fields(self, entry_id: int) -> dict[str, str]:
        fields: dict[str, str] = {}
        for field in self._session.execute(
            select(TextField).where(TextField.entry_id == entry_id)
        ).scalars().all():
            fields[field.type_key] = field.value or ""
        for field in self._session.execute(
            select(DatetimeField).where(DatetimeField.entry_id == entry_id)
        ).scalars().all():
            fields[field.type_key] = field.value or ""
        for field in self._session.execute(
            select(BooleanField).where(BooleanField.entry_id == entry_id)
        ).scalars().all():
            fields[field.type_key] = "true" if field.value else "false"
        return fields

    # ── Rating ────────────────────────────────────────────────────────────────

    def set_entry_rating(self, entry_id: int, rating: int) -> bool:
        """Set 0-5 star rating. Returns False if entry not found."""
        entry = self._session.get(Entry, entry_id)
        if not entry:
            return False
        entry.rating = max(0, min(5, rating))
        self._session.commit()
        return True

    def get_entries_by_rating(self, min_rating: int = 1) -> list[Entry]:
        """Return entries with rating >= min_rating."""
        return list(self._session.execute(
            select(Entry).where(Entry.rating >= min_rating)
            .order_by(Entry.rating.desc(), Entry.filename)
        ).scalars().all())

    # ── Inbox / Archive ───────────────────────────────────────────────────────

    def set_entry_inbox(self, entry_id: int, is_inbox: bool) -> bool:
        """Move entry to inbox (True) or archive (False)."""
        entry = self._session.get(Entry, entry_id)
        if not entry:
            return False
        entry.is_inbox = is_inbox
        self._session.commit()
        return True

    def get_inbox_entries(self, limit: int = 1000) -> list[Entry]:
        """Return entries where is_inbox = True."""
        return list(self._session.execute(
            select(Entry).where(Entry.is_inbox.is_(True))
            .order_by(Entry.filename).limit(limit)
        ).scalars().all())

    def get_archived_entries(self, limit: int = 1000) -> list[Entry]:
        """Return entries where is_inbox = False."""
        return list(self._session.execute(
            select(Entry).where(Entry.is_inbox.is_(False))
            .order_by(Entry.filename).limit(limit)
        ).scalars().all())

    # ── Source URL ────────────────────────────────────────────────────────────

    def set_entry_source_url(self, entry_id: int, url: str) -> bool:
        """Store the source URL for an entry."""
        entry = self._session.get(Entry, entry_id)
        if not entry:
            return False
        entry.source_url = url
        self._session.commit()
        return True

    # ── Cached Media Properties ───────────────────────────────────────────────

    def update_entry_media_props(self, entry_id: int, width: int | None = None,
                                  height: int | None = None, duration: float | None = None,
                                  word_count: int | None = None) -> bool:
        """Update cached media properties for an entry."""
        entry = self._session.get(Entry, entry_id)
        if not entry:
            return False
        if width is not None:
            entry.media_width = width
        if height is not None:
            entry.media_height = height
        if duration is not None:
            entry.media_duration = duration
        if word_count is not None:
            entry.word_count = word_count
        self._session.commit()
        return True

    # ── Broken-Link Scan ──────────────────────────────────────────────────────

    def scan_broken_links(self, batch_size: int = 1000) -> list[Entry]:
        """Return entries whose path no longer exists on disk.

        Uses paginated queries to avoid loading the entire library into memory.
        """
        broken: list[Entry] = []
        offset = 0
        while True:
            batch = list(self._session.execute(
                select(Entry).order_by(Entry.id)
                .limit(batch_size).offset(offset)
            ).scalars().all())
            if not batch:
                break
            for e in batch:
                if not Path(e.path).exists():
                    broken.append(e)
            offset += batch_size
            if len(batch) < batch_size:
                break
        return broken

    def relink_entry(self, entry_id: int, new_path: str) -> bool:
        """Update entry path to new_path (for relinking moved files)."""
        entry = self._session.get(Entry, entry_id)
        if not entry:
            return False
        p = Path(new_path)
        entry.path = p
        entry.folder = self._folder_for_path(p)
        entry.filename = p.name
        entry.suffix = p.suffix.lstrip(".").lower()
        self._session.commit()
        return True

    # ── Tag Namespace ─────────────────────────────────────────────────────────

    def get_tags_by_namespace(self, namespace: str) -> list[Tag]:
        """Return all tags with the given namespace."""
        return list(self._session.execute(
            select(Tag).where(Tag.namespace == namespace).order_by(Tag.name)
        ).scalars().all())

    def get_all_namespaces(self) -> list[str]:
        """Return sorted list of distinct tag namespaces (excluding None)."""
        rows = self._session.execute(
            select(Tag.namespace).where(Tag.namespace.is_not(None)).distinct()
        ).scalars().all()
        return sorted(r for r in rows if r)

    # ── Tag Merge ─────────────────────────────────────────────────────────────

    def merge_tags(self, source_id: int, target_id: int) -> bool:
        """Merge source tag into target: re-point all entries, then delete source."""
        source = self._session.get(Tag, source_id)
        target = self._session.get(Tag, target_id)
        if not source or not target:
            return False
        entries = self._session.execute(
            select(Entry).join(Entry.tags).where(Tag.id == source_id)
        ).unique().scalars().all()
        for entry in entries:
            entry.tags.discard(source)
            if target not in entry.tags:
                entry.tags.add(target)
        self._session.flush()
        self._session.delete(source)
        self._session.commit()
        return True

    # ── Entry Groups ──────────────────────────────────────────────────────────

    def create_entry_group(self, name: str, color_slug: str | None = None) -> EntryGroup:
        """Create a new entry group."""
        group = EntryGroup(name=name, color_slug=color_slug, created_at=dt.now())
        self._session.add(group)
        self._session.commit()
        return group

    def get_all_groups(self) -> list[EntryGroup]:
        """Return all entry groups."""
        return list(self._session.execute(
            select(EntryGroup).order_by(EntryGroup.name)
        ).scalars().all())

    def get_entry_group(self, group_id: int) -> EntryGroup | None:
        """Return one collection definition by ID."""
        return self._session.get(EntryGroup, group_id)

    def add_entries_to_group(self, group_id: int, entry_ids: list[int]) -> bool:
        """Add entries to a group (bulk, avoids N+1)."""
        group = self._session.get(EntryGroup, group_id)
        if not group:
            return False
        existing_ids = set(self._session.execute(
            select(EntryGroupMember.entry_id).where(
                EntryGroupMember.group_id == group_id,
                EntryGroupMember.entry_id.in_(entry_ids),
            )
        ).scalars().all())
        new_members = [
            EntryGroupMember(group_id=group_id, entry_id=eid)
            for eid in entry_ids if eid not in existing_ids
        ]
        if new_members:
            self._session.add_all(new_members)
        self._session.commit()
        return True

    def remove_entries_from_group(self, group_id: int, entry_ids: list[int]) -> bool:
        """Remove entries from a group (bulk delete)."""
        group = self._session.get(EntryGroup, group_id)
        if not group:
            return False
        self._session.execute(
            delete(EntryGroupMember).where(
                EntryGroupMember.group_id == group_id,
                EntryGroupMember.entry_id.in_(entry_ids),
            )
        )
        self._session.commit()
        return True

    def get_group_entries(self, group_id: int) -> list[Entry]:
        """Return all entries in a group (single JOIN query)."""
        return list(self._session.execute(
            select(Entry)
            .join(EntryGroupMember, EntryGroupMember.entry_id == Entry.id)
            .where(EntryGroupMember.group_id == group_id)
            .order_by(Entry.filename)
        ).scalars().all())

    def delete_entry_group(self, group_id: int) -> bool:
        """Delete a group (bulk member removal, not the entries themselves)."""
        group = self._session.get(EntryGroup, group_id)
        if not group:
            return False
        self._session.execute(
            delete(EntryGroupMember).where(EntryGroupMember.group_id == group_id)
        )
        self._session.delete(group)
        self._session.commit()
        return True

    def export_entry_group(self, group_id: int, destination: str,
                           mode: str = 'zip') -> dict[str, Any]:
        """Export group members without moving or copying source files.

        ``mode='zip'`` creates a new archive with collision-safe basenames.
        ``mode='symlink'`` creates a folder of Windows/ POSIX symlinks and
        reports privilege failures per item instead of silently copying data.
        """
        group = self._session.get(EntryGroup, group_id)
        if not group:
            return {'exported': 0, 'skipped': 0, 'failed': 1,
                    'path': destination, 'error': 'group not found'}
        entries = self.get_group_entries(group_id)
        mode = mode.lower().strip()
        if mode not in {'zip', 'symlink'}:
            return {'exported': 0, 'skipped': 0, 'failed': 1,
                    'path': destination, 'error': 'unsupported export mode'}

        destination_path = Path(destination)
        if mode == 'zip':
            if destination_path.exists() and destination_path.is_dir():
                destination_path = destination_path / f'{group.name}.zip'
            if destination_path.suffix.lower() != '.zip':
                destination_path = destination_path.with_suffix('.zip')
            try:
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                archive = zipfile.ZipFile(
                    destination_path, mode='x', compression=zipfile.ZIP_DEFLATED)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                return {'exported': 0, 'skipped': 0, 'failed': 1,
                        'path': str(destination_path), 'error': str(exc)}
            names = set()
            exported = skipped = 0
            with archive:
                for entry in entries:
                    source = Path(entry.path)
                    if not source.is_file():
                        skipped += 1
                        continue
                    arcname = source.name
                    stem, suffix = source.stem, source.suffix
                    counter = 2
                    while arcname in names:
                        arcname = f'{stem} ({counter}){suffix}'
                        counter += 1
                    names.add(arcname)
                    try:
                        archive.write(source, arcname=arcname)
                        exported += 1
                    except OSError:
                        skipped += 1
            return {'exported': exported, 'skipped': skipped, 'failed': 0,
                    'path': str(destination_path)}

        try:
            destination_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {'exported': 0, 'skipped': 0, 'failed': 1,
                    'path': str(destination_path), 'error': str(exc)}
        names = set()
        exported = skipped = failed = 0
        for entry in entries:
            source = Path(entry.path)
            if not source.is_file():
                skipped += 1
                continue
            link_name = source.name
            stem, suffix = source.stem, source.suffix
            counter = 2
            while link_name in names or (destination_path / link_name).exists():
                link_name = f'{stem} ({counter}){suffix}'
                counter += 1
            names.add(link_name)
            try:
                os.symlink(str(source), str(destination_path / link_name),
                           target_is_directory=False)
                exported += 1
            except OSError:
                failed += 1
        return {'exported': exported, 'skipped': skipped, 'failed': failed,
                'path': str(destination_path)}

    # ── Multiple Library Roots ────────────────────────────────────────────────

    def add_root(self, path: str) -> bool:
        """Add an additional root folder to this library."""
        if not str(path).strip():
            return False
        p = Path(os.path.abspath(path))
        normalized = os.path.normcase(str(p))
        existing = next(
            (
                folder
                for folder in self._session.execute(select(Folder)).scalars().all()
                if os.path.normcase(os.path.abspath(str(folder.path))) == normalized
            ),
            None,
        )
        if existing:
            return True
        folder = Folder(path=p, uuid=str(uuid.uuid4()))
        self._session.add(folder)
        self._session.flush()
        for entry in self._session.execute(select(Entry)).scalars().all():
            entry.folder = self._folder_for_path(Path(entry.path))
        self._session.commit()
        return True

    def get_roots(self) -> list[str]:
        """Return list of all root folder paths in this library."""
        folders = self._session.execute(select(Folder)).scalars().all()
        return [str(f.path) for f in folders]

    def get_root_statuses(self) -> list[dict[str, Any]]:
        """Return root health, writability, and indexed-entry counts."""
        statuses = []
        for folder in self._session.execute(select(Folder).order_by(Folder.path)).scalars().all():
            path = Path(folder.path)
            online = path.is_dir()
            if not online:
                state = 'offline'
            elif not os.access(path, os.W_OK):
                state = 'read-only'
            else:
                state = 'online'
            count = self._session.execute(
                select(func.count(Entry.id)).where(Entry.folder_id == folder.id)
            ).scalar() or 0
            statuses.append({
                'id': folder.id,
                'path': str(path),
                'state': state,
                'online': online,
                'read_only': state == 'read-only',
                'is_database_root': bool(self._folder and self._folder.id == folder.id),
                'entry_count': count,
            })
        return statuses

    def remove_root(self, root_id: int) -> bool:
        """Remove an empty configured root without deleting any file entries."""
        folder = self._session.get(Folder, root_id)
        if not folder:
            return False
        has_entries = self._session.execute(
            select(Entry.id).where(Entry.folder_id == root_id).limit(1)
        ).first()
        if has_entries:
            return False
        if self._folder and self._folder.id == root_id:
            return False
        self._session.delete(folder)
        self._session.commit()
        return True

    def relink_root(self, root_id: int, new_path: str) -> dict[str, Any]:
        """Relink every entry under a moved root to a new root location."""
        folder = self._session.get(Folder, root_id)
        if not folder:
            return {'updated': 0, 'failed': 1, 'error': 'root not found'}
        if self._folder and self._folder.id == root_id:
            return {
                'updated': 0,
                'failed': 1,
                'error': 'the active database root cannot be relinked while open',
            }
        if not str(new_path).strip():
            return {'updated': 0, 'failed': 1, 'error': 'new root path is empty'}
        new_root = Path(os.path.abspath(new_path))
        if not new_root.is_dir():
            return {'updated': 0, 'failed': 1, 'error': 'new root is not an existing directory'}
        normalized_new_root = os.path.normcase(str(new_root))
        duplicate_roots = self._session.execute(
            select(Folder).where(Folder.id != root_id)
        ).scalars().all()
        if any(
            os.path.normcase(os.path.abspath(str(candidate.path))) == normalized_new_root
            for candidate in duplicate_roots
        ):
            return {'updated': 0, 'failed': 1, 'error': 'new root is already configured'}

        old_root = Path(os.path.abspath(str(folder.path)))
        entries = list(self._session.execute(
            select(Entry).where(Entry.folder_id == root_id)
        ).scalars().all())
        existing_paths = {
            os.path.normcase(os.path.abspath(str(entry.path)))
            for entry in self._session.execute(select(Entry)).scalars().all()
            if entry.folder_id != root_id
        }
        updated = 0
        failed = 0
        for entry in entries:
            try:
                relative = Path(os.path.relpath(
                    os.path.abspath(str(entry.path)), str(old_root)))
                if str(relative) == os.pardir or str(relative).startswith(os.pardir + os.sep):
                    failed += 1
                    continue
                new_entry_path = new_root / relative
            except (OSError, ValueError):
                failed += 1
                continue
            if os.path.normcase(str(new_entry_path)) in existing_paths:
                failed += 1
                continue
            entry.path = new_entry_path
            entry.filename = new_entry_path.name
            entry.suffix = new_entry_path.suffix.lstrip('.').lower()
            updated += 1
        folder.path = new_root
        self._session.commit()
        return {
            'updated': updated,
            'failed': failed,
            'error': 'one or more entries could not be relinked' if failed else '',
        }

    # ── Search ────────────────────────────────────────────────────────────────

    def search_color_entries(
        self, color_name: str, limit: int = 100, *, dominant_only: bool = False
    ) -> list[Entry]:
        """Search the normalized palette index by coarse color name."""
        from unifile.color_extraction import canonical_color_name

        name = canonical_color_name(color_name)
        if not name:
            return []
        statement = (
            select(Entry)
            .join(EntryColor, EntryColor.entry_id == Entry.id)
            .where(EntryColor.color_name == name)
        )
        if dominant_only:
            statement = statement.where(EntryColor.rank == 0)
        return list(self._session.execute(
            statement.order_by(EntryColor.rank, Entry.filename).limit(limit)
        ).unique().scalars().all())

    def _search_index_exists(self) -> bool:
        """Return whether the entry FTS table is available for this library."""
        try:
            return bool(self._session.execute(text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'entries_fts'"
            )).scalar())
        except OperationalError as exc:
            raise SearchIndexError("Unable to inspect the Tag Library search index") from exc

    @staticmethod
    def _check_search_cancel(cancel) -> None:
        if cancel and cancel():
            raise SearchCancelled("Tag Library search cancelled")

    @contextmanager
    def _search_progress_handler(self, cancel):
        """Interrupt SQLite work without touching the caller's Qt thread."""
        if not cancel:
            yield
            return
        self._check_search_cancel(cancel)
        connection = self._session.connection()
        raw = getattr(connection.connection, "driver_connection", connection.connection)
        set_progress_handler = getattr(raw, "set_progress_handler", None)
        if not callable(set_progress_handler):
            yield
            return
        set_progress_handler(lambda: 1 if cancel() else 0, 1000)
        try:
            yield
        finally:
            set_progress_handler(None, 0)

    def _filename_search_predicate(self, query: str):
        if self._search_index_exists():
            self.last_search_diagnostic["index_mode"] = "fts5"
            fts_rows = (
                select(text("rowid"))
                .select_from(text("entries_fts"))
                .where(text("entries_fts.filename MATCH :fts_query"))
                .params(fts_query=_sanitize_fts(query))
            )
            return Entry.id.in_(fts_rows)
        self.last_search_diagnostic["index_mode"] = "like-fallback"
        self.last_search_diagnostic["fallback_reason"] = "entries_fts is unavailable"
        escaped = _escape_like(query)
        return Entry.filename.ilike(f"%{escaped}%", escape='\\')

    def _entry_search_predicate(self, query: str):
        """Build one SQL predicate; boolean branches never materialize IDs."""
        q = query.strip()
        if not q:
            return true()

        and_parts = re.split(r"\s+AND\s+", q, flags=re.IGNORECASE)
        if len(and_parts) > 1:
            return and_(*(self._entry_search_predicate(part) for part in and_parts))
        or_parts = re.split(r"\s+OR\s+", q, flags=re.IGNORECASE)
        if len(or_parts) > 1:
            return or_(*(self._entry_search_predicate(part) for part in or_parts))
        if q.upper().startswith("NOT "):
            return ~self._entry_search_predicate(q[4:])

        if q.startswith("-tag:"):
            tag_name = q[5:].strip().strip('"')
            tag = self.get_tag_by_name(tag_name)
            if not tag:
                return true()
            related_ids = self.get_tag_search_ids(tag.id)
            tagged_subquery = select(TagEntry.entry_id).where(
                TagEntry.tag_id.in_(related_ids)
            )
            return ~Entry.id.in_(tagged_subquery)

        if q.startswith("tag:"):
            tag_name = q[4:].strip().strip('"')
            tag = self.get_tag_by_name(tag_name)
            if not tag:
                return false()
            related_ids = self.get_tag_search_ids(tag.id)
            return Entry.id.in_(select(TagEntry.entry_id).where(
                TagEntry.tag_id.in_(related_ids)
            ))

        from unifile.color_extraction import parse_color_query

        color_query = parse_color_query(q)
        if color_query:
            color_name, dominant_only = color_query
            conditions = [EntryColor.color_name == color_name]
            if dominant_only:
                conditions.append(EntryColor.rank == 0)
            return Entry.id.in_(select(EntryColor.entry_id).where(and_(*conditions)))

        if q.startswith("ext:"):
            ext = q[4:].strip().lower().lstrip('.')
            return Entry.suffix == ext

        if q.startswith("field:"):
            field_query = q[6:].strip()
            if '=' in field_query:
                key, val = field_query.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"')
                escaped_val = _escape_like(val)
                field_predicates = [
                    select(TextField.entry_id).where(
                        TextField.type_key == key,
                        TextField.value.ilike(f"%{escaped_val}%", escape='\\'),
                    ),
                    select(DatetimeField.entry_id).where(
                        DatetimeField.type_key == key,
                        DatetimeField.value.ilike(f"%{escaped_val}%", escape='\\'),
                    ),
                ]
                if val.casefold() in {
                    "true", "false", "yes", "no", "1", "0", "on", "off",
                }:
                    boolean_value = val.casefold() in {"true", "yes", "1", "on"}
                    field_predicates.append(select(BooleanField.entry_id).where(
                        BooleanField.type_key == key,
                        BooleanField.value.is_(boolean_value),
                    ))
                return or_(*(Entry.id.in_(predicate) for predicate in field_predicates))

        if q == "special:untagged":
            return ~Entry.id.in_(select(TagEntry.entry_id))
        if q == "special:tagged":
            return Entry.id.in_(select(TagEntry.entry_id))

        if q.startswith("rating:"):
            try:
                min_rating = int(q[7:].strip())
            except ValueError:
                return false()
            return Entry.rating >= min_rating

        if q.startswith("inbox:"):
            return Entry.is_inbox.is_(q[6:].strip().lower() == "true")

        if q.startswith("ns:"):
            namespace = q[3:].strip().strip('"')
            return Entry.id.in_(select(TagEntry.entry_id).join(
                Tag, Tag.id == TagEntry.tag_id
            ).where(Tag.namespace == namespace))

        if q.startswith("group:"):
            group_name = q[6:].strip().strip('"')
            group_id = self._session.execute(select(EntryGroup.id).where(
                func.lower(EntryGroup.name) == group_name.lower()
            )).scalar_one_or_none()
            if group_id is None:
                return false()
            return Entry.id.in_(select(EntryGroupMember.entry_id).where(
                EntryGroupMember.group_id == group_id
            ))

        return self._filename_search_predicate(q)

    def search_entries_page(
        self,
        query: str,
        limit: int = 100,
        offset: int = 0,
        *,
        cancel=None,
    ) -> SearchPage:
        """Return one SQL-paginated page and deterministic planner diagnostics."""
        bounded_limit = min(MAX_SEARCH_PAGE_SIZE, max(0, int(limit)))
        bounded_offset = max(0, int(offset))
        self.last_search_diagnostic = {
            "query": query.strip(),
            "index_mode": "btree",
            "fallback_reason": "",
        }
        started = time.perf_counter()
        self._check_search_cancel(cancel)
        predicate = self._entry_search_predicate(query)
        try:
            with self._search_progress_handler(cancel):
                total = int(self._session.execute(
                    select(func.count(Entry.id)).where(predicate)
                ).scalar() or 0)
                self._check_search_cancel(cancel)
                entries = list(self._session.execute(
                    select(Entry)
                    .options(joinedload(Entry.tags))
                    .where(predicate)
                    .order_by(Entry.filename, Entry.id)
                    .limit(bounded_limit)
                    .offset(bounded_offset)
                ).unique().scalars().all())
        except SearchCancelled:
            raise
        except (OperationalError, sqlite3.OperationalError) as exc:
            if cancel and "interrupt" in str(exc).lower():
                raise SearchCancelled("Tag Library search cancelled") from exc
            self.last_search_diagnostic["error"] = type(exc).__name__
            raise SearchIndexError(
                "Tag Library search failed; check the database and search indexes"
            ) from exc
        self.last_search_diagnostic["elapsed_ms"] = round(
            (time.perf_counter() - started) * 1000.0, 2)
        return SearchPage(
            entries=entries,
            total=total,
            offset=bounded_offset,
            limit=bounded_limit,
            index_mode=self.last_search_diagnostic["index_mode"],
            elapsed_ms=self.last_search_diagnostic["elapsed_ms"],
        )

    def search_entries(
        self,
        query: str,
        limit: int = 100,
        offset: int = 0,
        *,
        cancel=None,
    ) -> list[Entry]:
        """Search entries with SQL boolean composition and bounded pagination.

        Supported syntax includes ``tag:``, ``-tag:``/``NOT``, ``ext:``,
        ``field:``, ``special:``, ``rating:``, ``inbox:``, ``ns:``, ``group:``,
        ``color:``, ``AND``, ``OR``, and plain filename text.
        """
        return self.search_entries_page(
            query, limit=limit, offset=offset, cancel=cancel
        ).entries

    # ── Tag Inheritance (transitive parent search) ──────────────────────────

    def get_descendant_tag_ids(self, tag_id: int) -> set[int]:
        """Get all descendant tag IDs (children, grandchildren, etc.) transitively."""
        descendants = set()
        queue = [tag_id]
        while queue:
            current = queue.pop()
            children = self._session.execute(
                select(TagParent.child_id).where(TagParent.parent_id == current)
            ).scalars().all()
            for child_id in children:
                if child_id not in descendants:
                    descendants.add(child_id)
                    queue.append(child_id)
        return descendants

    def get_ancestor_tag_ids(self, tag_id: int) -> set[int]:
        """Get all ancestor tag IDs (parents, grandparents, etc.) transitively."""
        ancestors = set()
        queue = [tag_id]
        while queue:
            current = queue.pop()
            parents = self._session.execute(
                select(TagParent.parent_id).where(TagParent.child_id == current)
            ).scalars().all()
            for pid in parents:
                if pid not in ancestors:
                    ancestors.add(pid)
                    queue.append(pid)
        return ancestors

    def get_tag_search_ids(self, tag_id: int) -> set[int]:
        """Expand a tag through child hierarchy and reverse implications.

        A search for a consequent such as ``cat`` should include entries that
        carry ``kitten`` through an implication, even if they were added
        before that rule existed.
        """
        related = {tag_id}
        queue = [tag_id]
        while queue:
            current = queue.pop()
            children = self._session.execute(
                select(TagParent.child_id).where(TagParent.parent_id == current)
            ).scalars().all()
            antecedents = self._session.execute(
                select(TagImplication.antecedent_id).where(
                    TagImplication.consequent_id == current
                )
            ).scalars().all()
            for related_id in (*children, *antecedents):
                if related_id not in related:
                    related.add(related_id)
                    queue.append(related_id)
        return related

    def get_entries_by_tag_recursive(self, tag_id: int) -> list[Entry]:
        """Get entries matching a tag, descendants, or implying tags."""
        all_ids = self.get_tag_search_ids(tag_id)
        return list(self._session.execute(
            select(Entry).join(Entry.tags).where(Tag.id.in_(all_ids))
            .order_by(Entry.filename)
        ).unique().scalars().all())

    def get_tag_display_name(self, tag: Tag) -> str:
        """Get disambiguated display name using parent shorthand.

        Example: Two tags named 'Freddy' with parents 'FNAF' and 'Elm Street'
        display as 'Freddy (FNAF)' and 'Freddy (Elm Street)'.
        """
        # Check if any other tag shares the same name
        others = self._session.execute(
            select(Tag).where(Tag.name == tag.name, Tag.id != tag.id)
        ).scalars().all()
        if not others:
            return str(tag.name)
        # Find disambiguating parent
        if tag.parent_tags:
            parent = next(iter(tag.parent_tags))
            suffix = str(parent.shorthand or parent.name)
            return f"{tag.name} ({suffix})"
        return str(tag.name)

    def get_tag_hierarchy(self) -> list[dict[str, Any]]:
        """Get full tag hierarchy as a tree structure for UI display.

        Returns list of root tags (those with no parents) with their children nested.
        Cycle-safe: silently omits any tag already visited in the current branch.
        """
        all_tags = self.get_all_tags()
        tag_map = {t.id: t for t in all_tags}
        # Find roots (tags with no parents)
        roots = [t for t in all_tags if not t.parent_tags]

        def _build_tree(
            tag: Tag, visited: set[int]
        ) -> dict[str, Any] | None:
            if tag.id in visited:
                return None  # cycle detected — skip
            branch = visited | {tag.id}
            children_ids = self._session.execute(
                select(TagParent.child_id).where(TagParent.parent_id == tag.id)
            ).scalars().all()
            children = [tag_map[cid] for cid in children_ids if cid in tag_map]
            child_nodes = [
                node for c in sorted(children, key=lambda t: t.name)
                if (node := _build_tree(c, branch)) is not None
            ]
            return {
                'id': tag.id,
                'name': tag.name,
                'shorthand': tag.shorthand,
                'color': tag.color_slug,
                'is_category': tag.is_category,
                'children': child_nodes,
            }

        return [
            node for r in sorted(roots, key=lambda t: t.name)
            if (node := _build_tree(r, set())) is not None
        ]

    # ── Tag Packs (import/export) ─────────────────────────────────────────

    def export_tag_pack(self, filepath: str, tag_ids: list[int] | None = None) -> bool:
        """Export tags as a shareable tag pack (TOML preferred, JSON fallback).

        Args:
            filepath: Output file path.
            tag_ids: Specific tag IDs to export, or None for all.
        """
        tags: list[Tag] = self.get_all_tags()
        if tag_ids:
            tags = []
            for tag_id in tag_ids:
                tag = self.get_tag(tag_id)
                if tag is not None:
                    tags.append(tag)
        pack: dict[str, Any] = {
            'version': '1.0',
            'name': os.path.splitext(os.path.basename(filepath))[0],
            'created': dt.now().isoformat(),
            'tags': [],
            'implications': [],
            'siblings': [],
        }
        exported_ids = {tag.id for tag in tags}
        exported_tag_names = {tag.id: tag.name for tag in tags}
        for tag in tags:
            entry = {
                'name': tag.name,
                'shorthand': tag.shorthand,
                'color': tag.color_slug,
                'namespace': tag.namespace,
                'description': tag.description,
                'is_category': tag.is_category,
                'aliases': tag.alias_strings,
                'parents': [p.name for p in tag.parent_tags],
            }
            pack['tags'].append(entry)

        for relation in self._session.execute(select(TagImplication)).scalars().all():
            if {relation.antecedent_id, relation.consequent_id} <= exported_ids:
                pack['implications'].append({
                    'antecedent': exported_tag_names[relation.antecedent_id],
                    'consequent': exported_tag_names[relation.consequent_id],
                })
        sibling_pairs = set()
        for relation in self._session.execute(select(TagSibling)).scalars().all():
            pair = tuple(sorted((relation.bad_tag_id, relation.good_tag_id)))
            if len(pair) == 2 and set(pair) <= exported_ids and pair not in sibling_pairs:
                sibling_pairs.add(pair)
                pack['siblings'].append({
                    'first': exported_tag_names[pair[0]],
                    'second': exported_tag_names[pair[1]],
                })

        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.toml':
            try:
                import tomli_w
                with open(filepath, 'wb') as f:
                    tomli_w.dump(pack, f)
                return True
            except ImportError:
                pass

        import json
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(pack, f, indent=2)
        return True

    def import_tag_pack(self, filepath: str) -> dict[str, Any]:
        """Import tags from a tag pack (TOML or JSON).

        Returns: {'imported': int, 'skipped': int, 'errors': int}
        """
        pack = None
        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.toml':
            try:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]
                with open(filepath, 'rb') as f:
                    pack = tomllib.load(f)
            except Exception:
                pack = None

        if pack is None:
            try:
                import json
                with open(filepath, encoding='utf-8') as f:
                    pack = json.load(f)
            except Exception as exc:
                logger.error("import_tag_pack: failed to parse %s — %s", filepath, exc)
                return {'imported': 0, 'skipped': 0, 'errors': 1}

        stats = {'imported': 0, 'skipped': 0, 'errors': 0}
        tag_entries = pack.get('tags', [])

        # First pass: create all tags
        name_to_tag = {}
        for entry in tag_entries:
            name = entry.get('name', '').strip()
            if not name:
                continue
            existing = self.get_tag_by_name(name)
            if existing:
                name_to_tag[name] = existing
                stats['skipped'] += 1
                continue
            tag = self.add_tag(
                name=name,
                shorthand=entry.get('shorthand'),
                color_slug=entry.get('color'),
                is_category=entry.get('is_category', False),
            )
            if tag:
                if entry.get('namespace'):
                    tag.namespace = entry['namespace']
                if entry.get('description'):
                    tag.description = entry['description']
                name_to_tag[name] = tag
                for alias in entry.get('aliases', []):
                    self.add_alias(tag.id, alias)
                stats['imported'] += 1
            else:
                stats['errors'] += 1
        self._session.commit()

        # Second pass: set parent relationships
        for entry in tag_entries:
            name = entry.get('name', '').strip()
            tag = name_to_tag.get(name)
            if not tag:
                continue
            for parent_name in entry.get('parents', []):
                parent = name_to_tag.get(parent_name) or self.get_tag_by_name(parent_name)
                if parent:
                    self.add_parent_tag(tag.id, parent.id)

        # Third pass: restore graph rules after all tag names are available.
        for relation in pack.get('implications', []):
            antecedent = name_to_tag.get(relation.get('antecedent', ''))
            consequent = name_to_tag.get(relation.get('consequent', ''))
            if antecedent and consequent:
                self.add_tag_implication(antecedent.id, consequent.id)
        for relation in pack.get('siblings', []):
            first = name_to_tag.get(relation.get('first', ''))
            second = name_to_tag.get(relation.get('second', ''))
            if first and second:
                self.add_tag_sibling(first.id, second.id)

        return stats

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, int]:
        return {
            "entries": self.get_entry_count(),
            "tags": self._session.execute(select(func.count(Tag.id))).scalar() or 0,
            "tagged_entries": self._session.execute(
                select(func.count(func.distinct(TagEntry.entry_id)))
            ).scalar() or 0,
        }

    # ── Bulk Auto-Tag from Classification ─────────────────────────────────────

    def auto_tag_from_category(self, entry_id: int, category: str,
                               method: str = "", confidence: float = 0) -> Tag | None:
        """Create or find a tag matching the category name, and apply it to the entry.
        Used by the classification pipeline to auto-tag entries."""
        tag = self.get_tag_by_name(category)
        if not tag:
            tag = self.add_tag(name=category, is_category=True, color_slug="blue")
        if tag:
            self.add_tags_to_entry(entry_id, [tag.id])
            if method:
                self.set_entry_field(entry_id, "ai_category",
                                     f"{category} ({method}, {confidence:.0f}%)")
        return tag
