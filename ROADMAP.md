# Roadmap

Forward-looking plans for UniFile — unified AI-powered file organizer (PyQt6 + SQLAlchemy + Ollama).  
Current version: **v9.3.32**. Merges TagStudio, FileOrganizer, Local-File-Organizer, classifier, and mnamer into one desktop app.

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

---

## Medium-Term (v10.x)

Larger features requiring non-trivial architecture or multi-week effort.

---

## Long-Term / Vision

Strategic / aspirational features. Some require significant architecture changes or external dependencies.

---

## AI & Inference

---

## Library & Tags

---

## Media Metadata


---

## Cleanup & Safety


---

## Performance & Scale

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
- **Test coverage baseline** — current tests cover critical paths; target: 60% coverage on `classifier.py`, `engine.py`, `learning.py`, `tagging/library.py`; enforced locally via `pytest-cov`
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

## Research-Driven Additions

No actionable items remain. All research-driven additions have been implemented.

## Audit-Identified Hardening

No actionable hardening items remain.
