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
import os

from unifile.dialogs import (
    BatchMetadataEditorDialog,
    CsvRulesDialog,
    CustomCategoriesDialog,
    OllamaSettingsDialog,
    PluginManagerDialog,
    ProtectedPathsDialog,
    ScheduleDialog,
    ThemePickerDialog,
)
from unifile.voice import (
    VoiceIntent,
    VoiceIntentParser,
    matches_voice_selector,
    provider_voice_classifier,
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

    def _setup_voice_shortcut(self):
        """Install the configurable application-wide voice control shortcut."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeySequence, QShortcut

        shortcut = str(self.settings.value("voice/shortcut", "Ctrl+Shift+V") or "")
        self._voice_shortcut = QShortcut(QKeySequence(shortcut), self)
        self._voice_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._voice_shortcut.activated.connect(self._open_voice_control)

    def _set_voice_shortcut(self, shortcut: str):
        """Persist and apply a voice activation shortcut from the dialog."""
        from PyQt6.QtGui import QKeySequence

        value = str(shortcut or "").strip()
        self.settings.setValue("voice/shortcut", value)
        if hasattr(self, "_voice_shortcut"):
            self._voice_shortcut.setKey(QKeySequence(value))
        self._log(f"Voice Control shortcut: {value or 'disabled'}")

    def _open_voice_control(self):
        """Open the offline-first voice command preview/execution dialog."""
        from unifile.dialogs.voice_control import VoiceControlDialog

        parser = VoiceIntentParser(llm_classifier=provider_voice_classifier)
        dlg = VoiceControlDialog(
            self,
            parser=parser,
            execute_callback=self._execute_voice_intent,
            preview_callback=self._preview_voice_intent,
            shortcut=str(self.settings.value("voice/shortcut", "Ctrl+Shift+V") or ""),
        )
        dlg.hotkey_changed.connect(self._set_voice_shortcut)
        dlg.exec()

    def _voice_library_matches(self, intent: VoiceIntent):
        panel = getattr(self, "_tag_panel", None)
        library = getattr(panel, "library", None)
        if library is None or not getattr(library, "is_open", False):
            return None
        entries = library.get_all_entries(limit=100_000)
        return [
            entry for entry in entries
            if matches_voice_selector(
                f"{entry.filename} {entry.path}", intent.selector_terms,
            )
        ]

    def _preview_voice_intent(self, intent: VoiceIntent) -> str:
        """Describe the bounded effect of an intent before execution."""
        if intent.action == "scan":
            if os.path.isdir(intent.path):
                return f"Ready to scan {intent.path}. Existing scan settings will be preserved."
            return f"Folder not found: {intent.path}"
        if intent.action == "search":
            return f"Read-only filter; no files will be changed. Query: {intent.query}"
        if intent.action == "tag":
            matches = self._voice_library_matches(intent)
            if matches is None:
                return "Open a Tag Library before applying a voice tag."
            tag_exists = bool(self._tag_panel.library.get_tag_by_name(intent.tag))
            created = "existing" if tag_exists else "new"
            count_word = "entry" if len(matches) == 1 else "entries"
            return f"{len(matches):,} matching {count_word}; {created} tag “{intent.tag}” will be applied."
        return intent.reason

    def _execute_voice_intent(self, intent: VoiceIntent) -> str:
        """Execute a parsed intent after the dialog's explicit review click."""
        if intent.action == "scan":
            if not os.path.isdir(intent.path):
                return f"Scan not started; folder not found: {intent.path}"
            if hasattr(self, "txt_src"):
                self.txt_src.setText(intent.path)
            self._on_scan()
            self._log(f"Voice Control: scan started for {intent.path}")
            return f"Scan started: {intent.path}"
        if intent.action == "search":
            if hasattr(self, "txt_search"):
                self.txt_search.setText(intent.query)
                self.txt_search.setFocus()
            self._log(f"Voice Control: search filter applied: {intent.query}")
            return f"Search filter applied: {intent.query}"
        if intent.action == "tag":
            matches = self._voice_library_matches(intent)
            if matches is None:
                return "Open a Tag Library before applying a voice tag."
            if not matches:
                return "No matching Tag Library entries; no changes were made."
            if len(matches) > 10_000:
                return "More than 10,000 entries matched; refine the voice selector first."
            library = self._tag_panel.library
            tag = library.get_tag_by_name(intent.tag) or library.add_tag(name=intent.tag)
            if tag is None:
                return f"Could not create or find tag: {intent.tag}"
            applied = sum(
                1 for entry in matches
                if library.add_tags_to_entry(entry.id, [tag.id])
            )
            self._tag_panel._refresh_tags()
            self._tag_panel._refresh_entries()
            self._tag_panel._update_stats()
            self._content_stack.setCurrentIndex(3)
            self._log(f"Voice Control: applied tag “{intent.tag}” to {applied:,} entries")
            return f"Applied “{intent.tag}” to {applied:,} entries."
        return intent.reason or "Unsupported voice action."

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

    def _open_batch_metadata_editor(self):
        """Open the review-first editor for checked scan result files."""
        paths = [
            item.full_src for item in getattr(self, 'file_items', [])
            if getattr(item, 'selected', False)
            and os.path.isfile(getattr(item, 'full_src', ''))
        ]
        if not paths:
            self._log("Batch metadata editor: check one or more files first")
            return
        dlg = BatchMetadataEditorDialog(paths, self)
        dlg.exec()
        if getattr(dlg, '_last_batch_id', ''):
            self._log(
                f"Batch metadata editor: {len(getattr(dlg, '_last_changes', []))} "
                "field change(s) remain available to undo"
            )

    def _open_project_audit(self):
        """Open the read-only video project reference audit."""
        from unifile.dialogs.project_audit import ProjectAuditDialog

        source = self.txt_src.text() if hasattr(self, "txt_src") else ""
        panel = getattr(self, "_tag_panel", None)
        library = getattr(panel, "library", None)
        dlg = ProjectAuditDialog(source=source, library=library, parent=self)
        dlg.exec()

    def _open_file_health(self):
        """Verify the active source/library and show its digest diff."""
        from unifile.dialogs.file_health import FileHealthDialog

        source = self.txt_src.text().strip() if hasattr(self, "txt_src") else ""
        if not source or not os.path.exists(source):
            panel = getattr(self, "_tag_panel", None)
            library = getattr(panel, "library", None)
            source = str(getattr(library, "library_dir", "") or "")
        if not source or not os.path.exists(source):
            self._log("File health: choose an existing source folder or open a Tag Library first")
            return
        dlg = FileHealthDialog(source, self)
        dlg.verification_complete.connect(lambda _report: self._refresh_dashboard_health(source))
        dlg.exec()
        self._refresh_dashboard_health(source)

    def _refresh_dashboard_health(self, source: str | None = None):
        """Refresh the compact integrity count shown on the scan dashboard."""
        label = getattr(self, "lbl_dash_health", None)
        if label is None:
            return
        try:
            from unifile.file_health import FileHealthMonitor

            root = source or (self.txt_src.text().strip() if hasattr(self, "txt_src") else "")
            if not root or not os.path.exists(root):
                label.setText("Integrity: not verified")
                return
            report = FileHealthMonitor(root).latest_report()
            if report.get("status") == "not-verified":
                label.setText("Integrity: not verified")
            else:
                label.setText(
                    f"Integrity: {report.get('files_verified', 0):,} verified · "
                    f"{report.get('changed_unexpectedly', 0):,} changed unexpectedly"
                )
        except Exception as exc:
            label.setText(f"Integrity unavailable: {exc}")

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

    # Accessibility ------------------------------------------------------------

    def _open_accessibility(self):
        """Open the Accessibility dialog (font size)."""
        from unifile.dialogs.accessibility import AccessibilityDialog
        dlg = AccessibilityDialog(self)
        if dlg.exec():
            # Re-apply the newly saved font size via the theme mixin
            from unifile.config import load_theme_name
            self._on_theme_changed(load_theme_name())

    # Saved searches -----------------------------------------------------------

    def _open_saved_searches(self):
        """Open the Saved Searches / Smart Views dialog."""
        from unifile.dialogs.saved_searches_dialog import SavedSearchesDialog
        dlg = SavedSearchesDialog(self)
        dlg.exec()
        if hasattr(self, '_refresh_smart_views_sidebar'):
            self._refresh_smart_views_sidebar()

    # Inbox / Quick Capture ----------------------------------------------------

    def _open_inbox(self):
        """Open the Inbox configuration dialog."""
        from unifile.dialogs.inbox_dialog import InboxDialog
        dlg = InboxDialog(self)
        dlg.exec()
        # Refresh the inbox badge in the status bar if present
        if hasattr(self, '_refresh_inbox_badge'):
            self._refresh_inbox_badge()
