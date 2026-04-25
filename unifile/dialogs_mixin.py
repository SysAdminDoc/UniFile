"""Thin dialog-launcher slots — extracted from `main_window.py` in v9.3.11.

These methods are all the same shape: instantiate a dialog, exec it,
optionally log the result. Each is 2–7 lines. Clustered together because
they have no shared state beyond `self._log` — the main window delegates
*to* them from menu items and sidebar buttons, never reads *from* them.

The lazy imports survive the move because each dialog is still a
heavyweight construct (the CSV sort rules dialog loads pandas, the
semantic search dialog loads embeddings, etc.) — keeping them
inside the methods preserves the fast-start behavior.
"""
from unifile.dialogs import (
    CsvRulesDialog,
    CustomCategoriesDialog,
    OllamaSettingsDialog,
    PluginManagerDialog,
    ProtectedPathsDialog,
    ScheduleDialog,
    ThemePickerDialog,
)


class DialogsMixin:
    """Mixin of simple dialog-launcher methods.

    Expected methods on the composed class:
      - `self._log(msg)` — used by the logging launchers.
      - `self._on_theme_changed(...)` — connected as a signal handler by
        `_open_theme_picker`.

    Expected attributes on the composed class:
      - `self.settings` — QSettings; used by `_open_embedding_settings`.
    """

    # Config / model settings --------------------------------------------------

    def _open_custom_cats(self):
        from unifile.categories import save_custom_categories
        dlg = CustomCategoriesDialog(self)
        if dlg.exec():
            save_custom_categories(dlg.get_categories())
            self._log(f"Custom categories saved ({len(dlg.get_categories())} categories)")

    def _open_ollama_settings(self):
        dlg = OllamaSettingsDialog(self)
        if dlg.exec():
            self._log(f"Ollama settings saved: {dlg.settings['url']} / {dlg.settings['model']}")

    def _open_ai_providers(self):
        from unifile.dialogs.advanced_settings import AIProviderSettingsDialog
        dlg = AIProviderSettingsDialog(self)
        if dlg.exec():
            self._log("AI provider settings saved")

    def _open_whisper_settings(self):
        from unifile.dialogs.advanced_settings import WhisperSettingsDialog
        dlg = WhisperSettingsDialog(self)
        if dlg.exec():
            from unifile.whisper_backend import get_transcriber
            model = dlg.get_model_size()
            get_transcriber(model)
            self._log(f"Whisper model set to: {model}")

    def _open_semantic_settings(self):
        from unifile.dialogs.advanced_settings import SemanticSearchSettingsDialog
        dlg = SemanticSearchSettingsDialog(self)
        dlg.exec()

    def _open_semantic_search(self):
        """Open the natural-language search panel."""
        from unifile.dialogs.advanced_settings import SemanticSearchDialog
        dlg = SemanticSearchDialog(self)
        dlg.exec()

    def _open_settings_hub(self):
        """Unified Settings Hub — aggregates every configuration dialog in
        a tabbed view so users don't have to navigate three submenus."""
        from unifile.dialogs.settings_hub import SettingsHubDialog
        dlg = SettingsHubDialog(self)
        dlg.exec()

    def _open_embedding_settings(self):
        from unifile.dialogs.advanced_settings import EmbeddingSettingsDialog
        dlg = EmbeddingSettingsDialog(self)
        if dlg.exec():
            self.settings.setValue("auto_embed", dlg.chk_auto.isChecked())
            self.settings.setValue("embed_tags", dlg.chk_tags.isChecked())
            self._log(f"Metadata embedding: auto={dlg.chk_auto.isChecked()}")

    def _open_learning_stats(self):
        from unifile.dialogs.advanced_settings import LearningStatsDialog
        dlg = LearningStatsDialog(self)
        dlg.exec()

    # Rule / plugin / schedule / theme ----------------------------------------

    def _open_schedule_dialog(self):
        """Open the scheduled scans dialog (Windows only)."""
        dlg = ScheduleDialog(self)
        dlg.exec()

    def _open_plugin_manager(self):
        """Open the plugin manager dialog."""
        dlg = PluginManagerDialog(self)
        dlg.exec()

    def _open_protected_paths(self):
        """Open the protected paths settings dialog."""
        dlg = ProtectedPathsDialog(self)
        dlg.exec()

    def _open_sort_rules(self):
        """Open the CSV sort rules editor."""
        dlg = CsvRulesDialog(self)
        dlg.exec()

    def _open_theme_picker(self):
        """Open the theme picker dialog and wire its live-change signal."""
        dlg = ThemePickerDialog(self)
        dlg.theme_changed.connect(self._on_theme_changed)
        dlg.exec()

    # Shell integration --------------------------------------------------------

    def _open_shell_integration(self):
        """Open the Shell Integration dialog (Windows only)."""
        from unifile.dialogs.shell_integration_dialog import ShellIntegrationDialog
        dlg = ShellIntegrationDialog(self)
        dlg.exec()

    # Archive indexer ----------------------------------------------------------

    def _open_archive_indexer(self):
        """Open the Archive Content Indexer dialog."""
        from unifile.dialogs.archive_indexer_dialog import ArchiveIndexerDialog
        dlg = ArchiveIndexerDialog(self)
        dlg.exec()
