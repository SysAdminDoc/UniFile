"""UniFile — Search query history.

Persists the last N search queries so the user can cycle through them
with Up/Down arrow keys in the search bar, or pick from the autocomplete
dropdown.
"""
from __future__ import annotations

import json
import os
from typing import List

_HISTORY_FILE = os.path.join(os.environ.get("APPDATA", ""), "UniFile", "query_history.json")
_MAX_HISTORY = 20


def load_history() -> List[str]:
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [str(q) for q in data if q][:_MAX_HISTORY]
    except Exception:
        return []


def add_to_history(query: str) -> None:
    query = query.strip()
    if not query:
        return
    history = load_history()
    if query in history:
        history.remove(query)
    history.insert(0, query)
    history = history[:_MAX_HISTORY]
    os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
    try:
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


def clear_history() -> None:
    try:
        os.remove(_HISTORY_FILE)
    except FileNotFoundError:
        pass
