"""CLI: `python -m unifile validate-rules <dir>` (added in v9.3.10).

Exercises the command end-to-end via `subprocess.run` so we catch:
  * argparse wiring (subcommand registration, --json flag)
  * exit-code contract (0 ok, 2 missing, 3 malformed, 4 unknown names)
  * both JSON and human output paths
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(args, cwd=None):
    """Invoke `python -m unifile <args...>` and return (returncode, stdout, stderr)."""
    cp = subprocess.run(
        [sys.executable, "-m", "unifile", *args],
        capture_output=True, text=True, cwd=str(cwd or REPO_ROOT),
    )
    return cp.returncode, cp.stdout, cp.stderr


def _extract_json(stdout: str):
    """Extract the JSON object/array from stdout, tolerating non-JSON preamble.

    The `face_recognition` package prints an install reminder to stdout at
    import time (we can't suppress it without patching the library). Scan
    for the first `{` or `[` that starts a parseable JSON value.
    """
    for i, ch in enumerate(stdout):
        if ch in "{[":
            try:
                # json.loads will raise if there's trailing non-whitespace, so
                # find the matching close via raw_decode.
                obj, _ = json.JSONDecoder().raw_decode(stdout[i:])
                return obj
            except json.JSONDecodeError:
                continue
    raise AssertionError(f"no JSON payload found in stdout:\n{stdout}")


def test_validate_rules_reports_missing_file_with_exit_2(tmp_path):
    rc, out, err = _run(["validate-rules", str(tmp_path)])
    assert rc == 2
    assert ".unifile_rules.json" in err or "No" in err


def test_validate_rules_missing_json_payload(tmp_path):
    rc, out, _ = _run(["validate-rules", str(tmp_path), "--json"])
    assert rc == 2
    payload = _extract_json(out)
    assert payload == {
        "ok": False,
        "reason": "missing",
        "expected_path": str(tmp_path / ".unifile_rules.json"),
    }


def test_validate_rules_malformed_exits_3(tmp_path):
    (tmp_path / ".unifile_rules.json").write_text("not json at all", encoding="utf-8")
    rc, _, err = _run(["validate-rules", str(tmp_path)])
    assert rc == 3
    assert "alformed" in err or "empty" in err.lower()


def test_validate_rules_malformed_json_payload(tmp_path):
    (tmp_path / ".unifile_rules.json").write_text("[]", encoding="utf-8")
    rc, out, _ = _run(["validate-rules", str(tmp_path), "--json"])
    assert rc == 3
    payload = _extract_json(out)
    assert payload["ok"] is False and payload["reason"] == "malformed"


def test_validate_rules_ok_reports_effective_set(tmp_path):
    (tmp_path / ".unifile_rules.json").write_text(json.dumps({
        "inline": [{"name": "local-a"}, {"name": "local-b"}],
    }), encoding="utf-8")
    rc, out, _ = _run(["validate-rules", str(tmp_path), "--json"])
    assert rc == 0
    payload = _extract_json(out)
    assert payload["ok"] is True
    assert payload["inline_count"] == 2
    assert "local-a" in payload["effective_rule_names"]
    assert "local-b" in payload["effective_rule_names"]


def test_validate_rules_unknown_include_exits_4(tmp_path):
    """include=[<name not in global rules>] should flag 'unknown_include_names'
    and exit non-zero so CI can catch stale per-folder configs."""
    (tmp_path / ".unifile_rules.json").write_text(json.dumps({
        "include": ["definitely-not-a-real-global-rule-xyz"],
    }), encoding="utf-8")
    rc, out, _ = _run(["validate-rules", str(tmp_path), "--json"])
    assert rc == 4
    payload = _extract_json(out)
    assert payload["ok"] is False
    assert "definitely-not-a-real-global-rule-xyz" in payload["unknown_include_names"]


def test_validate_rules_human_output_lists_effective_rules(tmp_path):
    (tmp_path / ".unifile_rules.json").write_text(json.dumps({
        "inline": [{"name": "my-local-rule"}],
    }), encoding="utf-8")
    rc, out, _ = _run(["validate-rules", str(tmp_path)])
    assert rc == 0
    assert "my-local-rule" in out
    assert "inline:" in out


def test_validate_rules_errors_for_non_directory(tmp_path):
    fake = tmp_path / "not_a_directory.txt"
    fake.write_text("x", encoding="utf-8")
    rc, _, err = _run(["validate-rules", str(fake)])
    assert rc == 2
    assert "not a directory" in err.lower()
