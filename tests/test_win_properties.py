"""Tests for Windows Property System metadata bridge."""
import os
import sys

import pytest

from unifile.win_properties import merge_with_metadata, read_shell_properties

# ── merge_with_metadata ──────────────────────────────────────────────────────

def test_merge_adds_new_fields():
    existing = {"width": "1920", "height": "1080"}
    shell = {"title": "My Photo", "rating": "4"}
    merged = merge_with_metadata(existing, shell)
    assert merged["title"] == "My Photo"
    assert merged["rating"] == "4"
    assert merged["width"] == "1920"


def test_merge_prefixes_conflicts():
    existing = {"title": "Original Title", "author": ""}
    shell = {"title": "Shell Title", "author": "Shell Author"}
    merged = merge_with_metadata(existing, shell)
    assert merged["title"] == "Original Title"
    assert merged["_shell_title"] == "Shell Title"
    assert merged["author"] == "Shell Author"


def test_merge_empty_shell_props():
    existing = {"width": "100"}
    assert merge_with_metadata(existing, {}) == existing


def test_merge_empty_existing():
    shell = {"title": "Test", "rating": "3"}
    merged = merge_with_metadata({}, shell)
    assert merged == shell


# ── read_shell_properties ────────────────────────────────────────────────────

def test_read_nonexistent_file():
    result = read_shell_properties("/nonexistent/path/file.txt")
    assert result == {}


@pytest.mark.skipif(sys.platform != 'win32', reason="Windows-only")
def test_read_real_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    result = read_shell_properties(str(f))
    assert isinstance(result, dict)


@pytest.mark.skipif(sys.platform == 'win32', reason="Non-Windows only")
def test_read_returns_empty_on_non_windows():
    assert read_shell_properties("/some/path.txt") == {}


# ── Module API ───────────────────────────────────────────────────────────────

def test_module_importable():
    from unifile import win_properties
    assert hasattr(win_properties, 'read_shell_properties')
    assert hasattr(win_properties, 'merge_with_metadata')
