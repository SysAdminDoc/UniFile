# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Actionable Items

- [ ] **Provider-abstraction layer** — one interface, adapters for each LLM backend, test double for offline CI (already partially implemented in `ai_providers.py`)

- [ ] **Action DAG + dry-run renderer** — LLM produces proposed actions as JSON; GUI renders diff; user approves atomic apply

- [ ] **Checkpointed scans** — large library scans write progress to SQLite so crash/resume is clean

- [ ] **Hydrus tag-sibling/parent DB layout** — `tag_implications(antecedent, consequent)` + `tag_siblings(bad_tag, good_tag)` tables; query-time expansion

- [ ] **Sidecar-tag coexistence** — write `.xmp` sidecars in TagStudio format alongside originals; read them back on re-open so tags survive outside UniFile

- [ ] P2 — Decompose the main window and worker orchestration behind stable facades
  Why: UniFile is concentrated in a 4,905-line, 175-method main window with a 1,346-line UI builder, while one LLM worker run method is 912 lines; this raises change and cancellation risk.
  Evidence: AST inventory of unifile/main_window.py and unifile/workers.py on 2026-08-08; existing UI tests cover only a small portion of these modules.
  Touches: scan/apply, library, media, cleanup, settings, worker lifecycle, public shims, contract tests, and module boundaries.
  Acceptance: Bounded domain controllers are extracted behind stable facades; public imports and user-visible behavior remain compatible; contract tests cover scan/apply/library/media/cleanup flows; every worker has explicit cancellation, close, and error ownership; module complexity thresholds are recorded and enforced without a rewrite.
  Complexity: XL

- [ ] P2 — Restore a zero-finding repository lint gate
  Why: The configured ruff check reported six findings on 2026-08-08, including import ordering, unnecessary open mode, a late import, and an unused import.
  Evidence: ruff check unifile tests baseline output for tests/test_hardening.py, unifile/metadata.py, unifile/tagging/library.py, and unifile/workers.py.
  Touches: the four reported source/test files, ruff configuration if required, Makefile lint target, and contributor verification docs.
  Acceptance: ruff check unifile tests exits 0 without broad ignores; the lint target is included in the documented verification sequence; any intentional compatibility import has a narrow documented exemption and a regression test.
  Complexity: S

- [ ] P3 — Make cron scheduling interoperable across Sunday aliases and local-time edge cases
  Why: scheduler.py explicitly omits Sunday=7 and does not define timezone or DST behavior for local-time matching.
  Evidence: unifile/scheduler.py parser and matcher logic reviewed on 2026-08-08; standard cron compatibility expectations.
  Touches: cron parser/matcher, job schema, timezone handling, fixtures, scheduler diagnostics, and documentation.
  Acceptance: Sunday accepts both 0 and 7; standard OR semantics are preserved; timezone and DST behavior is explicit; Sunday-alias and DST-boundary fixtures pass; invalid expressions receive actionable diagnostics.
  Complexity: S
