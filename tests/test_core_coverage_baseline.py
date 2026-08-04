"""Targeted coverage for the roadmap's four core coverage gates."""

from collections import Counter


def _composition_scan(ext_counts: dict[str, int], **overrides):
    data = {
        "ext_counts": Counter(ext_counts),
        "file_count": sum(ext_counts.values()),
        "subfolder_names": [],
        "archive_stems": [],
        "has_footage": False,
        "has_audio": False,
    }
    data.update(overrides)
    return data


def test_classifier_scan_and_extension_classification(tmp_path):
    from unifile.classifier import _classify_ext_from_scan, _scan_folder_once

    root = tmp_path / "font-pack"
    preview = root / "previews"
    preview.mkdir(parents=True)
    (root / "regular.ttf").write_bytes(b"font")
    (root / "bold.otf").write_bytes(b"font")
    (preview / "sample.png").write_bytes(b"image")
    (root / "readme.txt").write_text("font pack", encoding="utf-8")

    scan = _scan_folder_once(str(root))
    assert scan["file_count"] == 4
    assert scan["ext_counts"][".ttf"] == 1
    assert "previews" in scan["subfolder_names"]
    assert scan["has_design_files"] is False

    category, confidence, detail = _classify_ext_from_scan(scan)
    assert category == "Fonts & Typography"
    assert confidence >= 80
    assert ".ttf(1)" in detail


def test_classifier_composition_branches(monkeypatch):
    from unifile import classifier

    category, confidence, _ = classifier._classify_composition_from_scan(
        _composition_scan({".mp4": 5, ".txt": 1})
    )
    assert (category, confidence) == ("Stock Footage - General", 75)

    category, _, _ = classifier._classify_composition_from_scan(
        _composition_scan({".mp3": 5, ".txt": 1})
    )
    assert category == "Stock Music & Audio"

    category, _, _ = classifier._classify_composition_from_scan(
        _composition_scan({".cr2": 3, ".jpg": 1})
    )
    assert category == "Photography - RAW Files"

    monkeypatch.setattr(
        classifier,
        "aggregate_archive_names",
        lambda stems: ("Stock Footage - General", 81, "archive:stock"),
    )
    category, confidence, detail = classifier._classify_composition_from_scan(
        _composition_scan(
            {".zip": 2, ".txt": 1},
            archive_stems=["stock-footage", "stock-music"],
        )
    )
    assert (category, confidence, detail) == (
        "Stock Footage - General",
        81,
        "archive:stock",
    )


def test_classifier_tiered_paths_and_optional_fuzzy(monkeypatch, tmp_path):
    from unifile import classifier

    category, confidence, result = classifier.categorize_folder("Photoshop Brushes")
    assert category == "Photoshop - Brushes"
    assert confidence == 100
    assert result == "Photoshop Brushes"

    result = classifier.tiered_classify("Photoshop Brushes")
    assert result["category"] == "Photoshop - Brushes"
    assert result["confidence"] >= 65

    font_root = tmp_path / "fonts"
    font_root.mkdir()
    (font_root / "one.ttf").write_bytes(b"font")
    (font_root / "two.ttf").write_bytes(b"font")
    result = classifier.tiered_classify("font bundle", str(font_root))
    assert result["category"] == "Fonts & Typography"
    assert result["method"] == "extension"

    if classifier.HAS_RAPIDFUZZ:
        fuzzy_category, fuzzy_confidence, fuzzy_detail = classifier.fuzzy_match_categories(
            "Photoshop Brushes"
        )
        assert fuzzy_category == "Photoshop - Brushes"
        assert fuzzy_confidence > 0
        assert fuzzy_detail.startswith("fuzzy:")

    monkeypatch.setattr(classifier, "HAS_RAPIDFUZZ", False)
    assert classifier.fuzzy_match_categories("ab") == (None, 0, "")
    assert classifier.fuzzy_match_categories("long-enough-name") == (None, 0, "")


def test_classifier_context_and_metadata_helpers(monkeypatch, tmp_path):
    from unifile import classifier

    scan = _composition_scan(
        {".psd": 1},
        all_filenames_clean=["phone mockup"],
        design_file_count=1,
        video_template_count=0,
        has_design_files=True,
        has_video_templates=False,
        project_files=[
            ("demo.prproj", ".prproj"),
            ("demo.psd", ".psd"),
            ("demo.mogrt", ".mogrt"),
        ],
    )
    clues = classifier._asset_clues_from_scan(scan, str(tmp_path))
    assert clues["asset_type"] == "Mockups - Devices"
    assert clues["filename_hints"]

    monkeypatch.setattr(classifier, "extract_prproj_metadata", lambda path: ["client project"])
    monkeypatch.setattr(classifier, "extract_psd_metadata", lambda path: ["product mockup"])
    monkeypatch.setattr(classifier, "HAS_PSD_TOOLS", True)
    metadata = classifier._extract_metadata_from_scan(scan, "client-project")
    assert metadata["has_prproj"] is True
    assert metadata["has_psd"] is True
    assert metadata["has_mogrt"] is True
    assert metadata["project_names"] == ["client project"]
    assert metadata["keywords"] == ["product mockup"]

    result = {
        "category": "Photoshop - Templates & Composites",
        "confidence": 70,
        "cleaned_name": "phone mockup",
        "method": "keyword",
        "detail": "keyword",
        "metadata": {},
        "topic": None,
    }
    contextual = classifier._apply_context_from_scan(
        result, scan, str(tmp_path), "phone mockup"
    )
    assert contextual["category"] == "Mockups - Devices"
    assert contextual["method"] == "context"


def test_tag_library_core_crud_and_health_paths(tmp_path):
    from unifile.tagging.library import TagLibrary

    unopened = TagLibrary()
    assert not unopened.open()
    unopened.close()

    root = tmp_path / "library"
    library = TagLibrary(str(root))
    assert library.open()
    try:
        parent = library.add_tag("Projects", shorthand="PR", is_category=True)
        child = library.add_tag("Draft", parent_id=parent.id if parent else None)
        assert parent and child
        assert library.add_tag("projects") is parent
        assert library.update_tag(
            child.id,
            namespace="work",
            description="draft work",
            icon="file",
            is_hidden=True,
        )
        assert library.get_tag_by_name("Draft") is not None
        assert library.get_tag_display_name(child) == "Draft"
        hierarchy = library.get_tag_hierarchy()
        assert hierarchy and hierarchy[0]["children"]

        file_path = root / "draft.txt"
        file_path.write_text("draft", encoding="utf-8")
        entry = library.add_entry(str(file_path))
        assert entry
        assert library.set_entry_rating(entry.id, 4)
        assert library.set_entry_inbox(entry.id, False)
        assert library.set_entry_source_url(entry.id, "https://example.test/draft")
        assert library.update_entry_media_props(entry.id, width=100, height=80)
        assert library.get_entry_by_path(str(file_path)) is not None
        assert library.get_entries_by_rating(4)
        assert library.get_archived_entries()
        assert library.get_stats()["entries"] == 1

        extra_root = tmp_path / "extra"
        extra_root.mkdir()
        assert library.add_root(str(extra_root))
        assert str(extra_root) in library.get_roots()
        statuses = library.get_root_statuses()
        assert any(status["path"] == str(root) for status in statuses)
    finally:
        library.close()
