# Research — UniFile

## Executive Summary
UniFile is a local-first Python/PyQt6 desktop organizer for classifying, tagging, cleaning, deduplicating, previewing, and undoing work on existing folders. Its strongest current shape is the review-first desktop workflow: broad parser coverage, a SQLAlchemy tag library, optional local/network AI, sidecar foundations, diagnostics, undo logs, and a verified PyInstaller smoke path at v9.3.31. The highest-value direction is to finish trust and wiring work already implied by the code before adding bigger library features.

- Verified: fix destructive cleanup recovery first; `unifile/cleanup.py:624` and `unifile/cleanup.py:629` still fall back to permanent `os.rmdir`/`os.remove` when trash support is unavailable.
- Verified: wire inert interoperability into user-visible flows: `unifile/tagspaces.py`, `unifile/win_properties.py`, and `unifile/i18n.py` have tests/foundations but no complete GUI/startup/scan integration.
- Verified: move Tag Library search off the GUI thread; `unifile/dialogs/tag_library.py:915` calls synchronous `TagLibrary.search_entries()` on every search change.
- Verified: replace regex LLM cleanup with schema-validated outputs and central HTTP diagnostics across `unifile/ollama.py`, `unifile/ai_providers.py`, `unifile/engine.py`, and `unifile/workers.py`.
- Verified: add indexed/FTS-backed Tag Library search before large libraries; `unifile/tagging/library.py:140`, `:735`, and `:801` rely on wildcard `ilike`.
- Verified: add full-library backup/restore before more migrations and sidecar import/export; current backups cover apply snapshots and DB migrations, not user-triggered disaster recovery.
- Verified: align distribution with current source; GitHub's latest public release is `v9.3.15` while `pyproject.toml`, `README.md`, `ROADMAP.md`, and `unifile/__init__.py` are `v9.3.31`.
- Verified: isolate frozen builds from mixed Qt bindings; the local audit environment contains PyQt5 and PyQt6, and PyInstaller 6.21 documents aborting when multiple Qt bindings are collected.
- Verified: add release SBOM/license/vulnerability artifacts; `make audit` exists and `python -m pip_audit --local` currently reports no known vulnerabilities, but releases need reproducible evidence independent of the developer environment.
- Verified: remove tracked root debug outputs (`audit2.txt`, `cats.txt`, `smoke86_out.txt`) and enforce repository hygiene.

## Product Map
- Core workflows: scan folders into categorized previews; review and apply move/rename plans with undo; tag/search files in a local SQLite library; run cleanup/duplicate/media/metadata tools; export diagnostics and build a frozen desktop app.
- User personas: Windows desktop power users organizing Downloads/Desktop/Documents; photographers and media collectors needing metadata and sidecars; local-AI users who want offline classification; maintainers producing local PyInstaller releases.
- Platforms and distribution: Python 3.10+, PyQt6 desktop, strongest on Windows, source install plus PyInstaller onedir build; no current GitHub Actions workflows in `.github/`.
- Key integrations and data flows: filesystem metadata, SQLite/SQLAlchemy tag DB, XMP and TagSpaces sidecars, Windows Shell properties, Mark-of-the-Web source URL metadata, OCR/media parsers, Ollama/OpenAI-compatible providers, redacted diagnostics ZIPs.

## Competitive Landscape
- TagStudio / TagSpaces: Strong non-destructive library and sidecar interoperability, visible import/export paths, search grammar, translations, and saved-search concepts. UniFile should learn explicit migration/sidecar UX and avoid leaving sidecar code as hidden plumbing.
- Czkawka / fclones: Strong preview/simulation habits, fast cleanup analyzers, CLI automation, cache support, and explicit safe file-operation options. UniFile should learn fail-closed cleanup and dry-run ergonomics; avoid destructive fallbacks when safety dependencies are unavailable.
- Hydrus Network: Strong tag graph model, high-scale local media libraries, and privacy-first no-phone-home posture. UniFile should learn tag implications/siblings and scale-aware DB design; avoid Hydrus-level complexity before GUI search/indexing is fast.
- paperless-ngx / PhotoPrism / Immich / digiKam: Strong indexing, backups, metadata search, troubleshooting docs, and privacy positioning for large personal archives. UniFile should learn backup-first operations and search observability; avoid server-first or multi-user pivots before desktop reliability is complete.
- DEVONthink / Hazel / Eagle / File Juggler: Strong paid signals around smart groups, automation rules, batch metadata, duplicate handling, and visual asset management. UniFile should copy recoverable preview-and-rule patterns, not subscription/cloud assumptions.
- Local-AI file organizers / LSFS research: Strong signal for local semantic search, OCR, embeddings, natural-language queries, and prompt-driven file actions. UniFile should expose structured, reviewable local-AI workflows; avoid autonomous destructive actions without preview, rollback, and provenance.

## Security, Privacy, and Reliability
- Verified bug/risk: `unifile/cleanup.py:624` and `unifile/cleanup.py:629` fall back to permanent deletes; cleanup should fail closed or clearly require trash support instead of silently bypassing recovery.
- Verified risk: `unifile/bootstrap.py:143` tries `--break-system-packages`; PEP 668 treats this as an explicit override of externally managed environment protections.
- Verified risk: raw network/AI calls are spread across `unifile/ai_providers.py`, `unifile/ollama.py`, `unifile/engine.py`, `unifile/metadata.py`, and `unifile/workers.py`, making timeout, retry, diagnostics, and redaction behavior inconsistent.
- Verified risk: `archive_indexer.py:60`, `ratings.py:36`, and `semantic.py:49` use `check_same_thread=False`; concurrency policy needs explicit locking, WAL/busy-timeout consistency, and close semantics.
- Verified gap: `Entry.source_url` exists (`unifile/tagging/models.py:217`) and `Zone.Identifier` is treated as junk in `unifile/files.py`, but scans do not import or surface Windows `HostUrl`/`ReferrerUrl` risk context.
- Verified gap: `unifile/dialogs/tag_library.py:915` performs synchronous DB search from a text-change handler; large libraries can freeze the GUI even after backend FTS/indexing lands.
- Verified gap: public release state is stale (`v9.3.15`) relative to source (`v9.3.31`), so users cannot fetch an artifact matching the current tested code.
- Verified gap: local dependency state includes both PyQt5 and PyQt6 while PyInstaller now guards mixed Qt bindings; build commands need isolation or a preflight.
- Recovery needs: full-library backup/restore, integrity checks, delete fail-closed behavior, sidecar import dry-runs, and release rollback evidence should land before larger multi-root/cloud/plugin work.

## Architecture Assessment
- Boundary improvements needed: connect `unifile/tagspaces.py` to Tag Library/Settings UI, `unifile/win_properties.py` to scan metadata, and `unifile/i18n.py` to `unifile/__main__.py` before adding new interop modules.
- Refactor candidates: centralize provider HTTP in one request helper; move LLM parsing to typed schema validation; formalize SQLite connection ownership; add FTS/index migrations for tag library search.
- UI resilience candidates: debounce/cancel Tag Library searches, show loading/empty/error states, and keep result rendering off stale query responses.
- Test gaps: 463 tests collect successfully, but GUI coverage mostly instantiates widgets; add rendered offscreen screenshot/nonblank smoke tests for main, Tag Library, Cleanup, and Settings Hub surfaces.
- Documentation gaps: README and CONTRIBUTING document `make` commands, but the project is Windows-first; provide a Python task runner mirroring Makefile targets.
- Distribution gaps: PyInstaller smoke and SHA-256 are present, but releases should add isolated build preflights, SBOM, license inventory, vulnerability report, artifact checksums, and a current GitHub release.
- Hygiene gaps: tracked root debug outputs (`audit2.txt`, `cats.txt`, `smoke86_out.txt`) should be removed or converted into intentional fixtures with a guard against future ad-hoc dumps.

## Rejected Ideas
- Filename-mutating tags as the default, from TagSpaces/filetags patterns: rejected because UniFile's product philosophy is non-destructive metadata/sidecars; filename tags belong only as explicit import/export.
- Server/NAS/multi-user mode as near-term priority, from paperless-ngx/Immich/PhotoPrism: rejected for now because current value is desktop-local reliability and the roadmap already parks server features in long-term sections.
- Copying GPL/AGPL competitor implementation code, from TagStudio/PhotoPrism/Immich: rejected because UniFile is MIT; use public behavior/docs as patterns, not incompatible code.
- Native Explorer preview pane / IThumbnailProvider work, from Windows Shell integration research: rejected for active roadmap because it is already blocked in `Roadmap_Blocked.md` by signing, installer, and Explorer stability decisions.
- Cloud sharing/public albums, from Immich/PhotoPrism/Eagle: rejected because it adds account, auth, and privacy surfaces that do not help the local-first desktop user before backup/search/safety are solid.
- Plugin marketplace/community index as near-term work, from beets/Hydrus/TagStudio ecosystems: rejected until provider safety, package boundaries, and visible workflow wiring are complete.
- Fully autonomous AI file moves, from local-AI organizer demos and LSFS-style research: rejected until structured outputs, preview, rollback, provenance, and confidence thresholds are reliable.

## Sources
Project and public state:
- https://github.com/SysAdminDoc/UniFile
- https://api.github.com/repos/SysAdminDoc/UniFile/releases/latest

OSS competitors and adjacent projects:
- https://github.com/TagStudioDev/TagStudio
- https://docs.tagspaces.org/dev/metafileformats/
- https://github.com/qarmin/czkawka
- https://github.com/pkolaczk/fclones
- https://hydrusnetwork.github.io/hydrus/getting_started_tags.html
- https://docs.paperless-ngx.com/administration/
- https://docs.photoprism.app/user-guide/search/filters/
- https://docs.immich.app/administration/backup-and-restore
- https://docs.digikam.org/en/setup_application/metadata_settings.html

Commercial and closed-source signals:
- https://www.noodlesoft.com/manual/hazel/hazel-overview/
- https://en.eagle.cool/support/article/smart-folders
- https://www.devontechnologies.com/blog/20230704-smart-groups
- https://www.filejuggler.com/documentation/creating-rules/

Standards, platform APIs, and dependencies:
- https://docs.ollama.com/capabilities/structured-outputs
- https://learn.microsoft.com/en-us/windows/win32/properties/props-system-keywords
- https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-iattachmentexecute
- https://sqlite.org/fts5.html
- https://sqlite.org/threadsafe.html
- https://peps.python.org/pep-0668/
- https://doc.qt.io/qt-6/accessible.html
- https://doc.qt.io/qtforpython-6/tutorials/basictutorial/translations.html
- https://pyinstaller.org/en/stable/CHANGES.html
- https://pypa.github.io/pip-audit/
- https://cyclonedx.org/tool-center/

Community, awesome-lists, and research:
- https://github.com/simon987/awesome-datahoarding
- https://www.reddit.com/r/datacurator/comments/nm4gax/looking_for_file_manager_with_tags/
- https://github.com/orgs/linuxmint/discussions/184
- https://arxiv.org/html/2410.11843v5

## Open Questions
None that block prioritization or implementation. Installer/signing decisions for Explorer preview work remain parked in `Roadmap_Blocked.md`.
