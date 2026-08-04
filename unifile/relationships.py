"""Relationship discovery and durable manual links for file inspectors."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

RELATIONSHIP_SCHEMA_VERSION = "1"
DEFAULT_MAX_RELATED = 12
DEFAULT_DATE_WINDOW_DAYS = 7
_DATE_KEYS = ("date_taken", "creation_date", "date", "timestamp", "modified")
_PHOTOGRAPHER_KEYS = ("photographer", "artist", "author", "creator")


def _path_for(item: Any) -> str:
    if isinstance(item, (str, os.PathLike)):
        return str(item)
    if isinstance(item, dict):
        return str(item.get("full_src") or item.get("path") or item.get("src") or "")
    return str(getattr(item, "full_src", "") or getattr(item, "path", "") or "")


def _metadata_for(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        value = item.get("metadata", {})
        return dict(value) if isinstance(value, dict) else {}
    value = getattr(item, "metadata", {})
    return dict(value) if isinstance(value, dict) else {}


def _name_for(item: Any, path: str) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or Path(path).name)
    return str(getattr(item, "name", "") or Path(path).name)


def _as_values(value: Any) -> set[str]:
    if isinstance(value, str):
        values = re.split(r"[,;|]", value)
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        values = []
    return {
        str(candidate).strip().casefold()
        for candidate in values
        if str(candidate).strip()
    }


def _tags_for(item: Any, metadata: dict[str, Any]) -> set[str]:
    tags = _as_values(metadata.get("tags"))
    if isinstance(item, dict):
        tags |= _as_values(item.get("tags"))
    else:
        tags |= _as_values(getattr(item, "tags", None))
    return tags


def _photographer_for(metadata: dict[str, Any]) -> str:
    for key in _PHOTOGRAPHER_KEYS:
        value = str(metadata.get(key, "") or "").strip().casefold()
        if value:
            return value
    return ""


def _date_for(item: Any, metadata: dict[str, Any]) -> datetime | None:
    for key in _DATE_KEYS:
        value = metadata.get(key)
        if isinstance(value, datetime):
            return value
        text = str(value or "").strip()
        if not text:
            continue
        normalized = text.replace("Z", "+00:00").replace(":", "-", 2)
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            match = re.search(r"(\d{4})[-:/.](\d{1,2})[-:/.](\d{1,2})", text)
            if match:
                return datetime(
                    int(match.group(1)), int(match.group(2)), int(match.group(3))
                )
    path = _path_for(item)
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime)
    except (OSError, ValueError):
        return None


def _name_pattern(name: str) -> str:
    stem = Path(name).stem.casefold()
    stem = re.sub(r"\s*[\[(](?:copy|duplicate|\d+)[\])]$", "", stem)
    return re.sub(r"\d+", "#", stem)


def _candidate_payload(item: Any, path: str) -> dict[str, Any]:
    return {
        "path": path,
        "name": _name_for(item, path),
    }


class ManualLinkStore:
    """Persist symmetric file links without changing source files."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path or os.path.join(_APP_DATA_DIR, "file_relationships.json"))

    @staticmethod
    def _key(path: str | os.PathLike[str]) -> str:
        return os.path.normcase(str(Path(path).expanduser().resolve(strict=False)))

    def _load(self) -> dict[str, list[str]]:
        raw = load_json_safe(str(self.path), {}, expected_type=dict)
        result: dict[str, list[str]] = {}
        for key, values in raw.items():
            if not isinstance(values, list):
                continue
            result[str(key)] = [str(value) for value in values if str(value).strip()]
        return result

    def _save(self, links: dict[str, list[str]]) -> None:
        if not save_json_safe(str(self.path), links):
            raise OSError(f"could not save manual links: {self.path}")

    def links_for(self, path: str | os.PathLike[str]) -> list[str]:
        key = self._key(path)
        links = self._load()
        return sorted(set(links.get(key, [])), key=str.casefold)

    def add_link(self, first: str | os.PathLike[str], second: str | os.PathLike[str]) -> bool:
        first_path = str(Path(first).expanduser().resolve(strict=False))
        second_path = str(Path(second).expanduser().resolve(strict=False))
        first_key = self._key(first_path)
        second_key = self._key(second_path)
        if not first_path or not second_path or first_key == second_key:
            raise ValueError("manual links require two different paths")
        links = self._load()
        for key, value in ((first_key, second_path), (second_key, first_path)):
            links[key] = sorted(set([*links.get(key, []), value]), key=str.casefold)
        self._save(links)
        return True

    def remove_link(self, first: str | os.PathLike[str], second: str | os.PathLike[str]) -> bool:
        first_key = self._key(first)
        second_key = self._key(second)
        links = self._load()
        links[first_key] = [value for value in links.get(first_key, []) if self._key(value) != second_key]
        links[second_key] = [value for value in links.get(second_key, []) if self._key(value) != first_key]
        self._save(links)
        return True


def find_related(
    current: Any,
    candidates: list[Any] | tuple[Any, ...],
    *,
    manual_store: ManualLinkStore | None = None,
    max_results: int = DEFAULT_MAX_RELATED,
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Return ranked related files with explainable match reasons."""
    current_path = _path_for(current)
    current_key = ManualLinkStore._key(current_path) if current_path else ""
    current_metadata = _metadata_for(current)
    current_tags = _tags_for(current, current_metadata)
    current_photographer = _photographer_for(current_metadata)
    current_date = _date_for(current, current_metadata)
    current_pattern = _name_pattern(_name_for(current, current_path))
    manual_store = manual_store or ManualLinkStore()
    manual_paths = manual_store.links_for(current_path) if current_path else []
    manual_keys = {ManualLinkStore._key(path) for path in manual_paths}
    results: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        path = _path_for(candidate)
        if not path:
            continue
        key = ManualLinkStore._key(path)
        if key == current_key:
            continue
        metadata = _metadata_for(candidate)
        reasons: list[str] = []
        score = 0
        if key in manual_keys:
            reasons.append("manual link")
            score += 1000
        shared_tags = sorted(current_tags & _tags_for(candidate, metadata))
        if shared_tags:
            reasons.append("shared tags: " + ", ".join(shared_tags[:4]))
            score += 100 + min(30, len(shared_tags) * 10)
        candidate_photographer = _photographer_for(metadata)
        if current_photographer and current_photographer == candidate_photographer:
            reasons.append("same photographer")
            score += 80
        candidate_date = _date_for(candidate, metadata)
        if current_date and candidate_date:
            if abs(current_date - candidate_date) <= timedelta(days=max(0, date_window_days)):
                reasons.append(f"same date range (±{max(0, date_window_days)} days)")
                score += 35
        if current_pattern and current_pattern == _name_pattern(_name_for(candidate, path)):
            reasons.append("same name pattern")
            score += 25
        if not reasons:
            continue
        payload = _candidate_payload(candidate, path)
        payload.update({"score": score, "reasons": reasons})
        results[key] = payload

    for path in manual_paths:
        key = ManualLinkStore._key(path)
        if key == current_key or key in results:
            continue
        payload = _candidate_payload({}, path)
        payload.update({"score": 1000, "reasons": ["manual link"]})
        results[key] = payload

    bounded = max(1, min(100, int(max_results)))
    return sorted(results.values(), key=lambda item: (-item["score"], item["name"].casefold()))[:bounded]
