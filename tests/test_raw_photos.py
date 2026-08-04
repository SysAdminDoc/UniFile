"""Coverage for RAW/JPEG logical families and EXIF-first metadata."""

from pathlib import Path
from types import SimpleNamespace

from unifile.raw_photos import (
    RawPhotoFamily,
    collapse_raw_photo_pairs,
    extract_raw_photo_metadata,
    group_raw_photo_families,
)
from unifile.workers import ApplyFilesWorker, ScanFilesWorker


def test_group_raw_photo_families_is_case_insensitive_and_directory_scoped(tmp_path):
    raw = tmp_path / "IMG_0001.CR2"
    jpeg = tmp_path / "img_0001.JPEG"
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    unrelated = other_dir / "IMG_0001.jpg"

    families = group_raw_photo_families([raw, jpeg, unrelated])

    assert families == [RawPhotoFamily(raw_path=raw, jpeg_path=jpeg)]
    collapsed, lookup = collapse_raw_photo_pairs([
        (raw, False), (jpeg, False), (unrelated, False)
    ])
    assert collapsed == [(raw, False), (unrelated, False)]
    assert lookup[str(raw.resolve()).casefold()].is_paired


def test_raw_metadata_wins_and_jpeg_fills_missing_fields(tmp_path):
    raw = tmp_path / "IMG_0002.nef"
    jpeg = tmp_path / "IMG_0002.jpg"
    calls = []

    class FakeExtractor:
        @staticmethod
        def extract(path, log_cb=None):
            calls.append(Path(path).suffix.lower())
            if Path(path).suffix.lower() == ".nef":
                return {"_type": "image", "date_taken": "2026:08:03 12:00:00", "camera_model": "RAW body"}
            return {"_type": "image", "date_taken": "", "camera_model": "JPEG body", "width": 6000}

    metadata = extract_raw_photo_metadata(raw, jpeg, extractor=FakeExtractor)

    assert calls == [".nef", ".jpg"]
    assert metadata["date_taken"] == "2026:08:03 12:00:00"
    assert metadata["camera_model"] == "RAW body"
    assert metadata["width"] == 6000
    assert metadata["_metadata_source"] == "raw+jpeg-fallback"
    assert metadata["raw_family_paths"] == [str(raw), str(jpeg)]


def test_scan_collection_collapses_paired_jpeg(tmp_path):
    raw = tmp_path / "DSC_0100.dng"
    jpeg = tmp_path / "DSC_0100.jpg"
    raw.write_bytes(b"raw")
    jpeg.write_bytes(b"jpeg")
    worker = ScanFilesWorker(
        str(tmp_path), "", [{"name": "Images", "extensions": ["dng", "jpg"]}],
        include_folders=False, include_files=True,
    )

    items = worker._collect(tmp_path)

    assert items == [(raw, False)]
    family = worker._raw_families[str(raw.resolve()).casefold()]
    assert family.raw_path == raw
    assert family.jpeg_path == jpeg


def test_apply_worker_moves_raw_and_jpeg_as_one_item(tmp_path, monkeypatch):
    monkeypatch.setattr("unifile.workers.is_protected", lambda _path: False)
    source = tmp_path / "source"
    destination = tmp_path / "organized"
    source.mkdir()
    raw = source / "IMG_0003.ARW"
    jpeg = source / "IMG_0003.JPG"
    raw.write_bytes(b"raw")
    jpeg.write_bytes(b"jpeg")
    item = SimpleNamespace(
        full_src=str(raw),
        full_dst=str(destination / raw.name),
        is_folder=False,
        name=raw.name,
        display_name=raw.name,
        category="Images",
        confidence=90,
        metadata={"raw_family_paths": [str(raw), str(jpeg)]},
        rename_template="",
        rename_source="",
    )
    finished = []
    worker = ApplyFilesWorker([(0, item)])
    worker.finished.connect(lambda ok, err, undo_ops: finished.append((ok, err, undo_ops)))

    worker.run()

    assert not raw.exists()
    assert not jpeg.exists()
    assert (destination / raw.name).read_bytes() == b"raw"
    assert (destination / jpeg.name).read_bytes() == b"jpeg"
    assert finished[0][0:2] == (1, 0)
    assert {Path(op["src"]).suffix.upper() for op in finished[0][2]} == {".ARW", ".JPG"}
