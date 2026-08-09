# UniFile — developer convenience targets.
# `make help` lists everything. Cross-platform via `python -m` where possible.

PY ?= python

.PHONY: help install dev deps-check test cov lint typecheck docs audit format translations build build-smoke portable sdk release-audit benchmark-search clean run

help:
	@echo "UniFile developer targets:"
	@echo "  install     Install package + core deps (editable)"
	@echo "  dev         Install with runtime + dev extras"
	@echo "  deps-check  Validate dependency manifest alignment"
	@echo "  test        Validate dependency manifests and run pytest"
	@echo "  cov         Run the 60% core-module coverage gate"
	@echo "  lint        Run ruff"
	@echo "  typecheck   Run strict mypy for public SDK/core engine contracts"
	@echo "  docs        Build the SDK API and tutorial docs"
	@echo "  translations Extract the English Qt catalog, compile locale catalogs, and validate safety labels"
	@echo "  audit       Run pip-audit against the local environment"
	@echo "  release-audit  Audit current ZIP/MSI/SDK artifacts with SBOM, licenses, vulnerabilities, and hashes"
	@echo "  benchmark-search  Measure bounded Tag Library search and cancellation on a disposable fixture"
	@echo "  format      Auto-fix ruff issues"
	@echo "  build       Clean, build, smoke-test, and checksum the PyInstaller exe"
	@echo "  build-smoke Smoke-test dist/UniFile/UniFile.exe and write SHA-256 sidecar"
	@echo "  portable    Build the self-contained portable ZIP from dist/UniFile"
	@echo "  sdk         Build the PyQt-free unifile-sdk wheel"
	@echo "  run         Launch the GUI"
	@echo "  clean       Remove build artefacts and caches"

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[full,media,ocr,dev]"

deps-check:
	$(PY) tools/check_dependency_manifests.py

test: deps-check
	$(PY) tools/run_tests.py

cov:
	$(PY) -m pytest --cov=unifile.classifier --cov=unifile.engine --cov=unifile.learning --cov=unifile.tagging.library --cov-fail-under=60 --cov-report=term-missing --cov-report=html --cov-report=json:build/core-coverage.json
	$(PY) tools/check_core_coverage.py build/core-coverage.json

lint:
	$(PY) -m ruff check unifile tests

typecheck:
	$(PY) -m mypy --strict

docs:
	$(PY) -m sphinx -W --keep-going docs build/docs

translations:
	$(PY) tools/i18n_catalog.py all

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

portable:
	$(PY) tools/build_portable_zip.py

sdk:
	$(PY) tools/build_sdk.py

release-audit:
	$(PY) tools/release_audit.py

benchmark-search:
	$(PY) tools/benchmark_search.py

run:
	$(PY) run.py

clean:
	@$(PY) -c "import shutil, glob, os; [shutil.rmtree(p, ignore_errors=True) for p in ('build','dist','.pytest_cache','.ruff_cache','htmlcov')]; [shutil.rmtree(p, ignore_errors=True) for p in glob.glob('**/__pycache__', recursive=True)]; [os.remove(p) for p in glob.glob('**/*.pyc', recursive=True) if os.path.isfile(p)]"
