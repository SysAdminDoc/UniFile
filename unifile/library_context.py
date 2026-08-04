"""Process-local active library context shared by UI, rules, and AI settings."""

from __future__ import annotations

import os

_ACTIVE_LIBRARY_ROOT: str | None = None


def set_active_library_root(root: str | None) -> str | None:
    """Set the library whose scoped preferences should be active."""
    global _ACTIVE_LIBRARY_ROOT
    if root is None or not str(root).strip():
        _ACTIVE_LIBRARY_ROOT = None
        return None
    _ACTIVE_LIBRARY_ROOT = os.path.realpath(
        os.path.abspath(os.path.expanduser(str(root)))
    )
    return _ACTIVE_LIBRARY_ROOT


def get_active_library_root() -> str | None:
    """Return the normalized active library root, if one is selected."""
    return _ACTIVE_LIBRARY_ROOT


def active_library_settings_path(filename: str) -> str | None:
    """Return a scoped preference path, or ``None`` for global fallback."""
    root = get_active_library_root()
    if not root:
        return None
    name = os.path.basename(str(filename).strip())
    if not name or name in {".", ".."}:
        return None
    return os.path.join(root, ".unifile", name)


__all__ = [
    "active_library_settings_path",
    "get_active_library_root",
    "set_active_library_root",
]
