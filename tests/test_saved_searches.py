"""Saved Smart View cache and export contracts."""

import csv
import json

from unifile import saved_searches


def test_saved_search_cache_round_trip_and_changed_badge(tmp_path, monkeypatch):
    monkeypatch.setattr(saved_searches, "_APP_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(
        saved_searches, "_SEARCHES_FILE", str(tmp_path / "app" / "saved.json"))

    saved_searches.add_search(saved_searches.SavedSearch(
        name="Invoices", query="invoice", nightly_refresh=True, refresh_hour=4))
    assert saved_searches.update_cache("Invoices", ["a.pdf", "b.pdf"], computed_at=100)
    item = saved_searches.get_saved_search("Invoices")
    assert item is not None
    assert item.cached_paths == ["a.pdf", "b.pdf"]
    assert item.result_count == 2
    assert item.nightly_refresh is True
    assert item.refresh_hour == 4
    assert item.cache_changed is False

    saved_searches.update_cache("Invoices", ["b.pdf", "c.pdf"], computed_at=200)
    item = saved_searches.get_saved_search("Invoices")
    assert item.cached_paths == ["b.pdf", "c.pdf"]
    assert item.cache_changed is True


def test_saved_search_exports_json_and_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(saved_searches, "_APP_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(
        saved_searches, "_SEARCHES_FILE", str(tmp_path / "app" / "saved.json"))
    saved_searches.add_search(saved_searches.SavedSearch(name="Docs", query="pdf"))
    saved_searches.update_cache("Docs", ["one.pdf", "two.pdf"], computed_at=123)

    json_path = tmp_path / "out.json"
    csv_path = tmp_path / "out.csv"
    assert saved_searches.export_cached_results("Docs", str(json_path))
    assert saved_searches.export_cached_results("Docs", str(csv_path))

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["paths"] == ["one.pdf", "two.pdf"]
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][:4] == ["smart_view", "query", "category", "path"]
    assert [row[3] for row in rows[1:]] == ["one.pdf", "two.pdf"]
