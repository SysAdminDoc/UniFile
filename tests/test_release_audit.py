"""Artifact-scoped release audit contract tests."""
from __future__ import annotations

import json

from tools import release_audit


def _target(tmp_path, *, dependencies=()):
    manifest = tmp_path / "pyproject.toml"
    dependency_lines = ",\n".join(f'    "{value}"' for value in dependencies)
    manifest.write_text(
        "[project]\n"
        'name = "audit-fixture"\n'
        'version = "1.2.3"\n'
        'license = "MIT"\n'
        f"dependencies = [{dependency_lines}]\n",
        encoding="utf-8",
    )
    return release_audit.ProjectTarget("fixture", tmp_path, manifest, "fixture build")


def test_artifact_digest_is_content_and_path_stable(tmp_path):
    artifact = tmp_path / "payload"
    (artifact / "nested").mkdir(parents=True)
    (artifact / "nested" / "b.txt").write_text("b", encoding="utf-8")
    (artifact / "a.txt").write_text("a", encoding="utf-8")

    first = release_audit.artifact_digest(artifact)
    second = release_audit.artifact_digest(artifact)

    assert first == second
    assert first[1:] == (2, 2)


def test_fix_versions_do_not_imply_high_severity():
    assert release_audit._severity({"fix_versions": ["2.0"]}) == "unknown"
    assert release_audit._severity({"severity": "high", "fix_versions": []}) == "high"


def test_timeout_is_actionable_and_does_not_raise(monkeypatch, tmp_path):
    target = _target(tmp_path)
    monkeypatch.setattr(
        release_audit,
        "_run_capture",
        lambda *command, timeout=60: release_audit.CommandResult(
            None,
            "",
            "",
            timed_out=True,
            error=f"timed out after {timeout}s",
        ),
    )

    evidence = release_audit.scan_project(target, timeout=3)

    assert evidence["status"] == "unknown"
    assert evidence["failure"] == {
        "kind": "timeout",
        "message": "pip-audit timed out after 3s",
    }


def test_offline_mode_is_explicitly_unknown(tmp_path):
    evidence = release_audit.scan_project(_target(tmp_path), offline=True)

    assert evidence["mode"] == "offline"
    assert evidence["status"] == "unknown"
    assert evidence["failure"]["kind"] == "offline"


def test_missing_audit_tool_is_actionable(monkeypatch, tmp_path):
    target = _target(tmp_path)
    monkeypatch.setattr(
        release_audit,
        "_run_capture",
        lambda *command, timeout=60: release_audit.CommandResult(
            None,
            "",
            "",
            missing=True,
            error="pip-audit unavailable",
        ),
    )

    evidence = release_audit.scan_project(target)

    assert evidence["status"] == "unknown"
    assert evidence["failure"]["kind"] == "tool-unavailable"


def test_audit_payload_keeps_severity_unknown_when_only_a_fix_is_present(monkeypatch, tmp_path):
    target = _target(tmp_path)
    monkeypatch.setattr(release_audit, "_distribution_index", lambda: {})
    monkeypatch.setattr(
        release_audit,
        "_run_capture",
        lambda *command, timeout=60: release_audit.CommandResult(
            1,
            json.dumps(
                {
                    "dependencies": [
                        {
                            "name": "demo",
                            "version": "1.0",
                            "vulns": [{"id": "DEMO-1", "fix_versions": ["1.1"]}],
                        }
                    ]
                }
            ),
            "",
        ),
    )

    evidence = release_audit.scan_project(target)

    assert evidence["status"] == "unknown"
    assert evidence["counts"] == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "unknown": 1,
    }


def test_explicit_sdk_artifact_is_classified(tmp_path):
    wheel = tmp_path / "unifile_sdk-9.3.33-py3-none-any.whl"
    wheel.write_bytes(b"wheel")

    records, missing = release_audit.discover_artifacts(
        tmp_path,
        "9.3.33",
        explicit=[wheel],
    )

    assert missing == []
    assert records[0]["kind"] == "sdk-wheel"
    assert records[0]["dependency_project"] == "sdk"
    assert records[0]["sha256"] == release_audit.artifact_digest(wheel)[0]
