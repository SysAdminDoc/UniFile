from pathlib import Path

from unifile.tagging.library import TagLibrary


def _open_library(path: Path) -> TagLibrary:
    library = TagLibrary(str(path))
    assert library.open()
    return library


def _status_for(library: TagLibrary, path: Path) -> dict:
    normalized = str(path.absolute()).lower()
    return next(
        status for status in library.get_root_statuses()
        if status["path"].lower() == normalized
    )


def test_entries_use_the_most_specific_configured_root(tmp_path):
    library_root = tmp_path / "library"
    secondary_root = tmp_path / "secondary"
    nested_root = secondary_root / "nested"
    nested_root.mkdir(parents=True)
    library = _open_library(library_root)
    try:
        assert library.add_root(str(secondary_root))
        root_file = library_root / "root.txt"
        secondary_file = secondary_root / "secondary.txt"
        nested_file = nested_root / "nested.txt"
        for file_path in (root_file, secondary_file, nested_file):
            file_path.write_text(file_path.name, encoding="utf-8")

        root_entry = library.add_entry(str(root_file))
        secondary_entry = library.add_entry(str(secondary_file))
        nested_entry = library.add_entry(str(nested_file))
        assert root_entry and secondary_entry and nested_entry
        assert root_entry.folder_id != secondary_entry.folder_id

        assert library.add_root(str(nested_root))
        nested_again = library.add_entry(str(nested_file))
        assert nested_again and nested_again.id == nested_entry.id
        assert nested_again.folder_id != secondary_entry.folder_id
        assert _status_for(library, secondary_root)["entry_count"] == 1
        assert _status_for(library, nested_root)["entry_count"] == 1
    finally:
        library.close()


def test_root_statuses_and_empty_root_removal(tmp_path):
    library = _open_library(tmp_path / "library")
    try:
        offline_root = tmp_path / "offline"
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        assert library.add_root(str(offline_root))
        assert library.add_root(str(empty_root))
        statuses = library.get_root_statuses()
        assert _status_for(library, offline_root)["state"] == "offline"
        assert _status_for(library, empty_root)["state"] == "online"
        assert len(statuses) == 3

        empty_id = _status_for(library, empty_root)["id"]
        assert library.remove_root(empty_id)
        assert not any(status["id"] == empty_id for status in library.get_root_statuses())
        default_id = _status_for(library, tmp_path / "library")["id"]
        assert not library.remove_root(default_id)
    finally:
        library.close()


def test_relink_offline_root_updates_entry_paths(tmp_path):
    library = _open_library(tmp_path / "library")
    old_root = tmp_path / "old-drive"
    old_nested = old_root / "nested"
    old_nested.mkdir(parents=True)
    old_file = old_nested / "report.pdf"
    old_file.write_text("report", encoding="utf-8")
    new_root = tmp_path / "new-drive"
    new_nested = new_root / "nested"
    new_nested.mkdir(parents=True)
    new_file = new_nested / old_file.name
    try:
        assert library.add_root(str(old_root))
        entry = library.add_entry(str(old_file))
        assert entry
        old_root_id = _status_for(library, old_root)["id"]

        old_file.replace(new_file)
        old_nested.rmdir()
        old_root.rmdir()
        assert _status_for(library, old_root)["state"] == "offline"

        result = library.relink_root(old_root_id, str(new_root))
        assert result == {"updated": 1, "failed": 0, "error": ""}
        relinked = library.get_entry(entry.id)
        assert relinked and relinked.path == new_file
        assert not library.scan_broken_links()
        assert _status_for(library, new_root)["entry_count"] == 1
    finally:
        library.close()
