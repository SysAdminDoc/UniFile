"""UniFile — Per-file star ratings and review flags.

Ratings are stored in a local SQLite database at
``%APPDATA%\\UniFile\\ratings.sqlite``.

Schema::

    ratings(
        path      TEXT PRIMARY KEY,   -- normalised absolute path (lower-case)
        stars     INTEGER,            -- 0-5
        flag      TEXT,               -- 'pending' | 'approved' | 'rejected' | ''
        updated_at TEXT               -- ISO-8601 timestamp
    )

Public API
----------
get_rating(path)             -> (stars: int, flag: str)
set_rating(path, stars, flag)
clear_rating(path)
bulk_load(paths)             -> dict[str, tuple[int, str]]
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from unifile.config import _APP_DATA_DIR

_DB_PATH = os.path.join(_APP_DATA_DIR, "ratings.sqlite")
_VALID_FLAGS = {"pending", "approved", "rejected", ""}


def _conn() -> sqlite3.Connection:
    os.makedirs(_APP_DATA_DIR, exist_ok=True)
    con = sqlite3.connect(_DB_PATH, check_same_thread=False)
    con.execute(
        "CREATE TABLE IF NOT EXISTS ratings ("
        "path TEXT PRIMARY KEY, "
        "stars INTEGER NOT NULL DEFAULT 0, "
        "flag TEXT NOT NULL DEFAULT '', "
        "updated_at TEXT NOT NULL"
        ")"
    )
    con.commit()
    return con


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def get_rating(path: str) -> Tuple[int, str]:
    """Return (stars, flag) for *path*, or (0, '') if not rated."""
    try:
        con = _conn()
        row = con.execute(
            "SELECT stars, flag FROM ratings WHERE path = ?", (_norm(path),)
        ).fetchone()
        con.close()
        if row:
            return int(row[0] or 0), str(row[1] or "")
        return 0, ""
    except Exception:
        return 0, ""


def set_rating(path: str, stars: int, flag: str = "") -> None:
    """Persist a rating for *path*.  *stars* must be 0-5, *flag* one of the
    valid values (invalid values are coerced to '')."""
    stars = max(0, min(5, int(stars)))
    flag = flag.lower() if flag and flag.lower() in _VALID_FLAGS else ""
    now = datetime.now(timezone.utc).isoformat()
    try:
        con = _conn()
        con.execute(
            "INSERT INTO ratings (path, stars, flag, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET stars=excluded.stars, flag=excluded.flag, "
            "updated_at=excluded.updated_at",
            (_norm(path), stars, flag, now),
        )
        con.commit()
        con.close()
    except Exception:
        pass


def clear_rating(path: str) -> None:
    """Remove any rating record for *path*."""
    try:
        con = _conn()
        con.execute("DELETE FROM ratings WHERE path = ?", (_norm(path),))
        con.commit()
        con.close()
    except Exception:
        pass


def bulk_load(paths: List[str]) -> Dict[str, Tuple[int, str]]:
    """Fetch ratings for a list of paths in one query.

    Returns a dict mapping each normalised path to ``(stars, flag)``.
    Paths with no rating are omitted from the result.
    """
    if not paths:
        return {}
    normed = [_norm(p) for p in paths]
    result: Dict[str, Tuple[int, str]] = {}
    try:
        con = _conn()
        placeholders = ",".join("?" * len(normed))
        rows = con.execute(
            f"SELECT path, stars, flag FROM ratings WHERE path IN ({placeholders})",
            normed,
        ).fetchall()
        con.close()
        for row in rows:
            result[row[0]] = (int(row[1] or 0), str(row[2] or ""))
    except Exception:
        pass
    return result
