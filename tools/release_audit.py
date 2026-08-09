#!/usr/bin/env python
"""Build artifact-scoped release evidence for UniFile.

The release gate audits the dependency graph declared by the project manifest,
not every package installed in the developer's interpreter.  It records the
release artifacts that were actually supplied, their deterministic hashes and
provenance, a CycloneDX SBOM with purls and relationships, license metadata,
and a severity-aware vulnerability policy result.

Usage:
    python tools/release_audit.py
    python tools/release_audit.py --offline --artifact path/to/artifact.zip
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as importlib_metadata
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
REPOSITORY_URL = "https://github.com/SysAdminDoc/UniFile"
AUDIT_SCHEMA_VERSION = 1
AUDIT_FILENAMES = (
    "audit.json",
    "sbom.json",
    "licenses.json",
    "vulnerabilities.json",
)


@dataclass(frozen=True)
class ProjectTarget:
    """A manifest whose resolved dependencies back one or more artifacts."""

    project_id: str
    root: Path
    manifest: Path
    build_command: str


@dataclass(frozen=True)
class CommandResult:
    """Bounded subprocess result with failures represented as data."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    missing: bool = False
    error: str = ""


def project_targets() -> dict[str, ProjectTarget]:
    """Return the supported release dependency targets."""
    return {
        "unifile": ProjectTarget(
            "unifile",
            ROOT,
            ROOT / "pyproject.toml",
            "python tools/build_portable_zip.py / python tools/build_msi.py",
        ),
        "sdk": ProjectTarget(
            "sdk",
            ROOT / "sdk",
            ROOT / "sdk" / "pyproject.toml",
            "python tools/build_sdk.py",
        ),
    }


def _normalize_name(name: str) -> str:
    """Normalize a Python distribution name for graph joins and purls."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _purl(name: str, version: str) -> str:
    return f"pkg:pypi/{_normalize_name(name)}@{version}"


def _project_manifest(target: ProjectTarget) -> dict[str, Any]:
    with target.manifest.open("rb") as handle:
        document = tomllib.load(handle)
    project = document.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"{target.manifest} has no [project] table")
    name = str(project.get("name", "")).strip()
    version = str(project.get("version", "")).strip()
    if not name or not version:
        raise ValueError(f"{target.manifest} must declare project name and version")
    return {
        "name": name,
        "version": version,
        "dependencies": [
            str(value)
            for value in project.get("dependencies", [])
            if isinstance(value, str)
        ],
        "license": _manifest_license(project, target.root),
    }


def _manifest_license(project: dict[str, Any], root: Path) -> str:
    """Resolve a manifest license into a useful, stable display value."""
    raw = project.get("license")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        expression = raw.get("text") or raw.get("file")
        if isinstance(expression, str) and expression.strip():
            value = expression.strip()
            if value.lower().endswith("license") and (root / value).is_file():
                text = (root / value).read_text(encoding="utf-8", errors="replace")
                if "MIT License" in text:
                    return "MIT"
                return f"FILE:{value}"
            return value
    for classifier in project.get("classifiers", []):
        prefix = "License :: OSI Approved :: "
        if isinstance(classifier, str) and classifier.startswith(prefix):
            return classifier.removeprefix(prefix)
    return "UNKNOWN"


def _requirement_name(raw_requirement: str) -> str | None:
    """Return a normalized requirement name when its marker is active."""
    try:
        from packaging.requirements import Requirement

        requirement = Requirement(raw_requirement)
        if requirement.marker is not None and not requirement.marker.evaluate():
            return None
        return _normalize_name(requirement.name)
    except (ImportError, ValueError):
        # The release environment includes packaging through the dev extra.
        # Keep an intentionally conservative fallback for offline diagnostics.
        value = raw_requirement.split(";", 1)[0].strip()
        value = re.split(r"[<>=!~\[\s]", value, maxsplit=1)[0]
        return _normalize_name(value) if value else None


def _distribution_index() -> dict[str, importlib_metadata.Distribution]:
    distributions: dict[str, importlib_metadata.Distribution] = {}
    for distribution in importlib_metadata.distributions():
        name = distribution.metadata.get("Name") or distribution.name
        if name:
            distributions.setdefault(_normalize_name(name), distribution)
    return distributions


def _license_name(
    metadata: importlib_metadata.PackageMetadata | None,
    fallback: str = "UNKNOWN",
) -> tuple[str, str]:
    if metadata is None:
        return fallback, "unresolved"
    expression = metadata.get("License-Expression")
    if expression and expression.strip():
        return expression.strip(), "distribution-metadata"
    license_value = metadata.get("License")
    if license_value and license_value.strip() and license_value.strip().lower() not in {
        "unknown",
        "none",
    }:
        return license_value.strip(), "distribution-metadata"
    prefix = "License :: OSI Approved :: "
    for classifier in metadata.get_all("Classifier", []):
        if classifier.startswith(prefix):
            return classifier.removeprefix(prefix), "distribution-classifier"
    return fallback, "unresolved"


def _cyclonedx_licenses(name: str) -> list[dict[str, Any]]:
    if name == "UNKNOWN":
        return [{"license": {"name": "UNKNOWN"}}]
    return [{"license": {"name": name}}]


def _component(
    name: str,
    version: str,
    distribution: importlib_metadata.Distribution | None,
    *,
    project_id: str,
    component_type: str = "library",
    license_fallback: str = "UNKNOWN",
) -> dict[str, Any]:
    metadata = distribution.metadata if distribution is not None else None
    license_name, license_source = _license_name(metadata, license_fallback)
    return {
        "bom-ref": _purl(name, version),
        "name": name,
        "type": component_type,
        "version": version,
        "purl": _purl(name, version),
        "scope": "required",
        "licenses": _cyclonedx_licenses(license_name),
        "properties": [
            {"name": "unifile:dependency-project", "value": project_id},
            {"name": "unifile:license-source", "value": license_source},
        ],
    }


def _resolve_local_graph(
    target: ProjectTarget,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Resolve active manifest requirements against installed distributions."""
    distributions = _distribution_index()
    root_ref = _purl(manifest["name"], manifest["version"])
    components: dict[str, dict[str, Any]] = {}
    edges: dict[str, set[str]] = {root_ref: set()}
    queued: list[tuple[str, str]] = [
        (root_ref, requirement) for requirement in manifest["dependencies"]
    ]
    seen: set[tuple[str, str]] = set()
    unresolved: list[str] = []

    while queued:
        parent_ref, raw_requirement = queued.pop(0)
        name = _requirement_name(raw_requirement)
        if name is None:
            continue
        key = (parent_ref, name)
        if key in seen:
            continue
        seen.add(key)
        distribution = distributions.get(name)
        if distribution is None:
            unresolved.append(name)
            continue
        version = distribution.version
        reference = _purl(name, version)
        edges.setdefault(parent_ref, set()).add(reference)
        if name in components:
            continue
        component = _component(
            distribution.metadata.get("Name") or name,
            version,
            distribution,
            project_id=target.project_id,
        )
        components[name] = component
        for requirement in distribution.requires or []:
            queued.append((reference, requirement))

    return {
        "root_ref": root_ref,
        "root_requirements": manifest["dependencies"],
        "components": components,
        "edges": edges,
        "unresolved": sorted(set(unresolved)),
    }


def _run_capture(*command: str, timeout: int = 60) -> CommandResult:
    """Run a release helper with a hard timeout and structured failures."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            None,
            _text_output(exc.stdout),
            _text_output(exc.stderr),
            timed_out=True,
            error=f"command timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return CommandResult(None, "", "", missing=True, error=str(exc))
    except OSError as exc:
        return CommandResult(None, "", "", error=f"{type(exc).__name__}: {exc}")
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _text_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _severity(raw: Any) -> str:
    """Normalize advisory severity without using fix availability as severity."""
    value = raw
    if isinstance(raw, dict):
        value = raw.get("severity") or raw.get("score")
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("score") or value.get("value")
    if isinstance(value, (int, float)):
        if value >= 9:
            return "critical"
        if value >= 7:
            return "high"
        if value >= 4:
            return "medium"
        if value > 0:
            return "low"
        return "unknown"
    normalized = str(value or "").strip().lower()
    aliases = {
        "moderate": "medium",
        "informational": "low",
        "none": "unknown",
        "": "unknown",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"critical", "high", "medium", "low"} else "unknown"


def _vulnerability_record(vulnerability: dict[str, Any]) -> dict[str, Any]:
    aliases = vulnerability.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    record: dict[str, Any] = {
        "id": str(vulnerability.get("id") or "UNKNOWN"),
        "aliases": sorted(str(alias) for alias in aliases),
        "severity": _severity(vulnerability),
        "fix_versions": sorted(
            str(version) for version in vulnerability.get("fix_versions", [])
        ),
    }
    description = vulnerability.get("description")
    if description:
        record["description"] = str(description)
    return record


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}
    for row in rows:
        for vulnerability in row.get("vulnerabilities", []):
            severity = vulnerability["severity"]
            counts[severity] += 1
    return counts


def _graph_for_components(
    target: ProjectTarget,
    manifest: dict[str, Any],
    local_graph: dict[str, Any],
    components: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    refs = {component["bom-ref"] for component in components.values()}
    refs.add(local_graph["root_ref"])
    edges: dict[str, set[str]] = {reference: set() for reference in refs}
    for raw_requirement in manifest["dependencies"]:
        name = _requirement_name(raw_requirement)
        if name in components:
            edges[local_graph["root_ref"]].add(components[name]["bom-ref"])
    distribution_index = _distribution_index()
    for name, component in components.items():
        distribution = distribution_index.get(name)
        if distribution is None:
            continue
        for raw_requirement in distribution.requires or []:
            child_name = _requirement_name(raw_requirement)
            if child_name in components:
                edges[component["bom-ref"]].add(components[child_name]["bom-ref"])
    return [
        {"ref": reference, "dependsOn": sorted(edges[reference])}
        for reference in sorted(edges)
    ]


def _failure_evidence(
    target: ProjectTarget,
    manifest: dict[str, Any],
    local_graph: dict[str, Any],
    *,
    failure_kind: str,
    message: str,
    mode: str = "pip-audit",
) -> dict[str, Any]:
    rows = [
        {
            "name": component["name"],
            "version": component["version"],
            "purl": component["purl"],
            "vulnerability_status": "not-audited",
            "vulnerabilities": [],
        }
        for component in local_graph["components"].values()
    ]
    return {
        "project_id": target.project_id,
        "project": manifest["name"],
        "version": manifest["version"],
        "manifest": _display_path(target.manifest),
        "mode": mode,
        "status": "unknown",
        "failure": {"kind": failure_kind, "message": message},
        "components": [
            _component(
                manifest["name"],
                manifest["version"],
                None,
                project_id=target.project_id,
                component_type="application",
                license_fallback=manifest["license"],
            ),
            *local_graph["components"].values(),
        ],
        "dependencies": _graph_for_components(
            target,
            manifest,
            local_graph,
            local_graph["components"],
        ),
        "vulnerabilities": rows,
        "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0},
        "unresolved": local_graph["unresolved"],
    }


def _evidence_from_audit(
    target: ProjectTarget,
    manifest: dict[str, Any],
    local_graph: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    distribution_index = _distribution_index()
    rows: list[dict[str, Any]] = []
    components: dict[str, dict[str, Any]] = {}
    for dependency in payload.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        name = str(dependency.get("name", "")).strip()
        version = str(dependency.get("version", "")).strip()
        if not name or not version:
            continue
        normalized = _normalize_name(name)
        component = _component(
            name,
            version,
            distribution_index.get(normalized),
            project_id=target.project_id,
        )
        components[normalized] = component
        vulnerabilities = [
            _vulnerability_record(value)
            for value in dependency.get("vulns", [])
            if isinstance(value, dict)
        ]
        rows.append(
            {
                "name": name,
                "version": version,
                "purl": component["purl"],
                "vulnerability_status": "affected" if vulnerabilities else "clean",
                "vulnerabilities": vulnerabilities,
            }
        )
    rows.sort(key=lambda row: (row["name"].lower(), row["version"]))
    root = _component(
        manifest["name"],
        manifest["version"],
        None,
        project_id=target.project_id,
        component_type="application",
        license_fallback=manifest["license"],
    )
    counts = _counts(rows)
    if counts["critical"] or counts["high"]:
        status = "blocked"
    elif counts["unknown"]:
        status = "unknown"
    elif counts["medium"] or counts["low"]:
        status = "findings"
    else:
        status = "clean"
    return {
        "project_id": target.project_id,
        "project": manifest["name"],
        "version": manifest["version"],
        "manifest": _display_path(target.manifest),
        "mode": "pip-audit",
        "status": status,
        "components": [root, *components.values()],
        "dependencies": _graph_for_components(target, manifest, local_graph, components),
        "vulnerabilities": rows,
        "counts": counts,
        "unresolved": local_graph["unresolved"],
    }


def scan_project(
    target: ProjectTarget,
    *,
    timeout: int = 60,
    offline: bool = False,
) -> dict[str, Any]:
    """Resolve and audit one manifest, returning failures as actionable JSON."""
    manifest = _project_manifest(target)
    local_graph = _resolve_local_graph(target, manifest)
    if offline:
        return _failure_evidence(
            target,
            manifest,
            local_graph,
            failure_kind="offline",
            message="vulnerability service disabled; dependencies were resolved locally but not audited",
            mode="offline",
        )

    command = (
        PY,
        "-m",
        "pip_audit",
        str(target.root),
        "--format",
        "json",
        "--progress-spinner",
        "off",
        "--timeout",
        str(timeout),
    )
    result = _run_capture(*command, timeout=timeout)
    if result.timed_out:
        return _failure_evidence(
            target,
            manifest,
            local_graph,
            failure_kind="timeout",
            message=f"pip-audit timed out after {timeout}s",
        )
    if result.missing:
        return _failure_evidence(
            target,
            manifest,
            local_graph,
            failure_kind="tool-unavailable",
            message="pip-audit is not installed or could not be started",
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        detail = result.stderr.strip() or result.error or str(exc)
        return _failure_evidence(
            target,
            manifest,
            local_graph,
            failure_kind="invalid-tool-output",
            message=f"pip-audit did not return JSON: {detail[:500]}",
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("dependencies"), list):
        return _failure_evidence(
            target,
            manifest,
            local_graph,
            failure_kind="invalid-tool-output",
            message="pip-audit JSON has no dependency list",
        )
    evidence = _evidence_from_audit(target, manifest, local_graph, payload)
    if result.returncode not in (0, 1):
        evidence["status"] = "unknown"
        evidence["failure"] = {
            "kind": "audit-command-failed",
            "message": (result.stderr.strip() or f"pip-audit exited {result.returncode}")[:500],
        }
    return evidence


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _iter_artifact_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(child for child in path.rglob("*") if child.is_file())
    raise FileNotFoundError(path)


def artifact_digest(path: Path) -> tuple[str, int, int]:
    """Return deterministic SHA-256, total bytes, and file count for an artifact."""
    files = _iter_artifact_files(path)
    digest = hashlib.sha256()
    total_bytes = 0
    if path.is_dir():
        digest.update(b"unifile-directory-artifact-v1\0")
    for child in files:
        relative = child.relative_to(path).as_posix() if path.is_dir() else child.name
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        size = child.stat().st_size
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        total_bytes += size
        with child.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest(), total_bytes, len(files)


def _artifact_purl(project_id: str, version: str, kind: str) -> str:
    if project_id == "sdk":
        return _purl("unifile-sdk", version)
    return f"pkg:generic/unifile@{version}?artifact={kind}"


def _artifact_record(
    path: Path,
    *,
    kind: str,
    project_id: str,
    version: str,
    build_command: str,
) -> dict[str, Any]:
    digest, total_bytes, file_count = artifact_digest(path)
    return {
        "id": kind,
        "kind": kind,
        "path": _display_path(path),
        "size_bytes": total_bytes,
        "file_count": file_count,
        "sha256": digest,
        "purl": _artifact_purl(project_id, version, kind),
        "dependency_project": project_id,
        "provenance": {
            "repository": REPOSITORY_URL,
            "project_version": version,
            "manifest": _display_path(project_targets()[project_id].manifest),
            "build_command": build_command,
        },
    }


def _infer_artifact_kind(path: Path) -> tuple[str, str, str]:
    name = path.name.lower()
    if name.endswith(".whl") and "unifile_sdk" in name:
        return "sdk-wheel", "sdk", "python tools/build_sdk.py"
    if name.endswith(".msi"):
        return "msi", "unifile", "python tools/build_msi.py"
    if name.endswith(".zip"):
        return "portable-zip", "unifile", "python tools/build_portable_zip.py"
    return "artifact", "unifile", "python -m PyInstaller UniFile.spec"


def discover_artifacts(
    artifacts_root: Path,
    version: str,
    explicit: list[Path] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover the required current-version artifacts or explicit overrides."""
    targets = project_targets()
    if explicit:
        records = []
        missing = []
        for supplied in explicit:
            path = supplied.resolve()
            if not path.exists():
                missing.append(str(supplied))
                continue
            kind, project_id, build_command = _infer_artifact_kind(path)
            records.append(
                _artifact_record(
                    path,
                    kind=kind,
                    project_id=project_id,
                    version=version,
                    build_command=build_command,
                )
            )
        return records, missing

    expected: list[tuple[str, Path, str, str]] = [
        (
            "portable-zip",
            artifacts_root / f"UniFile-portable-v{version}.zip",
            "unifile",
            "python tools/build_portable_zip.py",
        ),
        (
            "msi",
            artifacts_root / f"UniFile-v{version}.msi",
            "unifile",
            "python tools/build_msi.py",
        ),
    ]
    sdk_matches = sorted(
        (artifacts_root / "sdk").glob(f"unifile_sdk-{version}-*.whl")
        if (artifacts_root / "sdk").is_dir()
        else []
    )
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for kind, path, project_id, build_command in expected:
        if not path.is_file():
            missing.append(_display_path(path))
            continue
        records.append(
            _artifact_record(
                path,
                kind=kind,
                project_id=project_id,
                version=version,
                build_command=build_command,
            )
        )
    if not sdk_matches:
        missing.append(_display_path(artifacts_root / "sdk" / f"unifile_sdk-{version}-*.whl"))
    for path in sdk_matches:
        records.append(
            _artifact_record(
                path,
                kind="sdk-wheel",
                project_id="sdk",
                version=version,
                build_command=targets["sdk"].build_command,
            )
        )
    return records, missing


def _build_sbom(
    version: str,
    artifacts: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    component_map: dict[str, dict[str, Any]] = {}
    dependency_map: dict[str, set[str]] = {}
    for project in evidence:
        for component in project["components"]:
            component_map[component["bom-ref"]] = component
        for dependency in project["dependencies"]:
            dependency_map.setdefault(dependency["ref"], set()).update(
                dependency.get("dependsOn", [])
            )
    properties = []
    for artifact in sorted(artifacts, key=lambda item: item["id"]):
        properties.extend(
            [
                {"name": f"unifile:artifact:{artifact['id']}:path", "value": artifact["path"]},
                {"name": f"unifile:artifact:{artifact['id']}:sha256", "value": artifact["sha256"]},
            ]
        )
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.5.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "unifile-release",
                "version": version,
                "purl": f"pkg:generic/unifile-release@{version}",
            },
            "tools": [{"vendor": "SysAdminDoc", "name": "UniFile release audit"}],
            "properties": properties,
        },
        "components": [component_map[key] for key in sorted(component_map)],
        "dependencies": [
            {"ref": reference, "dependsOn": sorted(dependency_map[reference])}
            for reference in sorted(dependency_map)
        ],
    }


def _build_license_inventory(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    projects: dict[str, list[dict[str, Any]]] = {}
    for project in evidence:
        rows = []
        for component in sorted(project["components"], key=lambda item: item["bom-ref"]):
            source = next(
                (
                    prop["value"]
                    for prop in component.get("properties", [])
                    if prop.get("name") == "unifile:license-source"
                ),
                "unknown",
            )
            rows.append(
                {
                    "name": component["name"],
                    "version": component["version"],
                    "purl": component["purl"],
                    "licenses": component.get("licenses", []),
                    "source": source,
                }
            )
        projects[project["project_id"]] = rows
    return {"schema_version": AUDIT_SCHEMA_VERSION, "projects": projects}


def _build_vulnerability_report(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "unknown": 0,
        "unknown_projects": 0,
    }
    projects = {}
    for project in evidence:
        projects[project["project_id"]] = {
            "status": project["status"],
            "mode": project["mode"],
            "dependencies": project["vulnerabilities"],
            "counts": project["counts"],
            "failure": project.get("failure"),
        }
        for severity in ("critical", "high", "medium", "low", "unknown"):
            summary[severity] += project["counts"][severity]
        if project["status"] == "unknown":
            summary["unknown_projects"] += 1
    if summary["unknown_projects"]:
        status = "unknown"
    elif summary["critical"] or summary["high"]:
        status = "blocked"
    elif summary["medium"] or summary["low"]:
        status = "findings"
    else:
        status = "clean"
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "policy": {
            "critical_or_high": "fail with exit code 1",
            "medium_or_low": "report and pass",
            "unknown_or_unavailable": "fail with exit code 2",
            "fix_versions_do_not_determine_severity": True,
        },
        "status": status,
        "summary": summary,
        "projects": projects,
    }


def _policy_exit_code(evidence: list[dict[str, Any]]) -> int:
    if any(project["status"] == "unknown" for project in evidence):
        return 2
    if any(project["counts"][severity] for project in evidence for severity in ("critical", "high")):
        return 1
    return 0


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_checksums(output_dir: Path) -> Path:
    path = output_dir / "checksums.sha256"
    lines = []
    for name in sorted(AUDIT_FILENAMES):
        file_path = output_dir / name
        digest, _, _ = artifact_digest(file_path)
        lines.append(f"{digest}  {name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _version() -> str:
    return _project_manifest(project_targets()["unifile"])["version"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "release-audit",
        help="directory for machine-readable audit evidence",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=ROOT / "dist",
        help="release artifact directory used by default discovery",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        action="append",
        default=None,
        help="audit one explicit artifact; repeat for multiple artifacts",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="per-project pip-audit timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="resolve local metadata but mark vulnerability status unknown",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("release audit failed: --timeout must be positive", file=sys.stderr)
        return 2
    try:
        version = _version()
        artifacts, missing = discover_artifacts(
            args.artifacts_root.resolve(),
            version,
            [path.resolve() for path in args.artifact] if args.artifact else None,
        )
        if missing:
            print(
                "release audit failed: missing required artifacts:\n- "
                + "\n- ".join(sorted(missing)),
                file=sys.stderr,
            )
            return 2
        targets = project_targets()
        project_ids = sorted({artifact["dependency_project"] for artifact in artifacts})
        evidence = [
            scan_project(targets[project_id], timeout=args.timeout, offline=args.offline)
            for project_id in project_ids
        ]
        output_dir = args.output.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        vulnerability_report = _build_vulnerability_report(evidence)
        sbom = _build_sbom(version, artifacts, evidence)
        licenses = _build_license_inventory(evidence)
        exit_code = _policy_exit_code(evidence)
        audit = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "status": vulnerability_report["status"],
            "exit_code": exit_code,
            "project_version": version,
            "artifacts": sorted(artifacts, key=lambda item: item["id"]),
            "dependency_projects": [
                {
                    "id": project["project_id"],
                    "manifest": project["manifest"],
                    "version": project["version"],
                    "mode": project["mode"],
                    "status": project["status"],
                    "unresolved": project["unresolved"],
                }
                for project in evidence
            ],
            "evidence_files": list(AUDIT_FILENAMES) + ["checksums.sha256"],
        }
        _write_json(output_dir / "sbom.json", sbom)
        _write_json(output_dir / "licenses.json", licenses)
        _write_json(output_dir / "vulnerabilities.json", vulnerability_report)
        _write_json(output_dir / "audit.json", audit)
        checksums = _write_checksums(output_dir)
        print(f"Release audit {vulnerability_report['status']}: {output_dir}")
        print(f"  artifacts: {len(artifacts)}")
        print(f"  dependency projects: {', '.join(project_ids)}")
        print(f"  checksums: {checksums}")
        return exit_code
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"release audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
