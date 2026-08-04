"""Shared action-plan validation and transactional apply coverage."""

from __future__ import annotations

import pytest

from unifile.action_plan import (
    ActionPlanError,
    apply_action_plan,
    build_action_plan,
    normalize_action_plan,
)


def test_normalize_action_list_adds_safe_dag_and_relative_paths(tmp_path):
    source = tmp_path / "inbox"
    destination = tmp_path / "organized"
    source.mkdir()
    item = source / "note.txt"
    item.write_text("note", encoding="utf-8")

    plan = normalize_action_plan({
        "source_root": str(source),
        "destination_roots": [str(destination)],
        "actions": [{
            "id": "note",
            "operation": "rename",
            "src": "note.txt",
            "dst": str(destination / "note.txt"),
            "reason": "classified as a note",
        }],
    })

    assert plan["plan_type"] == "file-actions"
    assert plan["actions"][0]["operation"] == "move"
    assert plan["actions"][0]["relative_source"] == "note.txt"
    assert plan["actions"][0]["relative_destination"] == "note.txt"
    assert [node["id"] for node in plan["nodes"]] == ["propose", "review", "apply"]
    assert plan["nodes"][-1]["requires_approval"] is True


def test_normalize_action_plan_rejects_unsafe_actions_and_cycles(tmp_path):
    source = tmp_path / "inbox"
    source.mkdir()
    (source / "note.txt").write_text("note", encoding="utf-8")

    with pytest.raises(ActionPlanError, match="approved roots"):
        normalize_action_plan({
            "source_root": str(source),
            "actions": [{"source": "note.txt", "destination": "../escape.txt"}],
        })

    with pytest.raises(ActionPlanError, match="dependency cycle"):
        normalize_action_plan({
            "source_root": str(source),
            "nodes": [
                {"id": "review", "depends_on": ["apply"], "requires_approval": True},
                {"id": "apply", "depends_on": ["review"], "requires_approval": True},
            ],
            "actions": [],
        })


def test_apply_action_plan_swaps_files_without_partial_state(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    plan = build_action_plan(
        source_root=tmp_path,
        actions=[
            {"id": "first", "source": str(first), "destination": str(second)},
            {"id": "second", "source": str(second), "destination": str(first)},
        ],
    )

    with pytest.raises(ActionPlanError, match="approval"):
        apply_action_plan(plan)
    result = apply_action_plan(plan, approved=True)

    assert result["applied"] == 2
    assert result["errors"] == []
    assert first.read_text(encoding="utf-8") == "second"
    assert second.read_text(encoding="utf-8") == "first"


def test_apply_action_plan_rolls_back_when_commit_fails(tmp_path, monkeypatch):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    destination = tmp_path / "out"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    first_target = destination / "first.txt"
    second_target = destination / "second.txt"
    plan = build_action_plan(
        source_root=tmp_path,
        destination_roots=[destination],
        actions=[
            {"id": "first", "source": str(first), "destination": str(first_target)},
            {"id": "second", "source": str(second), "destination": str(second_target)},
        ],
    )

    import unifile.action_plan as module

    real_move = module.shutil.move

    def fail_second_commit(source_path, destination_path, *args, **kwargs):
        if str(destination_path) == str(second_target):
            raise OSError("simulated commit failure")
        return real_move(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(module.shutil, "move", fail_second_commit)
    result = apply_action_plan(plan, approved=True)

    assert result["applied"] == 0
    assert result["rolled_back"] == 1
    assert result["errors"]
    assert first.read_text(encoding="utf-8") == "first"
    assert second.read_text(encoding="utf-8") == "second"
    assert not first_target.exists()
    assert not second_target.exists()
