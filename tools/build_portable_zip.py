"""Build the self-contained portable UniFile ZIP release artifact."""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import zipfile
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
    """Validate the three-part version used in the portable artifact name."""
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"portable ZIP version must be MAJOR.MINOR.PATCH, got {version!r}")
    return version


def archive_name(version: str) -> str:
    """Return the release ZIP filename for ``version``."""
    return f"UniFile-portable-v{validate_version(version)}.zip"


def _write_file(zf: zipfile.ZipFile, source: Path, archive_path: str) -> None:
    """Add a file with a normalized forward-slash archive path."""
    zf.write(source, archive_path.replace("\\", "/"))


def build_portable_zip(
    source: Path = DEFAULT_SOURCE,
    output: Path | None = None,
    version: str | None = None,
) -> Path:
    """Package the frozen payload, marker, license, and usage docs into a ZIP."""
    source = source.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"frozen payload directory not found: {source}")
    if not (source / "UniFile.exe").is_file():
        raise FileNotFoundError(f"frozen executable not found: {source / 'UniFile.exe'}")

    release_version = validate_version(version or project_version())
    root_name = f"UniFile-portable-v{release_version}"
    target = (output or (DEFAULT_OUTPUT / archive_name(release_version))).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}-", suffix=".tmp", dir=target.parent, delete=False
        ) as temporary:
            temporary_name = temporary.name
        with zipfile.ZipFile(temporary_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for path in sorted(source.rglob("*")):
                if path.is_file() and path.name != "UniFile.exe.sha256":
                    relative = path.relative_to(source).as_posix()
                    _write_file(zf, path, f"{root_name}/{relative}")
            zf.writestr(f"{root_name}/portable.flag", "UniFile portable mode\n")
            _write_file(zf, ROOT / "README.md", f"{root_name}/README.md")
            _write_file(zf, ROOT / "LICENSE", f"{root_name}/LICENSE")
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="PyInstaller payload directory")
    parser.add_argument("--output", type=Path, default=None, help="ZIP output path")
    parser.add_argument("--version", default=None, help="Override the package version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = build_portable_zip(args.source, args.output, args.version)
    except Exception as exc:
        print(f"portable ZIP build failed: {exc}", file=sys.stderr)
        return 1
    print(f"portable ZIP build passed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
