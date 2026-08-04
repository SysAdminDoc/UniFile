"""Accessibility configuration bounds."""

from unifile import config


def test_font_size_stays_within_accessibility_range(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_FONT_SIZE_FILE", str(tmp_path / "font-size.json"))
    monkeypatch.setattr(config, "_cached_font_size", None)

    config.save_font_size(99)
    assert config.load_font_size() == 20
    config.save_font_size(1)
    assert config.load_font_size() == 8


def test_high_contrast_theme_is_registered_with_strong_primary_tokens():
    theme = config.THEME_HIGH_CONTRAST

    assert len(config.THEMES) == 7
    assert config.THEMES["High Contrast"] is theme
    assert theme["bg"] == "#000000"
    assert theme["fg"] == "#ffffff"
    assert theme["accent"] == "#ffff00"
    stylesheet = config._build_theme_qss(theme)
    assert "background-color: #000000;" in stylesheet
    assert "color: #ffffff;" in stylesheet


def test_accessibility_dialog_exposes_the_supported_font_range(qtbot):
    from unifile.dialogs.accessibility import AccessibilityDialog

    dialog = AccessibilityDialog()
    qtbot.addWidget(dialog)

    assert dialog.sld.minimum() == 8
    assert dialog.sld.maximum() == 20
    dialog.sld.setValue(20)
    assert dialog.lbl_value.text() == "20 px"
