"""Semantic index coverage for normal files and archive members."""

from unifile import semantic


def test_archive_member_embeddings_keep_container_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "_EMBED_DB", str(tmp_path / "semantic.db"))
    index = semantic.SemanticIndex()

    def fake_embedding(text):
        return [1.0, 0.0] if "invoice" in text.lower() else [0.0, 1.0]

    monkeypatch.setattr(index, "_get_embedding", fake_embedding)
    archive = tmp_path / "invoices.zip"
    assert index.index_archive_entry(
        str(archive), "incoming/invoice.pdf", "Accounts payable", name="invoice.pdf")
    assert index.index_archive_entry(
        str(archive), "notes.txt", "General notes", name="notes.txt")

    results = index.search("invoice", top_k=5, threshold=0.0)
    match = next(result for result in results if result["source_type"] == "archive")
    assert match["filepath"] == str(archive)
    assert match["path"] == str(archive)
    assert match["archive_path"] == str(archive)
    assert match["inner_path"] == "incoming/invoice.pdf"
    assert match["name"] == "invoice.pdf"
    index.close()
