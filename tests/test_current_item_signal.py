"""Scan-worker `current_item` signal — regression tests for the per-file
progress surface used by `ScanMixin._set_current_scan_item`.

We exercise the workers via `run()` directly (skipping `.start()`) so they
execute synchronously on the test thread — no QApplication or event loop
required. That also lets us collect emissions from a plain Python callback.
"""

from pathlib import Path

import pytest

from unifile.workers import ScanAepWorker, ScanCategoryWorker, ScanFilesWorker


@pytest.fixture(autouse=True)
def _disable_protected_paths(monkeypatch):
    """On Windows, pytest's tmp_path lives under %USERPROFILE%\\AppData\\Local\\Temp,
    which `is_protected()` treats as a system-protected directory — scans
    inside will skip every folder. Disable the check for these tests only."""
    import unifile.config as _cfg
    monkeypatch.setattr(_cfg, '_cached_protected_paths',
                        {'system': [], 'custom': [], 'enabled': False})


# ── Signal is declared on each worker ──────────────────────────────────────────

def test_scan_aep_worker_declares_current_item_signal():
    assert hasattr(ScanAepWorker, 'current_item')


def test_scan_category_worker_declares_current_item_signal():
    assert hasattr(ScanCategoryWorker, 'current_item')


def test_scan_files_worker_declares_current_item_signal():
    assert hasattr(ScanFilesWorker, 'current_item')


# ── End-to-end: workers emit one current_item per iteration ───────────────────

def _make_sample_tree(tmp_path: Path, n: int = 3) -> Path:
    """Create N subfolders the scan workers will enumerate."""
    root = tmp_path / "scan_root"
    root.mkdir()
    for i in range(n):
        sub = root / f"folder_{i:02d}"
        sub.mkdir()
        # Give ScanFilesWorker something to pick up per folder
        (sub / f"sample_{i}.txt").write_text("x", encoding="utf-8")
    return root


def test_scan_aep_worker_emits_folder_name_per_iteration(tmp_path):
    root = _make_sample_tree(tmp_path, n=3)
    emitted = []
    worker = ScanAepWorker(str(root), scan_depth=0)
    worker.current_item.connect(emitted.append)
    worker.run()
    assert emitted, "current_item should emit at least once"
    # Every emitted string should match one of the real folder names on disk
    real_names = {p.name for p in root.iterdir() if p.is_dir()}
    for name in emitted:
        assert name in real_names, f"unexpected current_item emission: {name!r}"


def test_scan_category_worker_emits_folder_name_per_iteration(tmp_path):
    root = _make_sample_tree(tmp_path, n=3)
    emitted = []
    worker = ScanCategoryWorker(str(root), str(tmp_path / "dest"), scan_depth=0)
    worker.current_item.connect(emitted.append)
    worker.run()
    assert emitted, "current_item should emit at least once"
    real_names = {p.name for p in root.iterdir() if p.is_dir()}
    for name in emitted:
        assert name in real_names


def test_scan_files_worker_emits_item_name_per_iteration(tmp_path):
    """ScanFilesWorker iterates files directly under `src` at depth 0."""
    root = tmp_path / "files_root"
    root.mkdir()
    for i in range(3):
        (root / f"sample_{i}.txt").write_text("x", encoding="utf-8")

    emitted = []
    worker = ScanFilesWorker(
        src_dir=str(root), dst_dir=str(tmp_path / "dst"),
        categories=[], scan_depth=0,
        check_hashes=False, include_folders=False, include_files=True,
    )
    worker.current_item.connect(emitted.append)
    worker.run()
    assert emitted, "current_item should emit at least once"
    real_files = {p.name for p in root.iterdir() if p.is_file()}
    for name in emitted:
        assert name in real_files, f"unexpected emission: {name!r}"


def test_cancelled_scan_aep_worker_emits_nothing(tmp_path):
    """Cancelling before run() should short-circuit before any emission."""
    root = _make_sample_tree(tmp_path, n=3)
    emitted = []
    worker = ScanAepWorker(str(root), scan_depth=0)
    worker.current_item.connect(emitted.append)
    worker.cancel()
    worker.run()
    assert emitted == []
