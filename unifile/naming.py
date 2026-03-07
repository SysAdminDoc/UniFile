"""UniFile — Name normalization, beautification, and smart naming."""
import os, re, math, unicodedata
from pathlib import Path
from functools import lru_cache

from unifile.bootstrap import HAS_RAPIDFUZZ, HAS_UNIDECODE
try:
    from rapidfuzz import fuzz as _rfuzz
except ImportError:
    _rfuzz = None
try:
    from unidecode import unidecode as _unidecode
except ImportError:
    _unidecode = None

MARKETPLACE_PREFIXES = [
    # Envato ecosystem
    "videohive", "graphicriver", "themeforest", "audiojungle", "photodune",
    "codecanyon", "envato elements", "envato", "envato market",
    # Stock media sites
    "shutterstock", "adobe stock", "istockphoto", "istock", "getty images", "getty",
    "depositphotos", "dreamstime", "123rf", "pond5", "storyblocks", "videoblocks",
    "audioblocks", "artlist", "artgrid", "epidemic sound", "musicbed",
    "motion array", "motionarray", "mixkit",
    "motionelements", "motion elements",
    # Design marketplaces
    "creative market", "creativemarket", "creative fabrica", "creativefabrica",
    "design bundles", "designbundles", "design cuts", "designcuts",
    "mighty deals", "mightydeals", "the hungry jpeg", "thehungryjpeg",
    "yellow images", "placeit", "smartmockups", "vecteezy", "vectorstock",
    "freepik", "flaticon", "pngtree", "pikbest", "lovepik",
    # Font sites
    "myfonts", "fontbundles", "font bundles", "fontspring", "linotype",
    "dafont", "fontsquirrel", "font squirrel",
    # Misc
    "pixelsquid", "juicedrops", "99designs", "fiverr", "upwork",
    "ui8", "craftwork", "ls graphics", "artstation",
    # Common abbreviations - ONLY match with separator + number: VH-12345, GR-9999
    # NOT in prefix list to avoid eating real words (ae->aerial, gr->grand)
]

# Pre-computed prefix lookups (actual initialization after _normalize is defined below)
_SORTED_PREFIXES = sorted(MARKETPLACE_PREFIXES, key=len, reverse=True)
_LOWER_PREFIX_SET = frozenset(p.lower() for p in MARKETPLACE_PREFIXES)

# Regex patterns for item IDs and noise to strip
_ID_PATTERNS = [
    r'^\d{5,}[\s\-_]',            # Leading numeric ID: "22832058-Christmas"
    r'[\s\-_]\d{5,}$',            # Trailing numeric ID: "Christmas-22832058"
    r'^[A-Z]{1,3}[\-_]\d{4,}[\s\-_]?',  # Prefixed ID: "VH-22832058", "GR-12345-"
    r'\(\d{5,}\)',                 # ID in parens: "(22832058)"
    r'\[\d{5,}\]',                 # ID in brackets: "[22832058]"
]

def _strip_source_name(folder_name: str) -> str:
    """Remove marketplace names, item IDs, and other noise from folder names.
    'Creative Market - Watercolor Brushes' -> 'Watercolor Brushes'
    'VH-22832058-Christmas-Slideshow' -> 'Christmas-Slideshow'
    """
    name = folder_name

    # Remove bracketed source names: [VideoHive], (CreativeMarket), {Envato}
    name = re.sub(r'[\[\(\{](.*?)[\]\)\}]', lambda m: '' if _normalize(m.group(1)) in
                  _NORMALIZED_PREFIX_SET else m.group(0), name)

    # Strip item ID patterns
    for pat in _ID_PATTERNS:
        name = re.sub(pat, '', name, flags=re.IGNORECASE)

    # Normalize to work with the name
    norm = name.strip()

    # Try stripping source prefixes with common separators: " - ", "-", "_", " "
    norm_lower = norm.lower().replace('-', ' ').replace('_', ' ')
    norm_lower = re.sub(r'\s+', ' ', norm_lower).strip()

    # Sort prefixes longest-first so "envato elements" matches before "envato"
    for prefix in _SORTED_PREFIXES:
        p_lower = prefix.lower()
        # Check if the normalized name starts with this prefix
        if norm_lower.startswith(p_lower):
            remainder = norm_lower[len(p_lower):].strip()
            # Must have meaningful content left after stripping
            if len(remainder) > 2:
                # Find where the prefix ends in the original string
                # Try matching with common separators
                for sep in [' - ', ' _ ', '-', '_', ' ']:
                    pattern = re.compile(re.escape(prefix) + re.escape(sep), re.IGNORECASE)
                    match = pattern.match(norm)
                    if match:
                        norm = norm[match.end():].strip()
                        norm_lower = norm.lower().replace('-', ' ').replace('_', ' ')
                        norm_lower = re.sub(r'\s+', ' ', norm_lower).strip()
                        break
                else:
                    # No separator found, try direct prefix strip
                    pattern = re.compile(re.escape(prefix) + r'[\s\-_]*', re.IGNORECASE)
                    match = pattern.match(norm)
                    if match and len(norm[match.end():].strip()) > 2:
                        norm = norm[match.end():].strip()
                        norm_lower = norm.lower().replace('-', ' ').replace('_', ' ')
                        norm_lower = re.sub(r'\s+', ' ', norm_lower).strip()

    # Clean up any leading/trailing separators left behind
    norm = re.sub(r'^[\s\-_.,]+|[\s\-_.,]+$', '', norm)

    # If result is itself a known marketplace name, it means we can't extract real content
    result_check = norm.lower().replace('-', ' ').replace('_', ' ')
    result_check = re.sub(r'\s+', ' ', result_check).strip()
    if result_check in _LOWER_PREFIX_SET:
        return folder_name

    return norm if len(norm) > 2 else folder_name



# ── International text support ───────────────────────────────────────────────
# Detect non-Latin scripts and transliterate to ASCII for keyword matching and naming.


def _is_id_only_folder(folder_name: str) -> bool:
    """Detect folder names that are purely marketplace IDs with no meaningful content.

    Matches patterns like:
      VH-12345678, GR-12345678, ah-1234567, CM_12345678, 12345678,
      graphicriver-12345678, envato-12345  (prefix + ID only, no descriptive words)
    Returns True if the name yields no useful classification signal.
    """
    stripped = re.sub(
        r'(?i)^(graphicriver|videohive|audiojungle|envato|creativemarket|cm_?|'
        r'vh[-_]?|gr[-_]?|ah[-_]?|ae[-_]?|ft[-_]?|ph[-_]?|tm[-_]?)[-_\s]*',
        '', folder_name.strip()
    )
    alpha = sum(1 for c in stripped if c.isalpha())
    digit = sum(1 for c in stripped if c.isdigit())
    if not stripped:
        return True
    if digit > 0 and alpha == 0:
        return True
    if digit > 0 and alpha > 0 and alpha / max(digit, 1) < 0.4 and len(stripped) < 18:
        return True
    return False


def _has_non_latin(text: str) -> bool:
    """Check if text contains significant non-Latin characters (CJK, Cyrillic, Arabic, etc.).
    Returns True if >25% of alpha characters are non-Latin."""
    if not text:
        return False
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return False
    non_latin = sum(1 for c in alpha if ord(c) > 0x024F)  # Beyond Latin Extended-B
    return non_latin / len(alpha) > 0.25


def _detect_scripts(text: str) -> set:
    """Detect which Unicode script blocks are present in text.
    Returns set of script names: 'latin', 'cjk', 'cyrillic', 'arabic', 'thai', 'hangul', etc."""
    scripts = set()
    for c in text:
        cp = ord(c)
        if c.isspace() or not c.isalpha():
            continue
        if cp <= 0x024F:
            scripts.add('latin')
        elif 0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F:
            scripts.add('cyrillic')
        elif (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
              0x20000 <= cp <= 0x2A6DF or 0xF900 <= cp <= 0xFAFF):
            scripts.add('cjk')
        elif 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:
            scripts.add('japanese')
        elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
            scripts.add('hangul')
        elif 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F:
            scripts.add('arabic')
        elif 0x0E00 <= cp <= 0x0E7F:
            scripts.add('thai')
        elif 0x0900 <= cp <= 0x097F:
            scripts.add('devanagari')
        else:
            scripts.add('other')
    return scripts


# Fallback Cyrillic→Latin transliteration table (when unidecode unavailable)
_CYRILLIC_MAP = str.maketrans({
    'а':'a', 'б':'b', 'в':'v', 'г':'g', 'д':'d', 'е':'e', 'ё':'yo', 'ж':'zh',
    'з':'z', 'и':'i', 'й':'y', 'к':'k', 'л':'l', 'м':'m', 'н':'n', 'о':'o',
    'п':'p', 'р':'r', 'с':'s', 'т':'t', 'у':'u', 'ф':'f', 'х':'kh', 'ц':'ts',
    'ч':'ch', 'ш':'sh', 'щ':'shch', 'ъ':'', 'ы':'y', 'ь':'', 'э':'e', 'ю':'yu',
    'я':'ya',
    'А':'A', 'Б':'B', 'В':'V', 'Г':'G', 'Д':'D', 'Е':'E', 'Ё':'Yo', 'Ж':'Zh',
    'З':'Z', 'И':'I', 'Й':'Y', 'К':'K', 'Л':'L', 'М':'M', 'Н':'N', 'О':'O',
    'П':'P', 'Р':'R', 'С':'S', 'Т':'T', 'У':'U', 'Ф':'F', 'Х':'Kh', 'Ц':'Ts',
    'Ч':'Ch', 'Ш':'Sh', 'Щ':'Shch', 'Ъ':'', 'Ы':'Y', 'Ь':'', 'Э':'E', 'Ю':'Yu',
    'Я':'Ya',
})


def _transliterate(text: str) -> str:
    """Transliterate non-Latin text to ASCII/Latin characters.
    Uses unidecode if available (best quality), falls back to Cyrillic table.
    Returns the original text if no transliteration is possible (e.g. CJK without unidecode)."""
    if not text or not _has_non_latin(text):
        return text

    if HAS_UNIDECODE:
        result = _unidecode(text)
        # Clean up: unidecode can produce brackets and junk for some chars
        result = re.sub(r'\[.*?\]', '', result)
        result = re.sub(r'\s+', ' ', result).strip()
        return result if result else text

    # Fallback: handle Cyrillic manually
    scripts = _detect_scripts(text)
    if 'cyrillic' in scripts:
        result = text.translate(_CYRILLIC_MAP)
        # Strip any remaining non-Latin after transliteration
        result = re.sub(r'[^\x00-\x7F]+', ' ', result)
        result = re.sub(r'\s+', ' ', result).strip()
        return result if result else text

    # CJK/Arabic/Thai without unidecode — can't transliterate meaningfully
    return text


@lru_cache(maxsize=4096)
def _normalize(text: str) -> str:
    t = text.lower()
    # Transliterate non-Latin characters to ASCII before stripping
    if _has_non_latin(t):
        t = _transliterate(t).lower()
    t = t.replace('-', ' ').replace('_', ' ').replace('.', ' ')
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


# Now that _normalize is defined, build the normalized prefix set
_NORMALIZED_PREFIX_SET = frozenset(_normalize(p) for p in MARKETPLACE_PREFIXES)



# ── Name beautification pipeline ────────────────────────────────────────────
# Transforms raw marketplace folder names into clean, readable titles.
# Used as the non-LLM fallback for destination folder names.

# Words to strip entirely (noise that adds no meaning to the folder name)
_NOISE_WORDS = {
    # Version/quality tags
    'v1', 'v2', 'v3', 'v4', 'v5', 'v6', 'hq', 'hd', '4k', '1080p', '720p', 'uhd', '2k',
    # Status words
    'final', 'updated', 'new', 'free', 'premium', 'preview', 'sample', 'pro', 'lite',
    # File/format noise
    'psd', 'ai', 'eps', 'svg', 'aep', 'prproj', 'mogrt', 'indd', 'idml',
    'download', 'zip', 'rar',
    # License noise
    'personal use', 'commercial license', 'royalty free', 'rf',
}

# Common short marketplace prefix codes (2-3 letter + separator, no digits required)
_SHORT_PREFIX_PATTERN = re.compile(
    r'^(?:CM|EE|GR|VH|AJ|TF|CC|PD|CF|DF)[\s\-_]+',
    re.IGNORECASE
)

# Title case exceptions (stay lowercase unless first word)
_TITLE_LOWER = {'a', 'an', 'the', 'and', 'or', 'but', 'nor', 'for', 'of', 'in',
                'on', 'at', 'to', 'by', 'up', 'as', 'is', 'it', 'if', 'vs', 'via', 'with'}


def _beautify_name(folder_name: str) -> str:
    """Full name beautification pipeline for folder names.
    Strips marketplace noise, IDs, junk suffixes, normalizes separators,
    splits CamelCase, deduplicates tokens, and applies Title Case.

    '553035-Advertisment-Company-Flyer-Template' → 'Advertisement Company Flyer Template'
    'CM_NightClub-Party-Flyer-v2-PSD' → 'Night Club Party Flyer'
    'VH-22832058-Christmas-Slideshow-FINAL' → 'Christmas Slideshow'
    """
    name = folder_name

    # Step 0: Transliterate non-Latin text (Cyrillic, CJK, etc.) to ASCII
    if _has_non_latin(name):
        name = _transliterate(name)
        # If transliteration produced nothing useful, return the original as-is
        alpha_count = sum(1 for c in name if c.isalpha())
        if alpha_count < 2:
            return folder_name

    # Step 1: Strip marketplace prefixes and IDs (reuse existing function)
    name = _strip_source_name(name)

    # Step 1.5: Second-pass prefix strip on space-normalized name
    # Catches hyphenated multi-word prefixes like "envato-elements-..." where
    # _strip_source_name only partially strips (it matches "envato" but misses "envato elements")
    # Check both the original folder name and the stripped result
    for candidate in (folder_name, name):
        name_spaced = candidate.replace('-', ' ').replace('_', ' ')
        name_spaced = re.sub(r'\s+', ' ', name_spaced).strip()
        name_spaced_lower = name_spaced.lower()
        for prefix in _SORTED_PREFIXES:
            p_lower = prefix.lower()
            if name_spaced_lower.startswith(p_lower):
                remainder = name_spaced[len(p_lower):].strip()
                if len(remainder) > 2:
                    name = remainder
                    break
        else:
            continue  # No prefix matched this candidate, try next
        break  # Prefix matched and stripped, done

    # Step 2: Strip short marketplace prefix codes (CM_, EE_, GR_, VH_, etc)
    name = _SHORT_PREFIX_PATTERN.sub('', name).strip()

    # Step 3: Split CamelCase before normalizing separators
    # 'NightClubParty' → 'Night Club Party'
    name = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
    name = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', name)  # 'HTMLParser' → 'HTML Parser'

    # Step 4: Normalize separators to spaces
    name = name.replace('-', ' ').replace('_', ' ').replace('.', ' ')
    name = re.sub(r'\s+', ' ', name).strip()

    # Step 5: Strip noise words and version patterns
    tokens = name.split()
    cleaned_tokens = []
    for t in tokens:
        t_lower = t.lower()
        # Skip noise words
        if t_lower in _NOISE_WORDS:
            continue
        # Skip standalone version patterns: v1, v2.1, V3
        if re.match(r'^v\d+(\.\d+)?$', t_lower):
            continue
        # Skip bare large numbers (leftover IDs)
        if re.match(r'^\d{5,}$', t):
            continue
        # Skip dimension patterns like 300x250, 1920x1080
        if re.match(r'^\d{2,4}x\d{2,4}$', t_lower):
            continue
        cleaned_tokens.append(t)

    # Step 6: Deduplicate consecutive repeated tokens
    # 'Flyer Flyer Template' → 'Flyer Template'
    deduped = []
    for t in cleaned_tokens:
        if not deduped or t.lower() != deduped[-1].lower():
            deduped.append(t)

    # Step 7: Apply Title Case
    result_tokens = []
    for i, t in enumerate(deduped):
        if i == 0:
            # First word always capitalized
            result_tokens.append(t.capitalize() if t.islower() or t.isupper() else t)
        elif t.lower() in _TITLE_LOWER and len(t) <= 4:
            result_tokens.append(t.lower())
        elif t.isupper() and len(t) > 1:
            # ALL CAPS → Title Case (but preserve short acronyms like 'DJ', 'FX')
            if len(t) <= 3:
                result_tokens.append(t.upper())
            else:
                result_tokens.append(t.capitalize())
        else:
            result_tokens.append(t.capitalize() if t.islower() else t)

    result = ' '.join(result_tokens).strip()

    # Safety: if we stripped everything, return the _strip_source_name result
    if len(result) < 3:
        result = _strip_source_name(folder_name)
        # At minimum, normalize separators
        result = result.replace('-', ' ').replace('_', ' ')
        result = re.sub(r'\s+', ' ', result).strip()

    return result


# Generic asset-type names that indicate the LLM stripped too aggressively.
# These are meaningless as folder names because the category already conveys this.
_GENERIC_ASSET_NAMES = {
    _normalize(n) for n in [
        'Flyer', 'Flyer Template', 'Flyers', 'Template', 'Templates',
        'Business Card', 'Business Card Template', 'Business Cards',
        'Poster', 'Poster Template', 'Posters',
        'Brochure', 'Brochure Template', 'Brochures',
        'Slideshow', 'Slideshow Template', 'Presentation', 'Presentation Template',
        'Logo', 'Logo Template', 'Logo Design',
        'Mockup', 'Mockup Template', 'Mockup PSD',
        'Resume', 'Resume Template', 'CV Template',
        'Certificate', 'Certificate Template',
        'Invitation', 'Invitation Template',
        'Banner', 'Banner Template', 'Web Banner',
        'Social Media', 'Social Media Template', 'Social Media Post',
        'Intro', 'Outro', 'Opener', 'Title', 'Titles',
        'Lower Third', 'Lower Thirds', 'Transition', 'Transitions',
        'After Effects Template', 'Premiere Template', 'Photoshop Template',
        'Project', 'Design', 'Asset', 'Pack', 'Bundle', 'Kit', 'Set',
    ]
}


def _is_generic_name(name: str, category: str) -> bool:
    """Check if a cleaned name is just a generic asset type that restates the category.
    Returns True if the name should be rejected in favor of a rule-based fallback."""
    norm = _normalize(name)
    if not norm or len(norm) < 3:
        return True
    # Direct match against known generic names
    if norm in _GENERIC_ASSET_NAMES:
        return True
    # Check if the name is just the category name or a substring of it
    cat_norm = _normalize(category)
    if norm == cat_norm:
        return True
    # Name is a subset of category words (e.g., "Templates" for "After Effects - Templates")
    name_tokens = set(norm.split())
    cat_tokens = set(cat_norm.split())
    if name_tokens and name_tokens.issubset(cat_tokens):
        return True
    return False



# ── Project name hint extraction ─────────────────────────────────────────────
# Scans folder contents for AEP/project file names and meaningful subfolders
# to discover the real project name when the folder name is generic or noisy.

# Asset/utility folder names that should NEVER be used as project name sources.
# Matches both plain ("footage") and parenthesized ("(Footage)") variants.
_ASSET_FOLDER_NAMES = frozenset({
    # Generic asset/resource folders
    'assets', 'asset', 'source', 'src', 'dist', 'build', 'output',
    'export', 'render', 'renders', 'preview', 'previews', 'temp',
    'tmp', 'cache', '__macosx', '.ds_store', 'footage', 'fonts',
    'images', 'img', 'audio', 'video', 'music', 'sound', 'sounds',
    'textures', 'materials', 'elements', 'components', 'layers',
    'compositions', 'comps', 'precomps', 'help', 'docs', 'documentation',
    'readme', 'license', 'licenses', 'media', 'resources', 'data',
    'backup', 'backups', 'old', 'original', 'originals', 'raw',
    'final', 'finals', 'versions', 'archive', 'archives',
    'screenshots', 'thumbs', 'thumbnails', 'icons', 'sprites',
    'overlays', 'transitions', 'effects', 'fx', 'sfx', 'luts',
    'presets', 'scripts', 'expressions', 'plugins', 'extras',
    # Web/dev project structure folders
    'themes', 'ui', 'animations', 'demo', 'bootstrap', 'bootstrap-colorpick',
    'js', 'css', 'code', 'pages', 'includes', 'helpers', 'modules',
    'examples', 'integration', 'styling', 'lib', 'workflows',
    # Font/link/doc folders
    'font', 'font link', 'links', 'demo link', 'logo',
    # Media/music folders
    'soundtrack', 'manual', 'github',
    # ── Discovered from 23K-folder library scan (v5.4) ──
    # App/format named folders (contain project files, not project names)
    'after effects', 'aftereffects', 'after effect', 'ae',
    'photoshop', 'psd', 'ai', 'eps', 'pdf', 'word', 'ms word',
    'jpg', 'jpeg', 'jpegs', 'png', 'html', 'scss',
    # Container/wrapper folders
    'main', 'main file', 'main files', 'mainfile', 'main 1',
    'project', 'project file', 'project files',
    'file', 'files', 'misc', 'other', 'bonus',
    # Numbered project containers (common Envato pattern)
    '01. project file', '01. project', '02. project',
    '01 - help files', '02 project files',
    '01. help', '00. help', '00_help',
    '03. assets', '03. others',
    # Tutorial/help folders
    'tutorial', 'tutorials', 'video tutorial', 'videotutorial',
    'help file', 'help files', 'help documentation',
    'user guide', 'read me', '00_read_me_first',
    '01_watch_video_tutorials',
    # Color space / size variant folders
    'cmyk', 'cmyk-psd', 'a4', 'us letter', 'us letter size', 'letter',
    # Media subfolders
    'photo', 'footages', 'loops', 'element', '3d',
    'free font', 'audio link',
    # Marketing spam folders
    '~get your graphic files',
    # Photoshop source folders
    '01_photoshop_files', 'psd files', 'flyer-sourcefiles',
})

# Project file extensions whose filenames are most likely to contain the real project name
_PROJECT_NAME_EXTS = {'.aep', '.aet', '.prproj', '.psd', '.psb', '.mogrt', '.ai', '.indd'}

# Generic project filenames to skip (the file itself has no useful name)
_GENERIC_PROJECT_NAMES = frozenset({
    'main', 'project', 'comp', 'composition', 'untitled', 'new project',
    'final', 'final project', 'edit', 'master', 'output', 'render',
    'preview', 'thumbnail', 'template', 'source', 'original', 'backup',
    'copy', 'test', 'temp', 'draft', 'wip', 'v1', 'v2', 'v3',
    # File-type words that can appear as PSD/AEP stems (e.g. a file literally named "PSD.psd")
    'psd', 'ai', 'eps', 'pdf', 'png', 'jpg', 'jpeg', 'aep', 'ae',
    'prproj', 'mogrt', 'indd', 'idml', 'svg', 'gif', 'mp4', 'mov',
    'photoshop', 'illustrator', 'after effects', 'premiere',
    # Single-word app/format names that are never useful as project titles
    'file', 'files', 'document', 'layer', 'layers', 'page', 'pages',
    'image', 'photo', 'graphic', 'design', 'artwork', 'asset',
    # Chinese generic names (discovered from 23K scan)
    '\u5de5\u7a0b\u6587\u4ef6',  # "project file" in Chinese
    '\u6587\u4ef6',        # "file" in Chinese
    '\u6a21\u677f',        # "template" in Chinese
})


def _extract_name_hints(folder_path: str) -> list:
    """Scan a folder for project file names and meaningful subfolder names.
    Returns a list of (name_hint, source, priority) sorted best-first.

    Sources: 'aep', 'prproj', 'psd', 'mogrt', 'subfolder'
    Priority: higher = better quality hint (0-100)

    Example: folder contains 'Christmas_Slideshow.aep' and subfolder '(Footage)'
    Returns: [('Christmas Slideshow', 'aep', 90)]
    """
    hints = []
    if not folder_path or not os.path.isdir(folder_path):
        return hints

    try:
        for root, dirs, files in os.walk(folder_path):
            rel = os.path.relpath(root, folder_path)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            if depth > 2:
                dirs.clear(); continue

            # ── Collect project file name hints ──
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in _PROJECT_NAME_EXTS:
                    continue

                # Clean the filename (strip extension, separators, IDs)
                raw_name = os.path.splitext(f)[0]
                # Strip leading/trailing noise
                clean = re.sub(r'^\d{5,}[\s\-_]*', '', raw_name)  # Leading IDs
                clean = re.sub(r'[\s\-_]*\d{5,}$', '', clean)     # Trailing IDs
                clean = clean.replace('-', ' ').replace('_', ' ').replace('.', ' ')
                clean = re.sub(r'\s+', ' ', clean).strip()

                # Transliterate non-Latin characters (Chinese, Russian, etc.)
                if _has_non_latin(clean):
                    clean = _transliterate(clean)
                    clean = re.sub(r'\s+', ' ', clean).strip()

                if len(clean) < 3:
                    continue
                if clean.lower() in _GENERIC_PROJECT_NAMES:
                    continue
                # Skip if it's just the marketplace prefix
                if _normalize(clean) in _NORMALIZED_PREFIX_SET:
                    continue

                # Priority based on file type (AEP/PRPROJ are strongest signals)
                if ext in ('.aep', '.aet'):
                    priority = 90
                elif ext == '.prproj':
                    priority = 88
                elif ext == '.mogrt':
                    priority = 85
                elif ext in ('.psd', '.psb'):
                    priority = 75  # PSD names can be generic layer exports
                elif ext == '.ai':
                    priority = 72
                elif ext in ('.indd',):
                    priority = 70
                else:
                    priority = 60

                # Depth penalty (deeper = less likely to be the main project)
                priority -= depth * 8

                hints.append((clean, ext.lstrip('.'), priority))

            # ── Collect meaningful subfolder name hints (depth 0 only) ──
            if depth == 0:
                for d in dirs:
                    d_lower = d.lower().strip()
                    d_stripped = re.sub(r'^[\(\[\{]|[\)\]\}]$', '', d_lower).strip()
                    if d_stripped in _ASSET_FOLDER_NAMES or d_lower in _ASSET_FOLDER_NAMES:
                        continue
                    if len(d_stripped) < 3:
                        continue
                    # Strip leading ordinal numbers (e.g. "02 Vector" → "Vector", "01. Main" → "Main")
                    d_denumbered = re.sub(r'^\d+[\s._-]+', '', d).strip()
                    if not d_denumbered or len(d_denumbered) < 3:
                        continue
                    d_clean = d_denumbered.replace('-', ' ').replace('_', ' ')
                    d_clean = re.sub(r'\s+', ' ', d_clean).strip()
                    d_norm = _normalize(d_clean)
                    # Skip if it's a generic word or asset-type word after stripping numbers
                    if d_norm in _GENERIC_PROJECT_NAMES:
                        continue
                    if d_norm in _ASSET_FOLDER_NAMES:
                        continue
                    # Skip single-word generic design terms that could appear as subfolder names
                    single_word_blocklist = {
                        'vector', 'vectors', 'mockup', 'mockups', 'resume', 'cv',
                        'flyer', 'poster', 'banner', 'card', 'brochure', 'logo',
                        'icon', 'icons', 'font', 'fonts', 'color', 'colors',
                        'texture', 'pattern', 'background', 'graphic', 'print',
                    }
                    if d_norm in single_word_blocklist:
                        continue
                    if _normalize(d_clean) not in _GENERIC_PROJECT_NAMES:
                        hints.append((d_clean, 'subfolder', 50))

    except (PermissionError, OSError):
        pass

    # Sort by priority (highest first), deduplicate by normalized name
    hints.sort(key=lambda x: -x[2])
    seen = set()
    unique = []
    for name, source, priority in hints:
        norm = _normalize(name)
        if norm not in seen:
            seen.add(norm)
            unique.append((name, source, priority))
    return unique[:10]  # Cap at 10 hints


def _smart_name(folder_name: str, folder_path: str = None, category: str = None) -> str:
    """Intelligent project naming using folder name + project file/subfolder hints.
    Falls back to _beautify_name() when no better name is found.

    Logic:
    1. Beautify the folder name
    2. If the result is generic, noisy, or mostly numeric — look for AEP/project file hints
    3. Pick the best hint and beautify it
    4. If the hint is also generic, fall back to the beautified folder name
    """
    beautified = _beautify_name(folder_name)

    # Check if the beautified name needs improvement
    needs_hints = False

    # Case 1: Name is a generic asset type that restates the category
    if category and _is_generic_name(beautified, category):
        needs_hints = True

    # Case 2: Name is mostly numeric (leftover IDs not fully stripped)
    if not needs_hints:
        alpha_chars = sum(1 for c in beautified if c.isalpha())
        digit_chars = sum(1 for c in beautified if c.isdigit())
        if digit_chars > alpha_chars:
            needs_hints = True

    # Case 3: Name is very short (likely just abbreviations/codes)
    if not needs_hints and len(beautified.replace(' ', '')) <= 4:
        needs_hints = True

    # Case 4: Name is a known marketplace prefix that survived stripping
    if not needs_hints and _normalize(beautified) in _NORMALIZED_PREFIX_SET:
        needs_hints = True

    # Case 5: Original folder name contains non-Latin characters (Chinese, Russian, etc.)
    # Transliteration may produce awkward results, so try project file hints first
    if not needs_hints and _has_non_latin(folder_name):
        needs_hints = True

    if not needs_hints:
        return beautified

    # Folder name was inadequate — try to find a better name from project files
    if not folder_path:
        return beautified

    hints = _extract_name_hints(folder_path)
    if not hints:
        return beautified

    # Try each hint, pick the first non-generic one
    for name, source, priority in hints:
        hint_beautified = _beautify_name(name)
        if len(hint_beautified) >= 3:
            if not category or not _is_generic_name(hint_beautified, category):
                return hint_beautified

    return beautified


# Pre-computed normalized prefix set (used by _strip_source_name)
_NORMALIZED_PREFIX_SET = frozenset(_normalize(p) for p in MARKETPLACE_PREFIXES)
