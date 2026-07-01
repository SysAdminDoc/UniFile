#!/usr/bin/env python
"""Generate release audit artifacts: SBOM, license inventory, vulnerability report.

Usage:
    python tools/release_audit.py [--output dist/UniFile]

Produces:
    sbom.json       — CycloneDX-lite dependency list
    licenses.json   — package → license mapping
    vulnerabilities.txt — pip-audit output
    checksums.sha256 — SHA-256 of all artifacts in output dir
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _run_capture(*cmd, timeout=60):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                            cwd=ROOT)
    return result


def generate_sbom(output_dir: Path) -> Path:
    """Write a CycloneDX-lite SBOM from pip list."""
    result = _run_capture(PY, "-m", "pip", "list", "--format=json", "--local")
    if result.returncode != 0:
        raise RuntimeError(f"pip list failed: {result.stderr}")
    packages = json.loads(result.stdout)
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "components": [
            {"type": "library", "name": p["name"], "version": p["version"]}
            for p in packages
        ],
    }
    path = output_dir / "sbom.json"
    path.write_text(json.dumps(sbom, indent=2), encoding="utf-8")
    return path


def generate_license_inventory(output_dir: Path) -> Path:
    """Write package → license mapping."""
    result = _run_capture(PY, "-m", "pip", "list", "--format=json", "--local")
    if result.returncode != 0:
        raise RuntimeError(f"pip list failed: {result.stderr}")
    packages = json.loads(result.stdout)
    inventory = {}
    for pkg in packages:
        show = _run_capture(PY, "-m", "pip", "show", pkg["name"])
        license_line = ""
        for line in show.stdout.splitlines():
            if line.startswith("License:"):
                license_line = line.split(":", 1)[1].strip()
                break
        inventory[pkg["name"]] = {
            "version": pkg["version"],
            "license": license_line or "UNKNOWN",
        }
    path = output_dir / "licenses.json"
    path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return path


def generate_vulnerability_report(output_dir: Path) -> tuple[Path, bool]:
    """Run pip-audit and write results. Returns (path, has_high_severity)."""
    result = _run_capture(PY, "-m", "pip_audit", "--local", "--format=json",
                          timeout=120)
    path = output_dir / "vulnerabilities.json"
    has_high = False
    if result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            for dep in data.get("dependencies", []):
                for vuln in dep.get("vulns", []):
                    severity = vuln.get("fix_versions", [])
                    if severity:
                        has_high = True
        except json.JSONDecodeError:
            path.write_text(result.stdout, encoding="utf-8")
    else:
        path.write_text(result.stderr or "No output", encoding="utf-8")
    return path, has_high


def generate_checksums(output_dir: Path) -> Path:
    """Write SHA-256 checksums for all files in output_dir."""
    path = output_dir / "checksums.sha256"
    lines = []
    for f in sorted(output_dir.iterdir()):
        if f.name == "checksums.sha256" or f.is_dir():
            continue
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f"{h}  {f.name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "UniFile",
                        help="Output directory for audit artifacts")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"Generating release audit in {args.output}")

    sbom = generate_sbom(args.output)
    print(f"  SBOM: {sbom}")

    licenses = generate_license_inventory(args.output)
    print(f"  Licenses: {licenses}")

    vulns, has_high = generate_vulnerability_report(args.output)
    print(f"  Vulnerabilities: {vulns}" + (" (HIGH SEVERITY FOUND)" if has_high else ""))

    checksums = generate_checksums(args.output)
    print(f"  Checksums: {checksums}")

    if has_high:
        print("\nWARNING: High-severity vulnerabilities found. Review before release.")
        return 1
    print("\nRelease audit complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
