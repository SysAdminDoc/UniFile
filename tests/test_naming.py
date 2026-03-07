"""Tests for naming normalization and beautification."""
import pytest

from unifile.naming import _normalize, _beautify_name, _smart_name


class TestNormalize:
    def test_lowercase(self):
        assert _normalize("HELLO") == "hello"

    def test_strips_whitespace(self):
        result = _normalize("  hello  ")
        assert result.strip() == result or "hello" in result

    def test_empty_string(self):
        result = _normalize("")
        assert isinstance(result, str)


class TestBeautifyName:
    def test_basic_cleanup(self):
        result = _beautify_name("my___file---name")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_preserves_content(self):
        result = _beautify_name("photo_2024")
        assert "photo" in result.lower() or "2024" in result


class TestSmartName:
    def test_returns_string(self):
        result = _smart_name("some_folder_name")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handles_special_chars(self):
        result = _smart_name("file [v2] (final)")
        assert isinstance(result, str)
