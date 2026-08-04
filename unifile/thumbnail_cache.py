"""Shared persistent thumbnail cache.

Thumbnail pixels are stored as content-addressed files and indexed by a tiny
SQLite WAL database.  Reads map the object file with ``mmap`` before copying
the encoded bytes into Qt's image decoder, so panels share one bounded cache
without retaining every decoded QPixmap in process memory.
"""

from __future__ import annotations

import hashlib
import mmap
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from unifile.config import _APP_DATA_DIR

CACHE_SCHEMA_VERSION = 1
DEFAULT_MAX_MB = 500
MIN_MAX_MB = 16
MAX_MAX_MB = 4096
THUMBNAIL_CACHE_MAX_MB_KEY = "thumbnail_cache/max_mb"
_CACHE_ROOT = Path(_APP_DATA_DIR) / "thumbnail-cache"
_OBJECT_ROOT = _CACHE_ROOT / "objects"
_INDEX_DB = _CACHE_ROOT / "index.sqlite"


def _bounded_mb(value, default: int = DEFAULT_MAX_MB) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(MIN_MAX_MB, min(MAX_MAX_MB, value))


def max_mb_from_settings(settings=None, default: int = DEFAULT_MAX_MB) -> int:
    """Read and normalize the persistent cache cap from QSettings-like data."""
    if settings is None:
        return _bounded_mb(default, default)
    try:
        value = settings.value(THUMBNAIL_CACHE_MAX_MB_KEY, default, type=int)
    except (AttributeError, TypeError, ValueError):
        value = default
    return _bounded_mb(value, default)


def save_max_mb(settings, value: int) -> int:
    """Persist a bounded cache cap and return the normalized value."""
    normalized = _bounded_mb(value)
    settings.setValue(THUMBNAIL_CACHE_MAX_MB_KEY, normalized)
    try:
        settings.sync()
    except AttributeError:
        pass
    cache = get_thumbnail_cache()
    cache.max_bytes = normalized * 1024 * 1024
    cache.prune()
    return normalized


def thumbnail_key(path: str | os.PathLike[str], size: int, variant: str = "png") -> str | None:
    """Return a stable key for a current source file and thumbnail variant."""
    try:
        source = Path(path)
        stat = source.stat()
    except (OSError, ValueError, TypeError):
        return None
    try:
        identity = "\0".join((
            str(source.absolute()).casefold(),
            str(stat.st_size),
            str(stat.st_mtime_ns),
            str(max(1, int(size))),
            str(variant),
            str(CACHE_SCHEMA_VERSION),
        )).encode("utf-8", "surrogatepass")
    except (TypeError, ValueError, OSError):
        return None
    return hashlib.sha256(identity).hexdigest()


class ThumbnailCache:
    """Thread-safe bounded cache shared by every thumbnail consumer."""

    def __init__(
        self,
        root: str | os.PathLike[str] = _CACHE_ROOT,
        *,
        max_bytes: int = DEFAULT_MAX_MB * 1024 * 1024,
        db_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.db_path = Path(db_path) if db_path else self.root / "index.sqlite"
        self.max_bytes = max(1, int(max_bytes))
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        self.objects.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS thumbnail_entries (
                    cache_key TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    accessed_at REAL NOT NULL,
                    created_at REAL NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_thumbnail_accessed "
                "ON thumbnail_entries(accessed_at)"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _object_path(self, cache_key: str) -> Path:
        return self.objects / f"{cache_key}.bin"

    def _touch(self, cache_key: str) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                "UPDATE thumbnail_entries SET accessed_at=? WHERE cache_key=?",
                (now, cache_key),
            )
            connection.commit()

    @contextmanager
    def open_mmap(self, cache_key: str) -> Iterator[mmap.mmap | None]:
        """Yield a read-only mmap for an entry, or ``None`` when absent."""
        if not cache_key:
            yield None
            return
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT filename FROM thumbnail_entries WHERE cache_key=?",
                    (cache_key,),
                ).fetchone()
            if not row:
                yield None
                return
            path = self.root / row[0]
            try:
                with path.open("rb") as stream:
                    if path.stat().st_size == 0:
                        yield None
                        return
                    mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
                    try:
                        self._touch(cache_key)
                        yield mapped
                    finally:
                        mapped.close()
            except (OSError, ValueError):
                self._remove_missing(cache_key)
                yield None

    def _remove_missing(self, cache_key: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM thumbnail_entries WHERE cache_key=?", (cache_key,)
            )
            connection.commit()

    def get(self, cache_key: str) -> bytes | None:
        """Read an entry through mmap and return encoded image bytes."""
        with self.open_mmap(cache_key) as mapped:
            return bytes(mapped) if mapped is not None else None

    def put(self, cache_key: str, payload: bytes) -> bool:
        """Atomically store encoded image bytes and prune the LRU tail."""
        if not cache_key or not payload:
            return False
        payload = bytes(payload)
        path = self._object_path(cache_key)
        temporary = path.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
        now = time.time()
        with self._lock:
            try:
                self.objects.mkdir(parents=True, exist_ok=True)
                with temporary.open("wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                with self._connect() as connection:
                    connection.execute(
                        """INSERT INTO thumbnail_entries
                           (cache_key, filename, size, accessed_at, created_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(cache_key) DO UPDATE SET
                               filename=excluded.filename,
                               size=excluded.size,
                               accessed_at=excluded.accessed_at""",
                        (cache_key, str(path.relative_to(self.root)), len(payload), now, now),
                    )
                    connection.commit()
                self.prune()
                return True
            except (OSError, sqlite3.Error, ValueError):
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                return False

    def prune(self) -> int:
        """Evict least-recently-used entries until the byte cap is met."""
        removed = 0
        with self._lock:
            with self._connect() as connection:
                total = connection.execute(
                    "SELECT COALESCE(SUM(size), 0) FROM thumbnail_entries"
                ).fetchone()[0]
                if total <= self.max_bytes:
                    return 0
                rows = connection.execute(
                    "SELECT cache_key, filename, size FROM thumbnail_entries "
                    "ORDER BY accessed_at ASC"
                ).fetchall()
                for cache_key, filename, size in rows:
                    if total <= self.max_bytes:
                        break
                    try:
                        (self.root / filename).unlink(missing_ok=True)
                    except OSError:
                        pass
                    connection.execute(
                        "DELETE FROM thumbnail_entries WHERE cache_key=?", (cache_key,)
                    )
                    total -= int(size)
                    removed += 1
                connection.commit()
        return removed

    def clear(self) -> int:
        """Remove all indexed entries and their object files."""
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT filename FROM thumbnail_entries"
                ).fetchall()
                connection.execute("DELETE FROM thumbnail_entries")
                connection.commit()
            removed = 0
            for (filename,) in rows:
                try:
                    (self.root / filename).unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    pass
            return removed

    def stats(self) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            count, total = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM thumbnail_entries"
            ).fetchone()
        return {
            "count": int(count),
            "bytes": int(total),
            "max_bytes": int(self.max_bytes),
        }


_DEFAULT_CACHE: ThumbnailCache | None = None
_DEFAULT_CACHE_LOCK = threading.Lock()


def get_thumbnail_cache() -> ThumbnailCache:
    """Return the process-wide shared cache instance."""
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        with _DEFAULT_CACHE_LOCK:
            if _DEFAULT_CACHE is None:
                try:
                    from PyQt6.QtCore import QSettings

                    configured_mb = max_mb_from_settings(QSettings("UniFile", "UniFile"))
                except (ImportError, RuntimeError):
                    configured_mb = DEFAULT_MAX_MB
                _DEFAULT_CACHE = ThumbnailCache(max_bytes=configured_mb * 1024 * 1024)
    return _DEFAULT_CACHE


def encode_thumbnail(path: str, size: int) -> bytes | None:
    """Load and PNG-encode a source image for synchronous panel previews."""
    try:
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PyQt6.QtGui import QImage

        image = QImage(path)
        if image.isNull():
            return None
        scaled = image.scaled(
            max(1, int(size)),
            max(1, int(size)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        payload = QByteArray()
        buffer = QBuffer(payload)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            return None
        try:
            if not scaled.save(buffer, "PNG"):
                return None
        finally:
            buffer.close()
        return bytes(payload)
    except (OSError, RuntimeError, TypeError):
        return None


def load_thumbnail_bytes(path: str, size: int) -> bytes | None:
    """Return a cached thumbnail, filling the shared store on a miss."""
    key = thumbnail_key(path, size)
    if key is None:
        return None
    cache = get_thumbnail_cache()
    payload = cache.get(key)
    if payload is not None:
        return payload
    payload = encode_thumbnail(path, size)
    if payload:
        cache.put(key, payload)
    return payload


def load_thumbnail_pixmap(path: str, size: int):
    """Decode a shared cached thumbnail into a QPixmap, or return ``None``."""
    try:
        from PyQt6.QtGui import QPixmap

        payload = load_thumbnail_bytes(path, size)
        if not payload:
            return None
        pixmap = QPixmap()
        return pixmap if pixmap.loadFromData(payload) else None
    except (RuntimeError, TypeError):
        return None
