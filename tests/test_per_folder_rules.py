"""Per-folder rule-set overrides (v9.3.8).

Verifies:
  * `unifile.files.load_directory_rules` parses `.unifile_rules.json`
    correctly and degrades safely on malformed input.
  * `unifile.engine.apply_rule_delta` merges the delta into a base rule
    list with the documented include/exclude/inline semantics.
"""

import json

import pytest

from unifile.engine import apply_rule_delta
from unifile.files import load_directory_rules

# ── load_directory_rules: parser ──────────────────────────────────────────────

def test_load_directory_rules_missing_returns_none(tmp_path):
    assert load_directory_rules(str(tmp_path)) is None


def test_load_directory_rules_malformed_returns_none(tmp_path):
    (tmp_path / ".unifile_rules.json").write_text("not json", encoding="utf-8")
    assert load_directory_rules(str(tmp_path)) is None


def test_load_directory_rules_non_dict_toplevel_returns_none(tmp_path):
    (tmp_path / ".unifile_rules.json").write_text("[1,2,3]", encoding="utf-8")
    assert load_directory_rules(str(tmp_path)) is None


def test_load_directory_rules_parses_full_schema(tmp_path):
    payload = {
        "include": ["rule-a", "rule-b"],
        "exclude": ["rule-c"],
        "inline": [
            {"name": "local-pdf", "priority": 1, "enabled": True,
             "conditions": [{"field": "extension", "op": "eq", "value": ".pdf"}],
             "action_category": "Local-Docs", "confidence": 95},
        ],
    }
    (tmp_path / ".unifile_rules.json").write_text(json.dumps(payload), encoding="utf-8")
    result = load_directory_rules(str(tmp_path))
    assert result is not None
    assert result["include"] == ["rule-a", "rule-b"]
    assert result["exclude"] == ["rule-c"]
    assert len(result["inline"]) == 1
    assert result["inline"][0]["name"] == "local-pdf"


def test_load_directory_rules_strips_invalid_entries(tmp_path):
    """Non-string names in include/exclude and dicts without `name` in
    inline are silently dropped."""
    payload = {
        "include": ["ok", 42, None, "also-ok"],
        "exclude": [{"not": "a string"}, "drop-me"],
        "inline": [
            {"name": "keep"},
            {"no_name": True},  # dropped (no name)
            "not a dict",       # dropped (not a dict)
        ],
    }
    (tmp_path / ".unifile_rules.json").write_text(json.dumps(payload), encoding="utf-8")
    result = load_directory_rules(str(tmp_path))
    assert result["include"] == ["ok", "also-ok"]
    assert result["exclude"] == ["drop-me"]
    assert [r["name"] for r in result["inline"]] == ["keep"]


def test_load_directory_rules_empty_object_returns_none(tmp_path):
    (tmp_path / ".unifile_rules.json").write_text("{}", encoding="utf-8")
    assert load_directory_rules(str(tmp_path)) is None


# ── apply_rule_delta: merge semantics ─────────────────────────────────────────

_BASE = [
    {"name": "pdf-rule", "action_category": "Docs"},
    {"name": "img-rule", "action_category": "Images"},
    {"name": "vid-rule", "action_category": "Videos"},
]


def test_apply_rule_delta_no_delta_returns_copy_of_base():
    result = apply_rule_delta(_BASE, None)
    assert result == _BASE
    # Must be a new list (caller may mutate)
    assert result is not _BASE


def test_apply_rule_delta_empty_delta_returns_copy_of_base():
    assert apply_rule_delta(_BASE, {}) == _BASE


def test_apply_rule_delta_include_acts_as_allow_list():
    delta = {"include": ["pdf-rule"]}
    result = apply_rule_delta(_BASE, delta)
    assert [r["name"] for r in result] == ["pdf-rule"]


def test_apply_rule_delta_exclude_drops_named_rules():
    delta = {"exclude": ["vid-rule"]}
    names = [r["name"] for r in apply_rule_delta(_BASE, delta)]
    assert "vid-rule" not in names
    assert "pdf-rule" in names and "img-rule" in names


def test_apply_rule_delta_exclude_wins_over_include_on_conflict():
    delta = {"include": ["pdf-rule", "img-rule"], "exclude": ["pdf-rule"]}
    names = [r["name"] for r in apply_rule_delta(_BASE, delta)]
    assert names == ["img-rule"]


def test_apply_rule_delta_inline_appended():
    new_rule = {"name": "local-code", "action_category": "Code"}
    delta = {"inline": [new_rule]}
    result = apply_rule_delta(_BASE, delta)
    assert result[-1] is new_rule
    assert len(result) == len(_BASE) + 1


def test_apply_rule_delta_inline_replaces_global_by_name():
    """If an inline rule has the same `name` as a global one, it replaces
    the global — so per-folder overrides can retarget a named rule."""
    override = {"name": "pdf-rule", "action_category": "Local-Docs"}
    delta = {"inline": [override]}
    result = apply_rule_delta(_BASE, delta)
    # Only one rule named "pdf-rule" in the result, and it's the local one.
    pdfs = [r for r in result if r.get("name") == "pdf-rule"]
    assert len(pdfs) == 1
    assert pdfs[0] is override
    assert pdfs[0]["action_category"] == "Local-Docs"


def test_apply_rule_delta_does_not_mutate_base():
    base_copy = [dict(r) for r in _BASE]
    delta = {"exclude": ["pdf-rule"], "inline": [{"name": "new"}]}
    _ = apply_rule_delta(_BASE, delta)
    assert _BASE == base_copy, "apply_rule_delta mutated its input"


# ── Integration: loader output feeds merge ────────────────────────────────────

def test_loader_output_flows_into_merge(tmp_path):
    """End-to-end: write a file, load it, feed the delta into the merger."""
    (tmp_path / ".unifile_rules.json").write_text(json.dumps({
        "exclude": ["img-rule"],
        "inline": [{"name": "local-only", "action_category": "Here"}],
    }), encoding="utf-8")
    delta = load_directory_rules(str(tmp_path))
    result = apply_rule_delta(_BASE, delta)
    names = [r["name"] for r in result]
    assert "img-rule" not in names
    assert "local-only" in names
