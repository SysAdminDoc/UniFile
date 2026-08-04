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
    MetadataField,
    apply_metadata_changes,
    apply_metadata_field_changes,
    preview_metadata_changes,
    read_editable_metadata,
    read_metadata_fields,
    undo_metadata_batch,
    undo_metadata_field_batch,
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
        self.btn_inspect = QPushButton("Inspect Raw Metadata…")
        self.btn_inspect.setProperty("class", "toolbar")
        self.btn_inspect.setAccessibleName("Inspect raw metadata")
        self.btn_inspect.setAccessibleDescription(
            "View and review embedded EXIF, ID3, PDF, and XMP metadata fields"
        )
        self.btn_inspect.clicked.connect(self._open_inspector)
        controls.addWidget(self.btn_inspect)
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

    def _open_inspector(self):
        dialog = MetadataInspectorDialog(self._paths, self)
        dialog.exec()
        self._reload()


class MetadataInspectorDialog(QDialog):
    """Review and edit raw EXIF, XMP, ID3, mutagen, and PDF fields."""

    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Raw Metadata Inspector")
        self.setMinimumSize(1040, 680)
        self.setStyleSheet(get_active_stylesheet())
        self._paths = list(dict.fromkeys(
            os.path.abspath(path) for path in file_paths
            if path and os.path.isfile(path)
        ))
        self._fields: list[MetadataField] = []
        self._last_batch_id = ''
        self._pending_preview: dict | None = None
        self._updating = False
        _t = get_active_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(build_dialog_header(
            _t,
            "Metadata",
            "Raw Metadata Inspector",
            "Review the exact format-level fields before writing. Source files are backed up first; XMP edits stay in the adjacent UniFile sidecar.",
        ))

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("File"))
        self.cmb_file = QComboBox()
        self.cmb_file.setAccessibleName("Metadata inspector file")
        self.cmb_file.setAccessibleDescription("File whose raw metadata fields are shown")
        for path in self._paths:
            self.cmb_file.addItem(os.path.basename(path), path)
            self.cmb_file.setItemData(self.cmb_file.count() - 1, path, Qt.ItemDataRole.ToolTipRole)
        self.cmb_file.currentIndexChanged.connect(self._reload)
        file_row.addWidget(self.cmb_file, 1)
        self.btn_reload_raw = QPushButton("Reload")
        self.btn_reload_raw.setProperty("class", "toolbar")
        self.btn_reload_raw.clicked.connect(self._reload)
        file_row.addWidget(self.btn_reload_raw)
        layout.addLayout(file_row)

        self.tbl_fields = QTableWidget(0, 5)
        self.tbl_fields.setHorizontalHeaderLabels([
            "Source", "Field", "Current Value", "Proposed Value", "Writable",
        ])
        self.tbl_fields.setAccessibleName("Raw metadata fields")
        self.tbl_fields.setAccessibleDescription(
            "Review current raw metadata values and edit writable proposed values"
        )
        self.tbl_fields.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_fields.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_fields.setAlternatingRowColors(True)
        self.tbl_fields.verticalHeader().setVisible(False)
        self.tbl_fields.setWordWrap(False)
        header = self.tbl_fields.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_fields.itemChanged.connect(self._invalidate_preview)
        layout.addWidget(self.tbl_fields, 1)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        actions = QHBoxLayout()
        self.btn_preview = QPushButton("Preview Changes")
        self.btn_preview.setProperty("class", "toolbar")
        self.btn_preview.setAccessibleName("Preview raw metadata changes")
        self.btn_preview.clicked.connect(self._preview)
        actions.addWidget(self.btn_preview)
        self.btn_apply_raw = QPushButton("Apply Preview")
        self.btn_apply_raw.setProperty("class", "primary")
        self.btn_apply_raw.setAccessibleName("Apply previewed raw metadata changes")
        self.btn_apply_raw.clicked.connect(self._apply)
        actions.addWidget(self.btn_apply_raw)
        self.btn_undo_raw = QPushButton("Undo Last Write")
        self.btn_undo_raw.setProperty("class", "toolbar")
        self.btn_undo_raw.clicked.connect(self._undo)
        actions.addWidget(self.btn_undo_raw)
        actions.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        actions.addWidget(btn_close)
        layout.addLayout(actions)

        self._reload()

    def _current_path(self) -> str:
        return str(self.cmb_file.currentData() or '')

    def _reload(self):
        if not hasattr(self, 'tbl_fields'):
            return
        self._pending_preview = None
        self._fields = read_metadata_fields(self._current_path())
        self._updating = True
        try:
            self.tbl_fields.setRowCount(0)
            _t = get_active_theme()
            for row, field in enumerate(self._fields):
                self.tbl_fields.insertRow(row)
                source = QTableWidgetItem(field.source)
                name = QTableWidgetItem(field.label)
                current = QTableWidgetItem(field.value)
                proposed = QTableWidgetItem(field.value)
                writable = QTableWidgetItem("Yes" if field.writable else "Read-only")
                for item in (source, name, current, writable):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                proposed.setData(Qt.ItemDataRole.UserRole, field.key)
                if not field.writable:
                    proposed.setFlags(proposed.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    proposed.setBackground(QColor(_t['input_bg']))
                proposed.setToolTip(
                    "Edit this cell, then preview before writing."
                    if field.writable else "This field is visible for inspection only."
                )
                self.tbl_fields.setItem(row, 0, source)
                self.tbl_fields.setItem(row, 1, name)
                self.tbl_fields.setItem(row, 2, current)
                self.tbl_fields.setItem(row, 3, proposed)
                self.tbl_fields.setItem(row, 4, writable)
        finally:
            self._updating = False
        self.lbl_status.setText(
            f"{len(self._fields)} field(s) loaded. Edit writable proposed values, then preview before applying."
        )

    def _collect_edits(self) -> dict[str, str]:
        edits = {}
        for row, field in enumerate(self._fields):
            proposed = self.tbl_fields.item(row, 3)
            if field.writable and proposed and proposed.text() != field.value:
                edits[field.key] = proposed.text()
        return edits

    def _invalidate_preview(self, _item=None):
        if not self._updating:
            self._pending_preview = None

    def _preview(self):
        edits = self._collect_edits()
        self._pending_preview = preview_metadata_changes(self._current_path(), edits)
        result = self._pending_preview
        if result['unsupported']:
            self.lbl_status.setText(
                f"Preview rejected {len(result['unsupported'])} unsupported field(s); no write is available."
            )
            return
        for row, field in enumerate(self._fields):
            proposed = self.tbl_fields.item(row, 3)
            if proposed and field.key in {item['key'] for item in result['changes']}:
                proposed.setBackground(QColor('#2f5d3b'))
        self.lbl_status.setText(
            f"Preview: {len(result['changes'])} field change(s), {result['skipped']} unchanged. "
            "Apply Preview writes exactly this diff."
        )

    def _apply(self):
        if self._pending_preview is None:
            self.lbl_status.setText("Preview the proposed changes before writing.")
            return
        edits = self._collect_edits()
        current_preview = preview_metadata_changes(self._current_path(), edits)
        if current_preview != self._pending_preview:
            self.lbl_status.setText("The proposed values changed; preview again before writing.")
            self._pending_preview = None
            return
        result = apply_metadata_field_changes(self._current_path(), edits)
        if result['success']:
            self._last_batch_id = result['batch_id']
            self._reload()
        else:
            self._pending_preview = None
        self.lbl_status.setText(
            f"Applied {result['success']} field change(s); "
            f"failed {result['failed']}; skipped {result['skipped']}. "
            + ("Backup recorded for undo." if result['success'] else "No source bytes were changed.")
        )

    def _undo(self):
        if not self._last_batch_id:
            self.lbl_status.setText("No raw metadata write is available to undo.")
            return
        result = undo_metadata_field_batch(self._last_batch_id)
        if result['failed'] == 0:
            self._last_batch_id = ''
            self._reload()
        self.lbl_status.setText(
            f"Undid {result['restored']} artifact(s); {result['failed']} failed."
        )
