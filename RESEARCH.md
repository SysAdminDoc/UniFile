# Research - UniFile

## Executive Summary
UniFile is a local-first Python/PyQt6 desktop file organizer for classifying, tagging, cleaning, deduplicating, previewing, and undoing file operations across existing folders. Its strongest current shape is the preview-first, non-destructive local-library model: broad rule coverage, SQLite/SQLAlchemy tag storage, optional local AI, diagnostics, sidecar interop foundations, and 455 collected tests. The highest-value direction is to turn recently added infrastructure into visible workflows while hardening trust boundaries around deletion, release packaging, search scale, AI response contracts, parser dependencies, and provenance metadata.

Top opportunities, in order:
- Verified: restore the frozen-build release gate because `UniFile.spec` references missing `unifile/pyinstaller_runtime.py`, while `README.md`, `CONTRIBUTING.md`, and `CHANGELOG.md` claim frozen smoke and SHA-256 output.
- Verified: make cleanup deletion fail closed; `unifile/cleanup.py:621`/`:627` still falls back to permanent delete when `send2trash` is unavailable, despite `unifile/workers.py:266` using safer semantics.
- Verified: pin/audit untrusted parser dependencies because `[full]` leaves image/document/media parsers broad, and Pillow advisories affect formats UniFile can ingest.
- Verified: wire inert v9.3.29 modules into user workflows: `unifile/tagspaces.py`, `unifile/win_properties.py`, and `unifile/i18n.py` have tests but are not yet integrated at the GUI/startup boundary.
- Verified: replace regex LLM cleanup in `unifile/ollama.py` and `unifile/workers.py` with schema-validated structured outputs using Ollama/OpenAI-compatible APIs.
- Verified: add indexed/FTS-backed tag-library search; `search_tags()`/`search_entries()` use `%ilike%` scans over tag names, filenames, and text fields without indexes.
- Verified: capture download provenance into the existing `Entry.source_url` field from Windows Mark-of-the-Web/Zone.Identifier where available, instead of relying only on manual entry.
- Verified: remove tracked root debug/output artifacts (`audit2.txt`, `cats.txt`, `smoke86_out.txt`) and prevent recurrence with a repository hygiene check.
- Likely: split heavyweight face/local-AI dependencies from `[full]`; collect-only currently warns that `face_recognition_models` imports deprecated `pkg_resources`, and peer TagStudio now explicitly handles Python 3.13 compatibility.

## Product Map
- Core workflows: scan folders, classify files by rules/metadata/AI, preview destination trees, apply or undo file moves/renames, manage tags/metadata, find duplicates, run cleanup scans, and export diagnostics.
- User personas: Windows power users cleaning Downloads/Desktop/project trees; photographers and media librarians; document archivists; privacy-focused local-AI users; developers extending classification and tagging behavior.
- Platforms and distribution: Python 3.10+ source install, PyQt6 desktop GUI, console entry point `unifile`, Windows shell integration, PyInstaller onedir build via `UniFile.spec`, MIT license.
- Key integrations and data flows: filesystem metadata, SQLite/SQLAlchemy tag library, TagSpaces `.ts` sidecars, Windows Shell properties, optional OCR/media parsers, Ollama/OpenAI-compatible providers, media lookup APIs, redacted support bundles.

## Competitive Landscape
- TagStudio / TagSpaces: non-destructive tagging, sidecar metadata, GUI-visible import/export, active translations, and Python-version compatibility work are the closest peer signals. Learn from visible interoperability and migration paths; avoid leaving sidecar logic as code-only plumbing.
- Czkawka / Krokiet: cleanup credibility comes from focused analyzers, cache invalidation, broken-file checks with multiple checkers, separate trash/permanent-delete actions, and GUI responsiveness. Learn from explicit destructive-action separation; avoid permanent-delete fallbacks hidden behind "move to trash" labels.
- paperless-ngx: document value comes from OCR-backed indexing, workflows, saved views, custom fields, and indexing-performance work. Learn from workflow triggers and search/index discipline; avoid forcing UniFile users into a central consume folder because the project preserves existing layouts.
- Immich / PhotoPrism: media search is table-stakes when it combines metadata, OCR, faces, color/location/rating filters, and contextual search. Learn from reprocessing transparency and rich facets; avoid server-only assumptions for desktop-first use.
- Hydrus: tag parents/siblings show how tag graphs scale without physically duplicating implied tags. Learn from virtual implications and loop prevention; avoid shared-server moderation complexity until UniFile has a local graph model.
- Adobe Bridge / DEVONthink / Hazel / FileBot: commercial desktop tools monetize metadata grids, hierarchical keywords, smart groups, recursive rules, and naming expressions. Learn from visible rule/search builders and batch metadata workflows; avoid shortcut-only power features that violate the project's accessibility and no-shortcuts rules.
- rclone / data-hoarding tooling: adjacent projects show that remote and archive workflows need explicit list-only/download/sync-back modes, resumability, and provenance. Learn from clear mode boundaries; avoid implicit mutation of remote or cloud-backed files.

## Security, Privacy, and Reliability
- Verified bugs or risks:
  - `UniFile.spec:14` points at missing `unifile/pyinstaller_runtime.py`; `Makefile` only runs PyInstaller while docs claim frozen smoke and checksum output.
  - `unifile/cleanup.py:621`/`:627` permanently deletes when trash support is missing; this regresses the older changelog claim that trash-missing deletes fail closed.
  - `pyproject.toml` leaves parser-heavy packages broad while UniFile scans untrusted images, archives, PDFs, media, and OCR inputs.
  - `unifile/bootstrap.py:95` uses `--break-system-packages`, conflicting with Python's externally managed environment guidance.
  - `unifile/ollama.py:462`, `unifile/ollama.py:1102`, and `unifile/workers.py:2219` strip `<think>` blocks after generation instead of requesting schema-constrained responses.
  - `unifile/archive_indexer.py:60`, `unifile/ratings.py:36`, and `unifile/semantic.py:49` use `check_same_thread=False`; only some services document locking, WAL, timeout, and close semantics.
  - `audit2.txt`, `cats.txt`, and `smoke86_out.txt` are tracked root artifacts; `smoke86_out.txt` contains stale smoke output and a traceback.
- Missing guardrails:
  - No frozen EXE smoke enforces startup, `--version`, headless `classify --json`, GUI-start, and checksum generation.
  - No single AI HTTP layer owns timeouts, retries, redaction, schema validation, and normalized provider errors.
  - No scale benchmark or FTS/index migration protects Tag Library search from linear `%ilike%` scans.
  - No automatic provenance importer populates the existing Source URL field from Windows Zone.Identifier or other platform download metadata.
  - No root hygiene check fails when ad-hoc smoke/audit/category dumps are accidentally tracked.
- Recovery and rollback needs:
  - Cleanup actions should journal intended operations and refuse deletion unless trash or explicit permanent-delete mode is available.
  - Tag-library schema changes need migration tests, backup/restore behavior, and query equivalence tests.
  - PyInstaller packaging should clean stale artifacts before build and emit checksums only after smoke passes.

## Architecture Assessment
- Module or boundary improvements needed:
  - Keep new integrations behind services rather than expanding `unifile/main_window.py` (~4k lines) and `unifile/workers.py` (~2.7k lines).
  - `unifile/tagspaces.py`, `unifile/win_properties.py`, `unifile/i18n.py`, and `Entry.source_url` are useful boundaries but need startup/GUI/scan callers.
  - `unifile/ai_providers.py` should own OpenAI-compatible request/response behavior and become the shared path for Ollama-compatible schema outputs.
  - Tag Library search should move from ad hoc `%ilike%` calls in `unifile/tagging/library.py` to migration-backed indexes or SQLite FTS5 with query tests.
- Refactor candidates:
  - `unifile/ollama.py`: extract schema definitions, request execution, timeout policy, provider errors, and structured parsing.
  - `unifile/bootstrap.py`: remove system-package override and align optional extras with documented install paths.
  - `unifile/metadata.py`: merge Windows Shell and download-provenance reads without leaking platform specifics into callers.
  - `Makefile` / `UniFile.spec`: make release packaging executable truth instead of documentation-only claims.
- Test and documentation gaps:
  - `pytest --collect-only -q` finds 455 tests, but no checked-in frozen-build smoke test exists.
  - TagSpaces, Windows Shell properties, i18n, and Source URL handling need GUI/startup/scan integration coverage.
  - Accessibility and i18n remain partially planned: current roadmap has shortcut-heavy items, while project rules require visible controls first and Qt translator installation at startup.
  - Observability is partly present through diagnostics export, but AI/network calls need redacted request diagnostics and normalized failure evidence.
  - Distribution, plugin ecosystem, mobile, offline resilience, multi-user, migration paths, and upgrade strategy are represented in the roadmap; current priority should remain trust/search/release foundations before larger headless, remote, or collaborative bets.

## Rejected Ideas
- Full Paperless-style central ingest store: rejected because UniFile's README and roadmap emphasize organizing existing folders without breaking associated files.
- Native mobile app before a read-only local API/PWA: rejected because the desktop app lacks the stable local API and auth boundaries needed for mobile writes.
- Collaborative LAN tagging now: rejected because roles, auth, conflict resolution, and audit identity are not yet present.
- Auto-installing binary updates: rejected because a download-only update checker better matches local control and avoids unattended replacement risk.
- Copying AGPL AI organizer or TagSpaces code: rejected because UniFile is MIT; use patterns/docs, not incompatible code.
- More default shortcut-first workflows: rejected because repo instructions prohibit keyboard shortcuts; features must be visible and focus-accessible first.
- Full Windows Cloud Files sync provider: rejected because CFAPI provider work is heavyweight; placeholder-aware scanning/hydration policy is the correct first step.
- Filetags-style filename mutation as a near-term tagging format: rejected for now because UniFile's philosophy is non-destructive metadata/sidecars; filename tags can be reconsidered only as explicit import/export.

## Sources
OSS and peer projects:
- https://github.com/TagStudioDev/TagStudio/releases/tag/v9.6.0
- https://github.com/qarmin/czkawka/releases/tag/12.0.0
- https://docs.paperless-ngx.com/usage/
- https://github.com/paperless-ngx/paperless-ngx/issues?q=is%3Aissue+Performance%3A+Tantivy+indexing+optimization
- https://docs.immich.app/features/searching/
- https://docs.photoprism.app/user-guide/search/filters/
- https://docs.tagspaces.org/dev/metafileformats/
- https://hydrusnetwork.github.io/hydrus/advanced_parents.html
- https://github.com/simon987/awesome-datahoarding

Commercial and adjacent products:
- https://www.tagspaces.org/products/pro/
- https://helpx.adobe.com/bridge/desktop/organize-and-find-files/tag-and-find-files/use-keywords.html
- https://www.noodlesoft.com/manual/hazel/advanced-topics/processing-subfolders/
- https://www.devontechnologies.com/blog/20230704-smart-groups
- https://www.filebot.net/forums/viewforum.php?f=5

Standards, platform APIs, and dependency docs:
- https://docs.ollama.com/capabilities/structured-outputs
- https://docs.ollama.com/api/openai-compatibility
- https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
- https://packaging.python.org/en/latest/specifications/externally-managed-environments/
- https://doc.qt.io/qt-6/accessible.html
- https://doc.qt.io/qt-6/internationalization.html
- https://www.sqlite.org/fts5.html
- https://www.sqlite.org/threadsafe.html
- https://learn.microsoft.com/en-us/windows/win32/properties/property-system-overview
- https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/6e3f7352-d11c-4d76-8c39-2516a9df36e8
- https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-iattachmentexecute
- https://setuptools.pypa.io/en/latest/deprecated/pkg_resources.html

Security and community signal:
- https://github.com/python-pillow/Pillow/security/advisories/GHSA-cfh3-3jmp-rvhc
- https://github.com/python-pillow/Pillow/security/advisories/GHSA-pwv6-vv43-88gr
- https://github.com/python-pillow/Pillow/security/advisories/GHSA-whj4-6x5x-4v2j
- https://news.ycombinator.com/item?id=44932375

## Open Questions
- None.
