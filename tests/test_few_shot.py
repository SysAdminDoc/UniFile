"""Tests for the local few-shot correction store and prompt rendering."""
import json

from unifile import cache


def test_few_shot_examples_append_load_and_keep_latest_valid_rows(tmp_path):
    path = tmp_path / "few-shot.jsonl"
    path.write_text(
        "not json\n"
        + json.dumps({"folder_name": "", "correct_category": "Ignored"})
        + "\n",
        encoding="utf-8",
    )

    assert cache.save_few_shot_example("Invoice Q1", "Finance", path=str(path))
    assert cache.save_few_shot_example("Photo album", "Photos", path=str(path))
    assert cache.load_few_shot_examples(path=str(path)) == [
        {"folder_name": "Invoice Q1", "correct_category": "Finance"},
        {"folder_name": "Photo album", "correct_category": "Photos"},
    ]


def test_few_shot_prompt_is_quoted_and_limited_to_recent_examples(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CORRECTIONS_FILE", str(tmp_path / "corrections.json"))

    for index in range(12):
        assert cache.save_few_shot_example(f"Folder {index}", "Documents")
    assert cache.save_few_shot_example('Invoice "Q1"', "Finance")

    prompt = cache.format_few_shot_prompt()

    assert "FEW-SHOT CORRECTION EXAMPLES" in prompt
    assert "Folder 2" not in prompt
    assert "Folder 3" in prompt
    assert json.dumps('Invoice "Q1"') in prompt
    assert json.dumps("Finance") in prompt


def test_save_correction_updates_lookup_and_few_shot_store(tmp_path, monkeypatch):
    corrections_path = tmp_path / "corrections.json"
    monkeypatch.setattr(cache, "_CORRECTIONS_FILE", str(corrections_path))

    cache.save_correction("Invoice Q1", "Finance")

    assert cache.check_corrections("Invoice Q1") == "Finance"
    assert cache.load_few_shot_examples() == [
        {"folder_name": "Invoice Q1", "correct_category": "Finance"}
    ]


def test_llm_system_prompt_includes_recent_corrections(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CORRECTIONS_FILE", str(tmp_path / "corrections.json"))
    monkeypatch.setattr(
        "unifile.profiles.get_llm_system_prompt_prefix", lambda: None
    )
    cache.save_few_shot_example("Invoice Q1", "Finance")

    from unifile.ollama import _build_llm_system_prompt

    prompt = _build_llm_system_prompt(["Finance"])

    assert "VALID CATEGORIES (pick exactly one):\nFinance" in prompt
    assert "name=\"Invoice Q1\" -> correct_category=\"Finance\"" in prompt
