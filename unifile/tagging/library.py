"""UniFile — Tag Library Manager (core API for tag operations)."""
import logging
import os
import uuid
from datetime import datetime as dt
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, joinedload

# Sentinel for "not passed" (distinct from None, which means "clear the field")
_UNSET = object()

from unifile.tagging.db import Base, make_engine, make_tables
from unifile.tagging.models import (
    Tag, TagAlias, TagEntry, TagParent, Entry, Folder,
    ValueType, TextField, DatetimeField, BooleanField,
    DEFAULT_FIELDS, FieldTypeEnum,
    EntryGroup, EntryGroupMember,
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
            folder = Folder(path=p, uuid=str(uuid.uuid4()))
            self._session.add(folder)
            self._session.commit()
        return folder

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
        return list(self._session.execute(
            select(Tag).where(Tag.name.ilike(f"%{query}%")).limit(limit)
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
                   namespace=_UNSET,
                   is_hidden: bool | None = None,
                   description=_UNSET,
                   icon=_UNSET) -> bool:
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
            batch_paths = [Path(fp) for fp in batch]
            # Fetch all already-present paths in one query (avoids N+1)
            existing_paths: set = set(
                self._session.execute(
                    select(Entry.path).where(Entry.path.in_(batch_paths))
                ).scalars().all()
            )
            for fp in batch:
                p = Path(fp)
                if p in existing_paths:
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
        for tid in tag_ids:
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

    @staticmethod
    def set_entry_field_with_session(
        session, entry_id: int, field_key: str, value: str
    ) -> bool:
        """Thread-safe variant: caller provides an explicit SQLAlchemy session."""
        entry = session.get(Entry, entry_id)
        vt = session.get(ValueType, field_key)
        if not entry or not vt:
            return False
        existing = session.execute(
            select(TextField).where(
                TextField.entry_id == entry_id,
                TextField.type_key == field_key,
            )
        ).scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            session.add(TextField(
                type_key=field_key,
                entry_id=entry_id,
                value=value,
                position=vt.position,
            ))
        session.commit()
        return True

    def get_entry_fields(self, entry_id: int) -> dict[str, str]:
        fields = {}
        results = self._session.execute(
            select(TextField).where(TextField.entry_id == entry_id)
        ).scalars().all()
        for f in results:
            fields[f.type_key] = f.value or ""
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

    # ── Multiple Library Roots ────────────────────────────────────────────────

    def add_root(self, path: str) -> bool:
        """Add an additional root folder to this library."""
        p = Path(path)
        existing = self._session.execute(
            select(Folder).where(Folder.path == p)
        ).scalar_one_or_none()
        if existing:
            return True
        folder = Folder(path=p, uuid=str(uuid.uuid4()))
        self._session.add(folder)
        self._session.commit()
        return True

    def get_roots(self) -> list[str]:
        """Return list of all root folder paths in this library."""
        folders = self._session.execute(select(Folder)).scalars().all()
        return [str(f.path) for f in folders]

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
            rating:3             — entries with rating >= 3
            inbox:true/false     — filter by inbox state
            ns:namespace         — entries with at least one tag in namespace
            group:name           — entries in the named group
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

        # NOT tag — use SQL subquery instead of loading all entries into Python
        if q.startswith("-tag:"):
            tag_name = q[5:].strip().strip('"')
            tag = self.get_tag_by_name(tag_name)
            if not tag:
                return self.get_all_entries(limit=limit)
            tagged_subq = select(TagEntry.entry_id).where(TagEntry.tag_id == tag.id)
            return list(self._session.execute(
                select(Entry).where(~Entry.id.in_(tagged_subq))
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

        # Rating filter
        if q.startswith("rating:"):
            try:
                min_r = int(q[7:].strip())
            except ValueError:
                return []
            return list(self._session.execute(
                select(Entry).where(Entry.rating >= min_r)
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

        # Inbox filter
        if q.startswith("inbox:"):
            val = q[6:].strip().lower()
            is_inbox = val == "true"
            return list(self._session.execute(
                select(Entry).where(Entry.is_inbox == is_inbox)
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

        # Namespace filter
        if q.startswith("ns:"):
            ns = q[3:].strip()
            matching_ids = self._session.execute(
                select(TagEntry.entry_id).join(Tag, Tag.id == TagEntry.tag_id)
                .where(Tag.namespace == ns)
            ).scalars().all()
            return list(self._session.execute(
                select(Entry).where(Entry.id.in_(matching_ids))
                .order_by(Entry.filename).limit(limit)
            ).scalars().all())

        # Group filter
        if q.startswith("group:"):
            group_name = q[6:].strip()
            group = self._session.execute(
                select(EntryGroup).where(
                    func.lower(EntryGroup.name) == group_name.lower()
                )
            ).scalar_one_or_none()
            if not group:
                return []
            return self.get_group_entries(group.id)[:limit]

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
        Cycle-safe: silently omits any tag already visited in the current branch.
        """
        all_tags = self.get_all_tags()
        tag_map = {t.id: t for t in all_tags}
        # Find roots (tags with no parents)
        roots = [t for t in all_tags if not t.parent_tags]

        def _build_tree(tag, visited: set) -> dict | None:
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
                'namespace': tag.namespace,
                'description': tag.description,
                'is_category': tag.is_category,
                'aliases': tag.alias_strings,
                'parents': [p.name for p in tag.parent_tags],
            }
            pack['tags'].append(entry)

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

    def import_tag_pack(self, filepath: str) -> dict:
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
                with open(filepath, 'r', encoding='utf-8') as f:
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
