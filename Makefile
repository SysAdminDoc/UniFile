# UniFile — developer convenience targets.
# `make help` lists everything. Cross-platform via `python -m` where possible.

PY ?= python

.PHONY: help install dev deps-check test cov lint audit format build build-smoke release-audit clean run

help:
	@echo "UniFile developer targets:"
	@echo "  install     Install package + core deps (editable)"
	@echo "  dev         Install with runtime + dev extras"
	@echo "  deps-check  Validate dependency manifest alignment"
	@echo "  test        Validate dependency manifests and run pytest"
	@echo "  cov         Run pytest with coverage report"
	@echo "  lint        Run ruff"
	@echo "  audit       Run pip-audit against the local environment"
	@echo "  format      Auto-fix ruff issues"
	@echo "  build       Clean, build, smoke-test, and checksum the PyInstaller exe"
	@echo "  build-smoke Smoke-test dist/UniFile/UniFile.exe and write SHA-256 sidecar"
	@echo "  run         Launch the GUI"
	@echo "  clean       Remove build artefacts and caches"

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[full,media,ocr,dev]"

deps-check:
	$(PY) tools/check_dependency_manifests.py

test: deps-check
	$(PY) -m pytest

cov:
	$(PY) -m pytest --cov=unifile --cov-report=term-missing --cov-report=html

lint:
	$(PY) -m ruff check unifile tests

audit:
	$(PY) -m pip_audit --local

format:
	$(PY) -m ruff check --fix unifile tests

build: clean
	$(PY) -m pip install pyinstaller
	$(PY) -m PyInstaller --clean --noconfirm UniFile.spec
	$(PY) tools/smoke_pyinstaller_build.py

build-smoke:
	$(PY) tools/smoke_pyinstaller_build.py

release-audit:
	$(PY) tools/release_audit.py

run:
	$(PY) run.py

clean:
	@$(PY) -c "import shutil, glob, os; [shutil.rmtree(p, ignore_errors=True) for p in ('build','dist','.pytest_cache','.ruff_cache','htmlcov')]; [shutil.rmtree(p, ignore_errors=True) for p in glob.glob('**/__pycache__', recursive=True)]; [os.remove(p) for p in glob.glob('**/*.pyc', recursive=True) if os.path.isfile(p)]"
