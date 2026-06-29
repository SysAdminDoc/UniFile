# Research - UniFile

## Executive Summary
UniFile is a Windows-first, cross-platform Python/PyQt6 desktop organizer that combines local rules, Ollama/OpenAI-compatible AI classification, duplicate cleanup, tagging, media metadata, diagnostics, and portable PyInstaller distribution. Its strongest current shape is the non-destructive local-library model: preview-first operations, sidecar-oriented interoperability, local AI, and a broad test suite. The highest-value direction is to turn recently added infrastructure into visible workflows and harden the trust boundary around deletion, release packaging, AI response parsing, and untrusted image/document parsing.

Top opportunities, in order:
- Verified: restore the PyInstaller release gate because `UniFile.spec` references missing `unifile/pyinstaller_runtime.py`, while `README.md`, `CONTRIBUTING.md`, and `CHANGELOG.md` claim frozen smoke and SHA-256 output.
- Verified: complete the existing Cleanup & Safety recycle-bin item by making `unifile/cleanup.py::delete_items()` fail closed instead of hard-deleting when `send2trash` is unavailable.
- Verified: pin/audit image parser dependencies because `pyproject.toml` leaves `Pillow` unpinned and current Pillow advisories affect PSD/FITS parsing paths relevant to UniFile ingestion.
- Verified: wire inert v9.3.29 modules into the app surface: `unifile/tagspaces.py`, `unifile/win_properties.py`, and `unifile/i18n.py` are tested but not imported by the GUI/startup paths found by grep.
- Verified: replace regex-based LLM cleanup in `unifile/ollama.py` and `unifile/workers.py` with schema-validated structured outputs using Ollama/OpenAI-compatible APIs.
- Verified: remove `--break-system-packages` from the opt-in bootstrap path in `unifile/bootstrap.py` and guide source users toward virtual environments instead.
- Likely: centralize AI HTTP request handling; `urllib.request.urlopen` appears across provider, metadata, semantic, engine, worker, and Ollama modules with inconsistent timeouts and diagnostics.
- Likely: split heavyweight AI/face dependencies from `[full]` so normal installs do not pull `cmake`, `dlib`, `face_recognition`, and `nexaai` unless the user enables those features.

## Product Map
- Core workflows: scan folders; classify files with rules and local/remote AI; preview moves/renames; apply or undo file operations; manage tags, metadata, duplicates, cleanup, watch jobs, diagnostics, and shell integration.
- User personas: Windows power users cleaning large Downloads/Desktop/media trees; photographers and media librarians; document archivists; sysadmin-style users who want local-first automation without cloud upload; developers extending classification/tagging behavior.
- Platforms and distribution: Python 3.10+ source install, PyQt6 GUI, console entry point `unifile`, Windows shell integration, PyInstaller onedir build via `UniFile.spec`, MIT license.
- Key integrations and data flows: SQLite/SQLAlchemy tag library and caches; filesystem metadata, OCR/media extractors, TagSpaces `.ts` sidecars, Windows Shell properties, Ollama/OpenAI-compatible endpoints, optional media APIs, redacted diagnostics export.

## Competitive Landscape
- TagStudio / TagSpaces: sidecar metadata, non-destructive tagging, portable release assets, and user-focused library UX are the closest fit. Learn from visible import/export and sidecar format docs; avoid hiding completed sidecar logic behind code-only modules.
- Czkawka / Krokiet: cleanup credibility comes from many focused analyzers, safe previews, cache support, CLI/core separation, and explicit bad-extension/broken-file tools. Learn from fail-closed destructive flows and bad-extension scans; avoid adding cleanup breadth before deletion safety is consistent.
- paperless-ngx: document value comes from OCR-backed content matching, workflows, saved views, custom fields, and task diagnostics. Learn from workflow triggers and inbox patterns; avoid forcing all user files into a central consume folder because UniFile's value is preserving existing folder layouts.
- Immich / PhotoPrism: media search is table-stakes when it combines metadata, OCR, faces, color, location, ratings, and CLIP-style contextual search. Learn from model tradeoff settings and transparent reprocessing; avoid server-only assumptions for a desktop-first app.
- AI File Sorter / Fallinorg / Desktop Docs: local AI organizers compete on preview-first moves, offline operation, local learning, OpenAI-compatible endpoints, visual/document analysis, undo, and guided onboarding. Learn from constrained taxonomies and persistent undo; avoid AGPL code reuse from AI File Sorter unless licensing is handled explicitly.
- Hydrus: tag parents/siblings show how tag graphs scale without physically duplicating implied tags. Learn from virtual implications and loop prevention; avoid shared-server moderation complexity until UniFile has a local graph model.
- Adobe Bridge / DEVONthink / Hazel / FileBot: commercial desktop tools monetize metadata grids, hierarchical keywords, smart groups, recursive rules, and powerful naming expressions. Learn from batch metadata, saved search, and format-template UX; avoid shortcut-only or expert-only flows that conflict with UniFile's local GUI accessibility needs.

## Security, Privacy, and Reliability
- Verified bugs or risks:
  - `UniFile.spec` references `runtime_hooks=['unifile/pyinstaller_runtime.py']`, but that file is absent; `tools/smoke_pyinstaller_build.py` and `tests/test_pyinstaller_smoke.py` are absent while docs claim they exist.
  - `unifile/cleanup.py:597` falls back to `os.rmdir()` / `os.remove()` when `send2trash` cannot import, unlike `unifile/workers.py:265` which fails closed for trash deletion.
  - `pyproject.toml:39` leaves `Pillow` unpinned despite current GitHub advisories for PSD out-of-bounds writes and FITS decompression-bomb behavior; UniFile ingests images and PSD/HEIF-like optional formats.
  - `unifile/bootstrap.py:95` retries pip with `--break-system-packages`; the packaging spec labels that override risky and recommends virtual environments/pipx-style isolation.
  - `unifile/ollama.py:461`, `unifile/ollama.py:1102`, and `unifile/workers.py:2219` strip `<think>` blocks with regex after the fact instead of asking the model/API for schema-constrained responses.
  - `unifile/archive_indexer.py:60`, `unifile/ratings.py:36`, and `unifile/semantic.py:49` open SQLite connections with `check_same_thread=False`; only some SQLite modules enable WAL/timeouts.
- Missing guardrails:
  - No frozen-build smoke gate currently enforces that the release EXE starts, prints version, classifies a fixture, and produces a checksum.
  - No single AI HTTP layer owns retries, timeouts, provider errors, redaction, and structured response validation.
  - No dependency floor/lock policy for optional parser-heavy extras that process untrusted files.
  - Existing accessibility and i18n roadmap items are not yet backed by startup-level translator installation or visible command surfaces that avoid shortcut-only access.
- Recovery and rollback needs:
  - Cleanup deletions should journal planned operations and fail closed unless trash/undo support is available.
  - PyInstaller builds should delete stale artifacts before packaging and emit checksums only after smoke passes.
  - SQLite shared-connection modules need ownership rules, busy timeouts, and migration tests before scale features rely on them.

## Architecture Assessment
- Verified module boundary improvements:
  - `unifile/main_window.py` (~4k lines) and `unifile/workers.py` (~2.7k lines) remain large coordination modules; new integration work should land behind small services/dialog entry points instead of growing those files further.
  - `unifile/tagspaces.py`, `unifile/win_properties.py`, and `unifile/i18n.py` are good boundaries but need GUI/startup callers and tests for those callers.
  - `unifile/ai_providers.py` should own OpenAI-compatible request/response behavior now that Ollama supports OpenAI compatibility and structured output schemas.
  - Cleanup logic is split between `unifile/cleanup.py` and `unifile/workers.py`; destructive semantics should be centralized or at least tested for parity.
- Refactor candidates:
  - `unifile/ollama.py`: extract request building, schema definitions, structured parsing, and model health into reusable helpers.
  - `unifile/bootstrap.py`: keep opt-in install support but remove system-package overrides and align optional dependency names with `pyproject.toml` extras.
  - `unifile/metadata.py`: merge Windows Shell property reads into `MetadataExtractor.extract()` without platform-specific conditionals leaking into callers.
  - `Makefile` / `UniFile.spec`: make packaging targets executable truth, not documentation-only claims.
- Test and documentation gaps:
  - 455 tests collect, but current HEAD lacks PyInstaller smoke tests even though v9.3.28 documentation claims them.
  - TagSpaces, Windows properties, and i18n have unit tests but no GUI/startup integration tests.
  - No tests currently prove `cleanup.delete_items(use_trash=True)` refuses permanent deletion when trash support is unavailable.
  - Existing `ROADMAP.md` includes shortcut-heavy plans, but project instructions say no keyboard shortcuts; future UX work should expose visible buttons/menus first.

## Rejected Ideas
- Full Paperless-style ingest into a central managed store: rejected because Reddit/community complaints and UniFile's README/roadmap point to cataloging existing folders without breaking associated files.
- Native mobile app before the read-only LAN/PWA browser: rejected because UniFile has no stable local API yet and the current roadmap already proposes a lower-risk read-only browser.
- Collaborative LAN tagging with roles/ACLs now: rejected because it requires authentication, conflict resolution, and audit foundations not present in the desktop-first architecture.
- Auto-installing updates: rejected because the existing roadmap's no-auto-install update checker better matches local control and avoids risky unattended binary replacement.
- Copying AI File Sorter implementation code: rejected because the project is AGPL-3.0; use its UX patterns, not its code, unless UniFile's licensing strategy changes.
- Adding more default keyboard shortcuts: rejected because AGENTS.md says no keyboard shortcuts; visible command surfaces can still be keyboard navigable via Qt focus/tab order.
- Building a full Windows Cloud Files sync provider: rejected for now because Microsoft CFAPI provider work is complex; UniFile only needs placeholder-aware scanning/hydration policy first, already represented in the broader cloud roadmap.

## Sources
OSS and peer projects:
- https://github.com/TagStudioDev/TagStudio/releases/tag/v9.5.7
- https://github.com/qarmin/czkawka
- https://docs.paperless-ngx.com/usage/
- https://docs.immich.app/features/searching/
- https://docs.photoprism.app/user-guide/search/filters/
- https://docs.tagspaces.org/dev/metafileformats/
- https://hydrusnetwork.github.io/hydrus/advanced_parents.html
- https://github.com/hyperfield/ai-file-sorter

Commercial and adjacent products:
- https://www.tagspaces.org/products/pro/
- https://helpx.adobe.com/bridge/desktop/organize-and-find-files/tag-and-find-files/use-keywords.html
- https://www.noodlesoft.com/manual/hazel/advanced-topics/processing-subfolders/
- https://www.devontechnologies.com/blog/20230704-smart-groups
- https://www.filebot.net/forums/viewforum.php?f=5

Standards, platform APIs, and dependency docs:
- https://docs.ollama.com/capabilities/structured-outputs
- https://docs.ollama.com/openai
- https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
- https://pyinstaller.org/en/stable/CHANGES.html
- https://packaging.python.org/en/latest/specifications/externally-managed-environments/
- https://doc.qt.io/qt-6/accessible.html
- https://doc.qt.io/qt-6/internationalization.html
- https://www.sqlite.org/threadsafe.html
- https://learn.microsoft.com/en-us/windows/win32/properties/property-system-overview
- https://learn.microsoft.com/en-us/windows/win32/cfapi/build-a-cloud-file-sync-engine

Security and community signal:
- https://github.com/python-pillow/Pillow/security/advisories/GHSA-cfh3-3jmp-rvhc
- https://github.com/python-pillow/Pillow/security/advisories/GHSA-pwv6-vv43-88gr
- https://github.com/python-pillow/Pillow/security/advisories/GHSA-whj4-6x5x-4v2j
- https://news.ycombinator.com/item?id=44932375
- https://www.reddit.com/r/DataHoarder/comments/1k91a7h/looking_for_a_good_preferably_opensource/
- https://www.reddit.com/r/selfhosted/comments/vxqvh9/paperlessngx_is_not_what_i_thought_it_was/
- https://news.ycombinator.com/item?id=40371467

## Open Questions
- None.
