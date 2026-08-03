"""Quick Capture inbox synchronization coverage."""

from unifile import inbox
from unifile.tagging.library import TagLibrary


def test_sync_inbox_adds_tag_without_moving_files(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "capture"
    inbox_dir.mkdir()
    source = inbox_dir / "invoice.pdf"
    source.write_bytes(b"pdf")
    config_file = tmp_path / "inbox.json"
    monkeypatch.setattr(inbox, "_INBOX_FILE", str(config_file))
    monkeypatch.setattr(inbox, "_APP_DATA_DIR", str(tmp_path / "app"))
    inbox.save_inbox_config(str(inbox_dir))

    library = TagLibrary(str(tmp_path / "library"))
    assert library.open()
    assert inbox.sync_inbox_library(library) == 1
    entry = library.get_entry_by_path(str(source))
    assert entry is not None
    assert "inbox" in entry.tag_names
    assert source.exists()
    assert inbox.sync_inbox_library(library) == 0
    library.close()


def test_inbox_count_matches_recursive_sync_scope(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "capture"
    nested = inbox_dir / "nested"
    nested.mkdir(parents=True)
    (inbox_dir / "visible.txt").write_text("visible")
    (nested / "nested.txt").write_text("nested")
    (inbox_dir / ".hidden.txt").write_text("hidden")
    config_file = tmp_path / "inbox.json"
    monkeypatch.setattr(inbox, "_INBOX_FILE", str(config_file))
    monkeypatch.setattr(inbox, "_APP_DATA_DIR", str(tmp_path / "app"))
    inbox.save_inbox_config(str(inbox_dir), enabled=False)
    assert inbox.get_inbox_count() == 0
    inbox.save_inbox_config(str(inbox_dir), enabled=True)
    assert inbox.get_inbox_count() == 2
