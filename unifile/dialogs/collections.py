"""Collection board and no-move export dialog."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.tagging.library import TagLibrary

_THUMB_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tif', '.tiff'}


class CollectionBoardDialog(QDialog):
    """Show non-hierarchical entry groups as Kanban-style columns."""

    def __init__(self, library: TagLibrary, selected_entry_ids: list[int] | None = None,
                 parent=None):
        super().__init__(parent)
        self._lib = library
        self._selected_entry_ids = list(selected_entry_ids or [])
        self._selected_group_id: int | None = None
        self.setWindowTitle("Collections / Visual Boards")
        self.setMinimumSize(1120, 680)
        self.setStyleSheet(get_active_stylesheet())
        _t = get_active_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(build_dialog_header(
            _t,
            "Collections",
            "Visual Boards",
            "Group files from any folder without moving them. Each collection is a durable database membership; "
            "exports create a new ZIP or a folder of symlinks only."
        ))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Collection"))
        self.cmb_collection = QComboBox()
        self.cmb_collection.setAccessibleName("Collection selector")
        self.cmb_collection.currentIndexChanged.connect(self._on_collection_changed)
        controls.addWidget(self.cmb_collection, 1)
        self.btn_new = QPushButton("New Collection")
        self.btn_new.setProperty("class", "success")
        self.btn_new.clicked.connect(self._new_collection)
        controls.addWidget(self.btn_new)
        self.btn_add_selection = QPushButton("Add Panel Selection")
        self.btn_add_selection.setProperty("class", "toolbar")
        self.btn_add_selection.setEnabled(bool(self._selected_entry_ids))
        self.btn_add_selection.clicked.connect(self._add_panel_selection)
        controls.addWidget(self.btn_add_selection)
        self.btn_delete = QPushButton("Delete Collection")
        self.btn_delete.setProperty("class", "danger")
        self.btn_delete.clicked.connect(self._delete_collection)
        controls.addWidget(self.btn_delete)
        controls.addStretch()
        self.btn_zip = QPushButton("Export ZIP")
        self.btn_zip.setProperty("class", "toolbar")
        self.btn_zip.clicked.connect(self._export_zip)
        controls.addWidget(self.btn_zip)
        self.btn_links = QPushButton("Export Symlinks")
        self.btn_links.setProperty("class", "toolbar")
        self.btn_links.clicked.connect(self._export_symlinks)
        controls.addWidget(self.btn_links)
        layout.addLayout(controls)

        self.board_scroll = QScrollArea()
        self.board_scroll.setWidgetResizable(True)
        self.board_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.board_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.board_scroll, 1)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        self._refresh()

    def _refresh(self):
        groups = self._lib.get_all_groups() if self._lib.is_open else []
        selected = self._selected_group_id
        self.cmb_collection.blockSignals(True)
        self.cmb_collection.clear()
        for group in groups:
            self.cmb_collection.addItem(group.name, group.id)
        if groups:
            index = next((i for i, group in enumerate(groups)
                          if group.id == selected), 0)
            self.cmb_collection.setCurrentIndex(index)
            self._selected_group_id = self.cmb_collection.currentData()
        else:
            self._selected_group_id = None
        self.cmb_collection.blockSignals(False)
        self._build_board(groups)
        self._update_buttons()

    def _on_collection_changed(self, index: int):
        self._selected_group_id = self.cmb_collection.itemData(index)
        self._update_buttons()

    def _update_buttons(self):
        enabled = self._selected_group_id is not None
        self.btn_delete.setEnabled(enabled)
        self.btn_zip.setEnabled(enabled)
        self.btn_links.setEnabled(enabled)
        self.btn_add_selection.setEnabled(enabled and bool(self._selected_entry_ids))

    def _build_board(self, groups):
        old = self.board_scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        board = QWidget()
        columns = QHBoxLayout(board)
        columns.setContentsMargins(8, 8, 8, 8)
        columns.setSpacing(12)
        for group in groups:
            column = QFrame()
            column.setProperty("class", "card")
            column.setFixedWidth(270)
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(10, 10, 10, 10)
            column_layout.setSpacing(8)
            title = QPushButton(
                f"{group.name}  ({len(self._lib.get_group_entries(group.id))})")
            title.setProperty("class", "toolbar")
            title.setToolTip("Select this collection for export or panel assignment")
            title.clicked.connect(lambda checked, gid=group.id: self._select_group(gid))
            column_layout.addWidget(title)
            entries = self._lib.get_group_entries(group.id)
            if not entries:
                empty = QLabel("No files in this collection")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setWordWrap(True)
                column_layout.addWidget(empty)
            for entry in entries:
                column_layout.addWidget(self._entry_card(entry))
            column_layout.addStretch()
            columns.addWidget(column, 0, Qt.AlignmentFlag.AlignTop)
        columns.addStretch()
        self.board_scroll.setWidget(board)
        self.lbl_status.setText(
            f"{len(groups)} collection column(s). Files stay in their original locations."
        )

    def _entry_card(self, entry):
        card = QFrame()
        card.setProperty("class", "card")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(4)
        source = Path(entry.path)
        if source.is_file() and source.suffix.lower() in _THUMB_EXTS:
            pixmap = QPixmap(str(source))
            if not pixmap.isNull():
                preview = QLabel()
                preview.setPixmap(pixmap.scaled(
                    QSize(230, 120), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
                card_layout.addWidget(preview)
        name = QLabel(entry.filename)
        name.setWordWrap(True)
        name.setStyleSheet(f"font-weight: 700; color: {get_active_theme()['fg_bright']};")
        card_layout.addWidget(name)
        modified = entry.date_modified.isoformat(timespec='seconds') if entry.date_modified else 'unknown'
        details = QLabel(f"{entry.suffix.upper() or 'FILE'}  ·  {modified}")
        details.setWordWrap(True)
        details.setToolTip(str(source))
        card_layout.addWidget(details)
        card.setToolTip(f"{entry.filename}\n{source}\nModified: {modified}")
        return card

    def _select_group(self, group_id: int):
        index = self.cmb_collection.findData(group_id)
        if index >= 0:
            self.cmb_collection.setCurrentIndex(index)

    def _new_collection(self):
        name, ok = QInputDialog.getText(self, "New Collection", "Collection name:")
        if ok and name.strip():
            self._lib.create_entry_group(name.strip())
            self._selected_group_id = None
            self._refresh()

    def _add_panel_selection(self):
        if self._selected_group_id is None or not self._selected_entry_ids:
            return
        self._lib.add_entries_to_group(
            self._selected_group_id, self._selected_entry_ids)
        self._refresh()
        self.lbl_status.setText(
            f"Added {len(self._selected_entry_ids)} selected file(s) without moving them."
        )

    def _delete_collection(self):
        if self._selected_group_id is None:
            return
        group = self._lib.get_entry_group(self._selected_group_id)
        if not group:
            return
        answer = QMessageBox.question(
            self, "Delete Collection", f"Delete '{group.name}'? Files will not be moved or deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._lib.delete_entry_group(self._selected_group_id)
            self._selected_group_id = None
            self._refresh()

    def _export_zip(self):
        if self._selected_group_id is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Collection ZIP", "collection.zip", "ZIP files (*.zip)")
        if not path:
            return
        result = self._lib.export_entry_group(self._selected_group_id, path, 'zip')
        self._report_export(result)

    def _export_symlinks(self):
        if self._selected_group_id is None:
            return
        path = QFileDialog.getExistingDirectory(self, "Export Collection Symlinks")
        if not path:
            return
        result = self._lib.export_entry_group(self._selected_group_id, path, 'symlink')
        self._report_export(result)

    def _report_export(self, result: dict):
        if result.get('failed'):
            self.lbl_status.setText(
                f"Exported {result.get('exported', 0)}; skipped {result.get('skipped', 0)}; "
                f"failed {result['failed']}: {result.get('error', 'check permissions')}"
            )
        else:
            self.lbl_status.setText(
                f"Exported {result.get('exported', 0)} file(s); "
                f"skipped {result.get('skipped', 0)}. Output: {result.get('path', '')}"
            )
