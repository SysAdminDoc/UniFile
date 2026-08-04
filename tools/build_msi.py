"""Build the unsigned per-user UniFile Windows Installer package."""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "dist" / "UniFile"
DEFAULT_OUTPUT = ROOT / "dist"
VERSION_PATTERN = re.compile(r"^(?:0|[1-9]\d{0,3})\.(?:0|[1-9]\d{0,3})\.(?:0|[1-9]\d{0,3})$")


def project_version() -> str:
    """Read the release version from the package's single source of truth."""
    init_text = (ROOT / "unifile" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.MULTILINE)
    if not match:
        raise RuntimeError("could not find __version__ in unifile/__init__.py")
    return match.group(1)


def validate_version(version: str) -> str:
    """Validate the three-part numeric version format accepted by MSI."""
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"MSI version must be MAJOR.MINOR.PATCH, got {version!r}")
    return version


def build_command(
    source: Path,
    output: Path,
    version: str,
    *,
    wix_executable: str = "wix",
) -> list[str]:
    """Return the deterministic WiX command used by :func:`build_msi`."""
    validate_version(version)
    return [
        wix_executable,
        "build",
        "-arch",
        "x64",
        str(ROOT / "installer" / "UniFile.wxs"),
        "-d",
        f"ProductVersion={version}",
        "-d",
        f"BuildOutput={source}",
        "-d",
        f"ProjectRoot={ROOT}",
        "-o",
        str(output),
    ]


def build_msi(
    source: Path = DEFAULT_SOURCE,
    output: Path | None = None,
    version: str | None = None,
    *,
    wix_executable: str = "wix",
) -> Path:
    """Build and return an MSI containing the frozen application payload."""
    source = source.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"frozen payload directory not found: {source}")
    executable = source / "UniFile.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"frozen executable not found: {executable}")
    wix_path = shutil.which(wix_executable) if not Path(wix_executable).is_file() else wix_executable
    if wix_path is None:
        raise FileNotFoundError("WiX Toolset CLI 'wix' is not installed or not on PATH")

    release_version = validate_version(version or project_version())
    target = (output or (DEFAULT_OUTPUT / f"UniFile-v{release_version}.msi")).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    command = build_command(source, target, release_version, wix_executable=wix_path)
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        raise RuntimeError(f"WiX build failed with exit code {result.returncode}\n{detail}")
    if not target.is_file():
        raise RuntimeError(f"WiX reported success but did not create {target}")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="PyInstaller payload directory")
    parser.add_argument("--output", type=Path, default=None, help="MSI output path")
    parser.add_argument("--version", default=None, help="Override the package version")
    parser.add_argument("--wix", default="wix", help="WiX CLI executable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = build_msi(args.source, args.output, args.version, wix_executable=args.wix)
    except Exception as exc:
        print(f"MSI build failed: {exc}", file=sys.stderr)
        return 1
    print(f"MSI build passed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
