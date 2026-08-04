"""Tests for the isolated, PyQt-free SDK distribution."""
import importlib
import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

_sdk = importlib.import_module("unifile_sdk")
Classifier = _sdk.Classifier
PatternLearner = _sdk.PatternLearner
SemanticIndex = _sdk.SemanticIndex
TagLibrary = _sdk.TagLibrary

SDK_PROJECT = ROOT / "sdk" / "pyproject.toml"


def test_sdk_metadata_has_no_pyqt_dependency():
    with SDK_PROJECT.open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["name"] == "unifile-sdk"
    assert all("PyQt6" not in dependency for dependency in project["dependencies"])


def test_sdk_exports_core_engine_types_without_qt():
    assert Classifier().classify("Invoices")["category"] == "Accounting & Finance"
    assert PatternLearner.__name__ == "PatternLearner"
    assert SemanticIndex.__name__ == "SemanticIndex"
    assert TagLibrary.__name__ == "TagLibrary"


def test_sdk_core_imports_when_qt_is_forbidden(tmp_path):
    script = """
import sys
sys.path.insert(0, "sdk")
class BlockQt:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("PyQt6", "PySide")):
            raise ImportError("Qt is forbidden in SDK")
sys.meta_path.insert(0, BlockQt())
from unifile_sdk import Classifier, PatternLearner, SemanticIndex, TagLibrary
assert Classifier().classify("Invoices")["category"] == "Accounting & Finance"
assert PatternLearner and SemanticIndex and TagLibrary
print("sdk import passed")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "sdk import passed" in result.stdout
