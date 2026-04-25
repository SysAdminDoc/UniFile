"""UniFile — Unified Settings Hub.

A single tabbed dialog that hosts all the existing settings dialogs as tabs
instead of forcing users to navigate a nested Tools > AI & Intelligence menu.

Each tab embeds a *launcher* button plus a short description rather than
reimplementing every settings pane. This keeps the code change surgical
while giving users a single discoverable entry point for configuration.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header


def _section(title: str, description: str, actions: list[tuple[str, str, callable]],
             theme: dict) -> QWidget:
    """Build one settings panel: heading, description, and a list of launcher
    buttons. `actions` is a list of (button_label, hint_below_button, on_click)."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(12)

    lbl_title = QLabel(title)
    lbl_title.setStyleSheet(
        f"color: {theme['fg_bright']}; font-size: 15px; font-weight: 700;"
    )
    lay.addWidget(lbl_title)

    lbl_desc = QLabel(description)
    lbl_desc.setWordWrap(True)
    lbl_desc.setStyleSheet(f"color: {theme['muted']}; font-size: 12px;")
    lay.addWidget(lbl_desc)

    # Divider line for visual separation
    divider = QFrame()
    divider.setFrameShape(QFrame.Shape.HLine)
    divider.setStyleSheet(f"color: {theme['btn_bg']};")
    lay.addWidget(divider)

    for label, hint, handler in actions:
        row = QHBoxLayout()
        row.setSpacing(12)
        btn = QPushButton(label)
        btn.setProperty("class", "primary")
        btn.setMinimumWidth(220)
        btn.clicked.connect(handler)
        row.addWidget(btn)
        lbl_hint = QLabel(hint)
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        row.addWidget(lbl_hint, 1)
        lay.addLayout(row)

    lay.addStretch()
    return w


class SettingsHubDialog(QDialog):
    """Single discoverable entry point for every UniFile configuration dialog.

    The existing individual dialogs keep working standalone; this hub just
    aggregates them behind a single tabbed UI so users don't have to hunt
    through the menubar to find a setting.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UniFile Settings")
        self.setMinimumSize(700, 520)
        self.setStyleSheet(get_active_stylesheet())
        self._parent = parent
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            _t,
            "Configuration",
            "UniFile Settings",
            "One entry point for every configurable surface in UniFile. "
            "Choose a category on the left, then launch the detailed dialog."
        ))

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.tabs.setDocumentMode(True)
        lay.addWidget(self.tabs, 1)

        self.tabs.addTab(self._tab_ai(_t), "AI")
        self.tabs.addTab(self._tab_photo(_t), "Photo & Media")
        self.tabs.addTab(self._tab_rules(_t), "Rules & Learning")
        self.tabs.addTab(self._tab_system(_t), "System")
        self.tabs.addTab(self._tab_tools(_t), "Tools")

        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        footer.rejected.connect(self.reject)
        # Re-label for clarity
        footer.button(QDialogButtonBox.StandardButton.Close).setText("Done")
        lay.addWidget(footer)

    # ── Tab builders ─────────────────────────────────────────────────────────

    def _tab_ai(self, theme: dict) -> QWidget:
        return _section(
            "AI & Intelligence",
            "Configure local LLM backends, cloud providers, vision models, "
            "semantic search, and adaptive learning.",
            [
                ("Ollama Settings…",
                 "Server URL, default model, timeout, vision + content extraction.",
                 self._open_ollama),
                ("AI Providers…",
                 "Add OpenAI-compatible / Groq / LM Studio endpoints with priority fallback.",
                 self._open_providers),
                ("Semantic Search…",
                 "Natural-language query panel powered by embeddings.",
                 self._open_semantic_search),
                ("Semantic Search Settings…",
                 "Embedding model + similarity threshold for the search index.",
                 self._open_semantic_settings),
                ("Whisper Audio Transcription…",
                 "Pick a Whisper model size for audio → text extraction.",
                 self._open_whisper),
                ("Adaptive Learning Stats…",
                 "View patterns learned from your corrections and clear the learner.",
                 self._open_learning),
            ],
            theme,
        )

    def _tab_photo(self, theme: dict) -> QWidget:
        return _section(
            "Photo & Media",
            "Face recognition, EXIF geocoding, blur detection, and media "
            "metadata lookup providers.",
            [
                ("Photo Library Settings…",
                 "Enable face DB, EXIF-based folder structure, scene tagging, "
                 "and open the Face Manager from within this panel.",
                 self._open_photo),
                ("Metadata Embedding…",
                 "Write categories + tags back into files so other tools can read them.",
                 self._open_embedding),
            ],
            theme,
        )

    def _tab_rules(self, theme: dict) -> QWidget:
        return _section(
            "Rules, Learning & Automation",
            "User-defined classification rules, CSV sort rules, and watched "
            "folders that auto-organize new files.",
            [
                ("Custom Categories…",
                 "Add or edit the category keywords used by the classifier.",
                 self._open_categories),
                ("Rules Editor…",
                 "Define if/then classification rules with visual condition builder.",
                 self._open_rules),
                ("CSV Sort Rules…",
                 "Bulk import/export extension → category mappings via spreadsheet.",
                 self._open_csv_rules),
                ("Scheduler…",
                 "Create recurring scheduled scans via Windows Task Scheduler.",
                 self._open_schedule),
                ("Watch Mode History…",
                 "Review events from folders being watched for new files.",
                 self._open_watch),
            ],
            theme,
        )

    def _tab_system(self, theme: dict) -> QWidget:
        return _section(
            "System & Safety",
            "Color theme, protected system paths, plugin manager, and "
            "category presets (preset packs for different user profiles).",
            [
                ("Color Theme…",
                 "Switch between Steam Dark, Catppuccin, OLED Black, and more.",
                 self._open_theme),
                ("Protected Paths…",
                 "Folders and filenames that UniFile will never move or delete.",
                 self._open_protected),
                ("Plugin Manager…",
                 "Review installed plugins; enable or disable individually.",
                 self._open_plugins),
                ("Shell Integration…",
                 "Install 'Organize with UniFile' on folder right-click in Explorer.",
                 self._open_shell),
            ],
            theme,
        )

    def _tab_tools(self, theme: dict) -> QWidget:
        return _section(
            "Power Tools",
            "Utilities for advanced file management and search.",
            [
                ("Archive Content Indexer…",
                 "Index files inside .zip / .7z / .rar / .tar archives for search.",
                 self._open_archive_indexer),
            ],
            theme,
        )

    # ── Launchers — call through to the existing parent window slots so
    # every dialog stays backed by the same settings files. ──────────────────

    def _parent_or_self(self):
        return self._parent if self._parent is not None else self

    def _call(self, method_name: str):
        """Delegate to the main window slot, falling back to a friendly
        in-hub message if the parent doesn't expose it (e.g. standalone
        dialog usage in a test)."""
        target = self._parent
        fn = getattr(target, method_name, None)
        if callable(fn):
            fn()
        else:
            _t = get_active_theme()
            # Non-blocking feedback — just highlight the missing hook
            # visually by flashing the window title briefly.
            self.setWindowTitle("UniFile Settings  —  (slot not available)")

    # AI tab
    def _open_ollama(self):           self._call('_open_ollama_settings')
    def _open_providers(self):        self._call('_open_ai_providers')
    def _open_semantic_search(self):  self._call('_open_semantic_search')
    def _open_semantic_settings(self):self._call('_open_semantic_settings')
    def _open_whisper(self):          self._call('_open_whisper_settings')
    def _open_learning(self):         self._call('_open_learning_stats')

    # Photo tab
    def _open_photo(self):            self._call('_open_photo_settings')
    def _open_embedding(self):        self._call('_open_embedding_settings')

    # Rules tab
    def _open_categories(self):       self._call('_open_custom_cats')
    def _open_rules(self):            self._call('_open_rule_editor')
    def _open_csv_rules(self):        self._call('_open_sort_rules')
    def _open_schedule(self):         self._call('_open_schedule_dialog')
    def _open_watch(self):            self._call('_open_watch_history')

    # System tab
    def _open_theme(self):            self._call('_open_theme_picker')
    def _open_protected(self):        self._call('_open_protected_paths')
    def _open_plugins(self):          self._call('_open_plugin_manager')
    def _open_shell(self):            self._call('_open_shell_integration')

    # Tools tab
    def _open_archive_indexer(self):  self._call('_open_archive_indexer')
