# Research - UniFile

## Executive Summary
UniFile is a local-first PyQt6 desktop organizer that combines filesystem scans, rule/AI classification, a SQLAlchemy tag library, duplicate cleanup, media metadata lookup, shell integration, and Ollama/Nexa-backed intelligence. Verified: its strongest current shape is breadth plus safety-oriented preview/undo workflows; the highest-value direction is to harden trust boundaries and persistence before adding more feature breadth. Top opportunities: plugin trust gate, removal of embedded shared media API keys, versioned tag-library migrations, dependency/test manifest convergence, redacted diagnostics, PyInstaller runtime smoke hardening, security policy sync, locale-ready UI strings, Windows metadata bridge, and TagSpaces sidecar interop.

## Product Map
- Core workflows: scan folders/files, preview classifications, apply moves/renames with undo, manage tag-library entries, run cleanup/duplicate/media-lookup tools.
- Core workflows: shell-triggered scans and headless CLI commands in `unifile/__main__.py` (`classify`, `validate-rules`, `install-shell`, profile-driven scan/apply).
- User personas: Windows power users cleaning Downloads/Desktop, media-library maintainers, photographers/designers, local-AI privacy users, and developers extending classifiers.
- Platforms and distribution: Python >=3.10, PyQt6 GUI, SQLAlchemy/SQLite data layer, PyInstaller spec for Windows desktop artifacts, source installs via `pyproject.toml` and `requirements.txt`.
- Key integrations and data flows: Ollama/Nexa providers, TMDb/OMDb/TVMaze media APIs, optional metadata/OCR/image dependencies, SQLite tag library, CSV/undo/crash logs, Windows Explorer context-menu launcher.

## Competitive Landscape
- TagStudio: does non-destructive tag libraries, custom fields, Boolean search, translations, and library-format thinking well. Learn from its explicit library-format goals and user complaints about search/performance; avoid a single opaque database that cannot survive moves or interoperate.
- TagSpaces: does file-adjacent tag portability through filename tags or `.ts` JSON sidecars well. Learn import/export and travel-with-files metadata; avoid forcing sidecars as the only storage model.
- Hydrus Network: does tag parents/siblings and large tag graphs well. Learn graph semantics and query expansion; avoid importing PTR/community-repository complexity into a personal filesystem app.
- Czkawka/dupeGuru: do focused duplicate/cleanup UX with review-before-delete well. Learn reference-folder, conflict, and false-negative diagnostics; avoid irreversible delete paths and silent "no matches" results.
- Eagle/Adobe Bridge/FileBot: commercial tools make smart folders, batch metadata/rename templates, and media metadata workflows feel polished. Learn previewable batch templates and collection/search ergonomics; avoid paywall-style feature fragmentation and online-account assumptions.
- Paperless-ngx/Immich: adjacent self-hosted systems prove that OCR/ML tagging, saved views, CLIP search, and job status dashboards are expected in serious libraries. Learn explicit job state, retry, and review queues; avoid server-first architecture unless a future headless mode is intentionally built.

## Security, Privacy, and Reliability
- Verified: `unifile/plugins.py:144-174` discovers every `.py` file under the app-data plugins directory, executes it via `importlib.util.spec_from_file_location(...).loader.exec_module(...)`, and swallows load errors. Add an explicit trust/enable gate before expanding the roadmap's future scripting system.
- Verified: `unifile/media/providers.py:115` and `unifile/media/providers.py:247` embed shared TMDb/OMDb fallback keys; `ATTRIBUTION.md:23-25` documents the TMDb key as a shared demo key. Replace with user-owned credentials and visible provider status.
- Verified: `unifile/tagging/db.py:53-72` applies unordered raw `ALTER TABLE` statements and ignores `OperationalError`; this hides drift and gives no rollback path for user libraries.
- Verified: `SECURITY.md:12-15` still lists `9.0.x` as supported while `pyproject.toml` and README declare v9.3.21.
- Verified: `unifile/cleanup.py:621-629` can fall back to `os.remove()` when `send2trash` is unavailable; the existing ROADMAP already covers a Recycle Bin unification item, so this research does not add a duplicate roadmap item.
- Likely: crash logs, CSV audit trails, provider warnings, and diagnostic screenshots can expose local paths or credentials; `SECURITY.md:39` already names secrets/path exposure as in scope, but no redacted support-bundle path is documented.

## Architecture Assessment
- Verified: `unifile/main_window.py` is 4054 lines and `unifile/workers.py` is 2737 lines; recent commits show repeated mixin extraction, so future work should continue boundary cuts only when tied to testable behavior.
- Verified: package metadata is split across `pyproject.toml`, `requirements.txt`, and `unifile/bootstrap.py`; the sets disagree for optional/media/dev dependencies, and `tests/test_main_window_smoke.py:29` skips the main GUI smoke suite when `pytest-qt` is missing.
- Verified: `run.py:2` still says `UniFile v9.0.0` while project metadata says v9.3.21; PyInstaller docs require `multiprocessing.freeze_support()` in frozen apps that may spawn subprocesses/processes, but `run.py` does not call it.
- Verified: `UniFile.spec` has no runtime hooks, no signing identity, and no automated launch smoke; the existing distribution roadmap covers installers, but not executable-level boot verification.
- Likely: Windows Property System and Cloud Files API can improve metadata reads and placeholder handling without writing fragile Shell extensions; `plugins.py` already has heuristic cloud-folder detection, and `Roadmap_Blocked.md` keeps native thumbnail provider work blocked on COM signing.
- Verified: i18n is currently limited in the roadmap to RTL layout support; Qt Linguist-ready string extraction is missing and must precede real localization.

## Rejected Ideas
- GitHub Actions CI/release automation: rejected because repo rules and recent commit `ae27c3f` require local builds only, despite the older roadmap item mentioning GitHub Actions.
- Full commercial DAM/PIM suite parity: rejected because Pimcore/ResourceSpace-style multi-tenant asset workflows contradict UniFile's desktop local-first shape.
- Hydrus PTR/community tag-repository sync: rejected because moderation, legal, and network trust burdens do not fit the current personal-file organizer; tag graph semantics remain useful.
- RestrictedPython as a security sandbox: rejected because its own README says it is not a sandbox or secured environment; use explicit trust gates and process isolation for untrusted plugins.
- Mac-only Hazel clone behavior: rejected as a primary direction because UniFile is Windows-first and already has cross-platform watch/profile automation on the roadmap.
- Subtitle/NFO downloader and full media-provider parity: rejected as new additions because ROADMAP.md already contains those media items.
- Mobile companion, collaborative LAN tagging, NAS/headless, offline embeddings, and Recycle Bin unification: rejected as new additions because ROADMAP.md already contains those items.

## Sources
OSS and adjacent:
- https://docs.tagstud.io/
- https://github.com/TagStudioDev/TagStudio/discussions/1022
- https://docs.tagspaces.org/tagging/
- https://docs.tagspaces.org/dev/metafileformats/
- https://hydrusnetwork.github.io/hydrus/advanced_parents.html
- https://hydrusnetwork.github.io/hydrus/advanced_siblings.html
- https://github.com/qarmin/czkawka
- https://github.com/arsenetar/dupeguru/
- https://github.com/jkwill87/mnamer
- https://docs.immich.app/features/searching/
- https://docs.paperless-ngx.com/advanced_usage/

Commercial and product:
- https://en.eagle.cool/support/article/smart-folders
- https://helpx.adobe.com/bridge/desktop/organize-and-find-files/tag-and-find-files/batch-rename-files.html
- https://www.filebot.net/

Standards and platform APIs:
- https://developer.adobe.com/xmp/docs/xmp-specifications/
- https://www.iptc.org/std/photometadata/documentation/userguide/
- https://learn.microsoft.com/en-us/windows/win32/cfapi/build-a-cloud-file-sync-engine
- https://learn.microsoft.com/en-us/windows/win32/properties/property-system-overview
- https://doc.qt.io/qt-6/internationalization.html
- https://www.w3.org/TR/WCAG22/
- https://developer.themoviedb.org/docs/getting-started
- https://www.omdbapi.com/apikey.aspx
- https://www.tvmaze.com/api
- https://sqlite.org/pragma.html

Dependency, packaging, and security:
- https://pyinstaller.org/en/v6.6.0/common-issues-and-pitfalls.html
- https://github.com/python-pillow/Pillow/security/advisories/GHSA-cfh3-3jmp-rvhc
- https://pypi.org/project/pip-audit/
- https://packaging.python.org/en/latest/specifications/pylock-toml/
- https://alembic.sqlalchemy.org/
- https://github.com/zopefoundation/RestrictedPython

## Open Questions
- Needs live validation: which generated release artifact format is the canonical user install path right now: PyInstaller COLLECT folder, portable ZIP, or a future MSI?
- Needs live validation: should media API credentials be stored only in environment variables, or also in UniFile settings using OS credential storage?
