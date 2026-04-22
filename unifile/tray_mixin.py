"""System-tray wiring — extracted from `main_window.py` in v9.3.10.

The tray mixin owns the `self._tray` attribute (a `QSystemTrayIcon` or `None`)
and the four methods that manipulate it. WatchMixin (separate file) reads
`self._tray` but never mutates it — the tray is the source of truth for
"am I running in reduce-to-tray mode?".

Kept out of WatchMixin because the tray lives even when watch mode is off:
you can still get there via "Show UniFile" / "Exit" menu entries.
"""
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from unifile.config import get_active_stylesheet


class TrayMixin:
    """Mixin providing system-tray setup and lifecycle.

    Expected attributes on the composed class:
      - `self._watch_manager` (TrayMixin reads it only in `_tray_exit`)
      - `self._save_settings()` method
      - `self._watch_pause()` method (wired from the tray menu; provided
        by `WatchMixin`)
    """

    def _setup_tray(self):
        """Set up the system tray icon for watch mode."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("UniFile — Watch Mode")
        # Use app icon if available
        icon = self.windowIcon()
        if not icon.isNull():
            self._tray.setIcon(icon)
        else:
            self._tray.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_ComputerIcon))
        # Tray menu
        tray_menu = QMenu()
        tray_menu.setStyleSheet(get_active_stylesheet())
        act_show = tray_menu.addAction("Show UniFile")
        act_show.triggered.connect(self._tray_show)
        act_pause = tray_menu.addAction("Pause Watch")
        act_pause.triggered.connect(self._watch_pause)
        tray_menu.addSeparator()
        act_exit = tray_menu.addAction("Exit")
        act_exit.triggered.connect(self._tray_exit)
        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        """Show window on tray icon double-click."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show()

    def _tray_show(self):
        """Restore window from system tray."""
        self.showNormal()
        self.activateWindow()

    def _tray_exit(self):
        """Exit the application from tray."""
        if self._watch_manager and self._watch_manager.is_active:
            self._watch_manager.stop()
        self._save_settings()
        QApplication.instance().quit()
