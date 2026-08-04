"""Coverage for the unified cleanup Sweep workflow."""
import os
import shutil


def test_scan_sweep_combines_candidates_without_duplicate_paths(tmp_path, monkeypatch):
    from unifile import cleanup

    empty = tmp_path / "empty"
    empty.mkdir()
    zero = tmp_path / "zero.txt"
    zero.touch()
    shortcut = tmp_path / "missing.lnk"

    monkeypatch.setattr(
        cleanup,
        "scan_orphaned_shortcuts",
        lambda _root, **_kwargs: [cleanup.CleanupItem(
            path=str(shortcut),
            reason="Target missing: C:/gone.txt",
            category="orphaned_shortcut",
        )],
    )

    results = cleanup.scan_sweep(str(tmp_path))

    assert {item.category for item in results} == {
        "empty_folder",
        "empty_file",
        "orphaned_shortcut",
    }
    assert len({os.path.normcase(item.path) for item in results}) == 3


def test_scan_sweep_prefers_orphaned_shortcut_over_zero_byte_duplicate(
    tmp_path, monkeypatch
):
    from unifile.cleanup import CleanupItem, scan_sweep

    shortcut = tmp_path / "missing.lnk"
    shortcut.touch()
    monkeypatch.setattr(
        "unifile.cleanup.scan_orphaned_shortcuts",
        lambda _root, **_kwargs: [CleanupItem(
            path=str(shortcut),
            reason="Target missing: C:/gone.txt",
            category="orphaned_shortcut",
        )],
    )

    results = scan_sweep(str(tmp_path))

    assert len(results) == 1
    assert results[0].category == "orphaned_shortcut"


def test_scan_sweep_applies_hidden_and_system_filters_to_all_categories(tmp_path):
    from unifile.cleanup import scan_sweep

    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "empty.txt").touch()
    system = tmp_path / "node_modules"
    system.mkdir()
    (system / "empty.txt").touch()

    assert scan_sweep(str(tmp_path)) == []
    assert len(scan_sweep(str(tmp_path), ignore_hidden=False, ignore_system=False)) == 2


def test_quarantine_items_returns_restore_operations_for_nested_empty_folders(
    tmp_path, monkeypatch
):
    from unifile.cleanup import CleanupItem, quarantine_items

    monkeypatch.setattr("unifile.cleanup.is_protected", lambda _path: False)
    source = tmp_path / "source"
    nested = source / "empty" / "deeper"
    nested.mkdir(parents=True)
    zero = source / "zero.txt"
    zero.touch()
    recovery = tmp_path / "recovery"
    items = [
        CleanupItem(path=str(source / "empty"), category="empty_folder"),
        CleanupItem(path=str(nested), category="empty_folder"),
        CleanupItem(path=str(zero), size=0, category="empty_file"),
    ]

    success, failed, freed, undo_ops = quarantine_items(
        items,
        recovery_dir=str(recovery),
    )

    assert (success, failed, freed) == (3, 0, 0)
    assert not (source / "empty").exists()
    assert not zero.exists()
    assert len(undo_ops) == 3
    assert all(op["type"] == "move" for op in undo_ops)
    assert all(os.path.exists(op["src"]) for op in undo_ops)

    for operation in reversed(undo_ops):
        os.makedirs(os.path.dirname(operation["dst"]), exist_ok=True)
        shutil.move(operation["src"], operation["dst"])

    assert nested.is_dir()
    assert zero.exists()
