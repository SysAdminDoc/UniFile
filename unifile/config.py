"""UniFile — Configuration, paths, thresholds, themes, and protection."""
import os, sys, re, json, shutil, time
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd()

# ── App Data Directory ────────────────────────────────────────────────────────
# Portable mode: set UNIFILE_PORTABLE=1 env var (or pass --portable to run.py)
# to store all data in ./unifile-data/ beside the script instead of %APPDATA%.
if os.environ.get('UNIFILE_PORTABLE', '').strip() == '1':
    _APP_DATA_DIR = os.path.join(_SCRIPT_DIR, 'unifile-data')
else:
    _APP_DATA_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')),
                                  'UniFile')
os.makedirs(_APP_DATA_DIR, exist_ok=True)

# One-time migration: move legacy files from script dir into _APP_DATA_DIR
_MIGRATE_FILES = [
    'corrections.json', 'classification_cache.db', 'custom_categories.json',
    'envato_api_key.txt', 'ollama_settings.json', 'undo_log.json',
    'move_log.csv', 'crash.log',
]
for _mf in _MIGRATE_FILES:
    _old = os.path.join(_SCRIPT_DIR, _mf)
    _new = os.path.join(_APP_DATA_DIR, _mf)
    if os.path.exists(_old) and not os.path.exists(_new):
        try:
            shutil.move(_old, _new)
        except Exception:
            pass
del _mf, _old, _new

# ── Confidence Thresholds ─────────────────────────────────────────────────────
CONF_HIGH   = 80   # green — high confidence
CONF_MEDIUM = 50   # yellow — medium confidence (below = red)
CONF_FUZZY_CAP = 80   # max confidence for fuzzy-match results


# ── Dark Theme ─────────────────────────────────────────────────────────────────
DARK_STYLE = ""

# ── Theme System ──────────────────────────────────────────────────────────────
# Each theme is a dict of color tokens → hex values. _build_theme_qss() renders
# them into a full QSS stylesheet. DARK_STYLE above is the "Steam Dark" default.

def _build_theme_qss(t: dict) -> str:
    """Generate a full QSS stylesheet from a theme color token dict."""
    return f"""
QMainWindow, QWidget {{
    background-color: {t['bg']}; color: {t['fg']};
    font-family: 'Segoe UI';
    font-size: 13px;
    selection-background-color: {t['accent']};
    selection-color: #ffffff;
}}
QDialog {{ background-color: {t['bg']}; }}
QStatusBar {{ background: {t['header_bg']}; border-top: 1px solid {t['btn_bg']}; }}
QLabel {{ background: transparent; }}
QPushButton {{
    background-color: {t['btn_bg']}; color: {t['fg']};
    border: 1px solid {t['border']};
    min-height: 36px;
    padding: 0 16px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 12px;
    outline: none;
}}
QPushButton:hover {{ background-color: {t['btn_hover']}; color: {t['fg_bright']}; border-color: {t['border_hover']}; }}
QPushButton:pressed {{ background-color: {t['btn_pressed']}; }}
QPushButton:focus {{ border-color: {t['accent']}; }}
QPushButton:disabled {{ background-color: {t['bg_alt']}; color: {t['disabled']}; border-color: {t['btn_bg']}; }}
QPushButton:checked {{ background-color: {t['selection']}; color: {t['fg_bright']}; border-color: {t['accent']}; }}
QPushButton[class="primary"] {{
    background-color: {t['accent']}; color: #ffffff;
    border: 1px solid {t['accent']};
    min-height: 40px;
    padding: 0 18px;
    font-weight: 700;
    font-size: 13px;
}}
QPushButton[class="primary"]:hover {{ background-color: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
QPushButton[class="primary"]:pressed {{ background-color: {t['accent_pressed']}; }}
QPushButton[class="primary"]:disabled {{ background-color: {t['btn_bg']}; color: {t['disabled']}; }}
QPushButton[class="apply"] {{
    background-color: {t['green']}; color: #ffffff;
    border: 1px solid {t['green']};
    min-height: 40px;
    padding: 0 18px;
    font-weight: 700;
    font-size: 13px;
}}
QPushButton[class="apply"]:hover {{ background-color: {t['green_hover']}; border-color: {t['green_hover']}; }}
QPushButton[class="apply"]:pressed {{ background-color: {t['green_pressed']}; }}
QPushButton[class="apply"]:disabled {{ background-color: {t['btn_bg']}; color: {t['disabled']}; }}
QPushButton[class="success"] {{
    background-color: {t['green']}; color: #ffffff;
    border: 1px solid {t['green']};
    min-height: 34px;
    padding: 0 16px;
    font-weight: 700;
}}
QPushButton[class="success"]:hover {{ background-color: {t['green_hover']}; border-color: {t['green_hover']}; }}
QPushButton[class="success"]:pressed {{ background-color: {t['green_pressed']}; }}
QPushButton[class="danger"] {{
    background-color: #3a1f25;
    color: #ffb4c0;
    border: 1px solid #6e3241;
    min-height: 34px;
    padding: 0 16px;
    font-weight: 700;
}}
QPushButton[class="danger"]:hover {{ background-color: #4a2730; color: #ffd5db; border-color: #8c4054; }}
QPushButton[class="danger"]:pressed {{ background-color: #341b21; }}
QPushButton[class="toolbar"] {{
    background-color: transparent; color: {t['muted']};
    border: 1px solid transparent;
    min-height: 30px;
    padding: 0 12px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 9px;
}}
QPushButton[class="toolbar"]:hover {{ background-color: {t['bg_alt']}; color: {t['fg']}; border-color: {t['border']}; }}
QPushButton[class="toolbar"]:disabled {{ color: {t['border']}; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {t['input_bg']}; color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 12px;
    padding: 8px 12px;
    font-size: 13px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t['accent']};
}}
QLineEdit:read-only {{ color: {t['muted']}; background-color: {t['bg_alt']}; }}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {t['disabled']};
    background-color: {t['bg_alt']};
    border-color: {t['btn_bg']};
}}
QLineEdit, QTextEdit, QPlainTextEdit {{
    selection-background-color: {t['selection']};
}}
QLineEdit {{
    min-height: 20px;
    placeholder-text-color: {t['muted']};
}}
QComboBox {{
    padding: 7px 12px;
    min-height: 30px;
}}
QComboBox:hover {{ border-color: {t['border_hover']}; }}
QComboBox::drop-down {{ border: none; width: 30px; }}
QComboBox::down-arrow {{
    image: none; border-left: 5px solid transparent;
    border-right: 5px solid transparent; border-top: 5px solid {t['muted']}; margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {t['input_bg']}; color: {t['fg']}; border: 1px solid {t['border']};
    selection-background-color: {t['selection']}; selection-color: #ffffff;
    outline: none; padding: 6px; border-radius: 10px;
}}
QSpinBox {{
    padding: 6px 10px;
    font-size: 12px;
}}
QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {t['border_hover']}; }}
QTableWidget, QTreeWidget, QListWidget {{
    background-color: {t['input_bg']}; alternate-background-color: {t['bg_alt']};
    color: {t['fg']}; border: 1px solid {t['border']}; border-radius: 12px;
    gridline-color: transparent; font-size: 12px; outline: none;
    selection-background-color: {t['selection']}; selection-color: {t['fg_bright']};
}}
QTableWidget::item, QTreeWidget::item, QListWidget::item {{
    padding: 7px 10px;
}}
QTableWidget::item {{
    border-bottom: 1px solid {t['btn_bg']};
}}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {t['selection']};
}}
QTableWidget::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {{
    background-color: {t['row_hover']};
}}
QHeaderView::section {{
    background-color: {t['header_bg']}; color: {t['muted']};
    font-weight: 700; font-size: 11px; letter-spacing: 0.2px;
    padding: 10px 12px; border: none;
    border-bottom: 1px solid {t['btn_bg']}; border-right: 1px solid {t['btn_bg']};
}}
QHeaderView::section:hover {{ color: {t['fg']}; }}
QHeaderView::section:first {{ padding-left: 16px; }}
QTableCornerButton::section {{
    background-color: {t['header_bg']};
    border: none;
    border-bottom: 1px solid {t['btn_bg']};
    border-right: 1px solid {t['btn_bg']};
}}
QAbstractScrollArea {{
    background: transparent;
    border: none;
}}
QFrame[class="card"], QWidget[class="card"] {{
    background: {t['bg_alt']};
    border: 1px solid {t['border']};
    border-radius: 16px;
}}
QTabWidget::pane {{
    border: 1px solid {t['border']};
    border-radius: 14px;
    background: {t['bg_alt']};
    top: -1px;
}}
QTabBar::tab {{
    background: {t['header_bg']};
    color: {t['muted']};
    padding: 9px 16px;
    border: 1px solid transparent;
    border-radius: 12px;
    margin-right: 6px;
    font-size: 11px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {t['selection']};
    color: {t['fg_bright']};
    border-color: {t['border']};
}}
QTabBar::tab:hover {{
    color: {t['fg']};
}}
QScrollBar:vertical {{ background: transparent; width: 12px; border: none; margin: 6px 0; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 6px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['border_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; border: none; margin: 0 6px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 6px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['border_hover']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QCheckBox {{ spacing: 8px; color: {t['fg']}; min-height: 22px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 6px;
    border: 2px solid {t['border']}; background: {t['input_bg']};
}}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
QCheckBox::indicator:unchecked:hover {{ border-color: {t['border_hover']}; }}
QCheckBox:disabled {{ color: {t['disabled']}; }}
QCheckBox::indicator:disabled {{ background: {t['bg_alt']}; border-color: {t['btn_bg']}; }}
QSlider::groove:horizontal {{ background: {t['btn_bg']}; height: 6px; border-radius: 999px; }}
QSlider::sub-page:horizontal {{ background: {t['selection']}; border-radius: 999px; }}
QSlider::handle:horizontal {{
    background: {t['accent']};
    width: 16px; height: 16px; margin: -5px 0;
    border-radius: 8px; border: 2px solid {t['header_bg']};
}}
QSlider::handle:horizontal:hover {{ background: {t['accent_hover']}; }}
QMenuBar {{
    background-color: {t['header_bg']};
    color: {t['muted']};
    border-bottom: 1px solid {t['btn_bg']};
    padding: 4px 6px;
    font-size: 12px;
}}
QMenuBar::item {{ padding: 6px 12px; border-radius: 8px; }}
QMenuBar::item:selected {{ background-color: {t['bg_alt']}; color: {t['fg']}; }}
QMenu {{
    background-color: {t['input_bg']}; color: {t['fg']};
    border: 1px solid {t['border']}; border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 8px 24px 8px 16px; border-radius: 8px; }}
QMenu::item:selected {{ background-color: {t['selection']}; }}
QMenu::separator {{ height: 1px; background: {t['btn_bg']}; margin: 4px 8px; }}
QGroupBox {{
    background-color: {t['bg_alt']};
    border: 1px solid {t['border']};
    border-radius: 12px;
    margin-top: 12px;
    padding: 14px 12px 12px 12px;
    font-weight: 700;
    font-size: 11px;
    color: {t['muted']};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 8px; color: {t['muted']}; }}
QToolTip {{
    background-color: {t['header_bg']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
}}
QProgressBar {{
    background-color: {t['bg_alt']};
    border: 1px solid {t['border']};
    border-radius: 999px;
    min-height: 10px;
    text-align: center;
    padding: 1px;
}}
QProgressBar::chunk {{ background-color: {t['accent']}; border-radius: 999px; }}
QSplitter::handle {{
    background: {t['btn_bg']};
}}
QSplitter::handle:hover {{
    background: {t['border_hover']};
}}
"""

# ── Theme Palettes ───────────────────────────────────────────────────────────
THEME_STEAM_DARK = {
    'name': 'Steam Dark', 'sidebar_bg': '#080e16', 'sidebar_brand': '#060b12',
    'sidebar_border': '#1b2838', 'sidebar_section': '#3a4f65',
    'sidebar_btn': '#7a8a9a', 'sidebar_btn_hover_bg': '#0d1926',
    'sidebar_btn_hover_border': '#1e3a5c', 'sidebar_btn_active_bg': '#0f1f30',
    'sidebar_btn_active_fg': '#4fc3f7', 'sidebar_btn_active_border': '#1a6bc4',
    'sidebar_profile_bg': '#0d1520', 'sidebar_profile_fg': '#a78bfa',
    'sidebar_profile_border': '#1e3050',
    'bg': '#0f1923', 'bg_alt': '#121e2b', 'fg': '#c5cdd8', 'fg_bright': '#e0e6ec',
    'btn_bg': '#1b2838', 'btn_fg': '#8f98a0', 'btn_hover': '#1e3a5f',
    'btn_pressed': '#254a73', 'border': '#2a3f5f', 'border_hover': '#3d6a9e',
    'input_bg': '#141d26', 'header_bg': '#0a1219',
    'accent': '#1a6bc4', 'accent_hover': '#2080e0', 'accent_pressed': '#1560b0',
    'green': '#1b8553', 'green_hover': '#22a366', 'green_pressed': '#167045',
    'selection': '#1a3a5c', 'row_hover': '#152535',
    'muted': '#6b7785', 'disabled': '#3a4654',
}

THEME_CATPPUCCIN_MOCHA = {
    'name': 'Catppuccin Mocha', 'sidebar_bg': '#11111b', 'sidebar_brand': '#0e0e18',
    'sidebar_border': '#313244', 'sidebar_section': '#585b70',
    'sidebar_btn': '#a6adc8', 'sidebar_btn_hover_bg': '#181825',
    'sidebar_btn_hover_border': '#45475a', 'sidebar_btn_active_bg': '#1e1e2e',
    'sidebar_btn_active_fg': '#89b4fa', 'sidebar_btn_active_border': '#89b4fa',
    'sidebar_profile_bg': '#181825', 'sidebar_profile_fg': '#cba6f7',
    'sidebar_profile_border': '#45475a',
    'bg': '#1e1e2e', 'bg_alt': '#181825', 'fg': '#cdd6f4', 'fg_bright': '#e4e8f4',
    'btn_bg': '#313244', 'btn_fg': '#a6adc8', 'btn_hover': '#45475a',
    'btn_pressed': '#585b70', 'border': '#45475a', 'border_hover': '#585b70',
    'input_bg': '#181825', 'header_bg': '#11111b',
    'accent': '#89b4fa', 'accent_hover': '#a6c8ff', 'accent_pressed': '#6d9de8',
    'green': '#a6e3a1', 'green_hover': '#b8f0b4', 'green_pressed': '#8ad085',
    'selection': '#313244', 'row_hover': '#252536',
    'muted': '#6c7086', 'disabled': '#45475a',
}

THEME_OLED_BLACK = {
    'name': 'OLED Black', 'sidebar_bg': '#000000', 'sidebar_brand': '#000000',
    'sidebar_border': '#1a1a1a', 'sidebar_section': '#444444',
    'sidebar_btn': '#888888', 'sidebar_btn_hover_bg': '#0a0a0a',
    'sidebar_btn_hover_border': '#333333', 'sidebar_btn_active_bg': '#111111',
    'sidebar_btn_active_fg': '#00d4ff', 'sidebar_btn_active_border': '#0099cc',
    'sidebar_profile_bg': '#080808', 'sidebar_profile_fg': '#b388ff',
    'sidebar_profile_border': '#222222',
    'bg': '#000000', 'bg_alt': '#0a0a0a', 'fg': '#d0d0d0', 'fg_bright': '#f0f0f0',
    'btn_bg': '#1a1a1a', 'btn_fg': '#909090', 'btn_hover': '#252525',
    'btn_pressed': '#333333', 'border': '#2a2a2a', 'border_hover': '#444444',
    'input_bg': '#0d0d0d', 'header_bg': '#000000',
    'accent': '#0099cc', 'accent_hover': '#00bbee', 'accent_pressed': '#007799',
    'green': '#00aa55', 'green_hover': '#00cc66', 'green_pressed': '#008844',
    'selection': '#1a1a2e', 'row_hover': '#111118',
    'muted': '#666666', 'disabled': '#333333',
}

THEME_GITHUB_DARK = {
    'name': 'GitHub Dark', 'sidebar_bg': '#0d1117', 'sidebar_brand': '#090c10',
    'sidebar_border': '#21262d', 'sidebar_section': '#484f58',
    'sidebar_btn': '#8b949e', 'sidebar_btn_hover_bg': '#161b22',
    'sidebar_btn_hover_border': '#30363d', 'sidebar_btn_active_bg': '#1a2030',
    'sidebar_btn_active_fg': '#58a6ff', 'sidebar_btn_active_border': '#1f6feb',
    'sidebar_profile_bg': '#0d1117', 'sidebar_profile_fg': '#d2a8ff',
    'sidebar_profile_border': '#30363d',
    'bg': '#0d1117', 'bg_alt': '#161b22', 'fg': '#c9d1d9', 'fg_bright': '#e6edf3',
    'btn_bg': '#21262d', 'btn_fg': '#8b949e', 'btn_hover': '#30363d',
    'btn_pressed': '#3d444d', 'border': '#30363d', 'border_hover': '#484f58',
    'input_bg': '#0d1117', 'header_bg': '#010409',
    'accent': '#1f6feb', 'accent_hover': '#388bfd', 'accent_pressed': '#1a5cc8',
    'green': '#238636', 'green_hover': '#2ea043', 'green_pressed': '#1a7f37',
    'selection': '#1a2332', 'row_hover': '#131920',
    'muted': '#484f58', 'disabled': '#30363d',
}

THEME_NORD = {
    'name': 'Nord', 'sidebar_bg': '#242933', 'sidebar_brand': '#1e222b',
    'sidebar_border': '#3b4252', 'sidebar_section': '#616e88',
    'sidebar_btn': '#b0bec5', 'sidebar_btn_hover_bg': '#2e3440',
    'sidebar_btn_hover_border': '#434c5e', 'sidebar_btn_active_bg': '#3b4252',
    'sidebar_btn_active_fg': '#88c0d0', 'sidebar_btn_active_border': '#5e81ac',
    'sidebar_profile_bg': '#2e3440', 'sidebar_profile_fg': '#b48ead',
    'sidebar_profile_border': '#434c5e',
    'bg': '#2e3440', 'bg_alt': '#3b4252', 'fg': '#d8dee9', 'fg_bright': '#eceff4',
    'btn_bg': '#3b4252', 'btn_fg': '#b0bec5', 'btn_hover': '#434c5e',
    'btn_pressed': '#4c566a', 'border': '#434c5e', 'border_hover': '#4c566a',
    'input_bg': '#2e3440', 'header_bg': '#242933',
    'accent': '#5e81ac', 'accent_hover': '#81a1c1', 'accent_pressed': '#4c6d96',
    'green': '#a3be8c', 'green_hover': '#b4d09c', 'green_pressed': '#8aab73',
    'selection': '#3b4252', 'row_hover': '#353c4a',
    'muted': '#616e88', 'disabled': '#4c566a',
}

THEME_DRACULA = {
    'name': 'Dracula', 'sidebar_bg': '#1e1f29', 'sidebar_brand': '#191a23',
    'sidebar_border': '#44475a', 'sidebar_section': '#6272a4',
    'sidebar_btn': '#b0b8d1', 'sidebar_btn_hover_bg': '#282a36',
    'sidebar_btn_hover_border': '#44475a', 'sidebar_btn_active_bg': '#2c2e3e',
    'sidebar_btn_active_fg': '#bd93f9', 'sidebar_btn_active_border': '#bd93f9',
    'sidebar_profile_bg': '#282a36', 'sidebar_profile_fg': '#ff79c6',
    'sidebar_profile_border': '#44475a',
    'bg': '#282a36', 'bg_alt': '#2c2e3e', 'fg': '#f8f8f2', 'fg_bright': '#ffffff',
    'btn_bg': '#44475a', 'btn_fg': '#b0b8d1', 'btn_hover': '#515470',
    'btn_pressed': '#5e6180', 'border': '#44475a', 'border_hover': '#6272a4',
    'input_bg': '#21222c', 'header_bg': '#191a23',
    'accent': '#bd93f9', 'accent_hover': '#d0aaff', 'accent_pressed': '#a77de0',
    'green': '#50fa7b', 'green_hover': '#70ff95', 'green_pressed': '#38d960',
    'selection': '#383a4c', 'row_hover': '#30323f',
    'muted': '#6272a4', 'disabled': '#44475a',
}

# Registry: name → palette dict
THEMES = {
    'Steam Dark':        THEME_STEAM_DARK,
    'Catppuccin Mocha':  THEME_CATPPUCCIN_MOCHA,
    'OLED Black':        THEME_OLED_BLACK,
    'GitHub Dark':       THEME_GITHUB_DARK,
    'Nord':              THEME_NORD,
    'Dracula':           THEME_DRACULA,
}

DARK_STYLE = _build_theme_qss(THEME_STEAM_DARK)

_THEME_SETTINGS_FILE = os.path.join(_APP_DATA_DIR, 'theme.json')
_cached_theme_name: str | None = None

def load_theme_name() -> str:
    global _cached_theme_name
    if _cached_theme_name is not None:
        return _cached_theme_name
    try:
        with open(_THEME_SETTINGS_FILE, 'r') as f:
            _cached_theme_name = json.load(f).get('theme', 'Steam Dark')
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _cached_theme_name = 'Steam Dark'
    return _cached_theme_name

def save_theme_name(name: str):
    global _cached_theme_name
    _cached_theme_name = name
    try:
        with open(_THEME_SETTINGS_FILE, 'w') as f:
            json.dump({'theme': name}, f)
    except OSError:
        pass

def get_active_theme() -> dict:
    return THEMES.get(load_theme_name(), THEME_STEAM_DARK)

def get_active_stylesheet() -> str:
    name = load_theme_name()
    if name == 'Steam Dark':
        return DARK_STYLE
    theme = THEMES.get(name, THEME_STEAM_DARK)
    return _build_theme_qss(theme)

# ── Protected Paths ──────────────────────────────────────────────────────────
# System folders and important files that should NEVER be moved/deleted/renamed.

_PROTECTED_PATHS_FILE = os.path.join(_APP_DATA_DIR, 'protected_paths.json')
_cached_protected_paths: dict | None = None

def _default_protected_paths() -> list:
    """Platform-aware default protected system paths."""
    paths = []
    if sys.platform == 'win32':
        win = os.environ.get('SystemRoot', r'C:\Windows')
        paths += [
            win,
            os.path.join(os.environ.get('SystemDrive', 'C:'), os.sep, 'Program Files'),
            os.path.join(os.environ.get('SystemDrive', 'C:'), os.sep, 'Program Files (x86)'),
            os.path.join(os.environ.get('SystemDrive', 'C:'), os.sep, 'ProgramData'),
            os.path.join(os.environ.get('USERPROFILE', ''), 'AppData'),
            os.path.join(os.environ.get('USERPROFILE', ''), 'NTUSER.DAT'),
            os.environ.get('SystemRoot', r'C:\Windows') + r'\System32',
            os.environ.get('SystemRoot', r'C:\Windows') + r'\SysWOW64',
            '$RECYCLE.BIN', 'System Volume Information', 'Recovery',
            'pagefile.sys', 'hiberfil.sys', 'swapfile.sys',
            'desktop.ini', 'thumbs.db', 'ntldr', 'bootmgr',
        ]
    else:
        paths += [
            '/bin', '/sbin', '/usr', '/lib', '/lib64', '/boot', '/dev',
            '/proc', '/sys', '/etc', '/var/run', '/var/lock',
        ]
    # Universal
    paths += [
        '.git', '.svn', '.hg', '__pycache__', 'node_modules',
        '.env', '.ssh', '.gnupg', '.aws', '.kube',
    ]
    return paths

def load_protected_paths() -> dict:
    """Returns {'system': [...], 'custom': [...], 'enabled': bool}."""
    global _cached_protected_paths
    if _cached_protected_paths is not None:
        return _cached_protected_paths
    system = _default_protected_paths()
    try:
        with open(_PROTECTED_PATHS_FILE, 'r') as f:
            data = json.load(f)
        _cached_protected_paths = {
            'system': system,
            'custom': data.get('custom', []),
            'enabled': data.get('enabled', True),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _cached_protected_paths = {'system': system, 'custom': [], 'enabled': True}
    return _cached_protected_paths

def save_protected_paths(custom: list, enabled: bool = True):
    global _cached_protected_paths
    _cached_protected_paths = {
        'system': _default_protected_paths(),
        'custom': custom,
        'enabled': enabled,
    }
    try:
        with open(_PROTECTED_PATHS_FILE, 'w') as f:
            json.dump({'custom': custom, 'enabled': enabled}, f, indent=2)
    except OSError:
        pass

def is_protected(path: str) -> bool:
    """Check if a path (file or folder) is protected from operations.
    Matches by exact path, basename, or if the path is inside a protected directory."""
    prot = load_protected_paths()
    if not prot['enabled']:
        return False
    norm = os.path.normcase(os.path.normpath(path))
    basename = os.path.basename(norm)
    all_protected = prot['system'] + prot['custom']
    for p in all_protected:
        p_norm = os.path.normcase(os.path.normpath(p))
        # Exact match
        if norm == p_norm:
            return True
        # Basename match (for entries like 'desktop.ini', '.git')
        if os.sep not in p and '/' not in p and '\\' not in p:
            if basename == os.path.normcase(p):
                return True
        # Path-is-inside check
        elif norm.startswith(p_norm + os.sep) or norm == p_norm:
            return True
    return False


# ── File path constants ────────────────────────────────────────────────────────
# ── Undo / operation log ──────────────────────────────────────────────────────
_UNDO_LOG_FILE = os.path.join(_APP_DATA_DIR, 'undo_log.json')
_UNDO_STACK_FILE = os.path.join(_APP_DATA_DIR, 'undo_stack.json')
_CSV_LOG_FILE = os.path.join(_APP_DATA_DIR, 'move_log.csv')
_LAST_CONFIG_FILE = os.path.join(_APP_DATA_DIR, 'last_scan_config.json')
_WATCH_HISTORY_FILE = os.path.join(_APP_DATA_DIR, 'watch_history.json')
_WATCH_HISTORY_MAX = 500

def append_watch_event(event: dict):
    """Append an event to the watch history log. Each event is a dict with
    keys like: timestamp, folder, action, files, details."""
    event.setdefault('timestamp', datetime.now().isoformat())
    try:
        history = load_watch_history()
    except Exception:
        history = []
    history.append(event)
    if len(history) > _WATCH_HISTORY_MAX:
        history = history[-_WATCH_HISTORY_MAX:]
    try:
        with open(_WATCH_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=1)
    except OSError:
        pass

def load_watch_history() -> list:
    try:
        with open(_WATCH_HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

def clear_watch_history():
    try:
        os.remove(_WATCH_HISTORY_FILE)
    except OSError:
        pass
_PROFILES_DIR = os.path.join(_APP_DATA_DIR, 'profiles')
os.makedirs(_PROFILES_DIR, exist_ok=True)

# ── Category Presets ─────────────────────────────────────────────────────────
_PRESETS_DIR = os.path.join(_APP_DATA_DIR, 'category_presets')
os.makedirs(_PRESETS_DIR, exist_ok=True)

_CUSTOM_CATS_FILE = os.path.join(_APP_DATA_DIR, 'custom_categories.json')
_FACE_DB_FILE = os.path.join(_APP_DATA_DIR, 'face_db.json')

_PC_SCAN_CACHE_DB = os.path.join(_APP_DATA_DIR, 'scan_cache.db')
_CSV_RULES_FILE = os.path.join(_APP_DATA_DIR, 'sort_rules.csv')
