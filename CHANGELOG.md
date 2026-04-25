# Changelog

All notable changes to UniFile will be documented in this file.

## [v9.3.17] — High Contrast Theme, Font Size, Saved Searches, Inbox

### Added
- **High Contrast theme** (`config.py`):
  - New `THEME_HIGH_CONTRAST` palette: pure black/white with yellow accents, WCAG AA compliant
  - Registered in `THEMES` dict — automatically appears in the Theme Picker dialog
  - Subtitle added to the theme picker card: "WCAG AA compliant — pure black/white with yellow accents"

- **Configurable font size** (`config.py`):
  - `load_font_size()` / `save_font_size(size)` — persisted to `%APPDATA%\UniFile\accessibility.json`
  - `_build_theme_qss(t, font_size)` now scales base widget, input, button, table, and menu font sizes
  - `get_active_stylesheet()` automatically incorporates the saved font size
  - `_on_theme_changed()` in `theme_mixin.py` uses the active font size when regenerating QSS

- **Accessibility dialog** (`unifile/dialogs/accessibility.py`):
  - Font size slider (8–24 px) with live preview on the main window
  - "Reset to default" link; Apply / Cancel buttons
  - Accessible from: Settings Hub → System → `Accessibility…` and Ctrl+K "Accessibility"

- **Saved Searches / Smart Views** (`unifile/saved_searches.py`):
  - `SavedSearch` dataclass: name, query, category, conf_min, created_at, last_run, result_count
  - `load_saved_searches()`, `add_search()`, `delete_search()`, `update_run_stats()` API
  - Persisted to `%APPDATA%\UniFile\saved_searches.json`

- **Saved Searches dialog** (`unifile/dialogs/saved_searches_dialog.py`):
  - Name + save current filters in one row; list of all saved searches below
  - Apply: pushes query/category/confidence back to the main window; Delete: removes entry
  - Accessible from: Settings Hub → Tools → `Saved Searches…` and Ctrl+K "Saved Searches"
  - Command Palette "Smart View" section: each saved search appears as a runnable command

- **Inbox / Quick Capture** (`unifile/inbox.py`):
  - `load_inbox_config()`, `save_inbox_config()`, `get_inbox_path()`, `is_inbox_enabled()`, `get_inbox_count()` API
  - Persisted to `%APPDATA%\UniFile\inbox.json`

- **Inbox dialog** (`unifile/dialogs/inbox_dialog.py`):
  - Folder picker with live file count; Open Folder shortcut; Clear Inbox / Save buttons
  - Accessible from: Settings Hub → Tools → `Inbox / Quick Capture…` and Ctrl+K "Inbox"

### Changed
- `theme_mixin.py`: `_on_theme_changed()` now calls `load_font_size()` and passes it to `_build_theme_qss()`
- `settings_hub.py`:
  - System tab: added `Accessibility…` button; updated description to mention High Contrast
  - Tools tab: added `Saved Searches…` and `Inbox / Quick Capture…` buttons
- `dialogs_mixin.py`: added `_open_accessibility()`, `_open_saved_searches()`, `_open_inbox()` slots
- `dialogs/command_palette.py`: added Accessibility, Inbox, Saved Searches commands; new Smart View section for saved searches
- `dialogs/theme.py`: added subtitle for "High Contrast" theme in the picker dialog


## [v9.3.16] — Shell Integration, Ctrl+K Command Palette, Archive Indexer

### Added
- **Windows Shell Integration** (`unifile/shell_integration.py`):
  - `Organize with UniFile` context menu on folder right-click (HKCU, no admin required)
  - Background context menu entry (right-click on empty Explorer area)
  - Send To shortcut in `%APPDATA%\Microsoft\Windows\SendTo`
  - CLI: `python -m unifile install-shell` / `uninstall-shell`
  - Settings Hub → System tab → `Shell Integration…` button
  - New dialog (`dialogs/shell_integration_dialog.py`) with live install/uninstall status

- **Ctrl+K Command Palette** (`unifile/dialogs/command_palette.py`):
  - Spotlight-style floating launcher triggered by Ctrl+K or Settings → Command Palette
  - Real-time search across: built-in commands, saved profiles, all categories
  - Arrow-key navigation, Enter to execute, Escape to close
  - Rebuilds command list each open to pick up new profiles/categories

- **Archive Content Indexer** (`unifile/archive_indexer.py`):
  - Indexes files inside `.zip`, `.7z`, `.rar`, `.tar.*` without extraction
  - SQLite cache keyed by (path, mtime, size); only re-scans changed archives
  - `scan_file()`, `scan_directory()`, `search()`, `index_stats()`, `clear_index()` API
  - `ArchiveIndexWorker` QThread with progress/finished/error signals
  - New dialog (`dialogs/archive_indexer_dialog.py`) with directory picker, progress bar, search
  - Accessible via Settings Hub → Tools tab → `Archive Content Indexer…`

### Changed
- Settings Hub: added `Shell Integration…` to System tab; new `Tools` tab
- `main_window.py`: Ctrl+K shortcut + `_open_command_palette()` slot; `Command Palette` menu item
- `dialogs_mixin.py`: `_open_shell_integration()` and `_open_archive_indexer()` slots
- `__main__.py`: `install-shell` and `uninstall-shell` CLI subcommands



v9.3.14's release workflow failed with
`FileNotFoundError: Icon input file D:\a\UniFile\UniFile\icon.ico not found`
during the PyInstaller EXE-assembly step. `UniFile.spec` has declared
`icon='icon.ico'` from the start, but the file was never checked in —
only `icon.png` exists in the repo. Local builds on developer machines
had been succeeding because either an `icon.ico` had been generated
manually at some point, or PyInstaller had been launched from a spec
variant that pointed at the PNG.

Fixed:
- Generated a multi-size Windows `.ico` from `icon.png` using Pillow
  (256/128/64/48/32/24/16). Letterboxed because the source is 1024×516
  rather than square — fine for a first cut; a later pass can crop or
  resvg the source to a square if taskbar clarity suffers.
- Committed `icon.ico` alongside the existing `icon.png`.
- v9.3.14's tag remains on GitHub but has no release attached.
  v9.3.15 triggers the workflow with all assets now present.

## [v9.3.14] — Track `UniFile.spec` in git (v9.3.13 release workflow fix)

The v9.3.13 release workflow failed because `UniFile.spec` — the
PyInstaller entry point — wasn't actually checked into git. The
project's `.gitignore` inherited the generic Python `*.spec` pattern,
which was silently catching the only spec file the release pipeline
needs. The file existed locally across every machine that built a
release manually, but never made it into the repo.

Fixed:
- `.gitignore` — added `!UniFile.spec` negation so the one tracked
  spec file is never re-ignored, even if someone else drops more
  `.spec` files into the repo root.
- `UniFile.spec` — tracked for the first time, carrying the mixin-aware
  `hiddenimports` list staged in v9.3.13.

v9.3.13's tag still exists on GitHub but has no release attached. A
fresh v9.3.14 tag triggers the same workflow with the spec file now
actually present on checkout.

## [v9.3.13] — Release packaging: PyInstaller spec refreshed for new mixins

`UniFile.spec` was last updated before the mixin sweep that started in
v9.3.7. PyInstaller's static analyzer normally picks up
`from unifile.xxx_mixin import XxxMixin` in `main_window.py`, but
explicit `hiddenimports` are the fail-safe — missing entries cause
`ImportError` at first launch of the frozen exe, not at build time.

Added to `hiddenimports`:
- `unifile.theme_mixin`, `unifile.undo_mixin`, `unifile.filter_mixin`,
  `unifile.tray_mixin`, `unifile.watch_mixin`, `unifile.dialogs_mixin`
  — the six mixins extracted between v9.3.7 and v9.3.11.
- `unifile.ui_helpers` (added in v9.3.0).
- `unifile.dialogs.advanced_settings`, `unifile.dialogs.settings_hub`
  — the modules `DialogsMixin` imports lazily inside its methods.
- `unifile.semantic`, `unifile.embedding` — referenced through lazy
  imports in several dialogs.

No code changes. No test changes. Pure packaging metadata catch-up.

## [v9.3.12] — Tab-order / initial-focus audit (keyboard UX)

### Accessibility
Three of the most-visited dialogs got explicit `setTabOrder(...)` chains
and `setFocus()` on the widget a keyboard user is most likely to use
first:

- `ProtectedPathsDialog` — enable toggle → custom list → add-folder →
  add-file → protect-by-name → remove → Save/Cancel. Initial focus on
  the master enable toggle so `Space` immediately locks/unlocks the
  protection layer.
- `PhotoSettingsDialog` — master enable → folder preset → geocoding →
  blur + threshold → scene → face + library button → enhanced
  descriptions → Save/Cancel. Focus on the master toggle.
- `OllamaSettingsDialog` — URL input → model list. Focus on the URL
  input so users can immediately paste / edit the endpoint.

Widget creation order already matched visual order in all three
dialogs, so the explicit `setTabOrder` calls are redundant *today*. The
value is defensive: future layout refactors can shuffle widget creation
without accidentally breaking keyboard nav.

### Tests
- `tests/test_tab_order.py` — three source-level parametrized assertions
  that each audited dialog retains its expected `setTabOrder` and
  `setFocus` calls. Grep-based rather than Qt-live because the
  pytest-qt suite already covers live instantiation; adding another
  expensive per-dialog fixture would just slow the suite down.

### Impact
| Metric | Before | After |
|--------|--------|-------|
| Tests | 354 | **359** |
| Dialogs with explicit tab order | 0 | 3 |
| Ruff violations | 0 | 0 |
| Pyflakes undefined-name | 0 | 0 |

## [v9.3.11] — DialogsMixin: 13 dialog-launcher methods out of main_window.py

### Architecture
Every `_open_*_settings` / `_open_*_dialog` in `main_window.py` had the
same shape: instantiate dialog, exec, optionally log. Thirteen of the
most-self-contained ones are now in a single place:

- `unifile/dialogs_mixin.py` — `DialogsMixin`:
  - Settings & model dialogs: `_open_custom_cats`, `_open_ollama_settings`,
    `_open_ai_providers`, `_open_whisper_settings`, `_open_semantic_settings`,
    `_open_semantic_search`, `_open_settings_hub`, `_open_embedding_settings`,
    `_open_learning_stats`.
  - Rule / plugin / schedule / theme: `_open_schedule_dialog`,
    `_open_plugin_manager`, `_open_protected_paths`, `_open_sort_rules`,
    `_open_theme_picker`.

All the lazy imports (pandas-heavy `CsvRulesDialog`, embeddings-heavy
`SemanticSearchDialog`, etc.) survive the move intact — the mixin keeps
them inside the methods to preserve fast cold-start.

Also caught and cleaned up a stale duplicate of `_open_watch_history`
that was still present in `main_window.py` even though v9.3.10 had
already put the canonical copy on `WatchMixin`. Python's MRO resolved
the main_window copy first, making the WatchMixin version dead code.
Now only the mixin version exists.

### Mixin roster (current)
`UniFile(ScanMixin, ApplyMixin, ThemeMixin, UndoMixin, FilterMixin,`
`       TrayMixin, WatchMixin, DialogsMixin, QMainWindow)` — **8 mixins**.

### Metrics
| File | Lines (before extractions started) | Lines now |
|------|------------------------------------|-----------|
| `main_window.py` | 4121 | **3827** (−294 / −7%) |

### Tests (351 → 354)
`tests/test_main_window_smoke.py`:
- MRO check extended to `DialogsMixin`.
- Method-resolution parametrize covers five representative dialog
  openers: `_open_custom_cats`, `_open_ollama_settings`,
  `_open_settings_hub`, `_open_theme_picker`, `_open_sort_rules`.

Ruff: 0 violations. Pyflakes: 0 undefined names. All tests passing.

## [v9.3.10] — TrayMixin + WatchMixin + `validate-rules` CLI

### Architecture — two more mixins extracted
Continues the mixin sweep. Two more modules:

- `unifile/tray_mixin.py` — `TrayMixin` owns the `QSystemTrayIcon`
  lifecycle: `_setup_tray`, `_on_tray_activated`, `_tray_show`,
  `_tray_exit` (~40 lines).
- `unifile/watch_mixin.py` — `WatchMixin` owns watch-mode toggling:
  `_watch_pause`, `_toggle_watch_mode`, `_open_watch_history`
  (~60 lines). Reads `self._tray` (provided by `TrayMixin`) but never
  mutates it.

`UniFile(ScanMixin, ApplyMixin, ThemeMixin, UndoMixin, FilterMixin,
TrayMixin, WatchMixin, QMainWindow)` — seven mixins now (was three
before v9.3.7). `main_window.py` is down another ~105 lines.

### CLI — `validate-rules <dir>` (new subcommand)
Users can now validate a directory's `.unifile_rules.json` without
launching the GUI:

```
$ python -m unifile validate-rules ./client-project
rules file:  ./client-project/.unifile_rules.json
base rules:  3
include:     pdf-rule, img-rule
inline:      1
effective:   3 rule(s)
names:
  - pdf-rule
  - img-rule
  - local-custom
```

Emits JSON with `--json`. Exit codes are contract:
- `0` — valid (parsed, all `include`/`exclude` names match globals)
- `2` — missing file (or non-directory path)
- `3` — malformed / not a JSON object
- `4` — references an unknown global rule name

Handy for CI of a team's shared project directory: a CI job can run
`validate-rules` on every folder with a `.unifile_rules.json` after a
rule refactor, catching stale `include`/`exclude` entries before they
silently drop rules at scan time.

### Tests — 14 new (337 → 351)
- `tests/test_cli_validate_rules.py` — 8 tests via `subprocess.run`
  covering missing / malformed / ok / unknown-name / non-directory
  / JSON and human output. Uses a tolerant JSON extractor (stdout
  has a `face_recognition_models` import-time banner that can't be
  suppressed without patching the library; the test isolates the
  JSON payload).
- `tests/test_main_window_smoke.py` — parametrize updated to cover
  the three tray methods and three watch methods; MRO assertion
  extended to `TrayMixin` and `WatchMixin`.

### Status
Ruff: 0 violations. Pyflakes: 0 undefined names. All 351 tests
passing.

## [v9.3.9] — FilterMixin extracted (3 more methods out of main_window.py)

### Architecture
Continuing the mixin sweep started in v9.3.7. New module:

- `unifile/filter_mixin.py` — `FilterMixin` with three tightly-coupled
  methods moved together because they share state
  (`txt_search` / `cmb_face_filter` / `sld_conf` → `tbl`):
  - `_populate_face_filter` — builds the face filter dropdown from
    scanned metadata, auto-hides when empty or out of PC Files mode.
  - `_apply_filter` — search + face filter row-visibility pass.
  - `_on_conf_changed` — confidence slider handler; auto-selects/
    deselects rows based on the threshold, sort-safe via
    `_item_idx_from_row`.

- `UniFile(ScanMixin, ApplyMixin, ThemeMixin, UndoMixin, FilterMixin, QMainWindow)`
  — mixin order preserved.
- `main_window.py` shrank by another 70+ lines.

### Tests
`tests/test_main_window_smoke.py`:
- MRO assertion extended to include `FilterMixin`.
- Method-resolution parametrization covers the three filter slots.
- Total slow-suite tests now **14**.

**Total: 337 tests passing** (up from 334).

### Status
Ruff: still 0 violations across `unifile/` and `tests/`.
Pyflakes undefined-name set: still empty.

Three mixins extracted so far (UndoMixin, FilterMixin, and the pre-existing
trio of ScanMixin/ApplyMixin/ThemeMixin). Next candidates from the
continuation prompt: TrayMixin, WatchMixin.

## [v9.3.8] — Per-folder rule overrides

### Feature
A single user can have opinions that differ per-subtree — work clients
with their own filing conventions, a scratch folder where only local
inline rules apply, etc. The existing `.unifile.conf` already handles
per-folder category *mappings*; v9.3.8 adds the missing piece: per-folder
overrides for the **rule engine**.

New optional file: `.unifile_rules.json` in the scan root:

```json
{
    "include": ["rule-name", "..."],   // optional allow-list; if present,
                                       // only globals with matching names survive
    "exclude": ["rule-name", "..."],   // drop globals by name (wins over include)
    "inline":  [                       // extra rules merged in — same schema as
        { "name": "local-pdf",         // the global rules.json
          "priority": 1, "enabled": true,
          "conditions": [{"field": "extension", "op": "eq", "value": ".pdf"}],
          "action_category": "Local-Docs", "confidence": 95 }
    ]
}
```

Malformed JSON or non-dict top-level → silently falls back to the
global rule set. No error. No surprises. Unknown top-level keys are
ignored so the schema can grow.

### API
- `unifile/files.py::load_directory_rules(directory) -> dict | None` —
  file loader with input sanitation. Drops non-string names in
  `include`/`exclude`, drops dicts without `name` in `inline`.
- `unifile/engine.py::apply_rule_delta(base, delta) -> list` — pure
  function that produces a merged rule list. Semantics documented in
  the docstring and pinned by tests. Never mutates the input.

### Worker integration
`ScanFilesWorker.run` calls `load_directory_rules()` once at scan
start, caches the delta on `self._rule_delta`, and logs a summary
(`"Found .unifile_rules.json — include=…, exclude=…, inline=…"`).
The per-item RuleEngine evaluation now goes through
`apply_rule_delta(RuleEngine.load_rules(), self._rule_delta)` so each
file gets the effective rule set.

### Tests — 15 new (319 → 334 total)
`tests/test_per_folder_rules.py`:
- `load_directory_rules` — missing, malformed JSON, non-dict top-level,
  full schema, invalid-entry strip, empty object.
- `apply_rule_delta` — no-delta, empty-delta, include-as-allow-list,
  exclude, exclude-wins-over-include, inline-appended,
  inline-replaces-global-by-name, non-mutation guarantee.
- Loader-to-merger integration round trip.

### Deferred
The continuation prompt called for a "Per-folder rules" tab in the
Rules editor dialog. That's a dedicated UI pass — the backend is
in place and fully tested; a future session can wire the editor to
read/write `.unifile_rules.json` for the currently-selected source.

### Impact
| Metric | Before | After |
|--------|--------|-------|
| Tests | 319 | **334** |
| Ruff violations | 0 | 0 |
| Pyflakes undefined-name | 0 | 0 |
| New modules | — | two new functions in existing modules |

## [v9.3.7] — pytest-qt smoke suite + first mixin extraction; one real bug caught

### Architecture — UndoMixin extracted
`main_window.py` was 4121 lines. The continuation plan called for
extracting self-contained methods into dedicated mixins, starting with
`_on_undo` (~40 lines, few shared attrs — just `self.btn_undo` and
`self._log`). New module:

- `unifile/undo_mixin.py` — `UndoMixin` class with `_on_undo`. Moves the
  orphaned `shutil` / `_save_undo_stack` / `UndoBatchDialog` imports with
  it and leaves a one-line comment pointer in `main_window.py`.
- `UniFile(ScanMixin, ApplyMixin, ThemeMixin, UndoMixin, QMainWindow)` —
  mixin order preserved so `QMainWindow` stays at the end of the MRO.
- `main_window.py` shrank by 43 lines.

### Tests — smoke suite via pytest-qt
New `tests/test_main_window_smoke.py` (11 tests, all `@pytest.mark.slow`):

- Instantiates the full `UniFile` window with `QT_QPA_PLATFORM=offscreen`
  — catches any regression where `__init__` can't complete end-to-end.
- Asserts each extracted mixin (`ScanMixin`, `ApplyMixin`, `ThemeMixin`,
  `UndoMixin`) stays in the MRO. Protects future refactors from silently
  dropping a base.
- Parametrizes the seven most-called methods (`_on_scan`, `_scan_aep`,
  `_scan_cat`, `_scan_files`, `_on_undo`, `_show_empty_state`,
  `_hide_empty_state`) and confirms each resolves on the composed class.
- Round-trips the empty-state overlay with the v9.3.5 recovery-action
  kwargs, including the click handler.
- Exercises the undo no-op path with `_load_undo_stack` monkeypatched to
  return `[]`.
- Skips cleanly if `pytest-qt` isn't installed (it's now in the `dev`
  extra).

### Bug fix — caught by the new smoke test on first run
`unifile/dialogs/cleanup.py:624` referenced `self.lbl_progress` inside
`CleanupPanel._build_ui` but never created the widget. Every UniFile
startup therefore tried to instantiate `CleanupPanel` → raised
`AttributeError: 'CleanupPanel' object has no attribute 'lbl_progress'`.
The dialog was reachable only via the Cleanup menu entry, so it didn't
surface in headless test runs or in the minimal pytest-qt fixture
before v9.3.7. Added the missing `self.lbl_progress = QLabel("")`
definition above its first use.

### Dev deps
- `pyproject.toml` — added `pytest-qt>=4` to the `dev` optional
  dependencies so `pip install .[dev]` now wires the smoke tests.

### Impact
| Metric | Before | After |
|--------|--------|-------|
| `main_window.py` lines | 4121 | 4078 |
| Extracted mixins | 3 | 4 |
| Tests | 308 | 319 |
| Smoke-test suite | — | 11 `@slow` tests |
| Bugs caught by new suite | — | 1 (CleanupPanel AttributeError) |

pyflakes undefined-name set still empty; ruff still 0 violations across
both `unifile/` and `tests/`.

## [v9.3.6] — Ruff-clean across the codebase; CI flips to hard-fail

### Cleanup — 379 → 0 ruff violations
Continuing the sweep from v9.3.4 (942 → 379). All remaining categories
addressed:

- **I001** (97): isort-style import reordering — applied via `ruff --fix`.
- **F401** (257): unused imports. 243 auto-fixed. Manual pass for the
  14 that ruff left alone:
  - `unifile/duplicates.py` — removed dead `_PILImage` / `_cv2` probes;
    availability is tracked via the `HAS_PILLOW` flag imported from
    `bootstrap.py`, so the local try/imports never set a flag and went
    unreferenced for several releases.
  - `unifile/widgets.py` — same treatment.
  - `unifile/files.py`, `unifile/ollama.py` — kept `import magic as _magic`
    behind `# noqa: F401` (these are meaningful availability probes used
    elsewhere in each module).
  - `unifile/metadata.py` — removed dead aliases
    (`_GPS_TAGS`, `_EasyID3`, `_FLAC`, `_MP3`, `_MP4`, `_OggVorbis`) and
    kept `_PILImage` / `_EXIF_TAGS` / `_exifread` / `_mutagen` (used at
    lines 428, 623, 656). `_EXIF_TAGS` was flagged by ruff but is
    genuinely referenced through a late try/except path — pyflakes caught
    that during regression, prompting the restore.
  - `unifile/nexa_backend.py`, `unifile/whisper_backend.py` — legitimate
    availability probes; added targeted `# noqa: F401` with a comment
    explaining the intent.
- **B905** (4): `zip()` without explicit `strict=`. All four sites
  reviewed and annotated:
  - `duplicates.py:126` and `semantic.py:20`: length-equality is asserted
    immediately above → `strict=True`.
  - `photos.py:233`: face_recognition returns parallel `locations` and
    `encodings` arrays → `strict=True`.
  - `workers.py:1034`: a malformed LLM response can return fewer results
    than the batch size → `strict=False` with an explanatory comment.
- **F841** (10): unused-variable. Each reviewed; mostly stale scratch
  names from earlier refactors (`gf`, `waste`, `dst`, `paths`, `uncat`,
  `mt`, `top_ext`, `appeared`, `ext`). Removed.
- **F811** (1): `unifile/categories.py:661` redefined
  `_CUSTOM_CATS_FILE` that was already imported from `unifile.config`.
  Removed the redefinition.
- **E402** (6): module-level import after code. Four sites kept behind
  `# noqa: E402` because ordering is meaningful (sentinel/logger set up
  first, then dependent imports).
- **E731** (3): my own `action_cb = lambda:` assignments from v9.3.5.
  Converted each to a named inner `def` for readability.
- **E741** (1): `main_window.py:2554` used `l = QHBoxLayout(...)`
  (ambiguous name). Renamed to `lay`.

### CI
- `.github/workflows/tests.yml` — dropped `continue-on-error: true` from
  the ruff step. Lint is now a hard gate: any new violation fails CI.

### Impact
| Metric | Before v9.3.4 | After v9.3.6 |
|--------|---------------|--------------|
| Ruff (unifile/) | 942 | **0** |
| Ruff (tests/) | 24 | **0** |
| CI lint gate | soft | **hard** |
| Tests passing | 302 | 308 |
| Pyflakes undefined-name | 0 | 0 |

### Tests
- All **308 tests passing** (unchanged count). No behavior change — every
  removal was of a genuinely unused name, every `strict=` decision was
  justified from context, every `noqa` annotates a deliberate pattern.
- The full-repo check ran successfully against a planted canary (unused
  variable added and then reverted) to confirm the hard-fail gate trips.

## [v9.3.5] — Accessible empty states: primary recovery action button

### UX
The three "nothing here" overlays in `scan_mixin.py` (AEP scan, Category
scan, PC Files scan) used to tell the user *what* went wrong but gave no
way to act on it — the user had to hunt through the sidebar for the right
control. Each path now offers a context-appropriate primary-action button
on the empty-state overlay itself:

| Scan mode | Empty-state condition | Recovery action |
|-----------|----------------------|-----------------|
| AEP Scan  | 0 eligible folders found | `Reset scan depth (N → 0)` — only shown when depth > 0 |
| Category Scan | 0 folders categorized | `Lower confidence filter (N% → 0%)` if filter > 0; else `Enable AI mode for next scan` |
| PC Files Scan | 0 files/folders found | `Reset filter (<type> → All Files)` — only shown when a non-default filter is active |

The button is only rendered when a meaningful recovery is available
(e.g. there's no point showing "Reset scan depth" when depth is already 0).
Clicking it mutates the relevant UI control; the user re-runs the scan.

### API
`UniFile._show_empty_state` grew two optional keyword-only arguments,
`action_label: str | None = None` and `action_callback: Callable | None = None`.
Passing both surfaces the primary-action button; omitting either keeps
the button hidden (backward-compatible with the existing
`tests/test_v91_features.py` etc. callers). Click dispatch goes through
the new `_on_empty_action_clicked` slot, which swallows exceptions from
user-supplied callbacks and routes them to `_log` so a broken recovery
handler can never crash the UI.

### Tests
- **+6 tests** in `tests/test_empty_state_action.py`:
  - `_show_empty_state` signature includes the two new kwargs (both optional).
  - Legacy `title`/`detail`/`kicker` kwargs still exist.
  - Click with no handler set is a no-op.
  - Click with a handler invokes it exactly once.
  - Click where the handler raises is swallowed and logged.
  - Source-level guard: `scan_mixin.py` keeps at least three
    `action_callback=` call sites (one per recovery path).
- **Total: 308 tests passing** (up from 302). pyflakes undefined-name
  set still empty.

## [v9.3.4] — Ruff cleanup pass: 942 → 379 violations, modernized annotations

### Correctness — safe auto-fixes (85 sites across 31 files)
- **`F541` (22 sites)** — `f"..."` strings that had no `{}` placeholders. Pure
  correctness: the `f` prefix was a no-op. Removed.
- **`UP015` (46 sites)** — `open(path, 'r')` is redundant; `'r'` is the
  default mode. Dropped the explicit mode argument.
- **`UP006` (9 sites)** — `List[X]` / `Dict[X,Y]` / `Tuple[…]` → built-in
  `list[X]` / `dict[X,Y]` / `tuple[…]` (PEP 585, available since Python 3.9
  and 3.10 is our min).
- **`UP045` (7 sites)** — `Optional[X]` → `X | None` (PEP 604, Python 3.10+).
- **`UP035`** — removed unused `typing.List/Optional` imports in cleanup.py
  (dead code, not used anywhere in the module).
- **`UP031`** — one remaining `%`-format sheet in `dialogs/duplicates.py`
  rewritten as an f-string.
- **`UP036`** — `bootstrap.py`'s Python-version gate bumped `< (3, 8)` →
  `< (3, 10)` to match `requires-python`. The check is kept behind a
  `noqa: UP036` because pip's `requires-python` only enforces on install;
  git-clone users hitting the wrong interpreter still benefit from the
  friendly error.

### Ruff config — align with "dense output" preference
Added to `[tool.ruff.lint].ignore` (matches the `CLAUDE.md` project rule):
  - `E701` — multiple-statements-on-one-line-colon  (e.g. `if x: return`)
  - `E702` — multiple-statements-on-one-line-semicolon  (e.g. `a = 1; b = 2`)
  - `E401` — multiple-imports-on-one-line  (e.g. `import os, sys, json`)
  - `B007` — unused-loop-control-variable  (noisy false-positives for
    intentional enumerate patterns)

These were the dominant stylistic noise (408 + 36 + 25 sites). They fight
the hand-crafted compact style in `bootstrap.py`, `scan_mixin.py`, and
friends. Ignoring them as policy is cleaner than per-line `noqa`.

### Impact
| Before | After |
|--------|-------|
| 942 violations | 379 violations (**-60%**) |
| 8 `invalid-syntax` diagnostics (v9.3.3 fixed) | 0 |
| UP category | clean |

**Remaining debt** is mostly `F401` unused imports (257) and `I001` import
ordering (97) — both are per-file fixes that deserve a dedicated pass.

### Tests
- All **302 tests passing** (unchanged). Pyflakes undefined-name set
  still empty. No behavior change — all fixes are semantic no-ops.

## [v9.3.3] — Python 3.10/3.11 f-string compat: three latent `SyntaxError`s

### Correctness
`pyproject.toml` declares `requires-python = ">=3.10"`, but three f-strings
in the codebase used PEP-701 relaxations that Python didn't ship until 3.12:
  - backslash inside an f-string expression (`\\`)
  - reuse of the outer quote character inside an expression (`\"`)

On 3.10 or 3.11 each of these raises `SyntaxError` at import time, so a
user on a compliant Python would find UniFile completely unable to start.
Ruff flagged all three as `invalid-syntax` against its configured
`target-version = "py310"`. The dev interpreter is 3.12, which is why none
of the prior test runs surfaced them.

**Fixed (v9.3.3)**:
- `unifile/classifier.py:479` — the "Context: …" debug log used
  `{clues['asset_detail'].split('\"')[1]}` inside a double-quoted f-string.
  Extracted the split to a local `_fn_hint` and flipped the outer quotes
  to single, so the expression is plain Python.
- `unifile/classifier.py:1001` — identical pattern, fixed the same way.
- `unifile/workers.py:2511` — the Ollama image-reclassification prompt
  built a regex literal `r'[{}\[\]<>]` *inside* an f-string expression.
  Hoisted the `re.sub` call to a local `_clean_name` and rebuilt the
  prompt with single-quoted outer f-strings (no quote reuse needed).

### Tests
- **+1 test** in `tests/test_py310_fstring_compat.py`. Runs
  `ruff check --output-format=json unifile/` and asserts zero
  `invalid-syntax` diagnostics. Skips cleanly if `ruff` isn't on `PATH`
  (optional dev dep). Verified against a canary file that carries the
  original violation — the test correctly fails on it.
- **Total: 302 tests passing** (up from 301). pyflakes undefined-name
  set still empty.

## [v9.3.2] — Per-file scan progress: `current_item` signal wired end-to-end

### UX
- **"Processing: <name>" now actually updates during a scan** — the
  infrastructure has been in place since v9.0 (`ScanMixin._set_current_scan_item`
  with a 100 ms throttle), but none of the workers were emitting anything
  into it. The progress panel's method label therefore stayed frozen on the
  boilerplate phase text ("Categorizing + extracting names…") for the
  entire duration of large scans, which looks like a hang.
- Added a new `current_item = pyqtSignal(str)` to `ScanAepWorker`,
  `ScanCategoryWorker`, and `ScanFilesWorker`, emitted exactly once per
  main-loop iteration alongside the existing `progress(idx, total)` tick.
  `_scan_aep`, `_scan_cat`, and `_scan_files` in `scan_mixin.py` each
  connect the signal through an `hasattr` guard, so LLM-backed workers
  that don't define the signal yet stay untouched.

### Tests
- **+7 tests** in `tests/test_current_item_signal.py` covering:
  - Signal is declared on each of the three workers (class-level hasattr).
  - Each worker emits the current folder/file name during its main loop
    (executed synchronously via `worker.run()` with a tmp-path fixture).
  - A worker cancelled before `run()` emits nothing.
  - An autouse monkeypatch disables the `is_protected()` path check for
    these tests, because pytest's `tmp_path` lives under
    `%USERPROFILE%\AppData\Local\Temp` on Windows, which the default
    protected-paths list treats as system-critical and would otherwise
    cause `_collect_scan_folders()` to filter out every subfolder.
- **Total: 301 tests passing** (up from 294). pyflakes undefined-name set
  still empty.

## [v9.3.1] — Test consolidation: smoke scripts → parameterized pytest

### Tests
- **Smoke scripts converted to pytest** — `tests/smoke_v86.py` through
  `tests/smoke_v89.py` were manual exit-code scripts: each wrote to stdout,
  tallied pass/fail counters, and returned a non-zero exit on failure. They
  never ran as part of `pytest`, so v8.6–v8.9 archive-inference coverage
  (marketplace rules, design-tool rules, Motion Array / Envato Elements /
  Shutterstock / UI8 rules, LUT extension fix, AI-art / 3D-marketplace /
  game-asset / music-production rules, plus extension maps) was effectively
  dead to CI. All 165 cases migrated to `tests/test_archive_inference.py`
  as `pytest.mark.parametrize` blocks with historical ID labels preserved
  so CHANGELOG refs stay greppable.
- **`tests/check_cats.py` formalized** — the debug utility that sanity-
  checked `EXTENSION_CATEGORY_MAP`, `FILENAME_ASSET_MAP`, and
  `archive_inference._RAW_RULES` against `get_all_category_names()` is now
  `tests/test_category_consistency.py`, three real assertions that fail CI
  if a rule ever points at a category that no longer exists.
- **Deleted**: `smoke_v86.py`, `smoke_v87.py`, `smoke_v88.py`,
  `smoke_v89.py`, `check_cats.py`, `audit_out.txt` (one-off debug dump).
- **Total: 294 tests passing** (up from 129).

### Build
- `pyproject.toml` — dropped the `python_files` smoke-script comment and
  the `tests/smoke_v*.py` / `tests/audit_out.txt` entries from
  `[tool.ruff].extend-exclude`, since those paths no longer exist.

## [v9.3.0] — Deferred-item pass: Settings Hub, Audio-Dup UX, helper extraction

### New features
- **Unified Settings Hub** — `Settings > All Settings…` opens one tabbed
  dialog covering every configurable surface in UniFile (AI, Photo & Media,
  Rules & Learning, System & Safety). Replaces the need to hunt through
  nested `Tools > AI & Intelligence` submenus. Each tab's buttons delegate
  to the existing individual settings dialogs, so no settings store is
  duplicated or forked.
- **Audio duplicates discoverability** — `DuplicateFinderDialog` and
  `DuplicatePanel` now:
  - Detect Chromaprint (`fpcalc`) at open time and grey-out the audio
    checkbox when it's not installed, with an explicit tooltip pointing
    to https://acoustid.org/chromaprint.
  - Expose a "Show: All / Exact / Visual / Audio" filter above the results
    tree so users can focus on a specific match type. Audio duplicates were
    always in the results — they're now easy to find.

### Architecture
- **`unifile/ui_helpers.py`** — new module holding pure, side-effect-free
  UI helpers. First migrations: `confidence_bg()` and `confidence_text_color()`
  (previously static methods on the `UniFile` class) and a new
  `truncate_middle()` utility for long-path labels. The legacy
  `UniFile._confidence_bg` / `UniFile._confidence_text_color` still exist
  as thin shims for backward compatibility. The rule for future migrations:
  a function belongs in `ui_helpers.py` iff it has no `self` and no Qt
  widget side effects.

### Tests
- **+11 regression tests** in `tests/test_v93_features.py` covering:
  - `ui_helpers.confidence_*` colour gradients, out-of-range clamping,
    alpha preservation
  - `truncate_middle` — short-string passthrough, ends preservation,
    pathological max_length
  - Backward-compat shims on `UniFile` still work
  - `SettingsHubDialog` is exported from the package
  - Settings Hub's `_call` routing gracefully handles missing parent slots
    (no raise, visible feedback via title change)
  - `_find_fpcalc()` always returns a string, never `None` (UI relies on `bool()`)
  - Static source-level lock that `ApplyAepWorker` rollback now logs
    failures instead of silently swallowing them
- **Total: 129 tests passing** (up from 118).

### Deferred (see CONTINUATION_PROMPT.md)
- Stale `screenshot.png` re-capture requires a running GUI on a 125%-DPI
  display — cannot be done in a headless session.
- Deeper `main_window.py` mixin extraction (UndoMixin, FilterMixin, etc.)
  awaits integration tests; see continuation prompt for the safe path.

## [v9.2.0] — Second hardening pass: latent NameError sweep, Semantic Search UI, CLI inventory

### Correctness — 97 latent undefined-name bugs fixed
Static analysis (`pyflakes`) surfaced 97 module-level references to names that
were never imported or defined. Each is a real `NameError` waiting to trigger
the first time the corresponding code path runs.

- **`unifile/workers.py`** (56 refs) — missing `subprocess`, `sys`,
  `MetadataExtractor`, `ArchivePeeker`, `_JUNK_SUFFIXES`, `_PHASH_IMAGE_EXTS`,
  `ModelRouter`, `_ollama_generate`, `_ollama_pull_model`, `_llm_cache_get`,
  `_llm_cache_set`, `HAS_PILLOW`, `_cv2`, `_face_recognition`,
  `check_corrections`, `_CategoryIndex`, `_is_id_only_folder`,
  `_extract_name_hints`, `ollama_test_connection`,
  `_EVIDENCE_CONFIDENCE_THRESHOLD`, `_escalate_classification`.
- **`unifile/metadata.py`** (9 refs) — missing `shutil`, `subprocess`,
  `Counter`, and the `_META_IMAGE_EXTS` / `_META_AUDIO_EXTS` /
  `_META_VIDEO_EXTS` / `_META_PDF_EXTS` / `_META_DOCX_EXTS` /
  `_META_XLSX_EXTS` / `_META_PPTX_EXTS` extension sets. The
  `MetadataExtractor.extract()` dispatcher would `NameError` on *any* file.
- **`unifile/classifier.py`** — missing `TOPIC_CATEGORIES`,
  `HAS_PSD_TOOLS`, `extract_psd_metadata`, `_envato_api_classify`.
- **`unifile/categories.py`** — `load_custom_categories` /
  `save_custom_categories` used `json` without importing it.
- **`unifile/photos.py`** — `_detect_faces_full` used `io.BytesIO` and
  `base64.b64encode` without importing them.
- **`unifile/plugins.py`** — removed a dead-code duplicate of
  `append_csv_log` that referenced undefined `_CSV_LOG_FILE` and `csv`.
- **`unifile/widgets.py`** — missing `QSystemTrayIcon` import.
- **`unifile/dialogs/virtual_library_panel.py`** — missing `QFrame`.
- **`unifile/dialogs/media_lookup.py`** + **`tag_library.py`** — `_build_ui`
  used `_t` but the `get_active_theme()` call was in a sibling function only.
- **`unifile/main_window.py`** — missing `MetadataExtractor`, `QThreadPool`,
  `_load_envato_api_key`, `_save_envato_api_key`.

After this pass, `python -m pyflakes unifile/ | grep "undefined name"` returns
zero results.

### New features
- **Semantic Search UI** — `SemanticSearchDialog` is a fully wired natural-
  language search panel accessible from **Tools > AI & Intelligence > Semantic
  Search…**. Previously the `SemanticIndex` class was API-only. The dialog:
  - Shows index status + installed file count up-front
  - Runs queries in a `QThread` so the UI stays responsive
  - Lets users tune similarity threshold and max-results per-query
  - Double-click a result to reveal the file in the OS file manager
    (Explorer on Windows, Finder on macOS, xdg-open on Linux)
- **`list-profiles` CLI subcommand** — print saved scan profiles (plain or
  `--json`). Useful for cron + CI scripts that need to know what profiles
  exist before invoking `--profile`.
- **`list-models` CLI subcommand** — print installed Ollama models, with
  `--url` override. Returns cleanly (exit 0, empty list) when Ollama is
  unreachable, rather than crashing.

### Reliability / hardening
- **Defensive JSON loader** — new `config.load_json_safe(path, default, *,
  expected_type=...)` helper handles missing files, corrupt JSON, encoding
  errors, *and* wrong-type payloads (file contains list when dict expected).
  Complementary `config.save_json_safe()` writes atomically via
  tmp-then-`os.replace` so a crash mid-write can't leave a half-written
  settings file. `load_ollama_settings()` now uses these helpers —
  corrupt `ollama_settings.json` no longer crashes the app.
- **Resource leak fixes** — four leaky `urllib.request.urlopen()` calls in
  `ai_providers.py` (ollama_chat, ollama_vision, openai_chat, openai_vision),
  one in `ollama.py` (`_ollama_pull_model_streaming`), and one in
  `semantic.py` (`_get_embedding`) now use context managers. The perceptual-
  hash function in `duplicates.py` now closes its `PIL.Image` handle inside a
  `with` block — critical on Windows where lingering file handles block
  subsequent move/rename operations.
- **`ApplyAepWorker` rollback** — rollback `shutil.move` failure now logs
  instead of silently swallowing; users learn when their "undo" also failed.

### Tests
- **+19 regression tests** in `tests/test_v92_features.py`:
  - `load_json_safe` / `save_json_safe` behaviour (missing, corrupt,
    type-mismatch, atomic write, non-serializable rejection).
  - `list-profiles` / `list-models` CLI (empty, JSON, unreachable).
  - 6 NameError regression locks that would have caught this pass's bugs:
    `categories.load_custom_categories`, `categories.save_custom_categories`,
    `metadata._META_*` extension sets, `photos.io`/`photos.base64`,
    `classifier.TOPIC_CATEGORIES`, end-to-end `main_window` import,
    and a spot-check of 20 workers.py imports.
  - Ollama settings round-trip through the corrupt-JSON recovery path.
  - `SemanticSearchDialog` export from `unifile.dialogs`.
- **Total: 118 tests passing** (up from 99).

## [v9.1.0] — Productization pass: packaging, CI release, CLI, observability

### New features
- **Headless `classify` subcommand** — classify a single file or folder without
  loading Qt at all: `python -m unifile classify path/to/file --json`. Useful
  in cron jobs, CI, and shell pipelines.
- **`--output-json` scan plan export** — after `--source` or
  `--profile --auto-apply` scans complete, the scan results can be written to
  a machine-readable JSON plan (version, timestamp, source, mode, per-item
  src/dst/category/confidence/size/selected/status).
- **`--version` flag** — `unifile --version` prints the installed version
  and exits cleanly.
- **Undo preview panel** — `UndoBatchDialog` now splits into a batch list +
  preview tree. Selecting a batch shows up to 10 sample from→to operations
  (first 5, last 5) so users can see what will be restored before they
  confirm. Dialog resized from 560×420 to 780×520.
- **Per-file progress label** — scan progress now shows the current file/
  folder name on `lbl_prog_method`, throttled to 100 ms (connect from worker
  `log` or `progress` signal via `_set_current_scan_item`).
- **Ollama batch chunking** — `ollama_classify_batch()` now splits
  >25-folder batches into independent chunks. A single chunk timeout or
  JSON parse error no longer wipes the whole request; failed chunks fall
  through per-folder so results stream in with partial-success semantics.
  Per-chunk timeout capped at 10 minutes.

### Correctness
- **`classifier.py` missing imports** — `detect_envato_item_code` and
  `extract_prproj_metadata` were referenced in `_extract_metadata_from_scan`
  but never imported. Any folder scan that reached the metadata phase would
  raise `NameError`. Caught by the new folder-classify test.
- **Connection registry / atexit cleanup** — all four long-lived SQLite
  databases (`classification_cache.db`, `scan_cache.db`,
  `semantic_embeddings.db`, virtual library `library.sqlite`) now register
  themselves with a central `weakref.WeakSet` and are closed on interpreter
  exit. Unclean shutdowns no longer leave WAL files in inconsistent state.
- **Silent-failure audit** — four `except Exception: pass` blocks in the
  LLM file-scan hot path (archive peek, rule engine, plugin classifiers,
  adaptive learning) now log the exception with the filename so users can
  see which signal failed on which file.
- **`VirtualLibrary.close()`** — now wraps `self._conn.close()` in try/except
  so a double-close can't propagate.

### Developer experience
- **`pyproject.toml`** (PEP 621) — `pip install -e .`, `pip install -e ".[dev]"`,
  `[project.scripts]` entrypoint (`unifile`), ruff + pytest + coverage config
  all live here.
- **`CONTRIBUTING.md`** — dev-loop docs covering setup, testing, linting,
  commit style, versioning, release process.
- **`SECURITY.md`** — private vulnerability reporting via GitHub Security
  Advisories; in-scope / out-of-scope clarification.
- **`ATTRIBUTION.md`** — explicit credit to the 5 upstream projects
  UniFile adapts from, with per-project license notes and a warning about
  TagStudio's GPL-3 license + the PyQt6 redistribution obligation.
- **`Makefile`** — `make test`, `make cov`, `make lint`, `make format`,
  `make build`, `make run`, `make clean`.
- **GitHub templates** — `ISSUE_TEMPLATE/bug_report.md`,
  `ISSUE_TEMPLATE/feature_request.md`, `ISSUE_TEMPLATE/config.yml`
  (disables blank issues, routes security to advisories),
  `PULL_REQUEST_TEMPLATE.md`.
- **Release workflow** — `.github/workflows/release.yml` builds a Windows
  PyInstaller exe on `v*` tag push, extracts the matching changelog entry
  as release notes, and attaches the zip to the GitHub Release.
- **CI expansion** — `tests.yml` adds macOS coverage (3.12 only to keep
  runtimes down), Python 3.10 support, `pytest-cov` XML upload, and a
  separate `lint` job running `ruff check` (report-only until the
  codebase is ruff-clean).
- **+23 new tests** (`test_critical.py` covers cache undo-log round-trip,
  folder fingerprint stability, hash_file, duplicate detection, virtual
  library lifecycle, profile save/load, classifier categorize_folder,
  classify_pc_item, broken-file scanner. `test_v91_features.py` covers
  connection registry, Ollama batch chunking, chunk-failure isolation,
  scan-plan JSON writer, classify subcommand). Total: 99 tests, all passing.

## [v9.0.1] — Deep hardening & correctness pass

### Latent-import NameError bugs (would crash under rarely-hit code paths)
- **`unifile/files.py`** — added missing `time`, `mimetypes` (`_mimetypes`), `HAS_RAPIDFUZZ`, and `_rfuzz` imports; previously the scan-cache write path (`time.time()`), MIME fallback detection (`_mimetypes.guess_type`), and fuzzy keyword signal (`_rfuzz.token_sort_ratio`) would `NameError` the first time they were exercised
- **`unifile/workers.py`** — added missing `HAS_CV2`, `HAS_FACE_RECOGNITION` (from `bootstrap`), `_PHOTO_SCENES` (from `photos`), and `_extract_file_content` (from `metadata`) imports; vision-eligible, face-detection, and content-extraction code paths in `ScanFilesLLMWorker` would previously raise `NameError`
- **`unifile/engine.py`** — imported `Counter` at module level; `EventGrouper.suggest_event_name()` was unusable
- **`unifile/ollama.py`** — imported `_ASSET_FOLDER_NAMES` from `unifile.naming`; `ollama_classify_folder()` raised `NameError` when filtering asset subfolders
- **`unifile/categories.py`** — `_score_aep()` referenced `_normalize` and `_ASSET_FOLDER_NAMES` directly; replaced with late-resolution helpers to break the circular import
- **`unifile/dialogs/__init__.py`** — exported the previously-missing `CsvRulesDialog` so `main_window.py` loads cleanly
- **`unifile/__main__.py`** — `--profile` CLI arg called `window._apply_profile()` (doesn't exist); now routes to `_apply_profile_config()`; `--auto-apply` polled `window._scan_worker` (wrong attribute) and only ever called `_apply_files`; now polls `window.worker` + `_scanning` flag, honors the active op mode, and adds a 30-minute deadline so a stuck scan can't pin the event loop forever; `import time` added

### Correctness & data-safety
- **`safe_merge_move()` backup collisions** — if `<dst>.bak` already existed from a prior aborted merge, `os.rename(dst, dst + '.bak')` raised on Windows and left the destination file gone. New `_unique_backup_path()` helper picks `.bak`, `.bak.1`, `.bak.2`… up to `.bak.<pid>`
- **`safe_merge_move()` source==dest** — added an early guard so merging a directory into itself returns `(0, 0)` instead of potentially wiping data as the walker recurses into the growing destination
- **`safe_merge_move()` duplicate-source cleanup** — `os.remove(src_file)` now wrapped in try/except; a read-only source no longer aborts the whole merge
- **`ApplyAepWorker`** — replaced bare `os.rename()` (which fails across drives / volumes on Windows with `[WinError 17]`) with `shutil.move()`; same-path case (case-only rename) detected and short-circuited to "Done"; rollback path also uses `shutil.move()`; destination parent directory now created with `os.makedirs(..., exist_ok=True)` before move
- **`config.is_protected()`** — rewrote:
  - returns `False` for empty / invalid paths instead of crashing on `normpath('')`
  - basename-only protection entries (e.g. `.git`, `node_modules`, `desktop.ini`) now also match when they appear as any parent segment of `path`, so `foo/.git/config` is correctly recognised as protected
  - wraps `normpath` calls in try/except to handle exotic path inputs
- **`PatternLearner.clear()`** — now holds `self._lock` during reset+save, matching `record_correction()`
- **`get_learner()` singleton** — added double-checked locking so concurrent scan threads can't each construct a `PatternLearner`
- **`SemanticIndex._ensure_db()`** — SQLite connection opens with `check_same_thread=False` so Qt worker threads don't get `ProgrammingError`; `close()` now clears `self._conn` so it can be safely re-opened
- **`unifile/photos.py`** — `face_recognition` calls `quit()` (raises `SystemExit`) at import when `face_recognition_models` is missing; the except now catches `SystemExit` alongside `ImportError`, matching the pattern already used in `bootstrap.py`

### UX / reliability
- **Drag-and-drop crash** — `dropEvent()` referenced `self.content_stack` (doesn't exist; the attribute is `self._content_stack`) and `self.tag_lib_panel` (actually `self._tag_panel`). Any file drop at all would `AttributeError`. Fixed + wrapped in try/except for a user-facing error message
- **`Ollama URL normalization`** — user-configured URLs with a trailing slash (`http://localhost:11434/`) are now normalised on load; prevents `//api/chat` double-slash requests that some proxies reject
- **`IgnoreFilter.is_ignored()`** — the `is_dir` parameter was documented but never used; gitignore-style directory-only patterns (`build/`) now actually match directories
- **`cleanup.scan_empty_folders()`** — O(n²) scan (`any(r.path == sub_path for r in results)` per directory entry) replaced with an O(1) `set` lookup; large directory trees now scan significantly faster. Also `(OSError)` added to the exception handler so disk errors don't silently abort the scan, and `is_symlink()` branches now correctly treat symlinks as non-empty

### Developer experience & tests
- New `tests/test_hardening.py` with 13 regression tests locking in the fixes above (backup collision avoidance, same-path merge guard, Ollama URL normalization, is_protected basename-in-parent, module-level imports, EventGrouper Counter, etc.)

## [v9.0.0] — Engineering hardening pass

### Bug fixes
- Fixed **data loss in `safe_merge_move()`** — destination file was permanently destroyed before the source move succeeded; now backs up destination to `.bak`, restores on failure, and deletes `.bak` on success
- Fixed **silent permanent deletion** — when `use_trash=True` but `send2trash` is missing, files were silently deleted permanently; now returns an error so the UI can surface it
- Fixed **SQLAlchemy thread-safety in `OcrWorker`** — OCR worker now opens its own `Session(engine)` instead of sharing the main-thread session
- Fixed **SQLAlchemy thread-safety in `_StatsWorker`** — statistics worker creates its own session rather than borrowing `lib._session`
- Fixed **N+1 query in Tag Library tree** — `_refresh_tags()` called `get_entries_by_tag()` once per tag; replaced with a single `get_tag_entry_counts()` GROUP BY query
- Fixed **cycle/infinite-loop in `get_tag_hierarchy()`** — recursive tree builder now carries a `visited` set to handle circular parent-child relationships safely
- Fixed **Python 3.10 `fromisoformat()` crash** — timezone-aware ISO timestamps (trailing `Z` or `±HH:MM`) now stripped before parsing via `_parse_naive_dt()` helper
- Fixed **invalid regex crash in rule engine** — `matches` condition now wraps `re.search` in `try/except re.error` via `_safe_regex_match()` helper
- Fixed **AcoustID hardcoded placeholder key** — `_MBWorker` now loads the key from `acoustid_key.txt`; dep-label warns when no key is configured; "Set API Key…" dialog added
- Fixed **OCR temp file at source location** — `_ocr_pdf()` now uses `tempfile.mkstemp()` so temp PNGs never land beside the original file
- Fixed **`update_tag()` sentinel ambiguity** — nullable fields (`namespace`, `description`, `icon`) now use an `_UNSET` sentinel so `None` means "clear" and absence means "leave unchanged"
- Fixed **SA2 SQLAlchemy comparison warnings** — `== True` / `== False` comparisons on Boolean columns replaced with `.is_(True)` / `.is_(False)`
- Fixed **`add_entries_bulk()` N+1** — pre-fetches all existing paths per batch with a single `IN` query before the insert loop
- Fixed **`scan_broken_links()` OOM** — rewrote to use paginated 1000-entry batches instead of loading all entries into memory at once
- Fixed **JSON fence stripping in `natural_language_to_rule()`** — regex now handles both `` ```json `` and `` ``` `` fences

### New library API
- Added `TagLibrary.get_tag_entry_counts()` — returns `{tag_id: count}` in one GROUP BY query
- Added `TagLibrary.set_entry_field_with_session(session, ...)` — static method for thread-safe field writes from worker threads

### Second hardening pass (audit pass 2)
- Fixed **hardcoded `id=1` in `_get_or_create_folder()`** — removed explicit PK value so SQLite autoincrement prevents potential primary-key collision when a second folder record is inserted
- Fixed **`ScheduleManager.create_task()` always returning `False`** — broken `'__file__' in dir()` check (which always evaluates `False` inside a method) replaced; scheduled tasks now use `python -m unifile` instead of a fragile script-path lookup
- Fixed **`-tag:` NOT search loading all entries into Python** — replaced `{e.id for e in get_entries_by_tag(...)}` with a SQL subquery so large libraries are not fully materialised
- Fixed **`add_entries_to_group()` N+1** — replaced per-entry SELECT + INSERT loop with a single bulk-existence check and `add_all()`
- Fixed **`remove_entries_from_group()` N+1** — replaced per-entry SELECT + DELETE loop with a single `DELETE … WHERE entry_id IN (…)` statement
- Fixed **`get_group_entries()` two-query pattern** — replaced load-member-ids + second query with a single JOIN query
- Fixed **`delete_entry_group()` N+1** — replaced per-member delete loop with a single `DELETE … WHERE group_id=X` statement
- Fixed **`import_tag_pack()` unhandled exception** — JSON fallback path now wrapped in `try/except`; returns `{'errors': 1}` instead of crashing
- Fixed **`Tag.parent_tags` self-referential `back_populates`** — removed incorrect `back_populates="parent_tags"` on the association relationship that would cause SAWarnings
- Fixed **`_card_frame` / `_section_frame` duplication** — merged the two identical 9-line functions into one; `_section_frame` is now an alias
- Fixed **`_TimelineChart` label comment** — comment said "MM-YY" but the slice produces "YY-MM" (last 5 chars of "YYYY-MM"); updated comment
- Expanded `requirements.txt` — added all optional dependencies (SQLAlchemy, send2trash, rapidfuzz, mutagen, acoustid, musicbrainzngs, pytesseract, easyocr, pdfminer.six, pymupdf, pdf2image, tomli, tomli-w, PyYAML) with section comments

### New tests (audit pass 2)
- Added 31 new tests in `tests/test_engine.py` covering `_parse_naive_dt` (8 cases), `_safe_regex_match` (6 cases), `RuleEngine.evaluate` (12 cases), and `RuleEngine.find_conflicts` (5 cases)

### Features (v9.0.0)
- Added: **Rule Engine — time & size operators** — new `older_than_days`, `newer_than_days`, `size_gt_mb`, `size_lt_mb`, `in_list`, and `not_in_list` conditions for richer automation rules
- Added: **Rule import/export (YAML)** — rules can now be exported to YAML (with JSON fallback) and imported from `.yaml`/`.yml`/`.json` files via the Settings menu
- Added: **Natural language rule creation** — describe a rule in plain English; Ollama converts it to a structured rule automatically
- Added: **Rule conflict detection** — `find_conflicts()` surfaces rules that share the same source/condition so overlaps are visible before running
- Added: **Content-based classifier (Level 8)** — extracts text from PDF, DOCX, TXT, CSV, PPTX, XLSX files and classifies by keyword matching for higher accuracy
- Added: **Archive inspector (Level 9)** — peeks inside ZIP/TAR archives and classifies by the extension mix of contained files
- Added: **Tag namespaces** — tags can be grouped under a namespace (e.g. `genre:Rock`, `project:Alpha`), filterable in the Tag Library panel
- Added: **Tag descriptions and icons** — every tag can have a freeform description and an icon glyph for quick visual identification
- Added: **Hidden tags** — tags can be marked hidden; toggle visibility with the new Hidden checkbox in the tag tree header
- Added: **Entry ratings** — 1–5 star rating per entry; searchable with `rating:3` syntax; displayed in the detail bar
- Added: **Inbox / Archive workflow** — every entry has an inbox/archive state (`inbox:true`); dedicated Inbox/Archive sidebar panel with tab split
- Added: **Source URL tracking** — record where a file was downloaded from; searchable with `source_url:` syntax
- Added: **Media properties** — width, height, duration, word count stored per entry; shown in the preview detail bar
- Added: **Entry groups** — logical groupings of entries independent of folder structure; create from selection, browse in context menu
- Added: **Tag merge** — merge any tag into another with one action; all entries on the source are re-tagged and the source is deleted
- Added: **Multiple library roots** — Tag Library now supports multiple root scan paths per library
- Added: **Tag Pack (TOML)** — export/import tag definitions as `.toml` files with namespace and description preserved; JSON fallback
- Added: **Broken links panel** — dedicated sidebar panel scans the library for missing files, shows results in a table with Relink and Remove actions
- Added: **Statistics dashboard** — sidebar panel with file/tag/entry totals, extension distribution, top tags, storage by category, and 12-month activity timeline
- Added: **MusicBrainz Tagger** — acoustID fingerprint + MusicBrainz lookup dialog for audio files; writes ID3/FLAC tags and suggests renames
- Added: **OCR Indexer** — indexes image and PDF text via pytesseract/easyocr; stores result in the entry's AI summary field for full-text search
- Added: **Portable mode** — pass `--portable` to `run.py` (or set `UNIFILE_PORTABLE=1`) to store all data beside the script instead of `%APPDATA%`

## [v8.9.4]

- Refined: **Niche helper dialogs now feel more review-first** — Before/After comparison, AI Event Grouping, and the rename-source file picker now provide clearer summaries, better empty/selection guidance, and calmer card-based layout treatment so these smaller decision points feel intentional instead of legacy
- Refined: **Comparison and rename trust signals** — source-vs-destination previews now explain what each side means more clearly, while rename-source selection now reports candidate counts, filtered results, and the currently selected cleaned filename more explicitly
- Fixed: **Thin selection feedback in helper flows** — event grouping now makes selection state and apply intent clearer, and the rename picker no longer leaves filtering or candidate availability ambiguous

## [v8.9.3]

- Refined: **Editor and rules workflows feel calmer and more deliberate** — Custom Categories, Destination Preview, Classification Rules, Plugin Manager, Watch History, and CSV Sort Rules now present stronger summaries, clearer helper copy, and better action emphasis so power-user setup screens feel consistent with the premium shell
- Refined: **Automation dialogs now communicate order and intent better** — rule-driven workflows now explain that first-match-wins logic more clearly, surface better empty states, and reduce silent or ambiguous editor states while creating, cloning, testing, and saving rules
- Fixed: **Thin utility-screen affordances** — destructive actions in supporting dialogs now read more clearly, list-heavy views provide stronger context before selection, and CSV rule editing now keeps its summary in sync with the current table state

## [v8.9.2]

- Refined: **Secondary workflow panels now match the premium shell** — Tag Library, Media Lookup, and Virtual Library now use stronger section hierarchy, calmer search and empty-state copy, more intentional cards, clearer review-first action emphasis, and better feedback after add/apply/export/search flows
- Refined: **Theme consistency inside inline content panels** — the remaining heavy inline panels now re-apply their custom header, preview, detail, and status styling when the active theme changes, preventing the shell from feeling cohesive while those panels drift
- Fixed: **Thin or silent panel states** — Media Lookup now disables metadata actions until detail is ready, Tag Library surfaces clearer no-selection and action feedback, and Virtual Library now reports invalid paths, zero-match searches, empty overlays, and completed scans more clearly

## [v8.9.1]

- Refined: **Premium shell polish across the main workspace** — upgraded the organizer shell with a stronger action hierarchy, richer workflow copy, trust badges, more spacious cards, clearer empty states, calmer progress feedback, and better status-bar defaults so the product feels more intentional at first glance and during long sessions
- Refined: **Shared dark-theme design system** — improved the global QSS for button emphasis, danger/success semantics, focus/disabled states, input surfaces, tabs, tables, scrollbars, and splitter affordances to make the entire application feel more cohesive and premium
- Refined: **Settings, cleanup, duplicate, and support dialogs** — introduced a consistent dialog-header pattern, normalized action emphasis, simplified status messaging, and improved review-first affordances across AI settings, advanced settings, cleanup tools, duplicate tools, protected paths, theme picker, and utility dialogs
- Fixed: **Stale version and trust surfaces** — the app window title, sidebar branding, launch/bootstrap metadata, and docs now all reflect the current release instead of showing outdated `v8.0.0` references

## [v8.9.0]

- Fixed: **`.cube`/`.3dl`/`.lut` extension mapping** — previously routed to `Premiere Pro - LUTs & Color`; corrected to `Color Grading & LUTs` since LUT files are app-agnostic (work in Resolve, FCPX, Premiere, Photoshop, etc.); confidence adjusted to 90/88
- Added: **AI art platform rules** in `archive_inference.py` — `civitai`/`civit.ai` with model/lora/checkpoint/merge sub-types (88), generic `\bcivitai\b` catch-all (82), and `hugging.face` model/lora/safetensor/checkpoint (85); placed before the existing `safetensor`/`stable.diffusion` generic rule
- Added: **3D marketplace archive rules** — TurboSquid (sub-typed character/vehicle/weapon/prop 88, generic 82), CGTrader (sub-typed model/character/scene 88, generic 80), Sketchfab (sub-typed model/scene/pack 85, generic 78), KitBash3D (kit/pack/model/bundle 88), Renderosity/Daz3D/Poser (sub-typed figure/character/prop 85, generic 78), Poly Haven/HDRI Haven/AmbientCG (→ `3D - Materials & Textures` 88), Substance Painter/Designer/SBSAR (material/texture/pack 88), HDRI pack keyword (85), Fab/Unreal marketplace (→ `Unreal Engine - Assets` 85)
- Added: **Game asset marketplace rules** — itch.io (asset/pack/tileset/sprite/game 85), OpenGameArt (85), Kenney (asset/pack/sprite 85), RPG Maker (asset/pack/tileset 83)
- Added: **Music production marketplace rules** — Loopmasters (sample/loop/pack/kit 85, generic 78), Native Instruments/NI Komplete (library/preset/pack/expansion 87), Spitfire Audio (library/pack/expansion/instrument 87), ADSR/ADSR Sounds (sample/preset/pack 82), Samples From Mars (85)
- Added: **10 new extension mappings** — `.cr3` → `Photography - RAW Files` (Canon CR3 RAW), `.exr` → `3D - Materials & Textures` (OpenEXR for HDRI/VFX renders), `.sbs`/`.sbsar` → `3D - Materials & Textures` (Substance Designer/Painter), `.ztl` → `3D` (ZBrush tool), `.usd`/`.usda`/`.usdc`/`.usdz` → `3D - Models & Objects` (Apple AR/USD scene files), `.sf2`/`.sfz` → `Music Production - Presets` (SoundFont), `.nki`/`.nkx`/`.nkc` → `Music Production - Presets` (Kontakt instruments), `.ptx` → `Music Production - DAW Projects` (Pro Tools session), `.cpr` → `Music Production - DAW Projects` (Cubase project), `.xcf` → `Clipart & Illustrations` (GIMP)
- Added: **Composition heuristics** — USD/USDZ detection (≥ 2 files at ≥ 30% → `3D - Models & Objects` 76), Substance material detection (≥ 2 `.sbs`/`.sbsar` at ≥ 30% → `3D - Materials & Textures` 78), OpenEXR detection (≥ 3 `.exr` at ≥ 30% → `3D - Materials & Textures` 72); `.cr3` added to `raw_exts` counter
- Added: **14 new FILENAME_ASSET_MAP entries** — TurboSquid, CGTrader, Sketchfab, KitBash3D, Poly Haven/HDRI Haven/AmbientCG, Substance material packs, Daz3D/Poser/Renderosity, Civitai, itch.io, OpenGameArt/Kenney, Loopmasters, Native Instruments/Kontakt/Spitfire Audio



- Fixed: **Duplicate `is_generic_aep` and `_score_aep` definitions** in `categories.py` — first copy (lines 26–143) was silently shadowed by an identical second copy (lines 150–267); removed the second (dead) copy; `CATEGORY ENGINE` header now appears once
- Removed: **Dead code in `classifier.py`** — `analyze_folder_composition()` (superseded by `_scan_folder_once()`), `_classify_by_composition()` (superseded by `_classify_composition_from_scan()`), and `find_near_duplicates()` (referenced undefined `IMAGE_EXTS` and `_compute_phash`; never called) — all three functions deleted
- Added: **`_PREMIERE_SUBCATEGORIES` frozenset + PR collapse logic** in `aggregate_archive_names()` — mirrors AE/PS collapse; when ≥ 2 Premiere Pro subcategories (`Premiere Pro - Transitions`, `- Titles & Text`, `- LUTs & Color`, `- Presets & Effects`, `- Sound Design`) each receive votes and PR votes dominate by 1.5× (≥ 3 total), result collapses to `Premiere Pro - Templates`
- Added: **Motion Array sub-typed rules** — 10 sub-type rules before the generic MotionArray catch-all: titles, transitions, logo reveals, slideshows, lower thirds, broadcast, social/Instagram, promo/explainer, mogrt/premiere (→ `Premiere Pro - Templates`), LUT/color grade (→ `Color Grading & LUTs`)
- Added: **Envato Elements marketplace block** — 10 sub-typed rules for `envato.elements` / `elements.envato`: mogrt/premiere, transitions, logo reveals, titles, slideshows, fonts, mockups, stock photos, stock music, generic catch-all
- Added: **Shutterstock / Getty Images / iStock archive rules** — footage sub-type (→ `Stock Footage - General`), music sub-type (→ `Stock Music & Audio`), generic (→ `Stock Photos - General`) for each platform
- Added: **UI8 / Gumroad / ArtStation / Iconscout archive rules** — UI8 (kit/template/component → `UI & UX Design`), Gumroad (font/brush/svg/action sub-typed + catch-all), Iconscout/Craftwork (icons), ArtStation (brush/texture/model sub-typed + catch-all)
- Added: **Standalone Premiere Pro sub-typed archive rules** — `premiere.*transition`, `handy.seamless`, `premiere.*title`, `premiere.*lower third`, `premiere.*lut`, `premiere.*preset`, `premiere.*sound` — all routed to appropriate `Premiere Pro - *` subcategories for the collapse to work correctly
- Added: **10 new extension mappings** — `.glb`/`.gltf` → `3D - Models & Objects`, `.otc`/`.ttc` → `Fonts & Typography` (font collections), `.lottie` → `Animated Icons`, `.bmpr` → `UI & UX Design` (Balsamiq), `.rp`/`.rplib` → `UI & UX Design` (Axure RP), `.vsdx`/`.vsd` → `Forms & Documents` (Visio), `.sla`/`.slaz` → `Flyers & Print` (Scribus), `.pxm`/`.pxd` → `Clipart & Illustrations` (Pixelmator), `.splinecode` → `UI & UX Design`
- Added: **Composition heuristics improvements** — mixed RAW+JPEG detection (≥ 2 RAW + ≥ 1 JPEG at ≥ 50% total → `Photography - RAW Files` 73), glTF/GLB detection (≥ 2 GLB/GLTF at ≥ 40% → `3D - Models & Objects` 78), Lottie animation detection (≥ 2 `.lottie` files → `Animated Icons` 72); `.rpp` added to DAW extensions; `.otc`/`.ttc` added to font extension counts
- Added: **17 new FILENAME_ASSET_MAP entries** — Motion Array, Envato Elements, Shutterstock, Getty/iStock, UI8, Iconscout/Craftwork/Flaticon, Lottie/Bodymovin, Balsamiq, Axure RP, Visio, Scribus, Spline, glTF/GLB, ArtStation assets, Gumroad, Premiere Pro mogrt/transitions, Handy Seamless Transitions



- Fixed: **`SystemExit` swallowed by `except ImportError`** in `bootstrap.py` — `face_recognition` module calls `quit()` when `face_recognition_models` is absent, raising `SystemExit`; changed to `except (ImportError, SystemExit)` so the missing-models case is handled gracefully without killing the process
- Fixed: **`"Calendars & Planners"`** in `FILENAME_ASSET_MAP` → corrected to `"Calendar"` to match actual category name; also added `monthly planner`, `wall calendar`, `desk calendar`, `editorial calendar` keywords
- Added: **3 new categories** — `Canva - Templates`, `Final Cut Pro - Templates`, `3D Printing - STL Files` (with rich keyword lists)
- Added: **11 new extension mappings** — `.rpp` → `Music Production - DAW Projects`, `.band`/`.bandproject` → `Music Production - DAW Projects`, `.fcpbundle`/`.fcpxml` → `Final Cut Pro - Templates`, `.aco` → `Photoshop - Gradients & Swatches`, `.brushset` → `Procreate - Brushes & Stamps`, `.hip`/`.hiplc`/`.hipnc` → `3D` (Houdini), `.ma`/`.mb` → `3D` (Maya), `.max` → `3D` (3ds Max), `.stl`/`.3mf` → `3D Printing - STL Files` (overrides `3D - Models & Objects` when STL-dominant); `.fcpbundle`/`.fcpxml` added to `DESIGN_TEMPLATE_EXTS`
- Added: **`_PS_SUBCATEGORIES` frozenset + PS collapse logic** in `aggregate_archive_names()` — mirrors the AE collapse pattern; when ≥ 2 PS subcategories (`Photoshop - Actions`, `Brushes`, `Styles & Effects`, `Gradients & Swatches`, `Patterns`, `Mockups`, `Overlays`) each receive votes and PS votes dominate by 1.5× (≥ 3 total PS votes), result collapses to `Photoshop - Templates & Composites`
- Added: **14 numeric Envato ID subcategory rules** — previously unhandled sub-types now classified instead of falling through to the generic AE catch-all: particle/FX, character animation, lyric video, HUD/UI, countdown/timer, mockup, font/typeface, flyer, business card, resume/CV, logo, presentation/PowerPoint
- Added: **4 GraphicRiver PS sub-rules** — `graphicriver.*(action|actions)` → `Photoshop - Actions`, `graphicriver.*(brush|brushes)` → `Photoshop - Brushes`, `graphicriver.*(style|styles|effect|effects)` → `Photoshop - Styles & Effects`, `graphicriver.*(pattern|patterns)` → `Photoshop - Patterns`
- Added: **New marketplace archive rules** — Final Cut Pro/FCPX (typed: title/transition/effect/template/plugin/generator + catch-all), Canva (typed: template/design/graphic/social/flyer/resume/presentation + catch-all), Filmora/Wondershare (typed + catch-all), Pond5 (typed: SFX/footage/motion/music), Storyblocks/Videoblocks (typed: footage/music/motion), Epidemic Sound, Looperman (typed + catch-all), Splice (typed), ZapSplat/SoundSnap (typed + catch-all), AEJuice (typed + catch-all), MotionBro, Mixkit (typed: footage/music/motion + catch-all)
- Added: **FILENAME_ASSET_MAP entries** — Canva, Final Cut Pro, 3D printing, Filmora, Pond5/Storyblocks/Videoblocks/Epidemic Sound (stock audio), Looperman/Splice/ZapSplat/SoundSnap (SFX/loops), AEJuice/MotionBro/Mixkit/Envato Elements
- Added: **Composition heuristics improvements** in `_classify_composition_from_scan()` — LUT packs (≥ 2 `.cube`/`.3dl`/`.lut` files at ≥ 30% ratio → `Color Grading & LUTs`), 3D printing packs (≥ 2 `.stl`/`.3mf` at ≥ 40% → `3D Printing - STL Files`), icon packs (≥ 8 PNG/SVG in `/icons/` subfolder → `Icons & Symbols`), texture packs (images in `/textures/` or `/materials/` subfolder → `3D - Materials & Textures`), large icon packs (≥ 20 PNG/SVG at ≥ 70% → `Icons & Symbols`)
- Rule ordering: FCPX, Canva, and Filmora rules placed in tool-specific section (before generic AE standalone subcategory rules) to prevent false matches on generic title/transition/social-media rules



- Added: **5 new tool-specific categories** — `Sketch - UI Resources`, `Adobe XD - Templates`, `Affinity - Designer Files`, `Affinity - Photo Edits`, `Affinity - Publisher Layouts`
- Added: **7 new extension mappings** — `.sketch` → `Sketch - UI Resources`, `.xd` → `Adobe XD - Templates`, `.afdesign` → `Affinity - Designer Files`, `.afphoto` → `Affinity - Photo Edits`, `.afpub` → `Affinity - Publisher Layouts`, `.kra`/`.clip` → `Clipart & Illustrations`; `.xd`, `.kra`, `.clip` added to `DESIGN_TEMPLATE_EXTS`
- Added: **26 new marketplace archive rules** — Creative Market (sub-typed: font/brush/mockup/logo/vector/action + catch-all), Creative Fabrica (SVG/craft + font), Design Bundles (SVG/craft), Font Bundles, Freepik (mockup/photo/vector), Vecteezy/VectorStock → `Vectors & SVG`, ArtGrid → `Stock Footage - General`, ArtList → `Stock Music & Audio`, Placeit/SmartMockups → `Photoshop - Mockups`, Pixabay/Unsplash/Pexels → `Stock Photos - General`
- Added: **Sketch/XD/Affinity archive rules** — archive names containing these tool names now route to the correct new categories
- Added: **`_AE_SUBCATEGORIES` collapse in `aggregate_archive_names()`** — when ≥ 2 After Effects subcategories each receive votes and AE votes dominate by 1.5× over non-AE votes (≥ 3 total AE votes), result collapses to `After Effects - Templates` instead of a single arbitrarily-winning subcategory
- Fixed: **Dead infographic rule** — standalone `(r'infographic', 'After Effects - Infographics & Data')` at position ~156 made the generic `(r'infographic', 'Infographic')` rule unreachable. Replaced with two motion-specific rules (`animated?.*infographic` / `infographic.*(animated?|motion|video)`); generic `Infographic` rule now fires for non-motion packs
- Added: **FILENAME_ASSET_MAP entries** — Sketch/XD/Affinity keyword entries; Cricut/SVG cut file / sublimation / vinyl cut → `Cutting Machine - SVG & DXF`; Shopify/WooCommerce themes → `Website Design`; sample/loop packs → `Stock Music & Audio`; MIDI pack → `Music Production - DAW Projects`



- Fixed: **Critical category name mismatches** — ~19 category names in `archive_inference.py` and `FILENAME_ASSET_MAP` didn't match actual category names in `categories.py`, causing files to land in wrong/nonexistent folders. All corrected:
  - `'YouTube & Streaming'` → `'YouTube & Video Platform'`; twitch/stream rules → `'Twitch & Streaming'`
  - `'Web Templates & HTML'` → `'Website Design'`
  - `'Email Templates'` → `'Email & Newsletter'`
  - `'Banners & Ads'` → `'Banners'`
  - `'Icons & Icon Packs'` → `'Icons & Symbols'`
  - `'Patterns & Seamless'` → `'Patterns - Seamless'`
  - `'Photo Effects & Overlays'` → `'Overlays & Effects'`
  - `'Infographics & Data Viz'` → `'Infographic'`
  - `'Illustrations & Clipart'` → `'Clipart & Illustrations'`
  - `'Coupons & Vouchers'` → `'Gift Voucher & Coupon'`
  - `'Apparel & Merchandise'` → `'Clothing & Apparel'`
  - `'Catalogs & Lookbooks'` → `'InDesign - Magazine & Editorial'`
  - `'Book Covers & eBook'` → `'Book & Literature'`
  - `'Logos & Branding'` → `'Logo & Identity'`
  - `'Mockups'` (generic) → `'Photoshop - Mockups'`; device/apparel/packaging/branding/print/signage → specific `Mockups - *` subcategories
  - `'Social Media Templates'` → `'Social Media'`
  - `'Certificates & Awards'` → `'Certificate'`
  - `'Resume & CV Templates'` → `'Resume & CV'`
  - `'Menus & Food Templates'` → `'Menu Design'`
  - `'Wedding & Events'` → `'Wedding'`
  - Letterhead/stationery rules → `'Letterhead & Stationery'`
  - Rollup banner rules → `'Rollup Banners & Signage'`
- Fixed: **Archive inference skipped on topic-named folders** — `_apply_context_from_scan()` exited early at `has_design_files=False` before archive inference could fire. Archive check now runs before that gate so folders like "Christmas" full of Videohive ZIPs classify correctly
- Fixed: **Archive threshold too strict** — changed from `>= 25%` to `>= 5 archives OR >= 15%` so preview images don't dilute the archive ratio
- Added: **AudioJungle marketplace rules** — `audiojungle` → `'Stock Music & Audio'`; sfx variants → `'Sound Effects & SFX'`
- Added: **ThemeForest/CodeCanyon rules** — `themeforest`/WordPress themes → `'Website Design'`
- Added: **Numeric Envato ID prefix rules** (7-9 digit IDs like `25461234-wedding-slideshow.zip`) — 12 specific AE subcategory rules + generic catch-all `'After Effects - Templates'`
- Added: WordPress/WooCommerce/Elementor template rules → `'Website Design'`



- Added: **Archive name inference engine** (`unifile/archive_inference.py`) — 140+ regex rules classify ZIP/RAR/7z folders by filename patterns (marketplace-aware: Videohive, GraphicRiver, MotionElements; AE subcategories, print, social, seasonal, audio, game dev, 3D, and more)
- Added: `aggregate_archive_names(stems)` voting system — samples all archive names in a folder, computes consensus category with confidence scaling
- Changed: `_scan_folder_once()` now collects archive stems; adds them to `all_filenames_clean` for keyword matching bonus
- Changed: `_classify_composition_from_scan()` — when a folder is ≥25% archives and has ≥2 archives, triggers archive name inference as highest-priority rule
- Added: 4 new categories — `CorelDRAW - Vectors & Assets`, `Apple Motion - Templates`, `Cutting Machine - SVG & DXF`, `After Effects - Cinematic & Trailers`
- Added: 9 new extension mappings — `.cdr` (CorelDRAW), `.motn` (Apple Motion), `.dxf` (cutting machine), `.dds/.tga` (3D textures), `.hdr` (3D HDR), `.fon` (bitmap fonts), `.ait` (Illustrator templates), `.pub` (Publisher)

## [v8.3.0]

- Fixed: **Critical NameError bug** — `DESIGN_TEMPLATE_EXTS`, `VIDEO_TEMPLATE_EXTS`, `FILENAME_ASSET_MAP`, `_GENERIC_DESIGN_CATEGORIES` were defined in `ollama.py` but referenced in `classifier.py` without import; any `tiered_classify()` call on a real folder path would crash
- Changed: Moved and expanded all four constants into `classifier.py` (their actual point of use); removed stale definitions from `ollama.py`
- Added: 10 new categories — `Figma - Templates & UI Kits`, `DaVinci Resolve - Templates`, `CapCut - Templates`, `Game Assets & Sprites`, `Unreal Engine - Assets`, `AI Art & Generative`, `Procreate - Brushes & Stamps`, `Music Production - Presets`, `Music Production - DAW Projects`, `Photography - RAW Files`
- Added: 20 new extension mappings in `EXTENSION_CATEGORY_MAP` covering `.fig`, `.drp/.drfx`, `.als/.flp/.logicx`, `.procreate`, `.nks/.nksn`, `.vstpreset/.fxp/.fxb`, `.unitypackage`, `.uproject/.uasset`, `.ase/.aseprite`, RAW camera formats (`.nef/.cr2/.arw` etc.), `.safetensors/.ckpt`, `.lora`, `.capcut`
- Added: Composition rules for RAW files (≥3 at ≥40% → Photography - RAW Files), DAW projects (any `.als/.flp/.logicx` → Music Production - DAW Projects), MIDI-only folders, and Lightroom preset heavy folders
- Added: Expanded `FILENAME_ASSET_MAP` from 35 → 45+ entries covering Procreate, game assets, music production, RAW photos, calendars, patterns, and more
- Added: `DESIGN_TEMPLATE_EXTS` now includes `.fig`, `.afdesign`, `.afphoto`, `.afpub`, `.sketch`
- Added: `VIDEO_TEMPLATE_EXTS` now includes `.drp`, `.drfx`
- Changed: Keyword expansions across 10 existing categories: After Effects, 3D/3D Materials, Motion Graphics, Backgrounds & Textures, Fonts & Typography, Sound Effects, Lightroom, DaVinci Resolve, CapCut



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
