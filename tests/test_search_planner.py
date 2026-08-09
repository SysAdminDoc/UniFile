"""SQL-planned Tag Library search, indexes, cancellation, and benchmark coverage."""

from __future__ import annotations

from sqlalchemy import text

from unifile.tagging.library import SearchCancelled, SearchIndexError, TagLibrary


def _open_library(root):
    library = TagLibrary(str(root))
    assert library.open()
    return library


def _populate(library, root):
    paths = []
    for name in ("photo-alpha.pdf", "photo-beta.jpg", "report-beta.txt"):
        path = root / name
        path.write_text(name, encoding="utf-8")
        paths.append(path)
    entries = [library.add_entry(str(path)) for path in paths]
    assert all(entries)
    first = library.add_tag("one")
    second = library.add_tag("two")
    assert first and second
    assert library.add_tags_to_entry(entries[0].id, [first.id])
    assert library.add_tags_to_entry(entries[1].id, [second.id])
    return entries, first, second


def test_search_composes_boolean_predicates_in_sql_and_paginates(tmp_path):
    library = _open_library(tmp_path)
    try:
        entries, first, second = _populate(library, tmp_path)
        page = library.search_entries_page("photo AND ext:pdf", limit=1)
        assert page.total == 1
        assert [entry.id for entry in page.entries] == [entries[0].id]
        assert page.index_mode == "fts5"

        assert {entry.id for entry in library.search_entries("tag:one OR tag:two")} == {
            entries[0].id,
            entries[1].id,
        }
        assert {entry.id for entry in library.search_entries("NOT tag:one")} == {
            entries[1].id,
            entries[2].id,
        }
        assert library.search_entries_page("photo", limit=1, offset=1).total == 2
        assert library.search_entries("field:missing=value") == []
    finally:
        library.close()


def test_search_field_and_metadata_predicates_use_bounded_sql(tmp_path):
    library = _open_library(tmp_path)
    try:
        entries, _first, _second = _populate(library, tmp_path)
        entries[0].rating = 4
        entries[0].is_inbox = False
        library._session.commit()
        assert library.search_entries("rating:3")[0].id == entries[0].id
        assert library.search_entries("inbox:false")[0].id == entries[0].id

        indexes = {
            row[1] for row in library._session.execute(text("PRAGMA index_list(entries)"))
        }
        assert "ix_entries_suffix_filename" in indexes
        assert "ix_entries_rating_filename" in indexes
        field_indexes = {
            row[1] for row in library._session.execute(text("PRAGMA index_list(text_fields)"))
        }
        assert "ix_text_fields_key_value_entry" in field_indexes
    finally:
        library.close()


def test_search_fallback_is_diagnostic_and_corruption_is_visible(tmp_path):
    library = _open_library(tmp_path)
    try:
        _populate(library, tmp_path)
        library._session.execute(text("DROP TABLE entries_fts"))
        library._session.commit()
        fallback = library.search_entries_page("photo")
        assert fallback.index_mode == "like-fallback"
        assert "unavailable" in library.last_search_diagnostic["fallback_reason"]

        library._session.execute(text("CREATE TABLE entries_fts (rowid INTEGER PRIMARY KEY)"))
        library._session.commit()
        try:
            library.search_entries_page("photo")
        except SearchIndexError as exc:
            assert "search failed" in str(exc).lower()
        else:
            raise AssertionError("corrupt FTS schema was not surfaced")
    finally:
        library.close()


def test_search_cancellation_interrupts_before_query(tmp_path):
    library = _open_library(tmp_path)
    try:
        _populate(library, tmp_path)
        try:
            library.search_entries_page("photo", cancel=lambda: True)
        except SearchCancelled:
            pass
        else:
            raise AssertionError("cancelled search returned results")
    finally:
        library.close()


def test_benchmark_reports_fixture_latency_memory_and_cancellation():
    from tools.benchmark_search import run_benchmark

    report = run_benchmark(entries=128, seed=42, cancel_after_ms=0)
    assert report["fixture"] == {"entries": 128, "seed": 42}
    assert len(report["queries"]) == 3
    assert all("elapsed_ms" in query and "peak_python_bytes" in query
               for query in report["queries"])
    assert report["cancellation"]["status"] == "cancelled"


def test_tag_library_panel_rejects_stale_search_generation(qtbot):
    from unifile.dialogs.tag_library import TagLibraryPanel

    panel = TagLibraryPanel()
    qtbot.addWidget(panel)
    panel._pending_search = "new query"
    panel._search_generation = 2
    panel.lbl_selection_info.setText("Searching…")

    panel._on_search_results(1, "new query", [], [])
    assert panel.lbl_selection_info.text() == "Searching…"

    panel._on_search_results(2, "new query", [], [])
    assert panel.lbl_selection_info.text() == "No matching files found"
