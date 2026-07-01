"""Smoke-test a frozen UniFile build and emit a SHA-256 sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = ROOT / "dist" / "UniFile" / ("UniFile.exe" if os.name == "nt" else "UniFile")
GUI_SMOKE_EXIT_ENV = "UNIFILE_GUI_SMOKE_EXIT_MS"


def default_executable() -> Path:
    """Return the default PyInstaller output path for the current platform."""
    return DEFAULT_EXE


def _run(command: list[str], *, timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _assert_ok(name: str, result: subprocess.CompletedProcess) -> None:
    if result.returncode != 0:
        detail = "\n".join(
            part for part in (
                f"{name} failed with exit code {result.returncode}",
                result.stdout.strip(),
                result.stderr.strip(),
            )
            if part
        )
        raise RuntimeError(detail)


def smoke_version(exe: Path, *, timeout: int) -> None:
    result = _run([str(exe), "--version"], timeout=timeout)
    _assert_ok("version smoke", result)
    if "UniFile" not in result.stdout:
        raise RuntimeError(f"version smoke returned unexpected output: {result.stdout!r}")


def smoke_classify(exe: Path, *, timeout: int) -> None:
    with tempfile.TemporaryDirectory(prefix="unifile-smoke-") as temp_dir:
        sample = Path(temp_dir) / "sample.pdf"
        sample.write_bytes(b"%PDF-1.4\n% UniFile smoke fixture\n")
        result = _run([str(exe), "classify", str(sample), "--json"], timeout=timeout)
    _assert_ok("classify smoke", result)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"classify smoke returned invalid JSON: {result.stdout!r}") from exc
    if payload.get("kind") != "file" or not payload.get("category"):
        raise RuntimeError(f"classify smoke returned incomplete payload: {payload!r}")


def smoke_gui(exe: Path, *, timeout: int) -> None:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault(GUI_SMOKE_EXIT_ENV, "1200")
    result = _run([str(exe)], timeout=timeout, env=env)
    _assert_ok("GUI startup smoke", result)


def write_sha256_sidecar(exe: Path, sidecar: Path | None = None) -> Path:
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    output = sidecar or exe.with_name(f"{exe.name}.sha256")
    output.write_text(f"{digest}  {exe.name}\n", encoding="utf-8")
    return output


def check_qt_binding_isolation() -> None:
    """Fail early if conflicting Qt bindings are importable."""
    conflicts = []
    for pkg in ('PyQt5', 'PySide2', 'PySide6'):
        try:
            __import__(pkg)
            conflicts.append(pkg)
        except ImportError:
            pass
    if conflicts:
        raise RuntimeError(
            f"Conflicting Qt bindings detected: {', '.join(conflicts)}. "
            "PyInstaller will abort if multiple Qt bindings are importable. "
            "Uninstall them or build in an isolated environment.")


def run_smoke(exe: Path, *, timeout: int, skip_gui: bool = False, checksum: Path | None = None) -> Path:
    if not exe.is_file():
        raise FileNotFoundError(f"frozen executable not found: {exe}")
    smoke_version(exe, timeout=timeout)
    smoke_classify(exe, timeout=timeout)
    if not skip_gui:
        smoke_gui(exe, timeout=timeout)
    return write_sha256_sidecar(exe, checksum)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=default_executable(), help="Frozen UniFile executable path")
    parser.add_argument("--timeout", type=int, default=30, help="Seconds per smoke command")
    parser.add_argument("--skip-gui", action="store_true", help="Skip GUI startup smoke")
    parser.add_argument("--checksum", type=Path, default=None, help="Optional SHA-256 sidecar output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        check_qt_binding_isolation()
        sidecar = run_smoke(args.exe, timeout=args.timeout, skip_gui=args.skip_gui, checksum=args.checksum)
    except Exception as exc:
        print(f"build smoke failed: {exc}", file=sys.stderr)
        return 1
    print(f"build smoke passed: {args.exe}")
    print(f"sha256: {sidecar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
