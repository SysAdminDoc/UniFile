"""Tests for the i18n infrastructure (locale loading, language switching)."""
import os

import pytest

from unifile.i18n import (
    apply_layout_direction,
    effective_layout_direction,
    format_file_count,
    get_available_languages,
    get_current_language,
    get_layout_direction_preference,
    install_translator,
    is_rtl_language,
    set_language,
    set_layout_direction_preference,
    switch_language,
    translate,
    validate_translation_catalog,
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


def test_checked_in_catalogs_cover_every_safety_critical_source():
    from unifile.i18n import _TRANSLATIONS_DIR

    english_errors = validate_translation_catalog(
        os.path.join(_TRANSLATIONS_DIR, 'en.ts'),
    )
    spanish_errors = validate_translation_catalog(
        os.path.join(_TRANSLATIONS_DIR, 'es.ts'),
        require_distinct_critical=True,
    )
    assert english_errors == []
    assert spanish_errors == []
    assert os.path.isfile(os.path.join(_TRANSLATIONS_DIR, 'es.qm'))


def test_catalog_validation_reports_untranslated_labels_and_placeholder_loss(tmp_path):
    catalog = tmp_path / 'bad.ts'
    catalog.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="es">
<context><name>UniFile</name>
<message><source>Scan</source><translation>Scan</translation></message>
<message numerus="yes"><source>Found %n file(s)</source>
<translation><numerusform>Mucho texto sin %n</numerusform><numerusform>Mucho texto sin %1</numerusform></translation></message>
</context></TS>''',
        encoding='utf-8',
    )
    errors = validate_translation_catalog(
        catalog,
        required_sources=('Scan', 'Found %n file(s)'),
        critical_sources=frozenset({'Scan'}),
        require_distinct_critical=True,
    )
    assert any('untranslated critical source: Scan' in error for error in errors)
    assert any('placeholder mismatch: Found %n file(s)' in error for error in errors)


def test_runtime_spanish_catalog_switches_labels_and_plural_forms(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr('unifile.i18n._LANG_FILE', str(tmp_path / 'language.json'))
    monkeypatch.delenv('UNIFILE_LANG', raising=False)
    try:
        assert switch_language(qapp, 'es') is True
        assert translate('Scan') == 'Escanear'
        assert format_file_count(1) == 'Se encontró 1 archivo'
        assert format_file_count(3) == 'Se encontraron 3 archivos'
        assert apply_layout_direction(qapp, 'es') == 'ltr'
        assert switch_language(qapp, 'en') is True
        assert translate('Scan') == 'Scan'
        assert format_file_count(2) == 'Found 2 files'
    finally:
        switch_language(qapp, 'en')


def test_main_window_retranslates_safety_actions_at_runtime(qapp, qtbot, monkeypatch, tmp_path):
    from unifile.main_window import UniFile

    monkeypatch.setattr('unifile.i18n._LANG_FILE', str(tmp_path / 'language.json'))
    monkeypatch.delenv('UNIFILE_LANG', raising=False)
    window = UniFile()
    qtbot.addWidget(window)
    try:
        assert switch_language(qapp, 'es') is True
        qapp.processEvents()
        assert window.btn_undo.text() == 'Historial de deshacer'
        assert window.btn_replay.text() == 'Repetir el último escaneo'
        assert window.btn_export.text() == 'Exportar CSV'
        assert window.btn_watch.text() == 'Modo vigilancia'
    finally:
        switch_language(qapp, 'en')
