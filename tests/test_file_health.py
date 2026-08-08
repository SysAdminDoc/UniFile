"""Persistent SHA-256 integrity ledger and verification workflow coverage."""

import json
import subprocess
import sys

from unifile.file_health import FileHealthMonitor, export_health_log
from unifile.headless import HeadlessService, create_app
from unifile.scheduler import validate_job


def test_health_baselines_rechecks_and_reports_changes_and_missing(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    first = library / "first.txt"
    second = library / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    monitor = FileHealthMonitor(library)

    baseline = monitor.verify()
    assert baseline["status"] == "ok"
    assert baseline["files_verified"] == 2
    assert baseline["baselined"] == 2
    assert baseline["changed_unexpectedly"] == 0
    assert not any(item["path"].startswith(".unifile/") for item in baseline["diff"])

    unchanged = monitor.verify()
    assert unchanged["unchanged"] == 2
    assert unchanged["files_verified"] == 2

    first.write_text("first changed", encoding="utf-8")
    second.unlink()
    changed = monitor.verify()
    assert changed["status"] == "alert"
    assert changed["changed_unexpectedly"] == 1
    assert changed["missing"] == 1
    assert {item["change"] for item in changed["diff"]} == {"changed", "missing"}
    changed_item = next(item for item in changed["diff"] if item["path"] == "first.txt")
    assert changed_item["expected_sha256"] != changed_item["actual_sha256"]


def test_expected_change_and_single_file_scope_do_not_flag_unrelated_files(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    expected = library / "expected.txt"
    unrelated = library / "unrelated.txt"
    expected.write_text("before", encoding="utf-8")
    unrelated.write_text("unrelated", encoding="utf-8")
    monitor = FileHealthMonitor(library)
    monitor.verify()

    monitor.expect_change(expected, "planned rewrite")
    expected.write_text("after", encoding="utf-8")
    acknowledged = monitor.verify(expected)
    assert acknowledged["expected_changes"] == 1
    assert acknowledged["changed_unexpectedly"] == 0
    assert acknowledged["diff"][0]["change"] == "expected_change"

    unrelated.write_text("unrelated changed", encoding="utf-8")
    single_file = monitor.verify(expected)
    assert single_file["missing"] == 0
    assert single_file["changed_unexpectedly"] == 0


def test_health_log_exports_and_headless_scheduler_contract(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "note.txt").write_text("note", encoding="utf-8")
    report = FileHealthMonitor(library).verify()
    json_log = tmp_path / "health.json"
    csv_log = tmp_path / "health.csv"
    text_log = tmp_path / "health.txt"
    assert export_health_log(report, json_log).endswith("health.json")
    assert export_health_log(report, csv_log).endswith("health.csv")
    assert export_health_log(report, text_log, fmt="text").endswith("health.txt")
    assert json.loads(json_log.read_text(encoding="utf-8"))["files_verified"] == 1
    assert "path,change" in csv_log.read_text(encoding="utf-8")
    assert "Files verified: 1" in text_log.read_text(encoding="utf-8")

    job = validate_job({
        "name": "Weekly integrity",
        "schedule": "0 3 * * 0",
        "action": "verify",
        "path": str(library),
        "health_log": str(tmp_path / "scheduled.json"),
    })
    assert job["action"] == "verify"
    service = HeadlessService(library)
    result = service.run_job(job)
    assert result["files_verified"] == 1
    assert (tmp_path / "scheduled.json").is_file()


def test_headless_scan_includes_integrity_report_and_cli_returns_alert(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    target = library / "photo.jpg"
    target.write_bytes(b"baseline")
    service = HeadlessService(library)
    first = service.scan()
    assert first["verification"] == {"requested": False, "status": "not-requested"}
    assert "file_health" not in first
    verified = service.scan(verify=True)
    assert verified["file_health"]["baselined"] == 1
    target.write_bytes(b"changed")
    cli = subprocess.run(
        [sys.executable, "-m", "unifile", "verify", str(library), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli.returncode == 1
    payload = json.loads(cli.stdout)
    assert payload["changed_unexpectedly"] == 1


def test_headless_verify_endpoint_and_latest_report(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "note.txt").write_text("note", encoding="utf-8")
    service = HeadlessService(library)
    app = create_app(
        {"API_KEY": "health-key", "SCHEDULER_FILE": str(tmp_path / "jobs.json")},
        service=service,
    )
    app.config.update(TESTING=True)
    client = app.test_client()
    headers = {"X-API-Key": "health-key"}

    assert client.get("/file-health", headers=headers).get_json()["status"] == "not-verified"
    result = client.post("/verify", headers=headers, json={})
    assert result.status_code == 200
    assert result.get_json()["baselined"] == 1
    latest = client.get("/file-health", headers=headers)
    assert latest.get_json()["files_verified"] == 1
    assert client.get("/verify", headers=headers).status_code == 405
