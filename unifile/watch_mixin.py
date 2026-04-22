"""Watch-mode wiring — extracted from `main_window.py` in v9.3.10.

Works in tandem with `TrayMixin` but owns a separate concern: monitoring
folders, scheduling re-scans, and toggling the "active" badge on the
watch button. The tray mixin can live without the watch mixin
(minimize-to-tray with no folder watch) but the watch mixin needs tray
hooks for user-visible transitions.
"""
from PyQt6.QtWidgets import QSystemTrayIcon

from unifile.config import get_active_theme
from unifile.dialogs import WatchHistoryDialog
from unifile.widgets import (
    WatchModeManager,
    WatchSettingsDialog,
    _load_watch_settings,
    _save_watch_settings,
)


class WatchMixin:
    """Mixin providing folder-watch toggle and tray-driven pause.

    Expected attributes on the composed class:
      - `self._watch_manager` (nullable; created lazily on first use)
      - `self._tray` (nullable; provided by `TrayMixin`)
      - `self.btn_watch` — QPushButton toggle on the sidebar
      - `self._log(msg)` — status sink
    """

    def _watch_pause(self):
        """Pause/resume watch mode from tray."""
        if self._watch_manager and self._watch_manager.is_active:
            self._watch_manager.stop()
            self.btn_watch.setChecked(False)
            self._log("Watch mode paused")
            if self._tray:
                self._tray.showMessage("UniFile", "Watch mode paused",
                                       QSystemTrayIcon.MessageIcon.Information, 2000)

    def _toggle_watch_mode(self):
        """Toggle watch folder auto-organize mode."""
        if self.btn_watch.isChecked():
            # Open settings dialog
            settings = _load_watch_settings()
            dlg = WatchSettingsDialog(settings, self)
            if dlg.exec():
                new_settings = dlg.get_settings()
                _save_watch_settings(new_settings)
                # Start watching
                if not self._watch_manager:
                    self._watch_manager = WatchModeManager(self)
                folders = new_settings.get('folders', [])
                if folders:
                    self._watch_manager.start(folders, new_settings.get('delay_seconds', 5))
                    self._log(f"Watch mode active: monitoring {len(folders)} folder(s)")
                    _t = get_active_theme()
                    self.btn_watch.setStyleSheet(
                        f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {_t['sidebar_profile_fg']};"
                        f"color: {_t['sidebar_brand']}; border: 1px solid {_t['sidebar_profile_fg']}; border-radius: 4px; font-weight: bold; }}"
                        f"QPushButton:hover {{ background: {_t['accent_hover']}; }}")
                    if self._tray:
                        self._tray.show()
                        self._tray.showMessage("UniFile", f"Watching {len(folders)} folder(s)",
                                               QSystemTrayIcon.MessageIcon.Information, 3000)
                else:
                    self._log("No folders configured for watch mode")
                    self.btn_watch.setChecked(False)
            else:
                self.btn_watch.setChecked(False)
        else:
            # Stop watching
            if self._watch_manager and self._watch_manager.is_active:
                self._watch_manager.stop()
            self._log("Watch mode stopped")
            _t = get_active_theme()
            self.btn_watch.setStyleSheet(
                f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {_t['sidebar_profile_border']};"
                f"color: {_t['sidebar_profile_fg']}; border: 1px solid {_t['border']}; border-radius: 4px; }}"
                f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
            if self._tray:
                self._tray.hide()

    def _open_watch_history(self):
        """Open the watch history dialog."""
        dlg = WatchHistoryDialog(self)
        dlg.exec()
