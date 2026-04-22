"""UniFile — Classification engine: extension, keyword, fuzzy, composition, tiered."""
import os, re, math
from pathlib import Path
from collections import Counter

from unifile.bootstrap import HAS_RAPIDFUZZ
from unifile.archive_inference import aggregate_archive_names
try:
    from rapidfuzz import fuzz as _rfuzz
except ImportError:
    _rfuzz = None

from unifile.bootstrap import HAS_PSD_TOOLS
from unifile.config import CONF_HIGH, CONF_MEDIUM, CONF_FUZZY_CAP, _APP_DATA_DIR
from unifile.metadata import (
    detect_envato_item_code, extract_prproj_metadata,
    extract_psd_metadata, _envato_api_classify,
)
from unifile.cache import (
    check_corrections, cache_lookup, cache_store, _preload_corrections,
    _close_cache_conn, _init_cache_db
)
from unifile.categories import (
    CATEGORIES, BUILTIN_CATEGORIES, get_all_categories, get_all_category_names,
    _CategoryIndex, GENERIC_AEP_NAMES, is_generic_aep, _score_aep,
    TOPIC_CATEGORIES,
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
    ({'.cube', '.3dl'},                          "Color Grading & LUTs",              90),
    ({'.lut'},                                   "Color Grading & LUTs",              88),
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
    # New tool-specific extensions
    ({'.fig'},                                   "Figma - Templates & UI Kits",       90),
    ({'.drp', '.drfx'},                          "DaVinci Resolve - Templates",        88),
    ({'.als'},                                   "Music Production - DAW Projects",   85),
    ({'.flp'},                                   "Music Production - DAW Projects",   85),
    ({'.logicx'},                                "Music Production - DAW Projects",   85),
    ({'.procreate'},                             "Procreate - Brushes & Stamps",      90),
    ({'.nks', '.nksn'},                          "Music Production - Presets",        85),
    ({'.vstpreset', '.fxp', '.fxb'},             "Music Production - Presets",        80),
    ({'.unitypackage'},                          "Game Assets & Sprites",             88),
    ({'.uproject'},                              "Unreal Engine - Assets",            92),
    ({'.uasset'},                                "Unreal Engine - Assets",            88),
    ({'.ase', '.aseprite'},                      "Game Assets & Sprites",             85),
    ({'.nef', '.cr2', '.arw', '.crw', '.orf', '.raf', '.rw2', '.sr2'}, "Photography - RAW Files", 90),
    ({'.dng'},                                   "Photography - RAW Files",           80),
    ({'.safetensors', '.ckpt'},                  "AI Art & Generative",               88),
    ({'.lora'},                                  "AI Art & Generative",               85),
    ({'.capcut'},                                "CapCut - Templates",                88),
    # v8.4.0 additions
    ({'.cdr'},                                   "CorelDRAW - Vectors & Assets",      85),
    ({'.motn'},                                  "Apple Motion - Templates",          90),
    ({'.dxf'},                                   "Cutting Machine - SVG & DXF",       80),
    ({'.dds', '.tga'},                           "3D - Materials & Textures",         80),
    ({'.hdr'},                                   "3D - Materials & Textures",         82),
    ({'.fon'},                                   "Fonts & Typography",                88),
    ({'.ait'},                                   "Illustrator - Vectors & Assets",    85),
    ({'.pub'},                                   "Flyers & Print",                    72),
    # v8.6.0 additions
    ({'.sketch'},                                "Sketch - UI Resources",             90),
    ({'.xd'},                                    "Adobe XD - Templates",              90),
    ({'.afdesign'},                              "Affinity - Designer Files",         88),
    ({'.afphoto'},                               "Affinity - Photo Edits",            85),
    ({'.afpub'},                                 "Affinity - Publisher Layouts",      88),
    ({'.kra'},                                   "Clipart & Illustrations",           78),
    ({'.clip'},                                  "Clipart & Illustrations",           80),
    # v8.7.0 additions
    ({'.rpp'},                                   "Music Production - DAW Projects",   85),
    ({'.band', '.bandproject'},                  "Music Production - DAW Projects",   83),
    ({'.fcpbundle', '.fcpxml'},                  "Final Cut Pro - Templates",         90),
    ({'.aco'},                                   "Photoshop - Gradients & Swatches",  88),
    ({'.brushset'},                              "Procreate - Brushes & Stamps",      88),
    ({'.hip', '.hiplc', '.hipnc'},               "3D",                                85),
    ({'.ma', '.mb'},                             "3D",                                82),
    ({'.max'},                                   "3D",                                82),
    ({'.stl', '.3mf'},                           "3D Printing - STL Files",           85),
    # v8.8.0 additions
    ({'.glb', '.gltf'},                          "3D - Models & Objects",             82),
    ({'.otc', '.ttc'},                           "Fonts & Typography",                90),
    ({'.lottie'},                                "Animated Icons",                    85),
    ({'.bmpr'},                                  "UI & UX Design",                    88),
    ({'.rp', '.rplib'},                          "UI & UX Design",                    87),
    ({'.vsdx', '.vsd'},                          "Forms & Documents",                 80),
    ({'.sla', '.slaz'},                          "Flyers & Print",                    82),
    ({'.pxm', '.pxd'},                           "Clipart & Illustrations",           80),
    ({'.splinecode'},                            "UI & UX Design",                    82),
    # v8.9.0 additions
    ({'.cr3'},                                   "Photography - RAW Files",           90),
    ({'.exr'},                                   "3D - Materials & Textures",         82),
    ({'.sbs', '.sbsar'},                         "3D - Materials & Textures",         85),
    ({'.ztl'},                                   "3D",                                82),
    ({'.usd', '.usda', '.usdc', '.usdz'},        "3D - Models & Objects",             80),
    ({'.sf2', '.sfz'},                           "Music Production - Presets",        82),
    ({'.nki', '.nkx', '.nkc'},                   "Music Production - Presets",        85),
    ({'.ptx'},                                   "Music Production - DAW Projects",   83),
    ({'.cpr'},                                   "Music Production - DAW Projects",   83),
    ({'.xcf'},                                   "Clipart & Illustrations",           78),
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
            # Avoid backslashes/quote-reuse inside f-string expression (not allowed on Python 3.10/3.11)
            _fn_hint = clues['asset_detail'].split('"')[1] if '"' in clues['asset_detail'] else clues['asset_detail']
            log_cb(f'    Context: {initial_category} + filename "{_fn_hint}" → {clues["asset_type"]}')
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

# Design/video template extensions used in single-pass folder scan
DESIGN_TEMPLATE_EXTS = {
    '.psd', '.psb', '.ai', '.indd', '.idml', '.eps', '.fig',
    '.afdesign', '.afphoto', '.afpub', '.sketch', '.xd', '.kra', '.clip',
    '.fcpbundle', '.fcpxml',
}
VIDEO_TEMPLATE_EXTS = {
    '.aep', '.aet', '.prproj', '.mogrt', '.drp', '.drfx',
}

# Keyword→category map for filename/foldername-based asset-type inference.
# Each entry: ([keywords…], category, priority).  Higher priority wins on conflict.
FILENAME_ASSET_MAP = [
    # Print & flyer design
    (["flyer", "flyerfree", "flyer template"], "Flyers & Print", 80),
    (["brochure", "trifold", "tri-fold", "bifold", "bi-fold"], "Flyers & Print", 80),
    (["poster", "postertemplate", "a4 poster", "a3 poster"], "Flyers & Print", 80),
    (["business card", "businesscard", "visiting card", "namecard"], "Business Cards", 85),
    (["invoice", "receipt", "quotation", "letterhead", "stationary", "stationery"], "Flyers & Print", 75),
    (["resume", "cv template", "curriculum vitae", "resume template"], "Resume & CV", 85),
    (["menu", "restaurant menu", "food menu", "cafe menu"], "Menu Design", 82),
    # Social media
    (["instagram", "instagram post", "instagram story", "ig post", "ig story", "ig template"], "Social Media", 88),
    (["facebook", "fb post", "fb cover", "facebook cover", "facebook banner"], "Social Media", 88),
    (["twitter", "tweet", "twitter post", "twitter banner", "x post"], "Social Media", 85),
    (["youtube thumbnail", "yt thumbnail", "youtube banner", "channel art"], "YouTube & Video Platform", 88),
    (["twitch", "stream overlay", "stream alert", "obs overlay", "gaming overlay"], "Twitch & Streaming", 88),
    (["social media", "social pack", "social template", "social post"], "Social Media", 82),
    (["story template", "stories template", "instagram stories"], "Social Media", 85),
    # Mockups (specific before generic)
    (["device mockup", "phone mockup", "iphone mockup", "android mockup", "screen mockup", "laptop mockup", "monitor mockup"], "Mockups - Devices", 92),
    (["tshirt mockup", "t-shirt mockup", "shirt mockup", "hoodie mockup", "apparel mockup"], "Mockups - Apparel", 92),
    (["packaging mockup", "box mockup", "bottle mockup", "bag mockup", "mug mockup"], "Mockups - Packaging", 92),
    (["branding mockup", "stationery mockup", "identity mockup", "logo mockup"], "Mockups - Branding", 92),
    (["mockup", "mock-up", "mock up", "psd mockup"], "Photoshop - Mockups", 88),
    # UI/UX
    (["ui kit", "ui template", "app design", "wireframe", "dashboard template", "mobile ui", "web ui", "design system"], "UI & UX Design", 85),
    (["figma ui", "figma kit", "figma component", "sketch ui"], "UI & UX Design", 87),
    # Logo & Branding
    (["logo template", "logo pack", "logo design", "logotype", "logo kit", "logo bundle"], "Logo & Identity", 88),
    (["brand identity", "brand guidelines", "brand board", "brand kit", "branding pack"], "Logo & Identity", 87),
    # Presentation
    (["presentation", "powerpoint", "keynote", "google slides", "pptx template", "pitch deck", "slideshow template"], "Presentations & PowerPoint", 88),
    # Infographic
    (["infographic", "infographics", "chart template", "data visualization"], "Infographic", 85),
    # Web
    (["web template", "website template", "html template", "landing page", "web design", "homepage design"], "Website Design", 85),
    # Email
    (["email template", "newsletter template", "email design", "html email", "mailchimp"], "Email & Newsletter", 87),
    # Photo frames / overlay
    (["photo frame", "frame template", "photo overlay", "image overlay"], "Overlays & Effects", 75),
    (["overlay", "light leak", "film grain", "lens flare overlay", "bokeh overlay"], "Overlays & Effects", 78),
    # Procreate
    (["procreate brush", "procreate stamp", "procreate texture", "procreate swatches", "procreate palette"], "Procreate - Brushes & Stamps", 88),
    # Game assets
    (["sprite sheet", "game asset", "pixel art", "tileset", "tilemap", "game ui"], "Game Assets & Sprites", 87),
    # Music production
    (["serum preset", "serum bank", "sylenth preset", "massive preset", "wavetable preset", "synth preset"], "Music Production - Presets", 87),
    (["ableton project", "fl studio project", "logic project", "daw template", "session file"], "Music Production - DAW Projects", 87),
    # Photography
    (["raw photo", "raw files", "camera raw", "nef", "cr2", "arw", "raw pack"], "Photography - RAW Files", 82),
    # Calendars & planners
    (["calendar template", "planner template", "daily planner", "weekly planner", "yearly planner", "monthly planner", "wall calendar", "desk calendar", "editorial calendar"], "Calendar", 85),
    # General
    (["icon pack", "icon set", "icon bundle", "web icons", "app icons"], "Icons & Symbols", 87),
    (["pattern design", "seamless pattern", "repeat pattern", "surface pattern"], "Patterns - Seamless", 82),
    (["watercolor", "watercolour", "hand drawn", "hand lettered", "sketch illustration"], "Clipart & Illustrations", 75),
    (["certificate", "diploma", "award template", "award certificate"], "Certificate", 85),
    (["banner", "web banner", "display banner", "ad banner", "leaderboard banner"], "Banners", 80),
    (["voucher", "coupon", "gift card", "gift voucher"], "Gift Voucher & Coupon", 82),
    (["wedding", "wedding invitation", "wedding card", "wedding template", "save the date"], "Wedding", 85),
    # Design apps
    (["sketch app", "sketch ui", "sketch kit", "sketch template", "sketch resource", "sketch file"], "Sketch - UI Resources", 88),
    (["adobe xd", "xd template", "xd kit", "xd resource", "xd wireframe", "xd file"], "Adobe XD - Templates", 88),
    (["affinity designer", "affinity vector", "afdesign"], "Affinity - Designer Files", 85),
    (["affinity photo", "afphoto"], "Affinity - Photo Edits", 85),
    (["affinity publisher", "afpub", "affinity layout"], "Affinity - Publisher Layouts", 85),
    # Craft / cutting machines
    (["cricut file", "cricut svg", "cricut bundle", "cricut design", "cutting file", "svg cut file", "vinyl cut"], "Cutting Machine - SVG & DXF", 88),
    (["sublimation design", "sublimation file", "htv design", "heat transfer vinyl"], "Cutting Machine - SVG & DXF", 82),
    # E-commerce / web platforms
    (["shopify theme", "shopify template", "woocommerce theme", "woo theme", "ecommerce theme", "ecommerce template"], "Website Design", 87),
    # Sample packs / music production
    (["sample pack", "loop pack", "one shot pack", "drum kit", "drum samples", "splice sample", "loopmasters"], "Stock Music & Audio", 80),
    (["midi pack", "midi files", "midi kit"], "Music Production - DAW Projects", 80),
    # v8.7.0 additions
    (["canva template", "canva design", "canva graphic", "canva social", "canva presentation", "canva flyer", "canva resume", "canva story", "canva post", "canva bundle", "canva kit"], "Canva - Templates", 88),
    (["final cut", "fcpx template", "final cut template", "fcpx effect", "final cut effect", "fcpx transition", "final cut title", "fcpx plugin", "final cut generator", "fcp template"], "Final Cut Pro - Templates", 88),
    (["3d print", "3d printing", "stl file", "stl model", "fdm print", "resin print", "tabletop miniature", "miniature stl", "print in place", "functional print"], "3D Printing - STL Files", 85),
    (["filmora", "filmora template", "filmora effect", "filmora title", "filmora transition"], "After Effects - Templates", 80),
    (["pond5", "storyblocks", "videoblocks", "epidemic sound", "artlist music", "musicbed"], "Stock Music & Audio", 78),
    (["looperman", "splice sample", "zapsplat", "soundsnap", "freesound"], "Sound Effects & SFX", 78),
    (["aejuice", "motionbro", "mixkit", "envato elements"], "After Effects - Templates", 78),
    # v8.8.0 additions
    (["motion array", "motionarray"], "After Effects - Templates", 78),
    (["envato elements", "envatoelements"], "After Effects - Templates", 75),
    (["shutterstock", "shutter stock"], "Stock Photos - General", 78),
    (["getty images", "gettyimages", "istock", "istockphoto"], "Stock Photos - General", 78),
    (["ui8 kit", "ui8 template", "ui8 resource", "ui8 component"], "UI & UX Design", 87),
    (["iconscout icon", "craftwork icon", "flaticon", "iconfinder icon"], "Icons & Symbols", 85),
    (["lottie animation", "lottie file", "bodymovin", "lottie icon", "lottie json"], "Animated Icons", 82),
    (["balsamiq", "bmpr file", "balsamiq mockup"], "UI & UX Design", 85),
    (["axure rp", "axure wireframe", "rplib file"], "UI & UX Design", 85),
    (["visio diagram", "vsdx file", "microsoft visio", "visio template", "flowchart visio"], "Forms & Documents", 80),
    (["scribus", "scribus layout", "sla file"], "Flyers & Print", 80),
    (["spline 3d", "spline design", "splinecode"], "UI & UX Design", 82),
    (["gltf file", "glb file", "webgl model", "gltf model", "3d gltf"], "3D - Models & Objects", 82),
    (["artstation brush", "artstation texture", "artstation model", "artstation asset"], "3D - Materials & Textures", 80),
    (["gumroad font", "gumroad brush", "gumroad svg", "gumroad action"], "Clipart & Illustrations", 73),
    (["premier pro preset", "premiere mogrt", "premiere transition pack", "mogrt template"], "Premiere Pro - Templates", 88),
    (["handy seamless", "handy seamless transitions"], "Premiere Pro - Transitions", 90),
    # v8.9.0 additions
    (["turbosquid", "turbo squid"], "3D - Models & Objects", 82),
    (["cgtrader", "cg trader"], "3D - Models & Objects", 80),
    (["sketchfab model", "sketchfab 3d", "sketchfab scene"], "3D - Models & Objects", 80),
    (["kitbash3d", "kitbash kit", "kitbash pack", "kitbash bundle"], "3D - Models & Objects", 85),
    (["poly haven", "polyhaven", "hdri haven", "hdrihaven", "ambientcg", "ambient cg"], "3D - Materials & Textures", 85),
    (["substance designer material", "substance painter material", "sbsar material", "substance texture pack"], "3D - Materials & Textures", 87),
    (["daz3d", "daz studio", "daz figure", "poser figure", "renderosity"], "3D", 78),
    (["civitai model", "civitai lora", "civitai checkpoint", "civitai merge"], "AI Art & Generative", 87),
    (["itch.io asset", "itchio asset", "itch io pack", "itchio pack"], "Game Assets & Sprites", 82),
    (["opengameart", "open game art", "kenney assets", "kenney pack"], "Game Assets & Sprites", 82),
    (["loopmasters sample", "loopmasters pack", "loopmasters kit"], "Stock Music & Audio", 83),
    (["native instruments library", "kontakt library pack", "ni komplete", "spitfire audio"], "Music Production - Presets", 85),
]

# Categories that, when detected as "topic" and design files are also present,
# should trigger context-based re-inference of the actual asset type.
_GENERIC_DESIGN_CATEGORIES = {
    'Photoshop - Templates & Composites',
    'Illustrator - Vectors & Assets',
    'InDesign - Templates & Layouts',
    'Figma - Templates & UI Kits',
}

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
    archive_stems = []  # Stems of archive files for name-based inference

    _ARCHIVE_EXTS = {'.zip', '.rar', '.7z', '.tgz', '.tar', '.gz', '.bz2'}

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

                # Archive stems — collected for name-based inference
                if ext in _ARCHIVE_EXTS:
                    stem = os.path.splitext(f)[0]
                    archive_stems.append(stem)

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

    # Add archive stems to all_filenames_clean so keyword matching sees them too
    for stem in archive_stems:
        stem_clean = stem.lower().replace('-', ' ').replace('_', ' ').replace('.', ' ')
        stem_clean = re.sub(r'\s+', ' ', stem_clean).strip()
        if len(stem_clean) > 2 and stem_clean not in all_filenames_clean:
            all_filenames_clean.append(stem_clean)

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
        'archive_stems': archive_stems,
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
    font_exts = sum(ext.get(e, 0) for e in ['.ttf', '.otf', '.woff', '.woff2', '.otc', '.ttc'])
    doc_exts = sum(ext.get(e, 0) for e in ['.pdf', '.pptx', '.docx', '.xlsx', '.indd', '.idml'])
    raw_exts = sum(ext.get(e, 0) for e in ['.nef', '.cr2', '.cr3', '.arw', '.crw', '.orf', '.raf', '.rw2', '.sr2', '.dng'])
    daw_exts = sum(ext.get(e, 0) for e in ['.als', '.flp', '.logicx', '.ptx', '.cpr', '.rpp'])
    midi_exts = sum(ext.get(e, 0) for e in ['.mid', '.midi'])
    lr_exts = sum(ext.get(e, 0) for e in ['.lrtemplate', '.xmp'])
    archive_exts = sum(ext.get(e, 0) for e in ['.zip', '.rar', '.7z', '.tgz'])
    lut_exts = sum(ext.get(e, 0) for e in ['.cube', '.3dl', '.lut'])
    stl_exts = sum(ext.get(e, 0) for e in ['.stl', '.3mf'])
    gltf_exts = sum(ext.get(e, 0) for e in ['.glb', '.gltf'])
    lottie_exts = ext.get('.lottie', 0)
    usd_exts = sum(ext.get(e, 0) for e in ['.usd', '.usda', '.usdc', '.usdz'])
    sbs_exts = sum(ext.get(e, 0) for e in ['.sbs', '.sbsar'])
    exr_exts = ext.get('.exr', 0)
    png_count = ext.get('.png', 0)
    svg_count = ext.get('.svg', 0)
    jpg_count = ext.get('.jpg', 0) + ext.get('.jpeg', 0)
    subs = scan.get('subfolder_names', [])

    # ── Archive-heavy folders: use archive name inference ─────────────────
    archive_stems = scan.get('archive_stems', [])
    if archive_stems and archive_exts >= 2 and (archive_exts >= 5 or (archive_exts / max(total, 1)) >= 0.15):
        arc_cat, arc_conf, arc_detail = aggregate_archive_names(archive_stems)
        if arc_cat and arc_conf >= 65:
            return (arc_cat, arc_conf, arc_detail)

    if ext.get('.aep', 0) >= 1 and scan['has_footage']:
        return ('After Effects - Templates', 72, f"composition:.aep+/footage/ subfolder")
    if ext.get('.aep', 0) >= 1 and scan['has_audio']:
        return ('After Effects - Templates', 68, f"composition:.aep+/audio/ subfolder")
    if video_exts >= 5 and video_exts / total >= 0.5:
        return ('Stock Footage - General', 75, f"composition:{video_exts} video files ({video_exts/total:.0%})")
    if audio_exts >= 5 and audio_exts / total >= 0.5:
        return ('Stock Music & Audio', 75, f"composition:{audio_exts} audio files ({audio_exts/total:.0%})")
    if raw_exts >= 3 and raw_exts / total >= 0.4:
        return ('Photography - RAW Files', 75, f"composition:{raw_exts} RAW files ({raw_exts/total:.0%})")
    # Mixed RAW+JPEG shoot (camera download with both RAW and processed JPEGs)
    if raw_exts >= 2 and jpg_count >= 1 and (raw_exts + jpg_count) / total >= 0.5:
        return ('Photography - RAW Files', 73, f"composition:{raw_exts} RAW + {jpg_count} JPEG ({(raw_exts+jpg_count)/total:.0%})")
    if gltf_exts >= 2 and gltf_exts / total >= 0.4:
        return ('3D - Models & Objects', 78, f"composition:{gltf_exts} GLB/GLTF files ({gltf_exts/total:.0%})")
    if usd_exts >= 2 and usd_exts / total >= 0.3:
        return ('3D - Models & Objects', 76, f"composition:{usd_exts} USD/USDZ files ({usd_exts/total:.0%})")
    if sbs_exts >= 2 and sbs_exts / total >= 0.3:
        return ('3D - Materials & Textures', 78, f"composition:{sbs_exts} Substance material files")
    if exr_exts >= 3 and exr_exts / total >= 0.3:
        return ('3D - Materials & Textures', 72, f"composition:{exr_exts} OpenEXR files ({exr_exts/total:.0%})")
    if lottie_exts >= 2:
        return ('Animated Icons', 72, f"composition:{lottie_exts} Lottie animation files")
    if daw_exts >= 1:
        return ('Music Production - DAW Projects', 80, f"composition:DAW project file found ({daw_exts})")
    if midi_exts >= 2 and not audio_exts:
        return ('Music Production - DAW Projects', 65, f"composition:{midi_exts} MIDI files")
    if lr_exts >= 3:
        return ('Lightroom - Presets & Profiles', 70, f"composition:{lr_exts} LR preset files")
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
        # Icon pack: many small PNG/SVG files, often in /icons/ subfolder
        if (png_count + svg_count) >= 8 and any(s in subs for s in ['icons', 'icon']):
            return ('Icons & Symbols', 68, f"composition:{png_count + svg_count} PNG/SVG in icons/ subfolder")
        # Texture pack: many images in /textures/ subfolder
        if any(s in subs for s in ['textures', 'texture', 'materials', 'material']):
            return ('3D - Materials & Textures', 65, f"composition:{image_exts} images in textures/ subfolder")
        return ('Backgrounds & Textures', 55, f"composition:{image_exts} images, no project files")
    # LUT/color grading packs: predominantly .cube/.3dl/.lut files
    if lut_exts >= 2 and lut_exts / total >= 0.3:
        return ('Color Grading & LUTs', 78, f"composition:{lut_exts} LUT files ({lut_exts/total:.0%})")
    # 3D printing: predominantly STL/3MF files
    if stl_exts >= 2 and stl_exts / total >= 0.4:
        return ('3D Printing - STL Files', 75, f"composition:{stl_exts} STL/3MF files ({stl_exts/total:.0%})")
    # Icon pack: many PNG/SVG without a clear project-file anchor
    if png_count + svg_count >= 20 and (png_count + svg_count) / total >= 0.7:
        return ('Icons & Symbols', 62, f"composition:{png_count + svg_count} PNG/SVG ({(png_count + svg_count)/total:.0%})")
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

    # Archive inference: run before has_design_files gate so archive-heavy topic
    # folders (e.g. "Christmas" full of Videohive ZIPs) get reclassified correctly
    archive_stems = scan.get('archive_stems', [])
    archive_count = sum(scan['ext_counts'].get(e, 0) for e in ['.zip', '.rar', '.7z', '.tgz'])
    if archive_stems and archive_count >= 2:
        arc_cat, arc_conf, arc_detail = aggregate_archive_names(archive_stems)
        if arc_cat and arc_conf >= 68:
            if log_cb:
                log_cb(f"    Context+archive: {initial_category} + {arc_detail} → {arc_cat}")
            result['topic'] = result['category']
            result['category'] = arc_cat
            result['confidence'] = arc_conf
            result['method'] = 'context+archive'
            result['detail'] = f"context:{initial_category}+{arc_detail}"
            return result

    if not clues['has_design_files']:
        return result

    # Priority 1: Filenames explicitly name the asset type
    if clues['asset_type']:
        conf = min(clues['asset_confidence'], 92)
        detail = f"context:{initial_category}+{clues['asset_detail']}"
        if log_cb:
            # Avoid backslashes/quote-reuse inside f-string expression (not allowed on Python 3.10/3.11)
            _fn_hint = clues['asset_detail'].split('"')[1] if '"' in clues['asset_detail'] else clues['asset_detail']
            log_cb(f'    Context: {initial_category} + filename "{_fn_hint}" → {clues["asset_type"]}')
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


def classify_by_content(path: str, categories: list = None) -> tuple:
    """Level 8: Classify by extracting and analyzing file text content.

    Reads text from PDF/DOCX/TXT/MD/CSV files and runs keyword classification.
    Returns (category, confidence, cleaned_name) or (None, 0, cleaned_name).
    """
    from pathlib import Path as _Path
    _path = _Path(path)
    if not _path.is_file():
        return (None, 0, _path.stem)

    suffix = _path.suffix.lower()
    text = ''

    try:
        if suffix in ('.txt', '.md'):
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read(4096)  # First 4KB

        elif suffix == '.csv':
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read(2048)

        elif suffix == '.pdf':
            try:
                from pdfminer.high_level import extract_text as _pdf_extract
                text = _pdf_extract(path, maxpages=2) or ''
                text = text[:4096]
            except ImportError:
                try:
                    from pypdf import PdfReader as _PdfReader
                    reader = _PdfReader(path)
                    pages_text = []
                    for page in reader.pages[:2]:
                        pages_text.append(page.extract_text() or '')
                    text = ' '.join(pages_text)[:4096]
                except (ImportError, Exception):
                    pass

        elif suffix in ('.docx', '.doc'):
            try:
                from docx import Document as _DocxDoc
                doc = _DocxDoc(path)
                paras = [p.text for p in doc.paragraphs[:20]]
                text = ' '.join(paras)[:4096]
            except (ImportError, Exception):
                pass

        elif suffix in ('.pptx', '.ppt'):
            try:
                from pptx import Presentation as _Pptx
                prs = _Pptx(path)
                slide_texts = []
                for slide in list(prs.slides)[:5]:
                    for shape in slide.shapes:
                        if hasattr(shape, 'text'):
                            slide_texts.append(shape.text)
                text = ' '.join(slide_texts)[:4096]
            except (ImportError, Exception):
                pass

        elif suffix in ('.xlsx', '.xls'):
            try:
                from openpyxl import load_workbook as _load_wb
                wb = _load_wb(path, read_only=True, data_only=True)
                ws = wb.active
                cell_texts = []
                for row in ws.iter_rows(max_row=20, values_only=True):
                    for cell in row:
                        if cell and isinstance(cell, str):
                            cell_texts.append(cell)
                text = ' '.join(cell_texts)[:4096]
            except (ImportError, Exception):
                pass

    except Exception:
        pass

    if not text or not text.strip():
        return (None, 0, _path.stem)

    # Use existing keyword classifier on extracted text
    result = categorize_folder(text)
    if result and result[0]:
        # Lower confidence since this is content-based
        return (result[0], min(result[1], 65), _path.stem)

    return (None, 0, _path.stem)


def classify_by_archive(path: str) -> tuple:
    """Level 9: Classify by inspecting archive contents.

    Peeks inside ZIP/TAR archives and classifies based on majority extension.
    Returns (category, confidence, cleaned_name) or (None, 0, cleaned_name).
    """
    import zipfile, tarfile
    from pathlib import Path as _Path
    from collections import Counter as _Counter

    _path = _Path(path)
    suffix = _path.suffix.lower()

    names = []
    try:
        if suffix == '.zip' and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, 'r') as zf:
                names = zf.namelist()[:200]  # Cap at 200 entries

        elif suffix in ('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz', '.tar.xz', '.txz'):
            if tarfile.is_tarfile(path):
                with tarfile.open(path, 'r:*') as tf:
                    names = [m.name for m in tf.getmembers()[:200] if m.isfile()]

        elif suffix == '.gz' and not path.endswith('.tar.gz'):
            import gzip
            try:
                with gzip.open(path, 'rb') as gf:
                    inner = _Path(path).stem
                    names = [inner]
            except Exception:
                pass
    except Exception:
        return (None, 0, _path.stem)

    if not names:
        return (None, 0, _path.stem)

    # Count extensions
    ext_counts = _Counter()
    for name in names:
        ext = _Path(name).suffix.lower()
        if ext:
            ext_counts[ext] += 1

    if not ext_counts:
        return (None, 0, _path.stem)

    # Use EXTENSION_CATEGORY_MAP to find best category
    cat_votes: dict = {}
    for ext, count in ext_counts.items():
        for ext_set, cat, _ in EXTENSION_CATEGORY_MAP:
            if ext in ext_set:
                cat_votes[cat] = cat_votes.get(cat, 0) + count
                break

    if not cat_votes:
        return (None, 0, _path.stem)

    best_cat = max(cat_votes, key=lambda c: cat_votes[c])
    total = sum(ext_counts.values())
    best_count = cat_votes[best_cat]
    confidence = min(70, int(50 + (best_count / total) * 40))

    return (best_cat, confidence, _path.stem)
