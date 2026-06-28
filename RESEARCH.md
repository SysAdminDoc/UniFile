# Research - UniFile

## Executive Summary
UniFile is a local-first Python/PyQt6 desktop organizer that combines rule and AI classification, preview-first moves/renames, cleanup, duplicate detection, media metadata lookup, a SQLAlchemy tag library, shell integration, and optional Ollama/Nexa intelligence. Verified: its strongest current shape is breadth plus review/undo safety; the highest-value direction is to harden trust, install, deletion, job-state, and persistence paths before adding more surface area. Priority opportunities: stop runtime dependency/Ollama mutation by default; keep cleanup deletion fail-closed when trash support is missing; make watch-mode jobs explicit and recoverable; expose OCR/content extraction to rules and saved views; remove stale CI/release automation promises from docs/roadmap; then continue the already-planned plugin trust gate, API-key removal, tag-library migrations, dependency audit, diagnostics, PyInstaller smoke, i18n, Windows metadata bridge, and TagSpaces sidecar work.

## Product Map
- Core workflows: scan folders/files, classify by extension/rules/metadata/context/LLM, preview destinations, apply moves or renames with undo, and export scan plans from `unifile/__main__.py`.
- Core workflows: manage tag-library entries in SQLite, search by tags/query tokens, save searches, run OCR/media lookup, and write XMP sidecars.
- Core workflows: cleanup empty/temp/broken/big/old files, find duplicates with progressive hashing/perceptual image matching, and use shell context-menu launches with `--source` and `--show-preview`.
- User personas: Windows power users cleaning Downloads/Desktop, media-library maintainers, designers/photographers with asset packs, local-AI privacy users, and developers extending rules/plugins.
- Platforms and distribution: Python >=3.10, PyQt6, SQLAlchemy/SQLite, source install via `pyproject.toml`/`requirements.txt`, Windows PyInstaller spec, and cross-platform claims in README.
- Key integrations and data flows: Ollama/Nexa/local AI providers, TMDb/OMDb/TVMaze, optional OCR/media/image libraries, Windows Explorer shell registration, app-data JSON/SQLite stores, crash/CSV/undo/watch logs.

## Competitive Landscape
- TagStudio: strong non-destructive tag-library model, flexible fields, Boolean search, and library-format thinking. Learn from its local-library ergonomics and user demand for AI-assisted ingestion; avoid a closed database that cannot round-trip through sidecars or moves.
- TagSpaces: strong portable metadata through filename tags and `.ts` JSON sidecars. Learn file-adjacent metadata portability and mobile/PWA reach; avoid forcing sidecars as the only source of truth.
- Hydrus Network: strong tag parents/siblings and high-scale tag graph semantics. Learn implication/sibling query expansion; avoid importing public tag repository moderation and network trust complexity.
- Czkawka and dupeGuru: strong focused cleanup/duplicate workflows, reference-folder protection, and false-negative community feedback. Learn master-folder protection and explainable "why not duplicate" states; avoid permanent-delete fallbacks and silent no-result scans.
- Hazel, DropIt, and File Juggler: strong watched-folder automation with content/date/name rules. Learn file-settle checks, explicit rule order, and content-aware matching; avoid Mac-only assumptions and opaque automation side effects.
- Eagle, Adobe Bridge, and FileBot: strong smart folders, collections, batch metadata/rename previews, and media rename grammar. Learn previewable batch templates and merge-oriented duplicate handling; avoid account/cloud assumptions and feature fragmentation.
- Paperless-ngx and Immich: adjacent self-hosted libraries show OCR/content matching, saved views, ML-assisted search, job status, retry, and review queues are table-stakes for serious personal libraries. Learn visible background jobs and post-ingest review; avoid server-first architecture unless headless mode is deliberately added.

## Security, Privacy, and Reliability
- Verified: `unifile/bootstrap.py:27-113` auto-runs pip installs for required and optional packages during import, including large/native packages, with quiet stdout/stderr and no consent boundary. This conflicts with normal source-install expectations and can mutate user environments unexpectedly.
- Verified: `unifile/workers.py:1081-1250` can silently install/start Ollama and pull models as part of setup. This supports the README quick start but needs an explicit opt-in/offline-safe path for privacy, bandwidth, and enterprise environments.
- Verified: `unifile/cleanup.py:597-629` falls back to `os.rmdir()`/`os.remove()` when `send2trash` is unavailable. `unifile/workers.py:263-282` already fails closed for trash-mode deletion, so cleanup should match that safer behavior.
- Verified: `unifile/widgets.py:505-638` uses `QFileSystemWatcher` plus a fixed delay and triggers a scan by mutating main-window UI state. There is no durable pending-job record, file-size stability check, retry queue, or visible failed-watch job state.
- Verified: `unifile/plugins.py:159-172` executes every discovered plugin module and suppresses load errors. The existing roadmap already covers a plugin trust gate; keep that as a top trust prerequisite before scripting/manifest expansion.
- Verified: `unifile/media/providers.py:115` and `unifile/media/providers.py:247` embed shared TMDb/OMDb fallback keys; `ATTRIBUTION.md` documents the TMDb key as shared. The existing roadmap already covers replacing these with user-owned credentials.
- Verified: `unifile/tagging/db.py:50-70` applies raw `ALTER TABLE` statements and ignores `OperationalError`, with no schema version, backup, or rollback. The existing roadmap already covers versioned migrations.
- Verified: `SECURITY.md:12-15` says only latest releases are supported but still lists `9.0.x` while the app is v9.3.21; the existing roadmap already covers security policy sync.
- Likely: crash logs, provider failures, CSV audit trails, and watch history can expose full local paths. The existing diagnostics roadmap item should redact paths, keys, emails, and media API parameters.

## Architecture Assessment
- Verified: `unifile/main_window.py` is 4054 lines and `unifile/workers.py` is 2737 lines; recent commits show mixin extraction, but scan/apply/watch still share UI state and worker state tightly.
- Verified: `pyproject.toml`, `requirements.txt`, and `unifile/bootstrap.py` do not describe the same dependency set; optional packages are unpinned even though image/OCR/media parsers process untrusted files. This is already partly captured by the dependency convergence roadmap item.
- Verified: `tests/test_main_window_smoke.py:29` skips GUI smoke coverage if `pytest-qt` is absent; docs say `pip install -e ".[dev]"` is the dev path, so dev installs should make GUI smoke non-optional.
- Verified: `run.py:2` still says v9.0.0 while package metadata says v9.3.21, and `UniFile.spec` has no runtime hook. The existing PyInstaller smoke roadmap item should include version sync and frozen-process guards.
- Verified: `unifile/ocr_indexer.py:58-96` extracts OCR text into `ai_summary`, but `RuleEngine._get_field_value()` in `unifile/engine.py:114-137` only reads direct metadata fields and does not provide first-class content conditions, OCR confidence, or "content contains" rule ergonomics.
- Verified: `CONTRIBUTING.md:111-113` and `ROADMAP.md:266,279-280` still describe GitHub release/CI automation even though `.github/workflows/` is absent and commit `ae27c3f` removed workflows for local-only builds.
- Likely: Windows Property System and Cloud Files API can improve Shell metadata import and cloud-placeholder handling without risky Explorer shell extensions; native thumbnail provider work is correctly parked in `Roadmap_Blocked.md`.
- Verified: i18n is currently represented as RTL layout in the roadmap, but Qt Linguist extraction/catalog/release steps are missing. The existing i18n roadmap item should land before broader localization.

## Rejected Ideas
- GitHub Actions build/test/release automation: rejected because repo rules and commit `ae27c3f` require local builds only; update stale docs instead.
- Full commercial DAM/PIM parity: rejected because ResourceSpace/Pimcore-style multi-tenant workflows do not fit UniFile's desktop local-first shape.
- Hydrus PTR/community tag-repository sync: rejected because moderation, legal, and network trust burdens do not fit a personal filesystem organizer; tag graph semantics remain useful.
- RestrictedPython as the plugin security boundary: rejected because its own documentation says it is not a sandbox; use explicit trust gates, process isolation, and clear enabled-state UX.
- Mac-only Hazel clone behavior: rejected as a primary direction because UniFile is Windows-first/cross-platform; borrow rule clarity and file-settle semantics instead.
- New subtitle/NFO downloader, media-provider parity, mobile companion, collaborative LAN tagging, NAS/headless, ONNX embeddings, XMP sidecars, and TagStudio import/export: rejected as new additions because `ROADMAP.md` already contains those items.
- Native Explorer thumbnail/preview provider now: rejected because `Roadmap_Blocked.md` correctly identifies the COM DLL, installer, and signing requirements.

## Sources
OSS and adjacent:
- https://github.com/TagStudioDev/TagStudio
- https://docs.tagstud.io/
- https://github.com/TagStudioDev/TagStudio/discussions/1022
- https://docs.tagspaces.org/tagging/
- https://docs.tagspaces.org/dev/metafileformats/
- https://hydrusnetwork.github.io/hydrus/advanced_parents.html
- https://hydrusnetwork.github.io/hydrus/advanced_siblings.html
- https://github.com/qarmin/czkawka
- https://dupeguru.voltaicideas.net/help/en/
- https://docs.paperless-ngx.com/advanced_usage/
- https://docs.immich.app/features/searching/
- https://github.com/hyperfield/ai-file-sorter
- https://github.com/iyaja/llama-fs
- https://github.com/QiuYannnn/Local-File-Organizer

Commercial and product:
- https://www.noodlesoft.com/manual/hazel/hazel-overview/
- https://www.noodlesoft.com/manual/hazel/work-with-folders-rules/create-edit-rules/understand-the-logic-of-rules/
- https://www.dropitproject.com/
- https://www.filejuggler.com/
- https://en.eagle.cool/support/article/smart-folders
- https://helpx.adobe.com/bridge/desktop/organize-and-find-files/organize-files-and-folders/use-collections.html
- https://www.filebot.net/

Standards, platform, dependency, and security:
- https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
- https://doc.qt.io/qt-6/internationalization.html
- https://doc.qt.io/qt-6/linguist-lupdate.html
- https://learn.microsoft.com/en-us/windows/win32/properties/property-system-overview
- https://learn.microsoft.com/en-us/windows/win32/cfapi/build-a-cloud-file-sync-engine
- https://github.com/python-pillow/Pillow/security/advisories/GHSA-cfh3-3jmp-rvhc
- https://pypi.org/project/pip-audit/
- https://alembic.sqlalchemy.org/

## Open Questions
- Needs live validation: which install artifact should be canonical for users now: source checkout, PyInstaller COLLECT folder, portable ZIP, or a future MSI?
- Needs live validation: should media API credentials be environment-only, stored in UniFile settings, or stored through OS credential storage?
