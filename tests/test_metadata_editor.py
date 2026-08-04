import json

import pytest

from unifile.metadata_editor import (
    apply_metadata_changes,
    apply_metadata_field_changes,
    preview_metadata_changes,
    read_editable_metadata,
    read_metadata_fields,
    undo_metadata_batch,
    undo_metadata_field_batch,
)
from unifile.xmp_writer import read_sidecar, write_editable_fields, write_sidecar


def test_editable_fields_round_trip_and_clear_marker(tmp_path):
    filepath = tmp_path / "capture.nef"
    filepath.write_bytes(b"raw-placeholder")

    assert write_sidecar(str(filepath), "Photo", tags=["camera"])
    assert write_editable_fields(str(filepath), {
        "title": "Sunset",
        "description": "Warm light",
        "keywords": "camera; sunset",
        "rating": "4",
    })
    values = read_editable_metadata(str(filepath))
    assert values["title"] == "Sunset"
    assert values["description"] == "Warm light"
    assert values["keywords"] == "camera; sunset"
    assert values["rating"] == "4"

    assert write_editable_fields(str(filepath), {"title": ""})
    assert read_editable_metadata(str(filepath))["title"] == ""
    assert read_sidecar(str(filepath))["fields"]["title"] == ""


def test_batch_changes_are_logged_and_field_level_undo_is_supported(tmp_path):
    filepath = tmp_path / "photo.jpg"
    filepath.write_bytes(b"image-placeholder")
    log_path = tmp_path / "embed_log.json"

    result = apply_metadata_changes([
        {"filepath": str(filepath), "field": "title", "new": "New title"},
        {"filepath": str(filepath), "field": "rating", "new": "5"},
    ], log_path=str(log_path))
    assert result["success"] == 2
    assert result["failed"] == 0
    assert result["batch_id"]
    assert read_editable_metadata(str(filepath))["title"] == "New title"
    assert read_editable_metadata(str(filepath))["rating"] == "5"

    one = undo_metadata_batch(
        result["batch_id"],
        fields={(str(filepath.resolve()), "title")},
        log_path=str(log_path),
    )
    assert one == {"restored": 1, "failed": 0, "status": "partially-undone"}
    values = read_editable_metadata(str(filepath))
    assert values["title"] == ""
    assert values["rating"] == "5"

    undone = undo_metadata_batch(result["batch_id"], log_path=str(log_path))
    assert undone["status"] == "undone"
    assert read_editable_metadata(str(filepath))["rating"] == ""
    record = json.loads(log_path.read_text(encoding="utf-8"))[0]
    assert record["type"] == "metadata_batch"
    assert record["status"] == "undone"


def _field(fields, key):
    return next(item for item in fields if item.key == key)


def test_raw_exif_preview_write_and_byte_exact_undo(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    piexif = pytest.importorskip("piexif")
    filepath = tmp_path / "photo.jpg"
    exif = {
        "0th": {piexif.ImageIFD.ImageDescription: b"Before"},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2024:01:02 03:04:05"},
    }
    Image.new("RGB", (4, 4), "white").save(
        filepath, format="JPEG", exif=piexif.dump(exif)
    )
    original = filepath.read_bytes()
    key = f"exif:0th:{piexif.ImageIFD.ImageDescription}"

    field = _field(read_metadata_fields(str(filepath)), key)
    assert field.value == "Before"
    assert field.writable
    preview = preview_metadata_changes(str(filepath), {key: "After"})
    assert preview["valid"]
    assert preview["changes"][0]["old"] == "Before"
    assert preview["changes"][0]["new"] == "After"
    assert filepath.read_bytes() == original

    log_path = tmp_path / "raw-log.json"
    result = apply_metadata_field_changes(
        str(filepath), {key: "After"},
        log_path=str(log_path), backup_dir=str(tmp_path / "backups"),
    )
    assert result["success"] == 1
    assert _field(read_metadata_fields(str(filepath)), key).value == "After"
    undone = undo_metadata_field_batch(result["batch_id"], log_path=str(log_path))
    assert undone == {"restored": 1, "failed": 0, "status": "undone"}
    assert filepath.read_bytes() == original


def test_raw_id3_and_pdf_fields_round_trip(tmp_path):
    id3 = pytest.importorskip("mutagen.id3")
    mp3 = tmp_path / "track.mp3"
    tags = id3.ID3()
    tags.add(id3.TIT2(encoding=3, text=["Old title"]))
    tags.add(id3.TPE1(encoding=3, text=["Old artist"]))
    tags.save(mp3)
    title_key = "id3:TIT2"
    assert _field(read_metadata_fields(str(mp3)), title_key).value == "Old title"
    result = apply_metadata_field_changes(
        str(mp3), {title_key: "New title"},
        log_path=str(tmp_path / "id3-log.json"), backup_dir=str(tmp_path / "backups"),
    )
    assert result["success"] == 1
    assert _field(read_metadata_fields(str(mp3)), title_key).value == "New title"

    pypdf = pytest.importorskip("pypdf")
    pdf = tmp_path / "document.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": "Old PDF title"})
    with pdf.open("wb") as stream:
        writer.write(stream)
    pdf_key = "pdf:/Title"
    assert _field(read_metadata_fields(str(pdf)), pdf_key).value == "Old PDF title"
    result = apply_metadata_field_changes(
        str(pdf), {pdf_key: "New PDF title"},
        log_path=str(tmp_path / "pdf-log.json"), backup_dir=str(tmp_path / "backups"),
    )
    assert result["success"] == 1
    assert _field(read_metadata_fields(str(pdf)), pdf_key).value == "New PDF title"


def test_raw_xmp_field_creates_sidecar_and_undo_removes_it(tmp_path):
    filepath = tmp_path / "capture.nef"
    filepath.write_bytes(b"raw-placeholder")
    key = "xmp:uf:Field_title"
    log_path = tmp_path / "xmp-log.json"
    result = apply_metadata_field_changes(
        str(filepath), {key: "Sidecar title"},
        log_path=str(log_path), backup_dir=str(tmp_path / "backups"),
    )
    assert result["success"] == 1
    assert _field(read_metadata_fields(str(filepath)), key).value == "Sidecar title"
    assert (tmp_path / "capture.nef.xmp").is_file()
    undone = undo_metadata_field_batch(result["batch_id"], log_path=str(log_path))
    assert undone["status"] == "undone"
    assert not (tmp_path / "capture.nef.xmp").exists()
