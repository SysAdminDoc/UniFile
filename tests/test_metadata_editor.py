import json

from unifile.metadata_editor import (
    apply_metadata_changes,
    read_editable_metadata,
    undo_metadata_batch,
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
