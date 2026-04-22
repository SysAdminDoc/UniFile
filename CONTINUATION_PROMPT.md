# UniFile — Continuation Prompt

This document is a self-contained briefing for a new AI session to pick up
where v9.3.0 left off. Paste the "Prompt" section below into a new chat
along with access to the repo.

---

## Context (what's been done)

UniFile is a PyQt6 AI file-organization app at `~/repos/UniFile/`.
Between v9.0.0 and v9.3.0 we ran four consecutive hardening passes. The
headline outcomes:

- **129 tests passing** across `test_engine`, `test_hardening`, `test_ignore`,
  `test_learning`, `test_models`, `test_naming`, `test_critical`,
  `test_v91_features`, `test_v92_features`, `test_v93_features`.
- **`python -m pyflakes unifile/ | grep "undefined name"` returns zero.**
- **Shipped**: headless `classify`/`list-profiles`/`list-models` CLI,
  `--output-json` scan-plan export, Semantic Search dialog, Unified
  Settings Hub, audio-duplicate filter, Chromaprint availability detection,
  PyPI-style `pyproject.toml`, GitHub release workflow for Windows exe,
  SECURITY/CONTRIBUTING/ATTRIBUTION docs.
- **Fixed**: 97 latent `NameError`s, 6 leaked `urlopen` connections,
  `PIL.Image` handle leaks in `_compute_phash`, cross-drive rename in
  `ApplyAepWorker`, `.bak` collision in `safe_merge_move`, `is_protected()`
  parent-segment matching, `learning.py` singleton race, thread-unsafe
  SQLite in `SemanticIndex`, drag-and-drop `AttributeError`, and many more.

Refer to `CHANGELOG.md` for the full list.

## What's still open

These couldn't be completed in the last session — either because they need
a running GUI or because they're architecturally risky without integration
tests first. They're prioritized below.

### 1. Re-capture `screenshot.png` (blocks headless; high user-visible impact)

The hero screenshot at the top of `README.md` is from the pre-v9 UI and no
longer matches the "review-first" workspace. This needs someone to:

- Run UniFile v9.3+ on Windows at 125% DPI (see `memory/screenshots.md` if
  using the Claude-code harness — there's a DPI-aware capture helper).
- Populate the main view with a small representative scan (e.g.
  `~/Downloads`) so categories, confidence colors, and the sidebar are
  visible.
- Save a 1600×1000-ish PNG to `screenshot.png` in the repo root.
- Also re-capture the Settings Hub and Semantic Search dialogs for a
  new "Features gallery" section in README.

### 2. Deeper `main_window.py` mixin extraction (4000+ lines)

`main_window.py` is 4037 lines with 9 distinct responsibilities. The safe
path forward is *incremental*:

1. **Add an integration test scaffold first.** Create
   `tests/test_main_window_smoke.py` that uses `pytest-qt` to instantiate
   `UniFile` headlessly (`QT_QPA_PLATFORM=offscreen`) and asserts that each
   mode switches cleanly. Keep it slow-marked (`@pytest.mark.slow`) so the
   default suite stays fast.
2. **Extract one mixin at a time**, test-backed: start with
   `UndoMixin` (lines ~1895-1940 — `_on_undo`, ~40 lines, few shared
   attrs), then `FilterMixin` (`_apply_filter`, `_populate_face_filter`,
   `_on_conf_changed`), then `TrayMixin`, then `WatchMixin`.
3. After each extraction, verify `UniFile(ScanMixin, ApplyMixin, ThemeMixin,
   UndoMixin, ...)` still passes `tests/test_main_window_smoke.py` +
   existing suite.
4. **Never** extract something that touches `self.cmb_op`, `self.tbl`, or
   `self.sld_conf` across more than 3 methods — those should stay in
   `UniFile` itself.

### 3. Per-folder rule-set overrides (feature request, medium effort)

`.unifile.conf` already supports per-directory category overrides. Extend
it to support rule overrides:

- Schema: add a `[rules]` TOML-ish section that can reference rules from
  the global rule engine by name (include) or inline-define new ones.
- `load_directory_config()` in `unifile/files.py` should return both the
  category list AND a rule delta.
- `ScanCategoryWorker` / `ScanFilesWorker` need to merge the per-folder
  rule delta with the global rule list before invoking `RuleEngine.evaluate`.
- UI: a new "Per-folder rules" tab in the Rules editor that shows active
  per-folder overrides for the currently-selected source path.

### 4. UX polish items (from the earlier audit, not yet addressed)

- **Per-file scan progress**: The infrastructure is in place
  (`ScanMixin._set_current_scan_item`, throttled 100 ms). The remaining
  work is connecting worker signals to it in `_scan_aep`, `_scan_cat`,
  `_scan_files`. ~30 lines across 3 workers.
- **Accessible empty states**: `scan_mixin.py` around lines 285/472/682
  says things like "No files found" — add a "Try broadening the filter"
  follow-up hint and a **primary action button** to open the filter.
- **Tab-order audit of dialogs**: Several dialogs don't have a sensible
  tab order. Use `QWidget.setTabOrder()` explicitly in `_build_ui`.

### 5. Linter / type checker debt

`ruff` is configured in `pyproject.toml` but the lint job in
`.github/workflows/tests.yml` is `continue-on-error: true` because the
codebase isn't ruff-clean yet. Progressively fix warnings by file and
flip the flag once clean.

### 6. Stale test files

`tests/smoke_v86.py` … `tests/smoke_v89.py` are manual exit-code scripts.
Convert them to parametrized pytest tests or delete them. `tests/audit_out.txt`
is a one-off debug dump — delete.

---

## Prompt for the new session

```
You are continuing a hardening effort on the UniFile project at
~/repos/UniFile/. The previous sessions shipped v9.0.1 through v9.3.0
and the current state has 129 passing tests, zero pyflakes undefined-
name issues, and a clean CHANGELOG.

Read these first to get oriented:
  - README.md, CHANGELOG.md, CONTRIBUTING.md
  - CONTINUATION_PROMPT.md (what's still open, prioritized)
  - unifile/main_window.py structure (4037 lines; don't break it)

Then pick the highest-value item from CONTINUATION_PROMPT.md that is
safe to do in your current environment, and execute it end-to-end:
research → implement → test → update CHANGELOG → commit.

Rules that must be followed:
  1. Every code change comes with a test. Ship only with `pytest` green.
  2. Never regress the pyflakes-clean state:
     `python -m pyflakes unifile/ | grep "undefined name"` must stay empty.
  3. Follow the existing style: short why-comments, no docstrings on
     trivial functions, Ruff line-length 110.
  4. Bump the patch version and update CHANGELOG.md + README.md badges
     + pyproject.toml + unifile/__init__.py + unifile/bootstrap.py
     in the same commit.
  5. Commit messages follow the existing pattern: one-line subject
     "vX.Y.Z: <topic> — <one-line summary>" then a blank line then a
     bullet list. NEVER include Co-Authored-By trailers (per CLAUDE.md).
  6. If an item truly requires a running GUI (e.g. screenshot
     re-capture) and you can't run one, skip it and note why.
  7. Commit after each coherent chunk — don't let unrelated changes
     accumulate into one mega-commit.

Start by running the full test suite to confirm the baseline, then
pick one item.
```

---

## Handy verification commands

```bash
# From the repo root
python -m pytest                                    # 129 passing
python -m pyflakes unifile/ | grep "undefined name" # expected: no output
python -c "import unifile; print(unifile.__version__)"  # v9.3.0
python -m unifile --version                         # UniFile 9.3.0
python -m unifile list-profiles --json
python -m unifile classify README.md --json
```
