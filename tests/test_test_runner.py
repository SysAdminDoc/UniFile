"""Tests for the deterministic Windows pytest wrapper."""
from __future__ import annotations

from tools.run_tests import _cleanup_tree, has_explicit_basetemp


def test_runner_detects_explicit_basetemp():
    assert has_explicit_basetemp(["-q", "--basetemp", "build/test-temp"])
    assert has_explicit_basetemp(["--basetemp=build/test-temp"])
    assert not has_explicit_basetemp(["-q"])


def test_runner_cleanup_removes_owned_tree(tmp_path):
    owned = tmp_path / "owned"
    (owned / "nested").mkdir(parents=True)
    (owned / "nested" / "result.txt").write_text("ok", encoding="utf-8")

    assert _cleanup_tree(owned) is None
    assert not owned.exists()
