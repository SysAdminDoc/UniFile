"""Centralized credential storage with OS-keyring and environment support.

Credential values are deliberately never written to UniFile JSON settings,
job files, backups, or diagnostics. Environment variables take precedence over
the OS keyring. Legacy plaintext migration only runs when a keyring backend is
available; otherwise the old value is not read and callers receive a safe
missing-credential result.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KEYRING_SERVICE = "UniFile"

_UNSET = object()
_KEYRING_OVERRIDE: object = _UNSET
_KEYRING_LOCK = threading.RLock()


@dataclass(frozen=True)
class MigrationResult:
    """Non-secret result of a legacy credential migration attempt."""

    status: str
    migrated: tuple[str, ...] = ()

    @property
    def successful(self) -> bool:
        return self.status in {"not-found", "empty-removed", "migrated"}


def set_keyring_backend(backend: Any | None) -> None:
    """Inject a keyring-compatible backend for tests or controlled runtimes."""
    global _KEYRING_OVERRIDE
    _KEYRING_OVERRIDE = backend


def reset_keyring_backend() -> None:
    """Return credential access to the installed keyring package."""
    global _KEYRING_OVERRIDE
    _KEYRING_OVERRIDE = _UNSET


def _keyring_backend() -> Any | None:
    if _KEYRING_OVERRIDE is not _UNSET:
        return _KEYRING_OVERRIDE
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def keyring_available() -> bool:
    """Return whether a keyring module/backend can be selected."""
    return _keyring_backend() is not None


def _valid_name(name: str) -> str:
    value = str(name or "").strip()
    if not value or any(char in value for char in "\x00\r\n"):
        return ""
    return value


def _keyring_get(name: str) -> tuple[bool, str]:
    backend = _keyring_backend()
    if backend is None:
        return False, ""
    try:
        with _KEYRING_LOCK:
            value = backend.get_password(KEYRING_SERVICE, name)
    except Exception:
        return False, ""
    return True, str(value) if value is not None else ""


def _keyring_set(name: str, value: str) -> bool:
    backend = _keyring_backend()
    if backend is None:
        return False
    try:
        with _KEYRING_LOCK:
            backend.set_password(KEYRING_SERVICE, name, value)
    except Exception:
        return False
    return True


def delete_credential(name: str) -> bool:
    """Delete a keyring value, returning False when deletion cannot be proved."""
    normalized = _valid_name(name)
    if not normalized:
        return False
    readable, existing = _keyring_get(normalized)
    if not readable:
        return False
    if not existing:
        return True
    backend = _keyring_backend()
    if backend is None:
        return False
    try:
        with _KEYRING_LOCK:
            backend.delete_password(KEYRING_SERVICE, normalized)
    except Exception:
        return False
    return True


def set_credential(name: str, value: str) -> bool:
    """Store or remove a secret in the configured OS keyring only."""
    normalized = _valid_name(name)
    if not normalized:
        return False
    secret = str(value)
    if not secret:
        return delete_credential(normalized)
    return _keyring_set(normalized, secret)


def get_credential(
    name: str,
    *,
    env_var: str = "",
    legacy_path: str | os.PathLike[str] | None = None,
) -> str:
    """Return an environment or keyring credential, migrating one legacy file."""
    normalized = _valid_name(name)
    if not normalized:
        return ""
    if env_var:
        environment_value = os.environ.get(env_var, "").strip()
        if environment_value:
            return environment_value

    readable, value = _keyring_get(normalized)
    if readable and value:
        return value

    if legacy_path:
        migrate_legacy_text(normalized, legacy_path)
        readable, value = _keyring_get(normalized)
        if readable and value:
            return value
    return ""


def credential_status(
    name: str,
    *,
    env_var: str = "",
    legacy_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return redacted credential state suitable for UI and diagnostics."""
    if env_var and os.environ.get(env_var, "").strip():
        return {
            "configured": True,
            "source": "environment",
            "keyring_available": keyring_available(),
            "migration": "not-needed",
        }

    readable, value = _keyring_get(_valid_name(name))
    if readable and value:
        return {
            "configured": True,
            "source": "keyring",
            "keyring_available": True,
            "migration": "not-needed",
        }

    migration = MigrationResult("not-found")
    if legacy_path:
        migration = migrate_legacy_text(_valid_name(name), legacy_path)
        readable, value = _keyring_get(_valid_name(name))
        if readable and value:
            return {
                "configured": True,
                "source": "keyring",
                "keyring_available": True,
                "migration": migration.status,
            }

    return {
        "configured": False,
        "source": "missing",
        "keyring_available": keyring_available(),
        "migration": migration.status,
    }


def remove_legacy_file(path: str | os.PathLike[str]) -> bool:
    """Remove a legacy credential file after a successful migration."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        return False
    return not Path(path).exists()


def migrate_legacy_text(name: str, path: str | os.PathLike[str]) -> MigrationResult:
    """Move one plaintext credential into the keyring without making a copy."""
    normalized = _valid_name(name)
    if not normalized:
        return MigrationResult("invalid-name")
    legacy = Path(path)
    if not legacy.is_file():
        return MigrationResult("not-found")
    if not keyring_available():
        return MigrationResult("keyring-unavailable")
    try:
        value = legacy.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return MigrationResult("read-failed")
    if not value:
        return MigrationResult(
            "empty-removed" if remove_legacy_file(legacy) else "cleanup-failed"
        )
    if not _keyring_set(normalized, value):
        return MigrationResult("keyring-write-failed")
    if not remove_legacy_file(legacy):
        return MigrationResult("migrated-cleanup-failed", (normalized,))
    return MigrationResult("migrated", (normalized,))


def migrate_legacy_json(
    path: str | os.PathLike[str],
    fields: Mapping[str, str],
) -> MigrationResult:
    """Migrate mapped string fields from one plaintext JSON file.

    The source file is deleted only after every non-empty mapped field has
    reached the keyring. No source backup is created because that would retain
    the plaintext secret.
    """
    legacy = Path(path)
    if not legacy.is_file():
        return MigrationResult("not-found")
    if not keyring_available():
        return MigrationResult("keyring-unavailable")
    try:
        raw = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, json.JSONDecodeError):
        return MigrationResult("read-failed")
    if not isinstance(raw, dict):
        return MigrationResult("invalid-format")

    migrated: list[str] = []
    for field, name in fields.items():
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = _valid_name(name)
        if not normalized or not _keyring_set(normalized, value):
            return MigrationResult("keyring-write-failed", tuple(migrated))
        migrated.append(normalized)

    if not remove_legacy_file(legacy):
        return MigrationResult("migrated-cleanup-failed", tuple(migrated))
    return MigrationResult(
        "migrated" if migrated else "empty-removed",
        tuple(migrated),
    )
