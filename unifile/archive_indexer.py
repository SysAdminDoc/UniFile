"""UniFile — Archive Content Indexer.

Indexes the *contents* of archive files (.zip, .7z, .rar, .tar.*) so that
files-inside-archives appear in search results and classification.

Key features:
  - Reads archive file listings without extracting to disk
  - Caches results in a local SQLite database keyed by (path, mtime, size)
  - Exposes a simple `scan_file`, `scan_directory`, and `search` API
  - Background `QThread` worker for GUI use

Dependencies (all optional — falls back gracefully if absent):
  - py7zr  (7z archives)
  - rarfile  (RAR archives)
  - stdlib zipfile, tarfile  (always available)

The index database lives at:
  %APPDATA%\\UniFile\\archive_index.sqlite
"""
from __future__ import annotations

import os
import sqlite3
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from unifile.config import _APP_DATA_DIR, register_sqlite_connection

_DB_PATH = os.path.join(_APP_DATA_DIR, "archive_index.sqlite")
_SUPPORTED_EXTENSIONS = {".zip", ".7z", ".rar", ".tar",
                          ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                          ".tar.xz", ".txz"}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ArchiveEntry:
    """One file inside an archive."""
    archive_path: str       # absolute path to the container archive
    inner_path: str         # path inside the archive (forward-slash separated)
    name: str               # filename without directory
    size: int               # uncompressed size in bytes (0 if unknown)
    is_dir: bool = False


@dataclass
class ArchiveScanResult:
    """Result of scanning one archive file."""
    archive_path: str
    entries: list[ArchiveEntry] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0


# ── Database ──────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    os.makedirs(_APP_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    register_sqlite_connection(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS archive_meta (
            path        TEXT NOT NULL,
            mtime       REAL NOT NULL,
            size        INTEGER NOT NULL,
            scanned_at  REAL NOT NULL,
            error       TEXT,
            PRIMARY KEY (path)
        );
        CREATE TABLE IF NOT EXISTS archive_entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_id  TEXT NOT NULL,
            inner_path  TEXT NOT NULL,
            name        TEXT NOT NULL,
            size        INTEGER NOT NULL DEFAULT 0,
            is_dir      INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (archive_id) REFERENCES archive_meta(path)
        );
        CREATE INDEX IF NOT EXISTS idx_entries_archive
            ON archive_entries(archive_id);
        CREATE INDEX IF NOT EXISTS idx_entries_name
            ON archive_entries(name COLLATE NOCASE);
    """)
    conn.commit()
    return conn


_db_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = _get_db()
    return _db_conn


# ── Archive readers ───────────────────────────────────────────────────────────

def _read_zip(path: str) -> list[ArchiveEntry]:
    import zipfile
    entries = []
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            entries.append(ArchiveEntry(
                archive_path=path,
                inner_path=info.filename,
                name=os.path.basename(info.filename.rstrip("/")),
                size=info.file_size,
                is_dir=info.filename.endswith("/"),
            ))
    return entries


def _read_7z(path: str) -> list[ArchiveEntry]:
    try:
        import py7zr
    except ImportError:
        return []
    entries = []
    with py7zr.SevenZipFile(path, mode="r") as zf:
        for info in zf.list():
            entries.append(ArchiveEntry(
                archive_path=path,
                inner_path=info.filename,
                name=os.path.basename(info.filename),
                size=info.uncompressed or 0,
                is_dir=info.is_directory,
            ))
    return entries


def _read_rar(path: str) -> list[ArchiveEntry]:
    try:
        import rarfile
    except ImportError:
        return []
    entries = []
    try:
        with rarfile.RarFile(path, "r") as rf:
            for info in rf.infolist():
                entries.append(ArchiveEntry(
                    archive_path=path,
                    inner_path=info.filename,
                    name=os.path.basename(info.filename),
                    size=info.file_size,
                    is_dir=info.is_dir(),
                ))
    except Exception:
        pass
    return entries


def _read_tar(path: str) -> list[ArchiveEntry]:
    import tarfile
    entries = []
    try:
        with tarfile.open(path, "r:*") as tf:
            for member in tf.getmembers():
                entries.append(ArchiveEntry(
                    archive_path=path,
                    inner_path=member.name,
                    name=os.path.basename(member.name),
                    size=member.size,
                    is_dir=member.isdir(),
                ))
    except Exception:
        pass
    return entries


def _read_archive(path: str) -> list[ArchiveEntry]:
    """Dispatch to the appropriate reader based on file extension."""
    lower = path.lower()
    if lower.endswith(".zip"):
        return _read_zip(path)
    if lower.endswith(".7z"):
        return _read_7z(path)
    if lower.endswith(".rar"):
        return _read_rar(path)
    if any(lower.endswith(ext) for ext in
           (".tar", ".tgz", ".tar.gz", ".tbz2", ".tar.bz2", ".txz", ".tar.xz")):
        return _read_tar(path)
    return []


def _is_archive(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in _SUPPORTED_EXTENSIONS)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _is_cached(conn: sqlite3.Connection, path: str) -> bool:
    """Return True if the archive is already indexed and still fresh."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    row = conn.execute(
        "SELECT mtime, size FROM archive_meta WHERE path = ?", (path,)
    ).fetchone()
    if not row:
        return False
    return row[0] == st.st_mtime and row[1] == st.st_size


def _cache_result(conn: sqlite3.Connection, result: ArchiveScanResult) -> None:
    path = result.archive_path
    try:
        st = os.stat(path)
        mtime, size = st.st_mtime, st.st_size
    except OSError:
        mtime, size = 0.0, 0

    conn.execute("DELETE FROM archive_entries WHERE archive_id = ?", (path,))
    conn.execute(
        "INSERT OR REPLACE INTO archive_meta (path, mtime, size, scanned_at, error) "
        "VALUES (?, ?, ?, ?, ?)",
        (path, mtime, size, time.time(), result.error or None),
    )
    conn.executemany(
        "INSERT INTO archive_entries (archive_id, inner_path, name, size, is_dir) "
        "VALUES (?, ?, ?, ?, ?)",
        [(path, e.inner_path, e.name, e.size, int(e.is_dir))
         for e in result.entries],
    )
    conn.commit()


# ── Public API ────────────────────────────────────────────────────────────────

def scan_file(path: str, *, force: bool = False) -> ArchiveScanResult:
    """Index a single archive file.

    Args:
        path:  Absolute path to the archive.
        force: Re-index even if a fresh cache entry exists.

    Returns an :class:`ArchiveScanResult`.
    """
    path = os.path.abspath(path)
    conn = _db()

    if not force and _is_cached(conn, path):
        # Return cached entries
        rows = conn.execute(
            "SELECT inner_path, name, size, is_dir FROM archive_entries "
            "WHERE archive_id = ?", (path,)
        ).fetchall()
        entries = [ArchiveEntry(path, r[0], r[1], r[2], bool(r[3])) for r in rows]
        return ArchiveScanResult(archive_path=path, entries=entries)

    t0 = time.monotonic()
    error = ""
    entries: list[ArchiveEntry] = []
    try:
        entries = _read_archive(path)
    except Exception as exc:
        error = str(exc)

    result = ArchiveScanResult(
        archive_path=path,
        entries=entries,
        error=error,
        elapsed=time.monotonic() - t0,
    )
    _cache_result(conn, result)
    return result


def scan_directory(
    directory: str,
    *,
    recursive: bool = True,
    force: bool = False,
    progress_callback=None,
) -> list[ArchiveScanResult]:
    """Scan all archives in a directory.

    Args:
        directory:         Root directory to scan.
        recursive:         Whether to descend into subdirectories.
        force:             Re-index even if cached entries exist.
        progress_callback: Optional callable(scanned: int, total: int, path: str)
                           called after each archive is indexed.

    Returns a list of :class:`ArchiveScanResult`, one per archive found.
    """
    archives = []
    if recursive:
        for root, _dirs, files in os.walk(directory):
            for fname in files:
                full = os.path.join(root, fname)
                if _is_archive(full):
                    archives.append(full)
    else:
        for entry in os.scandir(directory):
            if entry.is_file() and _is_archive(entry.path):
                archives.append(entry.path)

    results: list[ArchiveScanResult] = []
    total = len(archives)
    for i, archive in enumerate(archives):
        result = scan_file(archive, force=force)
        results.append(result)
        if progress_callback:
            try:
                progress_callback(i + 1, total, archive)
            except Exception:
                pass

    return results


def search(
    query: str,
    *,
    directory: str | None = None,
    limit: int = 200,
) -> list[ArchiveEntry]:
    """Search the index for files whose name contains *query*.

    Args:
        query:     Case-insensitive substring to match against entry names.
        directory: If set, restrict results to archives inside this directory.
        limit:     Maximum number of results to return.

    Returns a list of :class:`ArchiveEntry`.
    """
    conn = _db()
    if directory:
        directory = os.path.abspath(directory)
        rows = conn.execute(
            "SELECT archive_id, inner_path, name, size, is_dir "
            "FROM archive_entries "
            "WHERE name LIKE ? AND archive_id LIKE ? "
            "AND is_dir = 0 LIMIT ?",
            (f"%{query}%", f"{directory}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT archive_id, inner_path, name, size, is_dir "
            "FROM archive_entries "
            "WHERE name LIKE ? AND is_dir = 0 LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
    return [ArchiveEntry(r[0], r[1], r[2], r[3], bool(r[4])) for r in rows]


def get_archive_entries(archive_path: str) -> list[ArchiveEntry]:
    """Return all indexed entries for a specific archive (from cache if available)."""
    return scan_file(archive_path).entries


def index_stats() -> dict:
    """Return statistics about the current index."""
    conn = _db()
    n_archives = conn.execute("SELECT COUNT(*) FROM archive_meta").fetchone()[0]
    n_entries  = conn.execute("SELECT COUNT(*) FROM archive_entries WHERE is_dir=0").fetchone()[0]
    errors     = conn.execute(
        "SELECT COUNT(*) FROM archive_meta WHERE error IS NOT NULL"
    ).fetchone()[0]
    return {
        "indexed_archives": n_archives,
        "indexed_files": n_entries,
        "errors": errors,
    }


def clear_index() -> None:
    """Wipe the entire archive index."""
    conn = _db()
    conn.execute("DELETE FROM archive_entries")
    conn.execute("DELETE FROM archive_meta")
    conn.commit()


# ── QThread worker for GUI use ────────────────────────────────────────────────

try:
    from PyQt6.QtCore import QThread, pyqtSignal as Signal

    class ArchiveIndexWorker(QThread):
        """Background worker that indexes archives in a directory.

        Signals:
            progress(int, int, str)   -- (scanned, total, current_archive_path)
            finished(list)            -- list of ArchiveScanResult
            error(str)                -- error message if the scan fails entirely
        """
        progress = Signal(int, int, str)
        finished = Signal(list)
        error    = Signal(str)

        def __init__(self, directory: str, *, recursive: bool = True,
                     force: bool = False, parent=None):
            super().__init__(parent)
            self._directory = directory
            self._recursive = recursive
            self._force = force

        def run(self) -> None:
            try:
                results = scan_directory(
                    self._directory,
                    recursive=self._recursive,
                    force=self._force,
                    progress_callback=lambda scanned, total, path:
                        self.progress.emit(scanned, total, path),
                )
                self.finished.emit(results)
            except Exception as exc:
                self.error.emit(str(exc))

except ImportError:
    # Headless / no Qt — just skip the worker definition
    pass
