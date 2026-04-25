"""Accessibility settings dialog — font size control."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
)

from unifile.config import (
    get_active_stylesheet, get_active_theme, load_font_size, save_font_size,
)
from unifile.dialogs.common import build_dialog_header


class AccessibilityDialog(QDialog):
    """Font-size and readability settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accessibility")
        self.setMinimumWidth(480)
        self._original_fs = load_font_size()
        self._preview_fs = self._original_fs
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            t,
            "Accessibility",
            "Display Settings",
            "Adjust the base UI font size. The change applies immediately so you "
            "can preview it before saving.",
        ))

        # ── Font size row ─────────────────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(10)

        lbl_caption = QLabel("Font size")
        lbl_caption.setStyleSheet(f"color: {t['fg']}; font-weight: 600;")
        row.addWidget(lbl_caption)

        self.sld = QSlider(Qt.Orientation.Horizontal)
        self.sld.setRange(8, 24)
        self.sld.setValue(self._original_fs)
        self.sld.setTickInterval(2)
        self.sld.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sld.valueChanged.connect(self._on_slide)
        row.addWidget(self.sld, 1)

        self.lbl_value = QLabel(f"{self._original_fs} px")
        self.lbl_value.setFixedWidth(44)
        self.lbl_value.setStyleSheet(
            f"color: {t['fg_bright']}; font-weight: 700; font-size: 13px;"
        )
        row.addWidget(self.lbl_value)

        lay.addLayout(row)

        # Reset link
        btn_reset = QPushButton("Reset to default (13 px)")
        btn_reset.setProperty("class", "toolbar")
        btn_reset.clicked.connect(self._reset)
        row2 = QHBoxLayout()
        row2.addStretch()
        row2.addWidget(btn_reset)
        lay.addLayout(row2)

        lay.addStretch()

        # Buttons
        bb = QHBoxLayout()
        bb.addStretch()
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setProperty("class", "primary")
        self.btn_apply.clicked.connect(self._apply)
        bb.addWidget(self.btn_apply)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self._cancel)
        bb.addWidget(btn_cancel)
        lay.addLayout(bb)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_slide(self, value: int):
        self._preview_fs = value
        self.lbl_value.setText(f"{value} px")
        # Live preview: push updated QSS to parent window if available
        parent = self.parent()
        if parent and hasattr(parent, 'setStyleSheet'):
            from unifile.config import _build_theme_qss, get_active_theme, load_theme_name, DARK_STYLE, THEMES
            name = load_theme_name()
            if name == 'Steam Dark' and value == 13:
                parent.setStyleSheet(DARK_STYLE)
            else:
                theme = THEMES.get(name, THEMES['Steam Dark'])
                parent.setStyleSheet(_build_theme_qss(theme, value))

    def _reset(self):
        self.sld.setValue(13)

    def _apply(self):
        save_font_size(self._preview_fs)
        self.accept()

    def _cancel(self):
        # Revert live preview
        self._on_slide(self._original_fs)
        self.reject()
