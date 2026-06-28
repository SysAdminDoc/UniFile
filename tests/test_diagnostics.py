import json
import zipfile

from unifile import diagnostics


def test_redact_text_removes_paths_emails_and_keys():
    raw = (
        r"api_key=sk-live-123 user=matt@example.com "
        r"path=C:\Users\Alice\Documents\secret.pdf Authorization: Bearer abc.def"
    )

    redacted = diagnostics.redact_text(raw)

    assert "sk-live-123" not in redacted
    assert "matt@example.com" not in redacted
    assert "Alice" not in redacted
    assert "abc.def" not in redacted
    assert diagnostics.REDACTED_SECRET in redacted
    assert diagnostics.REDACTED_EMAIL in redacted
    assert diagnostics.REDACTED_PATH in redacted


def test_redact_json_recurses_through_secret_keys_and_paths():
    payload = {
        "api_key": "sk-test",
        "nested": [{"email": "person@example.com", "path": r"C:\Users\Alice\file.txt"}],
        "safe": "plain",
    }

    redacted = diagnostics.redact_json(payload)

    assert redacted["api_key"] == diagnostics.REDACTED_SECRET
    assert redacted["nested"][0]["email"] == diagnostics.REDACTED_EMAIL
    assert redacted["nested"][0]["path"] == diagnostics.REDACTED_PATH
    assert redacted["safe"] == "plain"


def test_export_diagnostics_zip_redacts_recent_logs(monkeypatch, tmp_path):
    app_data = tmp_path / "appdata"
    app_data.mkdir()
    crash = app_data / "crash.log"
    csv_log = app_data / "move_log.csv"
    undo = app_data / "undo_stack.json"
    watch = app_data / "watch_history.json"
    crash.write_text(
        r"Unhandled crash for matt@example.com at C:\Users\Alice\secret.txt api_key=sk-live",
        encoding="utf-8",
    )
    csv_log.write_text(
        "Timestamp,Source,Destination\n"
        r"now,C:\Users\Alice\a.txt,C:\Users\Alice\b.txt",
        encoding="utf-8",
    )
    undo.write_text(json.dumps([{"src": r"C:\Users\Alice\a.txt"}]), encoding="utf-8")
    watch.write_text(json.dumps([{"folder": r"C:\Users\Alice\Inbox"}]), encoding="utf-8")

    monkeypatch.setattr(diagnostics, "_APP_DATA_DIR", str(app_data))
    monkeypatch.setattr(diagnostics, "_CSV_LOG_FILE", str(csv_log))
    monkeypatch.setattr(diagnostics, "_UNDO_STACK_FILE", str(undo))
    monkeypatch.setattr(diagnostics, "_WATCH_HISTORY_FILE", str(watch))

    output = diagnostics.export_diagnostics_zip(str(tmp_path / "diag.zip"))

    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        combined = "\n".join(zf.read(name).decode("utf-8") for name in names)

    assert {"summary.json", "providers.json", "logs/crash.log", "logs/move_log.csv"} <= names
    assert "sk-live" not in combined
    assert "matt@example.com" not in combined
    assert "Alice" not in combined
    assert diagnostics.REDACTED_SECRET in combined
    assert diagnostics.REDACTED_PATH in combined
