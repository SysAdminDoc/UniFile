import zipfile

from unifile.tagging.library import TagLibrary


def _open_library(path):
    library = TagLibrary(str(path))
    assert library.open()
    return library


def test_collection_membership_and_zip_export_do_not_move_sources(tmp_path):
    library = _open_library(tmp_path / "library")
    try:
        first_path = tmp_path / "library" / "first.txt"
        second_path = tmp_path / "library" / "nested" / "first.txt"
        first_path.parent.mkdir(parents=True, exist_ok=True)
        second_path.parent.mkdir(parents=True, exist_ok=True)
        first_path.write_text("one", encoding="utf-8")
        second_path.write_text("two", encoding="utf-8")
        first = library.add_entry(str(first_path))
        second = library.add_entry(str(second_path))
        assert first and second

        collection = library.create_entry_group("Review board", "blue")
        assert library.add_entries_to_group(collection.id, [first.id, second.id])
        assert {entry.id for entry in library.get_group_entries(collection.id)} == {
            first.id,
            second.id,
        }

        archive_path = tmp_path / "exports" / "review.zip"
        result = library.export_entry_group(collection.id, str(archive_path))
        assert result["exported"] == 2
        assert result["failed"] == 0
        assert first_path.is_file()
        assert second_path.is_file()
        with zipfile.ZipFile(archive_path) as archive:
            assert set(archive.namelist()) == {"first.txt", "first (2).txt"}
    finally:
        library.close()


def test_collection_export_skips_missing_members_and_rejects_overwrite(tmp_path):
    library = _open_library(tmp_path / "library")
    try:
        present_path = tmp_path / "library" / "present.txt"
        present_path.write_text("present", encoding="utf-8")
        present = library.add_entry(str(present_path))
        missing = library.add_entry(str(tmp_path / "library" / "missing.txt"))
        assert present and missing
        collection = library.create_entry_group("Mixed")
        library.add_entries_to_group(collection.id, [present.id, missing.id])

        archive_path = tmp_path / "mixed.zip"
        first = library.export_entry_group(collection.id, str(archive_path))
        assert first["exported"] == 1
        assert first["skipped"] == 1
        second = library.export_entry_group(collection.id, str(archive_path))
        assert second["failed"] == 1
        assert library.export_entry_group(collection.id, str(tmp_path / "bad.out"), "unknown")["failed"] == 1
    finally:
        library.close()
