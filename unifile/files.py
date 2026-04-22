"""UniFile — PC file classification, scan cache, MIME detection, filename intelligence."""
import json
import mimetypes as _mimetypes
import os
import re
import sqlite3
import time

from unifile.bootstrap import HAS_MAGIC, HAS_RAPIDFUZZ

try:
    import magic as _magic  # noqa: F401  -- availability probe for content-type detection
except ImportError:
    pass
try:
    from rapidfuzz import fuzz as _rfuzz
except ImportError:
    _rfuzz = None

from unifile.config import _APP_DATA_DIR, _PC_SCAN_CACHE_DB, register_sqlite_connection

_PC_CATEGORIES_DB = os.path.join(_APP_DATA_DIR, 'pc_categories.json')

_DEFAULT_PC_CATEGORIES = [
    {"name": "Documents",    "color": "#60a5fa", "rename_template": "",
     "extensions": ["doc","docx","odt","rtf","txt","md","pdf","xls","xlsx","ods",
                    "csv","ppt","pptx","odp","pages","numbers","key","wps","wpd",
                    "tex","bib","fodt","fods","fodp","epub","mobi"]},
    {"name": "Images",       "color": "#34d399", "rename_template": "{year}-{month}-{day}_{name}",
     "extensions": ["jpg","jpeg","png","gif","bmp","tiff","tif","webp","heic","heif",
                    "raw","cr2","cr3","nef","arw","dng","orf","rw2","pef","srw",
                    "ico","icns","svg","avif","jxl","jp2","j2k"]},
    {"name": "Videos",       "color": "#f472b6", "rename_template": "{year}-{month}-{day}_{name}",
     "extensions": ["mp4","mkv","avi","mov","wmv","flv","webm","m4v","mpg","mpeg",
                    "3gp","3g2","ts","mts","m2ts","vob","ogv","rm","rmvb","asf",
                    "f4v","divx","xvid","h264","h265","hevc"]},
    {"name": "Audio",        "color": "#a78bfa", "rename_template": "{artist} - {album} - {track:02d} - {title}",
     "extensions": ["mp3","wav","flac","aac","ogg","wma","m4a","opus","aiff","aif",
                    "ape","mka","mid","midi","amr","au","ra","wv","tta","dsd",
                    "dsf","dff","caf"]},
    {"name": "Archives",     "color": "#fbbf24", "rename_template": "",
     "extensions": ["zip","rar","7z","tar","gz","bz2","xz","zst","lz4","lzma",
                    "tgz","tbz2","txz","cab","iso","img","dmg","wim","lzh","arj",
                    "ace","jar","war","ear","apk","ipa","deb","rpm","pkg"]},
    {"name": "Code",         "color": "#38bdf8", "rename_template": "",
     "extensions": ["py","js","ts","jsx","tsx","html","htm","css","scss","sass",
                    "less","php","rb","java","c","cpp","cc","h","hpp","cs","go",
                    "rs","swift","kt","dart","lua","r","m","sh","bash","zsh","ps1",
                    "psm1","bat","cmd","vbs","asm","sql","json","xml","yaml","yml",
                    "toml","ini","cfg","conf","env","dockerfile","makefile","cmake",
                    "gradle","vue","svelte","elm","ex","exs","clj","hs","fs","fsx"]},
    {"name": "Executables",  "color": "#ef4444", "rename_template": "",
     "extensions": ["exe","msi","msix","appx","app","dmg","pkg","deb","rpm","run",
                    "bin","com","scr","gadget","pif","vxd","dll","sys","drv"]},
    {"name": "Fonts",        "color": "#fb923c", "rename_template": "",
     "extensions": ["ttf","otf","woff","woff2","eot","fon","fnt","pfb","pfm","afm",
                    "bdf","pcf","snf","sfd"]},
    {"name": "Data",         "color": "#2dd4bf", "rename_template": "",
     "extensions": ["db","sqlite","sqlite3","mdb","accdb","dbf","sql","bak",
                    "json","xml","csv","tsv","parquet","avro","orc","hdf5","h5",
                    "mat","pkl","pickle","npy","npz","feather","arrow"]},
    {"name": "Design",       "color": "#c084fc", "rename_template": "",
     "extensions": ["psd","psb","ai","eps","indd","idml","xd","fig","sketch",
                    "aep","aet","prproj","mogrt","fla","swf","blend","c4d","max",
                    "ma","mb","fbx","obj","stl","3ds","dae","glb","gltf"]},
    {"name": "Shortcuts",    "color": "#94a3b8", "rename_template": "",
     "extensions": ["lnk","url","webloc","desktop"]},
    {"name": "Other",        "color": "#6b7280", "rename_template": "", "extensions": []},
]


def _load_pc_categories() -> list:
    """Load user-customized PC categories, falling back to defaults."""
    try:
        if os.path.exists(_PC_CATEGORIES_DB):
            with open(_PC_CATEGORIES_DB, encoding='utf-8') as f:
                cats = json.load(f)
            if cats and isinstance(cats, list):
                return cats
    except Exception:
        pass
    return [dict(c) for c in _DEFAULT_PC_CATEGORIES]


def _save_pc_categories(cats: list):
    os.makedirs(os.path.dirname(_PC_CATEGORIES_DB), exist_ok=True)
    with open(_PC_CATEGORIES_DB, 'w', encoding='utf-8') as f:
        json.dump(cats, f, indent=2)


def _build_ext_map(categories: list) -> dict:
    """Build extension→category lookup dict from category list."""
    m = {}
    for cat in categories:
        for ext in cat.get('extensions', []):
            m[ext.lower().lstrip('.')] = cat['name']
    return m


# ── Classifier-format config import/export ───────────────────────────────────
# Compatible with bhrigu123/classifier's .classifier.conf format:
#   Category: ext1, ext2, ext3

DIRCONF_FILENAME = '.unifile.conf'


def import_classifier_config(config_path: str) -> list:
    """Import a classifier-format config file into UniFile category list.

    Format: 'Category: ext1, ext2, ext3' (one per line).
    Lines starting with IGNORE are treated as ignored extensions.
    """
    categories = []
    ignored_exts = []
    with open(config_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' not in line:
                continue
            parts = line.split(':', 1)
            name = parts[0].strip()
            exts = [e.strip().lower().lstrip('.') for e in parts[1].split(',') if e.strip()]
            if name.upper() == 'IGNORE':
                ignored_exts.extend(exts)
                continue
            categories.append({
                'name': name,
                'color': '#6b7280',
                'rename_template': '',
                'extensions': exts,
            })
    return categories


def export_classifier_config(categories: list, output_path: str):
    """Export UniFile categories to classifier-format config file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('# UniFile category config (classifier-compatible format)\n')
        for cat in categories:
            exts = cat.get('extensions', [])
            if exts:
                f.write(f"{cat['name']}: {', '.join(exts)}\n")


def load_directory_config(directory: str) -> list | None:
    """Load per-directory .unifile.conf if it exists.

    Returns category list or None if no local config found.
    Supports both classifier format (Category: ext1, ext2) and
    UniFile extended format (Category:OutputPath: ext1, ext2).
    """
    conf_path = os.path.join(directory, DIRCONF_FILENAME)
    # Also check for .classifier.conf for backwards compatibility
    if not os.path.exists(conf_path):
        conf_path = os.path.join(directory, '.classifier.conf')
    if not os.path.exists(conf_path):
        return None

    categories = []
    with open(conf_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(':')
            if len(parts) < 2:
                continue
            if len(parts) == 3:
                # Extended format: Category:OutputPath:ext1,ext2
                name = parts[0].strip()
                output_dir = parts[1].strip()
                exts = [e.strip().lower().lstrip('.') for e in parts[2].split(',') if e.strip()]
                categories.append({
                    'name': name,
                    'color': '#6b7280',
                    'rename_template': '',
                    'extensions': exts,
                    'output_dir': output_dir,
                })
            else:
                # Standard format: Category: ext1, ext2
                name = parts[0].strip()
                if name.upper() == 'IGNORE':
                    continue
                exts = [e.strip().lower().lstrip('.') for e in parts[1].split(',') if e.strip()]
                categories.append({
                    'name': name,
                    'color': '#6b7280',
                    'rename_template': '',
                    'extensions': exts,
                })
    return categories if categories else None


def merge_categories(base: list, override: list) -> list:
    """Merge override categories into base, adding new ones and extending existing."""
    merged = [dict(c) for c in base]
    name_map = {c['name'].lower(): i for i, c in enumerate(merged)}

    for ov in override:
        key = ov['name'].lower()
        if key in name_map:
            # Extend existing category with new extensions
            idx = name_map[key]
            existing_exts = set(merged[idx].get('extensions', []))
            for ext in ov.get('extensions', []):
                existing_exts.add(ext)
            merged[idx]['extensions'] = sorted(existing_exts)
            # Override output_dir if specified
            if 'output_dir' in ov:
                merged[idx]['output_dir'] = ov['output_dir']
        else:
            # Add new category
            merged.append(dict(ov))
            name_map[key] = len(merged) - 1

    return merged



# ── Junk / temp file patterns — skip during scan ────────────────────────────
_JUNK_PATTERNS = re.compile(
    r'^(?:'
    r'~\$.*|'               # Office lock files (~$document.docx)
    r'~lock\..*|'           # LibreOffice lock files
    r'\.~lock\..*|'         # LibreOffice alt lock
    r'Thumbs\.db|'          # Windows thumbnail cache
    r'desktop\.ini|'        # Windows folder config
    r'\.DS_Store|'          # macOS folder metadata
    r'\.Spotlight-V100|'    # macOS Spotlight index
    r'\.Trashes|'           # macOS Trash
    r'__MACOSX|'            # macOS archive artifacts
    r'\.fseventsd|'         # macOS FSEvents
    r'ehthumbs\.db|'        # Windows media center thumbnails
    r'Zone\.Identifier'     # Windows NTFS alternate data stream
    r')$', re.IGNORECASE)

_JUNK_SUFFIXES = {'.tmp', '.bak', '.swp', '.swo', '.crdownload', '.part', '.partial'}


# ── MIME type → category mapping (content-based detection via python-magic) ──
_MIME_CATEGORY_MAP = {
    # Images
    'image/jpeg': 'Images', 'image/png': 'Images', 'image/gif': 'Images',
    'image/bmp': 'Images', 'image/tiff': 'Images', 'image/webp': 'Images',
    'image/svg+xml': 'Images', 'image/x-icon': 'Images', 'image/heic': 'Images',
    'image/heif': 'Images', 'image/avif': 'Images',
    # Video
    'video/mp4': 'Videos', 'video/x-matroska': 'Videos', 'video/x-msvideo': 'Videos',
    'video/quicktime': 'Videos', 'video/webm': 'Videos', 'video/x-flv': 'Videos',
    'video/x-ms-wmv': 'Videos', 'video/mpeg': 'Videos', 'video/3gpp': 'Videos',
    # Audio
    'audio/mpeg': 'Audio', 'audio/x-wav': 'Audio', 'audio/flac': 'Audio',
    'audio/ogg': 'Audio', 'audio/aac': 'Audio', 'audio/mp4': 'Audio',
    'audio/x-ms-wma': 'Audio', 'audio/opus': 'Audio', 'audio/aiff': 'Audio',
    # Documents
    'application/pdf': 'Documents',
    'application/msword': 'Documents',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Documents',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Documents',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'Documents',
    'application/vnd.ms-excel': 'Documents', 'application/vnd.ms-powerpoint': 'Documents',
    'application/rtf': 'Documents', 'text/plain': 'Documents', 'text/markdown': 'Documents',
    'application/epub+zip': 'Documents',
    # Archives
    'application/zip': 'Archives', 'application/x-rar-compressed': 'Archives',
    'application/x-7z-compressed': 'Archives', 'application/gzip': 'Archives',
    'application/x-tar': 'Archives', 'application/x-bzip2': 'Archives',
    'application/x-xz': 'Archives', 'application/x-iso9660-image': 'Archives',
    # Code (text types)
    'text/html': 'Code', 'text/css': 'Code', 'text/xml': 'Code',
    'application/javascript': 'Code', 'application/json': 'Code',
    'application/xml': 'Code', 'text/x-python': 'Code', 'text/x-c': 'Code',
    'text/x-java': 'Code', 'text/x-shellscript': 'Code',
    # Executables
    'application/x-executable': 'Executables', 'application/x-dosexec': 'Executables',
    'application/x-msi': 'Executables',
    # Fonts
    'font/ttf': 'Fonts', 'font/otf': 'Fonts', 'font/woff': 'Fonts',
    'font/woff2': 'Fonts', 'application/vnd.ms-fontobject': 'Fonts',
    # Data
    'application/x-sqlite3': 'Data', 'application/vnd.ms-access': 'Data',
}


# ── Filename intelligence — recognise camera patterns, keywords, dates ───────
_FNAME_DEVICE_PATTERNS = [
    # Camera / phone image patterns (allow _ or - between prefix and digits)
    (re.compile(r'^(?:IMG|DSC|DSCN|DSCF|SAM|PXL|MVIMG|P\d{6,}|GOPR)[_\-]?\d', re.I), 'Images', 15, 'camera_filename'),
    # Camera / phone video patterns
    (re.compile(r'^(?:VID|MOV|MVI|GX\d{3,})[_\-]?\d', re.I), 'Videos', 15, 'video_filename'),
    # Screenshots
    (re.compile(r'^(?:Screenshot|Screen[\s_]?Shot|Capture|Snip)', re.I), 'Images', 12, 'screenshot'),
    # Document keywords (use non-alpha boundaries since _ is a word char in filenames)
    (re.compile(r'(?:^|[^a-zA-Z])(?:invoice|receipt|statement|contract|report|resume|cv|letter|memo)(?:[^a-zA-Z]|$)', re.I), 'Documents', 10, 'doc_keyword'),
    # Installer keywords
    (re.compile(r'(?:^|[^a-zA-Z])(?:setup|install|installer|update|patch|unins)(?:[^a-zA-Z]|$)', re.I), 'Executables', 10, 'installer_keyword'),
    # Archive keywords
    (re.compile(r'(?:^|[^a-zA-Z])(?:backup|archive|compressed|bundle)(?:[^a-zA-Z]|$)', re.I), 'Archives', 5, 'archive_keyword'),
    # Wallpaper / graphic keywords
    (re.compile(r'(?:^|[^a-zA-Z])(?:wallpaper|background|banner|poster|thumbnail|avatar|logo)(?:[^a-zA-Z]|$)', re.I), 'Images', 8, 'image_keyword'),
]

_FNAME_DATE_PATTERNS = [
    # YYYY-MM-DD or YYYY_MM_DD  (in filename)
    (re.compile(r'(?:^|[_\-\s])(\d{4})[_\-](\d{2})[_\-](\d{2})(?:[_\-\s]|$)'), 'ymd'),
    # YYYYMMDD  (compact, e.g. IMG_20240315)
    (re.compile(r'(?:^|[_\-\s])(\d{4})(\d{2})(\d{2})(?:[_\-\s]|$)'), 'ymd_compact'),
    # Device prefixes with date: IMG_20240315, VID_20240315, Screenshot_20240315
    (re.compile(r'(?:IMG|VID|Screenshot|DSC|SAM|DSCN|DSCF|PXL|MVIMG)[_\-]?(\d{4})(\d{2})(\d{2})', re.I), 'device_date'),
]


def _extract_filename_date(name: str) -> dict:
    """Extract date components from a filename. Returns {fname_year, fname_month, fname_day} or {}."""
    stem = os.path.splitext(name)[0]
    for pattern, mode in _FNAME_DATE_PATTERNS:
        m = pattern.search(stem)
        if m:
            groups = m.groups()
            try:
                y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                if 1990 <= y <= 2040 and 1 <= mo <= 12 and 1 <= d <= 31:
                    return {'fname_year': str(y), 'fname_month': f'{mo:02d}', 'fname_day': f'{d:02d}'}
            except (ValueError, IndexError):
                continue
    return {}


def _detect_mime_category(filepath: str) -> tuple:
    """Detect file category via MIME type. Returns (category, confidence, method_tag) or (None, 0, '')."""
    # Try python-magic first (content-based, most reliable)
    if HAS_MAGIC:
        try:
            mime = _magic.from_file(filepath, mime=True)
            if mime:
                cat = _MIME_CATEGORY_MAP.get(mime)
                if cat:
                    return cat, 75, f'mime:{mime}'
                # Broader prefix match  (image/* → Images, etc.)
                prefix = mime.split('/')[0]
                prefix_map = {'image': 'Images', 'video': 'Videos', 'audio': 'Audio',
                              'text': 'Documents', 'font': 'Fonts'}
                cat = prefix_map.get(prefix)
                if cat:
                    return cat, 65, f'mime_prefix:{prefix}'
        except Exception:
            pass
    # Fallback to stdlib mimetypes (extension-based but wider coverage)
    try:
        mime, _ = _mimetypes.guess_type(filepath)
        if mime:
            cat = _MIME_CATEGORY_MAP.get(mime)
            if cat:
                return cat, 55, f'mimetypes:{mime}'
    except Exception:
        pass
    return None, 0, ''


def _classify_pc_item(path: str, ext_map: dict, is_folder: bool = False,
                      categories: list = None) -> tuple:
    """Multi-signal file/folder classification.

    Combines extension matching, MIME content detection, filename intelligence,
    and category keyword fuzzy matching into a weighted confidence score.

    Returns (category, confidence, method).
    """
    if is_folder:
        return _classify_pc_folder(path, ext_map)

    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower().lstrip('.')

    # ── Signal 1: Extension match (strongest signal, fast) ───────────────
    ext_cat = ext_map.get(ext)
    ext_conf = 90 if ext_cat else 0

    # ── Signal 2: Filename pattern intelligence ──────────────────────────
    fname_cat, fname_boost, fname_detail = None, 0, ''
    for pattern, cat, boost, detail in _FNAME_DEVICE_PATTERNS:
        if pattern.search(name):
            fname_cat, fname_boost, fname_detail = cat, boost, detail
            break

    # ── Signal 3: MIME content detection (only when extension fails) ─────
    mime_cat, mime_conf, mime_detail = None, 0, ''
    if not ext_cat or ext_cat == 'Other':
        mime_cat, mime_conf, mime_detail = _detect_mime_category(path)

    # ── Signal 4: Category keyword fuzzy matching (last resort) ──────────
    fuzzy_cat, fuzzy_conf = None, 0
    if not ext_cat and categories and HAS_RAPIDFUZZ:
        stem = os.path.splitext(name)[0]
        if len(stem) >= 5:
            for cat_def in categories:
                for kw in cat_def.get('keywords', []):
                    if len(kw) < 4:
                        continue
                    ratio = _rfuzz.token_sort_ratio(stem.lower(), kw.lower())
                    if ratio > fuzzy_conf and ratio >= 70:
                        fuzzy_conf = ratio * 0.65
                        fuzzy_cat = cat_def['name']

    # ── Combine signals (priority: extension > MIME > filename > fuzzy) ──
    if ext_cat and ext_cat != 'Other':
        final_cat = ext_cat
        final_conf = ext_conf
        method = 'extension'
        # Boost confidence if filename pattern agrees
        if fname_cat == ext_cat:
            final_conf = min(98, final_conf + fname_boost)
            method = f'extension+{fname_detail}'
    elif mime_cat:
        final_cat = mime_cat
        final_conf = mime_conf
        method = 'content'
        if fname_cat == mime_cat:
            final_conf = min(90, final_conf + fname_boost)
            method = f'content+{fname_detail}'
    elif fname_cat:
        final_cat = fname_cat
        final_conf = min(70, 50 + fname_boost)
        method = f'filename:{fname_detail}'
    elif fuzzy_cat:
        final_cat = fuzzy_cat
        final_conf = min(70, int(fuzzy_conf))
        method = 'keyword_fuzzy'
    elif ext_cat == 'Other':
        final_cat = 'Other'
        final_conf = 40
        method = 'no_ext_match'
    else:
        final_cat = 'Other'
        final_conf = 30
        method = 'no_ext_match'

    return final_cat, final_conf, method


def _classify_pc_folder(path: str, ext_map: dict) -> tuple:
    """Classify a folder by weighted analysis of its contents (2 levels deep).

    Uses both file count and total size per category — a folder with 3 tiny
    .txt files and 1 large .mp4 should classify as Videos, not Documents.

    Returns (category, confidence, method).
    """
    cat_count = {}
    cat_size  = {}
    total_files = 0

    try:
        for root, dirs, files in os.walk(path):
            rel = os.path.relpath(root, path)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            if depth > 1:
                dirs.clear(); continue
            dirs[:] = [d for d in dirs if not d.startswith('.') and not d.startswith('$')]
            for f in files:
                if f.startswith('.') or _JUNK_PATTERNS.match(f):
                    continue
                e = os.path.splitext(f)[1].lower().lstrip('.')
                cat = ext_map.get(e)
                if cat and cat != 'Other':
                    cat_count[cat] = cat_count.get(cat, 0) + 1
                    try:
                        sz = os.path.getsize(os.path.join(root, f))
                        cat_size[cat] = cat_size.get(cat, 0) + sz
                    except OSError:
                        pass
                total_files += 1
    except (PermissionError, OSError):
        pass

    if not cat_count:
        return 'Other', 25, 'folder_empty'

    # Weighted score: 60% by file count, 40% by total size
    total_counted = sum(cat_count.values())
    total_bytes   = sum(cat_size.values()) or 1
    scores = {}
    for cat in cat_count:
        count_pct = cat_count[cat] / total_counted
        size_pct  = cat_size.get(cat, 0) / total_bytes
        scores[cat] = count_pct * 0.6 + size_pct * 0.4

    best = max(scores, key=scores.get)
    best_score = scores[best]
    conf = min(95, int(best_score * 100) + 15)

    # Require ≥2 files for high confidence
    if cat_count[best] < 2:
        conf = min(conf, 50)

    method = f'folder({cat_count[best]}/{total_counted}files)'
    return best, conf, method



# ── Scan Cache — SQLite keyed on (path, mtime, size) ────────────────────────
# Research: fclones/rmlint use (inode, mtime, size) but inode isn't reliable on
# Windows NTFS. We use full path + mtime + size as a cache key instead.

class _ScanCache:
    """Persists scan results across sessions for incremental rescans."""

    def __init__(self, db_path: str = _PC_SCAN_CACHE_DB):
        self.db_path = db_path
        self._conn = None

    def open(self):
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, timeout=5)
            register_sqlite_connection(self._conn)
            self._conn.execute('PRAGMA journal_mode=WAL')
            self._conn.execute("""CREATE TABLE IF NOT EXISTS scan_cache (
                path TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER,
                category TEXT,
                confidence INTEGER,
                method TEXT,
                metadata TEXT,
                cached_at REAL
            )""")
            self._conn.execute("""CREATE INDEX IF NOT EXISTS idx_cache_mtime
                ON scan_cache(path, mtime, size)""")
            self._conn.commit()
        except Exception:
            self._conn = None

    def close(self):
        if self._conn:
            try: self._conn.close()
            except Exception: pass
            self._conn = None

    def lookup(self, path: str, mtime: float, size: int) -> dict:
        """Return cached result dict or None if stale/missing."""
        if not self._conn:
            return None
        try:
            row = self._conn.execute(
                "SELECT category, confidence, method, metadata "
                "FROM scan_cache WHERE path=? AND mtime=? AND size=?",
                (path, mtime, size)
            ).fetchone()
            if row:
                meta = {}
                if row[3]:
                    try: meta = json.loads(row[3])
                    except Exception: pass
                return {
                    'category': row[0], 'confidence': row[1],
                    'method': row[2] + '+cached', 'metadata': meta,
                }
        except Exception:
            pass
        return None

    def store(self, path: str, mtime: float, size: int,
              category: str, confidence: int, method: str, metadata: dict):
        """Store or update a scan result."""
        if not self._conn:
            return
        try:
            meta_json = json.dumps(metadata) if metadata else ''
            self._conn.execute(
                "INSERT OR REPLACE INTO scan_cache "
                "(path, mtime, size, category, confidence, method, metadata, cached_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (path, mtime, size, category, confidence, method, meta_json, time.time())
            )
        except Exception:
            pass

    def commit(self):
        """Batch commit after processing multiple files."""
        if self._conn:
            try: self._conn.commit()
            except Exception: pass

    def prune(self, max_age_days: int = 30):
        """Remove entries older than max_age_days."""
        if not self._conn:
            return
        try:
            cutoff = time.time() - (max_age_days * 86400)
            self._conn.execute("DELETE FROM scan_cache WHERE cached_at < ?", (cutoff,))
            self._conn.commit()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# METADATA EXTRACTOR — Phase 1 (PC File Organizer)
# Extracts rich metadata from images, audio, video, PDFs, and Office docs.
# All library usage is guarded; missing libraries degrade gracefully.
# ══════════════════════════════════════════════════════════════════════════════

# Extension sets used by MetadataExtractor for type dispatch
_META_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.heic', '.heif',
                    '.webp', '.bmp', '.gif', '.cr2', '.cr3', '.nef', '.arw',
                    '.dng', '.orf', '.rw2', '.pef', '.srw', '.raw', '.avif', '.jxl'}
_META_AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a',
                    '.opus', '.aiff', '.aif', '.ape', '.mka', '.wv', '.tta',
                    '.dsf', '.dff', '.caf', '.mid', '.midi'}
_META_VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
                    '.m4v', '.mpg', '.mpeg', '.3gp', '.ts', '.mts', '.m2ts',
                    '.vob', '.ogv', '.asf', '.f4v', '.h264', '.h265', '.hevc'}
_META_PDF_EXTS   = {'.pdf'}
_META_DOCX_EXTS  = {'.docx'}
_META_XLSX_EXTS  = {'.xlsx'}
_META_PPTX_EXTS  = {'.pptx'}


