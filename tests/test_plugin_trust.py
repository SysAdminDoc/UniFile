from pathlib import Path


def _reset_plugin_state(monkeypatch, tmp_path):
    from unifile import plugins

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    trust_path = tmp_path / "trusted_plugins.json"
    monkeypatch.setattr(plugins, "_PLUGINS_DIR", str(plugin_dir))
    monkeypatch.setattr(plugins, "_PLUGIN_TRUST_PATH", str(trust_path))
    plugins.PluginManager._plugins.clear()
    plugins.PluginManager._load_errors.clear()
    return plugins, plugin_dir


def test_untrusted_plugin_is_discovered_but_not_executed(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    marker = tmp_path / "executed.txt"
    plugin_path = plugin_dir / "demo.py"
    plugin_path.write_text(
        '"""Demo plugin\nHook: classify\n"""\n'
        f"Path({str(marker)!r}).write_text('ran')\n"
        "def classify(filepath, metadata):\n"
        "    return ('Demo', 99)\n",
        encoding="utf-8",
    )

    discovered = plugins.PluginManager.discover()
    plugins.PluginManager.load_all()

    assert discovered[0]["trust_status"] == "untrusted"
    assert discovered[0]["trusted"] is False
    assert marker.exists() is False
    assert plugins.PluginManager._plugins == []


def test_trusted_plugin_loads_and_runs(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    marker = tmp_path / "executed.txt"
    plugin_path = plugin_dir / "demo.py"
    plugin_path.write_text(
        '"""Demo plugin\nHook: classify\n"""\n'
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran')\n"
        "def classify(filepath, metadata):\n"
        "    return ('Trusted Demo', 98)\n",
        encoding="utf-8",
    )

    assert plugins.PluginManager.trust(str(plugin_path))
    plugins.PluginManager.load_all()

    assert marker.read_text(encoding="utf-8") == "ran"
    assert plugins.PluginManager.run_classifiers("file.txt", {}) == ("Trusted Demo", 98)


def test_changed_trusted_plugin_is_disabled(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    marker = tmp_path / "executed.txt"
    plugin_path = plugin_dir / "demo.py"
    plugin_path.write_text('"""Demo plugin\nHook: classify\n"""\n', encoding="utf-8")
    assert plugins.PluginManager.trust(str(plugin_path))
    plugin_path.write_text(
        '"""Demo plugin\nHook: classify\n"""\n'
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )

    discovered = plugins.PluginManager.discover()
    plugins.PluginManager.load_all()

    assert discovered[0]["trust_status"] == "changed"
    assert marker.exists() is False
    assert plugins.PluginManager._plugins == []


def test_trusted_plugin_load_error_is_reported(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    plugin_path = plugin_dir / "bad.py"
    plugin_path.write_text(
        '"""Bad plugin\nHook: classify\n"""\n'
        "raise RuntimeError('boom')\n",
        encoding="utf-8",
    )

    assert plugins.PluginManager.trust(str(plugin_path))
    plugins.PluginManager.load_all()

    errors = plugins.PluginManager.last_load_errors()
    assert len(errors) == 1
    assert errors[0]["name"] == "bad"
    assert "RuntimeError: boom" in errors[0]["load_error"]
