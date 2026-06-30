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

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"
BOOTSTRAP = ROOT / "unifile" / "bootstrap.py"
EXPECTED_REQUIREMENTS = ["-e .[full,media,ocr,dev]"]
REQUIRED_DEV = {"pytest", "pytest-qt", "ruff", "pip-audit", "packaging"}
PARSER_MINIMUMS = {
    "pillow": "12.2.0",
    "pillow-heif": "1.4.0",
    "exifread": "3.5.1",
    "mutagen": "1.48.1",
    "pypdf": "6.14.2",
    "python-docx": "1.2.0",
    "python-pptx": "1.0.2",
    "openpyxl": "3.1.5",
    "psd-tools": "1.17.4",
    "rarfile": "4.2",
    "py7zr": "1.1.3",
    "opencv-python-headless": "4.13.0.92",
    "guessit": "4.0.2",
    "pyyaml": "6.0.3",
    "pyacoustid": "1.3.1",
    "musicbrainzngs": "0.7.1",
    "pytesseract": "0.3.13",
    "easyocr": "1.7.2",
    "pdfminer-six": "20260107",
    "pymupdf": "1.28.0",
    "pdf2image": "1.17.0",
}
REQUIRED_EXTRA_PACKAGES = {
    "full": set(PARSER_MINIMUMS),
    "media": {"mutagen", "pyacoustid", "musicbrainzngs"},
    "ocr": {"pytesseract", "easyocr", "pdfminer-six", "pymupdf", "pdf2image"},
}


def _name(spec: str) -> str:
    try:
        return str(canonicalize_name(Requirement(spec).name))
    except Exception:
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", spec)
        return str(canonicalize_name(match.group(1) if match else spec))


def _specs_by_name(specs: list[str]) -> dict[str, str]:
    return {_name(spec): spec for spec in specs}


def _has_required_floor(spec: str, minimum: str) -> bool:
    requirement = Requirement(spec)
    required_version = Version(minimum)
    for specifier in requirement.specifier:
        if specifier.operator in {">=", "==", "===", "~="} and Version(specifier.version) >= required_version:
            return True
    return False


def _pyproject_packages() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    base = _specs_by_name(project.get("dependencies", []))
    extras = {
        extra: _specs_by_name(specs)
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


def _bootstrap_packages() -> tuple[dict[str, str], dict[str, str]]:
    tree = ast.parse(BOOTSTRAP.read_text(encoding="utf-8"))
    required: dict[str, str] = {}
    optional: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"required", "optional"}:
                values = ast.literal_eval(node.value)
                if target.id == "required":
                    required.update(_specs_by_name(values))
                else:
                    optional.update(_specs_by_name(values))
    return required, optional


def main() -> int:
    errors: list[str] = []
    base, extras = _pyproject_packages()
    all_declared = set(base)
    for packages in extras.values():
        all_declared |= set(packages)

    req_lines = _requirements_lines()
    if req_lines != EXPECTED_REQUIREMENTS:
        errors.append(
            f"requirements.txt must contain only {EXPECTED_REQUIREMENTS!r}; got {req_lines!r}"
        )

    bootstrap_required, bootstrap_optional = _bootstrap_packages()
    missing_required = set(bootstrap_required) - set(base)
    missing_optional = set(bootstrap_optional) - all_declared
    if missing_required:
        errors.append(f"bootstrap required packages missing from project.dependencies: {sorted(missing_required)}")
    if missing_optional:
        errors.append(f"bootstrap optional packages missing from pyproject extras: {sorted(missing_optional)}")

    dev = extras.get("dev", {})
    missing_dev = REQUIRED_DEV - set(dev)
    if missing_dev:
        errors.append(f"dev extra missing required tooling: {sorted(missing_dev)}")

    for extra, required_packages in REQUIRED_EXTRA_PACKAGES.items():
        declared = extras.get(extra, {})
        missing = required_packages - set(declared)
        if missing:
            errors.append(f"{extra} extra missing parser/audit packages: {sorted(missing)}")

    for extra_name, packages in extras.items():
        for name, spec in packages.items():
            minimum = PARSER_MINIMUMS.get(name)
            if minimum and not _has_required_floor(spec, minimum):
                errors.append(
                    f"{extra_name} extra must require {name}>={minimum}; got {spec!r}"
                )

    if errors:
        for error in errors:
            print(f"dependency manifest check failed: {error}", file=sys.stderr)
        return 1
    print("dependency manifest check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
