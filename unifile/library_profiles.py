"""Persisted registry of switchable UniFile libraries."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

_LIBRARIES_FILE = os.path.join(_APP_DATA_DIR, "libraries.json")
_SCHEMA_VERSION = 1


def _normalized_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))


class LibraryProfileStore:
    """Manage named library roots without modifying their contents."""

    def __init__(self, path: str | None = None):
        self.path = path or _LIBRARIES_FILE
        self._data = self._load()

    def _load(self) -> dict:
        raw = load_json_safe(self.path, {}, expected_type=dict)
        if raw.get("version") != _SCHEMA_VERSION or not isinstance(raw.get("libraries"), list):
            return {"version": _SCHEMA_VERSION, "active_id": "", "libraries": []}
        libraries = []
        seen_paths = set()
        for entry in raw["libraries"]:
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path", "")).strip()
            name = str(entry.get("name", "")).strip()
            library_id = str(entry.get("id", "")).strip()
            if not path or not name or not library_id:
                continue
            normalized = _normalized_path(path)
            key = os.path.normcase(normalized)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            libraries.append({
                "id": library_id[:64],
                "name": name[:120],
                "path": normalized,
            })
        active_id = str(raw.get("active_id", ""))
        if active_id not in {item["id"] for item in libraries}:
            active_id = libraries[0]["id"] if libraries else ""
        return {
            "version": _SCHEMA_VERSION,
            "active_id": active_id,
            "libraries": libraries,
        }

    def _save(self) -> bool:
        return save_json_safe(self.path, self._data)

    @property
    def profiles(self) -> list[dict]:
        return [dict(item) for item in self._data["libraries"]]

    @property
    def active_id(self) -> str:
        return str(self._data.get("active_id", ""))

    def active_profile(self) -> dict | None:
        active_id = self.active_id
        return next((item for item in self._data["libraries"] if item["id"] == active_id), None)

    def add(self, path: str, name: str | None = None) -> dict | None:
        """Register an existing folder and make it active."""
        if not path or not os.path.isdir(path):
            return None
        normalized = _normalized_path(path)
        key = os.path.normcase(normalized)
        for item in self._data["libraries"]:
            if os.path.normcase(item["path"]) == key:
                self._data["active_id"] = item["id"]
                self._save()
                return dict(item)
        label = str(name or Path(normalized).name or normalized).strip()[:120]
        item = {
            "id": uuid.uuid4().hex[:16],
            "name": label or "Library",
            "path": normalized,
        }
        self._data["libraries"].append(item)
        self._data["active_id"] = item["id"]
        self._save()
        return dict(item)

    def set_active(self, library_id: str) -> dict | None:
        library_id = str(library_id or "")
        item = next(
            (candidate for candidate in self._data["libraries"] if candidate["id"] == library_id),
            None,
        )
        if item is None:
            return None
        self._data["active_id"] = item["id"]
        self._save()
        return dict(item)

    def rename(self, library_id: str, name: str) -> bool:
        value = str(name or "").strip()[:120]
        if not value:
            return False
        for item in self._data["libraries"]:
            if item["id"] == str(library_id):
                item["name"] = value
                self._save()
                return True
        return False

    def remove(self, library_id: str) -> bool:
        """Forget a library registration; never deletes its folder."""
        library_id = str(library_id or "")
        before = len(self._data["libraries"])
        self._data["libraries"] = [
            item for item in self._data["libraries"] if item["id"] != library_id
        ]
        if len(self._data["libraries"]) == before:
            return False
        if self.active_id == library_id:
            self._data["active_id"] = (
                self._data["libraries"][0]["id"] if self._data["libraries"] else ""
            )
        self._save()
        return True


__all__ = ["LibraryProfileStore"]
