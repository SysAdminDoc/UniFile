"""Settings dialog for optional rclone remotes and local cloud folders."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from unifile.accessibility import ensure_accessible_metadata
from unifile.cloud_storage import (
    CloudRemoteConfig,
    RcloneAdapter,
    RcloneError,
    list_configured_rclone_remotes,
    load_cloud_remotes,
    save_cloud_remotes,
)
from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.plugins import CloudPathResolver


class CloudRemotesDialog(QDialog):
    """Configure rclone remotes without storing credentials in UniFile."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cloud Remotes")
        self.setMinimumSize(980, 700)
        self.setStyleSheet(get_active_stylesheet())
        self._remotes = load_cloud_remotes()
        self._listed_files = []
        self._selected_index = -1
        theme = get_active_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(build_dialog_header(
            theme,
            "Storage",
            "Cloud Remotes",
            "Use a user-configured rclone remote for read-only listings and filtered local downloads. "
            "UniFile never stores rclone credentials; optional sidecar upload is a separate action."
        ))

        self.tbl_remotes = QTableWidget(0, 4)
        self.tbl_remotes.setHorizontalHeaderLabels(["Profile", "rclone remote", "Mode", "Filter"])
        self.tbl_remotes.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_remotes.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_remotes.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_remotes.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_remotes.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.tbl_remotes.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_remotes.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self.tbl_remotes.itemSelectionChanged.connect(self._on_selection_changed)
        self.tbl_remotes.setAccessibleName("Configured cloud remotes")
        layout.addWidget(self.tbl_remotes)

        editor = QGroupBox("Remote definition")
        form = QFormLayout(editor)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        self.txt_profile = QLineEdit()
        self.txt_profile.setPlaceholderText("e.g. Archive S3")
        self.txt_profile.setAccessibleName("Cloud remote profile name")
        form.addRow("Profile name", self.txt_profile)
        self.txt_remote = QLineEdit()
        self.txt_remote.setPlaceholderText("rclone remote name, e.g. my-s3")
        self.txt_remote.setAccessibleName("rclone remote name")
        form.addRow("rclone remote", self.txt_remote)
        self.txt_remote_path = QLineEdit()
        self.txt_remote_path.setPlaceholderText("Optional path within the remote")
        form.addRow("Remote path", self.txt_remote_path)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["list-only", "download", "sync-back"])
        self.cmb_mode.setToolTip(
            "list-only never downloads; download writes filtered files locally; "
            "sync-back enables the explicit sidecar upload action")
        form.addRow("Scan mode", self.cmb_mode)
        download_row = QHBoxLayout()
        self.txt_download_dir = QLineEdit()
        self.txt_download_dir.setPlaceholderText("Required for download and sync-back modes")
        download_row.addWidget(self.txt_download_dir, 1)
        self.btn_browse_download = QPushButton("Browse")
        self.btn_browse_download.setProperty("class", "toolbar")
        self.btn_browse_download.clicked.connect(self._browse_download_dir)
        download_row.addWidget(self.btn_browse_download)
        form.addRow("Local download folder", download_row)
        self.spn_max_size = QSpinBox()
        self.spn_max_size.setRange(0, 1024 * 1024)
        self.spn_max_size.setSuffix(" MB (0 = no cap)")
        form.addRow("Maximum file size", self.spn_max_size)
        self.txt_extensions = QLineEdit()
        self.txt_extensions.setPlaceholderText("pdf, jpg, png (blank = all)")
        form.addRow("Extension whitelist", self.txt_extensions)
        self.chk_sync_back = QCheckBox("Allow explicit XMP sidecar sync-back")
        self.chk_sync_back.setToolTip(
            "Enables the separate upload button; it does not run automatically after a scan")
        form.addRow("Safety", self.chk_sync_back)
        layout.addWidget(editor)

        actions = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_new.setProperty("class", "toolbar")
        self.btn_new.clicked.connect(self._new_remote)
        actions.addWidget(self.btn_new)
        self.btn_save = QPushButton("Save Remote")
        self.btn_save.setProperty("class", "success")
        self.btn_save.clicked.connect(self._save_remote)
        actions.addWidget(self.btn_save)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setProperty("class", "danger")
        self.btn_remove.clicked.connect(self._remove_remote)
        actions.addWidget(self.btn_remove)
        actions.addStretch()
        self.btn_test = QPushButton("Test rclone")
        self.btn_test.setProperty("class", "toolbar")
        self.btn_test.clicked.connect(self._test_remote)
        actions.addWidget(self.btn_test)
        self.btn_list = QPushButton("List Filtered Files")
        self.btn_list.setProperty("class", "toolbar")
        self.btn_list.clicked.connect(self._list_files)
        actions.addWidget(self.btn_list)
        self.btn_download = QPushButton("Download Filtered")
        self.btn_download.setProperty("class", "primary")
        self.btn_download.clicked.connect(self._download_files)
        actions.addWidget(self.btn_download)
        self.btn_sidecars = QPushButton("Sync XMP Sidecars")
        self.btn_sidecars.setProperty("class", "toolbar")
        self.btn_sidecars.clicked.connect(self._sync_sidecars)
        actions.addWidget(self.btn_sidecars)
        layout.addLayout(actions)

        self.lbl_local = QLabel()
        self.lbl_local.setWordWrap(True)
        self.lbl_local.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_local)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)

        self._refresh_table()
        self._new_remote()
        self._refresh_local_status()
        ensure_accessible_metadata(self, "Cloud Remotes")

    def _refresh_table(self):
        self.tbl_remotes.blockSignals(True)
        self.tbl_remotes.setRowCount(len(self._remotes))
        for row, remote in enumerate(self._remotes):
            values = [
                remote.name,
                f"{remote.remote_name}:{remote.remote_path}" if remote.remote_path else f"{remote.remote_name}:",
                remote.scan_mode,
                self._filter_summary(remote),
            ]
            for column, value in enumerate(values):
                self.tbl_remotes.setItem(row, column, QTableWidgetItem(value))
        self.tbl_remotes.blockSignals(False)
        if self._remotes:
            self.tbl_remotes.selectRow(min(max(self._selected_index, 0), len(self._remotes) - 1))

    @staticmethod
    def _filter_summary(remote: CloudRemoteConfig) -> str:
        filters = []
        if remote.extensions:
            filters.append(", ".join(remote.extensions))
        if remote.max_size_mb:
            filters.append(f"≤ {remote.max_size_mb} MB")
        return "; ".join(filters) or "all files"

    def _on_selection_changed(self):
        row = self.tbl_remotes.currentRow()
        if row < 0 or row >= len(self._remotes):
            return
        self._selected_index = row
        remote = self._remotes[row]
        self.txt_profile.setText(remote.name)
        self.txt_remote.setText(remote.remote_name)
        self.txt_remote_path.setText(remote.remote_path)
        self.cmb_mode.setCurrentText(remote.scan_mode)
        self.txt_download_dir.setText(remote.download_dir)
        self.spn_max_size.setValue(remote.max_size_mb)
        self.txt_extensions.setText(", ".join(remote.extensions))
        self.chk_sync_back.setChecked(remote.sync_back)
        self._listed_files = []

    def _new_remote(self):
        self._selected_index = -1
        self.tbl_remotes.clearSelection()
        self.txt_profile.clear()
        self.txt_remote.clear()
        self.txt_remote_path.clear()
        self.cmb_mode.setCurrentText("list-only")
        self.txt_download_dir.clear()
        self.spn_max_size.setValue(0)
        self.txt_extensions.clear()
        self.chk_sync_back.setChecked(False)
        self._listed_files = []
        self.lbl_status.setText("Enter a profile and rclone remote, then save it.")

    def _browse_download_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Local Download Folder")
        if path:
            self.txt_download_dir.setText(path)

    def _form_config(self) -> CloudRemoteConfig:
        return CloudRemoteConfig(
            name=self.txt_profile.text(),
            remote_name=self.txt_remote.text(),
            remote_path=self.txt_remote_path.text(),
            scan_mode=self.cmb_mode.currentText(),
            download_dir=self.txt_download_dir.text(),
            max_size_mb=self.spn_max_size.value(),
            extensions=tuple(self.txt_extensions.text().split(",")),
            sync_back=self.chk_sync_back.isChecked(),
        )

    def _save_remote(self):
        try:
            remote = self._form_config()
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Cloud Remotes", str(exc))
            return
        duplicate = next(
            (index for index, item in enumerate(self._remotes)
             if item.name.casefold() == remote.name.casefold() and index != self._selected_index),
            None,
        )
        if duplicate is not None:
            QMessageBox.warning(self, "Cloud Remotes", "Profile names must be unique.")
            return
        if self._selected_index >= 0:
            self._remotes[self._selected_index] = remote
        else:
            self._remotes.append(remote)
            self._selected_index = len(self._remotes) - 1
        if not save_cloud_remotes(self._remotes):
            QMessageBox.warning(self, "Cloud Remotes", "Could not save cloud remote settings.")
            return
        self._refresh_table()
        self.tbl_remotes.selectRow(self._selected_index)
        self.lbl_status.setText(f"Saved cloud remote profile: {remote.name}")

    def _remove_remote(self):
        if self._selected_index < 0 or self._selected_index >= len(self._remotes):
            return
        remote = self._remotes.pop(self._selected_index)
        if not save_cloud_remotes(self._remotes):
            self._remotes.insert(self._selected_index, remote)
            QMessageBox.warning(self, "Cloud Remotes", "Could not save cloud remote settings.")
            return
        self._selected_index = -1
        self._refresh_table()
        self._new_remote()
        self.lbl_status.setText(f"Removed cloud remote profile: {remote.name}")

    def _adapter(self) -> tuple[CloudRemoteConfig, RcloneAdapter] | None:
        try:
            remote = self._form_config()
            return remote, RcloneAdapter(remote.remote_name, remote.remote_path)
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Cloud Remotes", str(exc))
            return None

    def _test_remote(self):
        configured = self.txt_remote.text().strip()
        if not configured:
            QMessageBox.warning(self, "Test rclone", "Enter an rclone remote name first.")
            return
        try:
            remotes = list_configured_rclone_remotes()
        except RcloneError as exc:
            self.lbl_status.setText(f"rclone unavailable: {exc}")
            return
        if configured not in remotes:
            self.lbl_status.setText(
                f"rclone is available, but '{configured}' is not in its configured remote list.")
        else:
            self.lbl_status.setText(f"rclone remote '{configured}' is configured.")

    def _list_files(self):
        configured = self._adapter()
        if configured is None:
            return
        remote, adapter = configured
        try:
            self._listed_files = adapter.list_files(
                extensions=remote.extensions,
                max_size_bytes=remote.max_size_mb * 1024 * 1024,
            )
        except RcloneError as exc:
            self._listed_files = []
            self.lbl_status.setText(f"Remote listing failed: {exc}")
            return
        preview = ", ".join(file.path for file in self._listed_files[:3])
        suffix = " …" if len(self._listed_files) > 3 else ""
        self.lbl_status.setText(
            f"Read-only listing: {len(self._listed_files)} filtered file(s). {preview}{suffix}")

    def _download_files(self):
        configured = self._adapter()
        if configured is None:
            return
        remote, adapter = configured
        if remote.scan_mode == "list-only":
            self.lbl_status.setText("This profile is list-only; choose download or sync-back mode first.")
            return
        if not self._listed_files:
            self._list_files()
        if not self._listed_files:
            return
        result = adapter.download_files(self._listed_files, remote.download_dir)
        self.lbl_status.setText(
            f"Downloaded {result['downloaded']} file(s); {result['failed']} failed. "
            f"Local review folder: {result['destination']}")

    def _sync_sidecars(self):
        configured = self._adapter()
        if configured is None:
            return
        remote, adapter = configured
        if not remote.sync_back:
            self.lbl_status.setText("Enable explicit XMP sidecar sync-back in the profile first.")
            return
        if not self._listed_files:
            self._list_files()
        if not self._listed_files:
            return
        result = adapter.sync_sidecars(self._listed_files, remote.download_dir)
        self.lbl_status.setText(
            f"Uploaded {result['uploaded']} XMP sidecar(s); skipped {result['skipped']}; "
            f"{result['failed']} failed. Existing remote sidecars were not overwritten.")

    def _refresh_local_status(self):
        folders = CloudPathResolver.detect_cloud_folders()
        if not folders:
            self.lbl_local.setText("No local cloud-sync folders were detected.")
            return
        parts = []
        for folder in folders:
            state = folder.get("sync_status", {}).get("state", "unknown")
            parts.append(f"{folder['name']}: {state}")
        self.lbl_local.setText("Detected local sync folders: " + " · ".join(parts))
