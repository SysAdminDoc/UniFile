"""Runtime setup for PyInstaller-frozen UniFile builds."""
from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path


def configure_runtime() -> bool:
    """Apply frozen-process safeguards before UniFile imports the GUI stack."""
    multiprocessing.freeze_support()
    if getattr(sys, "frozen", False):
        os.environ.setdefault("UNIFILE_FROZEN", "1")
        exe_dir = Path(sys.executable).resolve().parent
        exe_dir_text = str(exe_dir)
        if exe_dir_text not in sys.path:
            sys.path.insert(0, exe_dir_text)
        if hasattr(multiprocessing, "set_executable"):
            multiprocessing.set_executable(sys.executable)
    return True


configure_runtime()
