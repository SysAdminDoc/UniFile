"""SQLite policy, concurrency, cancellation, and migration coverage."""

import sqlite3
import threading
import time

import pytest

from unifile.sqlite_policy import (
    SQLITE_BUSY_TIMEOUT_MS,
    connect_sqlite,
    sqlite_policy_snapshot,
)
from unifile.tagging import db as tag_db


def test_direct_connection_policy_is_explicit(tmp_path):
    path = tmp_path / "policy.sqlite"
    connection = connect_sqlite(path, check_same_thread=True)
    try:
        snapshot = sqlite_policy_snapshot(connection)
        assert snapshot == {
            "journal_mode": "wal",
            "busy_timeout": SQLITE_BUSY_TIMEOUT_MS,
            "foreign_keys": 1,
            "synchronous": 1,
            "wal_autocheckpoint": 1000,
            "query_only": 0,
        }
    finally:
        connection.close()


def test_tag_engine_applies_policy_to_each_connection(tmp_path):
    engine = tag_db.make_engine(str(tmp_path / "tags.sqlite"))
    try:
        with engine.connect() as connection:
            raw = connection.connection.driver_connection
            snapshot = sqlite_policy_snapshot(raw)
            assert snapshot["journal_mode"] == "wal"
            assert snapshot["busy_timeout"] == SQLITE_BUSY_TIMEOUT_MS
            assert snapshot["foreign_keys"] == 1
            assert snapshot["synchronous"] == 1
    finally:
        engine.dispose()


def test_wal_reader_and_writer_progress_under_lock_contention(tmp_path):
    path = tmp_path / "contention.sqlite"
    writer = connect_sqlite(path, check_same_thread=True)
    reader = connect_sqlite(path, check_same_thread=True)
    blocked = connect_sqlite(path, check_same_thread=False)
    try:
        writer.execute("CREATE TABLE values_table (value INTEGER)")
        writer.commit()
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO values_table VALUES (1)")

        assert reader.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 0

        finished = threading.Event()
        errors: list[Exception] = []

        def blocked_write():
            try:
                blocked.execute("INSERT INTO values_table VALUES (2)")
                blocked.commit()
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=blocked_write)
        thread.start()
        assert not finished.wait(0.05)
        writer.commit()
        assert finished.wait(2)
        thread.join(timeout=2)
        assert not errors
        assert reader.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 2
    finally:
        writer.close()
        reader.close()
        blocked.close()


def test_shared_connection_can_be_cancelled_without_corrupting_database(tmp_path):
    path = tmp_path / "cancel.sqlite"
    connection = connect_sqlite(path, check_same_thread=False)
    try:
        connection.execute("CREATE TABLE numbers (value INTEGER)")
        connection.executemany("INSERT INTO numbers VALUES (?)", [(index,) for index in range(500)])
        connection.commit()
        started = threading.Event()
        outcome: list[object] = []

        def long_search():
            try:
                started.set()
                connection.execute(
                    "SELECT count(*) FROM numbers a, numbers b, numbers c, numbers d"
                ).fetchone()
                outcome.append("completed")
            except sqlite3.OperationalError as exc:
                outcome.append(exc)

        thread = threading.Thread(target=long_search)
        thread.start()
        assert started.wait(1)
        time.sleep(0.01)
        connection.interrupt()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert isinstance(outcome[0], sqlite3.OperationalError)
        assert "interrupt" in str(outcome[0]).lower()
        assert connection.execute("SELECT COUNT(*) FROM numbers").fetchone()[0] == 500
    finally:
        connection.close()


def test_network_storage_is_rejected_for_tag_engine(tmp_path):
    if not hasattr(tmp_path, "as_posix"):
        pytest.skip("path fixture unavailable")
    with pytest.raises(Exception, match="local storage"):
        tag_db.make_engine(r"\\server\share\unifile_tags.sqlite")
