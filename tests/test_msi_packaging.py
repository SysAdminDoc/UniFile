"""Regression tests for the WiX MSI release definition."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_msi.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_msi_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wix_source_declares_required_windows_integration():
    source = (ROOT / "installer" / "UniFile.wxs").read_text(encoding="utf-8")
    assert 'Scope="perMachine"' in source
    assert 'Name="PATH"' in source
    assert 'Key=".unifile"' in source
    assert 'Key="Directory\\shell\\UniFile"' in source
    assert 'Key="Directory\\Background\\shell\\UniFile"' in source
    assert "UniFileStartMenuShortcut" in source


def test_build_command_binds_frozen_payload_and_version(tmp_path):
    module = _load_module()
    output = tmp_path / "UniFile-v9.3.32.msi"
    command = module.build_command(
        ROOT / "dist" / "UniFile",
        output,
        "9.3.32",
        wix_executable="wix-test",
    )
    assert command[:4] == ["wix-test", "build", "-arch", "x64"]
    assert "ProductVersion=9.3.32" in command
    assert f"BuildOutput={ROOT / 'dist' / 'UniFile'}" in command
    assert command[-1] == str(output)


def test_msi_version_validation_rejects_four_part_and_prerelease_versions():
    module = _load_module()
    for value in ("9.3.32.1", "9.3.32-beta", "v9.3.32"):
        try:
            module.validate_version(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid MSI version {value!r}")
