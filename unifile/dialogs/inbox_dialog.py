"""Inbox / Quick Capture settings dialog."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.inbox import (
    get_inbox_count, get_inbox_path, is_inbox_enabled,
    load_inbox_config, save_inbox_config,
)


class InboxDialog(QDialog):
    """Configure the inbox folder and view its current contents."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inbox")
        self.setMinimumWidth(520)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            t,
            "Quick Capture",
            "Inbox Folder",
            "Files placed in the Inbox folder appear here and as a badge in the "
            "dashboard. Scan them into UniFile to classify and move them.",
        ))

        # ── Folder picker ─────────────────────────────────────────────────────
        path_row = QHBoxLayout()
        lbl_path = QLabel("Inbox folder")
        lbl_path.setFixedWidth(90)
        lbl_path.setStyleSheet(f"color: {t['fg']}; font-weight: 600;")
        path_row.addWidget(lbl_path)
        self.txt_path = QLineEdit()
        self.txt_path.setPlaceholderText("Choose a folder…")
        path_row.addWidget(self.txt_path)
        btn_browse = QPushButton("Browse…")
        btn_browse.setProperty("class", "toolbar")
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(btn_browse)
        lay.addLayout(path_row)

        # ── Status ────────────────────────────────────────────────────────────
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet(f"color: {t['muted']}; font-size: 12px;")
        lay.addWidget(self.lbl_count)

        # ── Open folder shortcut ──────────────────────────────────────────────
        open_row = QHBoxLayout()
        btn_open = QPushButton("Open Inbox Folder")
        btn_open.setProperty("class", "toolbar")
        btn_open.clicked.connect(self._open_folder)
        open_row.addWidget(btn_open)
        open_row.addStretch()
        lay.addLayout(open_row)

        lay.addStretch()

        # ── Buttons ───────────────────────────────────────────────────────────
        bb = QHBoxLayout()
        bb.addStretch()
        btn_clear = QPushButton("Clear Inbox")
        btn_clear.setProperty("class", "danger")
        btn_clear.clicked.connect(self._clear_path)
        bb.addWidget(btn_clear)
        btn_save = QPushButton("Save")
        btn_save.setProperty("class", "primary")
        btn_save.clicked.connect(self._save)
        bb.addWidget(btn_save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bb.addWidget(btn_cancel)
        lay.addLayout(bb)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load(self):
        path = get_inbox_path()
        self.txt_path.setText(path)
        self._refresh_count()

    def _refresh_count(self):
        count = get_inbox_count()
        if count == 0:
            self.lbl_count.setText("Inbox is empty." if get_inbox_path() else "No inbox folder configured.")
        elif count == 1:
            self.lbl_count.setText("1 file in inbox.")
        else:
            self.lbl_count.setText(f"{count} files in inbox.")

    def _browse(self):
        start = self.txt_path.text() or ""
        folder = QFileDialog.getExistingDirectory(self, "Select Inbox Folder", start)
        if folder:
            self.txt_path.setText(folder)
            self._refresh_count()

    def _clear_path(self):
        self.txt_path.clear()
        self.lbl_count.setText("No inbox folder configured.")

    def _open_folder(self):
        import os, subprocess
        path = self.txt_path.text().strip()
        if path and os.path.isdir(path):
            subprocess.Popen(f'explorer "{path}"')

    def _save(self):
        path = self.txt_path.text().strip()
        save_inbox_config(path, enabled=bool(path))
        self.accept()
