"""Coverage for the Qt-free settled-file watch daemon."""

import json
import os
import subprocess
import sys


def test_watch_waits_for_stable_file_before_moving(tmp_path, monkeypatch):
    import unifile.cli_scan as cli_scan
    from unifile.cli_watch import WatchDaemon

    source = tmp_path / "inbox"
    destination = tmp_path / "organized"
    source.mkdir()
    monkeypatch.setattr(cli_scan, "is_protected", lambda _path: False)
    monkeypatch.setattr("unifile.cli_watch.is_protected", lambda _path: False)
    target = source / "download.pdf"
    daemon = WatchDaemon(
        source,
        destination=destination,
        apply_rules=True,
        settle_seconds=0.5,
        poll_seconds=0.05,
    )

    target.write_bytes(b"partial")
    assert daemon.poll_once(100.0) == []
    target.write_bytes(b"complete")
    assert daemon.poll_once(100.2) == []
    assert daemon.poll_once(100.6) == []
    events = daemon.poll_once(100.71)

    assert len(events) == 1
    assert events[0]["action"] == "moved"
    assert events[0]["item"]["category"] == "Documents"
    assert not target.exists()
    assert (destination / "Documents" / "download.pdf").read_bytes() == b"complete"


def test_watch_review_mode_does_not_move_and_flushes_pending_file(tmp_path, monkeypatch):
    import unifile.cli_scan as cli_scan
    from unifile.cli_watch import WatchDaemon

    source = tmp_path / "inbox"
    destination = tmp_path / "organized"
    source.mkdir()
    target = source / "note.txt"
    target.write_text("note", encoding="utf-8")
    monkeypatch.setattr(cli_scan, "is_protected", lambda _path: False)
    monkeypatch.setattr("unifile.cli_watch.is_protected", lambda _path: False)
    daemon = WatchDaemon(
        source,
        destination=destination,
        settle_seconds=0,
        include_existing=True,
    )

    result = daemon.result(daemon.run_once())

    assert result["moved"] == 0
    assert result["events"][0]["action"] == "classified"
    assert result["events"][0]["status"] == "pending"
    assert target.is_file()
    assert not (destination / "Documents" / "note.txt").exists()


def test_watch_cli_applies_existing_file_without_gui_imports(tmp_path):
    source = tmp_path / "inbox"
    destination = tmp_path / "organized"
    source.mkdir()
    (source / "image.png").write_bytes(b"png")
    env = os.environ.copy()
    env["APPDATA"] = str(tmp_path / "appdata")
    env["USERPROFILE"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unifile",
            "watch",
            str(source),
            "--include-existing",
            "--once",
            "--settle",
            "0",
            "--apply-rules",
            "--destination",
            str(destination),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["moved"] == 1
    assert payload["events"][0]["item"]["category"] == "Images"
    assert (destination / "Images" / "image.png").is_file()
    assert "PyQt6" not in completed.stderr
