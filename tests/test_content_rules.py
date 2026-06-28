"""Tests for content-aware rule conditions (content, has_ocr_text fields)."""
import os
import textwrap

import pytest

from unifile.engine import RuleEngine, extract_file_text


class _FakeItem:
    def __init__(self, name="test.txt", full_src="", size=100, metadata=None, vision_ocr=""):
        self.name = name
        self.full_src = full_src
        self.size = size
        self.metadata = metadata or {}
        self.vision_ocr = vision_ocr


def _make_rule(field, op, value, name="test-rule"):
    return {
        "name": name, "enabled": True, "priority": 1,
        "conditions": [{"field": field, "op": op, "value": value}],
        "logic": "all", "action_category": "Matched", "confidence": 95,
    }


# ── extract_file_text ────────────────────────────────────────────────────────

def test_extract_text_file(tmp_path):
    f = tmp_path / "readme.txt"
    f.write_text("Hello World\nLine two", encoding="utf-8")
    assert "Hello World" in extract_file_text(str(f))


def test_extract_text_markdown(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# Title\nSome notes", encoding="utf-8")
    assert "Title" in extract_file_text(str(f))


def test_extract_text_unsupported_ext(tmp_path):
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0")
    assert extract_file_text(str(f)) == ""


def test_extract_text_missing_file():
    assert extract_file_text("/nonexistent/path.txt") == ""


def test_extract_text_truncates_large(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("A" * 20000, encoding="utf-8")
    result = extract_file_text(str(f))
    assert len(result) <= 8192


# ── content field in rules ───────────────────────────────────────────────────

def test_content_contains_text_file(tmp_path):
    f = tmp_path / "invoice.txt"
    f.write_text("Invoice #42\nTotal: $100.00", encoding="utf-8")
    item = _FakeItem(name="invoice.txt", full_src=str(f))
    rule = _make_rule("content", "contains", "Invoice")
    result = RuleEngine.evaluate(item, [rule])
    assert result is not None
    assert result[0] == "Matched"


def test_content_matches_regex(tmp_path):
    f = tmp_path / "report.csv"
    f.write_text("date,amount\n2024-01-15,500\n2024-02-20,750", encoding="utf-8")
    item = _FakeItem(name="report.csv", full_src=str(f))
    rule = _make_rule("content", "matches", r"\d{4}-\d{2}-\d{2}")
    result = RuleEngine.evaluate(item, [rule])
    assert result is not None


def test_content_no_match(tmp_path):
    f = tmp_path / "readme.txt"
    f.write_text("Hello World", encoding="utf-8")
    item = _FakeItem(name="readme.txt", full_src=str(f))
    rule = _make_rule("content", "contains", "Invoice")
    result = RuleEngine.evaluate(item, [rule])
    assert result is None


def test_content_prefers_ai_summary():
    item = _FakeItem(name="scan.pdf", full_src="/fake/scan.pdf",
                     metadata={"ai_summary": "Medical invoice for patient visit"})
    rule = _make_rule("content", "contains", "Medical invoice")
    result = RuleEngine.evaluate(item, [rule])
    assert result is not None


def test_content_falls_back_to_vision_ocr():
    item = _FakeItem(name="receipt.jpg", full_src="/fake/receipt.jpg",
                     vision_ocr="Total amount due: $42.50")
    rule = _make_rule("content", "contains", "amount due")
    result = RuleEngine.evaluate(item, [rule])
    assert result is not None


def test_content_unsupported_format_no_metadata():
    item = _FakeItem(name="photo.png", full_src="/fake/photo.png")
    rule = _make_rule("content", "contains", "anything")
    result = RuleEngine.evaluate(item, [rule])
    assert result is None


def test_content_invalid_regex_no_crash():
    item = _FakeItem(name="test.txt", full_src="/fake/test.txt",
                     metadata={"ai_summary": "some text here"})
    rule = _make_rule("content", "matches", "[invalid(")
    result = RuleEngine.evaluate(item, [rule])
    assert result is None


# ── has_ocr_text field ───────────────────────────────────────────────────────

def test_has_ocr_text_true_from_ai_summary():
    item = _FakeItem(metadata={"ai_summary": "Extracted invoice text"})
    rule = _make_rule("has_ocr_text", "eq", "1")
    result = RuleEngine.evaluate(item, [rule])
    assert result is not None


def test_has_ocr_text_true_from_vision_ocr():
    item = _FakeItem(vision_ocr="OCR text from vision model")
    rule = _make_rule("has_ocr_text", "eq", "1")
    result = RuleEngine.evaluate(item, [rule])
    assert result is not None


def test_has_ocr_text_false_when_no_text():
    item = _FakeItem()
    rule = _make_rule("has_ocr_text", "eq", "1")
    result = RuleEngine.evaluate(item, [rule])
    assert result is None


def test_has_ocr_text_neq_for_missing():
    item = _FakeItem()
    rule = _make_rule("has_ocr_text", "neq", "1")
    result = RuleEngine.evaluate(item, [rule])
    assert result is not None


# ── editor fields list includes content fields ───────────────────────────────

def test_editor_fields_include_content():
    from unifile.dialogs.editors import RuleEditorDialog
    assert "content" in RuleEditorDialog._FIELDS
    assert "has_ocr_text" in RuleEditorDialog._FIELDS
