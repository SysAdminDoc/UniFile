"""Qt view for the read-only video project media audit."""

from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet
from unifile.project_awareness import ProjectAudit, apply_project_tags, build_project_audit


class ProjectAuditDialog(QDialog):
    """Show shared, orphaned, and missing project-media references."""

    def __init__(self, source: str = "", library=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project Audit")
        self.setMinimumSize(980, 620)
        self.setStyleSheet(get_active_stylesheet())
        self._library = library
        self._audit: ProjectAudit | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.txt_source = QLineEdit(source if os.path.isdir(source) else "")
        self.txt_source.setPlaceholderText("Project folder or project file…")
        self.txt_source.setAccessibleName("Project audit source")
        self.txt_source.setAccessibleDescription("Folder or project file to inspect for media references")
        header.addWidget(self.txt_source, 1)
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.setAccessibleName("Browse for project audit source")
        self.btn_browse.clicked.connect(self._browse)
        header.addWidget(self.btn_browse)
        self.btn_audit = QPushButton("Run Audit")
        self.btn_audit.setProperty("class", "primary")
        self.btn_audit.setAccessibleName("Run project audit")
        self.btn_audit.clicked.connect(self._run_audit)
        header.addWidget(self.btn_audit)
        layout.addLayout(header)

        self.lbl_summary = QLabel("Choose a project folder, then run the audit.")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setAccessibleName("Project audit summary")
        layout.addWidget(self.lbl_summary)

        self.tabs = QTabWidget()
        self.tbl_shared = self._make_table(["Asset", "Projects", "References"])
        self.tbl_orphaned = self._make_table(["Unreferenced media asset", "Size"])
        self.tbl_missing = self._make_table(["Project", "Referenced path", "Project file"])
        self.tabs.addTab(self.tbl_shared, "Shared Assets")
        self.tabs.addTab(self.tbl_orphaned, "Orphaned Assets")
        self.tabs.addTab(self.tbl_missing, "Missing References")
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setAccessibleName("Project audit status")
        footer.addWidget(self.lbl_status, 1)
        self.btn_apply = QPushButton("Tag Referenced Assets")
        self.btn_apply.setToolTip("Apply project names and modified dates to the open UniFile library")
        self.btn_apply.setAccessibleName("Tag referenced project assets")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply)
        footer.addWidget(self.btn_apply)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        footer.addWidget(self.btn_close)
        layout.addLayout(footer)

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAccessibleName("Project audit results")
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _browse(self):
        source = QFileDialog.getExistingDirectory(self, "Select Project Folder", self.txt_source.text())
        if source:
            self.txt_source.setText(source)

    def _run_audit(self):
        source = self.txt_source.text().strip()
        if not source:
            self.lbl_status.setText("Choose a project folder or file first.")
            return
        try:
            audit = build_project_audit(source)
        except (FileNotFoundError, OSError, ValueError) as exc:
            self._audit = None
            self.btn_apply.setEnabled(False)
            self.lbl_status.setText(f"Audit failed: {type(exc).__name__}: {exc}")
            return
        self._audit = audit
        self._populate(audit)
        self.btn_apply.setEnabled(bool(audit.resolved_references and self._library and self._library.is_open))
        if audit.errors:
            self.lbl_status.setText("Audit completed with errors; see the status count below.")
        else:
            self.lbl_status.setText("Audit complete.")

    def _populate(self, audit: ProjectAudit):
        counts = audit.to_dict()["counts"]
        self.lbl_summary.setText(
            f"{counts['projects']} project(s), {counts['referenced_assets']} referenced asset(s), "
            f"{counts['shared_assets']} shared asset(s), {counts['orphaned_assets']} orphaned asset(s), "
            f"{counts['missing_references']} missing reference(s)."
        )
        self.tbl_shared.setRowCount(0)
        for path, references in sorted(audit.shared_assets.items(), key=lambda item: str(item[0]).casefold()):
            row = self.tbl_shared.rowCount()
            self.tbl_shared.insertRow(row)
            self.tbl_shared.setItem(row, 0, QTableWidgetItem(str(path)))
            names = ", ".join(sorted({reference.project_name for reference in references}, key=str.casefold))
            self.tbl_shared.setItem(row, 1, QTableWidgetItem(names))
            self.tbl_shared.setItem(row, 2, QTableWidgetItem(str(len(references))))
        self.tbl_shared.resizeColumnsToContents()

        self.tbl_orphaned.setRowCount(0)
        for path in audit.orphaned_assets:
            row = self.tbl_orphaned.rowCount()
            self.tbl_orphaned.insertRow(row)
            self.tbl_orphaned.setItem(row, 0, QTableWidgetItem(str(path)))
            try:
                size = f"{path.stat().st_size:,} bytes"
            except OSError:
                size = "unavailable"
            self.tbl_orphaned.setItem(row, 1, QTableWidgetItem(size))
        self.tbl_orphaned.resizeColumnsToContents()

        self.tbl_missing.setRowCount(0)
        for reference in audit.missing_references:
            row = self.tbl_missing.rowCount()
            self.tbl_missing.insertRow(row)
            self.tbl_missing.setItem(row, 0, QTableWidgetItem(reference.project_name))
            self.tbl_missing.setItem(row, 1, QTableWidgetItem(reference.raw_path))
            self.tbl_missing.setItem(row, 2, QTableWidgetItem(str(reference.project_path)))
        self.tbl_missing.resizeColumnsToContents()

    def _apply(self):
        if self._audit is None or self._library is None or not self._library.is_open:
            self.lbl_status.setText("Open a UniFile tag library before applying project metadata.")
            return
        result = apply_project_tags(self._audit, self._library)
        self.lbl_status.setText(
            f"Tagged {result.applied} asset(s); skipped {result.skipped}."
            + (f" Errors: {len(result.errors)}." if result.errors else "")
        )
