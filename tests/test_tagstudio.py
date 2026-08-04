"""TagStudio SQLite import/export coverage."""

import hashlib
import json
import sqlite3
import subprocess
import sys

from unifile.tagging.library import TagLibrary
from unifile.tagstudio import export_tagstudio, import_tagstudio, inspect_tagstudio


def _make_tagstudio_library(root):
    (root / "media").mkdir(parents=True)
    (root / "media" / "photo.jpg").write_bytes(b"photo")
    (root / "notes.txt").write_text("notes", encoding="utf-8")
    thumbs = root / ".TagStudio" / "thumbs" / "123"
    thumbs.mkdir(parents=True)
    (thumbs / "photo.webp").write_bytes(b"thumbnail")
    database = root / ".TagStudio" / "ts_library.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                shorthand TEXT,
                color_namespace TEXT,
                color_slug TEXT,
                is_category BOOLEAN NOT NULL DEFAULT 0,
                is_hidden BOOLEAN NOT NULL DEFAULT 0,
                icon TEXT,
                disambiguation_id INTEGER
            );
            CREATE TABLE tag_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                tag_id INTEGER NOT NULL
            );
            CREATE TABLE tag_parents (parent_id INTEGER NOT NULL, child_id INTEGER NOT NULL,
                                      PRIMARY KEY (parent_id, child_id));
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                suffix TEXT NOT NULL,
                date_created DATETIME,
                date_modified DATETIME,
                date_added DATETIME
            );
            CREATE TABLE tag_entries (tag_id INTEGER NOT NULL, entry_id INTEGER NOT NULL,
                                      PRIMARY KEY (tag_id, entry_id));
            CREATE TABLE text_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                entry_id INTEGER NOT NULL,
                value TEXT,
                is_multiline BOOLEAN NOT NULL DEFAULT 0
            );
            CREATE TABLE datetime_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                entry_id INTEGER NOT NULL,
                value TEXT
            );
            CREATE TABLE versions (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            INSERT INTO versions(key, value) VALUES ('CURRENT', 300), ('INITIAL', 300);
            """
        )
        connection.executemany(
            "INSERT INTO tags(id, name, shorthand, color_slug, is_category, is_hidden) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (0, "Archived", None, "red", 0, 1),
                (1, "Favorite", None, "yellow", 0, 0),
                (1000, "People", "P", "blue", 1, 0),
                (1001, "Alice", "A", "green", 0, 0),
            ],
        )
        connection.execute("INSERT INTO tag_aliases(name, tag_id) VALUES (?, ?)", ("Al", 1001))
        connection.execute("INSERT INTO tag_parents(parent_id, child_id) VALUES (?, ?)", (1000, 1001))
        connection.executemany(
            "INSERT INTO entries(id, path, filename, suffix, date_added) VALUES (?, ?, ?, ?, ?)",
            [(42, "media", "photo.jpg", "jpg", "2026-08-01 10:00:00"),
             (43, "notes.txt", "notes.txt", "txt", "2026-08-01 10:01:00")],
        )
        connection.executemany(
            "INSERT INTO tag_entries(tag_id, entry_id) VALUES (?, ?)",
            [(1001, 42), (1, 43)],
        )
        connection.execute(
            "INSERT INTO text_fields(name, entry_id, value, is_multiline) VALUES (?, ?, ?, ?)",
            ("Description", 42, "Imported photo", 1),
        )
        connection.execute(
            "INSERT INTO datetime_fields(name, entry_id, value) VALUES (?, ?, ?)",
            ("Date", 42, "2026-08-01T10:00:00"),
        )
    return database


def test_import_tagstudio_is_read_only_and_preserves_metadata(tmp_path):
    source_root = tmp_path / "tagstudio"
    database = _make_tagstudio_library(source_root)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    target_root = tmp_path / "unifile"

    result = import_tagstudio(source_root, target_root)

    assert result.tags == 4
    assert result.entries == 2
    assert result.fields == 2
    assert database.exists()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert (target_root / ".unifile" / "tagstudio-thumbs" / "123" / "photo.webp").read_bytes() == b"thumbnail"

    library = TagLibrary(str(target_root))
    assert library.open()
    try:
        child = library.get_tag_by_name("Alice")
        parent = library.get_tag_by_name("People")
        assert child is not None and parent is not None
        assert parent.id in child.parent_ids
        assert "Al" in child.alias_strings
        entry = library.get_entry_by_path(str(source_root / "media" / "photo.jpg"))
        assert entry is not None
        assert "Alice" in entry.tag_names
        fields = library.get_entry_fields(entry.id)
        assert fields["description"] == "Imported photo"
    finally:
        library.close()


def test_tagstudio_export_is_additive_and_round_trips(tmp_path):
    source_root = tmp_path / "unifile"
    file_path = source_root / "image.png"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"image")
    library = TagLibrary(str(source_root))
    assert library.open()
    parent = library.add_tag("Projects", is_category=True, color_slug="blue")
    child = library.add_tag("Launch", color_slug="green")
    assert parent is not None and child is not None
    assert library.add_parent_tag(child.id, parent.id)
    entry = library.add_entry(str(file_path))
    assert entry is not None
    assert library.add_tags_to_entry(entry.id, [child.id])
    assert library.set_entry_field(entry.id, "description", "Round-trip value")
    library.close()
    thumbs = source_root / ".unifile" / "tagstudio-thumbs" / "456"
    thumbs.mkdir(parents=True)
    (thumbs / "image.webp").write_bytes(b"thumb")
    source_database = source_root / ".unifile" / "unifile_tags.sqlite"
    before = hashlib.sha256(source_database.read_bytes()).hexdigest()

    destination = tmp_path / "tagstudio-export"
    first = export_tagstudio(source_root, destination)
    second = export_tagstudio(source_root, destination)
    info = inspect_tagstudio(destination)

    assert first.tags >= 2
    assert first.entries == 1
    assert first.fields == 1
    assert second.merged >= first.tags + first.entries
    assert info["schema_version"] == 300
    assert info["entries"] == 1
    assert info["fields"] == 1
    assert (destination / ".TagStudio" / "thumbs" / "456" / "image.webp").read_bytes() == b"thumb"
    assert hashlib.sha256(source_database.read_bytes()).hexdigest() == before

    roundtrip_root = tmp_path / "roundtrip"
    imported = import_tagstudio(destination, roundtrip_root)
    assert imported.entries == 1
    roundtrip = TagLibrary(str(roundtrip_root))
    assert roundtrip.open()
    try:
        entry = roundtrip.get_entry_by_path(str(file_path))
        assert entry is not None
        assert "Launch" in entry.tag_names
        assert roundtrip.get_entry_fields(entry.id)["description"] == "Round-trip value"
    finally:
        roundtrip.close()


def test_tagstudio_inspection_dry_run_does_not_create_target(tmp_path):
    source_root = tmp_path / "tagstudio"
    _make_tagstudio_library(source_root)
    target_root = tmp_path / "target"

    result = import_tagstudio(source_root, target_root, dry_run=True)

    assert result.dry_run is True
    assert result.entries == 2
    assert not target_root.exists()


def test_tagstudio_cli_round_trip_commands(tmp_path):
    source_root = tmp_path / "tagstudio"
    _make_tagstudio_library(source_root)
    target_root = tmp_path / "unifile"
    imported = subprocess.run(
        [
            sys.executable,
            "-m",
            "unifile",
            "import-tagstudio",
            str(source_root),
            str(target_root),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
    assert json.loads(imported.stdout)["operation"] == "import"
    exported_root = tmp_path / "exported"
    exported = subprocess.run(
        [
            sys.executable,
            "-m",
            "unifile",
            "export-tagstudio",
            str(target_root),
            str(exported_root),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)["operation"] == "export"
