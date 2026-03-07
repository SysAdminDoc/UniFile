"""UniFile — Classification engine: extension, keyword, fuzzy, composition, tiered."""
import os, re, math
from pathlib import Path
from collections import Counter

from unifile.bootstrap import HAS_RAPIDFUZZ
try:
    from rapidfuzz import fuzz as _rfuzz
except ImportError:
    _rfuzz = None

from unifile.config import CONF_HIGH, CONF_MEDIUM, CONF_FUZZY_CAP, _APP_DATA_DIR
from unifile.cache import (
    check_corrections, cache_lookup, cache_store, _preload_corrections,
    _close_cache_conn, _init_cache_db
)
from unifile.categories import (
    CATEGORIES, BUILTIN_CATEGORIES, get_all_categories, get_all_category_names,
    _CategoryIndex, GENERIC_AEP_NAMES, is_generic_aep, _score_aep
)
from unifile.naming import (
    _normalize, _beautify_name, _smart_name, _strip_source_name,
    _is_id_only_folder, _has_non_latin, MARKETPLACE_PREFIXES,
    _NORMALIZED_PREFIX_SET
)

# ── Keyword-based folder categorization ───────────────────────────────────────

def categorize_folder(folder_name):
    """Match folder name against categories. Returns (category, score, cleaned_name) or (None, 0, cleaned).
    Strips marketplace prefixes and item IDs before matching.
    Uses pre-computed keyword index for speed."""
    cleaned = _strip_source_name(folder_name)

    # If the folder IS a bare marketplace name (nothing was stripped), skip categorization
    name_check = _normalize(folder_name)
    if name_check in _NORMALIZED_PREFIX_SET:
        return (None, 0, cleaned)

    norm = _normalize(cleaned)
    norm_loose = _normalize(cleaned.lower().replace('-', ' ').replace('_', ' ').replace('.', ' '))
    tokens = set(norm.split())
    best_cat = None
    best_score = 0

    index = _CategoryIndex.get()

    for cat_name, cat_norm, kw_list in index.entries:
        score = 0

        # Auto-match: folder name matches category name itself
        if norm == cat_norm:
            return (cat_name, 100, cleaned)  # Perfect match, early exit
        elif len(norm) > 3 and norm in cat_norm:
            score = max(score, 50 + len(norm) * 2)

        for kw, kw_norm, sig_tokens in kw_list:
            # Exact full match
            if norm == kw_norm:
                score = 100
                break  # Can't do better than 100, exit keyword loop
            # Short keywords (<=4 chars) must be exact token matches
            elif len(kw_norm) <= 4 and kw_norm in tokens:
                score = max(score, 50 + len(kw_norm) * 2)
            # Longer phrase found in folder name
            elif len(kw_norm) > 4 and kw_norm in norm:
                score = max(score, 50 + len(kw_norm) * 2)
            # Folder name found within keyword (reverse: "chill" inside "chill music")
            elif len(norm) > 3 and norm in kw_norm:
                score = max(score, 50 + len(norm) * 2)
            # Phrase found in loose name
            elif len(kw_norm) > 4 and kw_norm in norm_loose:
                score = max(score, 45 + len(kw_norm) * 2)
            else:
                # Token overlap (using pre-computed significant tokens)
                if sig_tokens:
                    matching = sig_tokens & tokens
                    if matching:
                        token_score = (len(matching) / len(sig_tokens)) * 40
                        if len(matching) > 1:
                            token_score += len(matching) * 5
                        score = max(score, token_score)

        if score >= 100:
            return (cat_name, 100, cleaned)  # Early exit on perfect match
        if score > best_score:
            best_score = score
            best_cat = cat_name

    if best_score >= 15:
        return (best_cat, min(best_score, 100), cleaned)
    return (None, 0, cleaned)


# ── Level 1: Extension-based classification ───────────────────────────────────
# Maps dominant file extensions to categories with base confidence.
# When >50% of files in a folder share an extension group, classification is near-certain.

EXTENSION_CATEGORY_MAP = [
    # (extension_set, category, base_confidence)
    # NOTE: Every category name here MUST exist in CATEGORIES or custom_categories
    ({'.ttf', '.otf', '.woff', '.woff2'},       "Fonts & Typography",                95),
    ({'.cube', '.3dl'},                          "Premiere Pro - LUTs & Color",       92),
    ({'.lut'},                                   "Premiere Pro - LUTs & Color",       92),
    ({'.lrtemplate'},                             "Lightroom - Presets & Profiles",    92),
    ({'.xmp'},                                   "Lightroom - Presets & Profiles",    85),
    ({'.abr'},                                   "Photoshop - Brushes",               92),
    ({'.atn'},                                   "Photoshop - Actions",               92),
    ({'.grd'},                                   "Photoshop - Gradients & Swatches",  90),
    ({'.pat'},                                   "Photoshop - Patterns",              90),
    ({'.asl'},                                   "Photoshop - Styles & Effects",      90),
    ({'.ffx'},                                   "After Effects - Presets & Scripts",  90),
    ({'.mogrt'},                                  "Premiere Pro - Templates",          92),
    ({'.jsx', '.jsxbin'},                        "After Effects - Presets & Scripts",  85),
    ({'.c4d'},                                   "3D",                                88),
    ({'.blend'},                                 "3D",                                88),
    ({'.obj', '.fbx', '.stl', '.3ds', '.dae'},  "3D - Models & Objects",             82),
    ({'.aep', '.aet'},                           "After Effects - Templates",         65),
    ({'.prproj'},                                "Premiere Pro - Templates",          65),
    ({'.psd', '.psb'},                           "Photoshop - Templates & Composites", 70),
    ({'.ai'},                                    "Illustrator - Vectors & Assets",    70),
    ({'.indd', '.idml'},                         "InDesign - Templates & Layouts",    85),
    ({'.svg'},                                   "Vectors & SVG",                     75),
    ({'.eps'},                                   "Illustrator - Vectors & Assets",    75),
]

def classify_by_extensions(folder_path: str) -> tuple:
    """Level 1: Classify folder by dominant file extension pattern.
    Returns (category, confidence, method_detail) or (None, 0, '')."""
    ext_counts = Counter()
    total_project_files = 0

    try:
        for root, dirs, files in os.walk(folder_path):
            rel = os.path.relpath(root, folder_path)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            if depth > 3: dirs.clear(); continue  # Cap traversal depth
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext and ext not in {'.txt', '.html', '.htm', '.url', '.ini', '.log',
                                        '.md', '.json', '.xml', '.csv', '.rtf', '.nfo',
                                        '.ds_store', '.zip', '.rar', '.7z'}:
                    ext_counts[ext] += 1
                    total_project_files += 1
    except (PermissionError, OSError):
        return (None, 0, '')

    if total_project_files == 0:
        return (None, 0, '')

    best = (None, 0, '')

    for ext_set, category, base_conf in EXTENSION_CATEGORY_MAP:
        matching = sum(ext_counts.get(e, 0) for e in ext_set)
        if matching == 0:
            continue

        ratio = matching / total_project_files

        # Confidence scales with how dominant the extension type is
        if ratio >= 0.7:
            conf = base_conf
        elif ratio >= 0.4:
            conf = base_conf - 10
        elif ratio >= 0.15:
            conf = base_conf - 20
        elif matching >= 2:
            conf = base_conf - 30
        else:
            continue

        # Bonus for higher absolute count (more files = more certain)
        if matching >= 10:
            conf = min(conf + 5, 100)

        ext_list = ', '.join(f"{e}({ext_counts[e]})" for e in ext_set if ext_counts.get(e, 0) > 0)
        if conf > best[1]:
            best = (category, conf, f"ext:{ext_list} ({ratio:.0%} of {total_project_files} files)")

    return best



# ── Level 1.5: Folder content structure analysis ─────────────────────────────
# Uses file composition patterns to infer asset type when extensions alone are mixed.

def analyze_folder_composition(folder_path: str) -> dict:
    """Analyze file composition of a folder for classification signals.
    Returns dict with extension counts, dominant types, and structural indicators."""
    ext_counts = Counter()
    subfolder_names = []
    total_size = 0
    file_count = 0

    try:
        for root, dirs, files in os.walk(folder_path):
            rel = os.path.relpath(root, folder_path)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            if depth == 0:
                subfolder_names = [d.lower() for d in dirs]
            if depth > 3:
                dirs.clear(); continue
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext:
                    ext_counts[ext] += 1
                    file_count += 1
                    try:
                        total_size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
    except (PermissionError, OSError):
        pass

    return {
        'ext_counts': dict(ext_counts),
        'subfolder_names': subfolder_names,
        'total_size': total_size,
        'file_count': file_count,
        'has_footage': any(d in subfolder_names for d in ['footage', 'video', 'media', 'clips']),
        'has_audio': any(d in subfolder_names for d in ['audio', 'music', 'sound', 'sfx']),
        'has_preview': any(d in subfolder_names for d in ['preview', 'previews', 'thumbnail', 'thumbnails']),
    }



# ── Level 4: Folder composition heuristics ───────────────────────────────────
# Uses structural patterns (subfolder names + extension mixtures) for classification.

# Composition patterns: (condition_fn, category, base_confidence, description)
def _classify_by_composition(comp: dict) -> tuple:
    """Classify based on folder composition analysis.
    Returns (category, confidence, detail) or (None, 0, '')."""
    ext = comp.get('ext_counts', {})
    subs = comp.get('subfolder_names', [])
    total = comp.get('file_count', 0)

    if total == 0:
        return (None, 0, '')

    # Count file types by category
    video_exts = sum(ext.get(e, 0) for e in ['.mp4', '.mov', '.avi', '.wmv', '.mkv', '.webm'])
    audio_exts = sum(ext.get(e, 0) for e in ['.mp3', '.wav', '.flac', '.aif', '.ogg', '.aac'])
    image_exts = sum(ext.get(e, 0) for e in ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.gif', '.webp'])
    vector_exts = sum(ext.get(e, 0) for e in ['.svg', '.eps', '.ai'])
    font_exts = sum(ext.get(e, 0) for e in ['.ttf', '.otf', '.woff', '.woff2'])
    doc_exts = sum(ext.get(e, 0) for e in ['.pdf', '.pptx', '.docx', '.xlsx', '.indd', '.idml'])

    # ── Subfolder structure heuristics ──

    # AEP + Footage subfolder = After Effects Template with footage
    if ext.get('.aep', 0) >= 1 and comp.get('has_footage'):
        return ('After Effects - Templates', 72, f"composition:.aep+/footage/ subfolder")

    # AEP + Audio subfolder = likely a full template pack
    if ext.get('.aep', 0) >= 1 and comp.get('has_audio'):
        return ('After Effects - Templates', 68, f"composition:.aep+/audio/ subfolder")

    # Multiple video files without project files = stock footage
    if video_exts >= 5 and video_exts / total >= 0.5:
        return ('Stock Footage - General', 75, f"composition:{video_exts} video files ({video_exts/total:.0%})")

    # Multiple audio files = music/sound pack
    if audio_exts >= 5 and audio_exts / total >= 0.5:
        return ('Stock Music & Audio', 75, f"composition:{audio_exts} audio files ({audio_exts/total:.0%})")

    # Photo-heavy folder (lots of JPGs/PNGs, few other types)
    if image_exts >= 10 and image_exts / total >= 0.7:
        return ('Stock Photos - General', 65, f"composition:{image_exts} images ({image_exts/total:.0%})")

    # Vector-heavy folder
    if vector_exts >= 3 and vector_exts / total >= 0.3:
        return ('Vectors & SVG', 65, f"composition:{vector_exts} vectors ({vector_exts/total:.0%})")

    # Font-heavy (lower threshold than Level 1 since this is fallback)
    if font_exts >= 2 and font_exts / total >= 0.3:
        return ('Fonts & Typography', 65, f"composition:{font_exts} font files ({font_exts/total:.0%})")

    # Document templates
    if doc_exts >= 2 and doc_exts / total >= 0.3:
        if ext.get('.pptx', 0) >= 1:
            return ('Presentations & PowerPoint', 60, f"composition:{doc_exts} docs (pptx found)")
        if ext.get('.indd', 0) >= 1 or ext.get('.idml', 0) >= 1:
            return ('InDesign - Templates & Layouts', 65, f"composition:InDesign files found")
        return ('Forms & Documents', 55, f"composition:{doc_exts} document files")

    # Texture/pattern folder: many identically-sized images, no project files
    if image_exts >= 8 and not any(ext.get(e, 0) for e in ['.aep', '.psd', '.prproj', '.ai']):
        return ('Backgrounds & Textures', 55, f"composition:{image_exts} images, no project files")

    return (None, 0, '')



# ── Scan file-type filter sets ────────────────────────────────────────────────
_FILTER_IMAGE_EXTS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp',
    '.heic', '.heif', '.avif', '.svg', '.ico', '.jfif', '.jpe',
    '.raw', '.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.rw2',
    '.pef', '.srw', '.raf', '.3fr', '.dcr', '.kdc', '.mrw', '.nrw',
    '.psd', '.psb', '.xcf', '.ai', '.eps',
}
_FILTER_VIDEO_EXTS = {
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v',
    '.mpg', '.mpeg', '.3gp', '.ogv', '.ts', '.vob', '.mts', '.m2ts',
}
_FILTER_AUDIO_EXTS = {
    '.mp3', '.flac', '.wav', '.aac', '.ogg', '.wma', '.m4a', '.opus',
    '.aiff', '.aif', '.alac', '.ape', '.mid', '.midi',
}
_FILTER_DOCUMENT_EXTS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.odt', '.ods', '.odp', '.rtf', '.txt', '.csv', '.tsv',
    '.epub', '.mobi', '.djvu', '.pages', '.numbers', '.key',
}
_SCAN_FILTERS = {
    'All Files': None,
    'Images Only': _FILTER_IMAGE_EXTS,
    'Videos Only': _FILTER_VIDEO_EXTS,
    'Audio Only': _FILTER_AUDIO_EXTS,
    'Documents Only': _FILTER_DOCUMENT_EXTS,
}

def find_near_duplicates(folder_path: str, threshold: int = 10, log_cb=None) -> list:
    """Scan a folder for near-duplicate images using perceptual hashing.
    Returns list of (file1, file2, distance) tuples for pairs below threshold.
    Threshold of 10 catches visually similar images (0 = identical, 64 = max different)."""
    hashes = {}  # {filepath: phash_string}

    try:
        for root, dirs, files in os.walk(folder_path):
            for f in files:
                if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                    fpath = os.path.join(root, f)
                    ph = _compute_phash(fpath)
                    if ph:
                        hashes[fpath] = ph
    except (PermissionError, OSError):
        pass

    if log_cb:
        log_cb(f"  Perceptual hashed {len(hashes)} images")

    # Compare all pairs (O(n^2) but fine for typical folder sizes)
    duplicates = []
    paths = list(hashes.keys())
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            dist = _hamming_distance(hashes[paths[i]], hashes[paths[j]])
            if dist <= threshold:
                duplicates.append((paths[i], paths[j], dist))

    return sorted(duplicates, key=lambda x: x[2])



# ── Level 2 Enhancement: Fuzzy keyword matching ──────────────────────────────

def fuzzy_match_categories(name: str, threshold: int = 75) -> tuple:
    """Use rapidfuzz to find best fuzzy match against all category keywords.
    Returns (category, confidence, match_detail) or (None, 0, '')."""
    if not HAS_RAPIDFUZZ:
        return (None, 0, '')

    norm = _normalize(name)
    if len(norm) < 5:  # Need meaningful input for fuzzy matching
        return (None, 0, '')

    best_cat = None
    best_score = 0
    best_detail = ''

    for cat_name, keywords in get_all_categories():
        # Check against category name itself
        cat_norm = _normalize(cat_name)
        ratio = _rfuzz.token_sort_ratio(norm, cat_norm)
        if ratio > best_score and ratio >= threshold:
            best_score = ratio
            best_cat = cat_name
            best_detail = f"fuzzy:cat_name({ratio:.0f}%)"

        # Check against each keyword (only multi-word keywords to avoid short word collisions)
        for kw in keywords:
            kw_norm = _normalize(kw)
            if len(kw_norm) < 5:  # Skip short keywords - too many false positives
                continue
            ratio = _rfuzz.token_sort_ratio(norm, kw_norm)
            if ratio > best_score and ratio >= threshold:
                best_score = ratio
                best_cat = cat_name
                best_detail = f"fuzzy:\"{kw}\"({ratio:.0f}%)"

            # Partial ratio for longer folder names - higher threshold, heavier discount
            if len(norm) > len(kw_norm) + 5 and len(kw_norm) >= 8:
                partial = _rfuzz.partial_ratio(kw_norm, norm)
                adj_score = partial * 0.7  # Heavy discount for partial matches
                if adj_score > best_score and adj_score >= threshold:
                    best_score = adj_score
                    best_cat = cat_name
                    best_detail = f"fuzzy_partial:\"{kw}\"({partial:.0f}%)"

    # Convert rapidfuzz score (0-100) to our confidence scale
    if best_cat:
        # Fuzzy matches are inherently less certain than exact matches
        confidence = min(best_score * 0.7, CONF_FUZZY_CAP)  # Cap for fuzzy matches
        return (best_cat, confidence, best_detail)

    return (None, 0, '')


# ══════════════════════════════════════════════════════════════════════════════
# OLLAMA LLM INTEGRATION (v4.0)
# Optional local LLM for intelligent folder classification and renaming.
# Requires Ollama running locally (https://ollama.com)
# ══════════════════════════════════════════════════════════════════════════════

_OLLAMA_SETTINGS_FILE = os.path.join(_APP_DATA_DIR, 'ollama_settings.json')

_OLLAMA_DEFAULTS = {
    'url': 'http://localhost:11434',
    'model': 'qwen3.5:9b',
    'enabled': True,
    'timeout': 120,
    'temperature': 0.1,
    'num_predict': 4096,
    'think': False,
    'batch_size': 3,
    'vision_enabled': True,
    'vision_max_file_mb': 20,
    'vision_max_pixels': 1024,
    'content_extraction': True,
    'content_max_chars': 800,
    'convert_heic_to_jpg': True,
    'convert_webp_to_jpg': True,
}


def scan_filenames_for_asset_clues(folder_path: str) -> dict:
    """Scan filenames inside a folder for asset-type keywords.
    Returns dict with detected asset type, design file count, and filename hints."""
    result = {
        'asset_type': None, 'asset_confidence': 0, 'asset_detail': '',
        'design_file_count': 0, 'video_template_count': 0,
        'has_design_files': False, 'has_video_templates': False,
        'filename_hints': []
    }

    design_count = 0
    video_count = 0
    all_filenames = []

    try:
        for root, dirs, files in os.walk(folder_path):
            rel = os.path.relpath(root, folder_path)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            if depth > 3:
                dirs.clear(); continue
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in DESIGN_TEMPLATE_EXTS:
                    design_count += 1
                if ext in VIDEO_TEMPLATE_EXTS:
                    video_count += 1
                # Collect filenames for keyword analysis (clean them for matching)
                name_clean = os.path.splitext(f)[0].lower()
                name_clean = name_clean.replace('-', ' ').replace('_', ' ').replace('.', ' ')
                name_clean = re.sub(r'\s+', ' ', name_clean).strip()
                if len(name_clean) > 2:
                    all_filenames.append(name_clean)
    except (PermissionError, OSError):
        pass

    result['design_file_count'] = design_count
    result['video_template_count'] = video_count
    result['has_design_files'] = design_count > 0
    result['has_video_templates'] = video_count > 0

    if not all_filenames:
        return result

    # Also add subfolder names as search candidates (they often contain asset type hints)
    try:
        for d in os.listdir(folder_path):
            if os.path.isdir(os.path.join(folder_path, d)):
                d_clean = d.lower().replace('-', ' ').replace('_', ' ')
                all_filenames.append(d_clean)
    except (PermissionError, OSError):
        pass

    # Combine all filenames into one search corpus
    combined = ' | '.join(all_filenames)

    best_cat = None
    best_priority = 0
    best_keyword = ''

    for keywords, category, priority in FILENAME_ASSET_MAP:
        for kw in keywords:
            if kw in combined:
                if priority > best_priority:
                    best_cat = category
                    best_priority = priority
                    best_keyword = kw
                result['filename_hints'].append((kw, category))
                break  # Found one keyword in this set, move to next

    if best_cat:
        result['asset_type'] = best_cat
        result['asset_confidence'] = best_priority
        result['asset_detail'] = f"filename:\"{best_keyword}\"→{best_cat}"

    return result


def infer_asset_type(initial_category: str, initial_confidence: float,
                     folder_path: str, folder_name: str, log_cb=None) -> tuple:
    """Context-aware post-processing: when a TOPIC category is detected alongside
    design template files, infer the actual asset type.

    Example: "Night Club" (topic: Club & DJ) + PSD files → "Flyers & Print"

    Also handles generic design categories like "Photoshop - Templates & Composites"
    by checking filenames for more specific asset type clues.

    Returns (category, confidence, method, detail) or (None, 0, '', '') if no override."""

    should_check = (initial_category in TOPIC_CATEGORIES or
                    initial_category in _GENERIC_DESIGN_CATEGORIES)

    if not should_check:
        return (None, 0, '', '')

    # Scan filenames for explicit asset type clues
    clues = scan_filenames_for_asset_clues(folder_path)

    # If video template files dominate, don't override — these are AE/Premiere templates
    if clues['has_video_templates'] and clues['video_template_count'] >= clues['design_file_count']:
        return (None, 0, '', '')

    if not clues['has_design_files']:
        # No design files → this is probably genuinely a topic-based asset bundle
        # (e.g., a Christmas photo pack, stock footage collection)
        return (None, 0, '', '')

    # ── Priority 1: Filenames explicitly name the asset type ──
    if clues['asset_type']:
        conf = min(clues['asset_confidence'], 92)
        detail = f"context:{initial_category}+{clues['asset_detail']}"
        if log_cb:
            log_cb(f"    Context: {initial_category} + filename \"{clues['asset_detail'].split('\"')[1]}\" → {clues['asset_type']}")
        return (clues['asset_type'], conf, 'context', detail)

    # ── Priority 2: Folder name itself hints at an asset type ──
    folder_norm = _normalize(folder_name)
    for keywords, category, priority in FILENAME_ASSET_MAP:
        for kw in keywords:
            if kw in folder_norm:
                conf = min(priority - 5, 88)
                detail = f"context:name_hint:\"{kw}\"→{category}"
                if log_cb:
                    log_cb(f"    Context: folder name hint \"{kw}\" + design files → {category}")
                return (category, conf, 'context', detail)

    # ── Priority 3: Default inference for generic design categories ──
    # For "Photoshop - Templates & Composites" with no other clues, keep it as-is
    if initial_category in _GENERIC_DESIGN_CATEGORIES:
        return (None, 0, '', '')

    # ── Priority 4: Default inference for topic categories + design files ──
    # In the marketplace, topic-named PSD/AI folders are overwhelmingly flyers/print templates
    # This is the "Night Club" + PSD → Flyers & Print rule
    conf = 72
    detail = f"context:design({clues['design_file_count']})+topic:{initial_category}→Flyers & Print"
    if log_cb:
        log_cb(f"    Context: {clues['design_file_count']} design files + topic \"{initial_category}\" → Flyers & Print (default)")
    return ('Flyers & Print', conf, 'context', detail)


# ── Tiered Classification Orchestrator ────────────────────────────────────────

# File extensions to exclude from "project file" counts
_NOISE_EXTS = {'.txt', '.html', '.htm', '.url', '.ini', '.log',
               '.md', '.json', '.xml', '.csv', '.rtf', '.nfo',
               '.ds_store', '.zip', '.rar', '.7z'}

def _scan_folder_once(folder_path: str) -> dict:
    """Single-pass folder scan that collects ALL data needed by every classification level.
    Eliminates the 3-4 redundant os.walk() calls per folder.

    Returns dict with:
        ext_counts: Counter of ALL extensions
        project_ext_counts: Counter excluding noise extensions
        total_project_files: int
        subfolder_names: list[str]  (lowercase)
        total_size: int
        file_count: int
        all_filenames_clean: list[str]  (cleaned for keyword matching)
        design_file_count: int
        video_template_count: int
        has_design_files: bool
        has_video_templates: bool
        has_footage/has_audio/has_preview: bool
        project_files: list[tuple[str, str]]  (filepath, ext) for metadata extraction
    """
    ext_counts = Counter()
    project_ext_counts = Counter()
    total_project_files = 0
    subfolder_names = []
    total_size = 0
    file_count = 0
    all_filenames_clean = []
    design_count = 0
    video_count = 0
    project_files = []  # Files to extract metadata from

    try:
        for root, dirs, files in os.walk(folder_path):
            rel = os.path.relpath(root, folder_path)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            if depth == 0:
                subfolder_names = [d.lower() for d in dirs]
            if depth > 3:
                dirs.clear(); continue
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if not ext:
                    continue
                ext_counts[ext] += 1
                file_count += 1
                try:
                    total_size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass

                # Project file counts (exclude noise)
                if ext not in _NOISE_EXTS:
                    project_ext_counts[ext] += 1
                    total_project_files += 1

                # Design/video template tracking
                if ext in DESIGN_TEMPLATE_EXTS:
                    design_count += 1
                if ext in VIDEO_TEMPLATE_EXTS:
                    video_count += 1

                # Collect project files for metadata extraction
                if ext in ('.prproj', '.psd', '.psb', '.aep', '.aet', '.mogrt'):
                    project_files.append((os.path.join(root, f), ext))

                # Collect cleaned filenames for keyword matching
                name_clean = os.path.splitext(f)[0].lower()
                name_clean = name_clean.replace('-', ' ').replace('_', ' ').replace('.', ' ')
                name_clean = re.sub(r'\s+', ' ', name_clean).strip()
                if len(name_clean) > 2:
                    all_filenames_clean.append(name_clean)
    except (PermissionError, OSError):
        pass

    # Also add subfolder names as search candidates
    for d in subfolder_names:
        d_clean = d.replace('-', ' ').replace('_', ' ')
        if len(d_clean) > 2:
            all_filenames_clean.append(d_clean)

    return {
        'ext_counts': ext_counts,
        'project_ext_counts': project_ext_counts,
        'total_project_files': total_project_files,
        'subfolder_names': subfolder_names,
        'total_size': total_size,
        'file_count': file_count,
        'all_filenames_clean': all_filenames_clean,
        'design_file_count': design_count,
        'video_template_count': video_count,
        'has_design_files': design_count > 0,
        'has_video_templates': video_count > 0,
        'has_footage': any(d in subfolder_names for d in ['footage', 'video', 'media', 'clips']),
        'has_audio': any(d in subfolder_names for d in ['audio', 'music', 'sound', 'sfx']),
        'has_preview': any(d in subfolder_names for d in ['preview', 'previews', 'thumbnail', 'thumbnails']),
        'project_files': project_files,
    }


def _classify_ext_from_scan(scan: dict) -> tuple:
    """Level 1 extension classification using pre-scanned data (no os.walk)."""
    ext_counts = scan['project_ext_counts']
    total_project_files = scan['total_project_files']
    if total_project_files == 0:
        return (None, 0, '')

    best = (None, 0, '')
    for ext_set, category, base_conf in EXTENSION_CATEGORY_MAP:
        matching = sum(ext_counts.get(e, 0) for e in ext_set)
        if matching == 0:
            continue
        ratio = matching / total_project_files
        if ratio >= 0.7:     conf = base_conf
        elif ratio >= 0.4:   conf = base_conf - 10
        elif ratio >= 0.15:  conf = base_conf - 20
        elif matching >= 2:  conf = base_conf - 30
        else: continue
        if matching >= 10:
            conf = min(conf + 5, 100)
        ext_list = ', '.join(f"{e}({ext_counts[e]})" for e in ext_set if ext_counts.get(e, 0) > 0)
        if conf > best[1]:
            best = (category, conf, f"ext:{ext_list} ({ratio:.0%} of {total_project_files} files)")
    return best


def _classify_composition_from_scan(scan: dict) -> tuple:
    """Level 4 composition classification using pre-scanned data (no os.walk)."""
    ext = scan['ext_counts']
    total = scan['file_count']
    if total == 0:
        return (None, 0, '')

    video_exts = sum(ext.get(e, 0) for e in ['.mp4', '.mov', '.avi', '.mkv', '.wmv', '.webm', '.m4v'])
    audio_exts = sum(ext.get(e, 0) for e in ['.mp3', '.wav', '.aac', '.flac', '.ogg', '.m4a', '.aif', '.aiff'])
    image_exts = sum(ext.get(e, 0) for e in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp', '.psd', '.psb'])
    vector_exts = sum(ext.get(e, 0) for e in ['.svg', '.eps', '.ai'])
    font_exts = sum(ext.get(e, 0) for e in ['.ttf', '.otf', '.woff', '.woff2'])
    doc_exts = sum(ext.get(e, 0) for e in ['.pdf', '.pptx', '.docx', '.xlsx', '.indd', '.idml'])

    if ext.get('.aep', 0) >= 1 and scan['has_footage']:
        return ('After Effects - Templates', 72, f"composition:.aep+/footage/ subfolder")
    if ext.get('.aep', 0) >= 1 and scan['has_audio']:
        return ('After Effects - Templates', 68, f"composition:.aep+/audio/ subfolder")
    if video_exts >= 5 and video_exts / total >= 0.5:
        return ('Stock Footage - General', 75, f"composition:{video_exts} video files ({video_exts/total:.0%})")
    if audio_exts >= 5 and audio_exts / total >= 0.5:
        return ('Stock Music & Audio', 75, f"composition:{audio_exts} audio files ({audio_exts/total:.0%})")
    if image_exts >= 10 and image_exts / total >= 0.7:
        return ('Stock Photos - General', 65, f"composition:{image_exts} images ({image_exts/total:.0%})")
    if vector_exts >= 3 and vector_exts / total >= 0.3:
        return ('Vectors & SVG', 65, f"composition:{vector_exts} vectors ({vector_exts/total:.0%})")
    if font_exts >= 2 and font_exts / total >= 0.3:
        return ('Fonts & Typography', 65, f"composition:{font_exts} font files ({font_exts/total:.0%})")
    if doc_exts >= 2 and doc_exts / total >= 0.3:
        if ext.get('.pptx', 0) >= 1:
            return ('Presentations & PowerPoint', 60, f"composition:{doc_exts} docs (pptx found)")
        if ext.get('.indd', 0) >= 1 or ext.get('.idml', 0) >= 1:
            return ('InDesign - Templates & Layouts', 65, f"composition:InDesign files found")
        return ('Forms & Documents', 55, f"composition:{doc_exts} document files")
    if image_exts >= 8 and not any(ext.get(e, 0) for e in ['.aep', '.psd', '.prproj', '.ai']):
        return ('Backgrounds & Textures', 55, f"composition:{image_exts} images, no project files")
    return (None, 0, '')


def _asset_clues_from_scan(scan: dict, folder_path: str) -> dict:
    """Asset type clue detection using pre-scanned data (no os.walk)."""
    result = {
        'asset_type': None, 'asset_confidence': 0, 'asset_detail': '',
        'design_file_count': scan['design_file_count'],
        'video_template_count': scan['video_template_count'],
        'has_design_files': scan['has_design_files'],
        'has_video_templates': scan['has_video_templates'],
        'filename_hints': []
    }
    if not scan['all_filenames_clean']:
        return result

    combined = ' | '.join(scan['all_filenames_clean'])
    best_cat = None
    best_priority = 0
    best_keyword = ''

    for keywords, category, priority in FILENAME_ASSET_MAP:
        for kw in keywords:
            if kw in combined:
                if priority > best_priority:
                    best_cat = category
                    best_priority = priority
                    best_keyword = kw
                result['filename_hints'].append((kw, category))
                break
    if best_cat:
        result['asset_type'] = best_cat
        result['asset_confidence'] = best_priority
        result['asset_detail'] = f"filename:\"{best_keyword}\"→{best_cat}"
    return result


def _extract_metadata_from_scan(scan: dict, folder_name: str, log_cb=None) -> dict:
    """Metadata extraction using pre-scanned project file list (no rglob)."""
    metadata = {
        'keywords': [], 'project_names': [],
        'envato_id': detect_envato_item_code(folder_name),
        'primary_app': '',
        'has_aep': False, 'has_prproj': False, 'has_psd': False, 'has_mogrt': False,
    }
    scanned = 0
    max_scan = 10

    for filepath, ext in scan['project_files']:
        if ext in ('.aep', '.aet'):
            metadata['has_aep'] = True
            metadata['primary_app'] = metadata['primary_app'] or 'After Effects'
        elif ext == '.prproj':
            metadata['has_prproj'] = True
            metadata['primary_app'] = metadata['primary_app'] or 'Premiere Pro'
            if scanned < max_scan:
                names = extract_prproj_metadata(filepath)
                metadata['project_names'].extend(names)
                scanned += 1
        elif ext in ('.psd', '.psb'):
            metadata['has_psd'] = True
            metadata['primary_app'] = metadata['primary_app'] or 'Photoshop'
            if scanned < max_scan and HAS_PSD_TOOLS:
                names = extract_psd_metadata(filepath)
                metadata['keywords'].extend(names)
                scanned += 1
        elif ext == '.mogrt':
            metadata['has_mogrt'] = True
            metadata['primary_app'] = metadata['primary_app'] or 'After Effects'
        if scanned >= max_scan:
            break
    return metadata


def _apply_context_from_scan(result: dict, scan: dict, folder_path: str,
                              folder_name: str, log_cb=None) -> dict:
    """Post-processing using pre-scanned data (no os.walk in infer_asset_type)."""
    if not result['category']:
        return result

    initial_category = result['category']
    should_check = (initial_category in TOPIC_CATEGORIES or
                    initial_category in _GENERIC_DESIGN_CATEGORIES)
    if not should_check:
        return result

    clues = _asset_clues_from_scan(scan, folder_path)

    # If video template files dominate, don't override
    if clues['has_video_templates'] and clues['video_template_count'] >= clues['design_file_count']:
        return result
    if not clues['has_design_files']:
        return result

    # Priority 1: Filenames explicitly name the asset type
    if clues['asset_type']:
        conf = min(clues['asset_confidence'], 92)
        detail = f"context:{initial_category}+{clues['asset_detail']}"
        if log_cb:
            log_cb(f"    Context: {initial_category} + filename \"{clues['asset_detail'].split('\"')[1]}\" → {clues['asset_type']}")
        result['topic'] = result['category']
        result['category'] = clues['asset_type']
        result['confidence'] = conf
        result['method'] = 'context'
        result['detail'] = detail
        return result

    # Priority 2: Folder name hints
    folder_norm = _normalize(folder_name)
    for keywords, category, priority in FILENAME_ASSET_MAP:
        for kw in keywords:
            if kw in folder_norm:
                conf = min(priority - 5, 88)
                detail = f"context:name_hint:\"{kw}\"→{category}"
                if log_cb:
                    log_cb(f"    Context: folder name hint \"{kw}\" + design files → {category}")
                result['topic'] = result['category']
                result['category'] = category
                result['confidence'] = conf
                result['method'] = 'context'
                result['detail'] = detail
                return result

    # Priority 3: Generic design categories — keep as-is
    if initial_category in _GENERIC_DESIGN_CATEGORIES:
        return result

    # Priority 4: Default topic + design files → Flyers & Print
    conf = 72
    detail = f"context:design({clues['design_file_count']})+topic:{initial_category}→Flyers & Print"
    if log_cb:
        log_cb(f"    Context: {clues['design_file_count']} design files + topic \"{initial_category}\" → Flyers & Print (default)")
    result['topic'] = result['category']
    result['category'] = 'Flyers & Print'
    result['confidence'] = conf
    result['method'] = 'context'
    result['detail'] = detail
    return result


def tiered_classify(folder_name: str, folder_path: str = None, log_cb=None) -> dict:
    """Run the full tiered classification pipeline on a folder.

    Returns dict:
        category: str or None
        confidence: float 0-100
        cleaned_name: str
        method: str  ('extension', 'keyword', 'fuzzy', 'metadata', 'metadata+keyword', 'context')
        detail: str  (human-readable explanation of how it was classified)
        metadata: dict (extracted metadata if any)
        topic: str or None  (original topic category before context override, if any)
    """
    result = {
        'category': None, 'confidence': 0, 'cleaned_name': folder_name,
        'method': '', 'detail': '', 'metadata': {}, 'topic': None
    }

    # ── Single-pass folder scan: collect ALL data once for all levels ──
    has_folder = folder_path and os.path.isdir(folder_path)
    scan = None
    if has_folder:
        scan = _scan_folder_once(folder_path)

    # ── Level 1: Extension-based classification ──
    if scan:
        ext_cat, ext_conf, ext_detail = _classify_ext_from_scan(scan)
    else:
        ext_cat, ext_conf, ext_detail = (None, 0, '')

    if ext_cat and ext_conf >= 80:
            result.update(category=ext_cat, confidence=ext_conf,
                          method='extension', detail=ext_detail)
            if log_cb:
                log_cb(f"    L1 Extension: {ext_cat} ({ext_conf:.0f}%) [{ext_detail}]")
            if scan:
                return _apply_context_from_scan(result, scan, folder_path, folder_name, log_cb)
            return result

    # Helper: context application using scan data when available
    def _ctx(r):
        if scan:
            return _apply_context_from_scan(r, scan, folder_path, folder_name, log_cb)
        elif has_folder:
            return _apply_context(r, folder_path, folder_name, has_folder, log_cb)
        return r

    # ── Level 2: Keyword matching (primary engine) ──
    cat, conf, cleaned = categorize_folder(folder_name)
    result['cleaned_name'] = cleaned

    if cat and conf >= 65:  # Only short-circuit for high-confidence keyword matches
        result.update(category=cat, confidence=conf, method='keyword',
                      detail=f"keyword:\"{cleaned}\"→{cat}")
        if log_cb:
            log_cb(f"    L2 Keyword: {cat} ({conf:.0f}%)")
        return _ctx(result)

    # Store lower-confidence keyword result as fallback
    keyword_fallback = (cat, conf) if cat else (None, 0)

    # ── Level 2.5: Fuzzy matching (rapidfuzz) ──
    if HAS_RAPIDFUZZ:
        fz_cat, fz_conf, fz_detail = fuzzy_match_categories(cleaned)
        if fz_cat and fz_conf > (keyword_fallback[1] if keyword_fallback[0] else 0):
            result.update(category=fz_cat, confidence=fz_conf, method='fuzzy',
                          detail=fz_detail)
            if log_cb:
                log_cb(f"    L2.5 Fuzzy: {fz_cat} ({fz_conf:.0f}%) [{fz_detail}]")
            return _ctx(result)

    # ── Level 3: Metadata extraction + re-classification ──
    if scan:
        meta = _extract_metadata_from_scan(scan, folder_name, log_cb)
        result['metadata'] = meta

        # Use extracted metadata to attempt classification
        meta_keywords = meta.get('project_names', []) + meta.get('keywords', [])

        if meta_keywords:
            for mk in meta_keywords[:10]:
                m_cat, m_conf, m_cleaned = categorize_folder(mk)
                if m_cat and m_conf >= 40:
                    adj_conf = min(m_conf + 10, 90)
                    result.update(category=m_cat, confidence=adj_conf,
                                  method='metadata+keyword',
                                  detail=f"meta:\"{mk}\"→{m_cat}")
                    if log_cb:
                        log_cb(f"    L3 Metadata: {m_cat} ({adj_conf:.0f}%) from \"{mk}\"")
                    return _ctx(result)

        # Use primary_app detection as last resort from metadata
        if meta.get('primary_app') and not keyword_fallback[0]:
            app = meta['primary_app']
            app_map = {
                'After Effects': 'After Effects - Templates',
                'Premiere Pro': 'Premiere Pro - Templates',
                'Photoshop': 'Photoshop - Templates & Composites',
            }
            if app in app_map:
                result.update(category=app_map[app], confidence=55,
                              method='metadata', detail=f"app_detect:{app}")
                if log_cb:
                    log_cb(f"    L3 App detect: {app_map[app]} (55%) [{app} files found]")
                return _ctx(result)

        # ── Level 3.5: Envato API enrichment ──
        envato_id = meta.get('envato_id', '')
        if envato_id:
            api_cat, api_conf, api_detail = _envato_api_classify(envato_id)
            if api_cat:
                result.update(category=api_cat, confidence=api_conf,
                              method='envato_api', detail=api_detail)
                if log_cb:
                    log_cb(f"    L3.5 Envato API: {api_cat} ({api_conf:.0f}%) [{api_detail}]")
                return _ctx(result)

    # ── Level 4: Folder composition heuristics (uses pre-scanned data) ──
    if scan:
        comp_cat, comp_conf, comp_detail = _classify_composition_from_scan(scan)
        if comp_cat and comp_conf >= 50:
            result.update(category=comp_cat, confidence=comp_conf,
                          method='composition', detail=comp_detail)
            if log_cb:
                log_cb(f"    L4 Composition: {comp_cat} ({comp_conf:.0f}%) [{comp_detail}]")
            return _ctx(result)

    # ── Level 1 low-confidence fallback ──
    if ext_cat and ext_conf >= 50:
        result.update(category=ext_cat, confidence=ext_conf,
                      method='extension', detail=ext_detail)
        if log_cb:
            log_cb(f"    L1 Extension (fallback): {ext_cat} ({ext_conf:.0f}%)")
        return _ctx(result)

    # ── Return best low-confidence result if any ──
    if keyword_fallback[0] and keyword_fallback[1] >= 15:
        result.update(category=keyword_fallback[0], confidence=keyword_fallback[1],
                      method='keyword_low', detail=f"keyword_low:\"{cleaned}\"")
        return _ctx(result)

    return result


def _apply_context(result: dict, folder_path: str, folder_name: str,
                   has_folder: bool, log_cb=None) -> dict:
    """Post-processing: apply context-aware asset type inference.
    If the initial category is a topic or generic design category AND the folder
    contains design template files, override with the inferred asset type."""

    if not has_folder or not result['category']:
        return result

    ctx_cat, ctx_conf, ctx_method, ctx_detail = infer_asset_type(
        result['category'], result['confidence'],
        folder_path, folder_name, log_cb)

    if ctx_cat:
        # Preserve the original topic for subfolder naming
        result['topic'] = result['category']
        result['category'] = ctx_cat
        result['confidence'] = ctx_conf
        result['method'] = ctx_method
        result['detail'] = ctx_detail

    return result


