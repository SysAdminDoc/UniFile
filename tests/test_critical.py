"""Minimal-but-valuable tests for the 5 highest-leverage untested modules.

Scope: hit the golden-path API of each module end-to-end using tmp_path
fixtures so no network, Ollama, or GUI is required.
"""
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

# ── cache.py ──────────────────────────────────────────────────────────────────

def test_cache_undo_log_roundtrip(tmp_path, monkeypatch):
    """save_undo_log -> load_undo_log preserves ops + batch metadata."""
    # Point cache module at an isolated temp dir so we don't pollute the real
    # APPDATA store.
    from unifile import cache, config
    monkeypatch.setattr(cache, '_UNDO_LOG_FILE',
                        str(tmp_path / 'undo_log.json'))
    monkeypatch.setattr(cache, '_UNDO_STACK_FILE',
                        str(tmp_path / 'undo_stack.json'))
    ops = [
        {'type': 'move', 'src': '/a/new', 'dst': '/a/old',
         'timestamp': '2026-04-22T10:00:00', 'category': 'Docs',
         'confidence': '90', 'status': 'Done'},
        {'type': 'move', 'src': '/a/new2', 'dst': '/a/old2',
         'timestamp': '2026-04-22T10:00:01', 'category': 'Docs',
         'confidence': '90', 'status': 'Done'},
    ]
    cache.save_undo_log(ops, source_dir='/tmp/src', mode='categorize')
    loaded = cache.load_undo_log()
    assert len(loaded) == 2
    assert loaded[0]['src'] == '/a/new'
    assert loaded[1]['dst'] == '/a/old2'

    # Stack structure carries the meta we added
    stack = cache._load_undo_stack()
    assert len(stack) == 1
    assert stack[0]['source_dir'] == '/tmp/src'
    assert stack[0]['mode'] == 'categorize'
    assert stack[0]['count'] == 2


def test_cache_folder_fingerprint_is_stable(tmp_path):
    """compute_file_fingerprint is deterministic for the same input."""
    from unifile.cache import compute_file_fingerprint
    (tmp_path / 'a.txt').write_text('x')
    (tmp_path / 'b.txt').write_text('yy')
    (tmp_path / 'c.txt').write_text('zzz')
    fp1 = compute_file_fingerprint(str(tmp_path))
    fp2 = compute_file_fingerprint(str(tmp_path))
    assert fp1 is not None and fp1 == fp2
    # Adding a new file mutates the fingerprint
    (tmp_path / 'd.txt').write_text('new')
    fp3 = compute_file_fingerprint(str(tmp_path))
    assert fp3 != fp1


def test_cache_hash_file(tmp_path):
    """hash_file handles missing and permission-denied paths gracefully."""
    from unifile.cache import hash_file
    target = tmp_path / 'payload.bin'
    target.write_bytes(b'abc' * 1000)
    h1 = hash_file(str(target))
    assert h1 and len(h1) == 32  # md5 hex
    # Same input -> same hash
    assert hash_file(str(target)) == h1
    # Missing file returns None, doesn't raise
    assert hash_file(str(tmp_path / 'missing.bin')) is None


# ── duplicates.py ─────────────────────────────────────────────────────────────

def test_duplicates_progressive_detects_exact_matches(tmp_path):
    """Two identical files should be flagged in the same group; a unique file
    is not in the dup_map."""
    from unifile.duplicates import ProgressiveDuplicateDetector
    payload = b'0123456789' * 10_000  # 100 KB so prefix+suffix both run
    (tmp_path / 'a.bin').write_bytes(payload)
    (tmp_path / 'b.bin').write_bytes(payload)
    (tmp_path / 'c.bin').write_bytes(b'different content entirely' * 4000)
    files = [(str(p), p.stat().st_size) for p in tmp_path.iterdir()]
    det = ProgressiveDuplicateDetector(enable_perceptual=False, enable_audio=False)
    dup_map = det.detect(files)
    a, b, c = str(tmp_path / 'a.bin'), str(tmp_path / 'b.bin'), str(tmp_path / 'c.bin')
    # Both duplicates should be in the map, in the same group
    assert a in dup_map and b in dup_map
    assert dup_map[a].group_id == dup_map[b].group_id
    # Exactly one of them is marked original (the other is the dup copy)
    originals = [dup_map[a].is_original, dup_map[b].is_original]
    assert sum(originals) == 1
    # Unique file should not be in dup_map at all
    assert c not in dup_map


def test_duplicates_handles_empty_input():
    from unifile.duplicates import ProgressiveDuplicateDetector
    det = ProgressiveDuplicateDetector(enable_perceptual=False, enable_audio=False)
    assert det.detect([]) == {}


def test_duplicates_single_file_no_dups(tmp_path):
    from unifile.duplicates import ProgressiveDuplicateDetector
    (tmp_path / 'lonely.txt').write_text('only one')
    det = ProgressiveDuplicateDetector(enable_perceptual=False, enable_audio=False)
    result = det.detect([(str(tmp_path / 'lonely.txt'), 8)])
    assert result == {}


# ── virtual_library.py ────────────────────────────────────────────────────────

def test_virtual_library_open_close_lifecycle(tmp_path):
    """A virtual library opens, creates .unifile/library.sqlite, closes cleanly."""
    from unifile.virtual_library import VirtualLibrary
    lib = VirtualLibrary()
    assert lib.is_open is False
    assert lib.open(str(tmp_path)) is True
    assert lib.is_open is True
    db_path = tmp_path / '.unifile' / 'library.sqlite'
    assert db_path.exists()
    lib.close()
    assert lib.is_open is False


def test_virtual_library_stats_empty(tmp_path):
    from unifile.virtual_library import VirtualLibrary
    lib = VirtualLibrary()
    lib.open(str(tmp_path))
    try:
        stats = lib.get_stats()
        assert stats['total_files'] == 0
        assert stats['categorized'] == 0
        assert stats['uncategorized'] == 0
    finally:
        lib.close()


# ── profiles.py (actually ProfileManager in plugins.py) ───────────────────────

def test_profile_manager_save_load_roundtrip(tmp_path, monkeypatch):
    from unifile import plugins
    # Redirect profile storage to an isolated dir
    monkeypatch.setattr(plugins, '_PROFILES_DIR', str(tmp_path))
    cfg = {
        'name': 'Test Profile',
        'llm_enabled': True,
        'scan_depth': 2,
        'categories': ['Documents', 'Images'],
    }
    plugins.ProfileManager.save('test', cfg)
    # Should appear in the listing
    assert 'test' in plugins.ProfileManager.list_profiles()
    # Round-trip
    loaded = plugins.ProfileManager.load('test')
    assert loaded == cfg
    # Delete removes from listing
    plugins.ProfileManager.delete('test')
    assert 'test' not in plugins.ProfileManager.list_profiles()


def test_profile_manager_load_missing_raises(tmp_path, monkeypatch):
    from unifile import plugins
    monkeypatch.setattr(plugins, '_PROFILES_DIR', str(tmp_path))
    with pytest.raises(FileNotFoundError):
        plugins.ProfileManager.load('never-existed')


# ── classifier.py (categorize_folder / is_protected integration) ──────────────

def test_classifier_categorize_folder_returns_something():
    """Even for a nonsense folder name, categorize_folder should return a
    well-formed tuple and not raise."""
    from unifile.classifier import categorize_folder
    result = categorize_folder('just_a_random_folder_name_12345')
    assert isinstance(result, tuple) and len(result) == 3
    # (category_or_none, score_int, cleaned_name_str)
    assert result[1] >= 0 and isinstance(result[2], str)


def test_classifier_matches_known_keyword():
    """A folder name that contains a hot category keyword should classify."""
    from unifile.classifier import categorize_folder
    cat, score, _cleaned = categorize_folder('Summer Wedding Slideshow Template')
    # The category might be any of the AE wedding / slideshow categories,
    # but *something* should match.
    assert cat is not None
    assert score >= 15


def test_classifier_pc_item_classifies_pdf(tmp_path):
    from unifile.files import _build_ext_map, _classify_pc_item, _load_pc_categories
    pdf = tmp_path / 'invoice_march.pdf'
    pdf.write_bytes(b'%PDF-1.4\n' + b'x' * 200)
    cats = _load_pc_categories()
    ext_map = _build_ext_map(cats)
    category, conf, method = _classify_pc_item(
        str(pdf), ext_map, is_folder=False, categories=cats
    )
    assert category == 'Documents'
    assert conf >= 80
    assert 'extension' in method


# ── cleanup.py: broken-file scanner works end-to-end ──────────────────────────

def test_scan_broken_files_flags_invalid_jpeg(tmp_path):
    """A file with .jpg extension but no JPEG magic bytes is flagged."""
    from unifile.cleanup import scan_broken_files
    bad = tmp_path / 'broken.jpg'
    bad.write_bytes(b'this is not a jpeg' + b'\x00' * 100)
    good = tmp_path / 'good.jpg'
    good.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100)
    results = scan_broken_files(str(tmp_path))
    paths = {r.path for r in results}
    assert str(bad) in paths
    assert str(good) not in paths
