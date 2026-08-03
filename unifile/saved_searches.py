"""UniFile — Saved Searches (Smart Views).

A saved search stores a named query — text, category filter, and confidence
threshold — so users can replay a specific view of their library in one click.

Persisted as JSON at %APPDATA%\\UniFile\\saved_searches.json.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field

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
    cached_paths: list[str] = field(default_factory=list)
    cached_at: float = 0.0
    cache_changed: bool = False
    nightly_refresh: bool = False
    refresh_hour: int = 2


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
        fd, temp_path = tempfile.mkstemp(
            prefix='.saved-searches-', suffix='.tmp', dir=_APP_DATA_DIR)
        os.close(fd)
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump([asdict(s) for s in searches], f, indent=2)
            os.replace(temp_path, _SEARCHES_FILE)
        finally:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
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
                cached_paths=[str(path) for path in item.get('cached_paths', [])
                              if path],
                cached_at=float(item.get('cached_at', 0)),
                cache_changed=bool(item.get('cache_changed', False)),
                nightly_refresh=bool(item.get('nightly_refresh', False)),
                refresh_hour=max(0, min(23, int(item.get('refresh_hour', 2)))),
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


def get_saved_search(name: str) -> SavedSearch | None:
    """Return one Smart View by name."""
    return next((search for search in load_saved_searches()
                 if search.name == name), None)


def update_cache(name: str, paths: Iterable[str], *, computed_at: float | None = None) -> bool:
    """Replace a Smart View cache and record whether its result set changed."""
    normalized = []
    seen = set()
    for path in paths:
        value = str(path)
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    searches = load_saved_searches()
    for search in searches:
        if search.name != name:
            continue
        search.cache_changed = bool(search.cached_paths) and search.cached_paths != normalized
        search.cached_paths = normalized
        search.cached_at = computed_at if computed_at is not None else time.time()
        search.last_run = search.cached_at
        search.result_count = len(normalized)
        _write(searches)
        return True
    return False


def refresh_search(name: str, resolver: Callable[[SavedSearch], Iterable[str]]) -> bool:
    """Resolve and cache one Smart View using an injected library resolver."""
    search = get_saved_search(name)
    if not search:
        return False
    return update_cache(name, resolver(search))


def set_refresh_schedule(name: str, enabled: bool, hour: int = 2) -> bool:
    """Set the optional nightly refresh schedule for a Smart View."""
    searches = load_saved_searches()
    for search in searches:
        if search.name != name:
            continue
        search.nightly_refresh = bool(enabled)
        search.refresh_hour = max(0, min(23, int(hour)))
        _write(searches)
        return True
    return False


def clear_cache_changed(name: str) -> bool:
    """Acknowledge a changed-result badge after the user has reviewed it."""
    searches = load_saved_searches()
    for search in searches:
        if search.name != name:
            continue
        search.cache_changed = False
        _write(searches)
        return True
    return False


def export_cached_results(name: str, destination: str, *, format: str | None = None) -> bool:
    """Export a cached Smart View result set to JSON or CSV."""
    search = get_saved_search(name)
    if not search:
        return False
    destination = os.path.abspath(destination)
    os.makedirs(os.path.dirname(destination) or '.', exist_ok=True)
    chosen = (format or os.path.splitext(destination)[1].lstrip('.') or 'json').lower()
    if chosen not in {'json', 'csv'}:
        raise ValueError("format must be json or csv")
    if chosen == 'csv':
        with open(destination, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['smart_view', 'query', 'category', 'path', 'cached_at'])
            writer.writerows([
                [search.name, search.query, search.category, path, search.cached_at]
                for path in search.cached_paths
            ])
    else:
        with open(destination, 'w', encoding='utf-8') as f:
            json.dump({
                'name': search.name,
                'query': search.query,
                'category': search.category,
                'cached_at': search.cached_at,
                'result_count': len(search.cached_paths),
                'paths': search.cached_paths,
            }, f, indent=2)
    return True
