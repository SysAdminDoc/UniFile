#!/usr/bin/env python3
"""UniFile v8.0.0 — Launch Script

Run this file to start UniFile:
    python run.py
    python run.py --source "C:/Users/You/Downloads"
    python run.py --profile MyProfile --auto-apply
    python run.py --dry-run --profile MyProfile --auto-apply
"""
import sys
import os

# Ensure the package directory is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unifile.__main__ import main

if __name__ == "__main__":
    main()
