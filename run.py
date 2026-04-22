#!/usr/bin/env python3
"""UniFile v9.0.0 — Launch Script

Run this file to start UniFile:
    python run.py
    python run.py --source "C:/Users/You/Downloads"
    python run.py --profile MyProfile --auto-apply
    python run.py --dry-run --profile MyProfile --auto-apply
    python run.py --portable        (store all data beside this script)
"""
import sys
import os

# Portable mode: must be set BEFORE importing unifile (config.py reads it at import)
if '--portable' in sys.argv:
    os.environ['UNIFILE_PORTABLE'] = '1'

# Ensure the package directory is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unifile.__main__ import main

if __name__ == "__main__":
    main()
