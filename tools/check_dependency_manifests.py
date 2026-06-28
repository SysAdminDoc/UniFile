"""Validate dependency manifest alignment.

`pyproject.toml` is authoritative. `requirements.txt` must delegate to the
project extras, and every package that the legacy bootstrap can install must be
declared in pyproject dependencies or optional dependencies.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"
BOOTSTRAP = ROOT / "unifile" / "bootstrap.py"
EXPECTED_REQUIREMENTS = ["-e .[full,media,ocr,dev]"]
REQUIRED_DEV = {"pytest", "pytest-qt", "ruff", "pip-audit"}


def _name(spec: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", spec)
    return (match.group(1) if match else spec).lower().replace("_", "-")


def _pyproject_packages() -> tuple[set[str], dict[str, set[str]]]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    base = {_name(spec) for spec in project.get("dependencies", [])}
    extras = {
        extra: {_name(spec) for spec in specs}
        for extra, specs in project.get("optional-dependencies", {}).items()
    }
    return base, extras


def _requirements_lines() -> list[str]:
    lines = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _bootstrap_packages() -> tuple[set[str], set[str]]:
    tree = ast.parse(BOOTSTRAP.read_text(encoding="utf-8"))
    required: set[str] = set()
    optional: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"required", "optional"}:
                values = ast.literal_eval(node.value)
                names = {_name(value) for value in values}
                if target.id == "required":
                    required |= names
                else:
                    optional |= names
    return required, optional


def main() -> int:
    errors: list[str] = []
    base, extras = _pyproject_packages()
    all_declared = set(base)
    for packages in extras.values():
        all_declared |= packages

    req_lines = _requirements_lines()
    if req_lines != EXPECTED_REQUIREMENTS:
        errors.append(
            f"requirements.txt must contain only {EXPECTED_REQUIREMENTS!r}; got {req_lines!r}"
        )

    bootstrap_required, bootstrap_optional = _bootstrap_packages()
    missing_required = bootstrap_required - base
    missing_optional = bootstrap_optional - all_declared
    if missing_required:
        errors.append(f"bootstrap required packages missing from project.dependencies: {sorted(missing_required)}")
    if missing_optional:
        errors.append(f"bootstrap optional packages missing from pyproject extras: {sorted(missing_optional)}")

    dev = extras.get("dev", set())
    missing_dev = REQUIRED_DEV - dev
    if missing_dev:
        errors.append(f"dev extra missing required tooling: {sorted(missing_dev)}")

    if errors:
        for error in errors:
            print(f"dependency manifest check failed: {error}", file=sys.stderr)
        return 1
    print("dependency manifest check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
