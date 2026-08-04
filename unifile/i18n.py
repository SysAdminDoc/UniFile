"""UniFile — Internationalization (i18n) infrastructure.

Provides locale loading, language switching, and translation helpers.
Uses Qt's built-in translation system (QTranslator + .qm files).

Translation catalogs live in unifile/translations/<lang>.qm. An English
baseline .ts file can be generated with:

    pylupdate6 unifile/ -ts unifile/translations/en.ts

Locale switching is testable without editing source — set the
UNIFILE_LANG environment variable or change the language in Settings.
"""
import os

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

_LANG_FILE = os.path.join(_APP_DATA_DIR, 'language.json')
_LAYOUT_DIRECTION_FILE = os.path.join(_APP_DATA_DIR, 'layout-direction.json')
_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), 'translations')
os.makedirs(_TRANSLATIONS_DIR, exist_ok=True)

_current_translator = None

RTL_LANGUAGE_CODES = frozenset({'ar', 'fa', 'he', 'iw', 'ku', 'ps', 'sd', 'ug', 'ur', 'yi'})
LAYOUT_DIRECTION_PREFERENCES = ('auto', 'ltr', 'rtl')


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


def get_current_language() -> str:
    """Return the currently configured language code."""
    env_lang = os.environ.get('UNIFILE_LANG', '').strip()
    if env_lang:
        return env_lang
    data = load_json_safe(_LANG_FILE, {}, expected_type=dict)
    return data.get('language', 'en')


def set_language(lang_code: str) -> None:
    """Save the language preference."""
    save_json_safe(_LANG_FILE, {'language': lang_code})


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


def install_translator(app) -> bool:
    """Install a QTranslator for the current language into the QApplication.

    Returns True if a translation was loaded, False if using English
    (no translation needed) or if the .qm file is missing.
    """
    global _current_translator
    lang = get_current_language()
    if lang == 'en':
        if _current_translator and app:
            app.removeTranslator(_current_translator)
            _current_translator = None
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
