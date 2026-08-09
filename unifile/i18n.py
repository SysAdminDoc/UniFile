"""UniFile — Internationalization (i18n) infrastructure.

Provides locale loading, language switching, translation helpers, and catalog
validation.  Qt's built-in translation system (``QTranslator`` + ``.qm``
files) is used so the same catalogs work in the source checkout and frozen
PyInstaller builds.

The source catalog is regenerated with ``make translations`` (or
``python tools/i18n_catalog.py all``).  The checked-in English ``.ts`` file
is intentionally complete, while non-English catalogs must translate every
safety-critical source string listed below.  Validation catches unfinished
messages, placeholder loss, missing plural forms, and suspiciously long
labels before release.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

_LANG_FILE = os.path.join(_APP_DATA_DIR, 'language.json')
_LAYOUT_DIRECTION_FILE = os.path.join(_APP_DATA_DIR, 'layout-direction.json')
_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), 'translations')
os.makedirs(_TRANSLATIONS_DIR, exist_ok=True)

_current_translator = None

RTL_LANGUAGE_CODES = frozenset({'ar', 'fa', 'he', 'iw', 'ku', 'ps', 'sd', 'ug', 'ur', 'yi'})
LAYOUT_DIRECTION_PREFERENCES = ('auto', 'ltr', 'rtl')
TRANSLATION_CONTEXT = 'UniFile'

# Keep this list small and deliberate.  It is the release-gated surface for
# destructive/review actions and locale controls.  Less critical copy can be
# migrated incrementally without allowing an untranslated safety action to
# ship unnoticed.
TRANSLATION_SOURCE_STRINGS = (
    'Scan',
    'Apply Changes',
    'Preview Plan',
    'Undo History',
    'Repeat Last Scan',
    'Export CSV',
    'Export HTML',
    'Open Folder',
    'Watch Mode',
    'Scan, Categorize & Rename',
    'Apply Folder Changes',
    'Preview Destinations',
    'Open Output',
    'Scan Files',
    'Organize Files',
    'Preview Moves',
    'UniFile Settings',
    'Language',
    'Language…',
    'Language Changed',
    'Select UI language',
    "Language set to '%1'. New dialogs use the selected locale; restart UniFile to refresh all open views.",
    'Layout Direction',
    'Layout Direction…',
    'Choose how UniFile lays out text and controls:',
    'Protected Paths',
    'Protected Paths…',
    'Accessibility',
    'Keyboard Shortcuts…',
    'Plugin Manager…',
    'Backup Tag Library…',
    'Restore Tag Library…',
    'Export Diagnostics…',
    'Done',
    'Found %n file(s)',
)
TRANSLATION_CRITICAL_SOURCES = frozenset(TRANSLATION_SOURCE_STRINGS)
TRANSLATION_PLURAL_SOURCES = frozenset({'Found %n file(s)'})
_PLACEHOLDER_RE = re.compile(r'%n|%\d+')


def _pylupdate_source_markers() -> tuple[str, ...]:
    """Expose literal Qt calls for ``pylupdate6`` extraction.

    Runtime code usually passes a variable to :func:`translate`, which is
    safer for shared UI helpers but cannot be discovered by pylupdate.  These
    intentionally unused calls are the authoritative extraction markers.
    """
    from PyQt6.QtCore import QCoreApplication

    return tuple(
        (
            QCoreApplication.translate('UniFile', 'Scan'),
            QCoreApplication.translate('UniFile', 'Apply Changes'),
            QCoreApplication.translate('UniFile', 'Preview Plan'),
            QCoreApplication.translate('UniFile', 'Undo History'),
            QCoreApplication.translate('UniFile', 'Repeat Last Scan'),
            QCoreApplication.translate('UniFile', 'Export CSV'),
            QCoreApplication.translate('UniFile', 'Export HTML'),
            QCoreApplication.translate('UniFile', 'Open Folder'),
            QCoreApplication.translate('UniFile', 'Watch Mode'),
            QCoreApplication.translate('UniFile', 'Scan, Categorize & Rename'),
            QCoreApplication.translate('UniFile', 'Apply Folder Changes'),
            QCoreApplication.translate('UniFile', 'Preview Destinations'),
            QCoreApplication.translate('UniFile', 'Open Output'),
            QCoreApplication.translate('UniFile', 'Scan Files'),
            QCoreApplication.translate('UniFile', 'Organize Files'),
            QCoreApplication.translate('UniFile', 'Preview Moves'),
            QCoreApplication.translate('UniFile', 'UniFile Settings'),
            QCoreApplication.translate('UniFile', 'Language'),
            QCoreApplication.translate('UniFile', 'Language…'),
            QCoreApplication.translate('UniFile', 'Language Changed'),
            QCoreApplication.translate('UniFile', 'Select UI language'),
            QCoreApplication.translate(
                'UniFile',
                "Language set to '%1'. New dialogs use the selected locale; restart UniFile to refresh all open views.",
            ),
            QCoreApplication.translate('UniFile', 'Layout Direction'),
            QCoreApplication.translate('UniFile', 'Layout Direction…'),
            QCoreApplication.translate('UniFile', 'Choose how UniFile lays out text and controls:'),
            QCoreApplication.translate('UniFile', 'Protected Paths'),
            QCoreApplication.translate('UniFile', 'Protected Paths…'),
            QCoreApplication.translate('UniFile', 'Accessibility'),
            QCoreApplication.translate('UniFile', 'Keyboard Shortcuts…'),
            QCoreApplication.translate('UniFile', 'Plugin Manager…'),
            QCoreApplication.translate('UniFile', 'Backup Tag Library…'),
            QCoreApplication.translate('UniFile', 'Restore Tag Library…'),
            QCoreApplication.translate('UniFile', 'Export Diagnostics…'),
            QCoreApplication.translate('UniFile', 'Done'),
            QCoreApplication.translate('UniFile', 'Found %n file(s)', '', 1),
        )
    )


def get_available_languages() -> list[str]:
    """Return a list of available language codes based on .qm files."""
    langs = ['en']
    if os.path.isdir(_TRANSLATIONS_DIR):
        for f in os.listdir(_TRANSLATIONS_DIR):
            if f.endswith('.qm'):
                code = f[:-3]
                if code not in langs:
                    langs.append(code)
    return sorted(langs)


def translate(source: str, *, context: str = TRANSLATION_CONTEXT, n: int | None = None) -> str:
    """Translate a source string, retaining English when no catalog is active."""
    from PyQt6.QtCore import QCoreApplication

    if n is None:
        return QCoreApplication.translate(context, source)
    return QCoreApplication.translate(context, source, '', n)


def format_file_count(count: int) -> str:
    """Return a locale-aware singular/plural file-count label."""
    value = max(0, int(count))
    translated = translate('Found %n file(s)', n=value)
    # Qt returns the source text unchanged when no translator is installed;
    # normalize the English fallback so it still has proper plural grammar.
    if translated == f'Found {value} file(s)':
        return f'Found {value} file' if value == 1 else f'Found {value} files'
    return translated


def get_current_language() -> str:
    """Return the currently configured language code."""
    env_lang = os.environ.get('UNIFILE_LANG', '').strip()
    if env_lang:
        return env_lang
    data = load_json_safe(_LANG_FILE, {}, expected_type=dict)
    return data.get('language', 'en')


def set_language(lang_code: str) -> None:
    """Save the language preference."""
    save_json_safe(_LANG_FILE, {'language': str(lang_code or '').strip() or 'en'})


def is_rtl_language(lang_code: str | None) -> bool:
    """Return whether a BCP-47 language code normally uses right-to-left text."""
    code = str(lang_code or '').strip().lower().replace('_', '-')
    return code.split('-', 1)[0] in RTL_LANGUAGE_CODES


def get_layout_direction_preference() -> str:
    """Return ``auto``, ``ltr``, or ``rtl`` for the application layout."""
    env_value = os.environ.get('UNIFILE_LAYOUT_DIRECTION', '').strip().lower()
    if env_value in LAYOUT_DIRECTION_PREFERENCES:
        return env_value
    data = load_json_safe(_LAYOUT_DIRECTION_FILE, {}, expected_type=dict)
    value = str(data.get('direction', 'auto')).strip().lower()
    return value if value in LAYOUT_DIRECTION_PREFERENCES else 'auto'


def set_layout_direction_preference(direction: str) -> None:
    """Persist a layout direction preference, falling back to automatic mode."""
    value = str(direction or '').strip().lower()
    if value not in LAYOUT_DIRECTION_PREFERENCES:
        value = 'auto'
    save_json_safe(_LAYOUT_DIRECTION_FILE, {'direction': value})


def effective_layout_direction(
    lang_code: str | None = None,
    preference: str | None = None,
) -> str:
    """Resolve the effective direction without requiring a QApplication."""
    value = str(preference or get_layout_direction_preference()).strip().lower()
    if value == 'auto':
        value = 'rtl' if is_rtl_language(lang_code or get_current_language()) else 'ltr'
    return value if value in ('ltr', 'rtl') else 'ltr'


def apply_layout_direction(app, lang_code: str | None = None) -> str:
    """Apply the configured BiDi direction to a QApplication and return it."""
    from PyQt6.QtCore import Qt

    direction = effective_layout_direction(lang_code)
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft
        if direction == 'rtl'
        else Qt.LayoutDirection.LeftToRight
    )
    return direction


def install_translator(app, lang_code: str | None = None) -> bool:
    """Install a QTranslator for the current language into the QApplication.

    Returns True if a translation was loaded, False if using English
    (no translation needed) or if the .qm file is missing.
    """
    global _current_translator
    lang = str(lang_code or get_current_language()).strip() or 'en'
    if lang == 'en':
        if _current_translator:
            if app:
                app.removeTranslator(_current_translator)
            _current_translator = None
        return False

    if app is None:
        return False

    qm_path = os.path.join(_TRANSLATIONS_DIR, f'{lang}.qm')
    if not os.path.isfile(qm_path):
        return False

    try:
        from PyQt6.QtCore import QTranslator
        translator = QTranslator(app)
        if translator.load(qm_path):
            if _current_translator:
                app.removeTranslator(_current_translator)
            app.installTranslator(translator)
            _current_translator = translator
            return True
    except Exception:
        pass
    return False


def switch_language(app, lang_code: str) -> bool:
    """Install ``lang_code``, persist it, and apply its BiDi direction.

    English is the built-in fallback and therefore returns ``True`` even
    though no QTranslator is needed.  Unknown or unavailable catalogs leave
    the current language untouched and return ``False``.
    """
    lang = str(lang_code or '').strip().lower().replace('_', '-')
    available = get_available_languages()
    if lang != 'en' and lang not in available:
        return False
    if lang != 'en' and not os.path.isfile(os.path.join(_TRANSLATIONS_DIR, f'{lang}.qm')):
        return False
    if lang == 'en':
        install_translator(app, lang)
    elif not install_translator(app, lang):
        return False
    set_language(lang)
    apply_layout_direction(app, lang)
    return True


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ''
    return ''.join(element.itertext()).strip()


def _catalog_messages(path: str | os.PathLike[str]) -> tuple[str, dict[str, tuple[bool, list[str]]]]:
    """Read a TS catalog as ``(language, source -> (numerus, translations))``."""
    root = ET.parse(path).getroot()
    messages: dict[str, tuple[bool, list[str]]] = {}
    for context in root.findall('context'):
        if _element_text(context.find('name')) != TRANSLATION_CONTEXT:
            continue
        for message in context.findall('message'):
            source = _element_text(message.find('source'))
            if not source:
                continue
            translation = message.find('translation')
            if translation is None:
                values: list[str] = []
            else:
                forms = translation.findall('numerusform')
                values = [_element_text(form) for form in forms] if forms else [_element_text(translation)]
                if translation.get('type') == 'unfinished':
                    values = []
            messages[source] = (message.get('numerus') == 'yes', values)
    return str(root.get('language') or ''), messages


def validate_translation_catalog(
    path: str | os.PathLike[str],
    *,
    required_sources: tuple[str, ...] = TRANSLATION_SOURCE_STRINGS,
    critical_sources: frozenset[str] = TRANSLATION_CRITICAL_SOURCES,
    require_distinct_critical: bool = False,
) -> list[str]:
    """Return actionable validation errors for one Qt ``.ts`` catalog."""
    catalog_path = Path(path)
    if not catalog_path.is_file():
        return [f'{catalog_path}: catalog is missing']
    try:
        language, messages = _catalog_messages(catalog_path)
    except (ET.ParseError, OSError) as exc:
        return [f'{catalog_path}: cannot parse catalog: {exc}']

    errors: list[str] = []
    if not language:
        errors.append(f'{catalog_path}: missing TS language attribute')
    for source in required_sources:
        record = messages.get(source)
        if record is None:
            errors.append(f'{catalog_path}: missing source: {source}')
            continue
        is_plural, values = record
        if source in TRANSLATION_PLURAL_SOURCES and not is_plural:
            errors.append(f'{catalog_path}: plural source is not marked numerus: {source}')
        if source not in TRANSLATION_PLURAL_SOURCES and is_plural:
            errors.append(f'{catalog_path}: non-plural source is marked numerus: {source}')
        expected_forms = 2 if source in TRANSLATION_PLURAL_SOURCES else 1
        if len(values) < expected_forms or any(not value for value in values):
            errors.append(f'{catalog_path}: unfinished or empty translation: {source}')
            continue
        source_placeholders = sorted(_PLACEHOLDER_RE.findall(source))
        for value in values:
            if sorted(_PLACEHOLDER_RE.findall(value)) != source_placeholders:
                errors.append(f'{catalog_path}: placeholder mismatch: {source}')
            if len(value) > max(64, len(source) * 4):
                errors.append(f'{catalog_path}: suspiciously long/truncated label: {source}')
            if (
                language.lower().split('-', 1)[0] != 'en'
                and source in critical_sources
                and require_distinct_critical
                and value.strip() == source.strip()
            ):
                errors.append(f'{catalog_path}: untranslated critical source: {source}')
    return errors
