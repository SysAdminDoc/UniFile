"""UniFile — Inbox / Quick Capture.

Designate a folder as the "Inbox". Files placed there appear as a badge in
the dashboard and can be quickly scanned and moved to the library.

Config persisted at %APPDATA%\\UniFile\\inbox.json.
"""

from __future__ import annotations

import json
import os

from unifile.config import _APP_DATA_DIR

_INBOX_FILE = os.path.join(_APP_DATA_DIR, 'inbox.json')


# ── Config I/O ────────────────────────────────────────────────────────────────

def _read() -> dict:
    try:
        with open(_INBOX_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def load_inbox_config() -> dict:
    cfg = _read()
    return {
        'path': str(cfg.get('path', '')),
        'enabled': bool(cfg.get('enabled', False)),
    }


def save_inbox_config(path: str, enabled: bool = True) -> None:
    try:
        os.makedirs(_APP_DATA_DIR, exist_ok=True)
        with open(_INBOX_FILE, 'w') as f:
            json.dump({'path': path, 'enabled': enabled}, f, indent=2)
    except OSError:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_inbox_path() -> str:
    return load_inbox_config()['path']


def is_inbox_enabled() -> bool:
    cfg = load_inbox_config()
    return bool(cfg['enabled'] and cfg['path'])


def get_inbox_count() -> int:
    """Count files directly in the inbox folder (non-recursive, files only)."""
    path = get_inbox_path()
    if not path or not os.path.isdir(path):
        return 0
    try:
        return sum(1 for entry in os.scandir(path) if entry.is_file())
    except OSError:
        return 0
