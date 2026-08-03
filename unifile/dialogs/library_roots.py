"""Dialog for managing the filesystem roots attached to a Tag Library."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.tagging.library import TagLibrary


class LibraryRootsDialog(QDialog):
    """Show root health and safely relink secondary roots."""

    def __init__(self, library: TagLibrary, parent=None):
        super().__init__(parent)
        self._library = library
        self._statuses: list[dict] = []
        self.setWindowTitle("Manage Library Roots")
        self.setMinimumSize(860, 500)
        self.setStyleSheet(get_active_stylesheet())
        theme = get_active_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(build_dialog_header(
            theme,
            "Library",
            "Manage Roots",
            "One tag library can index files across local drives, network shares, and removable media. "
            "Offline roots remain in the database until they can be relinked."
        ))

        self.tbl_roots = QTableWidget(0, 3)
        self.tbl_roots.setHorizontalHeaderLabels(["Status", "Root", "Indexed files"])
        self.tbl_roots.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_roots.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_roots.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_roots.horizontalHeader().setStretchLastSection(False)
        self.tbl_roots.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_roots.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.tbl_roots.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_roots.setAccessibleName("Configured library roots")
        self.tbl_roots.setAccessibleDescription(
            "Configured filesystem roots with online status and indexed file counts")
        layout.addWidget(self.tbl_roots, 1)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        controls = QHBoxLayout()
        self.btn_add = QPushButton("Add Root")
        self.btn_add.setProperty("class", "success")
        self.btn_add.setAccessibleName("Add library root")
        self.btn_add.setAccessibleDescription(
            "Attach another existing folder to this tag library")
        self.btn_add.clicked.connect(self._add_root)
        controls.addWidget(self.btn_add)
        self.btn_relink = QPushButton("Relink Selected")
        self.btn_relink.setProperty("class", "toolbar")
        self.btn_relink.setAccessibleName("Relink selected library root")
        self.btn_relink.setAccessibleDescription(
            "Point an offline secondary root at its new existing folder")
        self.btn_relink.clicked.connect(self._relink_selected)
        controls.addWidget(self.btn_relink)
        self.btn_remove = QPushButton("Remove Empty Root")
        self.btn_remove.setProperty("class", "danger")
        self.btn_remove.setAccessibleName("Remove empty library root")
        self.btn_remove.setAccessibleDescription(
            "Remove a configured root only when it has no indexed entries")
        self.btn_remove.clicked.connect(self._remove_selected)
        controls.addWidget(self.btn_remove)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setProperty("class", "toolbar")
        self.btn_refresh.clicked.connect(self._refresh)
        controls.addWidget(self.btn_refresh)
        controls.addStretch()
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        controls.addWidget(close_box)
        layout.addLayout(controls)

        self._refresh()

    def _selected_status(self) -> dict | None:
        row = self.tbl_roots.currentRow()
        if row < 0 or row >= len(self._statuses):
            return None
        return self._statuses[row]

    def _refresh(self):
        selected_id = None
        selected = self._selected_status()
        if selected:
            selected_id = selected['id']
        self._statuses = self._library.get_root_statuses()
        self.tbl_roots.setRowCount(len(self._statuses))
        selected_row = -1
        for row, status in enumerate(self._statuses):
            if status['id'] == selected_id:
                selected_row = row
            state_item = QTableWidgetItem(status['state'].title())
            state_item.setData(Qt.ItemDataRole.UserRole, status['id'])
            if status.get('is_database_root'):
                state_item.setToolTip("Active database root; it cannot be relinked while open")
            self.tbl_roots.setItem(row, 0, state_item)
            path_item = QTableWidgetItem(status['path'])
            path_item.setToolTip(status['path'])
            self.tbl_roots.setItem(row, 1, path_item)
            count_item = QTableWidgetItem(str(status['entry_count']))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tbl_roots.setItem(row, 2, count_item)
        if selected_row >= 0:
            self.tbl_roots.selectRow(selected_row)
        elif self._statuses:
            self.tbl_roots.selectRow(0)
        self.lbl_status.setText(
            f"{len(self._statuses)} configured root(s). The active database root stays anchored "
            "while this library is open."
        )

    def _add_root(self):
        path = QFileDialog.getExistingDirectory(self, "Add Library Root")
        if not path:
            return
        if self._library.add_root(path):
            self._refresh()
            self.lbl_status.setText(f"Added library root: {path}")
        else:
            QMessageBox.warning(self, "Add Root", "That folder could not be added.")

    def _relink_selected(self):
        status = self._selected_status()
        if not status:
            return
        if status.get('is_database_root'):
            QMessageBox.information(
                self,
                "Relink Root",
                "The active database root cannot be relinked while this library is open. "
                "Open the library from its new location after moving it.",
            )
            return
        path = QFileDialog.getExistingDirectory(self, "Relink Library Root")
        if not path:
            return
        result = self._library.relink_root(status['id'], path)
        if result['failed']:
            QMessageBox.warning(
                self,
                "Relink Root",
                f"Updated {result['updated']} entr{'y' if result['updated'] == 1 else 'ies'}; "
                f"{result['failed']} could not be relinked. {result['error']}",
            )
        else:
            self.lbl_status.setText(
                f"Relinked {result['updated']} entr{'y' if result['updated'] == 1 else 'ies'} "
                f"to {path}.")
        self._refresh()

    def _remove_selected(self):
        status = self._selected_status()
        if not status:
            return
        if status.get('is_database_root'):
            QMessageBox.information(
                self, "Remove Root", "The active database root cannot be removed while open.")
            return
        if status['entry_count']:
            QMessageBox.information(
                self,
                "Remove Root",
                "Only empty roots can be removed. Remove or relink its indexed entries first.",
            )
            return
        if self._library.remove_root(status['id']):
            self._refresh()
            self.lbl_status.setText(f"Removed empty root: {status['path']}")
