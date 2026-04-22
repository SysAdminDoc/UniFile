"""UniFile — Tag Library ORM models (adapted from TagStudio)."""
import enum
from datetime import datetime as dt
from pathlib import Path
from typing import override

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from unifile.tagging.db import Base, PathType, TAG_ARCHIVED, TAG_FAVORITE


# ── Enums ─────────────────────────────────────────────────────────────────────

class FieldTypeEnum(enum.Enum):
    TEXT_LINE = "Text Line"
    TEXT_BOX = "Text Box"
    DATETIME = "Datetime"
    BOOLEAN = "Checkbox"


# ── Junction Tables ───────────────────────────────────────────────────────────

class TagParent(Base):
    __tablename__ = "tag_parents"
    parent_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class TagEntry(Base):
    __tablename__ = "tag_entries"
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), primary_key=True)


# ── Entry Group Models ────────────────────────────────────────────────────────

class EntryGroup(Base):
    __tablename__ = "entry_groups"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]
    color_slug: Mapped[str | None]
    created_at: Mapped[dt | None]


class EntryGroupMember(Base):
    __tablename__ = "entry_group_members"
    group_id: Mapped[int] = mapped_column(ForeignKey("entry_groups.id"), primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), primary_key=True)


# ── Field Models ──────────────────────────────────────────────────────────────

class ValueType(Base):
    __tablename__ = "value_type"
    key: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    type: Mapped[FieldTypeEnum] = mapped_column(default=FieldTypeEnum.TEXT_LINE)
    is_default: Mapped[bool] = mapped_column(default=False)
    position: Mapped[int] = mapped_column(default=0)


class TextField(Base):
    __tablename__ = "text_fields"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type_key: Mapped[str] = mapped_column(ForeignKey("value_type.key"))
    type: Mapped[ValueType] = relationship(foreign_keys=[type_key], lazy=False)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    position: Mapped[int] = mapped_column(default=0)
    value: Mapped[str | None]


class DatetimeField(Base):
    __tablename__ = "datetime_fields"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type_key: Mapped[str] = mapped_column(ForeignKey("value_type.key"))
    type: Mapped[ValueType] = relationship(foreign_keys=[type_key], lazy=False)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    position: Mapped[int] = mapped_column(default=0)
    value: Mapped[str | None]


class BooleanField(Base):
    __tablename__ = "boolean_fields"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type_key: Mapped[str] = mapped_column(ForeignKey("value_type.key"))
    type: Mapped[ValueType] = relationship(foreign_keys=[type_key], lazy=False)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    position: Mapped[int] = mapped_column(default=0)
    value: Mapped[bool]


# ── Tag Models ────────────────────────────────────────────────────────────────

class TagAlias(Base):
    __tablename__ = "tag_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"))
    tag: Mapped["Tag"] = relationship(back_populates="aliases")

    def __init__(self, name: str, tag_id: int | None = None):
        self.name = name
        if tag_id is not None:
            self.tag_id = tag_id
        super().__init__()


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str]
    shorthand: Mapped[str | None]
    color_slug: Mapped[str | None] = mapped_column()
    is_category: Mapped[bool]
    is_hidden: Mapped[bool]
    icon: Mapped[str | None]
    namespace: Mapped[str | None]
    description: Mapped[str | None]
    aliases: Mapped[set[TagAlias]] = relationship(back_populates="tag")
    parent_tags: Mapped[set["Tag"]] = relationship(
        secondary=TagParent.__tablename__,
        primaryjoin="Tag.id == TagParent.child_id",
        secondaryjoin="Tag.id == TagParent.parent_id",
    )

    __table_args__ = ({"sqlite_autoincrement": True},)

    @property
    def parent_ids(self) -> list[int]:
        return [tag.id for tag in self.parent_tags]

    @property
    def alias_strings(self) -> list[str]:
        return [alias.name for alias in self.aliases]

    def __init__(
        self,
        name: str,
        id: int | None = None,
        shorthand: str | None = None,
        aliases: set[TagAlias] | None = None,
        parent_tags: set["Tag"] | None = None,
        icon: str | None = None,
        color_slug: str | None = None,
        is_category: bool = False,
        is_hidden: bool = False,
        namespace: str | None = None,
        description: str | None = None,
    ):
        self.name = name
        self.aliases = aliases or set()
        self.parent_tags = parent_tags or set()
        self.color_slug = color_slug
        self.icon = icon
        self.shorthand = shorthand
        self.is_category = is_category
        self.is_hidden = is_hidden
        self.namespace = namespace
        self.description = description
        self.id = id
        super().__init__()

    @override
    def __str__(self) -> str:
        display = f"{self.namespace}:{self.name}" if self.namespace else self.name
        return f"<Tag ID: {self.id} Name: {display}>"

    @override
    def __repr__(self) -> str:
        return self.__str__()

    @override
    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, Tag):
            return False
        return self.id == value.id

    def __lt__(self, other: "Tag") -> bool:
        return self.name < other.name


# ── Folder & Entry Models ─────────────────────────────────────────────────────

class Folder(Base):
    __tablename__ = "folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[Path] = mapped_column(PathType, unique=True)
    uuid: Mapped[str] = mapped_column(unique=True)


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("folders.id"))
    folder: Mapped[Folder] = relationship("Folder")
    path: Mapped[Path] = mapped_column(PathType, unique=True)
    filename: Mapped[str] = mapped_column()
    suffix: Mapped[str] = mapped_column()
    date_created: Mapped[dt | None]
    date_modified: Mapped[dt | None]
    date_added: Mapped[dt | None]
    rating: Mapped[int | None]
    is_inbox: Mapped[bool] = mapped_column(default=True)
    source_url: Mapped[str | None]
    media_width: Mapped[int | None]
    media_height: Mapped[int | None]
    media_duration: Mapped[float | None]
    word_count: Mapped[int | None]

    tags: Mapped[set[Tag]] = relationship(secondary="tag_entries")
    groups: Mapped[set[EntryGroup]] = relationship(secondary="entry_group_members")

    text_fields: Mapped[list[TextField]] = relationship(
        back_populates="entry",
        cascade="all, delete",
        foreign_keys=[TextField.entry_id],
    )
    datetime_fields: Mapped[list[DatetimeField]] = relationship(
        back_populates="entry",
        cascade="all, delete",
        foreign_keys=[DatetimeField.entry_id],
    )

    # Back-references for fields
    TextField.entry = relationship("Entry", back_populates="text_fields", foreign_keys=[TextField.entry_id])
    DatetimeField.entry = relationship("Entry", back_populates="datetime_fields", foreign_keys=[DatetimeField.entry_id])

    @property
    def tag_names(self) -> list[str]:
        return sorted([tag.name for tag in self.tags])

    @property
    def is_favorite(self) -> bool:
        return any(tag.id == TAG_FAVORITE for tag in self.tags)

    @property
    def is_archived(self) -> bool:
        return any(tag.id == TAG_ARCHIVED for tag in self.tags)

    def has_tag(self, tag: Tag) -> bool:
        return tag in self.tags


# ── Default Field Definitions ─────────────────────────────────────────────────

DEFAULT_FIELDS = [
    {"key": "title", "name": "Title", "type": FieldTypeEnum.TEXT_LINE, "is_default": True, "position": 0},
    {"key": "author", "name": "Author", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 1},
    {"key": "artist", "name": "Artist", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 2},
    {"key": "url", "name": "URL", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 3},
    {"key": "description", "name": "Description", "type": FieldTypeEnum.TEXT_BOX, "is_default": True, "position": 4},
    {"key": "notes", "name": "Notes", "type": FieldTypeEnum.TEXT_BOX, "is_default": False, "position": 5},
    {"key": "date", "name": "Date", "type": FieldTypeEnum.DATETIME, "is_default": False, "position": 10},
    {"key": "date_created", "name": "Date Created", "type": FieldTypeEnum.DATETIME, "is_default": False, "position": 11},
    {"key": "date_modified", "name": "Date Modified", "type": FieldTypeEnum.DATETIME, "is_default": False, "position": 12},
    {"key": "series", "name": "Series", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 19},
    {"key": "source", "name": "Source", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 21},
    {"key": "publisher", "name": "Publisher", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 27},
    {"key": "composer", "name": "Composer", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 29},
    {"key": "comments", "name": "Comments", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 30},
    # Media-specific (from mnamer integration)
    {"key": "season", "name": "Season", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 40},
    {"key": "episode", "name": "Episode", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 41},
    {"key": "genre", "name": "Genre", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 42},
    {"key": "imdb_id", "name": "IMDb ID", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 43},
    {"key": "tmdb_id", "name": "TMDb ID", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 44},
    # AI-generated (from Local-File-Organizer integration)
    {"key": "ai_summary", "name": "AI Summary", "type": FieldTypeEnum.TEXT_BOX, "is_default": False, "position": 50},
    {"key": "ai_category", "name": "AI Category", "type": FieldTypeEnum.TEXT_LINE, "is_default": False, "position": 51},
]

# Tag color palette for the UI
TAG_COLORS = {
    "red": "#ef4444", "orange": "#f97316", "amber": "#f59e0b",
    "yellow": "#eab308", "lime": "#84cc16", "green": "#22c55e",
    "emerald": "#10b981", "teal": "#14b8a6", "cyan": "#06b6d4",
    "sky": "#0ea5e9", "blue": "#3b82f6", "indigo": "#6366f1",
    "violet": "#8b5cf6", "purple": "#a855f7", "fuchsia": "#d946ef",
    "pink": "#ec4899", "rose": "#f43f5e", "slate": "#64748b",
    "gray": "#6b7280", "stone": "#78716c",
}
