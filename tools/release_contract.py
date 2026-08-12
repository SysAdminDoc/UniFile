"""Validate release metadata and the public headless scan contract.

The package version is defined by ``unifile.__version__``.  This gate keeps
the small set of user-facing release surfaces synchronized and exercises the
README scan/API promise against the live Qt-free implementation.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_VERSION_RE = r"\d+\.\d+\.\d+"


@dataclass(frozen=True)
class VersionSurface:
    """A checked-in file and the expression that exposes its release version."""

    path: str
    pattern: str
    description: str


VERSION_SURFACES = (
    VersionSurface("pyproject.toml", r"(?m)^version\s*=\s*\"([^\"\r\n]+)\"", "package manifest"),
    VersionSurface("sdk/pyproject.toml", r"(?m)^version\s*=\s*\"([^\"\r\n]+)\"", "SDK manifest"),
    VersionSurface("unifile/__init__.py", r"(?m)^__version__\s*=\s*[\"']([^\"']+)[\"']", "runtime package"),
    VersionSurface("README.md", rf"version-({_VERSION_RE})-blue", "README badge"),
    VersionSurface("CLAUDE.md", rf"(?<!\d)({_VERSION_RE})(?!\d)", "working-note version surfaces"),
    VersionSurface("docs/conf.py", rf"(?m)^release\s*=\s*[\"']({_VERSION_RE})[\"']", "Sphinx release"),
    VersionSurface("docs/index.rst", rf"unifile_sdk-({_VERSION_RE})-py3-none-any\.whl", "SDK install example"),
    VersionSurface("run.py", rf"UniFile v({_VERSION_RE})", "launch-script banner"),
    VersionSurface("unifile/bootstrap.py", rf"UniFile v({_VERSION_RE})", "bootstrap banner"),
    VersionSurface("smoke_ver.txt", rf"(?m)^UniFile ({_VERSION_RE})$", "frozen smoke marker"),
    VersionSurface("CHANGELOG.md", rf"(?ms)\A# Changelog.*?^## \[v({_VERSION_RE})\]", "current changelog heading"),
)

SCAN_RESPONSE_FIELDS = frozenset({
    "version",
    "timestamp",
    "source",
    "destination",
    "mode",
    "apply_rules",
    "dry_run",
    "min_confidence",
    "rules_count",
    "items",
    "count",
    "selected_count",
    "would_move",
    "moved",
    "failed",
    "errors",
    "action_plan",
})
ACTION_PLAN_FIELDS = frozenset({
    "schema_version",
    "plan_type",
    "source_root",
    "destination_roots",
    "nodes",
    "stats",
    "actions",
})
README_CONTRACT_MARKERS = (
    "python -m unifile scan",
    "--dry-run",
    "canonical `action_plan`",
    "same versioned JSON plan shape",
    '`{"verify": true}`',
)


def project_version(root: Path = ROOT) -> str:
    """Read the package version without importing optional GUI dependencies."""
    source = (root / "unifile" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r"(?m)^__version__\s*=\s*[\"']([^\"']+)[\"']", source)
    if not match:
        raise ValueError("unifile/__init__.py does not declare __version__")
    return match.group(1)


def _extract(path: Path, pattern: str) -> list[str]:
    return re.findall(pattern, path.read_text(encoding="utf-8"))


def check_version_surfaces(root: Path = ROOT) -> list[str]:
    """Return file-specific errors for stale or missing release metadata."""
    version = project_version(root)
    errors: list[str] = []
    for surface in VERSION_SURFACES:
        path = root / surface.path
        if not path.is_file():
            errors.append(f"{surface.path}: missing {surface.description} file")
            continue
        try:
            values = _extract(path, surface.pattern)
        except OSError as exc:
            errors.append(f"{surface.path}: could not read {surface.description}: {exc}")
            continue
        if not values:
            errors.append(f"{surface.path}: no {surface.description} version found")
            continue
        stale = sorted({value for value in values if value != version})
        if stale:
            errors.append(
                f"{surface.path}: {surface.description} has {stale!r}; expected {version!r}"
            )
    return errors


def _run_cli_scan(root: Path, source: Path, destination: Path) -> dict:
    """Run the documented scan command and decode its JSON response."""
    import json

    env = os.environ.copy()
    env["APPDATA"] = str(root / "appdata")
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unifile",
            "scan",
            str(source),
            "--json",
            "--destination",
            str(destination),
            "--dry-run",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"README scan command failed: {completed.stderr.strip()}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("README scan command did not emit JSON") from exc


def _validate_scan_result(result: dict, label: str) -> list[str]:
    errors: list[str] = []
    missing = sorted(SCAN_RESPONSE_FIELDS - set(result))
    if missing:
        errors.append(f"{label}: scan response is missing fields {missing!r}")
    plan = result.get("action_plan")
    if not isinstance(plan, dict):
        errors.append(f"{label}: action_plan must be an object")
        return errors
    missing_plan = sorted(ACTION_PLAN_FIELDS - set(plan))
    if missing_plan:
        errors.append(f"{label}: action_plan is missing fields {missing_plan!r}")
    if plan.get("schema_version") != 1:
        errors.append(f"{label}: unsupported action_plan schema {plan.get('schema_version')!r}")
    if plan.get("plan_type") != "file-actions":
        errors.append(f"{label}: unexpected action_plan type {plan.get('plan_type')!r}")
    return errors


def check_public_scan_contract(root: Path = ROOT) -> list[str]:
    """Exercise CLI, headless service, and README claims on a disposable fixture."""
    errors: list[str] = []
    readme = (root / "README.md").read_text(encoding="utf-8")
    for marker in README_CONTRACT_MARKERS:
        if marker not in readme:
            errors.append(f"README.md: missing scan/API contract marker {marker!r}")
    if errors:
        return errors

    sys.path.insert(0, str(root))
    try:
        from unifile import cli_scan
        from unifile.headless import HeadlessService

        with tempfile.TemporaryDirectory(prefix="unifile-release-contract-") as temp:
            fixture_root = Path(temp)
            source = fixture_root / "inbox"
            destination = fixture_root / "organized"
            source.mkdir()
            (source / "release-contract.txt").write_text("fixture", encoding="utf-8")
            cli_result = cli_scan.scan_directory(
                source,
                destination=destination,
                apply_rules=True,
                dry_run=True,
            )
            service = HeadlessService(
                source,
                scan_roots=[str(source), str(destination)],
            )
            api_result = service.scan(
                str(source),
                destination=str(destination),
                apply_rules=True,
                dry_run=True,
            )
            errors.extend(_validate_scan_result(cli_result, "CLI"))
            errors.extend(_validate_scan_result(api_result, "headless API"))
            for field in ("version", "destination", "apply_rules", "dry_run"):
                if api_result.get(field) != cli_result.get(field):
                    errors.append(
                        f"headless API: field {field!r} differs from CLI "
                        f"({api_result.get(field)!r} != {cli_result.get(field)!r})"
                    )
            if api_result.get("action_plan", {}).get("plan_type") != cli_result.get("action_plan", {}).get("plan_type"):
                errors.append("headless API: action_plan type differs from CLI")
            cli_example = _run_cli_scan(root, source, destination)
            errors.extend(_validate_scan_result(cli_example, "README CLI example"))
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        errors.append(f"public scan contract could not execute: {exc}")
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass
    return errors


def check_release(root: Path = ROOT) -> list[str]:
    """Run all release metadata and public-contract checks."""
    return [*check_version_surfaces(root), *check_public_scan_contract(root)]


def main() -> int:
    errors = check_release()
    if errors:
        for error in errors:
            print(f"release contract check failed: {error}", file=sys.stderr)
        return 1
    print(f"release contract check passed for UniFile v{project_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
