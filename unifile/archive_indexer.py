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

import contextlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from unifile.config import _APP_DATA_DIR, register_sqlite_connection

_DB_PATH = os.path.join(_APP_DATA_DIR, "archive_index.sqlite")
_SUPPORTED_EXTENSIONS = {".zip", ".7z", ".rar", ".tar",
                          ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                          ".tar.xz", ".txz"}
_DEFAULT_MAX_FILES = 10_000
_DEFAULT_MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024


class ArchiveExtractionError(RuntimeError):
    """Raised when an archive cannot be extracted safely."""


def archive_temp_root() -> str:
    """Return the private temporary root used for archive workflows.

    ``LOCALAPPDATA`` is preferred on Windows so the temporary files stay out
    of the user's library and are easy to identify and clean.  The system
    temporary directory is the portable fallback for tests and non-Windows
    environments.
    """
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "UniFile", "temp")


def _safe_member_name(root: str, member_name: str) -> str | None:
    """Validate an archive member and return its safe destination path."""
    name = str(member_name or "").replace("\\", "/")
    if not name or name == ".":
        return None
    if name.startswith("/") or name.startswith("\\"):
        raise ArchiveExtractionError(f"Unsafe absolute archive path: {member_name}")
    if len(name) >= 2 and name[1] == ":":
        raise ArchiveExtractionError(f"Unsafe drive-qualified archive path: {member_name}")
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ArchiveExtractionError(f"Unsafe parent traversal in archive path: {member_name}")
    if not parts:
        return None
    destination_root = Path(root).resolve()
    destination = (destination_root / Path(*parts)).resolve()
    try:
        destination.relative_to(destination_root)
    except ValueError as exc:
        raise ArchiveExtractionError(
            f"Archive path escapes temporary directory: {member_name}"
        ) from exc
    return str(destination)


def _validate_limits(file_count: int, total_size: int, *, max_files: int,
                     max_total_size: int) -> None:
    if file_count > max_files:
        raise ArchiveExtractionError(
            f"Archive contains more than the {max_files:,}-file safety limit"
        )
    if total_size > max_total_size:
        raise ArchiveExtractionError(
            f"Archive expands beyond the {max_total_size:,}-byte safety limit"
        )


def _zip_member_is_link(info) -> bool:
    mode = (getattr(info, "external_attr", 0) >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _extract_zip(path: str, root: str, *, max_files: int,
                 max_total_size: int) -> None:
    import zipfile

    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        file_infos = [info for info in infos if not info.is_dir()]
        total_size = sum(max(0, int(info.file_size)) for info in file_infos)
        _validate_limits(len(file_infos), total_size,
                         max_files=max_files, max_total_size=max_total_size)
        destinations = []
        for info in infos:
            if _zip_member_is_link(info):
                raise ArchiveExtractionError(
                    f"Symbolic links are not allowed in archives: {info.filename}"
                )
            destination = _safe_member_name(root, info.filename)
            destinations.append((info, destination))
        for info, destination in destinations:
            if destination is None:
                continue
            if info.is_dir():
                os.makedirs(destination, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with archive.open(info, "r") as source, open(destination, "wb") as target:
                shutil.copyfileobj(source, target)


def _extract_tar(path: str, root: str, *, max_files: int,
                 max_total_size: int) -> None:
    import tarfile

    with tarfile.open(path, "r:*") as archive:
        members = archive.getmembers()
        file_members = [member for member in members if member.isfile()]
        total_size = sum(max(0, int(member.size)) for member in file_members)
        _validate_limits(len(file_members), total_size,
                         max_files=max_files, max_total_size=max_total_size)
        destinations = []
        for member in members:
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ArchiveExtractionError(
                    f"Links and device entries are not allowed: {member.name}"
                )
            destination = _safe_member_name(root, member.name)
            destinations.append((member, destination))
        for member, destination in destinations:
            if destination is None:
                continue
            if member.isdir():
                os.makedirs(destination, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ArchiveExtractionError(f"Could not read archive member: {member.name}")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with source, open(destination, "wb") as target:
                shutil.copyfileobj(source, target)


def _validate_optional_archive_members(path: str, root: str, *, max_files: int,
                                       max_total_size: int) -> None:
    """Validate 7z/RAR listings before delegating extraction to their reader."""
    lower = path.lower()
    if lower.endswith(".7z"):
        try:
            import py7zr
        except ImportError as exc:
            raise ArchiveExtractionError(
                "7z extraction requires the optional py7zr dependency"
            ) from exc
        with py7zr.SevenZipFile(path, mode="r") as archive:
            infos = archive.list()
            files = [info for info in infos if not getattr(info, "is_directory", False)]
            total_size = sum(max(0, int(getattr(info, "uncompressed", 0) or 0))
                             for info in files)
            _validate_limits(len(files), total_size,
                             max_files=max_files, max_total_size=max_total_size)
            for info in infos:
                _safe_member_name(root, getattr(info, "filename", ""))
        return
    try:
        import rarfile
    except ImportError as exc:
        raise ArchiveExtractionError(
            "RAR extraction requires the optional rarfile dependency"
        ) from exc
    with rarfile.RarFile(path, "r") as archive:
        infos = archive.infolist()
        files = [info for info in infos if not info.is_dir()]
        total_size = sum(max(0, int(getattr(info, "file_size", 0) or 0))
                         for info in files)
        _validate_limits(len(files), total_size,
                         max_files=max_files, max_total_size=max_total_size)
        for info in infos:
            _safe_member_name(root, getattr(info, "filename", ""))


def _extract_optional_archive(path: str, root: str, *, max_files: int,
                              max_total_size: int) -> None:
    lower = path.lower()
    _validate_optional_archive_members(
        path, root, max_files=max_files, max_total_size=max_total_size)
    if lower.endswith(".7z"):
        import py7zr
        with py7zr.SevenZipFile(path, mode="r") as archive:
            archive.extractall(path=root)
    else:
        import rarfile
        with rarfile.RarFile(path, "r") as archive:
            archive.extractall(path=root)


def _extract_archive_to(path: str, root: str, *, max_files: int,
                        max_total_size: int) -> None:
    lower = path.lower()
    if lower.endswith(".zip"):
        _extract_zip(path, root, max_files=max_files, max_total_size=max_total_size)
    elif lower.endswith(".rar") or lower.endswith(".7z"):
        _extract_optional_archive(
            path, root, max_files=max_files, max_total_size=max_total_size)
    elif any(lower.endswith(ext) for ext in
             (".tar", ".tgz", ".tar.gz", ".tbz2", ".tar.bz2", ".txz", ".tar.xz")):
        _extract_tar(path, root, max_files=max_files, max_total_size=max_total_size)
    else:
        raise ArchiveExtractionError(f"Unsupported archive format: {path}")


@contextlib.contextmanager
def extracted_archive(path: str, *, temp_root: str | None = None,
                      max_files: int = _DEFAULT_MAX_FILES,
                      max_total_size: int = _DEFAULT_MAX_TOTAL_SIZE):
    """Extract *path* into a private temporary directory and always clean it.

    Archive member names are validated before any bytes are written.  Symlinks,
    device entries, parent traversal, absolute paths, and oversized archives
    are rejected.  The yielded directory is removed on both success and error.
    """
    archive_path = os.path.abspath(path)
    if not os.path.isfile(archive_path):
        raise ArchiveExtractionError(f"Archive not found: {path}")
    if max_files < 1 or max_total_size < 1:
        raise ValueError("Extraction safety limits must be positive")
    base = os.path.abspath(temp_root or archive_temp_root())
    os.makedirs(base, exist_ok=True)
    root = tempfile.mkdtemp(prefix="archive-", dir=base)
    try:
        _extract_archive_to(
            archive_path, root, max_files=max_files, max_total_size=max_total_size)
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def classify_extracted_archive(path: str, classifier, *,
                               temp_root: str | None = None,
                               max_files: int = _DEFAULT_MAX_FILES,
                               max_total_size: int = _DEFAULT_MAX_TOTAL_SIZE) -> list[dict]:
    """Classify every extracted file with ``classifier(path, inner_path)``.

    The callback is deliberately injected so GUI and headless callers can use
    their existing rule or AI classifier without making archive indexing depend
    on a provider.  Results contain the archive path, breadcrumb path, and the
    callback's classification payload.
    """
    if not callable(classifier):
        raise TypeError("classifier must be callable")
    archive_path = os.path.abspath(path)
    results = []
    with extracted_archive(archive_path, temp_root=temp_root,
                           max_files=max_files, max_total_size=max_total_size) as root:
        for child in sorted(Path(root).rglob("*")):
            if not child.is_file():
                continue
            inner_path = child.relative_to(root).as_posix()
            results.append({
                "archive_path": archive_path,
                "inner_path": inner_path,
                "name": child.name,
                "classification": classifier(str(child), inner_path),
            })
    return results


def repack_archive(extracted_root: str, destination: str, *,
                   format: str | None = None) -> str:
    """Safely repackage an extracted tree using an atomic destination write.

    ZIP and TAR variants are supported by the standard library.  7z is
    supported when py7zr is installed; RAR is intentionally read-only because
    rarfile does not provide a portable writer.  Existing destinations are
    never overwritten.
    """
    root = os.path.abspath(extracted_root)
    if not os.path.isdir(root):
        raise ArchiveExtractionError(f"Extraction directory not found: {extracted_root}")
    destination = os.path.abspath(destination)
    if os.path.exists(destination):
        raise FileExistsError(destination)
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
    lower = (format or destination).lower().lstrip(".")
    if lower in {"rar"}:
        raise ArchiveExtractionError("RAR archives are read-only and cannot be repacked")
    if lower.endswith(".tar.gz") or lower.endswith(".tgz") or lower == "tar.gz":
        tar_mode = "w:gz"
    elif lower.endswith(".tar.bz2") or lower.endswith(".tbz2") or lower == "tar.bz2":
        tar_mode = "w:bz2"
    elif lower.endswith(".tar.xz") or lower.endswith(".txz") or lower == "tar.xz":
        tar_mode = "w:xz"
    elif lower.endswith(".tar") or lower == "tar":
        tar_mode = "w"
    elif lower.endswith(".7z") or lower == "7z":
        tar_mode = None
    else:
        lower = "zip"
        tar_mode = None

    fd, temp_path = tempfile.mkstemp(
        prefix=".unifile-repack-", suffix=".tmp", dir=os.path.dirname(destination) or ".")
    os.close(fd)
    try:
        if lower == "7z" or lower.endswith(".7z"):
            try:
                import py7zr
            except ImportError as exc:
                raise ArchiveExtractionError(
                    "7z repacking requires the optional py7zr dependency"
                ) from exc
            with py7zr.SevenZipFile(temp_path, "w") as archive:
                archive.writeall(root, arcname="")
        elif tar_mode:
            import tarfile
            with tarfile.open(temp_path, tar_mode) as archive:
                archive.add(root, arcname="", recursive=True)
        else:
            import zipfile
            with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for child in sorted(Path(root).rglob("*")):
                    archive.write(child, child.relative_to(root).as_posix())
        os.replace(temp_path, destination)
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass
    return destination


def archive_breadcrumb(entry: ArchiveEntry) -> str:
    """Return the user-facing ``inner (inside archive)`` breadcrumb."""
    archive_name = os.path.basename(entry.archive_path)
    return f"{entry.name} (inside {archive_name})"


def _default_archive_classifier(_file_path: str, inner_path: str) -> dict:
    """Classify an archive member with AI when available, then fall back locally."""
    from unifile.classifier import tiered_classify

    local_result = tiered_classify(Path(inner_path).stem)
    try:
        from unifile.ai_providers import ProviderChain
        from unifile.categories import get_all_category_names
        from unifile.ollama import _build_llm_system_prompt

        prompt = (
            "Classify this extracted archive member into exactly one category.\n"
            f"Archive member path: {inner_path}\n"
            f"Filename: {Path(inner_path).name}\n"
            f"Extension: {Path(inner_path).suffix or '(none)'}\n"
            "Respond only with JSON containing category, confidence, and detail."
        )
        raw, provider = ProviderChain().classify(
            prompt, system=_build_llm_system_prompt())
        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        data = json.loads(match.group(0) if match else raw)
        category = str(data.get("category", "")).strip()
        if category not in get_all_category_names():
            return {
                "category": local_result.get("category"),
                "confidence": local_result.get("confidence", 0),
                "method": local_result.get("method", ""),
                "detail": local_result.get("detail", ""),
            }
        return {
            "category": category,
            "confidence": max(0, min(100, int(data.get("confidence", 0)))),
            "method": f"llm:{provider or 'provider'}",
            "detail": str(data.get("detail", "")),
        }
    except Exception:
        pass
    return {
        "category": local_result.get("category"),
        "confidence": local_result.get("confidence", 0),
        "method": local_result.get("method", ""),
        "detail": local_result.get("detail", ""),
    }


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
    classifications: list[dict] = field(default_factory=list)
    semantic_indexed: int = 0


# ── Database ──────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    os.makedirs(_APP_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
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
_db_lock = __import__('threading').Lock()


def _db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is not None:
        return _db_conn
    with _db_lock:
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


def index_semantic_entries(entries, classifications=None, *, semantic_index=None) -> int:
    """Best-effort index of archive members in the shared semantic index.

    The archive listing remains authoritative and usable without Ollama.  If
    embeddings are unavailable this returns zero without turning a successful
    lexical archive scan into an error.
    """
    entries = list(entries or [])
    if not entries:
        return 0
    owns_index = semantic_index is None
    if semantic_index is None:
        try:
            from unifile.semantic import SemanticIndex
            semantic_index = SemanticIndex()
            if not semantic_index.is_available():
                semantic_index.close()
                return 0
        except Exception:
            return 0
    classification_by_path = {
        item.get("inner_path"): item.get("classification")
        for item in (classifications or [])
        if isinstance(item, dict)
    }
    payloads = []
    for entry in entries:
        inner_path = getattr(entry, "inner_path", "")
        classification = classification_by_path.get(inner_path)
        description = ""
        if isinstance(classification, dict):
            description = " ".join(
                str(value) for key, value in classification.items()
                if key not in {"detail", "raw"} and value not in (None, "")
            )
        payloads.append({
            "archive_path": getattr(entry, "archive_path", ""),
            "inner_path": inner_path,
            "name": getattr(entry, "name", ""),
            "size": getattr(entry, "size", 0),
            "description": description,
        })
    try:
        return semantic_index.index_archive_entries(payloads)
    except Exception:
        return 0
    finally:
        if owns_index:
            semantic_index.close()


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
    from PyQt6.QtCore import QThread
    from PyQt6.QtCore import pyqtSignal as Signal

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
                     force: bool = False, mode: str = "index",
                     classifier=None, parent=None):
            super().__init__(parent)
            self._directory = directory
            self._recursive = recursive
            self._force = force
            self._mode = mode
            self._classifier = classifier

        def run(self) -> None:
            try:
                results = scan_directory(
                    self._directory,
                    recursive=self._recursive,
                    force=self._force,
                    progress_callback=lambda scanned, total, path:
                        self.progress.emit(scanned, total, path),
                )
                if self._mode == "extract":
                    classifier = self._classifier or _default_archive_classifier
                    for result in results:
                        if result.error:
                            continue
                        try:
                            result.classifications = classify_extracted_archive(
                                result.archive_path, classifier)
                        except Exception as exc:
                            result.error = str(exc)
                semantic_index = None
                try:
                    from unifile.semantic import SemanticIndex
                    semantic_index = SemanticIndex()
                    if not semantic_index.is_available():
                        semantic_index.close()
                        semantic_index = None
                except Exception:
                    semantic_index = None
                if semantic_index is not None:
                    try:
                        for result in results:
                            if not result.error:
                                result.semantic_indexed = index_semantic_entries(
                                    result.entries,
                                    result.classifications,
                                    semantic_index=semantic_index,
                                )
                    finally:
                        semantic_index.close()
                self.finished.emit(results)
            except Exception as exc:
                self.error.emit(str(exc))

except ImportError:
    # Headless / no Qt — just skip the worker definition
    pass
