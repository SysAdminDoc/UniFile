"""Multi-library registry and scoped preference coverage."""

from __future__ import annotations

import json

import pytest

from unifile.engine import RuleEngine
from unifile.library_context import set_active_library_root
from unifile.library_profiles import LibraryProfileStore
from unifile.ollama import load_ollama_settings, save_ollama_settings


@pytest.fixture
def unifile_window(qtbot):
    from unifile.main_window import UniFile

    window = UniFile()
    qtbot.addWidget(window)
    yield window
    window.close()


def test_library_profile_store_round_trips_and_never_deletes_folders(tmp_path):
    first = tmp_path / "Design Library"
    second = tmp_path / "Books"
    first.mkdir()
    second.mkdir()
    store = LibraryProfileStore(str(tmp_path / "libraries.json"))

    assert store.add(str(tmp_path / "missing")) is None
    design = store.add(str(first), "Design")
    assert design and design["name"] == "Design"
    assert store.add(str(first), "Renamed") == design
    books = store.add(str(second), "Books")
    assert books and store.active_id == books["id"]
    assert store.set_active(design["id"])["path"] == str(first.resolve())
    assert store.remove(books["id"]) is True
    assert second.is_dir()
    reloaded = LibraryProfileStore(str(tmp_path / "libraries.json"))
    assert [item["name"] for item in reloaded.profiles] == ["Design"]
    assert reloaded.active_profile()["id"] == design["id"]


def test_ollama_rules_and_theme_are_scoped_to_active_library(tmp_path):
    from unifile import config

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_rule = [{"name": "first", "conditions": [{"field": "name", "op": "contains", "value": "a"}]}]
    second_rule = [{"name": "second", "conditions": [{"field": "name", "op": "contains", "value": "b"}]}]
    try:
        set_active_library_root(str(first))
        save_ollama_settings({"model": "first-model"})
        RuleEngine.save_rules(first_rule)
        config.save_theme_name("Nord")

        set_active_library_root(str(second))
        save_ollama_settings({"model": "second-model"})
        RuleEngine.save_rules(second_rule)
        config.save_theme_name("Dracula")

        set_active_library_root(str(first))
        assert load_ollama_settings()["model"] == "first-model"
        assert RuleEngine.load_rules() == first_rule
        assert config.load_theme_name() == "Nord"

        set_active_library_root(str(second))
        assert load_ollama_settings()["model"] == "second-model"
        assert RuleEngine.load_rules() == second_rule
        assert config.load_theme_name() == "Dracula"
        assert (second / ".unifile" / "rules.json").is_file()
        assert json.loads((first / ".unifile" / "ollama_settings.json").read_text())["model"] == "first-model"
    finally:
        set_active_library_root(None)


@pytest.mark.slow
def test_sidebar_library_selector_switches_open_tag_library(unifile_window, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    store = LibraryProfileStore(str(tmp_path / "libraries.json"))
    unifile_window._library_store = store

    try:
        first_profile = store.add(str(first), "First")
        unifile_window._populate_library_selector()
        unifile_window._activate_library(first_profile)
        assert unifile_window.cmb_library.currentText() == "First"
        assert unifile_window._tag_panel.library.library_dir == str(first.resolve())

        second_profile = store.add(str(second), "Second")
        unifile_window._populate_library_selector()
        unifile_window._activate_library(second_profile)
        assert unifile_window.cmb_library.currentText() == "Second"
        assert unifile_window._tag_panel.library.library_dir == str(second.resolve())
    finally:
        set_active_library_root(None)
