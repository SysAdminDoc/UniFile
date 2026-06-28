"""Tests for TagSpaces .ts sidecar import/export."""
import json
import os

import pytest

from unifile.tagspaces import (
    dry_run_import,
    extract_description,
    extract_tag_colors,
    extract_tags,
    read_sidecar,
    scan_directory_sidecars,
    write_sidecar,
)

# ── Read/write sidecars ──────────────────────────────────────────────────────

def test_write_and_read_sidecar(tmp_path):
    f = tmp_path / "invoice.pdf"
    f.write_bytes(b"%PDF-1.4")
    sc = write_sidecar(str(f), ["finance", "2024"], description="Monthly invoice")
    assert sc.exists()
    assert sc.parent.name == ".ts"
    data = read_sidecar(str(f))
    assert data is not None
    assert len(data["tags"]) == 2
    assert data["tags"][0]["title"] == "finance"
    assert data["description"] == "Monthly invoice"


def test_read_sidecar_missing(tmp_path):
    f = tmp_path / "missing.txt"
    f.write_text("data")
    assert read_sidecar(str(f)) is None


def test_write_sidecar_with_colors(tmp_path):
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"\xff\xd8")
    write_sidecar(str(f), ["vacation"], tag_colors={"vacation": "#4fc3f7"})
    data = read_sidecar(str(f))
    assert data["tags"][0]["color"] == "#4fc3f7"
    assert data["tags"][0]["textcolor"] == "#ffffff"


def test_write_sidecar_preserves_existing_fields(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    ts_dir = tmp_path / ".ts"
    ts_dir.mkdir()
    (ts_dir / "doc.txt.json").write_text(
        json.dumps({"id": "custom-id", "tags": [], "description": "old"}),
        encoding="utf-8"
    )
    write_sidecar(str(f), ["new-tag"], description="updated")
    data = read_sidecar(str(f))
    assert data["id"] == "custom-id"
    assert data["description"] == "updated"
    assert data["tags"][0]["title"] == "new-tag"


# ── Extract helpers ──────────────────────────────────────────────────────────

def test_extract_tags():
    data = {"tags": [{"title": "a", "type": "sidecar"}, {"title": "b"}]}
    assert extract_tags(data) == ["a", "b"]


def test_extract_tags_empty():
    assert extract_tags({}) == []
    assert extract_tags({"tags": [{}]}) == []


def test_extract_description():
    assert extract_description({"description": "hello"}) == "hello"
    assert extract_description({}) == ""


def test_extract_tag_colors():
    data = {"tags": [{"title": "x", "color": "#ff0000"}, {"title": "y"}]}
    colors = extract_tag_colors(data)
    assert colors == {"x": "#ff0000"}


# ── Directory scanning ───────────────────────────────────────────────────────

def test_scan_directory_sidecars(tmp_path):
    f1 = tmp_path / "a.txt"
    f1.write_text("file a")
    f2 = tmp_path / "b.pdf"
    f2.write_bytes(b"%PDF")
    ts = tmp_path / ".ts"
    ts.mkdir()
    (ts / "a.txt.json").write_text(
        json.dumps({"tags": [{"title": "tag1"}]}), encoding="utf-8"
    )
    (ts / "b.pdf.json").write_text(
        json.dumps({"tags": [{"title": "tag2"}], "description": "a pdf"}),
        encoding="utf-8"
    )
    # Orphan sidecar (no matching original) — should be skipped
    (ts / "ghost.png.json").write_text(
        json.dumps({"tags": [{"title": "nope"}]}), encoding="utf-8"
    )
    results = scan_directory_sidecars(str(tmp_path))
    paths = [r[0] for r in results]
    assert len(results) == 2
    assert str(f1) in paths
    assert str(f2) in paths


def test_scan_skips_tsm_tsl(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x")
    ts = tmp_path / ".ts"
    ts.mkdir()
    (ts / "tsm.json").write_text("{}", encoding="utf-8")
    (ts / "tsl.json").write_text("{}", encoding="utf-8")
    (ts / "x.txt.json").write_text(
        json.dumps({"tags": [{"title": "real"}]}), encoding="utf-8"
    )
    results = scan_directory_sidecars(str(tmp_path))
    assert len(results) == 1


# ── Dry-run import ───────────────────────────────────────────────────────────

def test_dry_run_import(tmp_path):
    f = tmp_path / "report.docx"
    f.write_bytes(b"PK")
    write_sidecar(str(f), ["work", "Q1"], description="Q1 report")
    preview = dry_run_import(str(tmp_path))
    assert len(preview) == 1
    assert preview[0]["tags"] == ["work", "Q1"]
    assert preview[0]["description"] == "Q1 report"


def test_dry_run_import_empty_dir(tmp_path):
    assert dry_run_import(str(tmp_path)) == []


# ── Malformed sidecars ───────────────────────────────────────────────────────

def test_read_sidecar_malformed_json(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("data")
    ts = tmp_path / ".ts"
    ts.mkdir()
    (ts / "bad.txt.json").write_text("not json!", encoding="utf-8")
    assert read_sidecar(str(f)) is None


def test_read_sidecar_non_dict(tmp_path):
    f = tmp_path / "arr.txt"
    f.write_text("data")
    ts = tmp_path / ".ts"
    ts.mkdir()
    (ts / "arr.txt.json").write_text("[1,2,3]", encoding="utf-8")
    assert read_sidecar(str(f)) is None
