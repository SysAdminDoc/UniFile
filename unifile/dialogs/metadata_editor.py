"""Review-first batch metadata editor dialog."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.metadata_editor import (
    EDITABLE_FIELDS,
    apply_metadata_changes,
    read_editable_metadata,
    undo_metadata_batch,
)


class BatchMetadataEditorDialog(QDialog):
    """Edit one metadata field across reviewed files at a time.

    Each row is opt-in. Current values are read from embedded metadata and
    UniFile XMP sidecars; writes are sidecar-first and can be undone by the
    whole batch or only the active field.
    """

    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Metadata Editor")
        self.setMinimumSize(920, 600)
        self.setStyleSheet(get_active_stylesheet())
        self._paths = list(dict.fromkeys(
            os.path.abspath(path) for path in file_paths
            if path and os.path.isfile(path)
        ))
        self._metadata: dict[str, dict[str, str]] = {}
        self._proposed: dict[tuple[str, str], str] = {}
        self._last_batch_id = ''
        self._last_changes: list[dict] = []
        self._active_field = EDITABLE_FIELDS[0][0]
        self._updating = False
        _t = get_active_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(build_dialog_header(
            _t,
            "Metadata",
            "Batch Metadata Editor",
            "Review current XMP/EXIF values, edit the proposed value, and check only rows you want to write. "
            "Writes use UniFile-managed XMP sidecars so RAW and unsupported source formats remain untouched."
        ))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Field"))
        self.cmb_field = QComboBox()
        self.cmb_field.setAccessibleName("Metadata field")
        self.cmb_field.setAccessibleDescription("Metadata field to review and edit")
        for key, label in EDITABLE_FIELDS:
            self.cmb_field.addItem(label, key)
        self.cmb_field.currentIndexChanged.connect(self._on_field_changed)
        controls.addWidget(self.cmb_field)
        self.btn_reload = QPushButton("Reload Current Values")
        self.btn_reload.setProperty("class", "toolbar")
        self.btn_reload.clicked.connect(self._reload)
        controls.addWidget(self.btn_reload)
        controls.addStretch()
        layout.addLayout(controls)

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels([
            "Filename", "Current XMP / EXIF", "Proposed New Value", "Apply",
        ])
        self.tbl.setAccessibleName("Batch metadata review table")
        self.tbl.setAccessibleDescription(
            "Review current and proposed metadata values; check rows before applying"
        )
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setWordWrap(False)
        header = self.tbl.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tbl, 1)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        actions = QHBoxLayout()
        self.btn_apply = QPushButton("Apply Checked Fields")
        self.btn_apply.setProperty("class", "primary")
        self.btn_apply.clicked.connect(self._apply)
        actions.addWidget(self.btn_apply)
        self.btn_undo_field = QPushButton("Undo Current Field")
        self.btn_undo_field.setProperty("class", "toolbar")
        self.btn_undo_field.clicked.connect(self._undo_current_field)
        actions.addWidget(self.btn_undo_field)
        self.btn_undo = QPushButton("Undo Last Batch")
        self.btn_undo.setProperty("class", "toolbar")
        self.btn_undo.clicked.connect(self._undo_last_batch)
        actions.addWidget(self.btn_undo)
        actions.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        actions.addWidget(btn_close)
        layout.addLayout(actions)

        self._reload()

    def _capture_proposals(self):
        if self._updating:
            return
        for row, path in enumerate(self._paths):
            item = self.tbl.item(row, 2)
            if item is not None:
                self._proposed[(path, self._active_field)] = item.text()

    def _on_field_changed(self, index: int):
        self._capture_proposals()
        self._active_field = self.cmb_field.itemData(index)
        self._populate()

    def _reload(self):
        self._capture_proposals()
        self._metadata = {
            path: read_editable_metadata(path) for path in self._paths
        }
        self._populate()

    def _populate(self):
        self._updating = True
        try:
            self.tbl.setRowCount(0)
            current_values = [
                self._metadata.get(path, {}).get(self._active_field, '')
                for path in self._paths
            ]
            distinct = {value for value in current_values}
            conflict_text = (
                f"Mixed values ({len(distinct)})" if len(distinct) > 1 else None
            )
            for row, path in enumerate(self._paths):
                self.tbl.insertRow(row)
                filename = QTableWidgetItem(os.path.basename(path))
                filename.setToolTip(path)
                filename.setFlags(filename.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tbl.setItem(row, 0, filename)

                current = current_values[row]
                current_item = QTableWidgetItem(conflict_text or current)
                current_item.setToolTip(f"{path}\nCurrent value: {current or '(empty)'}")
                current_item.setFlags(current_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if conflict_text:
                    current_item.setBackground(QColor('#6b4f1d'))
                self.tbl.setItem(row, 1, current_item)

                proposed = self._proposed.get((path, self._active_field), current)
                proposed_item = QTableWidgetItem(proposed)
                proposed_item.setToolTip("Value written when this row is checked")
                self.tbl.setItem(row, 2, proposed_item)

                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemFlag.ItemIsEnabled |
                    Qt.ItemFlag.ItemIsSelectable |
                    Qt.ItemFlag.ItemIsUserCheckable
                )
                check.setCheckState(Qt.CheckState.Unchecked)
                self.tbl.setItem(row, 3, check)
        finally:
            self._updating = False
        self._update_status()

    def _update_status(self, message: str = ''):
        if message:
            self.lbl_status.setText(message)
            return
        label = self.cmb_field.currentText()
        self.lbl_status.setText(
            f"{len(self._paths)} file(s) loaded for {label}. "
            "Mixed current values are highlighted; checked rows are the only rows written."
        )

    def _collect_changes(self) -> list[dict]:
        self._capture_proposals()
        changes = []
        for row, path in enumerate(self._paths):
            check = self.tbl.item(row, 3)
            proposed = self.tbl.item(row, 2)
            if not check or check.checkState() != Qt.CheckState.Checked or not proposed:
                continue
            changes.append({
                'filepath': path,
                'field': self._active_field,
                'new': proposed.text(),
            })
        return changes

    def _apply(self):
        result = apply_metadata_changes(self._collect_changes())
        if result['success']:
            self._last_batch_id = result['batch_id']
            self._last_changes = result['changes']
            self._metadata = {
                path: read_editable_metadata(path) for path in self._paths
            }
        self._populate()
        self._update_status(
            f"Applied {result['success']} field change(s); "
            f"skipped {result['skipped']}; failed {result['failed']}. "
            "The batch is recorded in the embedding log."
        )

    def _undo_current_field(self):
        if not self._last_batch_id:
            self._update_status("No metadata batch is available to undo.")
            return
        selected = {
            (change['filepath'], change['field'])
            for change in self._last_changes
            if change['field'] == self._active_field
        }
        if not selected:
            self._update_status("The last batch has no changes for the active field.")
            return
        result = undo_metadata_batch(self._last_batch_id, fields=selected)
        self._last_changes = [
            change for change in self._last_changes
            if (change['filepath'], change['field']) not in selected
        ]
        if not self._last_changes:
            self._last_batch_id = ''
        self._reload()
        self._update_status(
            f"Undid {result['restored']} {self.cmb_field.currentText()} field(s); "
            f"{result['failed']} failed."
        )

    def _undo_last_batch(self):
        if not self._last_batch_id:
            self._update_status("No metadata batch is available to undo.")
            return
        result = undo_metadata_batch(self._last_batch_id)
        self._last_batch_id = ''
        self._last_changes = []
        self._reload()
        self._update_status(
            f"Undid {result['restored']} field change(s); {result['failed']} failed."
        )
