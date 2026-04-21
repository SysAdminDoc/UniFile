# Changelog

All notable changes to UniFile will be documented in this file.

## [v8.4.0]

- Added: **Archive name inference engine** (`unifile/archive_inference.py`) — 140+ regex rules classify ZIP/RAR/7z folders by filename patterns (marketplace-aware: Videohive, GraphicRiver, MotionElements; AE subcategories, print, social, seasonal, audio, game dev, 3D, and more)
- Added: `aggregate_archive_names(stems)` voting system — samples all archive names in a folder, computes consensus category with confidence scaling
- Changed: `_scan_folder_once()` now collects archive stems; adds them to `all_filenames_clean` for keyword matching bonus
- Changed: `_classify_composition_from_scan()` — when a folder is ≥25% archives and has ≥2 archives, triggers archive name inference as highest-priority rule
- Added: 4 new categories — `CorelDRAW - Vectors & Assets`, `Apple Motion - Templates`, `Cutting Machine - SVG & DXF`, `After Effects - Cinematic & Trailers`
- Added: 9 new extension mappings — `.cdr` (CorelDRAW), `.motn` (Apple Motion), `.dxf` (cutting machine), `.dds/.tga` (3D textures), `.hdr` (3D HDR), `.fon` (bitmap fonts), `.ait` (Illustrator templates), `.pub` (Publisher)

## [v8.3.0]

- Fixed: **Critical NameError bug** — `DESIGN_TEMPLATE_EXTS`, `VIDEO_TEMPLATE_EXTS`, `FILENAME_ASSET_MAP`, `_GENERIC_DESIGN_CATEGORIES` were defined in `ollama.py` but referenced in `classifier.py` without import; any `tiered_classify()` call on a real folder path would crash
- Changed: Moved and expanded all four constants into `classifier.py` (their actual point of use); removed stale definitions from `ollama.py`
- Added: 10 new categories — `Figma - Templates & UI Kits`, `DaVinci Resolve - Templates`, `CapCut - Templates`, `Game Assets & Sprites`, `Unreal Engine - Assets`, `AI Art & Generative`, `Procreate - Brushes & Stamps`, `Music Production - Presets`, `Music Production - DAW Projects`, `Photography - RAW Files`
- Added: 20 new extension mappings in `EXTENSION_CATEGORY_MAP` covering `.fig`, `.drp/.drfx`, `.als/.flp/.logicx`, `.procreate`, `.nks/.nksn`, `.vstpreset/.fxp/.fxb`, `.unitypackage`, `.uproject/.uasset`, `.ase/.aseprite`, RAW camera formats (`.nef/.cr2/.arw` etc.), `.safetensors/.ckpt`, `.lora`, `.capcut`
- Added: Composition rules for RAW files (≥3 at ≥40% → Photography - RAW Files), DAW projects (any `.als/.flp/.logicx` → Music Production - DAW Projects), MIDI-only folders, and Lightroom preset heavy folders
- Added: Expanded `FILENAME_ASSET_MAP` from 35 → 45+ entries covering Procreate, game assets, music production, RAW photos, calendars, patterns, and more
- Added: `DESIGN_TEMPLATE_EXTS` now includes `.fig`, `.afdesign`, `.afphoto`, `.afpub`, `.sketch`
- Added: `VIDEO_TEMPLATE_EXTS` now includes `.drp`, `.drfx`
- Changed: Keyword expansions across 10 existing categories: After Effects, 3D/3D Materials, Motion Graphics, Backgrounds & Textures, Fonts & Typography, Sound Effects, Lightroom, DaVinci Resolve, CapCut



- Added: CSV sort rules engine (`unifile/csv_rules.py`) — user-editable regex patterns that classify folders without consuming AI tokens
- Added: `CsvRulesDialog` editor accessible via **Tools → Sort Rules...** — add/remove/test rules inline
- Added: CSV rules hooked into both `ScanSmartWorker` and `ScanLLMWorker` (priority: corrections → CSV rules → cache → AI)
- Added: `source_dir` and `mode` metadata stored in every undo batch for richer history display
- Added: Undo history limit increased from 10 → 50 batches
- Changed: Undo timeline now shows mode (categorize / aep / files) and source folder name per batch
- Changed: Undone batches are now archived with `status: 'undone'` instead of deleted from stack — full history preserved
- Changed: Undo logic moved into `UndoTimelineDialog._perform_undo()` — shows confirmation message, refreshes list inline

## [v8.1.0]

- Added: Route AI scans through ProviderChain (OpenAI, Groq, LM Studio, Ollama) — any enabled non-Ollama provider is now used automatically
- Added: `classify_folder_via_chain()` in `ai_providers.py` with full context-building, system/user prompt split, JSON parsing, and category validation
- Added: System message support (`system` param) on `AIProvider.classify()`, `ProviderChain.classify()`, `_openai_chat()`, and `_ollama_generate()`
- Fixed: `context_lines` initialization order bug in `ollama_classify_folder()` (ID-only hints were being overwritten)
- Changed: `_get_ai_backend()` now returns `'providers'` when any non-Ollama AI provider is enabled
- Changed: `ScanLLMWorker` skips Ollama connection check and batching when using provider chain



- docs: add Related Tools section clarifying relationship to FileOrganizer
- Fixed: Fix runtime bug, thread safety, and silent exception swallowing
- Added: Add 15 intelligence and architecture features
- Fixed: Fix NameError bugs found during code audit
- Added: Add search query language and file preview panel to Tag Library
- Added: Add classifier-compatible config import/export and per-directory overrides
- Added: Add Nexa SDK as alternative AI backend alongside Ollama
- Added: Add Media Lookup panel with TMDb, OMDb, and TVMaze providers
- UniFile v8.0.0 — unified AI-powered file organization platform
