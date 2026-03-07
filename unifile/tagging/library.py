"""UniFile — Tag Library Manager (core API for tag operations)."""
import logging
import os
import uuid
from datetime import datetime as dt
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from unifile.tagging.db import Base, make_engine, make_tables
from unifile.tagging.models import (
    Tag, TagAlias, TagEntry, TagParent, Entry, Folder,
    ValueType, TextField, DatetimeField, BooleanField,
    DEFAULT_FIELDS, FieldTypeEnum,
)

logger = logging.getLogger(__name__)

DB_FILENAME = "unifile_tags.sqlite"


class TagLibrary:
    """Manages a tag-based file library stored in SQLite via SQLAlchemy."""

    def __init__(self, library_dir: str | None = None):
        self.library_dir = library_dir
        self.engine = None
        self._session = None
        self._folder = None

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

    def close(self):
        if self._session:
            self._session.close()
            self._session = None
        if self.engine:
            self.engine.dispose()
            self.engine = None
        self._folder = None

    def _init_default_fields(self):
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
        p = Path(path)
        folder = self._session.execute(
            select(Folder).where(Folder.path == p)
        ).scalar_one_or_none()
        if not folder:
            folder = Folder(id=1, path=p, uuid=str(uuid.uuid4()))
            self._session.add(folder)
            self._session.commit()
        return folder

    # ── Tag CRUD ──────────────────────────────────────────────────────────────

    def add_tag(self, name: str, shorthand: str | None = None,
                color_slug: str | None = None, is_category: bool = False,
                parent_id: int | None = None) -> Tag | None:
        existing = self._session.execute(
            select(Tag).where(func.lower(Tag.name) == name.lower())
        ).scalar_one_or_none()
        if existing:
            return existing

        tag = Tag(name=name, shorthand=shorthand, color_slug=color_slug,
                  is_category=is_category)
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
        return list(self._session.execute(
            select(Tag).where(Tag.name.ilike(f"%{query}%")).limit(limit)
        ).scalars().all())

    def get_all_tags(self) -> list[Tag]:
        return list(self._session.execute(
            select(Tag).order_by(Tag.name)
        ).scalars().all())

    def get_category_tags(self) -> list[Tag]:
        return list(self._session.execute(
            select(Tag).where(Tag.is_category == True).order_by(Tag.name)
        ).scalars().all())

    def update_tag(self, tag_id: int, name: str | None = None,
                   color_slug: str | None = None,
                   is_category: bool | None = None) -> bool:
        tag = self._session.get(Tag, tag_id)
        if not tag:
            return False
        if name is not None:
            tag.name = name
        if color_slug is not None:
            tag.color_slug = color_slug
        if is_category is not None:
            tag.is_category = is_category
        self._session.commit()
        return True

    def delete_tag(self, tag_id: int) -> bool:
        tag = self._session.get(Tag, tag_id)
        if not tag:
            return False
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
            folder=self._folder,
            filename=p.name,
            suffix=p.suffix.lstrip(".").lower(),
            date_created=dt.fromtimestamp(stat.st_ctime) if stat else None,
            date_modified=dt.fromtimestamp(stat.st_mtime) if stat else None,
            date_added=dt.now(),
        )
        self._session.add(entry)
        self._session.commit()
        return entry

    def add_entries_bulk(self, file_paths: list[str], batch_size: int = 200) -> int:
        count = 0
        for i in range(0, len(file_paths), batch_size):
            batch = file_paths[i:i + batch_size]
            for fp in batch:
                p = Path(fp)
                existing = self._session.execute(
                    select(Entry).where(Entry.path == p)
                ).scalar_one_or_none()
                if existing:
                    continue
                stat = p.stat() if p.exists() else None
                entry = Entry(
                    path=p,
                    folder=self._folder,
                    filename=p.name,
                    suffix=p.suffix.lstrip(".").lower(),
                    date_created=dt.fromtimestamp(stat.st_ctime) if stat else None,
                    date_modified=dt.fromtimestamp(stat.st_mtime) if stat else None,
                    date_added=dt.now(),
                )
                self._session.add(entry)
                count += 1
            self._session.commit()
        return count

    def get_entry(self, entry_id: int) -> Entry | None:
        return self._session.execute(
            select(Entry).options(joinedload(Entry.tags)).where(Entry.id == entry_id)
        ).scalar_one_or_none()

    def get_entry_by_path(self, path: str) -> Entry | None:
        return self._session.execute(
            select(Entry).options(joinedload(Entry.tags)).where(Entry.path == Path(path))
        ).scalar_one_or_none()

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
        self._session.delete(entry)
        self._session.commit()
        return True

    # ── Tag ↔ Entry Operations ────────────────────────────────────────────────

    def add_tags_to_entry(self, entry_id: int, tag_ids: list[int]) -> bool:
        entry = self._session.execute(
            select(Entry).options(joinedload(Entry.tags)).where(Entry.id == entry_id)
        ).scalar_one_or_none()
        if not entry:
            return False
        for tid in tag_ids:
            tag = self._session.get(Tag, tid)
            if tag:
                entry.tags.add(tag)
        self._session.commit()
        return True

    def remove_tags_from_entry(self, entry_id: int, tag_ids: list[int]) -> bool:
        entry = self._session.execute(
            select(Entry).options(joinedload(Entry.tags)).where(Entry.id == entry_id)
        ).scalar_one_or_none()
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

    def get_untagged_entries(self) -> list[Entry]:
        subq = select(TagEntry.entry_id)
        return list(self._session.execute(
            select(Entry).where(~Entry.id.in_(subq)).order_by(Entry.filename)
        ).scalars().all())

    # ── Entry Field Operations ────────────────────────────────────────────────

    def set_entry_field(self, entry_id: int, field_key: str, value: str) -> bool:
        entry = self._session.get(Entry, entry_id)
        vt = self._session.get(ValueType, field_key)
        if not entry or not vt:
            return False

        # Check if field already exists
        existing = self._session.execute(
            select(TextField).where(
                TextField.entry_id == entry_id,
                TextField.type_key == field_key,
            )
        ).scalar_one_or_none()

        if existing:
            existing.value = value
        else:
            field = TextField(type_key=field_key, entry_id=entry_id,
                              value=value, position=vt.position)
            self._session.add(field)

        self._session.commit()
        return True

    def get_entry_fields(self, entry_id: int) -> dict[str, str]:
        fields = {}
        results = self._session.execute(
            select(TextField).where(TextField.entry_id == entry_id)
        ).scalars().all()
        for f in results:
            fields[f.type_key] = f.value or ""
        return fields

    # ── Search ────────────────────────────────────────────────────────────────

    def search_entries(self, query: str, limit: int = 100) -> list[Entry]:
        q = query.strip()
        if q.startswith("tag:"):
            tag_name = q[4:].strip().strip('"')
            tag = self.get_tag_by_name(tag_name)
            if tag:
                return self.get_entries_by_tag(tag.id)[:limit]
            return []
        elif q == "special:untagged":
            return self.get_untagged_entries()[:limit]
        else:
            return list(self._session.execute(
                select(Entry).where(Entry.filename.ilike(f"%{q}%"))
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
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
