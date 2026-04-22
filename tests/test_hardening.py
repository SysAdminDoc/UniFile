"""Regression tests for the v9.0.1 hardening pass.

These tests lock in fixes for:
 - Missing module-level imports (files.py, workers.py, engine.py, etc.)
 - safe_merge_move backup collision handling
 - is_protected() basename + parent-segment matching
 - Ollama URL trailing-slash normalization
 - scan_empty_folders O(n^2) avoidance + symlink handling
 - EventGrouper.suggest_event_name no longer NameErrors on Counter
"""
import os
import tempfile
from pathlib import Path

import pytest


# ── Module-level import smoke tests ───────────────────────────────────────────
# These catch missing imports that would only surface under rare code paths.

def test_files_module_has_time_mimetypes_rapidfuzz():
    from unifile import files as _files
    assert hasattr(_files, 'time')
    assert hasattr(_files, '_mimetypes')
    # HAS_RAPIDFUZZ must be importable (even if False on this platform)
    assert hasattr(_files, 'HAS_RAPIDFUZZ')


def test_workers_module_imports_photo_scenes_and_haz_flags():
    from unifile import workers as _w
    assert hasattr(_w, 'HAS_CV2')
    assert hasattr(_w, 'HAS_FACE_RECOGNITION')
    assert hasattr(_w, '_PHOTO_SCENES')
    assert hasattr(_w, '_extract_file_content')


def test_engine_counter_imported_for_event_grouper():
    from unifile.engine import EventGrouper
    # Previously raised NameError: name 'Counter' is not defined
    name = EventGrouper.suggest_event_name([
        "A beautiful sunset at the beach",
        "Sunset over the beach with friends",
        "Beach evening sunset panorama",
    ])
    assert isinstance(name, str)
    assert name  # non-empty
    # Expected behaviour: top tokens should include "sunset" or "beach"
    assert any(word in name.lower() for word in ('sunset', 'beach'))


def test_event_grouper_handles_empty_and_short_descriptions():
    from unifile.engine import EventGrouper
    assert EventGrouper.suggest_event_name([]) == "Unknown Event"
    # No useful tokens (all stopwords or too-short)
    result = EventGrouper.suggest_event_name(["a an the", "is it or"])
    assert isinstance(result, str)


def test_dialogs_exports_csvrulesdialog():
    """Regression: UniFile main_window imported CsvRulesDialog but it
    wasn't re-exported from unifile.dialogs, crashing on startup."""
    import unifile.dialogs as _d
    assert 'CsvRulesDialog' in _d.__all__
    assert hasattr(_d, 'CsvRulesDialog')


# ── is_protected hardening ────────────────────────────────────────────────────

def test_is_protected_empty_path_is_false():
    from unifile.config import is_protected
    assert is_protected('') is False


def test_is_protected_basename_match_inside_parent():
    """.git/config should be protected because .git is a protected basename."""
    from unifile.config import is_protected
    # Use a non-system path so only basename rules apply
    path = os.path.join(tempfile.gettempdir(), 'someproj', '.git', 'config')
    # Create the hierarchy briefly for realism; is_protected doesn't need the file to exist
    assert is_protected(path) is True


# ── safe_merge_move backup collision ──────────────────────────────────────────

def test_unique_backup_path_avoids_collision(tmp_path):
    from unifile.workers import _unique_backup_path
    target = tmp_path / 'x.txt'
    target.write_text('orig')
    bak1 = tmp_path / 'x.txt.bak'
    bak1.write_text('stale')
    result = _unique_backup_path(str(target))
    assert result != str(bak1)
    assert not os.path.exists(result)


def test_safe_merge_move_skips_same_path(tmp_path):
    from unifile.workers import safe_merge_move
    folder = tmp_path / 'dir'
    folder.mkdir()
    (folder / 'a.txt').write_text('x')
    merged, skipped = safe_merge_move(str(folder), str(folder))
    # Should refuse to merge a directory into itself (would wipe data)
    assert merged == 0 and skipped == 0
    # Original content still present
    assert (folder / 'a.txt').exists()


# ── Ollama URL normalization ──────────────────────────────────────────────────

def test_normalize_ollama_url_strips_trailing_slash():
    from unifile.ollama import _normalize_ollama_url
    assert _normalize_ollama_url('http://localhost:11434/') == 'http://localhost:11434'
    assert _normalize_ollama_url('http://localhost:11434///') == 'http://localhost:11434'
    assert _normalize_ollama_url('') == 'http://localhost:11434'
    assert _normalize_ollama_url('   ') == 'http://localhost:11434'
    assert _normalize_ollama_url('http://example.com:8080') == 'http://example.com:8080'


# ── Cleanup scan_empty_folders fast-path ──────────────────────────────────────

def test_scan_empty_folders_detects_nested_empty_tree(tmp_path):
    from unifile.cleanup import scan_empty_folders
    (tmp_path / 'empty').mkdir()
    (tmp_path / 'empty' / 'deeper').mkdir()
    (tmp_path / 'empty' / 'deeper' / 'deepest').mkdir()
    (tmp_path / 'has_file').mkdir()
    (tmp_path / 'has_file' / 'x.txt').write_text('hi')
    found = scan_empty_folders(str(tmp_path))
    found_paths = {os.path.basename(r.path) for r in found}
    # Every folder in the "empty" subtree should be flagged
    assert {'empty', 'deeper', 'deepest'}.issubset(found_paths)
    # has_file should NOT be flagged
    assert 'has_file' not in found_paths


def test_scan_empty_folders_does_not_flag_root(tmp_path):
    from unifile.cleanup import scan_empty_folders
    # Only root, no children — root should never be flagged
    found = scan_empty_folders(str(tmp_path))
    assert not any(r.path == str(tmp_path) for r in found)


# ── IgnoreFilter: is_dir flag now honoured for directory patterns ─────────────

def test_ignore_filter_dir_only_pattern_matches_dir():
    from unifile.ignore import IgnoreFilter
    filt = IgnoreFilter()
    filt.add_pattern('build/')
    assert filt.is_ignored('build', is_dir=True) is True
    # The pattern is directory-only — as a file, it should not match
    # (gitignore semantics). We test the is_dir=True path works.
    assert filt.is_ignored('src/build', is_dir=True) is True
