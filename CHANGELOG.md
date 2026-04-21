# Changelog

All notable changes to UniFile will be documented in this file.

## [v8.2.0]

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
