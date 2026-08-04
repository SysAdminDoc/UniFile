"""Regression tests for the PyInstaller release-smoke gate."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_runtime_hook_exists_and_configures():
    hook = ROOT / "unifile" / "pyinstaller_runtime.py"
    assert hook.is_file()
    module = _load_module(hook, "pyinstaller_runtime_test")
    assert module.configure_runtime() is True


def test_spec_references_checked_in_runtime_hook():
    spec_text = (ROOT / "UniFile.spec").read_text(encoding="utf-8")
    assert "runtime_hooks=['unifile/pyinstaller_runtime.py']" in spec_text
    assert (ROOT / "unifile" / "pyinstaller_runtime.py").is_file()


def test_make_build_runs_clean_pyinstaller_and_smoke():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert ".PHONY:" in makefile and "build-smoke" in makefile
    assert "build: clean" in makefile
    assert "$(PY) -m PyInstaller --clean --noconfirm UniFile.spec" in makefile
    assert "$(PY) tools/smoke_pyinstaller_build.py" in makefile


def test_smoke_script_has_expected_checks_and_checksum(tmp_path):
    script = ROOT / "tools" / "smoke_pyinstaller_build.py"
    module = _load_module(script, "smoke_pyinstaller_build_test")
    payload = tmp_path / "UniFile.exe"
    payload.write_bytes(b"frozen-smoke")
    sidecar = module.write_sha256_sidecar(payload)
    digest = hashlib.sha256(b"frozen-smoke").hexdigest()
    assert sidecar.read_text(encoding="utf-8") == f"{digest}  UniFile.exe\n"
    parser = module.build_parser()
    args = parser.parse_args(["--exe", str(payload), "--skip-gui", "--timeout", "5"])
    assert args.exe == payload
    assert args.skip_gui is True
    assert args.timeout == 5


def test_gui_smoke_exit_env_is_wired():
    main_text = (ROOT / "unifile" / "__main__.py").read_text(encoding="utf-8")
    assert "UNIFILE_GUI_SMOKE_EXIT_MS" in main_text
    assert "QTimer.singleShot" in main_text


def test_smoke_json_parser_tolerates_optional_dependency_preamble():
    module = _load_module(ROOT / "tools" / "smoke_pyinstaller_build.py", "smoke_json_parser_test")
    payload = module._extract_json_object(
        'OpenCV bindings requires "numpy" package.\n'
        '{"kind": "file", "category": "Documents"}\n'
    )
    assert payload == {"kind": "file", "category": "Documents"}
