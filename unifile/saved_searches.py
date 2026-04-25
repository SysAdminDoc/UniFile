"""UniFile — Saved Searches (Smart Views).

A saved search stores a named query — text, category filter, and confidence
threshold — so users can replay a specific view of their library in one click.

Persisted as JSON at %APPDATA%\\UniFile\\saved_searches.json.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from unifile.config import _APP_DATA_DIR

_SEARCHES_FILE = os.path.join(_APP_DATA_DIR, 'saved_searches.json')


@dataclass
class SavedSearch:
    name: str
    query: str = ""           # txt_search value
    category: str = ""        # category / file-type filter
    conf_min: int = 0         # minimum confidence threshold (0-100)
    created_at: float = field(default_factory=time.time)
    last_run: float = 0.0
    result_count: int = 0


# ── Persistence ───────────────────────────────────────────────────────────────

def _read() -> list[dict]:
    try:
        with open(_SEARCHES_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _write(searches: list[SavedSearch]) -> None:
    try:
        os.makedirs(_APP_DATA_DIR, exist_ok=True)
        with open(_SEARCHES_FILE, 'w') as f:
            json.dump([asdict(s) for s in searches], f, indent=2)
    except OSError:
        pass


def load_saved_searches() -> list[SavedSearch]:
    out = []
    for item in _read():
        if not isinstance(item, dict) or 'name' not in item:
            continue
        try:
            out.append(SavedSearch(
                name=str(item.get('name', '')),
                query=str(item.get('query', '')),
                category=str(item.get('category', '')),
                conf_min=int(item.get('conf_min', 0)),
                created_at=float(item.get('created_at', 0)),
                last_run=float(item.get('last_run', 0)),
                result_count=int(item.get('result_count', 0)),
            ))
        except (TypeError, ValueError):
            pass
    return out


def add_search(s: SavedSearch) -> None:
    """Upsert a saved search (replace by name if it already exists)."""
    searches = [x for x in load_saved_searches() if x.name != s.name]
    searches.insert(0, s)
    _write(searches)


def delete_search(name: str) -> None:
    _write([s for s in load_saved_searches() if s.name != name])


def update_run_stats(name: str, result_count: int) -> None:
    searches = load_saved_searches()
    for s in searches:
        if s.name == name:
            s.last_run = time.time()
            s.result_count = result_count
            break
    _write(searches)
