"""UniFile — Tag Library database engine and base model."""
import logging
from pathlib import Path
from typing import override

from sqlalchemy import Dialect, Engine, String, TypeDecorator, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

RESERVED_TAG_END = 999
TAG_ARCHIVED = 0
TAG_FAVORITE = 1


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


def make_tables(engine: Engine) -> None:
    logger.info("Creating tag library tables...")
    Base.metadata.create_all(engine)
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
