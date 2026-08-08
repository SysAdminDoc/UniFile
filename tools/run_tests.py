#!/usr/bin/env python
"""Run pytest with an isolated, deterministically cleaned test directory."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _cleanup_tree(path: str | os.PathLike[str], *, attempts: int = 5) -> str | None:
    """Remove a test-owned tree, returning a diagnostic instead of masking tests."""
    last_error = ""
    for attempt in range(max(1, attempts)):
        try:
            shutil.rmtree(path)
            return None
        except FileNotFoundError:
            return None
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < attempts:
                time.sleep(0.05 * (attempt + 1))
    return last_error


def has_explicit_basetemp(args: list[str]) -> bool:
    """Return whether pytest's caller selected ownership of its temp root."""
    return any(arg == "--basetemp" or arg.startswith("--basetemp=") for arg in args)


def main(argv: list[str] | None = None) -> int:
    """Execute pytest and clean only the temporary directory owned here."""
    args = list(sys.argv[1:] if argv is None else argv)
    owned_basetemp: Path | None = None
    if not has_explicit_basetemp(args):
        root = Path(tempfile.gettempdir()) / "unifile-pytest"
        root.mkdir(parents=True, exist_ok=True)
        owned_basetemp = Path(
            tempfile.mkdtemp(prefix=f"run-{os.getpid()}-", dir=str(root))
        )
        args = ["--basetemp", str(owned_basetemp), *args]

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTEST_QT_API"] = "pyqt6"
    result_code = 1
    try:
        result_code = subprocess.run(
            [sys.executable, "-m", "pytest", *args],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            check=False,
        ).returncode
    finally:
        if owned_basetemp is not None:
            cleanup_error = _cleanup_tree(owned_basetemp)
            if cleanup_error:
                print(
                    "UNIFILE TEST CLEANUP WARNING: "
                    "temporary-directory cleanup "
                    "(environment/resource lock): "
                    f"{owned_basetemp}: {cleanup_error}",
                    file=sys.stderr,
                )
                if result_code == 0:
                    result_code = 1
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
