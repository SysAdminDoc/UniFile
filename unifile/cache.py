"""UniFile — Caching, corrections, undo log, and backup utilities."""
import os, json, csv, hashlib, sqlite3, shutil, gzip, re, threading
from datetime import datetime
from pathlib import Path

from unifile.config import (
    _APP_DATA_DIR, _UNDO_LOG_FILE, _UNDO_STACK_FILE, _CSV_LOG_FILE,
    _LAST_CONFIG_FILE, _PROFILES_DIR, _CUSTOM_CATS_FILE, CONF_FUZZY_CAP,
    register_sqlite_connection,
)

from unifile.bootstrap import HAS_RAPIDFUZZ
try:
    from rapidfuzz import fuzz as _rfuzz
except ImportError:
    _rfuzz = None

_CORRECTIONS_FILE = os.path.join(_APP_DATA_DIR, 'corrections.json')

def load_corrections():
    """Load user corrections: {folder_name_pattern: category}"""
    try:
        with open(_CORRECTIONS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# In-memory corrections cache for scan performance (avoids re-reading JSON per folder)
_corrections_cache = None

def _preload_corrections():
    """Pre-load corrections into memory. Call once at scan start."""
    global _corrections_cache
    _corrections_cache = load_corrections()

def _invalidate_corrections_cache():
    """Invalidate cache after edits."""
    global _corrections_cache
    _corrections_cache = None

def save_correction(folder_name, category):
    """Save a single correction for future learning."""
    corrections = load_corrections()
    # Store the cleaned folder name as key
    key = re.sub(r'[\d_\-]+$', '', folder_name).strip().lower()
    if key:
        corrections[key] = category
    corrections[folder_name.lower()] = category
    with open(_CORRECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(corrections, f, indent=2)
    _invalidate_corrections_cache()

def check_corrections(folder_name):
    """Check if we have a prior correction for this folder name.
    Returns category string or None. Uses in-memory cache when available."""
    corrections = _corrections_cache if _corrections_cache is not None else load_corrections()
    if not corrections:
        return None
    name_lower = folder_name.lower()
    # Exact match
    if name_lower in corrections:
        return corrections[name_lower]
    # Pattern match (cleaned name)
    key = re.sub(r'[\d_\-]+$', '', folder_name).strip().lower()
    if key and key in corrections:
        return corrections[key]
    # Fuzzy match against correction keys
    if HAS_RAPIDFUZZ:
        for ck, cv in corrections.items():
            if _rfuzz.token_set_ratio(name_lower, ck) >= 90:
                return cv
    return None



# ── Classification Cache (SQLite) ─────────────────────────────────────────────
_CACHE_DB = os.path.join(_APP_DATA_DIR, 'classification_cache.db')
_cache_local = threading.local()  # Thread-local storage for connections

def _get_cache_conn():
    """Get thread-local SQLite connection, creating if needed."""
    conn = getattr(_cache_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(_CACHE_DB, timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS cache ('
            'fingerprint TEXT PRIMARY KEY,'
            'category TEXT,'
            'confidence REAL,'
            'cleaned_name TEXT,'
            'method TEXT,'
            'detail TEXT,'
            'topic TEXT,'
            'created_at TEXT DEFAULT CURRENT_TIMESTAMP'
        ')')
        conn.commit()
        _cache_local.conn = conn
        register_sqlite_connection(conn)
    return conn

def _close_cache_conn():
    """Close thread-local connection (call after scan completes)."""
    conn = getattr(_cache_local, 'conn', None)
    if conn:
        try:
            conn.close()
        except Exception:
            pass
        _cache_local.conn = None

def _init_cache_db():
    """Initialize the cache database. Uses persistent connection."""
    return _get_cache_conn()

def _folder_fingerprint(folder_name, folder_path):
    """Compute a fingerprint based on folder name + file listing."""
    try:
        files = sorted(f.name for f in Path(folder_path).iterdir() if f.is_file())[:50]
    except (PermissionError, OSError):
        files = []
    raw = f"{folder_name}|{'|'.join(files)}"
    return hashlib.md5(raw.encode()).hexdigest()

def cache_lookup(folder_name, folder_path):
    """Check the cache for a prior classification. Returns dict or None."""
    try:
        fp = _folder_fingerprint(folder_name, folder_path)
        conn = _get_cache_conn()
        row = conn.execute('SELECT category, confidence, cleaned_name, method, detail, topic FROM cache WHERE fingerprint=?', (fp,)).fetchone()
        if row:
            return {'category': row[0], 'confidence': row[1], 'cleaned_name': row[2],
                    'method': row[3], 'detail': row[4], 'topic': row[5]}
    except Exception:
        pass
    return None

def cache_store(folder_name, folder_path, result):
    """Store a classification result in the cache."""
    try:
        fp = _folder_fingerprint(folder_name, folder_path)
        conn = _get_cache_conn()
        conn.execute('INSERT OR REPLACE INTO cache (fingerprint, category, confidence, cleaned_name, method, detail, topic) VALUES (?,?,?,?,?,?,?)',
                     (fp, result.get('category'), result.get('confidence', 0),
                      result.get('cleaned_name', ''), result.get('method', ''),
                      result.get('detail', ''), result.get('topic', '')))
        conn.commit()
    except Exception:
        pass

def cache_clear():
    """Clear the entire classification cache."""
    try:
        conn = _get_cache_conn()
        conn.execute('DELETE FROM cache')
        conn.commit()
    except Exception:
        pass

def cache_count():
    """Return the number of cached classifications."""
    try:
        conn = _get_cache_conn()
        n = conn.execute('SELECT COUNT(*) FROM cache').fetchone()[0]
        return n
    except Exception:
        return 0



# ── Duplicate Folder Detection ────────────────────────────────────────────────
def compute_file_fingerprint(folder_path, max_files=20):
    """Compute a content fingerprint for a folder based on file names and sizes."""
    try:
        entries = []
        for f in sorted(Path(folder_path).iterdir()):
            if f.is_file():
                try:
                    entries.append(f"{f.name}:{f.stat().st_size}")
                except (PermissionError, OSError):
                    continue
            if len(entries) >= max_files:
                break
        return hashlib.md5('|'.join(entries).encode()).hexdigest() if entries else None
    except (PermissionError, OSError):
        return None



# ── Backup Snapshot ───────────────────────────────────────────────────────────
def create_backup_snapshot(src_dir, items):
    """Save a directory listing snapshot before apply operations."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    snap_file = os.path.join(_APP_DATA_DIR, f'snapshot_{ts}.txt')
    try:
        with open(snap_file, 'w', encoding='utf-8') as f:
            f.write(f"UniFile Backup Snapshot - {datetime.now().isoformat()}\n")
            f.write(f"Source: {src_dir}\n")
            f.write(f"Items: {len(items)}\n")
            f.write("=" * 80 + "\n\n")
            for it in items:
                src = getattr(it, 'full_source_path', getattr(it, 'full_current_path', ''))
                dst = getattr(it, 'full_dest_path', getattr(it, 'full_new_path', ''))
                f.write(f"FROM: {src}\n  TO: {dst}\n\n")
        return snap_file
    except Exception:
        return None



# ── Export/Import Classification Rules ────────────────────────────────────────
def export_rules_bundle(filepath):
    """Export custom categories + corrections as a single JSON bundle."""
    from unifile.categories import load_custom_categories
    bundle = {
        'version': '7.2',
        'custom_categories': load_custom_categories(),
        'corrections': load_corrections(),
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, indent=2)

def import_rules_bundle(filepath):
    """Import custom categories + corrections from a JSON bundle."""
    from unifile.categories import save_custom_categories
    with open(filepath, encoding='utf-8') as f:
        bundle = json.load(f)
    if 'custom_categories' in bundle:
        save_custom_categories(bundle['custom_categories'])
    if 'corrections' in bundle:
        with open(_CORRECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(bundle['corrections'], f, indent=2)
    return bundle

# ── Undo / operation log ──────────────────────────────────────────────────────
_UNDO_MAX_BATCHES = 50

def _load_undo_stack() -> list:
    """Load multi-level undo stack. Each entry is a dict with 'timestamp', 'ops'."""
    # Migration: convert old flat undo_log.json into a single batch
    if os.path.exists(_UNDO_LOG_FILE) and not os.path.exists(_UNDO_STACK_FILE):
        try:
            with open(_UNDO_LOG_FILE, encoding='utf-8') as f:
                old_ops = json.load(f)
            if old_ops:
                batch = {'timestamp': datetime.now().isoformat(), 'ops': old_ops,
                         'count': len(old_ops)}
                with open(_UNDO_STACK_FILE, 'w', encoding='utf-8') as f:
                    json.dump([batch], f, indent=2)
            os.remove(_UNDO_LOG_FILE)
        except Exception:
            pass
    if os.path.exists(_UNDO_STACK_FILE):
        try:
            with open(_UNDO_STACK_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def _save_undo_stack(stack: list):
    with open(_UNDO_STACK_FILE, 'w', encoding='utf-8') as f:
        json.dump(stack, f, indent=2)

def save_undo_log(operations, **meta):
    """Push a new batch onto the undo stack (preserves previous batches, max 50).

    Extra keyword args (source_dir, mode, etc.) are stored in the batch record
    so the history UI can show meaningful context for each operation.
    """
    stack = _load_undo_stack()
    batch = {
        'timestamp': datetime.now().isoformat(),
        'ops': operations,
        'count': len(operations),
        'status': 'applied',
    }
    batch.update(meta)
    stack.append(batch)
    if len(stack) > _UNDO_MAX_BATCHES:
        stack = stack[-_UNDO_MAX_BATCHES:]
    _save_undo_stack(stack)

def load_undo_log():
    """Flatten all batches for backward compat (returns all ops)."""
    stack = _load_undo_stack()
    ops = []
    for batch in stack:
        ops.extend(batch.get('ops', []))
    return ops

def clear_undo_log():
    for f in (_UNDO_LOG_FILE, _UNDO_STACK_FILE):
        if os.path.exists(f):
            os.remove(f)

def append_csv_log(operations):
    """Append operations to CSV audit log."""
    exists = os.path.exists(_CSV_LOG_FILE)
    with open(_CSV_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(['Timestamp', 'Operation', 'Source', 'Destination', 'Category', 'Confidence', 'Status'])
        for op in operations:
            w.writerow([op.get('timestamp',''), op.get('type',''), op.get('src',''),
                        op.get('dst',''), op.get('category',''), op.get('confidence',''), op.get('status','')])

# ── File hashing for duplicate detection ──────────────────────────────────────
def hash_file(filepath, chunk_size=65536):
    """Fast MD5 hash of a file."""
    h = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk: break
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError):
        return None

