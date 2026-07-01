"""Tests for TagSpaces .ts sidecar import/export."""
import json
import os

import pytest

from unifile.tagspaces import (
    dry_run_import,
    dry_run_import_folders,
    export_saved_searches,
    extract_description,
    extract_tag_colors,
    extract_tags,
    import_saved_searches,
    parse_saved_search,
    read_folder_metadata,
    read_saved_searches_file,
    read_sidecar,
    scan_directory_sidecars,
    scan_folder_metadata,
    write_folder_metadata,
    write_saved_searches_file,
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


# ── Folder metadata (.ts/tsm.json) ─────────────────────────────────────────

def test_write_and_read_folder_metadata(tmp_path):
    sub = tmp_path / "photos"
    sub.mkdir()
    tsm = write_folder_metadata(str(sub), ["vacation", "2024"],
                                description="Summer trip")
    assert tsm.name == "tsm.json"
    assert tsm.parent.name == ".ts"
    data = read_folder_metadata(str(sub))
    assert data is not None
    assert len(data["tags"]) == 2
    assert data["tags"][0]["title"] == "vacation"
    assert data["description"] == "Summer trip"


def test_read_folder_metadata_missing(tmp_path):
    assert read_folder_metadata(str(tmp_path)) is None


def test_write_folder_metadata_with_colors(tmp_path):
    sub = tmp_path / "docs"
    sub.mkdir()
    write_folder_metadata(str(sub), ["work"], tag_colors={"work": "#e57373"})
    data = read_folder_metadata(str(sub))
    assert data["tags"][0]["color"] == "#e57373"


def test_write_folder_metadata_preserves_existing(tmp_path):
    sub = tmp_path / "archive"
    sub.mkdir()
    ts_dir = sub / ".ts"
    ts_dir.mkdir()
    (ts_dir / "tsm.json").write_text(
        json.dumps({"id": "folder-uuid", "perspective": "grid",
                    "tags": [], "description": "old"}),
        encoding="utf-8"
    )
    write_folder_metadata(str(sub), ["archived"], description="new desc")
    data = read_folder_metadata(str(sub))
    assert data["id"] == "folder-uuid"
    assert data["perspective"] == "grid"
    assert data["description"] == "new desc"
    assert data["tags"][0]["title"] == "archived"


def test_scan_folder_metadata(tmp_path):
    d1 = tmp_path / "a"
    d1.mkdir()
    d2 = tmp_path / "b"
    d2.mkdir()
    write_folder_metadata(str(d1), ["tag1"])
    write_folder_metadata(str(d2), ["tag2"], description="folder b")
    results = scan_folder_metadata(str(tmp_path))
    assert len(results) == 2
    paths = [r[0] for r in results]
    assert str(d1) in paths
    assert str(d2) in paths


def test_dry_run_import_folders(tmp_path):
    sub = tmp_path / "project"
    sub.mkdir()
    ts_dir = sub / ".ts"
    ts_dir.mkdir()
    (ts_dir / "tsm.json").write_text(
        json.dumps({"tags": [{"title": "important"}],
                    "description": "Key project",
                    "customField": "value"}),
        encoding="utf-8"
    )
    preview = dry_run_import_folders(str(tmp_path))
    assert len(preview) == 1
    assert preview[0]["tags"] == ["important"]
    assert preview[0]["description"] == "Key project"
    assert "customField" in preview[0]["unsupported_fields"]


def test_dry_run_import_folders_empty(tmp_path):
    assert dry_run_import_folders(str(tmp_path)) == []


# ── Saved searches ──────────────────────────────────────────────────────────

def test_parse_saved_search_basic():
    ts_search = {
        "title": "Photos 2024",
        "textQuery": "sunset",
        "tagsAND": [{"title": "nature", "type": "sidecar"}],
        "fileTypes": ["jpg", "png"],
    }
    result = parse_saved_search(ts_search)
    assert result["name"] == "Photos 2024"
    assert "sunset" in result["query"]
    assert "tag:nature" in result["query"]
    assert "ext:jpg" in result["query"]
    assert result["unsupported_fields"] == []


def test_parse_saved_search_unsupported_fields():
    ts_search = {
        "title": "Complex",
        "textQuery": "hello",
        "tagTimePeriod": "past-month",
        "maxSize": 1000000,
    }
    result = parse_saved_search(ts_search)
    assert "tagTimePeriod" in result["unsupported_fields"]
    assert "maxSize" in result["unsupported_fields"]
    assert result["query"] == "hello"


def test_parse_saved_search_empty():
    result = parse_saved_search({})
    assert result["name"] == "Untitled"
    assert result["query"] == ""


def test_import_saved_searches():
    searches = [
        {"title": "A", "textQuery": "foo", "tagsAND": [{"title": "bar"}]},
        {"title": "B", "fileTypes": ["pdf"]},
    ]
    results = import_saved_searches(searches)
    assert len(results) == 2
    assert results[0]["name"] == "A"
    assert results[1]["query"] == "ext:pdf"


def test_export_saved_searches():
    queries = [
        {"name": "My Search", "query": "tag:photo AND ext:jpg AND sunset"},
    ]
    exported = export_saved_searches(queries)
    assert len(exported) == 1
    assert exported[0]["title"] == "My Search"
    assert {"title": "photo", "type": "sidecar"} in exported[0]["tagsAND"]
    assert "jpg" in exported[0]["fileTypes"]
    assert "sunset" in exported[0]["textQuery"]


def test_export_saved_searches_empty_query():
    queries = [{"name": "All", "query": ""}]
    exported = export_saved_searches(queries)
    assert exported[0]["textQuery"] == ""
    assert exported[0]["tagsAND"] == []


def test_read_write_saved_searches_file(tmp_path):
    searches = [
        {"title": "S1", "textQuery": "hello"},
        {"title": "S2", "tagsAND": [{"title": "work"}]},
    ]
    path = write_saved_searches_file(str(tmp_path / "searches.json"), searches)
    assert path.exists()
    loaded = read_saved_searches_file(str(path))
    assert len(loaded) == 2
    assert loaded[0]["title"] == "S1"


def test_read_saved_searches_file_wrapped(tmp_path):
    """TagSpaces sometimes wraps searches in a container dict."""
    wrapped = {"searches": [{"title": "X", "textQuery": "test"}]}
    path = tmp_path / "wrapped.json"
    path.write_text(json.dumps(wrapped), encoding="utf-8")
    loaded = read_saved_searches_file(str(path))
    assert len(loaded) == 1
    assert loaded[0]["title"] == "X"


def test_read_saved_searches_file_missing(tmp_path):
    assert read_saved_searches_file(str(tmp_path / "nonexistent.json")) == []


def test_read_saved_searches_file_malformed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json!", encoding="utf-8")
    assert read_saved_searches_file(str(path)) == []


def test_roundtrip_saved_searches():
    """Export then import should preserve the essential fields."""
    original = [{"name": "Test", "query": "tag:alpha AND ext:pdf AND report"}]
    ts_format = export_saved_searches(original)
    reimported = import_saved_searches(ts_format)
    assert reimported[0]["name"] == "Test"
    assert "tag:alpha" in reimported[0]["query"]
    assert "ext:pdf" in reimported[0]["query"]
    assert "report" in reimported[0]["query"]
