"""Enforce the roadmap coverage floor for UniFile's core modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MINIMUM_COVERAGE = 60.0
TARGETS = (
    "unifile/classifier.py",
    "unifile/engine.py",
    "unifile/learning.py",
    "unifile/tagging/library.py",
)


def _normalized(path: str) -> str:
    return path.replace("\\", "/").lower()


def check_report(report_path: Path) -> list[tuple[str, float]]:
    """Return core modules that fall below the configured percentage floor."""
    payload: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    files: dict[str, Any] = payload.get("files", {})
    failures: list[tuple[str, float]] = []
    for target in TARGETS:
        match = next(
            (data for path, data in files.items() if _normalized(path).endswith(target)),
            None,
        )
        if match is None:
            raise ValueError(f"coverage report is missing {target}")
        percentage = float(match["summary"]["percent_covered"])
        if percentage < MINIMUM_COVERAGE:
            failures.append((target, percentage))
    return failures


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: check_core_coverage.py COVERAGE_JSON", file=sys.stderr)
        return 2
    report_path = Path(args[0])
    try:
        failures = check_report(report_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"core coverage gate failed: {exc}", file=sys.stderr)
        return 2
    if failures:
        details = ", ".join(f"{path}={percentage:.1f}%" for path, percentage in failures)
        print(
            f"core coverage gate failed (<{MINIMUM_COVERAGE:.0f}%): {details}",
            file=sys.stderr,
        )
        return 1
    print(
        "core coverage gate passed: "
        + ", ".join(f"{path} >= {MINIMUM_COVERAGE:.0f}%" for path in TARGETS)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
