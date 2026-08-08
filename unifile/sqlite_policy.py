"""Shared SQLite connection, locking, and storage policy.

UniFile uses SQLite for the tag library and several bounded local indexes.
Every connection goes through this module so journal, timeout, foreign-key,
thread, synchronous, and shutdown behavior stays explicit.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from unifile.config import register_sqlite_connection

logger = logging.getLogger(__name__)

SQLITE_TIMEOUT_SECONDS = 10.0
SQLITE_BUSY_TIMEOUT_MS = 10_000
SQLITE_JOURNAL_MODE = "WAL"
SQLITE_SYNCHRONOUS = "NORMAL"
SQLITE_WAL_AUTOCHECKPOINT = 1_000


class SQLitePolicyError(RuntimeError):
    """Raised when a database cannot honor UniFile's local SQLite policy."""


def is_network_path(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* is a UNC/network-style Windows path."""
    value = os.fspath(path).replace("/", "\\")
    lowered = value.lower()
    return (
        value.startswith("\\\\")
        and not lowered.startswith("\\\\?\\")
    ) or lowered.startswith("\\\\?\\unc\\")


def ensure_supported_storage(path: str | os.PathLike[str]) -> None:
    """Reject WAL-backed Tag Library databases on network filesystems."""
    if is_network_path(path):
        raise SQLitePolicyError(
            "WAL-backed UniFile SQLite databases require local storage; "
            "copy the library from a network share before opening it"
        )


def _pragma_value(value: Any) -> str:
    text = str(value).strip().upper()
    if text not in {"DELETE", "MEMORY", "OFF", "TRUNCATE", "PERSIST", "WAL", "NORMAL", "FULL", "EXTRA"}:
        raise ValueError(f"unsupported SQLite policy value: {value}")
    return text


def configure_sqlite_connection(
    connection: sqlite3.Connection,
    *,
    read_only: bool = False,
    query_only: bool = False,
    journal_mode: str | None = SQLITE_JOURNAL_MODE,
    synchronous: str = SQLITE_SYNCHRONOUS,
    busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
    wal_autocheckpoint: int = SQLITE_WAL_AUTOCHECKPOINT,
    register: bool = True,
) -> sqlite3.Connection:
    """Apply the complete UniFile connection policy to an open connection."""
    if register:
        register_sqlite_connection(connection)

    if journal_mode is not None and not read_only:
        desired_journal = _pragma_value(journal_mode)
        actual = connection.execute(
            f"PRAGMA journal_mode={desired_journal}"
        ).fetchone()[0]
        if str(actual).upper() != desired_journal:
            raise SQLitePolicyError(
                f"SQLite journal policy requested {desired_journal}, got {actual}"
            )

    connection.execute(f"PRAGMA busy_timeout={max(0, int(busy_timeout_ms))}")
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        connection.execute(f"PRAGMA synchronous={_pragma_value(synchronous)}")
    except sqlite3.OperationalError:
        if not read_only:
            raise
    if journal_mode and not read_only:
        connection.execute(f"PRAGMA wal_autocheckpoint={max(1, int(wal_autocheckpoint))}")
    if query_only:
        connection.execute("PRAGMA query_only=ON")
    return connection


def connect_sqlite(
    database: str | os.PathLike[str],
    *,
    timeout: float = SQLITE_TIMEOUT_SECONDS,
    uri: bool = False,
    check_same_thread: bool = True,
    row_factory: Any = None,
    read_only: bool = False,
    query_only: bool = False,
    journal_mode: str | None = SQLITE_JOURNAL_MODE,
    synchronous: str = SQLITE_SYNCHRONOUS,
    busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
    wal_autocheckpoint: int = SQLITE_WAL_AUTOCHECKPOINT,
) -> sqlite3.Connection:
    """Open and configure one SQLite connection with explicit thread policy."""
    connection = sqlite3.connect(
        os.fspath(database),
        timeout=float(timeout),
        uri=uri,
        check_same_thread=check_same_thread,
    )
    if row_factory is not None:
        connection.row_factory = row_factory
    try:
        return configure_sqlite_connection(
            connection,
            read_only=read_only,
            query_only=query_only,
            journal_mode=None if read_only else journal_mode,
            synchronous=synchronous,
            busy_timeout_ms=busy_timeout_ms,
            wal_autocheckpoint=wal_autocheckpoint,
        )
    except Exception:
        connection.close()
        raise


def checkpoint_wal(
    database: str | os.PathLike[str],
    *,
    mode: str = "PASSIVE",
) -> tuple[int, int, int]:
    """Checkpoint a WAL database and return SQLite's busy/log/checkpoint tuple."""
    normalized = str(mode).strip().upper()
    if normalized not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
        raise ValueError(f"unsupported WAL checkpoint mode: {mode}")
    connection = connect_sqlite(database, check_same_thread=True)
    try:
        row = connection.execute(
            f"PRAGMA wal_checkpoint({normalized})"
        ).fetchone()
        return tuple(int(value) for value in row)
    finally:
        connection.close()


def sqlite_policy_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return the effective policy pragmas for diagnostics and tests."""
    return {
        "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
        "busy_timeout": int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
        "foreign_keys": int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
        "synchronous": int(connection.execute("PRAGMA synchronous").fetchone()[0]),
        "wal_autocheckpoint": int(
            connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
        ),
        "query_only": int(connection.execute("PRAGMA query_only").fetchone()[0]),
    }


__all__ = [
    "SQLITE_BUSY_TIMEOUT_MS",
    "SQLITE_JOURNAL_MODE",
    "SQLITE_SYNCHRONOUS",
    "SQLITE_TIMEOUT_SECONDS",
    "SQLITE_WAL_AUTOCHECKPOINT",
    "SQLitePolicyError",
    "checkpoint_wal",
    "configure_sqlite_connection",
    "connect_sqlite",
    "ensure_supported_storage",
    "is_network_path",
    "sqlite_policy_snapshot",
]
