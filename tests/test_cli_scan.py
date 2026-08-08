"""Coverage for the Qt-free scan-and-apply command."""

import json
import os
import subprocess
import sys


def _categories():
    return [
        {"name": "Documents", "extensions": ["pdf", "txt"]},
        {"name": "Images", "extensions": ["png", "jpg"]},
        {"name": "Other", "extensions": []},
    ]


def test_scan_plan_is_review_first_and_collision_safe(tmp_path, monkeypatch):
    import unifile.cli_scan as cli_scan

    source = tmp_path / "inbox"
    destination = tmp_path / "organized"
    source.mkdir()
    (source / "report.pdf").write_bytes(b"pdf")
    (source / "photo.png").write_bytes(b"png")
    existing = destination / "Documents" / "report.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")
    monkeypatch.setattr(cli_scan, "_load_pc_categories", _categories)
    monkeypatch.setattr(cli_scan, "is_protected", lambda _path: False)

    result = cli_scan.scan_directory(source, destination=destination)

    assert result["mode"] == "headless-rule-based"
    assert result["moved"] == 0
    assert result["selected_count"] == 2
    report = next(item for item in result["items"] if item["name"] == "report.pdf")
    assert report["dst"].endswith(os.path.join("Documents", "report (2).pdf"))
    assert report["status"] == "Pending"
    assert (source / "report.pdf").is_file()
    assert not (destination / "Images" / "photo.png").exists()


def test_scan_apply_rules_honors_source_rules_and_dry_run(tmp_path, monkeypatch):
    import unifile.cli_scan as cli_scan

    source = tmp_path / "inbox"
    destination = tmp_path / "organized"
    source.mkdir()
    target = source / "camera.xyz"
    target.write_text("camera", encoding="utf-8")
    rules_dir = source / ".unifile"
    rules_dir.mkdir()
    (rules_dir / "rules.json").write_text(
        json.dumps([{
            "name": "Camera files",
            "priority": 1,
            "conditions": [{"field": "extension", "op": "eq", "value": ".xyz"}],
            "action_category": "Images",
            "confidence": 95,
        }]),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_scan, "_load_pc_categories", _categories)
    monkeypatch.setattr(cli_scan, "is_protected", lambda _path: False)

    dry_run = cli_scan.scan_directory(
        source, destination=destination, apply_rules=True, dry_run=True
    )
    assert dry_run["would_move"] == 1
    assert dry_run["moved"] == 0
    assert dry_run["items"][0]["method"] == "rule"
    assert dry_run["action_plan"]["plan_type"] == "file-actions"
    assert len(dry_run["action_plan"]["actions"]) == 1
    assert dry_run["action_plan"]["nodes"][-1]["requires_approval"] is True
    assert target.is_file()
    assert not (destination / "Images" / "camera.xyz").exists()

    applied = cli_scan.scan_directory(source, destination=destination, apply_rules=True)
    assert applied["moved"] == 1
    assert applied["failed"] == 0
    assert (destination / "Images" / "camera.xyz").read_text(encoding="utf-8") == "camera"
    assert not target.exists()


def test_headless_scan_uses_the_cli_contract(tmp_path, monkeypatch):
    import unifile.cli_scan as cli_scan
    from unifile.headless import HeadlessService

    source = tmp_path / "library"
    destination = tmp_path / "organized"
    source.mkdir()
    (source / "report.pdf").write_bytes(b"pdf")
    monkeypatch.setattr(cli_scan, "_load_pc_categories", _categories)
    monkeypatch.setattr(cli_scan, "is_protected", lambda _path: False)

    cli_result = cli_scan.scan_directory(source, destination=destination)
    service = HeadlessService(
        source,
        scan_roots=[str(source), str(destination)],
    )
    api_result = service.scan(
        destination=str(destination),
        min_confidence=80,
    )

    assert api_result["version"] == cli_result["version"]
    assert api_result["destination"] == cli_result["destination"]
    assert api_result["apply_rules"] == cli_result["apply_rules"]
    assert api_result["dry_run"] == cli_result["dry_run"]
    assert api_result["action_plan"]["plan_type"] == cli_result["action_plan"]["plan_type"]
    for field in ("src", "dst", "category", "selected", "status"):
        assert api_result["items"][0][field] == cli_result["items"][0][field]


def test_scan_subcommand_runs_without_gui_imports(tmp_path):
    source = tmp_path / "inbox"
    source.mkdir()
    (source / "note.txt").write_text("note", encoding="utf-8")
    env = os.environ.copy()
    env["APPDATA"] = str(tmp_path / "appdata")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unifile",
            "scan",
            str(source),
            "--json",
            "--destination",
            str(tmp_path / "organized"),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["count"] == 1
    assert payload["items"][0]["category"] == "Documents"
    assert "PyQt6" not in completed.stderr
