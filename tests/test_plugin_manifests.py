import json

import pytest

pytest.importorskip("yaml")


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


def test_manifest_parser_normalizes_documented_hook_list():
    from unifile.plugin_manifest import parse_manifest

    manifest = parse_manifest(
        """manifest_version: 1
id: plugin.my_classifier
name: My Custom Classifier
version: 1.0
hooks:
  - classify: classify_custom
  - on_apply: log_movement
"""
    )

    assert manifest["id"] == "plugin.my_classifier"
    assert manifest["version"] == "1.0"
    assert manifest["entrypoint"] == "plugin.py"
    assert manifest["hooks"] == {
        "classify": "classify_custom",
        "on_apply": "log_movement",
    }


def test_manifest_v2_requires_capabilities_and_bounds_resources():
    from unifile.plugin_manifest import ManifestError, parse_manifest

    manifest = parse_manifest(
        """manifest_version: 2
id: plugin.v2
name: V2 Plugin
version: 2.0
capabilities:
  - read_metadata
resources:
  timeout_ms: 500
  max_output_bytes: 4096
  max_items: 20
isolation: process
hooks:
  classify: classify_custom
"""
    )

    assert manifest["capabilities"] == ["read_metadata"]
    assert manifest["resources"] == {
        "timeout_ms": 500,
        "max_output_bytes": 4096,
        "max_items": 20,
    }
    assert manifest["isolation"] == "process"
    assert manifest["legacy_manifest"] is False
    with pytest.raises(ManifestError, match="capabilities is required"):
        parse_manifest(
            """manifest_version: 2
id: plugin.missing
name: Missing
version: 1
resources: {}
hooks:
  classify: classify
"""
        )
    with pytest.raises(ManifestError, match="between 100 and 60000"):
        parse_manifest(
            """manifest_version: 2
id: plugin.bad-resource
name: Bad Resource
version: 1
capabilities: [read_metadata]
resources:
  timeout_ms: 50
hooks:
  classify: classify
"""
        )


@pytest.mark.parametrize(
    "source, message",
    [
        ("id: plugin.bad\nname: Bad\nversion: 1\nentrypoint: ../bad.py\nhooks:\n  classify: run\n", "entrypoint"),
        ("id: plugin.bad\nname: Bad\nversion: 1\nhooks:\n  unknown: run\n", "unsupported hook"),
        ("id: plugin.bad\nname: Bad\nversion: 1\nhooks:\n  classify: __run\n", "public Python identifier"),
    ],
)
def test_manifest_parser_rejects_unsafe_or_unknown_fields(source, message):
    from unifile.plugin_manifest import ManifestError, parse_manifest

    with pytest.raises(ManifestError, match=message):
        parse_manifest(source)


def test_manifest_plugin_is_discovered_and_legacy_hook_is_mapped(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    package = plugin_dir / "my-plugin"
    package.mkdir()
    marker = tmp_path / "loaded.txt"
    (package / "plugin.yaml").write_text(
        """manifest_version: 1
id: plugin.my_classifier
name: My Custom Classifier
version: 1.0
hooks:
  - classify: classify_custom
""",
        encoding="utf-8",
    )
    (package / "plugin.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('loaded', encoding='utf-8')\n"
        "def classify_custom(filepath, metadata):\n"
        "    return ('Manifest Category', 97)\n",
        encoding="utf-8",
    )

    discovered = plugins.PluginManager.discover()
    assert discovered[0]["kind"] == "manifest"
    assert discovered[0]["trust_status"] == "untrusted"
    assert discovered[0]["hook_functions"] == {"classify": "classify_custom"}
    assert plugins.PluginManager.trust_metadata(discovered[0])
    plugins.PluginManager.load_all()

    assert marker.read_text(encoding="utf-8") == "loaded"
    assert plugins.PluginManager.run_classifiers("file.txt", {}) == ("Manifest Category", 97)


def test_manifest_change_invalidates_entrypoint_trust(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    package = plugin_dir / "demo"
    package.mkdir()
    (package / "plugin.yaml").write_text(
        "id: plugin.demo\nname: Demo\nversion: 1\nhooks:\n  classify: classify\n",
        encoding="utf-8",
    )
    entrypoint = package / "plugin.py"
    entrypoint.write_text("def classify(filepath, metadata):\n    return None\n", encoding="utf-8")
    meta = plugins.PluginManager.discover()[0]
    assert plugins.PluginManager.trust_metadata(meta)
    assert plugins.PluginManager.discover()[0]["trust_status"] == "trusted"
    (package / "plugin.yaml").write_text(
        "id: plugin.demo\nname: Changed\nversion: 1\nhooks:\n  classify: classify\n",
        encoding="utf-8",
    )
    assert plugins.PluginManager.discover()[0]["trust_status"] == "changed"


def test_manifest_v2_runs_out_of_process_and_fingerprints_contract(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    package = plugin_dir / "isolated"
    package.mkdir()
    marker = tmp_path / "child-import.txt"
    manifest_path = package / "plugin.yaml"
    manifest_path.write_text(
        """manifest_version: 2
id: plugin.isolated
name: Isolated
version: 1
capabilities:
  - read_metadata
resources:
  timeout_ms: 1000
  max_output_bytes: 4096
  max_items: 20
isolation: process
hooks:
  classify: classify
""",
        encoding="utf-8",
    )
    (package / "plugin.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('child', encoding='utf-8')\n"
        "def classify(filepath, metadata):\n"
        "    return ('Isolated', 96)\n",
        encoding="utf-8",
    )

    meta = plugins.PluginManager.discover()[0]
    assert meta["isolation"] == "process"
    assert meta["disabled_hooks"] == ["classify"]
    assert plugins.PluginManager.trust_metadata(meta)
    assert plugins.PluginManager.discover()[0]["disabled_hooks"] == []
    plugins.PluginManager.load_all()
    assert marker.exists() is False
    assert plugins.PluginManager.run_classifiers("file.txt", {}) == ("Isolated", 96)
    assert marker.read_text(encoding="utf-8") == "child"
    record = json.loads((tmp_path / "trusted_plugins.json").read_text(encoding="utf-8"))
    fingerprint = next(iter(record.values()))["fingerprint"]
    assert fingerprint["capability_contract"]["capabilities"] == ["read_metadata"]
    assert fingerprint["capability_sha256"]

    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace("- read_metadata", "- network"),
        encoding="utf-8",
    )
    assert plugins.PluginManager.discover()[0]["trust_status"] == "changed"


def test_high_risk_in_process_manifest_hook_is_disabled(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    package = plugin_dir / "unsafe"
    package.mkdir()
    marker = tmp_path / "unsafe-ran.txt"
    (package / "plugin.yaml").write_text(
        """manifest_version: 2
id: plugin.unsafe
name: Unsafe
version: 1
capabilities: [file_ops]
resources:
  timeout_ms: 1000
  max_output_bytes: 4096
  max_items: 20
isolation: in_process
hooks:
  post_move: post_move
""",
        encoding="utf-8",
    )
    (package / "plugin.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
        "def post_move(src, dst, category):\n"
        "    Path(src).write_text('unexpected', encoding='utf-8')\n",
        encoding="utf-8",
    )

    meta = plugins.PluginManager.discover()[0]
    assert meta["disabled_hooks"] == ["post_move"]
    assert plugins.PluginManager.trust_metadata(meta)
    plugins.PluginManager.load_all()
    plugins.PluginManager.run_post_move("source", "destination", "Docs")
    assert marker.exists() is False
    assert plugins.PluginManager._plugins == []


def test_manifest_process_timeout_is_reaped(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    package = plugin_dir / "timeout"
    package.mkdir()
    (package / "plugin.yaml").write_text(
        """manifest_version: 2
id: plugin.timeout
name: Timeout
version: 1
capabilities: [read_metadata]
resources:
  timeout_ms: 100
  max_output_bytes: 4096
  max_items: 1
isolation: process
hooks:
  classify: classify
""",
        encoding="utf-8",
    )
    (package / "plugin.py").write_text(
        "def classify(filepath, metadata):\n"
        "    while True:\n"
        "        pass\n",
        encoding="utf-8",
    )

    meta = plugins.PluginManager.discover()[0]
    assert plugins.PluginManager.trust_metadata(meta)
    plugins.PluginManager.load_all()
    assert plugins.PluginManager.run_classifiers("file.txt", {}) is None


def test_legacy_manifest_trust_requires_explicit_migration(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    package = plugin_dir / "legacy"
    package.mkdir()
    (package / "plugin.yaml").write_text(
        """manifest_version: 1
id: plugin.legacy
name: Legacy
version: 1
hooks:
  classify: classify
""",
        encoding="utf-8",
    )
    (package / "plugin.py").write_text(
        "def classify(filepath, metadata):\n"
        "    return ('Legacy', 90)\n",
        encoding="utf-8",
    )
    meta = plugins.PluginManager.discover()[0]
    fingerprint = plugins.PluginManager._fingerprint(meta["path"], [meta["manifest_path"]])
    assert plugins.save_json_safe(
        str(tmp_path / "trusted_plugins.json"), {fingerprint["path"]: fingerprint}
    )
    assert plugins.PluginManager.discover()[0]["trust_status"] == "migration_required"
    plugins.PluginManager.load_all()
    assert plugins.PluginManager._plugins == []
    migrated = plugins.PluginManager.discover()[0]
    assert plugins.PluginManager.trust_metadata(migrated)
    assert plugins.PluginManager.discover()[0]["trust_status"] == "trusted"


def test_manifest_workflow_function_alias_runs_in_restricted_process(monkeypatch, tmp_path):
    plugins, plugin_dir = _reset_plugin_state(monkeypatch, tmp_path)
    package = plugin_dir / "workflow"
    package.mkdir()
    (package / "plugin.yaml").write_text(
        """id: plugin.workflow
name: Workflow
version: 1
hooks:
  - on_scan_item: classify_custom
""",
        encoding="utf-8",
    )
    (package / "plugin.py").write_text(
        "def classify_custom(item, classifier, tag_library, file_ops, log):\n"
        "    if item.category == 'Photo':\n"
        "        tag_library.add_tag(item, 'review')\n",
        encoding="utf-8",
    )
    meta = plugins.PluginManager.discover()[0]
    assert plugins.PluginManager.trust_metadata(meta)
    jobs = plugins.PluginManager.workflow_jobs("on_scan_item")
    assert jobs[0]["function"] == "classify_custom"
    result = plugins.PluginManager.run_workflow_hook(
        "on_scan_item",
        {"name": "photo.jpg", "full_src": str(tmp_path / "photo.jpg"), "category": "Photo"},
    )
    assert result[0]["success"] is True
    assert result[0]["commands"][0]["tag"] == "review"


def test_scaffold_creates_manifest_and_entrypoint(tmp_path):
    from unifile.plugin_manifest import create_plugin_scaffold, read_manifest

    result = create_plugin_scaffold("My Plugin", tmp_path)
    assert result["id"] == "plugin.my_plugin"
    assert (tmp_path / "my-plugin" / "plugin.py").is_file()
    manifest = read_manifest(tmp_path / "my-plugin" / "plugin.yaml")
    assert manifest["hooks"] == {"classify": "classify_custom"}


def test_community_index_is_strict_and_display_only():
    from unifile.plugin_manifest import fetch_community_index, parse_community_index

    payload = json.dumps({
        "schema_version": 1,
        "plugins": [{
            "id": "plugin.demo",
            "name": "Demo",
            "version": "1.2.0",
            "description": "A catalog entry",
            "url": "https://github.com/example/demo",
            "hooks": ["classify"],
        }],
    })

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            assert limit > len(payload)
            return payload.encode("utf-8")

    def opener(request, timeout):
        assert request.full_url.startswith("https://")
        assert timeout == 2.0
        return Response()

    assert parse_community_index(payload)[0]["id"] == "plugin.demo"
    assert fetch_community_index("https://example.test/index.json", timeout=2, opener=opener)[0]["name"] == "Demo"
