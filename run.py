#!/usr/bin/env python3
"""UniFile v9.3.31 — Launch Script

Run this file to start UniFile:
    python run.py
    python run.py --install-deps
    python run.py --source "C:/Users/You/Downloads"
    python run.py --profile MyProfile --auto-apply
    python run.py --dry-run --profile MyProfile --auto-apply
    python run.py --portable        (store all data beside this script)
"""
import multiprocessing
import os
import sys


def _prepare_runtime() -> None:
    # Portable mode must be set before importing unifile; config.py reads it at import.
    if "--portable" in sys.argv:
        os.environ["UNIFILE_PORTABLE"] = "1"
    if "--install-deps" in sys.argv:
        os.environ["UNIFILE_INSTALL_DEPS"] = "1"

    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    _prepare_runtime()
    multiprocessing.freeze_support()
    from unifile.__main__ import main as unifile_main

    unifile_main()

if __name__ == "__main__":
    main()
