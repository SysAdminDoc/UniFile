# UniFile Research and Implementation Plan

Research date: 2026-08-08
Repository: UniFile v9.3.33
Scope: product, ecosystem, architecture, security, reliability, and implementation planning

## Executive Summary

UniFile is a broad local-first Windows file organizer with a stronger shipped surface than its name suggests. The v9.3.33 checkout combines multiple library roots, tags and tag relationships, custom fields, collections, full-text search, media and book workflows, archive and metadata tooling, duplicate and cleanup operations, watch folders, AI providers, natural-language rule plans, a CLI, a Flask headless API, a read-only mobile shell, LAN collaboration, a PyQt-free SDK, workflow scripts, YAML plugin manifests, portable ZIP packaging, and an unsigned WiX MSI. Accessibility and release metadata have received sustained attention.

The product is at a transition point. Additional feature breadth is less valuable than making the existing breadth predictable at trust boundaries. The highest-value work is to remove plaintext credential persistence, make CLI/API scan contracts canonical, harden remote/mobile token exposure, and make storage and release verification deterministic. These items address concrete code evidence and align with recurring ecosystem signals: safe destructive workflows, explicit backup/restore, privacy-preserving local operation, stable APIs, bounded plugins, and observable large-library behavior.

The research process reviewed 60 distinct sources, including 15 direct or near-direct open-source projects, commercial organizers and rule engines, adjacent knowledge/document systems, community discussions, standards, platform APIs, academic work, dependency changelogs, and security advisory feeds. An internal feature harvest produced approximately 128 raw signals; deduplication and comparison against the live checkout produced 16 net-new roadmap items. Existing blocked publication and shell-integration work remains in Roadmap_Blocked.md and is not repeated here.

Baseline evidence from 2026-08-08:

- 724 pytest items were collected; all test assertions passed and one item was skipped, but the process exited 1 during Windows temporary-directory cleanup with WinError 5 on pytest-current.
- Strict mypy for the configured public source set passed, Sphinx documentation built with warnings treated as errors, Python compilation passed, and UniFile reported version 9.3.33.
- ruff check unifile tests reported six findings in tests/test_hardening.py, unifile/metadata.py, unifile/tagging/library.py, and unifile/workers.py.
- The release audit did not complete within its nested timeout budget. Its implementation currently inventories the whole local environment rather than a resolved project graph, calls the result CycloneDX-lite, and treats any fixable vulnerability as high severity.
- Offscreen Qt construction succeeded for 15 dialogs. Several dialogs had a minimumSizeHint larger than the adjusted test size, which is a layout-regression signal requiring systematic rendering coverage, not proof of user-visible clipping.

Recommended order:

1. P0 trust and contract work: secret storage migration, canonical scan/action-plan contracts, and remote/mobile API exposure controls.
2. P1 reliability and evidence: one SQLite connection policy, deterministic Windows test cleanup, artifact-scoped release evidence, outbound network policy, scalable search, and offscreen UI regression coverage.
3. P2 product durability: translation catalogs, disaster-recovery drills, plugin capabilities, modularization, documentation synchronization, and a zero-finding lint gate.
4. P3 compatibility polish: cron Sunday aliases and timezone/DST behavior.

## Product Map

| Surface | Shipped behavior observed in the v9.3.33 checkout | Strategic implication |
|---|---|---|
| Local library model | Multiple roots, Tag Library, TagStudio migration, collections, virtual libraries, custom fields, tag implications, archive indexes, and file-health records | Preserve a local-first data model; invest in schema contracts, restore drills, and large-library query plans |
| Discovery and search | SQLite FTS5 for core filename/tag search, field search, timeline filtering, saved searches, color search, related files, and semantic duplicate support | Search is a differentiator only if field queries, boolean composition, pagination, cancellation, and scale are measurable |
| Automation | Rules, action plans, dry-run flows, CLI scan/tag/watch/report commands, watch jobs, restricted workflow scripts, YAML manifests, and shell integration | The canonical action model must be shared by GUI, CLI, API, and automation before more actions are added |
| AI and media | Multiple AI providers, Ollama and remote-provider health, batch vision/LLM paths, confidence/few-shot flows, metadata/media lookup, books, subtitles, NFO, RAW, and cover-art tools | Provider breadth increases the need for one credential, timeout, redaction, and offline-test policy |
| Safety and recovery | Dry-run action plans, undo/apply rollback, recycle-bin cleanup, backups with checksums and pre-restore backup, archive validation, and path traversal hardening | The next step is a versioned recovery contract and evidence that failure paths remain recoverable after upgrades |
| Deployment and integration | Headless Flask API, Docker/Ollama compose, read-only mobile PWA, LAN collaboration, SDK, portable ZIP, unsigned WiX MSI, update checker, and local release audit | Remote defaults and artifact evidence are now first-class product behavior, not packaging details |
| UX and accessibility | Seven themes including high contrast, font-size preferences, RTL infrastructure, screen-reader and keyboard work, shortcuts, responsive panels, and offscreen Qt tests | Add rendered regression coverage and actual translation catalogs to convert infrastructure into dependable user-facing support |
| Extensibility | Trusted in-process plugins, display-only community manifests, restricted child-process workflow scripts, and SDK documentation | Keep trust and capability boundaries explicit before community distribution or more powerful hooks |

The main product-contract mismatch is in the scan path. The CLI assembles an action plan through cli_scan.py, while HeadlessService.scan returns a smaller result with empty destinations and does not expose action_plan. The headless scan also calls verify, which writes .unifile/file_health.json despite its read-only scan documentation. README.md describes the API as returning the same versioned JSON plan shape as the CLI. This is a concrete compatibility and trust issue rather than a documentation-only discrepancy.

## Competitive Landscape

The table groups the most useful signals from the reviewed projects. It is intentionally limited to eight comparison entries; the underlying source set includes more than ten OSS projects.

| Ecosystem | Observed strength and 2026-08-08 signal | UniFile implication |
|---|---|---|
| TagStudio | SQLite-backed tag layer over existing folders, aliases, parents, colors, fields, boolean/path/filetype/media search, refresh/relink work, and a portable non-cloud posture. Its v9.6.2 release was published 2026-08-07. | UniFile already covers more adjacent workflows; interoperability, relink behavior, sidecar boundaries, and stable list/search behavior are more valuable than another tagging feature |
| TagSpaces | Offline/serverless cross-platform organization, filename tags and sidecars, fuzzy search, notes and media players. Its v6.13.12 release was published 2026-07-20, with issue signals around sorting persistence, Android file opening, and associations. | Keep metadata export and filename/sidecar choices explicit; test persistence and platform behavior instead of assuming desktop-only semantics |
| Hydrus Network | Mature tag siblings/implications, duplicate handling, client-server scale, a broad API, and sustained database/UI concurrency work. Release v682 was published 2026-08-05. | Tag relationship correctness and API contract stability matter at scale; do not copy Hydrus complexity before UniFile has query and concurrency benchmarks |
| Czkawka and fclones | Fast, explicit duplicate grouping with dry-run, export, priorities, safe deletion/move/link actions, reproducible binaries, and warnings around destructive operations. Czkawka 12.0.1 was published 2026-07-29. | Preserve preview-before-apply and recoverability; add measurable large-library behavior and deterministic command output |
| digiKam, Immich, and PhotoPrism | Rich media metadata, face/semantic search, XMP sidecars, PWA/accessibility, duplicate suggestions, backup/export, and active security/performance release cycles. Immich v3.1.0 was published 2026-07-29. | Media parity is already broad; prioritize sidecar fidelity, privacy controls, search scale, backup drills, and response hardening |
| Paperless-ngx, Docspell, and Papra | OCR/full-text, tags, rules, ingestion, retention/trash, versions, APIs/SDKs, SSO, webhooks, and explicit warnings that sensitive documents are plaintext on an untrusted host. Paperless-ngx v3.0.5 was published 2026-08-01. | Treat remote exposure and credential handling as product design; document the local trust model and make export/restore verifiable |
| Hazel, File Juggler, Eagle, and DEVONthink | Commercially mature watched-folder rules, conditions/actions, Spotlight metadata, tags, smart folders, password-protected collections, Boolean search, and duplicate groups. | UniFile’s rule engine should emphasize explainability, dry-run diffs, condition coverage, and a stable action-plan API |
| Calibre, Nextcloud, Zotero, and Obsidian | Durable metadata conventions: OPF restore, saved searches, system tags with visibility/access levels, collections/tags, Web APIs, properties, and nested tags. | Interoperable metadata and migration formats are strategic; do not make UniFile’s database the only recoverable representation |

Community discussions reinforced a narrower product pattern: people repeatedly ask for OCR/full-text, tags, watch-folder or email ingestion, mobile access, and existing-filesystem indexing, while warning against complexity, opaque AI, and weak native UX. Local-first research emphasizes offline ownership, privacy, preservation, and collaboration as a combined design constraint. UniFile has most of the requested feature vocabulary; the remaining advantage must come from transparent behavior and dependable failure recovery.

## Security, Privacy, and Reliability

### Trust-boundary findings

| Area | Evidence in the live checkout | Risk | Planned response |
|---|---|---|---|
| Credentials | media/providers.py writes media API keys and OpenSubtitles credentials to a JSON file; scheduler job payloads can contain SMTP email data including a password; AI providers and metadata use an optional keyring with JSON fallbacks | Secret disclosure through files, backups, diagnostics, or job inspection; inconsistent behavior across optional dependencies | P0 secure secret abstraction, legacy migration, redaction, rotation, and tests |
| Headless API | /health is unauthenticated and exposes library_root and ollama_url; non-health routes depend on API keys or collaboration tokens; Flask has no configured body-size cap or rate limiter | Information disclosure, resource exhaustion, and unsafe deployment surprises | P0 redacted health, bounded requests, rate limits, explicit bind/TLS posture, and security headers |
| Mobile shell | run_mobile_server defaults to 0.0.0.0; bearer-like tokens are placed in query URLs for bootstrap/service-worker flows; tokens have no visible expiry, rotation, or revocation lifecycle | Access tokens can enter browser history, proxy logs, referrers, or copied URLs; long-lived LAN access is hard to revoke | P0 header-based lifecycle with short-lived bootstrap, rotate/revoke, no token in URLs, and response hardening |
| File and plugin execution | Workflow scripts run in restricted child processes, but trusted non-workflow plugin entrypoints execute in the host process through importlib | A trusted plugin can crash or compromise the host; capability changes are not part of the manifest contract | P2 capability declarations and isolation for high-risk hooks |
| Outbound requests | urllib, requests, SMTP, provider clients, update checks, collaboration, metadata, and plugin manifest fetching are implemented in several modules | Inconsistent timeouts, retry behavior, URL validation, user-agent policy, and secret/path redaction | P1 typed outbound network policy and offline failure tests |
| Dependency and artifact evidence | release_audit.py scans the local environment, emits incomplete license metadata, and has severity/timeout weaknesses; the project has no lock-driven artifact graph | Release evidence can be misleading or incomplete, and audits may be too slow to gate releases | P1 deterministic SBOM/license/vulnerability gate scoped to project artifacts |
| SQLite concurrency | SQLAlchemy make_engine currently produced journal_mode=delete and foreign_keys=0 in a direct probe, while other SQLite code configures WAL/busy_timeout; the changelog claims broader WAL coverage | Lock contention, inconsistent integrity enforcement, and misleading concurrency assumptions | P1 one connection policy plus stress, checkpoint, and upgrade tests |

### Reliability baseline and standards implications

SQLite FTS5 is an appropriate local search foundation, but FTS5 does not by itself solve field indexing, Boolean query planning, pagination, or result cancellation. SQLite WAL improves reader/writer overlap but still has a single writer, checkpoint behavior, same-host limitations, and SQLITE_BUSY cases. The implementation should make those constraints visible and test them rather than treating WAL as a general network-filesystem solution.

OWASP guidance supports central secret storage, rotation and revocation, TLS, input and resource limits, safe audit logging, and redaction. RFC 6750 specifically identifies bearer tokens in URI query strings as a logging and disclosure risk. CycloneDX provides the right vocabulary for components, relationships, purls, licenses, vulnerabilities, hashes, and provenance; the current release audit should produce a real artifact-scoped document rather than a local-environment approximation.

The baseline failure is operationally important. The assertions passed, but a nonzero pytest exit caused by pytest-current cleanup means release automation cannot treat the current suite result as deterministic. The fix should be in test-owned process and temporary-resource lifecycle code, with an explicit diagnostic for environmental cleanup failures. No GUI verification should depend on the interactive desktop.

## Architecture Assessment

### Strengths to retain

- The local-first SQLite model and filesystem-preserving workflows fit the privacy, ownership, and preservation requirements seen across TagStudio, TagSpaces, Calibre, and local-first research.
- The CLI, headless service, SDK, workflow script runner, and plugin manifest parser provide useful seams for non-GUI operation and automated verification.
- Action plans, dry runs, rollback/undo, recycle-bin cleanup, path validation, archive checks, and atomic writes show a safety-oriented direction.
- Provider abstractions, feature-specific workers, release scripts, Sphinx API documentation, portable packaging, and an unsigned MSI provide a credible distribution foundation.
- Accessibility settings, RTL infrastructure, keyboard navigation, high contrast, and screen-reader work are unusually visible for a desktop organizer and should be protected by rendered regression tests.

### Constraints to address

| Constraint | Current signal | Architectural response |
|---|---|---|
| Contract duplication | CLI scan and HeadlessService.scan assemble different result shapes and side effects | Define one versioned scan request/result/action-plan model consumed by GUI, CLI, API, and tests |
| Secret duplication | Media, AI, metadata, and scheduler paths each have different persistence behavior | Introduce one credential provider interface with OS keyring, environment, migration, and redaction policies |
| Storage duplication | SQLAlchemy and direct sqlite connections have different pragmas and lifecycle assumptions | Centralize connection setup, transaction boundaries, close/dispose rules, and network-FS warnings |
| Network duplication | Several modules call urllib/requests/SMTP directly | Use typed provider adapters with common timeout, retry, validation, logging, and health semantics |
| UI/worker scale | main_window.py is 4,905 lines and 175 methods; _build_ui is 1,346 lines; an LLM worker run method is 912 lines | Extract bounded facades after contracts stabilize; preserve public shims and cancellation ownership |
| Release evidence | release_audit.py is environment-scoped and slow | Resolve declared dependencies, attach artifact metadata, and emit deterministic machine-readable evidence |
| Internationalization gap | i18n.py and RTL tests exist, but no .ts or .qm catalogs were found | Add an extraction/catalog workflow and test one non-English locale before expanding language scope |

### Suggested target shape

1. A core contract layer owns versioned scan requests, item plans, action plans, errors, capabilities, and redacted diagnostics.
2. Storage adapters own SQLAlchemy/direct SQLite configuration, migrations, checkpoints, backups, and restore verification.
3. Credential and network adapters own secrets, outbound policy, provider health, and offline test doubles.
4. GUI, CLI, headless API, mobile shell, and SDK consume those core interfaces without reimplementing policy.
5. Plugins declare capabilities and use an explicit host bridge; high-risk work is isolated or disabled by default.
6. Release tooling produces artifact-specific SBOM, license, vulnerability, checksum, and contract-test evidence.

This is an incremental refactor plan, not a rewrite recommendation. The first three P0 items should land before extracting large UI modules because they define the contracts and trust boundaries that the extracted modules must use.

## Rejected Ideas

- Replace SQLite with a mandatory server database. This would weaken the local-first and portable story, add deployment and backup complexity, and avoid rather than solve the current connection-policy gap.
- Make cloud sync or multi-user collaboration the next major feature. The research shows demand, but remote data ownership, conflict resolution, authentication, and operator support would expand the threat model before the current API/mobile posture is hardened.
- Add more AI providers or autonomous bulk actions immediately. UniFile already has provider breadth; credential lifecycle, offline behavior, explainable plans, and recovery are the limiting factors.
- Auto-download and execute community plugins. The current display-only catalog and explicit trust model are safer. Capability declarations and isolation should precede any distribution mechanism.
- Rewrite the PyQt application from scratch. The application is large, but stable facades, contract tests, and bounded extraction can reduce risk without discarding working accessibility and workflow behavior.
- Treat WAL as a complete multi-host synchronization solution. SQLite documentation limits WAL to same-host access and still requires writer/checkpoint handling; cloud/network storage needs a separate design decision.
- Implement a native Explorer thumbnail/preview extension in this pass. The repository already records the compiled shell-extension and signing/toolchain issue in Roadmap_Blocked.md, which requires operator-controlled external decisions.

## Sources

### Repository and direct open-source projects

https://github.com/TagStudioDev/TagStudio
https://github.com/TagStudioDev/TagStudio/issues
https://github.com/TagStudioDev/TagStudio/releases
https://github.com/tagspaces/tagspaces
https://github.com/tagspaces/tagspaces/issues
https://docs.tagspaces.org/dev/metafileformats/
https://github.com/hydrusnetwork/hydrus
https://github.com/hydrusnetwork/hydrus/issues
https://github.com/hydrusnetwork/hydrus/releases
https://hydrusnetwork.github.io/hydrus/getting_started_tags.html
https://github.com/qarmin/czkawka
https://github.com/qarmin/czkawka/issues
https://github.com/qarmin/czkawka/releases
https://github.com/pkolaczk/fclones
https://github.com/KDE/digikam
https://docs.digikam.org/en/setup_application/metadata_settings.html
https://github.com/immich-app/immich
https://github.com/immich-app/immich/releases
https://github.com/photoprism/photoprism
https://docs.photoprism.app/user-guide/search/filters/
https://github.com/paperless-ngx/paperless-ngx
https://github.com/paperless-ngx/paperless-ngx/releases
https://github.com/paperless-ngx/paperless-ngx/blob/dev/docs/administration.md
https://github.com/beetbox/beets
https://docs.beets.io/en/latest/plugins/index.html
https://manual.calibre-ebook.com/gui.html
https://docs.nextcloud.com/server/stable/user_manual/en/files/tagging.html
https://docspell.org/docs/
https://docs.papra.app/

### Commercial products

https://www.noodlesoft.com/manual/hazel/hazel-basics/about-folders-rules/
https://www.filejuggler.com/documentation/
https://en.eagle.cool/support/desktop/organize
https://www.devontechnologies.com/blog/20230704-smart-groups

### Adjacent products and curated lists

https://www.zotero.org/support/collections_and_tags
https://www.zotero.org/support/dev/web_api/v3/basics
https://obsidian.md/help/Plugins/Search
https://awesome-selfhosted.net/tags/document-management.html

### Community signal

https://www.reddit.com/r/selfhosted/comments/1r9icxn/best_selfhosted_open_source_document_management/
https://news.ycombinator.com/item?id=40717797

### Standards, platform APIs, and security

https://www.sqlite.org/fts5.html
https://www.sqlite.org/wal.html
https://sqlite.org/threadsafe.html
https://www.sqlite.org/pragma.html
https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html
https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
https://www.rfc-editor.org/info/rfc6750
https://keyring.readthedocs.io/en/latest/index.html
https://doc.qt.io/qt-6/accessible.html
https://doc.qt.io/qt-6/internationalization.html
https://learn.microsoft.com/en-us/windows/win32/properties/props
https://cyclonedx.org/capabilities/sbom/
https://csrc.nist.gov/pubs/sp/800/218/final

### Academic and engineering research

https://www.inkandswitch.com/essay/local-first/
https://arxiv.org/abs/2109.09668

### Dependency changelogs and security advisories

https://pypi.org/project/PyQt6/
https://www.sqlalchemy.org/changelog/
https://flask.palletsprojects.com/en/stable/changes/
https://pyinstaller.org/en/latest/CHANGES.html
https://osv.dev/list?ecosystem=PyPI&q=pillow

## Open Questions

These questions do not block the implementation plan; they identify decisions that should be made in the corresponding roadmap acceptance tests.

- Should remote headless/mobile access be loopback-only by default, or may an operator explicitly bind to a LAN address after a loud security check? The safe default is loopback, with remote use requiring authenticated HTTPS termination or a documented trusted reverse proxy.
- Is the Windows keyring available in every supported interactive and unattended deployment? If not, what operator-approved fallback may store a reference rather than a secret, and how should legacy plaintext files be migrated or retained for rollback?
- Which existing CLI/API consumers rely on the current smaller headless scan response? The contract work should provide a versioned compatibility path and machine-readable deprecation diagnostics.
- Which artifact formats must the release gate cover: portable ZIP, MSI, SDK wheel, source distribution, or all of them? The implementation can support all targets, but the acceptance policy needs one explicit required set.
- Should translation work begin with one maintained non-English locale, or should the project first ship an extraction and contributor workflow without promising a language? The first catalog should be selected based on a maintainer who can review safety-critical strings.
- Which plugin capabilities are acceptable in-process for trusted local plugins, and which must always be isolated? The default should be deny-by-capability with explicit per-plugin approval.
- What minimum library size and hardware profile should define the search benchmark? A reproducible synthetic fixture and one anonymized real-world profile are preferable to an unbounded performance claim.
- Should backup archives include provider configuration references, or should all credentials be excluded and re-established after restore? The security-preserving default is exclusion with a restore checklist.
- Are Sunday=7 cron expressions expected for compatibility with external schedulers? The proposed parser change treats 0 and 7 as Sunday while retaining standard OR semantics and documenting local timezone/DST behavior.
