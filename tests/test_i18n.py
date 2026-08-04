"""Tests for the i18n infrastructure (locale loading, language switching)."""
import os

import pytest

from unifile.i18n import (
    apply_layout_direction,
    effective_layout_direction,
    get_available_languages,
    get_current_language,
    get_layout_direction_preference,
    install_translator,
    is_rtl_language,
    set_language,
    set_layout_direction_preference,
)


def test_default_language_is_english(monkeypatch, tmp_path):
    monkeypatch.setattr('unifile.i18n._LANG_FILE', str(tmp_path / 'lang.json'))
    monkeypatch.delenv('UNIFILE_LANG', raising=False)
    assert get_current_language() == 'en'


def test_env_overrides_saved_language(monkeypatch, tmp_path):
    monkeypatch.setattr('unifile.i18n._LANG_FILE', str(tmp_path / 'lang.json'))
    monkeypatch.setenv('UNIFILE_LANG', 'fr')
    assert get_current_language() == 'fr'


def test_set_and_get_language(monkeypatch, tmp_path):
    lang_file = str(tmp_path / 'lang.json')
    monkeypatch.setattr('unifile.i18n._LANG_FILE', lang_file)
    monkeypatch.delenv('UNIFILE_LANG', raising=False)
    set_language('de')
    assert get_current_language() == 'de'


def test_rtl_language_detection_accepts_arabic_and_hebrew_variants():
    assert is_rtl_language('ar')
    assert is_rtl_language('ar-SA')
    assert is_rtl_language('he_IL')
    assert not is_rtl_language('en-US')


def test_layout_direction_preference_and_application(monkeypatch, tmp_path):
    direction_file = str(tmp_path / 'layout-direction.json')
    monkeypatch.setattr('unifile.i18n._LAYOUT_DIRECTION_FILE', direction_file)
    monkeypatch.delenv('UNIFILE_LAYOUT_DIRECTION', raising=False)

    assert get_layout_direction_preference() == 'auto'
    assert effective_layout_direction('ar') == 'rtl'
    set_layout_direction_preference('ltr')
    assert get_layout_direction_preference() == 'ltr'
    assert effective_layout_direction('ar') == 'ltr'

    class FakeApplication:
        direction = None

        def setLayoutDirection(self, value):
            self.direction = value

    from PyQt6.QtCore import Qt

    app = FakeApplication()
    assert apply_layout_direction(app, 'ar') == 'ltr'
    assert app.direction == Qt.LayoutDirection.LeftToRight
    set_layout_direction_preference('rtl')
    assert apply_layout_direction(app, 'en') == 'rtl'
    assert app.direction == Qt.LayoutDirection.RightToLeft


def test_available_languages_includes_english(monkeypatch, tmp_path):
    monkeypatch.setattr('unifile.i18n._TRANSLATIONS_DIR', str(tmp_path))
    langs = get_available_languages()
    assert 'en' in langs


def test_available_languages_detects_qm_files(monkeypatch, tmp_path):
    (tmp_path / 'fr.qm').write_bytes(b'')
    (tmp_path / 'de.qm').write_bytes(b'')
    (tmp_path / 'not_a_lang.txt').write_text('x')
    monkeypatch.setattr('unifile.i18n._TRANSLATIONS_DIR', str(tmp_path))
    langs = get_available_languages()
    assert 'en' in langs
    assert 'fr' in langs
    assert 'de' in langs
    assert 'not_a_lang' not in langs


def test_install_translator_returns_false_for_english(monkeypatch, tmp_path):
    monkeypatch.setattr('unifile.i18n._LANG_FILE', str(tmp_path / 'lang.json'))
    monkeypatch.delenv('UNIFILE_LANG', raising=False)
    assert install_translator(None) is False


def test_install_translator_returns_false_for_missing_qm(monkeypatch, tmp_path):
    monkeypatch.setattr('unifile.i18n._LANG_FILE', str(tmp_path / 'lang.json'))
    monkeypatch.setattr('unifile.i18n._TRANSLATIONS_DIR', str(tmp_path))
    monkeypatch.setenv('UNIFILE_LANG', 'ja')
    assert install_translator(None) is False


def test_translations_dir_exists():
    from unifile.i18n import _TRANSLATIONS_DIR
    assert os.path.isdir(_TRANSLATIONS_DIR)
