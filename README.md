# UniFile

![Version](https://img.shields.io/badge/version-9.3.32-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![Status](https://img.shields.io/badge/status-active-success)
![AI Powered](https://img.shields.io/badge/AI-Ollama%20LLM-e879f9)
![Tags](https://img.shields.io/badge/Tags-SQLAlchemy-orange)

> Unified AI-powered file organization platform — combining tag-based library management, 7-level classification, LLM intelligence, cleanup tools, duplicate detection, and media metadata into a single premium dark-themed desktop app.

![Screenshot](screenshot.png)

## Overview

UniFile merges the best ideas from five file organization projects into one cohesive tool:

| Source Project | Stars | What UniFile Takes From It |
|----------------|-------|----------------------------|
| [TagStudio](https://github.com/TagStudioDev/TagStudio) | 42k | Tag-based file library with hierarchical tags, aliases, color coding, field system |
| [FileOrganizer](https://github.com/SysAdminDoc/FileOrganizer) | — | Foundation: 7-level classification, Ollama LLM, PyQt6 GUI, 384+ categories |
| [Local-File-Organizer](https://github.com/QiuYannworworworworworworworwor/Local-File-Organizer) | 3.1k | AI file analysis with vision models (planned: Nexa SDK backend) |
| [classifier](https://github.com/bhrigu123/classifier) | 1.1k | Rule-based file sorting by extension (planned: category preset merge) |
| [mnamer](https://github.com/jkwill87/mnamer) | 1k | Media metadata lookup patterns via TMDb, OMDb, TVMaze, and `guessit` |

## Quick Start

```bash
git clone https://github.com/SysAdminDoc/UniFile.git
cd UniFile
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[full]"
.\.venv\Scripts\python run.py
```

Source imports do not install packages or download models. To opt in to the legacy dependency bootstrap for a source checkout, run:

```bash
python run.py --install-deps
```

Ollama is optional. Install it from [ollama.com](https://ollama.com), start it with `ollama serve`, then download a model manually (`ollama pull qwen2.5:7b`) or from **Settings > Ollama LLM**. UniFile falls back to rule-based classification when Ollama is unavailable.

## Features

### Tag Library (NEW in v8.0)

Full tag-based file management adapted from TagStudio's SQLAlchemy models:

| Feature | Description |
|---------|-------------|
| Hierarchical Tags | Parent-child tag relationships with unlimited nesting |
| Tag Aliases | Multiple names for the same tag |
| Color-Coded Tags | 20 color presets for visual organization |
| Category Tags | Distinguish organizational categories from descriptive tags |
| Quick Presets | One-click Favorite, Important, Review, Archive tags |
| Entry Fields | 21 built-in field types (title, author, AI summary, TMDb ID, etc.) |
| Custom Field Schemas | Per-library currency, date, status/enum, checkbox, and text fields with validation |
| Auto-Tagging | Classification results automatically create and apply tags |
| Bulk Operations | Scan directories, bulk-add files, batch tag assignment |
| Tag Search | Real-time search across tags and entries |

The tag library stores data in `.unifile/unifile_tags.sqlite` within your library directory — non-destructive, no files are modified.

TagStudio migration is available from the Tag Library panel and headless CLI. Import accepts a TagStudio library folder or `.TagStudio/ts_library.sqlite`/`.db` file and reads it in SQLite read-only mode. Export writes an additive TagStudio-compatible `.TagStudio/ts_library.sqlite`; existing TagStudio records are retained, and preserved `.TagStudio/thumbs` data is copied without changing the original files.

```bash
python -m unifile import-tagstudio /path/to/tagstudio /path/to/unifile-library --json
python -m unifile export-tagstudio /path/to/unifile-library /path/to/tagstudio-export --json
```

Use `--dry-run` with `import-tagstudio` to inspect counts without creating a UniFile database, or `--no-thumbnails` to omit cached thumbnail transfer.

### Book Library

The built-in **Book Library** profile narrows scans to `.epub`, `.pdf`, `.mobi`, and `.azw3` files. EPUB and PDF metadata is extracted locally; ISBNs are normalized with the optional `isbnlib2` package, while MOBI/AZW3 files fall back safely to filename metadata. When a Tag Library is open, a Book Library scan adds title, author, ISBN, language, genre, series, publisher, synopsis, and reading-status fields plus deterministic `book`, `genre:*`, `language:*`, `series:*`, and `reading:*` tags.

Remote enrichment is explicit and cached. OpenLibrary is queried first and Google Books fills missing values; covers are downloaded only when `--download-covers` is requested. The API client uses a one-request-per-second default interval and an identifying User-Agent. Use the headless commands for repeatable workflows:

```bash
python -m unifile books scan /path/to/ebooks --library /path/to/unifile-library --lookup --download-covers --json
python -m unifile books export-opf /path/to/unifile-library --output /path/to/calibre-metadata --json
```

OPF export is non-destructive: each book gets a deterministic folder containing a Calibre-compatible `metadata.opf`, and cached cover art is copied when available. Generated metadata defaults to `.unifile/calibre-opf` when `--output` is omitted.

### Video Project Awareness

**Project Audit** reads `.aep`, `.prproj`, `.drp`, and `.fcpbundle` projects without opening or modifying them. It resolves referenced media, reports assets shared by multiple projects, lists media files with no project reference, and separates missing paths. Open **Ctrl+K → Project Audit** from the desktop UI, or use the read-only CLI report:

```bash
python -m unifile projects audit /path/to/projects --json
python -m unifile projects audit /path/to/projects --library /path/to/unifile-library --apply
```

`--apply` is explicit: resolved assets receive `project:*` and `project-reference` tags plus project names, project modified timestamps, and reference counts in the tag library. Binary project formats use bounded string extraction, while Final Cut bundles also inspect FCPXML/SQLite content and managed media.

### Media Lookup (NEW in v8.0)

Unified movie, TV, book, audiobook, and audio metadata lookup powered by TMDb, TVDB, TVMaze, OMDb, OpenLibrary, Google Books, and MusicBrainz (adapted from mnamer):
TMDb, TVDB, OMDb, and OpenSubtitles use your own API keys via the Media Lookup panel or `API_KEY_TMDB`, `API_KEY_TVDB`, `API_KEY_OMDB`, and `API_KEY_OPENSUBTITLES`; TVDB can also use `API_KEY_TVDB_PIN`. TVMaze, OpenLibrary, Google Books, and MusicBrainz work without a key. OpenSubtitles downloads additionally require the user account credentials accepted by its API.

| Feature | Description |
|---------|-------------|
| Video Search | TMDb → OMDb movie fallback and TVDB → TMDb → TVMaze TV fallback with full details and episode lists |
| Book Search | OpenLibrary → Google Books fallback for books and audiobooks, including authors, ISBN, covers, and publication data |
| Audio Search | MusicBrainz recording lookup with artist, album, release, and Cover Art Archive metadata |
| Provider Key Status | Missing or rejected credentials are shown before and after searches, with environment-variable precedence |
| guessit Parser | Parse video, book, audiobook, and audio filenames to auto-detect title, year, season, and episode |
| Artwork Preview | Full poster or cover-art display with synopsis, genres, and external IDs |
| Cover Art Embedding | Select a local MP3, FLAC/Ogg, MP4/M4A, or EPUB file and fetch missing artwork from the reviewed provider result; writes are atomic, cached, and undoable |
| Apply to Tags | Push normalized media metadata into matching Tag Library fields and genre tags |
| Copy Metadata | One-click copy of all metadata fields to clipboard |
| Subtitle + Chapter Sidecars | Review `.srt`/`.ass` OpenSubtitles matches and save TMDb-derived `.chapters.json` metadata beside a local video |
| NFO Sidecars | Save reviewed movie, TV, music, or book metadata as Kodi/Plex-compatible `.nfo` XML beside local media; the headless CLI also accepts Tag Library field JSON |
| RAW Photo Families | Recognize CR2, CR3, NEF, ARW, ORF, DNG, and related RAW files; collapse same-stem RAW+JPEG captures into one move item and prefer RAW EXIF before filling gaps from the JPEG |
| Cached Requests | API responses cached for 6 days to reduce API calls |

For format-level metadata work, select a file, open **Tools → Batch Metadata Editor**, and choose **Inspect Raw Metadata**. The inspector enumerates EXIF, XMP sidecar, ID3, mutagen audio, and PDF fields, lets you edit writable values in a proposed-value column, and requires an explicit preview before applying. JPEG/TIFF EXIF, ID3, mutagen, and PDF writes are atomic and backed up for undo; XMP changes remain non-destructive adjacent `.xmp` sidecars.

### Nexa SDK Backend (NEW in v8.0)

Alternative local AI backend using Nexa SDK (adapted from Local-File-Organizer):

| Feature | Description |
|---------|-------------|
| LLaVA Vision | Image understanding and description via LLaVA v1.6 |
| Llama 3.2 Text | Text summarization and classification via Llama 3.2 3B |
| One-Click Switch | Toggle between Ollama and Nexa in Settings |
| Image Classification | Vision model describes images, text model classifies |
| File Content Analysis | Reads text files and generates summaries for classification |
| Model Catalog | 5 pre-configured model options for vision and text |

Enable in **Settings > Ollama LLM > Alternative Backend: Nexa SDK**. Requires `pip install nexaai`.

### AI Classification

| Feature | Description |
|---------|-------------|
| Ollama LLM | Local AI-powered category + name inference via Ollama |
| Explicit Ollama Setup | Checks local Ollama/model readiness and points to Settings/manual setup when missing |
| 384+ Built-in Categories | Covers design, video, audio, print, web, 3D, photography |
| 7-Level Pipeline | Extension > Keyword > Fuzzy > Metadata > Composition > Context > LLM |
| Multiple Profiles | Design Assets, Book Library, PC Files, Photo Library, and custom profiles |
| Multiple Libraries | Switch registered Tag Libraries from the sidebar with scoped AI, rules, and theme preferences |
| Color Palette Search | Index dominant image colors and search with `color:blue` or natural color-tone phrases |
| Rules Editor | Custom if/then rules with condition builder UI |
| Natural Language Rules | Compile one routing request into a local, reviewable action plan |
| Rename Templates | Token-based rename templates with live preview and move-time rendering, including media season/episode tokens |

### Natural Language Rules

Open **Settings → Natural Language Rules**, describe one routing request, and
choose the source folder. UniFile asks the configured provider for one
structured rule, evaluates matching files locally, and previews the resulting
action DAG with exact source and destination paths. Click **Apply approved
plan** only after reviewing the rows; the apply step makes no further AI calls,
never overwrites an existing file, and records successful moves for undo.

### Multiple Libraries

Register existing library folders with the **+** control in the sidebar's
**LIBRARY** section. The active selector switches the open Tag Library and
keeps each library's Ollama model/settings, classification rules, and theme in
its own `.unifile` folder. Opening a folder directly from the Tag Library also
registers it automatically; forgetting a registration never deletes its files.

### Color Palette Search

Images added or scanned into a Tag Library receive a small, deterministic
dominant-color palette index. Use **Index Colors** in the Tag Library header to
rebuild the index for existing images, then search with `color:blue` or phrases
such as `show me files with predominant blue tones`. Searches remain local and
read-only; unsupported or unreadable images are simply left without palette rows.

### Custom Field Schemas

Open **Field Schemas** in the Tag Library header to add fields scoped to the
active library. Currency fields support optional minimum and maximum values;
status fields use a fixed choice list; dates normalize to `YYYY-MM-DD`; and
checkboxes accept true/false values. Select one file and choose **Edit Fields**
to update built-in or custom metadata. Invalid values are rejected before they
reach the library database, and blank values clear the stored field.

### Voice Control

Open **Settings → Voice Control** or press `Ctrl+Shift+V` to type a command or
transcribe an existing audio/video file with the configured offline Whisper
model. Local grammar handles scan, tag, and search actions (including phrases
such as `show me large video files`); an optional AI fallback is explicit and
disabled by default. Every command is previewed before it runs, and tag writes
require the dialog's review button.

### Organization Modes

| Mode | Description |
|------|-------------|
| Categorize Folders | Sort folders into category groups using AI + rules |
| Categorize + Smart Rename | Full AI rename + categorization in one pass |
| PC File Organizer | Sort individual files by extension/type with per-category output paths |
| Rename .aep Folders | Rename After Effects project folders by their largest `.aep` filename |

### Cleanup Tools

| Tool | Description |
|------|-------------|
| Empty Folders | Find and delete empty directories |
| Empty Files | Find zero-byte files |
| Sweep | Review empty folders, zero-byte files, and broken shortcuts in one pass; move selected results to undoable UniFile Recovery |
| Temp / Junk Files | Find `.tmp`, `.bak`, `Thumbs.db`, etc. |
| Broken Files | Detect corrupt/truncated files |
| Big Files | Find files above a configurable size threshold |
| Old Downloads | Find stale files in download folders |

### Duplicate Finder

- Progressive hash-based detection: Size > Prefix hash > Suffix hash > Full SHA-256
- Perceptual image hashing for near-duplicate photos
- Side-by-side comparison dialog
- Configurable similarity tolerance

### Photo Organization

- EXIF metadata extraction (date, camera, GPS)
- Photo map view with geotagged markers (Leaflet)
- AI event grouping — cluster photos by vision descriptions
- Face detection and person-based organization (optional)
- Virtualized thumbnail grid with fixed-size item delegates and visible-item loading; large PC result tables use a lazy `QAbstractTableModel`/`QTableView` surface instead of one widget per result
- Shared thumbnail cache stores encoded previews in a bounded SQLite-indexed filesystem cache with read-only `mmap` reads and LRU eviction; configure or clear it at Settings → All Settings → System → Thumbnail Cache

### Watch Mode

- Monitor folders and auto-organize new files
- System tray integration with minimize-to-tray
- Watch history log with timestamps

### Windows Shell Integration

- `unifile install-shell` adds "Organize with UniFile" to folder context menus and the Send To menu.
- Explorer launches include `--source <folder> --show-preview`, so a shell-opened folder is scanned and the review preview opens automatically.

### UI & UX

| Feature | Description |
|---------|-------------|
| 6 Color Themes | Steam Dark, Catppuccin Mocha, OLED Black, GitHub Dark, Nord, Dracula |
| Review-First Workspace | Stronger hierarchy, calmer action layout, richer empty states, and clearer trust/status messaging across the main shell |
| Premium Secondary Panels | Tag Library, Media Lookup, and Virtual Library now use clearer section hierarchy, calmer states, and theme-aware premium surfaces |
| Refined Editor Workflows | Category and rule editors now use better summaries, calmer action emphasis, and clearer preview-oriented guidance for power users |
| Guided Helper Dialogs | Before/After, Event Grouping, and rename-source picking now surface stronger summaries and more intentional review-first guidance |
| Live Theme Preview | See themes applied instantly before committing |
| Sidebar Navigation | Left panel with Organizer, Cleanup, Duplicates, Tag Library, Media Lookup |
| Before/After Preview | Visual directory tree comparison |
| Dashboard Chart | Interactive category distribution with drag-reassign |
| File Preview Panel | Split-view with image preview, text excerpt, metadata |
| Drag & Drop | Drop folders onto the window to set source |
| Undo Timeline | Visual timeline of all operations with one-click rollback |
| Trusted Plugin System | Python plugins are discovered but disabled until explicitly trusted; changed plugins must be re-trusted |

### Safety

- **Preview before apply** — full destination tree preview before any files move
- **Protected paths** — system folders guarded at scan, apply, and delete layers
- **Safe merge-move** — merging into existing folders preserves all files
- **Progressive hash dedup** — SHA-256 + perceptual hash prevents overwrites
- **Full undo log** — every operation recorded with one-click rollback
- **SQLite transaction replay** — apply operations are journaled in WAL mode and can be replayed newest-first by batch or by a configurable last-N count from Undo Timeline
- **Disk space protection** — bulk moves and renames stop before execution when the destination would fall below the configurable free-space floor (500 MB by default); configure it in Settings → All Settings → System
- **Checkpointed scans** — PC scans persist completed results to SQLite in 500-item batches and resume interrupted work without reclassifying unchanged items
- **Background scan throttle** — scans yield between items and pause on known battery power by default; configure pacing and battery behavior in Settings → All Settings → System
- **CSV audit trail** — every classification logged with timestamp, method, confidence
- **Confidence tiers** — Auto-apply (90%+), Suggest (70–89%), and Skip (<70%) labels; scheduled applies use only the high-confidence tier, with per-profile overrides in Settings → All Settings → Confidence Tiers
- **Crash handler** — unhandled exceptions saved to crash log with MessageBox notification
- **Redacted diagnostics export** — Settings > Tools creates a support ZIP with paths, emails, and API keys removed
- **Plugin trust gate** — local Python plugins are fingerprinted and must be explicitly trusted before execution

## Architecture

```
unifile/
├── __init__.py          # Package version
├── __main__.py          # Entry point with crash handler
├── bootstrap.py         # Optional dependency probes + explicit opt-in installer
├── config.py            # Settings, themes, protected paths
├── categories.py        # 384+ category definitions
├── classifier.py        # 7-level classification engine
├── engine.py            # Rule engine, scheduler, templates
├── naming.py            # Smart rename logic
├── metadata.py          # File metadata extraction
├── thumbnail_cache.py   # Shared mmap-backed thumbnail cache with LRU eviction
├── virtualized_view.py  # Paged PC results model and thumbnail-grid delegates
├── ollama.py            # Ollama LLM integration
├── photos.py            # Photo/EXIF/face processing
├── files.py             # PC file organizer logic
├── cache.py             # Classification cache, undo log
├── models.py            # Data models (ScanItem, etc.)
├── workers.py           # QThread workers for scanning/applying
├── plugins.py           # Plugin system, profiles, presets
├── profiles.py          # Scan profile management
├── confidence.py        # Per-profile confidence tiers and auto-apply policy
├── cleanup.py           # Cleanup scanners (6 types)
├── duplicates.py        # Duplicate detection engine
├── widgets.py           # Custom Qt widgets (charts, map, preview)
├── main_window.py       # Main application window (UniFile class)
├── nexa_backend.py      # Nexa SDK AI backend (LLaVA + Llama 3.2)
├── scan_mixin.py        # Scan pipeline + auto-tag integration
├── apply_mixin.py       # Apply/move operations
├── tagging/
│   ├── db.py            # SQLAlchemy engine, Base, PathType
│   ├── models.py        # Tag, Entry, Folder, ValueType ORM models
│   └── library.py       # TagLibrary CRUD API
├── media/
│   └── providers.py     # Video, book, audiobook, and audio APIs + guessit parser
└── dialogs/
    ├── tag_library.py   # Tag Library browser panel
    ├── media_lookup.py  # Media Lookup panel (video/book/audio search)
    ├── cleanup.py       # Cleanup results dialog
    ├── duplicates.py    # Duplicate comparison dialog
    ├── editors.py       # Rules/category editors
    ├── settings.py      # Settings dialog
    ├── theme.py         # Theme preview dialog
    └── tools.py         # Tool dialogs
```

## Configuration

### Ollama Settings

Click **Settings > Ollama LLM** to configure:

| Setting | Default | Description |
|---------|---------|-------------|
| URL | `http://localhost:11434` | Ollama server address |
| Model | `qwen2.5:7b` | Model for classification |
| Timeout | 30s | Per-item LLM timeout |
| Vision batch size | 32 | Images grouped into one multimodal request; failed images retry individually |

### Provider Health

Open **Settings > AI & Intelligence > Provider Health** to review local request
history for configured AI providers. The dashboard shows average latency, error
rate, input/output token totals, optional estimated token cost, and a compact
latency sparkline. **Probe Enabled Providers** runs reachability checks in the
background; history is stored locally in `ai_provider_health.json` and errors
are redacted before storage.

The **AI Providers** settings also support native Anthropic Messages and
Google Gemini `generateContent` adapters. They use the configured API key from
the local keyring, send structured-output requests where supported, and keep
the existing priority-based fallback chain.

### Confidence Tiers

Classification results are labeled by confidence: **Auto-apply** (90% or higher), **Suggest** (70–89%), or **Skip** (below 70%). Scheduled `--auto-apply` jobs select only Auto-apply rows; interactive scans keep Suggest rows available for review. Open **Settings → All Settings → Confidence Tiers** to override the thresholds for each built-in scan profile.

Manual category corrections are retained as local few-shot examples and the 10 most recent examples are supplied to later AI classifications as quoted hints. They are included in rules-bundle export/import and never require a remote learning service.

**Recommended models:**

| Model | Size | Speed | Accuracy | Install |
|-------|------|-------|----------|---------|
| `qwen2.5:7b` | 4.7 GB | Medium | Best | `ollama pull qwen2.5:7b` |
| `llama3.2:3b` | 2.0 GB | Fastest | Good | `ollama pull llama3.2:3b` |
| `gemma3:4b` | 3.3 GB | Fast | Good | `ollama pull gemma3:4b` |
| `mistral:7b` | 4.1 GB | Medium | Good | `ollama pull mistral:7b` |

### Themes

6 dark themes with live preview: **Steam Dark** (default), **Catppuccin Mocha**, **OLED Black**, **GitHub Dark**, **Nord**, **Dracula**.

## CLI Usage

```bash
python run.py                                          # Launch GUI
python run.py --install-deps                           # Opt in to dependency bootstrap
python run.py --source "C:/Users/You/Downloads"        # Auto-scan a folder
python run.py --profile MyProfile --auto-apply         # Automated profile scan
python run.py --dry-run --profile MyProfile            # Simulate without moving
python run.py --source DIR --output-json plan.json     # Export scan plan as JSON
python -m unifile                                      # Alternative launch
python -m unifile --version                            # Print version

# Headless classification (no GUI, no Qt)
python -m unifile classify path/to/file.pdf --json
python -m unifile classify path/to/folder --json
python -m unifile scan path/to/inbox --json --destination path/to/organized
python -m unifile scan path/to/inbox --apply-rules --destination path/to/organized
python -m unifile scan path/to/inbox --apply-rules --dry-run --output-json plan.json
python -m unifile verify path/to/library --json --output health.json
python -m unifile nfo generate path/to/movie.mkv --metadata-json metadata.json --json
python -m unifile nfo generate path/to/episode.mkv --kind episode --no-overwrite

# Inventory subcommands (no GUI)
python -m unifile list-profiles --json
python -m unifile list-models --url http://localhost:11434 --json

# Manifest-backed plugin scaffolding (no GUI required)
python -m unifile plugin create --name "My Plugin"
python -m unifile plugin create --name "My Plugin" --output C:/path/to/plugins --json

# Qt-free Flask API (set UNIFILE_API_KEY for non-health routes)
python -m unifile serve --host 127.0.0.1 --port 8787
curl http://127.0.0.1:8787/health
```

The `classify` subcommand is safe to use in cron jobs and CI — it loads
**zero Qt modules** and runs purely against the rule-based classifier.
`scan` is also Qt-free and review-first: it prints or exports a versioned move
plan, and only `--apply-rules` performs collision-safe moves. Use
`--destination` to place category folders beneath an explicit root; without it,
the command uses the same configured category destinations as the desktop app.
Only results at or above the default 80% confidence floor are candidates, and
`--min-confidence` can adjust that threshold.

### Headless Docker deployment

`docker-compose.yml` starts `unifile-api` and Ollama with separate library,
SQLite, and model volumes. Configure `UNIFILE_API_KEY`, `SCAN_INTERVAL` (seconds,
rounded to a cron minute), and `OLLAMA_URL` before running:

```bash
docker compose up -d --build
curl -H "X-API-Key: $UNIFILE_API_KEY" http://127.0.0.1:8787/health
```

The API exposes authenticated `/scan`, `/tag`, `/search`, `/report`, and
scheduled-job routes plus a small `/admin` status page. It is review-first:
scans return the same versioned JSON plan shape used by `--output-json`, while
tag writes are explicit. Leave `UNIFILE_ALLOW_UNAUTHENTICATED=0` in shared
deployments.

`unifile verify` and the authenticated `/verify` endpoint maintain a
library-local `.unifile/file_health.json` ledger. The first verification
establishes SHA-256 baselines; later runs report changed, missing, and unstable
files without modifying the source tree. Export a JSON, CSV, or text diff with
`--output`, or schedule a `verify` job through `/jobs` (for example `0 3 * * 0`
for weekly checks) and set its `health_log` path for persistent log export.

### Mobile Companion

Start the read-only LAN browser on demand. UniFile prints an authenticated URL with a random token; open it from a phone on the same network and optionally install it as a PWA:

```bash
python -m unifile mobile --library /path/to/unifile-library
```

The companion browses entries, tags, fields, search results, and image previews. Mobile mode rejects every non-GET request, does not expose tag/scan/job writes, keeps paths relative to the configured library, and generates thumbnails in memory when Pillow is available. Use `--host 127.0.0.1` for local-only access or set `UNIFILE_MOBILE_HOST` / `UNIFILE_MOBILE_PORT` for a different bind address and port.

### Collaborative LAN Tagging

For a shared library, initialize a library-scoped administrator and create role-limited tokens locally:

```bash
python -m unifile collab init --library /path/to/unifile-library --user-id admin
python -m unifile collab add-user --library /path/to/unifile-library --user-id editor --role editor
python -m unifile collab add-user --library /path/to/unifile-library --user-id viewer --role viewer
python -m unifile serve --library /path/to/unifile-library --collaborative --host 0.0.0.0 --port 8787
python -m unifile collab search http://server:8787 --user viewer --token TOKEN --query "tag:important"
python -m unifile collab tag http://server:8787 --user editor --token TOKEN --entry-id 42 --tag important
```

The server stores only SHA-256 token hashes in `.unifile/collaboration.json`. Viewers can search, editors can apply existing tags, and administrators can manage tags, per-tag role ACLs, rules, users, and the audit log. `tag:confidential` is administrator-only by default. Tag writes use per-field timestamps and return a `409` conflict with the current version when a stale client write loses.

### JSON scan plan format

`--output-json <path>` writes a plan file after the scan completes. Use it
to integrate UniFile with other tooling (e.g. feed plans into `jq` / an
approval queue / a CI job):

```json
{
  "version": "1",
  "timestamp": "2026-04-22T14:30:00",
  "source": "C:/Users/You/Downloads",
  "mode": "PC File Organizer",
  "items": [
    { "name": "invoice.pdf", "src": "...", "dst": "...",
      "category": "Documents", "confidence": 90, "method": "extension",
      "size": 45312, "selected": true, "status": "Pending" }
  ]
}
```

## Prerequisites

- **Python 3.10+**
- **8 GB RAM** minimum (for Ollama LLM models)
- **~5 GB disk space** for the default `qwen2.5:7b` model
- **Internet connection** only when you choose to install dependencies or download AI models
- Works without Ollama — falls back to rule-based engine automatically

Install optional dependencies with `pip install -e ".[full]"`. Missing optional packages disable their related feature instead of triggering runtime installs. `pyproject.toml` is the dependency source of truth; parser-heavy optional packages use audited lower bounds and `requirements.txt` delegates to the runtime/dev extras.

For local semantic embeddings, install `pip install -e ".[onnx]"` (or `.[onnx-gpu]` instead for the CUDA runtime) and place an exported `all-MiniLM-L6-v2` ONNX graph (`model.onnx`) plus `tokenizer.json` under `%APPDATA%\UniFile\models\all-MiniLM-L6-v2` (or select another folder in Semantic Search Settings). Auto mode prefers CUDA when available, falls back to the ONNX CPU provider, and then uses Ollama when no local graph is present.

For optional semantic duplicate detection, use the same ONNX extra and select the **Semantic duplicates (CLIP/SigLIP)** option in Duplicate Finder. Choose a local exported image graph named `model.onnx` or `vision_model.onnx`; it must accept NCHW float32 `pixel_values` and return one `[batch, embedding]` vector per image. The default cosine threshold is `0.92` and can be changed in the dialog. UniFile never downloads the image model or requires PyTorch for this feature.

For workflow scripts, open **Tools → Plugins**, create or edit a script in the embedded editor, validate it, and explicitly choose **Trust & Enable** before it can run. Scripts live under `%APPDATA%\UniFile\plugins` and declare `Workflow-Hook: on_scan_item` or `Workflow-Hook: on_apply` in their module docstring. The restricted `unifile.script` API exposes `item`, `classifier`, `tag_library`/`library`, `file_ops`, and `log`; imports and arbitrary standard-library access are rejected, and each hook runs in a bounded child process. Tag commands are applied only when a Tag Library is open; file-operation commands remain disabled by default unless a host supplies explicit allowed roots.

Manifest-backed plugins live in a folder containing `plugin.yaml` and a Python entrypoint. The manifest declares a stable `id`, display name/version, and a list or mapping of supported hooks to public function names. UniFile validates the YAML and entrypoint path before discovery, includes the manifest in the trust fingerprint, and keeps untrusted or changed packages disabled. **Tools → Plugins → Community Plugin Index** reads a bounded HTTPS JSON catalog for browsing only; it never downloads or executes catalog entries.

Developer checks:

```bash
make dev         # install runtime + dev extras
make deps-check  # verify pyproject/requirements/bootstrap alignment
make test        # deps-check + full pytest, including pytest-qt smoke tests
make lint        # Ruff
make audit       # pip-audit --local
make build       # clean PyInstaller build + frozen --version/classify/GUI smoke + SHA-256
make build-smoke # rerun frozen smoke/checksum against an existing dist/UniFile/UniFile.exe
```

## Related Tools

| Tool | Best For |
|------|----------|
| **UniFile** (this repo) | Everything — AI classification, tag library, media lookup, vision AI, cleanup, duplicates, photo organization |
| [FileOrganizer](https://github.com/SysAdminDoc/FileOrganizer) | Focused file organization without the tag library overhead — lighter, simpler, same core classification engine |

UniFile is built directly on FileOrganizer's foundation. If you only need folder sorting and cleanup without tag-based library management or media metadata, [FileOrganizer](https://github.com/SysAdminDoc/FileOrganizer) is the lighter option.

## Roadmap

- [x] **Media Lookup** — TMDb/OMDb/TVMaze metadata panel (from mnamer's provider system)
- [x] **Nexa SDK Backend** — Alternative AI backend with Llama 3.2 + LLaVA vision (from Local-File-Organizer)
- [x] **Category Presets** — Per-directory config, import/export, extension-based presets (from classifier)
- [x] **Search Query Language** — Advanced tag search with boolean operators (tag:, ext:, field:, AND/OR/NOT)
- [x] **Preview Panel** — Rich file preview with tag overlay, image thumbnails, metadata, and field display

## License

MIT License — see [LICENSE](LICENSE) for details.
