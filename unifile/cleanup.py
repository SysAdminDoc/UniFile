"""UniFile — Cleanup Tools: scanners for empty folders, empty files,
temp files, broken/corrupt files, and big file finder.

Inspired by Czkawka, DropIt, File Juggler, and Duplicate Cleaner Pro."""

import os
import re
import struct
import zipfile
import tarfile
import time
from dataclasses import dataclass, field
from typing import List, Optional, Callable

from unifile.config import is_protected

# ── Data classes for scan results ────────────────────────────────────────────

@dataclass
class CleanupItem:
    """Universal result item from any cleanup scanner."""
    path: str
    size: int = 0
    reason: str = ""          # human-readable explanation
    category: str = ""        # scanner category (empty_folder, temp_file, etc.)
    modified: float = 0.0     # mtime
    selected: bool = True     # pre-selected for action


# ── Empty Folder Scanner ─────────────────────────────────────────────────────

def scan_empty_folders(root: str, *, ignore_hidden: bool = True,
                       ignore_system: bool = True,
                       progress_cb: Callable = None,
                       item_cb: Callable = None) -> List[CleanupItem]:
    """Find all empty directories (recursively) under root.
    A folder is 'empty' if it contains no files — only other empty folders.
    Returns deepest-first order so deletion is safe top-down."""

    _SYSTEM_DIRS = frozenset({
        '.git', '.svn', '.hg', '__pycache__', 'node_modules',
        '.Spotlight-V100', '.Trashes', '.fseventsd', 'System Volume Information',
        '$RECYCLE.BIN', 'Recovery',
    })

    results = []
    empty_paths = set()  # set of normalized paths known to be empty (O(1) membership)
    # Walk bottom-up so we can detect recursively-empty trees
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue  # never flag the root itself

        basename = os.path.basename(dirpath)

        if ignore_hidden and basename.startswith('.'):
            continue
        if ignore_system and basename in _SYSTEM_DIRS:
            continue

        # Check if directory is empty (no files, and all subdirs were already removed/flagged)
        has_files = False
        has_non_empty_subdirs = False
        try:
            for entry in os.scandir(dirpath):
                if entry.is_file(follow_symlinks=False) or entry.is_symlink():
                    has_files = True
                    break
                elif entry.is_dir(follow_symlinks=False):
                    sub_norm = os.path.normcase(os.path.normpath(entry.path))
                    if sub_norm not in empty_paths:
                        has_non_empty_subdirs = True
                        break
        except (PermissionError, OSError):
            continue

        if not has_files and not has_non_empty_subdirs:
            try:
                st = os.stat(dirpath)
                mtime = st.st_mtime
            except OSError:
                mtime = 0
            item = CleanupItem(
                path=dirpath, size=0, reason="Empty directory",
                category="empty_folder", modified=mtime
            )
            results.append(item)
            empty_paths.add(os.path.normcase(os.path.normpath(dirpath)))
            if progress_cb:
                progress_cb(f"Empty: {dirpath}")
            if item_cb:
                item_cb(item)

    return results


# ── Empty / Zero-Byte File Scanner ───────────────────────────────────────────

def scan_empty_files(root: str, *, depth: int = 99,
                     progress_cb: Callable = None,
                     item_cb: Callable = None) -> List[CleanupItem]:
    """Find all zero-byte files under root."""
    results = []
    root_depth = root.rstrip(os.sep).count(os.sep)

    for dirpath, dirnames, filenames in os.walk(root):
        current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        if current_depth > depth:
            dirnames.clear()
            continue

        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                st = os.stat(fpath)
                if st.st_size == 0:
                    item = CleanupItem(
                        path=fpath, size=0, reason="Zero-byte file",
                        category="empty_file", modified=st.st_mtime
                    )
                    results.append(item)
                    if progress_cb:
                        progress_cb(f"Empty file: {fpath}")
                    if item_cb:
                        item_cb(item)
            except (OSError, PermissionError):
                continue

    return results


# ── Temporary File Scanner ───────────────────────────────────────────────────

# Patterns that identify temporary/junk files
_TEMP_PATTERNS = [
    # Editor swap/backup files
    (re.compile(r'^~\$'), "Office lock file"),
    (re.compile(r'^~lock\.'), "LibreOffice lock file"),
    (re.compile(r'^\.~lock\.'), "LibreOffice lock file"),
    (re.compile(r'\.swp$', re.I), "Vim swap file"),
    (re.compile(r'\.swo$', re.I), "Vim swap file"),
    (re.compile(r'\.swn$', re.I), "Vim swap file"),
    # Temp/backup extensions
    (re.compile(r'\.tmp$', re.I), "Temporary file"),
    (re.compile(r'\.temp$', re.I), "Temporary file"),
    (re.compile(r'\.bak$', re.I), "Backup file"),
    (re.compile(r'\.old$', re.I), "Old backup file"),
    (re.compile(r'\.orig$', re.I), "Original backup file"),
    (re.compile(r'\.cache$', re.I), "Cache file"),
    # Download fragments
    (re.compile(r'\.crdownload$', re.I), "Chrome incomplete download"),
    (re.compile(r'\.part$', re.I), "Partial download"),
    (re.compile(r'\.partial$', re.I), "Partial download"),
    (re.compile(r'\.download$', re.I), "Incomplete download"),
    (re.compile(r'\.opdownload$', re.I), "Opera incomplete download"),
    # OS junk
    (re.compile(r'^Thumbs\.db$', re.I), "Windows thumbnail cache"),
    (re.compile(r'^desktop\.ini$', re.I), "Windows folder config"),
    (re.compile(r'^\.DS_Store$'), "macOS folder metadata"),
    (re.compile(r'^\.localized$'), "macOS localization file"),
    (re.compile(r'^\._'), "macOS resource fork"),
    (re.compile(r'^__MACOSX$'), "macOS archive artifact"),
    # Log/dump files
    (re.compile(r'\.log$', re.I), "Log file"),
    (re.compile(r'\.dmp$', re.I), "Crash dump file"),
    (re.compile(r'^hs_err_pid\d+\.log$'), "Java crash log"),
    # Thumbnail databases
    (re.compile(r'^\.thumbnails$'), "Thumbnail cache directory"),
    (re.compile(r'^ehthumbs\.db$', re.I), "Windows thumbnail cache"),
    (re.compile(r'^ehthumbs_vista\.db$', re.I), "Windows thumbnail cache"),
    # Zone identifiers
    (re.compile(r':Zone\.Identifier$'), "Windows zone identifier"),
    (re.compile(r'\.Zone\.Identifier$'), "Windows zone identifier"),
]


def scan_temp_files(root: str, *, depth: int = 99, include_logs: bool = False,
                    min_age_days: int = 0,
                    progress_cb: Callable = None,
                    item_cb: Callable = None) -> List[CleanupItem]:
    """Find temporary, junk, and incomplete download files under root."""
    results = []
    root_depth = root.rstrip(os.sep).count(os.sep)
    now = time.time()
    min_age_secs = min_age_days * 86400

    # Build active pattern list
    patterns = [(p, reason) for p, reason in _TEMP_PATTERNS
                if include_logs or "Log file" not in reason]

    for dirpath, dirnames, filenames in os.walk(root):
        current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        if current_depth > depth:
            dirnames.clear()
            continue

        for fname in filenames:
            for pattern, reason in patterns:
                if pattern.search(fname):
                    fpath = os.path.join(dirpath, fname)
                    try:
                        st = os.stat(fpath)
                        if min_age_secs and (now - st.st_mtime) < min_age_secs:
                            continue  # too recent
                        item = CleanupItem(
                            path=fpath, size=st.st_size, reason=reason,
                            category="temp_file", modified=st.st_mtime
                        )
                        results.append(item)
                        if progress_cb:
                            progress_cb(f"Temp: {fpath}")
                        if item_cb:
                            item_cb(item)
                    except (OSError, PermissionError):
                        pass
                    break  # first match wins

    return results


# ── Broken / Corrupt File Scanner ────────────────────────────────────────────

# Magic bytes for common file formats (first N bytes → expected format)
_MAGIC_HEADERS = {
    # Images
    '.jpg':  [b'\xff\xd8\xff'],
    '.jpeg': [b'\xff\xd8\xff'],
    '.png':  [b'\x89PNG\r\n\x1a\n'],
    '.gif':  [b'GIF87a', b'GIF89a'],
    '.bmp':  [b'BM'],
    '.webp': [b'RIFF'],  # RIFF....WEBP
    '.tiff': [b'II\x2a\x00', b'MM\x00\x2a'],
    '.tif':  [b'II\x2a\x00', b'MM\x00\x2a'],
    '.ico':  [b'\x00\x00\x01\x00'],
    '.svg':  [b'<?xml', b'<svg'],
    # Audio
    '.mp3':  [b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'],
    '.wav':  [b'RIFF'],
    '.flac': [b'fLaC'],
    '.ogg':  [b'OggS'],
    '.m4a':  [b'\x00\x00\x00'],  # ftyp box (variable offset)
    # Video
    '.mp4':  [b'\x00\x00\x00'],  # ftyp box
    '.avi':  [b'RIFF'],
    '.mkv':  [b'\x1a\x45\xdf\xa3'],
    '.webm': [b'\x1a\x45\xdf\xa3'],
    '.mov':  [b'\x00\x00\x00'],  # ftyp/moov
    '.flv':  [b'FLV'],
    '.wmv':  [b'\x30\x26\xb2\x75'],
    # Documents
    '.pdf':  [b'%PDF'],
    '.docx': [b'PK\x03\x04'],  # ZIP-based
    '.xlsx': [b'PK\x03\x04'],
    '.pptx': [b'PK\x03\x04'],
    '.odt':  [b'PK\x03\x04'],
    '.ods':  [b'PK\x03\x04'],
    '.doc':  [b'\xd0\xcf\x11\xe0'],  # OLE2
    '.xls':  [b'\xd0\xcf\x11\xe0'],
    '.ppt':  [b'\xd0\xcf\x11\xe0'],
    # Archives
    '.zip':  [b'PK\x03\x04', b'PK\x05\x06'],
    '.rar':  [b'Rar!\x1a\x07'],
    '.7z':   [b'7z\xbc\xaf\x27\x1c'],
    '.gz':   [b'\x1f\x8b'],
    '.bz2':  [b'BZh'],
    '.xz':   [b'\xfd7zXZ\x00'],
    '.tar':  [b'ustar'],  # at offset 257
    # Executables
    '.exe':  [b'MZ'],
    '.dll':  [b'MZ'],
    # Fonts
    '.ttf':  [b'\x00\x01\x00\x00'],
    '.otf':  [b'OTTO'],
    '.woff': [b'wOFF'],
    '.woff2':[b'wOF2'],
}

# Archives we can validate more deeply
_ARCHIVE_EXTS = frozenset({'.zip', '.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz'})


def _check_magic(fpath: str, ext: str) -> Optional[str]:
    """Check if file magic bytes match expected format. Returns error string or None."""
    headers = _MAGIC_HEADERS.get(ext.lower())
    if not headers:
        return None

    try:
        with open(fpath, 'rb') as f:
            # Read enough bytes for the longest header
            max_len = max(len(h) for h in headers)
            data = f.read(max(max_len, 16))

        if not data:
            return "File is empty"

        # Special case: .tar files have magic at offset 257
        if ext.lower() in ('.tar',):
            try:
                with open(fpath, 'rb') as f:
                    f.seek(257)
                    tar_magic = f.read(5)
                if tar_magic == b'ustar':
                    return None
            except OSError:
                pass
            return f"Invalid tar header (expected 'ustar' at offset 257)"

        # Check if any expected header matches
        for header in headers:
            if data[:len(header)] == header:
                return None

        return f"Invalid header: expected {headers[0][:8]!r}, got {data[:8]!r}"

    except (OSError, PermissionError) as e:
        return f"Cannot read: {e}"


def _check_archive_integrity(fpath: str, ext: str) -> Optional[str]:
    """Validate archive integrity. Returns error string or None."""
    ext_lower = ext.lower()
    try:
        if ext_lower == '.zip':
            with zipfile.ZipFile(fpath, 'r') as zf:
                bad = zf.testzip()
                if bad:
                    return f"Corrupt entry in ZIP: {bad}"
        elif ext_lower in ('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz'):
            mode = 'r'
            if ext_lower in ('.tar.gz', '.tgz'):
                mode = 'r:gz'
            elif ext_lower == '.tar.bz2':
                mode = 'r:bz2'
            elif ext_lower == '.tar.xz':
                mode = 'r:xz'
            with tarfile.open(fpath, mode) as tf:
                tf.getmembers()  # will raise on corrupt
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as e:
        return f"Corrupt archive: {e}"
    return None


def scan_broken_files(root: str, *, depth: int = 99,
                      check_archives: bool = True,
                      progress_cb: Callable = None,
                      item_cb: Callable = None) -> List[CleanupItem]:
    """Find files with invalid headers (wrong magic bytes) or corrupt archives."""
    results = []
    root_depth = root.rstrip(os.sep).count(os.sep)

    for dirpath, dirnames, filenames in os.walk(root):
        current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        if current_depth > depth:
            dirnames.clear()
            continue

        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            _, ext = os.path.splitext(fname)
            if not ext:
                continue

            try:
                st = os.stat(fpath)
            except (OSError, PermissionError):
                continue

            # Skip very small files (likely placeholders)
            if st.st_size < 8:
                continue

            # Check magic bytes
            error = _check_magic(fpath, ext)
            if error:
                item = CleanupItem(
                    path=fpath, size=st.st_size,
                    reason=f"Invalid file format: {error}",
                    category="broken_file", modified=st.st_mtime
                )
                results.append(item)
                if progress_cb:
                    progress_cb(f"Broken: {fpath}")
                if item_cb:
                    item_cb(item)
                continue

            # Deep archive validation
            if check_archives and ext.lower() in _ARCHIVE_EXTS:
                error = _check_archive_integrity(fpath, ext)
                if error:
                    item = CleanupItem(
                        path=fpath, size=st.st_size,
                        reason=error, category="broken_file",
                        modified=st.st_mtime
                    )
                    results.append(item)
                    if progress_cb:
                        progress_cb(f"Corrupt archive: {fpath}")
                    if item_cb:
                        item_cb(item)

    return results


# ── Big File Finder ──────────────────────────────────────────────────────────

def scan_big_files(root: str, *, min_size_mb: float = 100.0, depth: int = 99,
                   limit: int = 500,
                   progress_cb: Callable = None,
                   item_cb: Callable = None) -> List[CleanupItem]:
    """Find the largest files under root, above min_size_mb threshold."""
    results = []
    root_depth = root.rstrip(os.sep).count(os.sep)
    min_bytes = int(min_size_mb * 1024 * 1024)

    for dirpath, dirnames, filenames in os.walk(root):
        current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        if current_depth > depth:
            dirnames.clear()
            continue

        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                st = os.stat(fpath)
                if st.st_size >= min_bytes:
                    _, ext = os.path.splitext(fname)
                    item = CleanupItem(
                        path=fpath, size=st.st_size,
                        reason=f"Large file ({_fmt_size(st.st_size)})",
                        category="big_file", modified=st.st_mtime
                    )
                    results.append(item)
                    if progress_cb:
                        progress_cb(f"Big: {fpath}")
                    if item_cb:
                        item_cb(item)
            except (OSError, PermissionError):
                continue

    # Sort by size descending, limit results
    results.sort(key=lambda x: x.size, reverse=True)
    return results[:limit]


# ── Duplicate Folder Scanner ─────────────────────────────────────────────────

def scan_duplicate_folders(root: str, *, depth: int = 3,
                           progress_cb: Callable = None) -> List[tuple]:
    """Find folders with identical content (same files by hash).
    Returns list of (canonical_folder, [duplicate_folders]) tuples."""
    import hashlib
    from collections import defaultdict

    folder_hashes = {}  # path -> composite hash
    root_depth = root.rstrip(os.sep).count(os.sep)

    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        if current_depth > depth:
            continue

        if not filenames:
            continue

        # Build composite hash from sorted file names + sizes
        hasher = hashlib.sha256()
        file_entries = []
        try:
            for fname in sorted(filenames):
                fpath = os.path.join(dirpath, fname)
                try:
                    st = os.stat(fpath)
                    file_entries.append((fname, st.st_size))
                except OSError:
                    continue
        except PermissionError:
            continue

        if not file_entries:
            continue

        for fname, fsize in file_entries:
            hasher.update(f"{fname}:{fsize}".encode())

        folder_hashes[dirpath] = hasher.hexdigest()

        if progress_cb:
            progress_cb(f"Hashing: {dirpath}")

    # Group by hash
    hash_groups = defaultdict(list)
    for path, h in folder_hashes.items():
        hash_groups[h].append(path)

    # Return only groups with duplicates
    results = []
    for h, paths in hash_groups.items():
        if len(paths) > 1:
            paths.sort(key=lambda p: len(p))  # shortest path = canonical
            results.append((paths[0], paths[1:]))

    return results


# ── Orphaned Shortcut Scanner (Windows) ──────────────────────────────────────

def scan_orphaned_shortcuts(root: str, *, depth: int = 99,
                            progress_cb: Callable = None) -> List[CleanupItem]:
    """Find .lnk shortcuts pointing to non-existent targets (Windows only)."""
    import sys
    if sys.platform != 'win32':
        return []

    results = []
    root_depth = root.rstrip(os.sep).count(os.sep)

    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
    except ImportError:
        # Fallback: just check if .lnk files exist but can't resolve targets
        return results

    for dirpath, dirnames, filenames in os.walk(root):
        current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        if current_depth > depth:
            dirnames.clear()
            continue

        for fname in filenames:
            if not fname.lower().endswith('.lnk'):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                shortcut = shell.CreateShortCut(fpath)
                target = shortcut.TargetPath
                if target and not os.path.exists(target):
                    st = os.stat(fpath)
                    results.append(CleanupItem(
                        path=fpath, size=st.st_size,
                        reason=f"Target missing: {target}",
                        category="orphaned_shortcut", modified=st.st_mtime
                    ))
                    if progress_cb:
                        progress_cb(f"Orphaned: {fpath}")
            except Exception:
                continue

    return results


# ── Old Download Scanner ─────────────────────────────────────────────────────

def scan_old_downloads(root: str, *, days_old: int = 90,
                       progress_cb: Callable = None,
                       item_cb: Callable = None) -> List[CleanupItem]:
    """Find files not accessed/modified in N days. Useful for Downloads cleanup."""
    results = []
    cutoff = time.time() - (days_old * 86400)

    for entry in os.scandir(root):
        if not entry.is_file(follow_symlinks=False):
            continue
        try:
            st = entry.stat()
            last_access = max(st.st_mtime, st.st_atime)
            if last_access < cutoff:
                age_days = int((time.time() - last_access) / 86400)
                item = CleanupItem(
                    path=entry.path, size=st.st_size,
                    reason=f"Not accessed in {age_days} days",
                    category="old_file", modified=st.st_mtime
                )
                results.append(item)
                if progress_cb:
                    progress_cb(f"Old: {entry.path}")
                if item_cb:
                    item_cb(item)
        except (OSError, PermissionError):
            continue

    results.sort(key=lambda x: x.modified)
    return results


# ── Utility ──────────────────────────────────────────────────────────────────

def _fmt_size(size_bytes: int) -> str:
    """Format file size as human-readable string."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != 'B' else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def delete_items(items: List[CleanupItem], *, use_trash: bool = True,
                 progress_cb: Callable = None) -> tuple:
    """Delete selected cleanup items. Returns (success_count, fail_count, freed_bytes)."""
    success = 0
    failed = 0
    freed = 0

    # Try to use send2trash for safe deletion
    _send2trash = None
    if use_trash:
        try:
            from send2trash import send2trash as _send2trash
        except ImportError:
            _send2trash = None

    for item in items:
        if not item.selected:
            continue
        if is_protected(item.path):
            if progress_cb:
                progress_cb(f"Skipped (protected): {item.path}")
            continue
        try:
            if item.category == "empty_folder":
                if _send2trash:
                    _send2trash(item.path)
                else:
                    os.rmdir(item.path)
            else:
                if _send2trash:
                    _send2trash(item.path)
                else:
                    os.remove(item.path)
            freed += item.size
            success += 1
            if progress_cb:
                progress_cb(f"Deleted: {item.path}")
        except Exception as e:
            failed += 1
            if progress_cb:
                progress_cb(f"Failed: {item.path} ({e})")

    return success, failed, freed
