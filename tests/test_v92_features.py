"""Tests for v9.2.0 additions: defensive JSON loaders, new CLI subcommands,
additional latent-NameError fixes, and SemanticSearchDialog wiring."""
import json
import os

import pytest

# ── Defensive JSON helpers (config.load_json_safe / save_json_safe) ───────────

def test_load_json_safe_returns_default_when_missing(tmp_path):
    from unifile.config import load_json_safe
    assert load_json_safe(str(tmp_path / 'nope.json'), default={}) == {}
    assert load_json_safe(str(tmp_path / 'nope.json'), default=[]) == []


def test_load_json_safe_handles_corrupt_file(tmp_path):
    from unifile.config import load_json_safe
    bad = tmp_path / 'bad.json'
    bad.write_text('this is not JSON {{{')
    assert load_json_safe(str(bad), default={'fallback': True}) == {'fallback': True}


def test_load_json_safe_type_mismatch_uses_default(tmp_path):
    from unifile.config import load_json_safe
    path = tmp_path / 'wrong_type.json'
    # File contains a list, caller expected a dict
    path.write_text('[1, 2, 3]')
    assert load_json_safe(str(path), default={}, expected_type=dict) == {}
    # Caller expected a list — should succeed
    assert load_json_safe(str(path), default=[], expected_type=list) == [1, 2, 3]


def test_save_json_safe_roundtrip(tmp_path):
    from unifile.config import load_json_safe, save_json_safe
    path = tmp_path / 'sub' / 'settings.json'  # parent dir doesn't exist
    payload = {'theme': 'dark', 'confidence_threshold': 80, 'nested': {'a': 1}}
    assert save_json_safe(str(path), payload) is True
    assert path.exists()
    # Round-trip through load_json_safe
    assert load_json_safe(str(path), default={}) == payload


def test_save_json_safe_atomic_no_tmp_leftover(tmp_path):
    from unifile.config import save_json_safe
    path = tmp_path / 'atomic.json'
    save_json_safe(str(path), {'x': 1})
    # No .tmp file should be left behind after a successful write
    assert not (tmp_path / 'atomic.json.tmp').exists()


def test_save_json_safe_returns_false_on_non_serializable(tmp_path):
    from unifile.config import save_json_safe
    class _Unserializable:
        pass
    path = tmp_path / 'bad.json'
    assert save_json_safe(str(path), {'obj': _Unserializable()}) is False
    # No partial file left behind
    assert not path.exists()
    assert not (tmp_path / 'bad.json.tmp').exists()


# ── CLI: list-profiles / list-models ──────────────────────────────────────────

def test_list_profiles_empty(capsys, tmp_path, monkeypatch):
    import argparse

    from unifile import plugins
    from unifile.__main__ import _cmd_list_profiles
    monkeypatch.setattr(plugins, '_PROFILES_DIR', str(tmp_path))
    rc = _cmd_list_profiles(argparse.Namespace(json=False))
    assert rc == 0
    assert 'no saved profiles' in capsys.readouterr().out.lower()


def test_list_profiles_json(capsys, tmp_path, monkeypatch):
    import argparse

    from unifile import plugins
    from unifile.__main__ import _cmd_list_profiles
    monkeypatch.setattr(plugins, '_PROFILES_DIR', str(tmp_path))
    plugins.ProfileManager.save('alpha', {'name': 'alpha'})
    plugins.ProfileManager.save('bravo', {'name': 'bravo'})
    rc = _cmd_list_profiles(argparse.Namespace(json=True))
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {'alpha', 'bravo'}


def test_list_models_unreachable_returns_empty_list(capsys, monkeypatch):
    """When Ollama is unreachable, list-models should print an empty list
    (or '(no models installed)'), not crash."""
    import argparse

    from unifile import ollama as _ol
    from unifile.__main__ import _cmd_list_models
    # Force the helper to return an empty list (simulates unreachable server)
    monkeypatch.setattr(_ol, '_ollama_list_models', lambda url=None: [])
    rc = _cmd_list_models(argparse.Namespace(json=False, url='http://x'))
    assert rc == 0
    assert 'no models installed' in capsys.readouterr().out.lower()


def test_list_models_json(capsys, monkeypatch):
    import argparse

    from unifile import ollama as _ol
    from unifile.__main__ import _cmd_list_models
    monkeypatch.setattr(_ol, '_ollama_list_models',
                        lambda url=None: ['qwen3.5:9b', 'llama3.2:3b'])
    rc = _cmd_list_models(argparse.Namespace(
        json=True, url='http://localhost:11434'))
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == ['qwen3.5:9b', 'llama3.2:3b']


# ── Latent NameError regression locks ─────────────────────────────────────────

def test_categories_load_custom_doesnt_nameerror():
    """load_custom_categories used `json` without importing it."""
    from unifile.categories import load_custom_categories
    # Call the function; it should not raise NameError even if no file exists
    result = load_custom_categories()
    assert isinstance(result, list)


def test_categories_save_custom_doesnt_nameerror(tmp_path, monkeypatch):
    from unifile import categories as _cats
    monkeypatch.setattr(_cats, '_CUSTOM_CATS_FILE', str(tmp_path / 'c.json'))
    _cats.save_custom_categories([('My Cat', ['keyword'])])
    assert (tmp_path / 'c.json').exists()


def test_metadata_module_has_extension_sets():
    """metadata.py used _META_IMAGE_EXTS etc. without defining them."""
    from unifile import metadata as _m
    assert hasattr(_m, '_META_IMAGE_EXTS')
    assert hasattr(_m, '_META_AUDIO_EXTS')
    assert hasattr(_m, '_META_VIDEO_EXTS')
    assert hasattr(_m, 'Counter')  # module-level import
    assert hasattr(_m, 'shutil')
    assert hasattr(_m, 'subprocess')


def test_photos_module_has_io_and_base64():
    """_detect_faces_full used io.BytesIO and base64 without imports."""
    from unifile import photos as _p
    assert hasattr(_p, 'io')
    assert hasattr(_p, 'base64')


def test_classifier_has_topic_categories():
    """classifier.py referenced TOPIC_CATEGORIES without importing it."""
    from unifile.classifier import TOPIC_CATEGORIES
    assert isinstance(TOPIC_CATEGORIES, set)


def test_main_window_can_import_without_nameerror():
    """End-to-end: importing main_window should not raise NameError."""
    # Previously failed with undefined names: MetadataExtractor, QThreadPool,
    # _load_envato_api_key, _save_envato_api_key.
    import unifile.main_window
    assert hasattr(unifile.main_window, 'UniFile')


def test_workers_module_has_all_missing_imports():
    """Spot-check the 15+ names that were previously undefined in workers.py."""
    from unifile import workers as _w
    names = [
        'subprocess', 'sys', 'MetadataExtractor', 'ArchivePeeker',
        '_JUNK_SUFFIXES', '_PHASH_IMAGE_EXTS', 'ModelRouter',
        '_ollama_generate', '_ollama_pull_model', '_llm_cache_get',
        '_llm_cache_set', 'HAS_PILLOW', '_cv2', '_face_recognition',
        'check_corrections', '_CategoryIndex', '_is_id_only_folder',
        '_extract_name_hints', 'ollama_test_connection',
        '_EVIDENCE_CONFIDENCE_THRESHOLD', '_escalate_classification',
    ]
    missing = [n for n in names if not hasattr(_w, n)]
    assert not missing, f"workers.py still missing: {missing}"


# ── Ollama settings uses safe loader ──────────────────────────────────────────

def test_load_ollama_settings_recovers_from_corrupt_file(tmp_path, monkeypatch):
    """Corrupt JSON in ollama_settings.json should not crash the app."""
    from unifile import ollama as _ol
    bad = tmp_path / 'ollama_settings.json'
    bad.write_text('{not valid json')
    monkeypatch.setattr(_ol, '_OLLAMA_SETTINGS_FILE', str(bad))
    # Should return defaults, not raise
    s = _ol.load_ollama_settings()
    assert isinstance(s, dict)
    assert 'url' in s
    assert s['url']  # has a usable default URL


# ── SemanticSearchDialog export (smoke test) ──────────────────────────────────

def test_semantic_search_dialog_is_exported():
    """Regression: SemanticSearchDialog must be importable from the
    top-level dialogs package for main_window to use it."""
    from unifile.dialogs import SemanticSearchDialog
    assert SemanticSearchDialog is not None
