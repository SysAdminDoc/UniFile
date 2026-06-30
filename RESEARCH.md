# Research — UniFile

## Executive Summary
UniFile is a local-first Python/PyQt6 desktop organizer for classifying, tagging, cleaning, deduplicating, previewing, and undoing work on existing folders. Its strongest current shape is the review-first desktop workflow: broad parsers, a SQLAlchemy tag library, optional local/network AI, sidecar foundations, diagnostics, undo logs, and a now-verified frozen build path at v9.3.31. The highest-value direction is to convert recent infrastructure into visible, recoverable workflows while tightening trust boundaries before adding larger library features.

- Verified: treat the existing Cleanup & Safety Recycle Bin item as the next root-cause safety fix; `unifile/cleanup.py:621` and `unifile/cleanup.py:629` still permanently remove files when `send2trash` is missing.
- Verified: wire inert interoperability modules into workflows: `unifile/tagspaces.py`, `unifile/win_properties.py`, and `unifile/i18n.py` have tests but still need GUI/startup/scan callers.
- Verified: replace regex-based LLM JSON extraction with schema-validated outputs and central HTTP diagnostics across `unifile/ollama.py`, `unifile/ai_providers.py`, `unifile/engine.py`, and `unifile/workers.py`.
- Verified: add indexed/FTS-backed Tag Library search before scaling large libraries; `unifile/tagging/library.py:140`, `:735`, and `:801` rely on wildcard `ilike`.
- Verified: add full-library backup/restore before more migrations and sidecar import/export; current backups cover apply snapshots and DB migrations, not user-triggered library disaster recovery.
- Verified: split heavyweight face/local-AI extras and remove the `--break-system-packages` bootstrap path; `pyproject.toml:71`-`:74` and `unifile/bootstrap.py:143` keep source installs fragile.
- Verified: add release SBOM/license/vulnerability artifacts; `make audit` exists, but release evidence stops at local audit and PyInstaller checksum.
- Verified: remove tracked root debug outputs (`audit2.txt`, `cats.txt`, `smoke86_out.txt`) and enforce repo hygiene.

## Product Map
- Core workflows: scan folders into categorized previews; review and apply move/rename plans with undo; tag/search files in a local SQLite library; run cleanup/duplicate/media/metadata tools; export diagnostics and build a frozen desktop app.
- User personas: Windows desktop power users organizing Downloads/Desktop/Documents; photographers and media collectors needing metadata and sidecars; local-AI users who want offline classification; maintainers releasing a signed-ish local PyInstaller build.
- Platforms and distribution: Python 3.10+, PyQt6 desktop, strongest on Windows, source install plus PyInstaller onedir build; no GitHub Actions build dependency.
- Key integrations and data flows: filesystem metadata, SQLite/SQLAlchemy tag DB, XMP and TagSpaces sidecars, Windows Shell properties, Mark-of-the-Web source URL metadata, OCR/media parsers, Ollama/OpenAI-compatible providers, redacted diagnostics ZIPs.

## Competitive Landscape
- TagStudio / TagSpaces: Strong non-destructive library and sidecar interoperability, visible import/export paths, search grammar, and translation surface. UniFile should learn from explicit migration/sidecar UX and avoid leaving sidecar code as hidden plumbing.
- Czkawka / organize: Strong preview/simulation habits, fast cleanup analyzers, CLI automation, cache support, and explicit safe file-operation options. UniFile should learn fail-closed cleanup and dry-run ergonomics; avoid destructive fallbacks when safety dependencies are unavailable.
- Hydrus Network: Strong tag graph model, high-scale local media libraries, and privacy-first no-phone-home posture. UniFile should learn tag implications/siblings and scale-aware DB design; avoid Hydrus-level complexity before basic GUI search/indexing is fast.
- paperless-ngx / PhotoPrism / Immich: Strong indexing, backups, metadata search, troubleshooting docs, and privacy positioning for large personal archives. UniFile should learn backup-first operations and search observability; avoid server-first or multi-user pivots before desktop reliability is complete.
- DEVONthink / Hazel / Eagle / File Juggler: Strong paid signals around smart groups, automation rules, batch metadata, duplicate handling, and visual asset management. UniFile should copy the recoverable preview-and-rule patterns, not subscription/cloud account assumptions.

## Security, Privacy, and Reliability
- Verified bug/risk: `unifile/cleanup.py:621` and `unifile/cleanup.py:629` fall back to `os.rmdir`/`os.remove`; cleanup should fail closed or clearly require trash support instead of silently bypassing recovery.
- Verified risk: `unifile/bootstrap.py:143` tries `--break-system-packages`; PEP 668 treats this as an explicit override of externally managed environment protections.
- Verified risk: raw network/AI calls are spread across `unifile/ai_providers.py`, `unifile/ollama.py`, `unifile/engine.py`, `unifile/metadata.py`, and `unifile/workers.py`, making timeout, retry, diagnostics, and redaction behavior inconsistent.
- Verified risk: `archive_indexer.py:60`, `ratings.py:36`, and `semantic.py:49` use `check_same_thread=False`; concurrency policy needs explicit locking, WAL/busy-timeout consistency, and close semantics.
- Verified gap: `Entry.source_url` exists (`unifile/tagging/models.py:217`) but scans do not import Windows Zone.Identifier `HostUrl`/`ReferrerUrl`, so downloaded-file provenance remains manual.
- Verified gap: release hardening lacks SBOM/license/vulnerability artifact generation despite optional parser, OCR, AI, and PyQt6 dependencies.
- Recovery needs: full-library backup/restore, integrity checks, delete fail-closed behavior, and sidecar import dry-runs should land before larger multi-root/cloud/plugin work.

## Architecture Assessment
- Boundary improvements needed: connect `unifile/tagspaces.py` to Tag Library/Settings UI, `unifile/win_properties.py` to scan metadata, and `unifile/i18n.py` to `unifile/__main__.py` before adding new interop modules.
- Refactor candidates: centralize provider HTTP in one request helper; move LLM parsing to typed schema validation; formalize SQLite connection ownership; add FTS/index migrations for tag library search.
- Test gaps: 463 tests collect successfully, but GUI coverage mostly instantiates widgets; add rendered offscreen screenshot/nonblank smoke tests for main, Tag Library, Cleanup, and Settings Hub surfaces.
- Documentation gaps: README and CONTRIBUTING document `make` commands, but the project is Windows-first; provide a Python task runner mirroring Makefile targets.
- Distribution gaps: PyInstaller smoke and SHA-256 are now present, but release evidence should include SBOM, license inventory, vulnerability report, and dependency provenance.
- Hygiene gaps: tracked root debug outputs (`audit2.txt`, `cats.txt`, `smoke86_out.txt`) should be removed or converted into intentional fixtures with a guard against future ad-hoc dumps.

## Rejected Ideas
- Filename-mutating tags as the default, from TagSpaces/filetags patterns: rejected because UniFile's product philosophy is non-destructive metadata/sidecars; filename tags belong only as explicit import/export.
- Server/NAS/multi-user mode as near-term priority, from paperless-ngx/Immich/PhotoPrism: rejected for now because current value is desktop-local reliability and the roadmap already parks server features in long-term sections.
- Copying GPL/AGPL competitor implementation code, from TagStudio/PhotoPrism/Immich: rejected because UniFile is MIT; use public behavior/docs as patterns, not incompatible code.
- Native Explorer preview pane / IThumbnailProvider work, from Windows Shell integration research: rejected for active roadmap because it is already blocked in `Roadmap_Blocked.md` by signing, installer, and Explorer stability decisions.
- Cloud sharing/public albums, from Immich/PhotoPrism/Eagle: rejected because it adds account, auth, and privacy surfaces that do not help the local-first desktop user before backup/search/safety are solid.
- Plugin marketplace/community index as near-term work, from beets/Hydrus/TagStudio ecosystems: rejected until provider safety, package boundaries, and visible workflow wiring are complete.

## Sources
OSS competitors:
- https://github.com/TagStudioDev/TagStudio
- https://docs.tagstud.io/search/
- https://docs.tagspaces.org/dev/metafileformats/
- https://github.com/qarmin/czkawka
- https://github.com/tfeldmann/organize
- https://github.com/hydrusnetwork/hydrus
- https://github.com/paperless-ngx/paperless-ngx
- https://github.com/photoprism/photoprism
- https://github.com/immich-app/immich

Commercial and adjacent:
- https://www.tagspaces.org/products/pro/
- https://www.devontechnologies.com/apps/devonthink
- https://www.noodlesoft.com/
- https://eagle.cool/
- https://www.filejuggler.com/

Standards and platform APIs:
- https://learn.microsoft.com/en-us/windows/win32/properties/props-system-keywords
- https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-iattachmentexecute
- https://sqlite.org/fts5.html
- https://sqlite.org/threadsafe.html
- https://peps.python.org/pep-0668/
- https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTranslator.html
- https://doc.qt.io/qt-6/accessible.html
- https://www.freedesktop.org/wiki/Specifications/trash-spec/

Dependencies and security:
- https://pyinstaller.org/en/stable/CHANGES.html
- https://pypa.github.io/pip-audit/
- https://cyclonedx.org/
- https://setuptools.pypa.io/en/latest/pkg_resources.html
- https://www.riverbankcomputing.com/software/pyqt/license

Community and lists:
- https://github.com/simon987/awesome-datahoarding
- https://hn.algolia.com/?q=TagStudio
- https://www.reddit.com/r/DataHoarder/search/?q=file%20tagging%20sidecar&restrict_sr=1

## Open Questions
None that block prioritization or implementation. Installer/signing decisions for Explorer preview work remain parked in `Roadmap_Blocked.md`.
