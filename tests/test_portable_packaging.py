"""Regression tests for portable-mode detection and ZIP packaging."""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_portable_zip_contains_marker_payload_and_docs(tmp_path):
    module = _load_module(ROOT / "tools" / "build_portable_zip.py", "build_portable_zip_test")
    source = tmp_path / "payload"
    (source / "_internal" / "nested").mkdir(parents=True)
    (source / "UniFile.exe").write_bytes(b"frozen executable")
    (source / "_internal" / "nested" / "runtime.dll").write_bytes(b"runtime")
    (source / "UniFile.exe.sha256").write_text("ignored", encoding="ascii")
    output = tmp_path / "portable.zip"

    result = module.build_portable_zip(source, output, "1.2.3")

    assert result == output.resolve()
    with zipfile.ZipFile(result) as archive:
        names = set(archive.namelist())
    assert "UniFile-portable-v1.2.3/UniFile.exe" in names
    assert "UniFile-portable-v1.2.3/_internal/nested/runtime.dll" in names
    assert "UniFile-portable-v1.2.3/portable.flag" in names
    assert "UniFile-portable-v1.2.3/README.md" in names
    assert "UniFile-portable-v1.2.3/LICENSE" in names
    assert all(not name.endswith("UniFile.exe.sha256") for name in names)


def test_portable_zip_rejects_missing_frozen_executable(tmp_path):
    module = _load_module(ROOT / "tools" / "build_portable_zip.py", "build_portable_zip_missing_test")
    source = tmp_path / "payload"
    source.mkdir()
    try:
        module.build_portable_zip(source, tmp_path / "portable.zip", "1.2.3")
    except FileNotFoundError as exc:
        assert "UniFile.exe" in str(exc)
    else:
        raise AssertionError("portable builder accepted a payload without UniFile.exe")


def test_run_py_auto_detects_adjacent_portable_marker(tmp_path, monkeypatch):
    module = _load_module(ROOT / "run.py", "run_portable_test")
    executable = tmp_path / "UniFile.exe"
    executable.write_bytes(b"placeholder")
    marker = tmp_path / "portable.flag"
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "executable", str(executable))
    monkeypatch.setattr(module.sys, "argv", [str(executable)])
    assert module._portable_mode_requested() is False
    marker.write_text("portable\n", encoding="ascii")
    assert module._portable_mode_requested() is True


def test_frozen_config_data_root_is_next_to_executable(monkeypatch, tmp_path):
    import unifile.config as config

    executable = tmp_path / "UniFile.exe"
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(executable))
    assert Path(config._runtime_script_dir()) == tmp_path
