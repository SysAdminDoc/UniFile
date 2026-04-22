"""Regression guard for Python 3.10 / 3.11 f-string compatibility.

PEP 701 (Python 3.12) relaxed two f-string restrictions:
  - backslashes are now allowed inside f-string expressions
  - the outer quote character can be reused inside expressions

UniFile declares `requires-python = ">=3.10"` in pyproject.toml, so any
file using those constructs will fail with SyntaxError when imported on
3.10 or 3.11 — even though it parses fine on the 3.12 dev interpreter.

We rely on ruff's parser to flag these as `invalid-syntax` (ruff knows
the 3.10 target from the `target-version` setting in pyproject.toml).
If ruff is not available, the test is skipped — fine for local dev,
CI has ruff pinned in the dev extras.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UNIFILE_DIR = REPO_ROOT / "unifile"


@pytest.fixture(scope="module")
def _ruff_bin():
    exe = shutil.which("ruff")
    if not exe:
        pytest.skip("ruff not installed — install the `dev` extra to enable this guard")
    return exe


def test_unifile_package_has_no_py310_fstring_violations(_ruff_bin):
    """ruff, configured with target-version = py310 in pyproject.toml,
    must not report any `invalid-syntax` diagnostics for the unifile/
    package. Three historical violations in classifier.py and workers.py
    were fixed in v9.3.3; this test prevents regressions."""
    result = subprocess.run(
        [_ruff_bin, "check", "--output-format=json", str(UNIFILE_DIR)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    # Ruff exits non-zero when there are any violations; we only care about
    # invalid-syntax specifically, so don't assert on returncode.
    try:
        diagnostics = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        pytest.fail(
            f"ruff JSON output unparseable — stdout was:\n{result.stdout[:500]}\n"
            f"stderr:\n{result.stderr[:500]}"
        )
    syntax_errors = [
        d for d in diagnostics
        if d.get("code") == "invalid-syntax"
    ]
    if syntax_errors:
        formatted = "\n".join(
            f"  {d['filename']}:{d['location']['row']}: {d['message']}"
            for d in syntax_errors[:10]
        )
        pytest.fail(
            f"ruff reported {len(syntax_errors)} invalid-syntax diagnostic(s) — "
            f"likely Python 3.10/3.11 f-string incompat:\n{formatted}"
        )
