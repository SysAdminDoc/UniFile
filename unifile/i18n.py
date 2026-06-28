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
_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), 'translations')
os.makedirs(_TRANSLATIONS_DIR, exist_ok=True)

_current_translator = None


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
