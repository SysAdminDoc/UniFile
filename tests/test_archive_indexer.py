"""Archive indexing and safe extraction regression coverage."""

import os
import zipfile

import pytest

from unifile import archive_indexer, profiles


@pytest.fixture
def isolated_archive_db(tmp_path, monkeypatch):
    old_conn = archive_indexer._db_conn
    if old_conn is not None:
        old_conn.close()
    monkeypatch.setattr(archive_indexer, "_db_conn", None)
    monkeypatch.setattr(archive_indexer, "_APP_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(
        archive_indexer, "_DB_PATH", str(tmp_path / "app" / "archive.sqlite"))
    yield tmp_path
    conn = archive_indexer._db_conn
    if conn is not None:
        conn.close()
    archive_indexer._db_conn = None


def _write_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def test_scan_and_search_archive_entries(isolated_archive_db):
    archive_path = isolated_archive_db / "2024-Invoices.zip"
    _write_zip(archive_path, {"incoming/invoice.pdf": b"pdf", "notes.txt": b"notes"})

    result = archive_indexer.scan_file(str(archive_path), force=True)

    assert {entry.inner_path for entry in result.entries} == {
        "incoming/invoice.pdf", "notes.txt"
    }
    matches = archive_indexer.search("invoice")
    assert len(matches) == 1
    assert archive_indexer.archive_breadcrumb(matches[0]) == (
        "invoice.pdf (inside 2024-Invoices.zip)"
    )


def test_extraction_rejects_traversal_and_cleans_temp(isolated_archive_db):
    archive_path = isolated_archive_db / "unsafe.zip"
    _write_zip(archive_path, {"safe.txt": b"safe", "../escaped.txt": b"nope"})
    temp_root = isolated_archive_db / "temp"

    with pytest.raises(archive_indexer.ArchiveExtractionError, match="traversal"):
        with archive_indexer.extracted_archive(
            str(archive_path), temp_root=str(temp_root)
        ):
            pytest.fail("unsafe archive unexpectedly extracted")

    assert not (isolated_archive_db / "escaped.txt").exists()
    assert list(temp_root.iterdir()) == []


def test_extract_classify_and_repack_round_trip(isolated_archive_db):
    archive_path = isolated_archive_db / "source.zip"
    _write_zip(archive_path, {"docs/invoice.pdf": b"pdf", "readme.txt": b"readme"})
    temp_root = isolated_archive_db / "temp"
    seen = []

    def classifier(file_path, inner_path):
        assert os.path.isfile(file_path)
        seen.append(inner_path)
        return {"category": "Documents"}

    results = archive_indexer.classify_extracted_archive(
        str(archive_path), classifier, temp_root=str(temp_root)
    )
    assert [item["inner_path"] for item in results] == ["docs/invoice.pdf", "readme.txt"]
    assert seen == ["docs/invoice.pdf", "readme.txt"]
    assert list(temp_root.iterdir()) == []

    with archive_indexer.extracted_archive(str(archive_path), temp_root=str(temp_root)) as root:
        destination = isolated_archive_db / "repacked.zip"
        archive_indexer.repack_archive(root, str(destination))

    with zipfile.ZipFile(destination) as repacked:
        assert {name for name in repacked.namelist() if not name.endswith("/")} == {
            "docs/invoice.pdf", "readme.txt"
        }
    assert list(temp_root.iterdir()) == []


def test_archive_mode_is_persisted_per_profile(tmp_path, monkeypatch):
    profile_file = tmp_path / "active-profile.json"
    monkeypatch.setattr(profiles, "_PROFILES_FILE", str(profile_file))
    monkeypatch.setattr(profiles, "_active_profile_name", "General Files")

    assert profiles.get_archive_mode() == profiles.ARCHIVE_MODE_INDEX
    assert profiles.set_archive_mode(profiles.ARCHIVE_MODE_EXTRACT)
    assert profiles.get_archive_mode() == profiles.ARCHIVE_MODE_EXTRACT

    profiles.set_active_profile("Design Assets")
    assert profiles.get_archive_mode() == profiles.ARCHIVE_MODE_INDEX
    profiles.set_active_profile("General Files")
    assert profiles.get_archive_mode() == profiles.ARCHIVE_MODE_EXTRACT
