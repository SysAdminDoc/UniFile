"""Natural-language rule compilation, preview, and apply coverage."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

from unifile.natural_rules import (
    NaturalRuleError,
    apply_natural_rule_plan,
    build_natural_rule_plan,
    expand_destination_template,
    normalize_natural_rule,
    parse_natural_rule,
)


def _rule(destination="Archive/Screenshots/YYYY-MM"):
    return {
        "name": "Archive old screenshots",
        "enabled": True,
        "priority": 10,
        "logic": "all",
        "conditions": [
            {"field": "name", "op": "contains", "value": "screenshot"},
            {"field": "modified_date", "op": "older_than_days", "value": "30"},
        ],
        "action_destination": destination,
        "action_rename": "",
        "confidence": 96,
    }


def test_normalize_natural_rule_validates_schema_and_paths():
    normalized = normalize_natural_rule(_rule())
    assert normalized["action_destination"] == "Archive/Screenshots/YYYY-MM"
    assert normalized["conditions"][1]["op"] == "older_than_days"

    with pytest.raises(NaturalRuleError, match="unsafe path"):
        normalize_natural_rule(_rule("../outside"))
    with pytest.raises(NaturalRuleError, match="Unsupported rule field"):
        normalize_natural_rule({**_rule(), "conditions": [{
            "field": "shell_command", "op": "eq", "value": "whoami",
        }]})


def test_expand_destination_template_uses_file_date_without_leaving_root(tmp_path):
    source = tmp_path / "screenshot-old.png"
    source.write_bytes(b"old")
    modified = datetime.now() - timedelta(days=45)
    os.utime(source, (modified.timestamp(), modified.timestamp()))

    expected = modified.strftime("Archive/Screenshots/%Y-%m")
    assert expand_destination_template(
        "Archive/Screenshots/YYYY-MM", str(source), str(tmp_path)
    ) == expected
    with pytest.raises(NaturalRuleError):
        expand_destination_template("/absolute", str(source), str(tmp_path))


def test_build_plan_matches_locally_and_emits_ordered_action_dag(tmp_path):
    old = tmp_path / "screenshot-old.png"
    old.write_bytes(b"old")
    old_stamp = datetime.now() - timedelta(days=45)
    os.utime(old, (old_stamp.timestamp(), old_stamp.timestamp()))
    recent = tmp_path / "screenshot-recent.png"
    recent.write_bytes(b"recent")
    other = tmp_path / "document.pdf"
    other.write_bytes(b"pdf")

    plan = build_natural_rule_plan(
        "archive old screenshots", str(tmp_path), parsed_rule=_rule(), provider_key="demo"
    )
    assert plan["provider"] == "demo"
    assert plan["stats"]["scanned"] == 3
    assert plan["stats"]["matched"] == 1
    assert len(plan["actions"]) == 1
    assert plan["actions"][0]["relative_source"] == "screenshot-old.png"
    assert plan["actions"][0]["relative_destination"].startswith(
        f"Archive/Screenshots/{old_stamp:%Y-%m}/"
    )
    assert [node["id"] for node in plan["nodes"]] == [
        "discover", "match", "route", "review", "apply"
    ]
    assert plan["nodes"][-1]["requires_approval"] is True


def test_parse_natural_rule_forwards_structured_schema_once():
    calls = []

    class FakeChain:
        def classify(self, prompt, *, system, format):
            calls.append((prompt, system, format))
            return json.dumps(_rule()), "fake-provider"

    parsed, provider = parse_natural_rule("archive old screenshots", FakeChain())
    assert provider == "fake-provider"
    assert parsed["name"] == "Archive old screenshots"
    assert calls[0][2]["required"] == ["name", "conditions", "action_destination"]


def test_apply_plan_requires_approval_and_never_overwrites(tmp_path):
    source = tmp_path / "screenshot-old.png"
    source.write_bytes(b"old")
    stamp = datetime.now() - timedelta(days=45)
    os.utime(source, (stamp.timestamp(), stamp.timestamp()))
    plan = build_natural_rule_plan("archive", str(tmp_path), parsed_rule=_rule())

    with pytest.raises(NaturalRuleError, match="approval"):
        apply_natural_rule_plan(plan)

    destination = tmp_path / plan["actions"][0]["relative_destination"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"existing")
    result = apply_natural_rule_plan(plan, approved=True)
    assert result["applied"] == 1
    assert result["errors"] == []
    assert destination.read_bytes() == b"existing"
    moved = list(destination.parent.glob("screenshot-old*.png"))
    assert len(moved) == 2
    assert result["undo_ops"][0]["dst"] == str(source)


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], "-platform", "offscreen"])
    yield app


def test_natural_language_rules_dialog_builds_review_surface(qapp, tmp_path):
    from unifile.dialogs.natural_rules import NaturalLanguageRulesDialog

    dialog = NaturalLanguageRulesDialog(source_root=str(tmp_path))
    assert dialog.edit_source.text() == str(tmp_path)
    assert dialog.table.columnCount() == 4
    assert dialog.btn_open.text() == "Open JSON plan…"
    assert not dialog.btn_apply.isEnabled()
    dialog.close()
