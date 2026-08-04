"""Disk-space preflight checks for filesystem apply operations."""

import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass

DEFAULT_MIN_FREE_MB = 500
MIN_FREE_MB_KEY = "disk_protection/min_free_mb"
MAX_MIN_FREE_MB = 1_000_000


@dataclass(frozen=True)
class DiskSpaceIssue:
    """A destination volume that would fall below its configured floor."""

    location: str
    free_bytes: int
    required_bytes: int

    @property
    def free_mb(self) -> int:
        return self.free_bytes // (1024 * 1024)

    @property
    def required_mb(self) -> int:
        return self.required_bytes // (1024 * 1024)

    def describe(self) -> str:
        return (
            f"{self.location}: {self.free_mb:,} MB free, "
            f"{self.required_mb:,} MB required"
        )


def normalize_min_free_mb(value, default: int = DEFAULT_MIN_FREE_MB) -> int:
    """Return a bounded non-negative threshold in megabytes."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(0, min(MAX_MIN_FREE_MB, value))


def min_free_mb_from_settings(settings, default: int = DEFAULT_MIN_FREE_MB) -> int:
    """Read and normalize the persisted threshold from a settings object."""
    try:
        value = settings.value(MIN_FREE_MB_KEY, default, type=int)
    except (AttributeError, TypeError, ValueError):
        value = default
    return normalize_min_free_mb(value, default)


def _work_item(entry):
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return entry[1]
    return entry


def _first_path(item, names: tuple[str, ...]) -> str:
    for name in names:
        value = getattr(item, name, "") or ""
        if value:
            return os.fspath(value)
    return ""


def _nearest_existing_parent(path: str) -> str:
    current = os.path.abspath(path)
    while current and not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    if not current or not os.path.exists(current):
        return ""
    return current if os.path.isdir(current) else os.path.dirname(current)


def _volume_identity(path: str):
    """Return a stable identity for the filesystem containing *path*."""
    try:
        return ("device", os.stat(path).st_dev)
    except (OSError, ValueError):
        drive = os.path.splitdrive(os.path.abspath(path))[0].upper()
        return ("drive", drive or os.path.abspath(path).lower())


def _path_size(path: str) -> int:
    """Return the readable byte size of a file or directory tree."""
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        if not os.path.isdir(path):
            return 0
    except (OSError, PermissionError):
        return 0

    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [name for name in dirnames if not os.path.islink(os.path.join(dirpath, name))]
        for filename in filenames:
            candidate = os.path.join(dirpath, filename)
            try:
                if not os.path.islink(candidate):
                    total += os.path.getsize(candidate)
            except (OSError, PermissionError):
                continue
    return total


def check_work(work: Iterable, *, min_free_mb: int = DEFAULT_MIN_FREE_MB) -> list[DiskSpaceIssue]:
    """Return destination volumes that violate the free-space floor.

    File organizer items expose ``full_src``/``full_dst``; category items use
    ``full_source_path``/``full_dest_path``; AEP rename items use
    ``full_current_path``/``full_new_path``.  Same-volume renames only require
    the configured floor, while cross-volume moves also require the source
    bytes on the destination volume.
    """
    floor_bytes = normalize_min_free_mb(min_free_mb) * 1024 * 1024
    requirements: dict[object, dict[str, int | str]] = {}
    for entry in work:
        item = _work_item(entry)
        source = _first_path(item, ("full_src", "full_source_path", "full_current_path"))
        destination = _first_path(item, ("full_dst", "full_dest_path", "full_new_path"))
        if not destination:
            continue
        destination_root = _nearest_existing_parent(destination)
        if not destination_root:
            continue
        volume = _volume_identity(destination_root)
        requirement = requirements.setdefault(
            volume,
            {"path": destination_root, "needed": 0},
        )
        if not source or _volume_identity(_nearest_existing_parent(source) or source) != volume:
            size = getattr(item, "size", 0) or 0
            if not size:
                size = _path_size(source)
            requirement["needed"] += size

    issues = []
    for requirement in requirements.values():
        path = str(requirement["path"])
        try:
            free = shutil.disk_usage(path).free
        except (OSError, ValueError):
            continue
        required = floor_bytes + int(requirement["needed"])
        if free < required:
            issues.append(DiskSpaceIssue(path, free, required))
    return issues


def check_work_messages(work: Iterable, *, min_free_mb: int = DEFAULT_MIN_FREE_MB) -> list[str]:
    """Return user-facing messages for disk-space violations."""
    return [issue.describe() for issue in check_work(work, min_free_mb=min_free_mb)]


__all__ = [
    "DEFAULT_MIN_FREE_MB",
    "MAX_MIN_FREE_MB",
    "MIN_FREE_MB_KEY",
    "DiskSpaceIssue",
    "check_work",
    "check_work_messages",
    "min_free_mb_from_settings",
    "normalize_min_free_mb",
]
