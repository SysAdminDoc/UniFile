"""Accessibility configuration bounds."""

from unifile import config


def test_font_size_stays_within_accessibility_range(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_FONT_SIZE_FILE", str(tmp_path / "font-size.json"))
    monkeypatch.setattr(config, "_cached_font_size", None)

    config.save_font_size(99)
    assert config.load_font_size() == 20
    config.save_font_size(1)
    assert config.load_font_size() == 8
