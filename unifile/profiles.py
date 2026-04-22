"""UniFile — Scan Profiles: switchable behavior sets for different organizing scenarios."""
import json
import os

from unifile.config import _APP_DATA_DIR

_PROFILES_FILE = os.path.join(_APP_DATA_DIR, 'active_profile.json')


# ── Built-in profile definitions ─────────────────────────────────────────────

BUILTIN_PROFILES = {

    # ── Design Assets (original behavior, default) ───────────────────────────
    "Design Assets": {
        "id": "design_assets",
        "icon": "🎨",
        "description": "Organize creative marketplace content — After Effects, Photoshop, Premiere, fonts, mockups, stock media.",
        "category_filter": None,  # None = use all CATEGORIES (design-centric keyword list)
        "llm_persona": "design_asset",
        "rename_strategy": "smart",       # _smart_name with AEP/project file hints
        "scan_depth": 0,                  # scan direct children of source folder
        "show_aep_mode": True,
        "show_cat_mode": True,
        "show_smart_mode": True,
        "show_files_mode": True,
        "default_mode": 1,                # Categorize Folders
        "file_rename_templates": {},      # use defaults from PC categories
        "organization_rules": {
            "group_by": "category",       # group into category subfolders
            "flatten": False,
        },
    },

    # ── General Files ────────────────────────────────────────────────────────
    "General Files": {
        "id": "general_files",
        "icon": "📂",
        "description": "Organize any folder — downloads, desktop, documents. Sort by type, date, or project.",
        "category_filter": "general",
        "llm_persona": "general_file",
        "rename_strategy": "metadata",    # use file metadata for renaming
        "scan_depth": 0,
        "show_aep_mode": False,
        "show_cat_mode": True,
        "show_smart_mode": True,
        "show_files_mode": True,
        "default_mode": 3,                # PC File Organizer
        "file_rename_templates": {
            "Images":    "{year}-{month}-{day}_{name}",
            "Videos":    "{year}-{month}-{day}_{name}",
            "Audio":     "{artist} - {title}",
            "Documents": "{name}",
        },
        "organization_rules": {
            "group_by": "type",
            "flatten": False,
        },
    },

    # ── Photo Library ────────────────────────────────────────────────────────
    "Photo Library": {
        "id": "photo_library",
        "icon": "📷",
        "description": "Organize photos by date, location, faces, and scene type. HEIC/RAW conversion, blur detection, deduplication.",
        "category_filter": "photos",
        "llm_persona": "photo_library",
        "rename_strategy": "exif",        # EXIF-based rename
        "scan_depth": 2,                  # recurse into subfolders
        "show_aep_mode": False,
        "show_cat_mode": False,
        "show_smart_mode": False,
        "show_files_mode": True,
        "default_mode": 3,
        "file_rename_templates": {
            "Images": "{year}-{month}-{day}_{hour}{minute}_{name}",
            "Videos": "{year}-{month}-{day}_{hour}{minute}_{name}",
        },
        "organization_rules": {
            "group_by": "date",
            "date_format": "{year}/{month_name}",
            "flatten": False,
            "dedupe": True,
            "convert_heic": True,
        },
    },

    # ── Music Library ────────────────────────────────────────────────────────
    "Music Library": {
        "id": "music_library",
        "icon": "🎵",
        "description": "Organize music by artist, album, genre. Uses ID3/FLAC tags for smart renaming and folder structure.",
        "category_filter": "music",
        "llm_persona": "music_library",
        "rename_strategy": "audio_tags",
        "scan_depth": 2,
        "show_aep_mode": False,
        "show_cat_mode": False,
        "show_smart_mode": False,
        "show_files_mode": True,
        "default_mode": 3,
        "file_rename_templates": {
            "Audio": "{artist}/{album}/{track:02d} - {title}",
        },
        "organization_rules": {
            "group_by": "artist_album",
            "flatten": False,
        },
    },

    # ── Developer / Code ─────────────────────────────────────────────────────
    "Developer": {
        "id": "developer",
        "icon": "💻",
        "description": "Organize code projects, repos, configs, logs, and build artifacts. Respects .gitignore patterns.",
        "category_filter": "developer",
        "llm_persona": "developer",
        "rename_strategy": "none",        # devs want control, no auto-rename
        "scan_depth": 1,
        "show_aep_mode": False,
        "show_cat_mode": True,
        "show_smart_mode": False,
        "show_files_mode": True,
        "default_mode": 3,
        "file_rename_templates": {},
        "organization_rules": {
            "group_by": "type",
            "respect_gitignore": True,
            "flatten": False,
        },
    },

    # ── Office & Business ────────────────────────────────────────────────────
    "Office & Business": {
        "id": "office_business",
        "icon": "💼",
        "description": "Organize business documents — contracts, invoices, reports, presentations, spreadsheets.",
        "category_filter": "office",
        "llm_persona": "office_business",
        "rename_strategy": "metadata",
        "scan_depth": 1,
        "show_aep_mode": False,
        "show_cat_mode": True,
        "show_smart_mode": True,
        "show_files_mode": True,
        "default_mode": 3,
        "file_rename_templates": {
            "Documents": "{year}-{month}-{day}_{name}",
        },
        "organization_rules": {
            "group_by": "document_type",
            "flatten": False,
        },
    },

    # ── Downloads Cleanup ────────────────────────────────────────────────────
    "Downloads Cleanup": {
        "id": "downloads_cleanup",
        "icon": "📥",
        "description": "Quick cleanup for Downloads folder — sort by file type, remove duplicates, archive old files.",
        "category_filter": "general",
        "llm_persona": "general_file",
        "rename_strategy": "none",
        "scan_depth": 0,
        "show_aep_mode": False,
        "show_cat_mode": False,
        "show_smart_mode": False,
        "show_files_mode": True,
        "default_mode": 3,
        "file_rename_templates": {},
        "organization_rules": {
            "group_by": "type",
            "flatten": True,
            "dedupe": True,
        },
        "default_source": "~/Downloads",
    },
}


# ── Per-profile category sets ────────────────────────────────────────────────
# These extend (not replace) the base CATEGORIES from categories.py.
# When a profile has category_filter set, only matching categories are shown
# in the LLM prompt and keyword matching.

PROFILE_CATEGORIES = {

    "general": [
        ("Documents - Personal", ["personal document", "personal letter", "diary", "journal", "notes", "personal notes", "memo"]),
        ("Documents - Financial", ["invoice", "receipt", "bank statement", "tax return", "tax form", "w2", "1099", "pay stub", "payroll", "expense report", "financial statement", "budget"]),
        ("Documents - Legal", ["contract", "agreement", "lease", "nda", "terms of service", "license agreement", "power of attorney", "will", "deed", "court document", "legal document"]),
        ("Documents - Medical", ["medical record", "prescription", "lab result", "x-ray", "mri", "health record", "insurance claim", "medical bill", "vaccination record"]),
        ("Documents - Academic", ["thesis", "dissertation", "research paper", "essay", "homework", "assignment", "lecture notes", "syllabus", "transcript", "report card", "coursework"]),
        ("Documents - Reference", ["manual", "guide", "handbook", "documentation", "specification", "datasheet", "whitepaper", "reference guide", "user guide", "how-to"]),
        ("Spreadsheets & Data", ["spreadsheet", "excel", "csv data", "database export", "data dump", "analytics", "metrics", "statistics", "pivot table"]),
        ("Presentations", ["presentation", "slide deck", "pitch deck", "keynote", "powerpoint", "pptx", "slides"]),
        ("PDFs & Reports", ["pdf report", "annual report", "quarterly report", "summary report", "audit report", "compliance report"]),
        ("Ebooks & Reading", ["ebook", "epub", "kindle", "audiobook", "pdf book", "textbook", "novel", "manga", "comic"]),
        ("Screenshots & Screen Captures", ["screenshot", "screen capture", "screen grab", "screen recording", "screencast"]),
        ("Installers & Setup", ["installer", "setup", "install", "setup wizard", "msi", "dmg", "pkg", "deb", "rpm", "appimage"]),
        ("Compressed & Archives", ["zip file", "archive", "compressed", "tar", "rar", "7z", "backup archive"]),
        ("Temporary & Cache", ["temp file", "cache", "tmp", "scratch", "draft", "wip"]),
        ("Torrents & Downloads", ["torrent", "magnet", "download", "downloaded"]),
        ("Disk Images & ISOs", ["iso", "disk image", "boot disk", "recovery disk", "virtual machine", "vmdk", "vdi", "qcow2"]),
        ("Backups", ["backup", "bak", "snapshot", "restore point", "time machine"]),
        ("Wallpapers & Themes", ["wallpaper", "desktop background", "lock screen", "theme pack", "icon pack"]),
        ("Fonts", ["font", "typeface", "ttf", "otf", "woff"]),
        ("3D Printing & CAD", ["stl file", "gcode", "3d print", "cad", "solidworks", "autocad", "fusion 360"]),
        ("Game Files & Mods", ["game mod", "save game", "game save", "rom", "emulator", "mod pack", "addon", "plugin"]),
        ("Recipes & Cooking", ["recipe", "cookbook", "meal plan", "grocery list"]),
        ("Travel & Itineraries", ["itinerary", "boarding pass", "travel plan", "hotel booking", "flight confirmation", "passport scan"]),
    ],

    "photos": [
        ("Photos - Portraits & People", ["portrait", "headshot", "selfie", "group photo", "family photo", "people"]),
        ("Photos - Landscapes & Nature", ["landscape", "nature", "mountain", "ocean", "sunset", "sunrise", "forest", "beach", "scenic"]),
        ("Photos - Architecture & Urban", ["architecture", "building", "city", "street", "urban", "skyline", "bridge"]),
        ("Photos - Food & Drink", ["food photo", "meal", "restaurant", "cooking", "drink", "coffee"]),
        ("Photos - Animals & Pets", ["pet photo", "dog photo", "cat photo", "animal", "wildlife", "bird"]),
        ("Photos - Events & Celebrations", ["wedding photo", "birthday photo", "party photo", "graduation photo", "holiday photo", "celebration"]),
        ("Photos - Travel & Vacation", ["travel photo", "vacation photo", "tourist", "landmark", "sightseeing"]),
        ("Photos - Sports & Action", ["sports photo", "action shot", "game day", "athletic", "racing"]),
        ("Photos - Art & Abstract", ["art photo", "abstract photo", "macro photo", "long exposure", "black and white", "monochrome"]),
        ("Photos - Product & Commercial", ["product photo", "catalog photo", "ecommerce", "flat lay", "styled"]),
        ("Photos - Documents & Scans", ["document scan", "receipt scan", "whiteboard photo", "screenshot", "screen capture"]),
        ("Photos - RAW Files", ["raw photo", "cr2", "cr3", "nef", "arw", "dng", "orf"]),
        ("Photos - Edited & Processed", ["edited photo", "processed", "retouched", "filtered", "enhanced"]),
        ("Photos - Panoramas", ["panorama", "pano", "360 photo", "wide angle"]),
        ("Photos - Blurry & Low Quality", ["blurry", "out of focus", "low quality", "noise", "motion blur"]),
        ("Videos - Personal", ["home video", "family video", "vacation video", "birthday video"]),
        ("Videos - Clips", ["video clip", "short clip", "highlight", "reel"]),
        ("Videos - Screen Recordings", ["screen recording", "screencast", "tutorial recording"]),
    ],

    "music": [
        ("Music - Rock & Alternative", ["rock", "alternative rock", "indie rock", "punk", "grunge", "metal", "hard rock"]),
        ("Music - Pop", ["pop", "pop music", "dance pop", "synth pop", "electropop"]),
        ("Music - Hip Hop & Rap", ["hip hop", "rap", "trap", "r&b", "rnb", "soul"]),
        ("Music - Electronic & EDM", ["electronic", "edm", "techno", "house", "trance", "dubstep", "drum and bass", "ambient electronic"]),
        ("Music - Classical & Orchestral", ["classical", "orchestral", "symphony", "chamber music", "opera", "piano", "violin", "concerto"]),
        ("Music - Jazz & Blues", ["jazz", "blues", "swing", "bebop", "smooth jazz", "fusion"]),
        ("Music - Country & Folk", ["country", "folk", "bluegrass", "americana", "singer songwriter"]),
        ("Music - Soundtracks & Scores", ["soundtrack", "film score", "game soundtrack", "movie music", "ost"]),
        ("Music - Ambient & Chill", ["ambient", "chill", "lofi", "lo-fi", "downtempo", "new age", "meditation"]),
        ("Music - World & Cultural", ["world music", "latin", "reggae", "afrobeat", "k-pop", "j-pop", "bossa nova", "flamenco"]),
        ("Music - Podcasts", ["podcast", "podcast episode", "audio show", "talk show"]),
        ("Music - Audiobooks", ["audiobook", "audio book", "narration", "spoken word"]),
        ("Music - Sound Effects", ["sound effect", "sfx", "foley", "ambient sound", "nature sound"]),
        ("Music - Samples & Loops", ["sample", "loop", "drum loop", "beat", "sample pack", "stem"]),
        ("Music - DJ Sets & Mixes", ["dj set", "dj mix", "mixtape", "live set", "radio show"]),
        ("Music - Recordings & Demos", ["demo", "recording session", "rough mix", "rehearsal", "live recording"]),
        ("Music - Karaoke & Instrumental", ["karaoke", "instrumental", "backing track", "minus one"]),
    ],

    "developer": [
        ("Code - Python", ["python", "py", "django", "flask", "fastapi", "pytest", "pip", "conda"]),
        ("Code - JavaScript & TypeScript", ["javascript", "typescript", "react", "vue", "angular", "node", "npm", "nextjs", "express"]),
        ("Code - Web Frontend", ["html", "css", "scss", "tailwind", "bootstrap", "webpack", "vite"]),
        ("Code - Backend & APIs", ["api", "rest api", "graphql", "grpc", "backend", "server", "microservice"]),
        ("Code - Mobile", ["android", "ios", "react native", "flutter", "swift", "kotlin", "mobile app"]),
        ("Code - Systems & Low Level", ["c", "cpp", "rust", "go", "assembly", "embedded", "firmware", "kernel"]),
        ("Code - DevOps & Infrastructure", ["docker", "kubernetes", "terraform", "ansible", "ci cd", "pipeline", "github actions", "jenkins"]),
        ("Code - Database", ["sql", "database", "postgres", "mysql", "mongodb", "redis", "sqlite", "migration"]),
        ("Code - Data Science & ML", ["machine learning", "data science", "jupyter", "notebook", "pandas", "numpy", "tensorflow", "pytorch"]),
        ("Code - Scripts & Automation", ["script", "automation", "bash script", "powershell", "cron job", "task scheduler"]),
        ("Config & Environment", ["config", "environment", "env file", "settings", "yaml", "toml", "ini", "dotfile"]),
        ("Documentation", ["readme", "docs", "documentation", "changelog", "contributing", "license", "wiki"]),
        ("Build Artifacts & Output", ["build", "dist", "output", "compiled", "binary", "executable", "release"]),
        ("Dependencies & Packages", ["node_modules", "vendor", "packages", "requirements", "lock file", "package.json"]),
        ("Tests & QA", ["test", "tests", "spec", "unit test", "integration test", "e2e", "coverage"]),
        ("Logs & Debug", ["log", "debug", "trace", "error log", "crash dump", "core dump"]),
        ("Git & Version Control", ["git", "repo", "repository", "branch", "commit", "pull request", "merge"]),
    ],

    "office": [
        ("Contracts & Agreements", ["contract", "agreement", "terms", "nda", "sla", "mou", "memorandum"]),
        ("Invoices & Billing", ["invoice", "bill", "billing", "payment", "receipt", "purchase order", "po"]),
        ("Reports & Analysis", ["report", "analysis", "summary", "quarterly report", "annual report", "audit", "assessment"]),
        ("Proposals & Bids", ["proposal", "bid", "rfp", "rfq", "quotation", "estimate", "tender"]),
        ("Meeting Notes & Minutes", ["meeting notes", "minutes", "agenda", "action items", "standup", "retrospective"]),
        ("Policies & Procedures", ["policy", "procedure", "sop", "guideline", "compliance", "regulation"]),
        ("HR & Personnel", ["resume", "cv", "job description", "onboarding", "employee handbook", "performance review", "timesheet"]),
        ("Marketing & Sales", ["marketing plan", "sales report", "campaign", "press release", "media kit", "pitch"]),
        ("Presentations & Decks", ["presentation", "slide deck", "pitch deck", "keynote", "boardroom"]),
        ("Spreadsheets & Financial", ["spreadsheet", "budget", "forecast", "p&l", "balance sheet", "cashflow", "expense"]),
        ("Letters & Correspondence", ["letter", "memo", "correspondence", "notice", "announcement", "circular"]),
        ("Templates & Forms", ["template", "form", "fillable", "checklist", "worksheet", "timecard"]),
        ("Training & Education", ["training material", "course", "curriculum", "certification", "tutorial", "webinar"]),
        ("Project Plans", ["project plan", "gantt", "roadmap", "milestone", "timeline", "work breakdown"]),
        ("Client Files", ["client file", "customer record", "case file", "account", "portfolio"]),
        ("Archives & Old Files", ["archive", "archived", "legacy", "deprecated", "old version", "previous"]),
    ],
}


# ── LLM system prompts per profile persona ───────────────────────────────────

LLM_PERSONAS = {

    "design_asset": None,  # None = use existing _build_llm_system_prompt() unchanged

    "general_file": (
        "You are a file organization assistant. Your job is to classify files and folders "
        "into the correct category based on their names, extensions, and content.\n\n"
        "Your job:\n"
        "1. CLEAN the name: remove junk characters, timestamps, duplicate markers "
        "(copy, (1), (2)), download prefixes, and convert to clean Title Case.\n"
        "2. CATEGORIZE into the single best category from the list below.\n\n"
        "Respond ONLY with valid JSON, no other text:\n"
        '{\"name\": \"Clean Name\", \"category\": \"Exact Category Name\", \"confidence\": 85}\n\n'
        "VALID CATEGORIES (pick exactly one):\n"
    ),

    "photo_library": (
        "You are a photo library organizer. Classify images and videos by their content, "
        "subject matter, and visual characteristics.\n\n"
        "Your job:\n"
        "1. CLEAN the filename: remove camera codes (IMG_, DSC_, DCIM), timestamps "
        "that duplicate EXIF data, copy markers, and random strings.\n"
        "2. CATEGORIZE into the best category based on the image content implied by the filename, "
        "folder structure, and any EXIF metadata provided.\n\n"
        "Respond ONLY with valid JSON, no other text:\n"
        '{\"name\": \"Clean Name\", \"category\": \"Exact Category Name\", \"confidence\": 85}\n\n'
        "VALID CATEGORIES (pick exactly one):\n"
    ),

    "music_library": (
        "You are a music library organizer. Classify audio files by genre, type, and purpose "
        "using filenames, folder structure, and any ID3/metadata tags provided.\n\n"
        "Your job:\n"
        "1. CLEAN the name: extract artist, album, track info. Remove scene tags "
        "(WEB, FLAC, 320kbps, etc), release group names, and junk.\n"
        "2. CATEGORIZE into the best music category from the list below.\n\n"
        "Respond ONLY with valid JSON, no other text:\n"
        '{\"name\": \"Clean Name\", \"category\": \"Exact Category Name\", \"confidence\": 85}\n\n'
        "VALID CATEGORIES (pick exactly one):\n"
    ),

    "developer": (
        "You are a developer workspace organizer. Classify code projects, repositories, "
        "scripts, and development files by their technology stack and purpose.\n\n"
        "Your job:\n"
        "1. CLEAN the project name: remove git hashes, build numbers, version suffixes, "
        "and normalize to clean Title Case while preserving technical identifiers.\n"
        "2. CATEGORIZE into the best developer category from the list below.\n\n"
        "Respond ONLY with valid JSON, no other text:\n"
        '{\"name\": \"Clean Name\", \"category\": \"Exact Category Name\", \"confidence\": 85}\n\n'
        "VALID CATEGORIES (pick exactly one):\n"
    ),

    "office_business": (
        "You are a business document organizer. Classify documents, spreadsheets, "
        "presentations, and business files by their type and purpose.\n\n"
        "Your job:\n"
        "1. CLEAN the name: remove version numbers, draft markers, timestamps, "
        "and normalize to clean Title Case.\n"
        "2. CATEGORIZE into the best business category from the list below.\n\n"
        "Respond ONLY with valid JSON, no other text:\n"
        '{\"name\": \"Clean Name\", \"category\": \"Exact Category Name\", \"confidence\": 85}\n\n'
        "VALID CATEGORIES (pick exactly one):\n"
    ),
}


# ── Profile management ───────────────────────────────────────────────────────

_active_profile_name = "Design Assets"


def get_active_profile_name() -> str:
    """Return the name of the currently active profile."""
    return _active_profile_name


def get_active_profile() -> dict:
    """Return the full profile dict for the active profile."""
    return BUILTIN_PROFILES.get(_active_profile_name, BUILTIN_PROFILES["Design Assets"])


def set_active_profile(name: str):
    """Switch the active profile."""
    global _active_profile_name
    if name in BUILTIN_PROFILES:
        _active_profile_name = name
        _save_active_profile(name)


def get_profile_names() -> list:
    """Return list of all available profile names."""
    return list(BUILTIN_PROFILES.keys())


def get_profile_categories(profile_name: str = None) -> list:
    """Return the category list for a profile. Returns profile-specific categories
    merged with applicable base categories, or all categories if no filter."""
    from unifile.categories import CATEGORIES, get_all_categories
    profile = BUILTIN_PROFILES.get(profile_name or _active_profile_name)
    if not profile:
        return get_all_categories()

    cat_filter = profile.get("category_filter")
    if cat_filter is None:
        # Design Assets profile: use all existing categories
        return get_all_categories()

    # Get profile-specific categories
    profile_cats = PROFILE_CATEGORIES.get(cat_filter, [])

    # For non-design profiles, combine profile categories with relevant base categories
    # (e.g., general files still benefit from topic categories like "Travel", "Health", etc.)
    combined = list(profile_cats)

    # Add base topic/theme categories that are universally useful
    _UNIVERSAL_SECTIONS = {
        "TOPICS, THEMES & EVENTS",
    }
    in_universal = False
    for cat_name, keywords in CATEGORIES:
        # Check section markers by looking at surrounding categories
        if cat_name in ("Accounting & Finance",):
            in_universal = True
        if cat_name in ("Yoga & Meditation",):
            combined.append((cat_name, keywords))
            in_universal = False
            continue
        if in_universal:
            combined.append((cat_name, keywords))

    return combined


def get_llm_persona(profile_name: str = None) -> str:
    """Return the LLM persona ID for a profile."""
    profile = BUILTIN_PROFILES.get(profile_name or _active_profile_name)
    if not profile:
        return "design_asset"
    return profile.get("llm_persona", "design_asset")


def get_llm_system_prompt_prefix(profile_name: str = None) -> str:
    """Return the LLM system prompt prefix for a profile, or None to use default."""
    persona = get_llm_persona(profile_name)
    return LLM_PERSONAS.get(persona)


def _load_active_profile():
    """Load the last-used profile from disk."""
    global _active_profile_name
    try:
        with open(_PROFILES_FILE) as f:
            data = json.load(f)
        name = data.get('active_profile', 'Design Assets')
        if name in BUILTIN_PROFILES:
            _active_profile_name = name
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass


def _save_active_profile(name: str):
    """Persist the active profile choice."""
    try:
        os.makedirs(os.path.dirname(_PROFILES_FILE), exist_ok=True)
        with open(_PROFILES_FILE, 'w') as f:
            json.dump({'active_profile': name}, f)
    except OSError:
        pass


# Auto-load on import
_load_active_profile()
