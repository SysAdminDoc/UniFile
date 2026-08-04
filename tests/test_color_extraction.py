"""Palette extraction and Tag Library color-search coverage."""

from PyQt6.QtGui import QColor, QImage

from unifile.color_extraction import (
    color_name_for_rgb,
    extract_color_palette,
    parse_color_query,
)
from unifile.tagging.library import TagLibrary


def _write_solid_image(path, color: str):
    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def test_color_name_and_query_parser_cover_explicit_and_natural_forms():
    assert color_name_for_rgb(30, 70, 220) == "blue"
    assert color_name_for_rgb(225, 35, 35) == "red"
    assert parse_color_query("color:navy") == ("blue", False)
    assert parse_color_query("show me files with predominant blue tones") == (
        "blue", True)
    assert parse_color_query("blue") is None


def test_palette_extraction_returns_weighted_ranked_colors(tmp_path):
    image_path = tmp_path / "ocean.png"
    _write_solid_image(image_path, "#1e46dc")

    palette = extract_color_palette(image_path)

    assert palette
    assert palette[0]["name"] == "blue"
    assert palette[0]["rank"] == 0
    assert palette[0]["weight"] == 1.0
    assert palette[0]["hex"].startswith("#")


def test_tag_library_indexes_and_searches_image_colors(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    blue_path = root / "ocean.png"
    red_path = root / "sunset.jpg"
    _write_solid_image(blue_path, "#1e46dc")
    _write_solid_image(red_path, "#dc3028")

    library = TagLibrary(str(root))
    assert library.open()
    try:
        blue_entry = library.add_entry(str(blue_path))
        assert blue_entry is not None
        assert library.add_entries_bulk([str(red_path)]) == 1

        colors = library.get_entry_colors(blue_entry.id)
        assert colors and colors[0].color_name == "blue"
        assert [entry.filename for entry in library.search_entries("color:blue")] == [
            "ocean.png"
        ]
        assert [
            entry.filename
            for entry in library.search_entries(
                "show me files with predominant red tones")
        ] == ["sunset.jpg"]
    finally:
        library.close()


def test_tag_library_dominant_color_swatches_drive_search_query(qtbot):
    from unifile.dialogs.tag_library import TagLibraryPanel

    panel = TagLibraryPanel()
    qtbot.addWidget(panel)

    panel._color_swatch_buttons["blue"].click()

    assert panel.txt_entry_search.text() == (
        "show me files with predominant blue tones"
    )
    assert panel._color_swatch_buttons["blue"].isChecked()
    assert not panel._color_swatch_buttons["red"].isChecked()

    panel.btn_color_clear.click()
    assert panel.txt_entry_search.text() == ""
    assert not any(button.isChecked() for button in panel._color_swatch_buttons.values())
