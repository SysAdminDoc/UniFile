"""UniFile — Shell Integration Dialog.

Allows users to install or remove the Windows Explorer context menu entry
("Organize with UniFile" on right-click) and the Send To shortcut.
"""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header


class ShellIntegrationDialog(QDialog):
    """Install / remove Windows Explorer shell integration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shell Integration")
        self.setMinimumWidth(540)
        self.setStyleSheet(get_active_stylesheet())
        self._t = get_active_theme()
        self._build_ui()
        self._refresh_status()

    def _build_ui(self) -> None:
        t = self._t
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            t,
            "System",
            "Shell Integration",
            "Add 'Organize with UniFile' to the right-click menu in Windows "
            "Explorer and to the Send To list. No admin rights required — "
            "entries are added per-user only.",
        ))

        if sys.platform != "win32":
            lbl = QLabel("Shell integration is only available on Windows.")
            lbl.setStyleSheet(f"color: {t['muted']}; font-size: 12px;")
            lay.addWidget(lbl)
        else:
            lay.addWidget(self._context_menu_section(t))
            lay.addWidget(self._sendto_section(t))

        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        footer.rejected.connect(self.reject)
        footer.button(QDialogButtonBox.StandardButton.Close).setText("Done")
        lay.addWidget(footer)

    def _row(self, t: dict, label: str, hint: str,
             btn_text: str, btn_slot) -> tuple[QWidget, QLabel]:
        """Build one action row: status label + button. Returns (widget, status_label)."""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        texts = QVBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {t['fg_bright']}; font-size: 13px;")
        texts.addWidget(lbl)
        status = QLabel("")
        status.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        texts.addWidget(status)
        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setWordWrap(True)
            hint_lbl.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
            texts.addWidget(hint_lbl)
        lay.addLayout(texts, 1)

        btn = QPushButton(btn_text)
        btn.setProperty("class", "primary")
        btn.setMinimumWidth(140)
        btn.clicked.connect(btn_slot)
        lay.addWidget(btn)
        return w, status

    def _context_menu_section(self, t: dict) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
            f"border-radius: 10px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        title = QLabel("Explorer Context Menu")
        title.setStyleSheet(f"color: {t['fg_bright']}; font-size: 14px; font-weight: 700;")
        lay.addWidget(title)

        row, self._cm_status = self._row(
            t,
            "Right-click on folders",
            'Adds "Organize with UniFile" to the folder right-click menu.',
            "Install",
            self._toggle_context_menu,
        )
        self._cm_btn = row.findChild(QPushButton)
        lay.addWidget(row)
        return frame

    def _sendto_section(self, t: dict) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
            f"border-radius: 10px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        title = QLabel("Send To Shortcut")
        title.setStyleSheet(f"color: {t['fg_bright']}; font-size: 14px; font-weight: 700;")
        lay.addWidget(title)

        row, self._st_status = self._row(
            t,
            "Send To menu",
            'Adds "Organize with UniFile" to Send To in Explorer.',
            "Install",
            self._toggle_sendto,
        )
        self._st_btn = row.findChild(QPushButton)
        lay.addWidget(row)
        return frame

    def _refresh_status(self) -> None:
        if sys.platform != "win32":
            return
        from unifile import shell_integration as si
        state = si.is_installed()

        # Context menu
        cm = state["context_menu"]
        self._cm_status.setText("Status: Installed" if cm else "Status: Not installed")
        self._cm_status.setStyleSheet(
            f"color: {'#4ade80' if cm else self._t['muted']}; font-size: 11px;"
        )
        if self._cm_btn:
            self._cm_btn.setText("Uninstall" if cm else "Install")

        # Send To
        st = state["sendto"]
        self._st_status.setText("Status: Installed" if st else "Status: Not installed")
        self._st_status.setStyleSheet(
            f"color: {'#4ade80' if st else self._t['muted']}; font-size: 11px;"
        )
        if self._st_btn:
            self._st_btn.setText("Uninstall" if st else "Install")

    def _toggle_context_menu(self) -> None:
        from unifile import shell_integration as si
        if si.is_context_menu_installed():
            si.uninstall_context_menu()
        else:
            si.install_context_menu()
        self._refresh_status()

    def _toggle_sendto(self) -> None:
        from unifile import shell_integration as si
        if si.is_sendto_installed():
            si.uninstall_sendto()
        else:
            si.install_sendto()
        self._refresh_status()
