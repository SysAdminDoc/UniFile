"""Coverage for explainable file relationships and symmetric manual links."""


def test_find_related_reports_shared_metadata_signals(tmp_path):
    from unifile.relationships import find_related

    current = {
        "path": str(tmp_path / "IMG_0001.jpg"),
        "name": "IMG_0001.jpg",
        "metadata": {
            "tags": ["trip", "sunset"],
            "artist": "A. Photographer",
            "date_taken": "2024:06:01 12:00:00",
        },
    }
    related = {
        "path": str(tmp_path / "IMG_0002.jpg"),
        "name": "IMG_0002.jpg",
        "metadata": {
            "tags": ["trip", "beach"],
            "artist": "a. photographer",
            "date_taken": "2024-06-03T09:00:00",
        },
    }
    unrelated = {
        "path": str(tmp_path / "invoice.pdf"),
        "name": "invoice.pdf",
        "metadata": {"author": "Accounting", "date_taken": "2020-01-01"},
    }

    results = find_related(current, [current, related, unrelated])

    assert [item["name"] for item in results] == ["IMG_0002.jpg"]
    assert results[0]["score"] > 0
    assert any(reason.startswith("shared tags:") for reason in results[0]["reasons"])
    assert "same photographer" in results[0]["reasons"]
    assert any(reason.startswith("same date range") for reason in results[0]["reasons"])
    assert "same name pattern" in results[0]["reasons"]


def test_manual_link_store_is_bidirectional_and_surfaces_external_target(tmp_path):
    from unifile.relationships import ManualLinkStore, find_related

    store = ManualLinkStore(tmp_path / "links.json")
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    store.add_link(first, second)

    assert store.links_for(first) == [str(second.resolve())]
    assert store.links_for(second) == [str(first.resolve())]
    results = find_related(first, [], manual_store=store)
    assert results[0]["path"] == str(second.resolve())
    assert results[0]["reasons"] == ["manual link"]

    store.remove_link(first, second)
    assert store.links_for(first) == []
    assert store.links_for(second) == []
