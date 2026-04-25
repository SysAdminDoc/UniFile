"""Saved Searches dialog — create, apply, and manage named Smart Views."""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.saved_searches import (
    SavedSearch, add_search, delete_search, load_saved_searches,
)


class SavedSearchesDialog(QDialog):
    """Browse, apply, and manage saved searches / Smart Views."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Saved Searches")
        self.setMinimumSize(580, 500)
        self._selected: SavedSearch | None = None
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()
        self._populate()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            t,
            "Smart Views",
            "Saved Searches",
            "Save the current search filters as a named Smart View and replay them "
            "instantly from here or the Command Palette.",
        ))

        # ── Save current state row ────────────────────────────────────────────
        save_row = QHBoxLayout()
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Smart View name…")
        self.txt_name.returnPressed.connect(self._save_current)
        save_row.addWidget(self.txt_name)
        btn_save = QPushButton("Save Current Search")
        btn_save.setProperty("class", "apply")
        btn_save.clicked.connect(self._save_current)
        save_row.addWidget(btn_save)
        lay.addLayout(save_row)

        # Hint
        lbl_hint = QLabel(
            "The search query and confidence threshold are captured from the main window."
        )
        lbl_hint.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        lay.addWidget(lbl_hint)

        # ── List ──────────────────────────────────────────────────────────────
        self.lst = QListWidget()
        self.lst.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.lst, 1)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_apply = QPushButton("Apply Search")
        self.btn_apply.setProperty("class", "primary")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_selected)
        btn_row.addWidget(self.btn_apply)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setProperty("class", "danger")
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.btn_delete)

        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _populate(self):
        t = get_active_theme()
        self.lst.clear()
        for s in load_saved_searches():
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, s)
            label = s.name
            meta_parts = []
            if s.query:
                meta_parts.append(f'"{s.query}"')
            if s.category:
                meta_parts.append(s.category)
            if s.conf_min:
                meta_parts.append(f">={s.conf_min}%")
            meta = "  |  " + "  ·  ".join(meta_parts) if meta_parts else ""
            if s.result_count:
                meta += f"  ({s.result_count} results)"
            item.setText(f"{label}{meta}")
            self.lst.addItem(item)

    def _save_current(self):
        name = self.txt_name.text().strip()
        if not name:
            return
        parent = self.parent()
        query = ""
        category = ""
        conf_min = 0
        if parent:
            if hasattr(parent, 'txt_search'):
                query = parent.txt_search.text()
            if hasattr(parent, 'cmb_type_filter'):
                txt = parent.cmb_type_filter.currentText()
                if txt and txt not in ("All", "All Types"):
                    category = txt
            if hasattr(parent, 'sld_conf'):
                conf_min = parent.sld_conf.value()
        add_search(SavedSearch(
            name=name, query=query, category=category,
            conf_min=conf_min, created_at=time.time(),
        ))
        self.txt_name.clear()
        self._populate()

    def _on_select(self):
        items = self.lst.selectedItems()
        has = bool(items)
        self.btn_apply.setEnabled(has)
        self.btn_delete.setEnabled(has)
        self._selected = items[0].data(Qt.ItemDataRole.UserRole) if has else None

    def _apply_selected(self):
        if not self._selected:
            return
        s = self._selected
        parent = self.parent()
        if parent:
            if hasattr(parent, 'txt_search'):
                parent.txt_search.setText(s.query)
            if hasattr(parent, 'cmb_type_filter') and s.category:
                idx = parent.cmb_type_filter.findText(s.category)
                if idx >= 0:
                    parent.cmb_type_filter.setCurrentIndex(idx)
            if hasattr(parent, 'sld_conf') and s.conf_min:
                parent.sld_conf.setValue(s.conf_min)
            if hasattr(parent, '_apply_filter'):
                parent._apply_filter()
        self.accept()

    def _delete_selected(self):
        if not self._selected:
            return
        delete_search(self._selected.name)
        self._selected = None
        self._populate()
        self.btn_apply.setEnabled(False)
        self.btn_delete.setEnabled(False)
