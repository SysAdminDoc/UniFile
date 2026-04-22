# UniFile — developer convenience targets.
# `make help` lists everything. Cross-platform via `python -m` where possible.

PY ?= python

.PHONY: help install dev test cov lint format build clean run

help:
	@echo "UniFile developer targets:"
	@echo "  install     Install package + core deps (editable)"
	@echo "  dev         Install with [dev] extras (pytest, ruff, coverage)"
	@echo "  test        Run pytest"
	@echo "  cov         Run pytest with coverage report"
	@echo "  lint        Run ruff"
	@echo "  format      Auto-fix ruff issues"
	@echo "  build       Build a Windows exe via PyInstaller"
	@echo "  run         Launch the GUI"
	@echo "  clean       Remove build artefacts and caches"

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest

cov:
	$(PY) -m pytest --cov=unifile --cov-report=term-missing --cov-report=html

lint:
	$(PY) -m ruff check unifile tests

format:
	$(PY) -m ruff check --fix unifile tests

build:
	$(PY) -m pip install pyinstaller
	$(PY) -m PyInstaller --clean --noconfirm UniFile.spec

run:
	$(PY) run.py

clean:
	@$(PY) -c "import shutil, glob, os; [shutil.rmtree(p, ignore_errors=True) for p in ('build','dist','.pytest_cache','.ruff_cache','htmlcov')]; [shutil.rmtree(p, ignore_errors=True) for p in glob.glob('**/__pycache__', recursive=True)]; [os.remove(p) for p in glob.glob('**/*.pyc', recursive=True) if os.path.isfile(p)]"
