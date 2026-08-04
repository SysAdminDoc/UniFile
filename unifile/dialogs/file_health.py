"""Non-destructive file-integrity verification dialog."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.file_health import FileHealthError, FileHealthMonitor, export_health_log


class _HealthVerifyWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, monitor: FileHealthMonitor, scope: str, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.scope = scope

    def run(self) -> None:
        try:
            self.completed.emit(self.monitor.verify(self.scope))
        except Exception as exc:
            self.failed.emit(str(exc))


class FileHealthDialog(QDialog):
    """Show integrity counts and a row-level digest diff for a selected scope."""

    verification_complete = pyqtSignal(object)

    def __init__(self, source: str | Path, parent=None):
        super().__init__(parent)
        self.source = Path(source).expanduser().resolve()
        self.monitor: FileHealthMonitor | None = None
        self._worker: _HealthVerifyWorker | None = None
        self._report: dict = {}
        self.setWindowTitle("File Health Monitor")
        self.setMinimumSize(900, 560)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()
        self._load_latest()

    def _build_ui(self) -> None:
        theme = get_active_theme()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        root.addWidget(build_dialog_header(
            theme,
            "Integrity",
            "File Health Monitor",
            "Verify SHA-256 digests without changing files. New files establish a baseline; unexpected edits, missing files, and unstable reads appear in the diff below.",
        ))

        self.lbl_scope = QLabel(f"Scope: {self.source}")
        self.lbl_scope.setWordWrap(True)
        self.lbl_scope.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        root.addWidget(self.lbl_scope)

        self.lbl_summary = QLabel("Not verified yet")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {theme['fg_bright']}; font-size: 13px; font-weight: 700;")
        root.addWidget(self.lbl_summary)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Change", "Path", "Expected SHA-256", "Actual SHA-256"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setAccessibleName("File health differences")
        self.table.setAccessibleDescription("Unexpected, expected, missing, or unstable file integrity changes")
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 320)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.btn_verify = QPushButton("Verify Now")
        self.btn_verify.setProperty("class", "apply")
        self.btn_verify.setAccessibleName("Verify file integrity now")
        self.btn_verify.clicked.connect(self._verify)
        buttons.addWidget(self.btn_verify)
        self.btn_export = QPushButton("Export Log…")
        self.btn_export.setAccessibleName("Export file health log")
        self.btn_export.clicked.connect(self._export)
        buttons.addWidget(self.btn_export)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _load_latest(self) -> None:
        try:
            self.monitor = FileHealthMonitor(self.source)
            self._set_report(self.monitor.latest_report())
        except FileHealthError as exc:
            self._set_report({"status": "error", "error": str(exc), "diff": []})
            self.btn_verify.setEnabled(False)

    def _set_report(self, report: dict) -> None:
        self._report = dict(report or {})
        status = self._report.get("status", "not-verified")
        if status == "not-verified":
            self.lbl_summary.setText("Not verified yet — click Verify Now to establish a baseline.")
        else:
            self.lbl_summary.setText(
                f"{status.upper()} · {self._report.get('files_verified', 0)} verified · "
                f"{self._report.get('changed_unexpectedly', 0)} changed unexpectedly · "
                f"{self._report.get('missing', 0)} missing · "
                f"{self._report.get('errors', 0)} errors"
            )
            if self._report.get("error"):
                self.lbl_summary.setText(f"ERROR · {self._report['error']}")
        self.table.setRowCount(0)
        for diff in self._report.get("diff", []):
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(diff.get("change", "")),
                str(diff.get("path", "")),
                str(diff.get("expected_sha256", "")),
                str(diff.get("actual_sha256", "")),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeRowsToContents()

    def _verify(self) -> None:
        if self._worker is not None or self.monitor is None:
            return
        self.btn_verify.setEnabled(False)
        self.lbl_summary.setText("Hashing files…")
        self._worker = _HealthVerifyWorker(self.monitor, str(self.source), self)
        self._worker.completed.connect(self._verification_finished)
        self._worker.failed.connect(self._verification_failed)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self.btn_verify.setEnabled(True)

    def _verification_finished(self, report) -> None:
        self._set_report(report)
        self.verification_complete.emit(report)

    def _verification_failed(self, message: str) -> None:
        self._set_report({"status": "error", "error": message, "diff": []})

    def _export(self) -> None:
        if not self._report or self._report.get("status") == "not-verified":
            QMessageBox.information(self, "File Health", "Run a verification before exporting a log.")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, selected = QFileDialog.getSaveFileName(
            self, "Export File Health Log", f"file_health_{stamp}.json",
            "JSON (*.json);;CSV (*.csv);;Text (*.txt)",
        )
        if not path:
            return
        try:
            fmt = "csv" if selected.startswith("CSV") else "txt" if selected.startswith("Text") else "json"
            export_health_log(self._report, path, fmt=fmt)
            self.lbl_summary.setText(f"Log exported: {path}")
        except (FileHealthError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "File Health", f"Could not export the log:\n{exc}")

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5_000)
        super().closeEvent(event)


__all__ = ["FileHealthDialog"]
