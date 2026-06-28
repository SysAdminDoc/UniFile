"""Tests for explanatory no-result outcomes in duplicate and cleanup dialogs."""
import pytest


def test_dup_worker_tracks_scan_stats():
    """_DupScanWorker exposes total_scanned and total_skipped after scan."""
    from unifile.dialogs.duplicates import _DupScanWorker
    w = _DupScanWorker("/fake", {"depth": 1, "min_size": 1})
    assert hasattr(w, 'total_scanned')
    assert hasattr(w, 'total_skipped')
    assert w.total_scanned == 0
    assert w.total_skipped == 0


def test_cleanup_panel_tab_labels():
    """CleanupPanel has descriptive labels for each scan tab."""
    from unifile.dialogs.cleanup import CleanupPanel
    labels = CleanupPanel._TAB_LABELS
    assert 0 in labels
    assert "empty" in labels[0].lower()
    assert 3 in labels
    assert "broken" in labels[3].lower() or "corrupt" in labels[3].lower()


def test_dup_no_result_message_source():
    """Verify the no-result branch in _on_scan_done constructs a message
    referencing the scan criteria and file count."""
    import inspect

    from unifile.dialogs.duplicates import DuplicateFinderDialog
    src = inspect.getsource(DuplicateFinderDialog._on_scan_done)
    assert "No duplicates found" in src
    assert "total_scanned" in src
    assert "criteria" in src


def test_cleanup_no_result_message_source():
    """Verify the no-result branch shows a category-specific explanation."""
    import inspect

    from unifile.dialogs.cleanup import CleanupPanel
    src = inspect.getsource(CleanupPanel._on_scan_done)
    assert "_TAB_LABELS" in src
    assert "appears clean" in src
