"""Restricted workflow script execution and trust-boundary tests."""
from __future__ import annotations

import json
import multiprocessing

import pytest


def _item(path="C:/library/photo.jpg"):
    return {
        "name": "photo.jpg",
        "full_src": path,
        "category": "Photo",
        "confidence": 93,
        "size": 12_000_000,
        "method": "extension",
        "metadata": {"camera": "test"},
    }


def test_workflow_validator_rejects_imports_and_private_access():
    from unifile.script import ScriptValidationError, validate_script

    with pytest.raises(ScriptValidationError, match="Import"):
        validate_script(
            "import os\n"
            "def on_scan_item(item, classifier, tag_library, file_ops, log):\n"
            "    log(os.getcwd())\n"
        )
    with pytest.raises(ScriptValidationError, match="Private"):
        validate_script(
            "def on_scan_item(item, classifier, tag_library, file_ops, log):\n"
            "    log(item.__class__)\n"
        )
    with pytest.raises(ScriptValidationError, match="While"):
        validate_script(
            "def on_scan_item(item, classifier, tag_library, file_ops, log):\n"
            "    while True:\n"
            "        pass\n"
        )


def test_workflow_execution_returns_only_serializable_commands():
    from unifile.script import execute_script

    source = """\
def on_scan_item(item, classifier, tag_library, file_ops, log):
    if classifier.category(item) == "Photo" and item.size > 10_000_000:
        tag_library.add_tag(item, "hires")
        file_ops.rename(item, "photo-reviewed.jpg")
        log(f"reviewed {item.name}")
"""
    result = execute_script(
        source,
        "on_scan_item",
        _item(),
        classifier_values={"C:/library/photo.jpg": _item()},
        tag_values={"C:/library/photo.jpg": []},
        timeout=5,
    )

    assert result.success is True
    assert result.logs == ["reviewed photo.jpg"]
    assert {command["op"] for command in result.commands} == {"tag_add", "file_rename"}
    json.dumps(result.commands)


def test_workflow_timeout_terminates_child_process():
    from unifile.script import execute_script

    before = {process.pid for process in multiprocessing.active_children() if process.is_alive()}
    source = """\
def on_scan_item(item, classifier, tag_library, file_ops, log):
    for value in range(10_000_000_000):
        log(value)
"""
    result = execute_script(source, "on_scan_item", _item(), timeout=0.2)

    assert result.success is False
    assert result.timed_out is True
    assert "timed out" in result.error
    assert [
        process.pid
        for process in multiprocessing.active_children()
        if process.is_alive() and process.pid not in before
    ] == []


def test_apply_workflow_commands_requires_explicit_file_roots(tmp_path):
    from unifile.plugins import apply_workflow_commands

    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    commands = [{
        "op": "file_copy",
        "source": str(source),
        "destination": str(outside),
    }]

    applied, skipped = apply_workflow_commands(
        commands,
        allow_file_ops=True,
        allowed_roots=[str(tmp_path)],
    )

    assert applied == []
    assert skipped[0]["reason"] == "destination is outside allowed roots"
    assert outside.exists() is False


def test_workflow_plugin_is_trusted_but_never_imported(monkeypatch, tmp_path):
    from unifile import plugins

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    trust_path = tmp_path / "trusted.json"
    monkeypatch.setattr(plugins, "_PLUGINS_DIR", str(plugin_dir))
    monkeypatch.setattr(plugins, "_PLUGIN_TRUST_PATH", str(trust_path))
    plugins.PluginManager._plugins.clear()
    script_path = plugin_dir / "workflow.py"
    marker = tmp_path / "imported.txt"
    script_path.write_text(
        '"""Workflow\nWorkflow-Hook: on_scan_item\n"""\n'
        f"open({str(marker)!r}, 'w').write('imported')\n"
        "def on_scan_item(item, classifier, tag_library, file_ops, log):\n"
        "    log(item.name)\n",
        encoding="utf-8",
    )

    assert plugins.PluginManager.trust(str(script_path))
    plugins.PluginManager.load_all()

    discovered = plugins.PluginManager.discover()
    assert discovered[0]["kind"] == "workflow"
    assert discovered[0]["workflow_hooks"] == ["on_scan_item"]
    assert plugins.PluginManager._plugins == []
    assert marker.exists() is False
