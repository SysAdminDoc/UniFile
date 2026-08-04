"""Tests for the shared mmap-backed thumbnail cache."""

import os
import sqlite3
import time

from unifile.thumbnail_cache import (
    DEFAULT_MAX_MB,
    MIN_MAX_MB,
    ThumbnailCache,
    max_mb_from_settings,
    thumbnail_key,
)


class _Settings:
    def __init__(self):
        self.values = {}

    def value(self, key, default, type=int):
        del type
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


def test_cache_uses_wal_mmap_reads_and_lru_eviction(tmp_path):
    cache = ThumbnailCache(tmp_path / "thumbs", max_bytes=10)
    assert cache.put("old", b"123456")
    time.sleep(0.01)
    assert cache.put("new", b"abcdef")

    assert cache.get("old") is None
    assert cache.get("new") == b"abcdef"
    with cache.open_mmap("new") as mapped:
        assert mapped is not None
        assert mapped[:] == b"abcdef"

    with sqlite3.connect(cache.db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_cache_key_changes_when_source_metadata_changes(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"one")
    first = thumbnail_key(source, 150)
    assert first
    source.write_bytes(b"two bytes")
    os.utime(source, None)
    second = thumbnail_key(source, 150)
    assert second and second != first
    assert thumbnail_key(source, 300) != second


def test_cache_settings_are_bounded(tmp_path):
    del tmp_path
    settings = _Settings()
    assert max_mb_from_settings(settings) == DEFAULT_MAX_MB
    settings.values["thumbnail_cache/max_mb"] = 1
    assert max_mb_from_settings(settings) == MIN_MAX_MB


def test_qt_thumbnail_helper_round_trips_through_shared_cache(tmp_path):
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import QApplication

    from unifile import thumbnail_cache as cache_module
    from unifile.thumbnail_cache import load_thumbnail_pixmap

    app = QApplication.instance() or QApplication(["unifile-thumbnail-test"])
    app.processEvents()
    source = tmp_path / "photo.png"
    image = QImage(24, 12, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    assert image.save(str(source), "PNG")

    original_cache = cache_module._DEFAULT_CACHE
    cache_module._DEFAULT_CACHE = ThumbnailCache(tmp_path / "shared", max_bytes=1024 * 1024)
    try:
        pixmap = load_thumbnail_pixmap(str(source), 12)
        assert pixmap is not None
        assert pixmap.width() == 12
        assert pixmap.height() == 6
        assert cache_module._DEFAULT_CACHE.stats()["count"] == 1
    finally:
        cache_module._DEFAULT_CACHE = original_cache
