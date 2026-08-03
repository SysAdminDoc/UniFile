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
    """Count visible files in the configured inbox, including subfolders."""
    return len(iter_inbox_files())


def iter_inbox_files(*, recursive: bool = True) -> list[str]:
    """Return configured inbox files without following directory symlinks."""
    path = get_inbox_path()
    if not is_inbox_enabled() or not os.path.isdir(path):
        return []
    files = []
    if recursive:
        for root, dirs, names in os.walk(path, followlinks=False):
            dirs[:] = [name for name in dirs if not name.startswith('.')]
            files.extend(
                os.path.join(root, name) for name in names
                if not name.startswith('.') and os.path.isfile(os.path.join(root, name))
            )
    else:
        try:
            files = [entry.path for entry in os.scandir(path)
                     if entry.is_file(follow_symlinks=False)]
        except OSError:
            return []
    return sorted(files, key=os.path.normcase)


def sync_inbox_library(library) -> int:
    """Add physical inbox files to a TagLibrary and apply ``tag:inbox``.

    The files remain in their configured folder.  The return value is the
    number of entries whose inbox state or tag changed during this pass.
    """
    if library is None or not getattr(library, 'is_open', False):
        return 0
    paths = iter_inbox_files()
    if not paths:
        return 0
    tag = library.get_tag_by_name('inbox') or library.add_tag(
        'inbox', namespace='system', description='Physical Quick Capture inbox')
    if not tag:
        return 0
    changed = 0
    for path in paths:
        entry = library.add_entry(path)
        if not entry:
            continue
        has_tag = any(existing.id == tag.id for existing in entry.tags)
        if not has_tag:
            library.add_tags_to_entry(entry.id, [tag.id])
            changed += 1
        if entry.is_inbox is not True:
            if library.set_entry_inbox(entry.id, True):
                changed += 1
    return changed
