#!/usr/bin/env python
"""Windows-friendly dev task runner — mirrors Makefile targets.

Usage:
    python tools/dev_tasks.py test
    python tools/dev_tasks.py lint
    python tools/dev_tasks.py audit
    python tools/dev_tasks.py build
    python tools/dev_tasks.py build-smoke
    python tools/dev_tasks.py clean
"""
import glob
import os
import shutil
import subprocess
import sys

PY = sys.executable

TASKS = {}


def task(name):
    def decorator(fn):
        TASKS[name] = fn
        return fn
    return decorator


def _run(*cmd):
    print(f"  > {' '.join(cmd)}")
    return subprocess.call(cmd)


@task("test")
def _test():
    rc = _run(PY, "tools/check_dependency_manifests.py")
    if rc != 0:
        return rc
    return _run(PY, "tools/run_tests.py")


@task("lint")
def _lint():
    return _run(PY, "-m", "ruff", "check", "unifile", "tests")


@task("audit")
def _audit():
    return _run(PY, "-m", "pip_audit", "--local")


@task("build")
def _build():
    _clean()
    rc = _run(PY, "-m", "pip", "install", "pyinstaller")
    if rc != 0:
        return rc
    rc = _run(PY, "-m", "PyInstaller", "--clean", "--noconfirm", "UniFile.spec")
    if rc != 0:
        return rc
    return _run(PY, "tools/smoke_pyinstaller_build.py")


@task("build-smoke")
def _build_smoke():
    return _run(PY, "tools/smoke_pyinstaller_build.py")


@task("clean")
def _clean():
    for d in ("build", "dist", ".pytest_cache", ".ruff_cache", "htmlcov"):
        shutil.rmtree(d, ignore_errors=True)
    for d in glob.glob("**/__pycache__", recursive=True):
        shutil.rmtree(d, ignore_errors=True)
    for f in glob.glob("**/*.pyc", recursive=True):
        try:
            os.remove(f)
        except OSError:
            pass
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Available tasks:", ", ".join(sorted(TASKS)))
        return 0
    name = sys.argv[1]
    fn = TASKS.get(name)
    if not fn:
        print(f"Unknown task: {name}")
        print("Available:", ", ".join(sorted(TASKS)))
        return 1
    return fn() or 0


if __name__ == "__main__":
    sys.exit(main())
