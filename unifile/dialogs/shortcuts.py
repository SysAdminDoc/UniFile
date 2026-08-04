"""Keyboard shortcut configuration dialog."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.shortcuts import ShortcutManager, normalize_sequence


class KeyboardShortcutsDialog(QDialog):
    """Show every binding and let users replace it without OS conflicts."""

    saved = pyqtSignal(dict)

    def __init__(self, parent=None, *, manager: ShortcutManager | None = None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(760, 620)
        self.setStyleSheet(get_active_stylesheet())
        self._manager = manager or ShortcutManager()
        self._editors: dict[str, QKeySequenceEdit] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        theme = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(build_dialog_header(
            theme,
            "Keyboard & Accessibility",
            "Keyboard Shortcuts",
            "Click any shortcut field and press a new combination. Clear a field to disable it. "
            "Windows shell shortcuts and duplicate bindings are rejected.",
        ))

        self.table = QTableWidget(len(self._manager.definitions()), 3)
        self.table.setHorizontalHeaderLabels(["Action", "Description", "Shortcut"])
        self.table.setAccessibleName("Keyboard shortcut bindings")
        self.table.setAccessibleDescription(
            "All configurable UniFile keyboard shortcuts and their current bindings"
        )
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 190)
        self.table.setColumnWidth(1, 380)
        self.table.setColumnWidth(2, 150)

        for row, definition in enumerate(self._manager.definitions()):
            action = QTableWidgetItem(definition.label)
            action.setData(Qt.ItemDataRole.UserRole, definition.key)
            self.table.setItem(row, 0, action)
            self.table.setItem(row, 1, QTableWidgetItem(definition.description))
            editor = QKeySequenceEdit(QKeySequence(self._manager.sequence(definition.key)))
            editor.setAccessibleName(f"{definition.label} shortcut")
            editor.setAccessibleDescription(definition.description)
            editor.keySequenceChanged.connect(self._validate)
            self._editors[definition.key] = editor
            self.table.setCellWidget(row, 2, editor)
            self.table.setRowHeight(row, 42)
        layout.addWidget(self.table, 1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Shortcut validation status")
        layout.addWidget(self.status)

        footer = QHBoxLayout()
        self.btn_reset = QPushButton("Reset defaults")
        self.btn_reset.setProperty("class", "toolbar")
        self.btn_reset.setAccessibleName("Reset keyboard shortcuts")
        self.btn_reset.clicked.connect(self._reset_defaults)
        footer.addWidget(self.btn_reset)
        footer.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.btn_save = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.btn_save.setText("Save shortcuts")
        self.btn_save.setAccessibleName("Save keyboard shortcuts")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self._validate()

    def values(self) -> dict[str, str]:
        return {
            key: normalize_sequence(editor.keySequence())
            for key, editor in self._editors.items()
        }

    def _validate(self, *_args) -> None:
        _normalized, errors = self._manager.validate_values(self.values())
        if errors:
            labels = {
                definition.key: definition.label
                for definition in self._manager.definitions()
            }
            details = "; ".join(
                f"{labels.get(key, key)}: {message}"
                for key, message in errors.items()
            )
            self.status.setText(f"Fix shortcut conflicts before saving: {details}")
            self.status.setStyleSheet(f"color: {get_active_theme()['danger_fg']};")
            self.btn_save.setEnabled(False)
            return
        self.status.setText("No conflicts detected. Changes apply when you save.")
        self.status.setStyleSheet(f"color: {get_active_theme()['muted']};")
        self.btn_save.setEnabled(True)

    def _reset_defaults(self) -> None:
        for definition in self._manager.definitions():
            self._editors[definition.key].setKeySequence(QKeySequence(definition.default))
        self._validate()

    def _save(self) -> None:
        values = self.values()
        ok, errors = self._manager.save_values(values)
        if not ok:
            self._validate()
            return
        self.saved.emit(self._manager.values())
        self.accept()
