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
        """Search entries with query language support.

        Supported syntax:
            tag:TagName          — entries with a specific tag
            -tag:TagName         — entries WITHOUT a tag (NOT)
            ext:pdf              — entries with specific extension
            field:key=value      — entries with a field matching value
            special:untagged     — entries with no tags
            special:tagged       — entries with at least one tag
            tag:A AND tag:B      — boolean AND (intersection)
            tag:A OR tag:B       — boolean OR (union)
            plain text           — filename search (ilike)
        """
        q = query.strip()
        if not q:
            return self.get_all_entries(limit=limit)

        # Boolean AND/OR
        if ' AND ' in q:
            parts = [p.strip() for p in q.split(' AND ')]
            result_sets = [set(e.id for e in self.search_entries(p, limit=10000)) for p in parts]
            if not result_sets:
                return []
            common_ids = result_sets[0]
            for s in result_sets[1:]:
                common_ids &= s
            if not common_ids:
                return []
            return list(self._session.execute(
                select(Entry).where(Entry.id.in_(common_ids))
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

        if ' OR ' in q:
            parts = [p.strip() for p in q.split(' OR ')]
            all_ids = set()
            for p in parts:
                all_ids.update(e.id for e in self.search_entries(p, limit=10000))
            if not all_ids:
                return []
            return list(self._session.execute(
                select(Entry).where(Entry.id.in_(all_ids))
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

        # NOT tag
        if q.startswith("-tag:"):
            tag_name = q[5:].strip().strip('"')
            tag = self.get_tag_by_name(tag_name)
            if not tag:
                return self.get_all_entries(limit=limit)
            tagged_ids = {e.id for e in self.get_entries_by_tag(tag.id)}
            return list(self._session.execute(
                select(Entry).where(~Entry.id.in_(tagged_ids))
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

        # Tag search (with transitive inheritance)
        if q.startswith("tag:"):
            tag_name = q[4:].strip().strip('"')
            tag = self.get_tag_by_name(tag_name)
            if tag:
                return self.get_entries_by_tag_recursive(tag.id)[:limit]
            return []

        # Extension search
        if q.startswith("ext:"):
            ext = q[4:].strip().lower().lstrip('.')
            return list(self._session.execute(
                select(Entry).where(Entry.suffix == ext)
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

        # Field search
        if q.startswith("field:"):
            field_query = q[6:].strip()
            if '=' in field_query:
                key, val = field_query.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"')
                matching = self._session.execute(
                    select(TextField.entry_id).where(
                        TextField.type_key == key,
                        TextField.value.ilike(f"%{val}%"),
                    )
                ).scalars().all()
                if not matching:
                    return []
                return list(self._session.execute(
                    select(Entry).where(Entry.id.in_(matching))
                    .order_by(Entry.filename).limit(limit)
                ).scalars().all())

        # Special queries
        if q == "special:untagged":
            return self.get_untagged_entries()[:limit]
        if q == "special:tagged":
            subq = select(TagEntry.entry_id)
            return list(self._session.execute(
                select(Entry).where(Entry.id.in_(subq))
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

        # Default: filename search
        return list(self._session.execute(
            select(Entry).where(Entry.filename.ilike(f"%{q}%"))
            .order_by(Entry.filename).limit(limit)
        ).scalars().all())

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

    def get_entries_by_tag_recursive(self, tag_id: int) -> list[Entry]:
        """Get entries matching a tag OR any of its descendant tags."""
        all_ids = {tag_id} | self.get_descendant_tag_ids(tag_id)
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
            return tag.name
        # Find disambiguating parent
        if tag.parent_tags:
            parent = next(iter(tag.parent_tags))
            suffix = parent.shorthand or parent.name
            return f"{tag.name} ({suffix})"
        return tag.name

    def get_tag_hierarchy(self) -> list[dict]:
        """Get full tag hierarchy as a tree structure for UI display.

        Returns list of root tags (those with no parents) with their children nested.
        """
        all_tags = self.get_all_tags()
        tag_map = {t.id: t for t in all_tags}
        # Find roots (tags with no parents)
        roots = [t for t in all_tags if not t.parent_tags]

        def _build_tree(tag):
            children_ids = self._session.execute(
                select(TagParent.child_id).where(TagParent.parent_id == tag.id)
            ).scalars().all()
            children = [tag_map[cid] for cid in children_ids if cid in tag_map]
            return {
                'id': tag.id,
                'name': tag.name,
                'shorthand': tag.shorthand,
                'color': tag.color_slug,
                'is_category': tag.is_category,
                'children': [_build_tree(c) for c in sorted(children, key=lambda t: t.name)],
            }

        return [_build_tree(r) for r in sorted(roots, key=lambda t: t.name)]

    # ── Tag Packs (import/export) ─────────────────────────────────────────

    def export_tag_pack(self, filepath: str, tag_ids: list[int] | None = None) -> bool:
        """Export tags as a shareable JSON tag pack.

        Args:
            filepath: Output file path.
            tag_ids: Specific tag IDs to export, or None for all.
        """
        tags = self.get_all_tags() if not tag_ids else [
            self.get_tag(tid) for tid in tag_ids if self.get_tag(tid)]
        pack = {
            'version': '1.0',
            'name': os.path.splitext(os.path.basename(filepath))[0],
            'created': dt.now().isoformat(),
            'tags': [],
        }
        for tag in tags:
            entry = {
                'name': tag.name,
                'shorthand': tag.shorthand,
                'color': tag.color_slug,
                'is_category': tag.is_category,
                'aliases': tag.alias_strings,
                'parents': [p.name for p in tag.parent_tags],
            }
            pack['tags'].append(entry)

        import json
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(pack, f, indent=2)
        return True

    def import_tag_pack(self, filepath: str) -> dict:
        """Import tags from a tag pack JSON file.

        Returns: {'imported': int, 'skipped': int, 'errors': int}
        """
        import json
        with open(filepath, 'r', encoding='utf-8') as f:
            pack = json.load(f)

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
                name_to_tag[name] = tag
                # Add aliases
                for alias in entry.get('aliases', []):
                    self.add_alias(tag.id, alias)
                stats['imported'] += 1
            else:
                stats['errors'] += 1

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

        return stats

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
