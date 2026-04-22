# Contributing to UniFile

Thanks for taking the time to contribute. Short version:

1. Fork → clone → branch → commit → PR.
2. Run the test suite locally before opening a PR.
3. Ruff-clean code only (`ruff check unifile/` must pass).
4. One logical change per commit. No AI-attribution trailers.

## Quick start

```bash
git clone https://github.com/SysAdminDoc/UniFile.git
cd UniFile

# Install editable + dev extras
pip install -e ".[dev]"

# Run the full test suite (should complete in under 5 seconds)
pytest

# Lint
ruff check unifile/ tests/

# Launch the app
python run.py
```

## Project layout

```
unifile/
├── __main__.py     Application entry point + CLI argument handling
├── bootstrap.py    Optional-dependency auto-installer
├── config.py       Settings, themes, protected paths, APP_DATA_DIR
├── categories.py   384+ built-in classification categories
├── classifier.py   7-level classification engine
├── engine.py       Rule engine, event grouping, rename templates
├── naming.py       Smart rename + marketplace-noise stripping
├── ollama.py       Ollama LLM integration
├── photos.py       EXIF / face recognition / geocoding
├── files.py        PC file organizer + scan cache
├── cache.py        Classification cache + undo log
├── duplicates.py   Progressive duplicate detection
├── cleanup.py      Empty / junk / broken file scanners
├── workers.py      QThread workers for scan + apply
├── main_window.py  Main Qt window + sidebar + signals
├── scan_mixin.py   Scan-related methods (mixed into UniFile)
├── apply_mixin.py  Apply-related methods (mixed into UniFile)
├── theme_mixin.py  Theme-related methods (mixed into UniFile)
├── tagging/        SQLAlchemy-backed tag library
├── media/          TMDb / OMDb / TVMaze providers
└── dialogs/        All QDialog subclasses

tests/              pytest tests (76+ as of v9.0.1)
```

## Testing

```bash
# Full suite, verbose
pytest -v

# Run only the fast lane (skip anything marked "slow")
pytest -m "not slow"

# Coverage report
pytest --cov=unifile --cov-report=term-missing
```

New features must come with tests. Regression fixes must come with a test
that would have caught the original bug. See `tests/test_hardening.py` for
examples of testing module-level imports, data-safety invariants, and URL
normalization.

## Code style

- **Ruff** is the source of truth: `ruff check unifile/`. Line length 110.
- **No comments that explain WHAT** — good names do that. Comments explain
  WHY only (hidden constraint, workaround for a bug, subtle invariant).
- **Error handling**: prefer narrow `except (SpecificErr, ...)` over bare
  `except Exception: pass`. Silent swallowing in scan/apply paths masks real
  data bugs.
- **Imports at module top** only. Don't put `import foo` inside hot-path
  functions unless `foo` is optional.

## Commit messages

```
short subject: why the change matters (under 70 chars)

Optional body explaining why, linking issues, etc. No AI-attribution
trailers. No Co-Authored-By lines.
```

One logical change per commit. Bug fixes and feature work go in separate
commits even if they live in the same PR.

## Versioning

- **Patch** (9.0.x): bug fixes, documentation, internal hardening.
- **Minor** (9.x.0): new features, new commands, new UI surfaces.
- **Major** (x.0.0): breaking config/plugin API changes.

When bumping, update all of the following in the same commit:
`unifile/__init__.py`, `pyproject.toml`, `README.md` badges,
`CHANGELOG.md`.

## Releases

Tagged `v*` pushes trigger the release workflow
(`.github/workflows/release.yml`), which builds a PyInstaller Windows exe
and uploads it to the GitHub Release. Maintainers only.

## Reporting bugs

Use the bug-report issue template. Include:
- OS + version
- Python version (`python --version`)
- UniFile version (`python run.py --version` or see About dialog)
- Exact steps to reproduce
- What you expected vs. what happened
- Relevant lines from `~/.unifile/crash.log` if the app crashed

## Security

See [SECURITY.md](SECURITY.md) for the vulnerability disclosure process.
