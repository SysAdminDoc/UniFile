# Roadmap

Forward-looking plans for UniFile — unified AI-powered file organizer (PyQt6 + SQLAlchemy + Ollama).  
Current version: **v9.3.20**. Merges TagStudio, FileOrganizer, Local-File-Organizer, classifier, and mnamer into one desktop app.

---

## Table of Contents

1. [Near-Term (v9.4 – v9.6)](#near-term-v94--v96)
2. [Medium-Term (v10.x)](#medium-term-v10x)
3. [Long-Term / Vision](#long-term--vision)
4. [AI & Inference](#ai--inference)
5. [Library & Tags](#library--tags)
6. [Media Metadata](#media-metadata)
7. [Cleanup & Safety](#cleanup--safety)
8. [Performance & Scale](#performance--scale)
9. [Automation & CLI](#automation--cli)
10. [UX & Accessibility](#ux--accessibility)
11. [Distribution & Packaging](#distribution--packaging)
12. [Developer Ecosystem](#developer-ecosystem)
13. [Competitive Research](#competitive-research)
14. [Open-Source Reference Projects](#open-source-reference-projects)

---

## Near-Term (v9.4 – v9.6)

High-impact, achievable improvements. Each item is scoped to a few days–one week of work.

### Windows Shell Integration
- **Context menu handler** — register "Organize with UniFile" on right-click for folders; launches UniFile with `--source <path> --show-preview`; done via a minimal `.reg` file or installer step that writes `HKCU\Software\Classes\Directory\shell\UniFile`
- **Send To shortcut** — installer drops `UniFile.lnk` into the user's `SendTo` folder as the zero-dependency fallback
- **Explorer preview pane** — optional IThumbnailProvider COM shim to show UniFile category badge on folder icons; lower priority, Windows-only

### Keyboard Navigation & Accessibility
- Full Tab-order through all panels (main tree → tag library → results → toolbar)
- Space/Enter to expand folders and trigger actions; arrow keys to navigate trees
- Ctrl+K — Spotlight-style command palette: type `scan`, `tag`, a profile name, or a file query; results update instantly with inline thumbnail preview
- Ctrl+T to focus tag search; Ctrl+S to start scan; Alt+1–9 to switch profiles
- `setAccessibleName()` + `setAccessibleDescription()` on all major widgets for NVDA/JAWS screen reader compatibility
- High-contrast theme (WCAG AA: pure black bg, pure white text, bright accents) as a seventh theme option
- Configurable base font size in Settings → Accessibility (8–20 pt, scales all UI elements proportionally)

### Archive Content Indexing
- Scan inside `.zip`, `.rar`, `.7z`, `.tar.*` archives without extracting — index the file listing and inner filenames into the tag library and semantic search index
- Extraction mode (per-profile toggle): "Extract to temp → classify → repackage" for full AI classification of archive contents; temp path `%LOCALAPPDATA%\UniFile\temp`, always cleaned up
- Surface results in tag search UI: "invoice.pdf (inside 2024-Invoices.zip)" with path breadcrumb
- Dependencies: `zipfile` (stdlib), `py7zr`, `rarfile`

### Spotlight-Style Search Bar
- Ctrl+K command palette: instant file/tag/category search with thumbnail preview pane on hover; results show top 5 matching files before pressing Enter
- Chainable filters without closing (`tag:photo date:2024 ext:raw`)
- History of last 20 queries; arrow-up to cycle
- Analogous to Notion's database search / Bear's tag search

### Saved Searches with Cached Results
- Save any tag/filter query as a named Smart View; materialized as a sidebar item under "Smart Views"
- Cache result set (file list + date computed); show "Last updated X ago" with Refresh button
- Optional scheduled refresh: nightly rescan at configurable time, badge sidebar icon when results change
- Export cached results to JSON or CSV

### Inbox / Quick Capture Pattern
- Designate any folder as the "Inbox" — files added there auto-receive `tag:inbox` (no moving)
- Dashboard widget: "X files in inbox" → click → filter to inbox files
- Batch action on selected inbox files: "Move to Library" → applies chosen destination rule and clears `tag:inbox`

---

## Medium-Term (v10.x)

Larger features requiring non-trivial architecture or multi-week effort.

### Batch Metadata Spreadsheet Editor
- Spreadsheet-like grid: filename | current XMP/EXIF | proposed new value | accept/reject checkbox
- Conflict detection: highlight rows where a field is already populated with a different value
- Batch write with per-field undo; all writes logged to the existing embed log
- Especially useful for photographers ingesting 1000+ RAW files and needing to bulk-apply EXIF location, copyright, or caption fields

### Collections / Visual Boards
- Non-hierarchical "Collection" grouping — drag any files from any folder into a named collection
- Board view: Kanban-style columns per collection; thumbnail cards with hover metadata
- Collections stored in the tag library database as a special entry type; no files are moved
- "Add to collection" from right-click context menu in any panel
- Export collection as ZIP or as a folder of symlinks

### Multi-Root Library
- Single tag library that spans multiple drives, network shares, or external drives
- Each root gets a status indicator (online / offline / read-only)
- Broken-link detection and re-link wizard when a root goes offline and comes back at a different path
- Builds on top of the existing `VirtualLibrary.relink_file()` foundation

### Cloud / Remote Storage Awareness
- **Phase 1 (Rclone adapter)**: read-only scan of any rclone remote (S3, GCS, OneDrive, Dropbox, Backblaze B2, SFTP); downloads filtered subsets for local classification; optional sync-back of tag sidecars
- **Phase 2 (native OneDrive/Dropbox)**: detect locally-synced cloud folders; handle placeholder/stub files gracefully (skip or trigger on-demand hydration via Windows cloud file API)
- Settings panel: "Cloud Remotes" tab with rclone remote name, scan mode (list-only / download / sync-back), download filter (size cap, extension whitelist)

### GPU-Accelerated Embeddings via ONNX Runtime
- Replace Ollama embedding endpoint dependency with `onnxruntime` + `sentence-transformers/all-MiniLM-L6-v2` (ONNX export ~23 MB)
- 10–50× speedup for batch embedding on NVIDIA/AMD GPUs; automatic CPU fallback if no GPU detected
- Eliminates the Ollama dependency for semantic search — works offline with no model download
- Settings: "Embedding Backend" → Auto / ONNX (local) / Ollama

### CLIP-Based Near-Duplicate Detection
- OpenAI CLIP (or SigLIP) vision encoder to detect near-duplicate images that differ by crop, compression, slight color shift, or watermark removal — cases perceptual hashing misses
- GPU-batch encode all images → cosine similarity matrix → cluster at configurable threshold (0.92 default)
- Results integrated into the existing Duplicate Finder dialog: new "Semantic Duplicates" tab alongside hash-based results
- Optional: `clip-embed` via ONNX to avoid PyTorch dependency

### Workflow Scripting (Python Hooks)
- Expose `classifier`, `tag_library`, `file_ops` to user-authored hook scripts via a sandboxed `unifile.script` API
- Script editor embedded in the Plugin panel with live debugger output
- Example: after classification, if `item.category == "Photo"` and `item.size > 10_000_000` → `library.add_tag(item, "hires")`
- Execution model: scripts run in a `QThread` with a timeout watchdog; cannot import arbitrary stdlib modules by default

### YAML Declarative Plugin Manifest
- YAML descriptor for plugins (alongside the existing Python hook system):
  ```yaml
  id: plugin.my_classifier
  name: My Custom Classifier
  version: 1.0
  hooks:
    - on_scan_item: classify_custom
    - on_apply: log_movement
  ```
- CLI scaffolding: `unifile plugin create --name "My Plugin"` generates the boilerplate directory structure
- Community plugin discovery: GitHub-hosted index (plain JSON), browsable from Settings → Plugins

---

## Long-Term / Vision

Strategic / aspirational features. Some require significant architecture changes or external dependencies.

### NAS / Docker Headless Deployment
- Official `docker-compose.yml` in repo: `unifile-api` service + `ollama` service; volumes for library and DB; `SCAN_INTERVAL`, `OLLAMA_URL` env vars
- Synology/QNAP `.spk`/`.qpkg` install package
- Built-in job scheduler: cron-style scan/tag runs; email digest reports when results change
- Extends the planned Flask REST API with an admin UI for headless configuration

### TagStudio Library Import / Export
- Import an existing TagStudio `.db` library into UniFile's SQLAlchemy schema (entries, tags, fields, thumbnails)
- Export UniFile tag library back to TagStudio format for cross-migration
- Users can run both tools on the same library without destructive conflict; TagStudio's non-destructive philosophy is preserved

### Calibre / OpenLibrary Ebook Mode
- Dedicated "Book Library" profile: scan ebooks (`.epub`, `.pdf`, `.mobi`, `.azw3`), extract metadata (title, author, ISBN via `isbnlib`), fetch cover art + synopsis from OpenLibrary/Google Books
- Auto-tag by genre, language, series, reading status
- Export virtual library to Calibre-compatible `metadata.opf` sidecars for round-trip compatibility

### Video Project Awareness (AE, Premiere, DaVinci, FCPX)
- Parse `.aep`, `.prproj`, `.drp`, `.fcpbundle` project files to discover all referenced media assets
- Tag referenced files with the parent project name and last-modified date
- "Project Audit" view: which assets are referenced by multiple projects; which are orphaned

### Mobile Companion App (Read-Only LAN Browser)
- Lightweight web server started on demand; accessible from phone browser on local network
- Browse tag library, search, preview thumbnails; no write operations
- Progressive Web App (PWA manifest, installable to home screen)
- Possible implementation: `bottle.py` + Jinja2 templates + base64 thumbnails; or Pyodide WASM for in-browser classifier

### Collaborative LAN Tagging
- Multi-user mode: UniFile exposes tag library over LAN; other instances connect as clients
- Role-based permissions: Admin (edit tags + rules), Editor (apply tags), Viewer (search only)
- Conflict resolution: last-write-wins with per-field timestamp; audit log of all tag changes by user
- Per-tag access control: `tag:confidential` visible only to Admin role

### File Health Monitor / Bit-Rot Detection
- Compute and store SHA-256 checksums on first scan; re-verify on subsequent scans
- Alert on checksum mismatch (file modified without expected change) — indicator of storage corruption
- Dashboard widget: "X files verified, Y changed unexpectedly" with diff view
- Optional scheduled verification (nightly, weekly) with log export

### Voice Control Integration
- Trigger common actions by voice: "tag all 2024 Florida photos as vacation", "scan Downloads folder", "show me large video files"
- Implementation: Whisper (already integrated for transcription) as the STT engine; intent parsing via the existing LLM classification pipeline with a voice-action grammar
- Activate with a configurable hotkey or "Hey UniFile" wake word via `pvporcupine` (offline)

---

## AI & Inference

- **Batched LLM inference** — collect N scan items into a single prompt call; reduces wall-clock time proportionally for large trees; configurable batch size (default 10)
- **Confidence tiers** — per-level thresholds: auto-apply ≥ 0.90, suggest 0.70–0.89, skip < 0.70; override per profile
- **Few-shot correction store** — when user overrides an LLM result, append `(folder_name, correct_category)` to a local examples file; inject top-10 examples into the system prompt
- **Batched vision inference** — queue 32 images, encode in a single forward pass (Nexa SDK / ONNX); 30× faster than one-at-a-time for photo libraries
- **Provider health dashboard** — Settings panel showing latency, error rate, and token cost for each configured AI provider; sparkline per provider
- **Anthropic Claude / Gemini adapters** — extend `AIProvider` with Claude (messages API) and Gemini (generateContent API) as additional OpenAI-compat variants
- **Natural language rules** — "all screenshots older than 30 days → Archive/Screenshots/YYYY-MM"; compiled to an action DAG, previewed before apply; uses the LLM to parse the rule once, then runs rule-engine locally

---

## Library & Tags

- **Multi-library support** — switch libraries from the sidebar; each library has its own Ollama model selection, rules, and theme preference
- **Tag implication rules** — "kitten" → "cat" → "animal" (Hydrus Network-style graph); implications stored in a `tag_implications` table; propagated automatically on tag application
- **Tag siblings** — mark two tags as synonyms; applying one auto-suggests the other; Hydrus's sibling DB layout as the reference
- **Saved searches + Smart Views** — any query saved as a persistent Smart View; materialized in sidebar with file count badge
- **XMP sidecar writer** — write tags to `.xmp` sidecar files alongside originals so tags survive outside UniFile; supports TagStudio sidecar format for round-trip compatibility
- **Rule-based auto-tagging** — classifier extension + regex rules merged with LLM output; fire after every scan apply
- **Color extraction** — extract dominant palette from images; index by color; "show me files with predominant blue tones" search; analogous to Eagle's color search
- **Star ratings & review flags** — 1–5 star rating field + "Needs Review" / "Approved" / "Rejected" status enum; shown as icon overlays on thumbnails
- **Custom field schemas per library** — define additional field types per library (Budget/currency, Deadline/date, Status/enum); validation rules enforced in the editor

---

## Media Metadata

- **TMDb / TVDb / MusicBrainz / OpenLibrary** — full mnamer feature parity: movie, TV, audiobook, book lookup; multi-provider fallback chain
- **Auto-rename template engine** — format string: `{title} ({year}) - S{season:02d}E{episode:02d}{ext}`; live preview in settings; applied at move time
- **Chapter + subtitle downloader** — fetch `.srt`/`.ass` subtitles from OpenSubtitles API; chapter metadata from TMDb; saved alongside media file
- **EXIF/XMP/ID3 viewer + editor pane** — read/write any metadata field; changes previewed before write; backed by `piexif`, `mutagen`, `pypdf`
- **Cover art fetcher** — for media files missing embedded artwork: fetch from TMDb poster, MusicBrainz Cover Art Archive, or OpenLibrary; embed into file metadata
- **NFO file generator** — emit Kodi/Plex-compatible `.nfo` XML alongside media files; field mapping from tag library entry fields
- **RAW photo family recognition** — CR2, NEF, ARW, ORF, DNG; treat RAW + JPEG pairs as a single logical item; EXIF-first tagging using RAW sidecar when JPEG lacks full EXIF

---

## Cleanup & Safety

- **Empty-folder / zero-byte / broken-shortcut sweeper** — all three combined in one pass with preview + undo journal (already partially implemented; unify into a single "Sweep" action)
- **Recycle Bin integration** — `send2trash` for all destructive operations (already a dependency; verify all delete paths use it); confirm 30-day recovery via Windows Recycle Bin
- **Disk space protection** — abort scan-apply if free space drops below a configurable threshold (default 500 MB); show warning before any bulk operation
- **Checkpointed scans** — write scan progress to SQLite every 500 items; crash-resume picks up where it left off without re-scanning completed items
- **Transaction log replay** — SQLite WAL with a reverse-iterator to undo the last N apply operations; exposed in the Undo Timeline panel

---

## Performance & Scale

- **Background scanner with throttle** — rate-limit I/O to avoid saturating HDDs; battery-aware throttle on laptops (pause when on battery by default, configurable)
- **Virtualized tree + thumbnail grid** — `QAbstractItemModel` with lazy-load for 500k+ entries; thumbnail grid uses item view with fixed-size delegates; no full-list materialization in memory
- **Memory-mapped thumbnail cache** — LRU-evicted per configurable cap (default 500 MB); SQLite blob or filesystem cache with `mmap` access; shared across library panels
- **Incremental scan** — skip files whose `mtime + size` hasn't changed since last scan; only re-classify new or modified files; configurable "force full rescan" option
- **Parallel classification workers** — spawn N `QThread` workers for rule-based classification (CPU-bound); LLM calls remain single-threaded to respect Ollama's concurrency model
- **ONNX embeddings** — local sentence-transformer model via `onnxruntime`; 10–50× faster than Ollama embedding endpoint on GPU; falls back to CPU if no GPU

---

## Automation & CLI

- `unifile scan /path --apply-rules` — headless scan + apply in one command
- `unifile tag --query 'cat AND outdoor'` — query tag library from shell; pipe to `jq`
- `unifile report --format html --output /tmp/report.html` — export category distribution + file list as HTML/PDF report
- `unifile verify /path` — re-verify checksums for all files in a directory; print mismatches
- **Watch-folder daemon** — `unifile watch /path/to/inbox`; debounced file detection (500 ms settle); newly arrived files classified and optionally moved; `SIGTERM`-safe with graceful flush
- **REST API (Flask)** — headless NAS runs; `/scan`, `/tag`, `/search`, `/report` endpoints; API key auth; JSON responses matching the existing `--output-json` schema
- **Built-in job scheduler** — cron-style: add scan jobs with a time expression (e.g., `0 2 * * *`); runs in background thread; results logged and summarized in dashboard
- **Docker Compose template** — `docker-compose.yml` in repo root; `unifile-api` + `ollama` services; volume mounts for library path and DB; environment variables for all settings

---

## UX & Accessibility

- **Ctrl+K command palette** — Spotlight-style: search files, tags, categories, profiles, and commands; inline thumbnail preview; history of last 20 queries
- **Bidirectional file relationships** — "Related Files" panel in the file info sidebar: similar tags, same photographer, same date range, same name pattern; optional manual "Link" field
- **Timeline view** — histogram of files by creation/modification date; scrub to filter results panel; analogous to Apple Photos date navigator
- **Color-based image search** — pick a color swatch → find images with that dominant color; powered by color palette extracted at index time
- **Keyboard shortcuts dialog** — Settings → Shortcuts; all bindings shown; click any to rebind; no defaults that conflict with OS shortcuts
- **High-contrast theme** — WCAG AA compliant; pure black bg, pure white text, bright accent; seventh theme slot
- **Configurable font size** — Settings → Accessibility → Base font size (8–20 pt); proportional scaling
- **Screen reader support** — `setAccessibleName()` and `setAccessibleDescription()` on all major widgets; tested against NVDA on Windows
- **Right-to-left language support** — `QApplication.setLayoutDirection(Qt.RightToLeft)` toggle; Arabic and Hebrew character rendering via Qt's built-in BiDi support
- **Customizable sidebar** — drag to reorder panels; collapse any section; persist layout to config

---

## Distribution & Packaging

- **Official Windows installer (MSI)** — WiX Toolset; adds Start Menu shortcut, `unifile` to PATH, file association for `.unifile` library files, and shell extension registration
- **Chocolatey / Scoop package** — community-maintainable; updated automatically on each release via CI
- **Homebrew formula** — macOS users `brew install unifile`; formula in `homebrew-unifile` tap
- **Snap package** — `unifile` on Snapcraft for Ubuntu/Debian; confined snap with `home` and `network` plugs
- **Portable ZIP** — no-installer option; `unifile-portable-vX.Y.Z.zip`; auto-detects portable mode and stores all config/DBs adjacent to the exe
- **Auto-update checker** — on startup, poll the GitHub Releases API for a newer version; show unobtrusive banner with "Download" link; no auto-install; respects a `disable_update_check` config flag
- **`unifile-sdk` package on PyPI** — core engine only (no PyQt6); `pip install unifile-sdk`; provides `Classifier`, `TagLibrary`, `SemanticIndex`, `PatternLearner` for embedding in third-party tools

---

## Developer Ecosystem

- **Full type hints (PEP 484)** — all public APIs annotated; `mypy --strict` clean; improves IDE autocomplete and catches integration bugs
- **Sphinx API documentation** — auto-generated from docstrings; published to Read the Docs; includes "How to add a custom classifier" and "How to integrate with S3" tutorials
- **Test coverage baseline** — current tests cover critical paths; target: 60% coverage on `classifier.py`, `engine.py`, `learning.py`, `tagging/library.py`; CI enforced via `pytest-cov`
- **GitHub Actions CI matrix** — Python 3.10/3.11/3.12 on Windows/macOS/Linux; headless Qt tests via `pytest-qt` with `xvfb`; auto-publish to PyPI on tag push
- **YAML plugin manifest + scaffolding CLI** — `unifile plugin create --name "My Plugin"`; community plugin index (hosted JSON); browsable from Settings → Plugins
- **Action DAG dry-run renderer** — LLM produces proposed file actions as a JSON action list; GUI renders a diff view; user approves before atomic apply; same interface used by `--dry-run` CLI flag

---

## Competitive Research

| Tool | Stars | What We Watch | Key Gap to Close |
|------|-------|---------------|-----------------|
| **TagStudio** | 42k | Tag-based library model, non-destructive philosophy | Library format import/export for cross-migration |
| **Hydrus Network** | ~12k | Tag implications/siblings, 500k+ scale, client-server | Tag graph at Hydrus scale (implications, siblings, DB layout) |
| **Eagle App** | commercial | Collections, boards, color palette search, fast thumbnails | Collections panel + color-based search |
| **Calibre** | 24k | Metadata-driven library, format conversion, ebook management | OpenLibrary/ebook mode; Calibre `.opf` sidecar compatibility |
| **digiKam** | KDE | Face recognition training, geolocation clustering, RAW pipeline | Trained face recognition; geolocation clustering from EXIF GPS |
| **FileBot** | commercial | Media renaming format grammar, multi-provider fallback, NFO gen | NFO generator; subtitle downloader; format string parity |
| **Adobe Bridge** | commercial | Batch metadata workflows, saved searches, collection sync | Batch metadata spreadsheet editor |
| **DEVONthink** | commercial | Smart groups, AI-assisted classification, bidirectional links | Bidirectional file relationships; smart groups |

---

## Open-Source Reference Projects

### Related OSS Projects
- https://github.com/hyperfield/ai-file-sorter — local+remote LLM file sorter, preview-before-apply, undo
- https://github.com/QiuYannnn/Local-File-Organizer — Llama3.2 + LLaVA dual-modal (text + vision)
- https://github.com/yousefebrahimi0/Offline-AI-File-Organizer — LM Studio + Mistral offline rename
- https://github.com/thebearwithabite/ai-file-organizer — 3-tier dedup (size → MD5 → SHA256)
- https://github.com/TagStudioDev/TagStudio — tag-based library UX for peer features
- https://github.com/tagspaces/tagspaces — filename-encoded tag interop pattern
- https://github.com/MrRajiii/file-organizer — PyQt5 threaded scanning reference
- https://github.com/lunagray932-ctrl/file-organizer-renamer — 150+ format recognition + RAW photos
- https://pypi.org/project/local-file-organizer/ — 307 tests, daemon/profiles/TUI — polished packaging
- https://github.com/XIVIX134/AI-File-Organizer — multi-provider LLM abstraction pattern

### Architectural Patterns Worth Studying
- **Provider-abstraction layer** — one interface, adapters for each LLM backend, test double for offline CI (already partially implemented in `ai_providers.py`)
- **Action DAG + dry-run renderer** — LLM produces proposed actions as JSON; GUI renders diff; user approves atomic apply
- **Checkpointed scans** — large library scans write progress to SQLite so crash/resume is clean
- **Hydrus tag-sibling/parent DB layout** — `tag_implications(antecedent, consequent)` + `tag_siblings(bad_tag, good_tag)` tables; query-time expansion
- **Sidecar-tag coexistence** — write `.xmp` sidecars in TagStudio format alongside originals; read them back on re-open so tags survive outside UniFile
