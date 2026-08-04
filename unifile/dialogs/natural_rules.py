"""Natural-language rule compiler and review-first action-plan dialog."""

from __future__ import annotations

import os

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.natural_rules import (
    apply_natural_rule_plan,
    build_natural_rule_plan,
)


class _NaturalRulePlanWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, prompt: str, source_root: str, builder=None, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.source_root = source_root
        self.builder = builder or build_natural_rule_plan

    def run(self) -> None:
        try:
            self.completed.emit(self.builder(self.prompt, self.source_root))
        except Exception as exc:
            self.failed.emit(str(exc))


class _NaturalRuleApplyWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, plan: dict, applier=None, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.applier = applier or apply_natural_rule_plan

    def run(self) -> None:
        try:
            self.completed.emit(self.applier(self.plan, approved=True))
        except Exception as exc:
            self.failed.emit(str(exc))


class NaturalLanguageRulesDialog(QDialog):
    """Compile one natural-language request, preview its actions, then apply."""

    def __init__(self, parent=None, source_root: str = "", plan_builder=None, plan_applier=None):
        super().__init__(parent)
        self.setWindowTitle("Natural Language Rules")
        self.setMinimumSize(980, 650)
        self.setStyleSheet(get_active_stylesheet())
        self._plan_builder = plan_builder
        self._plan_applier = plan_applier
        self._plan = None
        self._plan_worker = None
        self._apply_worker = None
        self._build_ui(source_root)

    def _build_ui(self, source_root: str) -> None:
        theme = get_active_theme()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        root.addWidget(build_dialog_header(
            theme,
            "REVIEW-FIRST AUTOMATION",
            "Natural Language Rules",
            "Describe one routing rule in plain language. UniFile asks the configured provider for a structured rule once, then evaluates files and builds a local action plan. Nothing moves until you review and approve it.",
        ))

        request_box = QGroupBox("Rule request")
        request_form = QFormLayout(request_box)
        request_form.setSpacing(10)
        self.edit_prompt = QPlainTextEdit()
        self.edit_prompt.setPlaceholderText(
            "Example: move screenshots older than 30 days to Archive/Screenshots/YYYY-MM"
        )
        self.edit_prompt.setFixedHeight(76)
        self.edit_prompt.setAccessibleName("Natural language rule request")
        request_form.addRow("Describe the rule:", self.edit_prompt)

        source_row = QHBoxLayout()
        self.edit_source = QLineEdit(str(source_root or ""))
        self.edit_source.setPlaceholderText("Choose the folder whose files may be routed")
        self.edit_source.setAccessibleName("Natural rule source folder")
        source_row.addWidget(self.edit_source, 1)
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.clicked.connect(self._browse_source)
        source_row.addWidget(self.btn_browse)
        request_form.addRow("Source folder:", source_row)
        root.addWidget(request_box)

        action_row = QHBoxLayout()
        self.btn_build = QPushButton("Build review plan")
        self.btn_build.setProperty("class", "primary")
        self.btn_build.setAccessibleName("Build natural language rule review plan")
        self.btn_build.clicked.connect(self._build_plan)
        action_row.addWidget(self.btn_build)
        self.lbl_status = QLabel("No plan built yet.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        action_row.addWidget(self.lbl_status, 1)
        root.addLayout(action_row)

        preview_box = QGroupBox("Action preview")
        preview_layout = QVBoxLayout(preview_box)
        self.lbl_summary = QLabel("The preview will show the exact source and destination for every proposed move.")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {theme['fg_bright']}; font-size: 12px; font-weight: 700;")
        preview_layout.addWidget(self.lbl_summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Source", "Destination", "Why it matches", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setAccessibleName("Natural rule action preview")
        self.table.setAccessibleDescription("Review the files and destinations proposed by the natural language rule")
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 230)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 300)
        preview_layout.addWidget(self.table, 1)
        root.addWidget(preview_box, 1)

        footer = QHBoxLayout()
        self.btn_apply = QPushButton("Apply approved plan")
        self.btn_apply.setProperty("class", "success")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setAccessibleName("Apply approved natural rule plan")
        self.btn_apply.clicked.connect(self._approve_and_apply)
        footer.addWidget(self.btn_apply)
        footer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        root.addLayout(footer)

    def _browse_source(self) -> None:
        current = self.edit_source.text().strip()
        chosen = QFileDialog.getExistingDirectory(self, "Choose rule source folder", current)
        if chosen:
            self.edit_source.setText(chosen)

    def _build_plan(self) -> None:
        if self._plan_worker is not None:
            return
        prompt = self.edit_prompt.toPlainText().strip()
        source = self.edit_source.text().strip()
        if not prompt:
            self.lbl_status.setText("Describe the rule before building a plan.")
            return
        if not os.path.isdir(source):
            self.lbl_status.setText("Choose an existing source folder before building a plan.")
            return
        self._plan = None
        self.btn_build.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.table.setRowCount(0)
        self.lbl_summary.setText("Compiling the rule and scanning the selected folder…")
        self.lbl_status.setText("The provider is parsing the request; file operations are not running.")
        self._plan_worker = _NaturalRulePlanWorker(
            prompt, source, builder=self._plan_builder, parent=self
        )
        self._plan_worker.completed.connect(self._plan_ready)
        self._plan_worker.failed.connect(self._plan_failed)
        self._plan_worker.finished.connect(self._plan_worker_finished)
        self._plan_worker.start()

    def _plan_worker_finished(self) -> None:
        worker = self._plan_worker
        self._plan_worker = None
        self.btn_build.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def _plan_ready(self, plan: dict) -> None:
        self._plan = plan
        stats = plan.get("stats", {})
        actions = plan.get("actions", [])
        self.table.setRowCount(0)
        for action in actions:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(action.get("relative_source", "")),
                str(action.get("relative_destination", "")),
                str(action.get("reason", "")),
                "Pending approval",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeRowsToContents()
        provider = str(plan.get("provider", "") or "local rule compiler")
        self.lbl_summary.setText(
            f"Scanned {stats.get('scanned', 0):,} file(s) · "
            f"matched {stats.get('matched', 0):,} · "
            f"proposed {len(actions):,} move(s) · provider: {provider}."
        )
        self.lbl_status.setText(
            "Review the destinations carefully. Apply remains disabled until this preview is explicitly approved."
            if actions else "No files matched the compiled rule."
        )
        self.btn_apply.setEnabled(bool(actions))

    def _plan_failed(self, message: str) -> None:
        self._plan = None
        self.table.setRowCount(0)
        self.lbl_summary.setText("No review plan was created.")
        self.lbl_status.setText(f"Rule compilation failed: {message}")

    def _approve_and_apply(self) -> None:
        if not self._plan or self._apply_worker is not None:
            return
        count = len(self._plan.get("actions", []))
        answer = QMessageBox.question(
            self,
            "Approve file moves",
            f"Apply the reviewed plan to {count:,} file(s)?\n\n"
            "Existing files will not be overwritten; collisions receive a numeric suffix.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.btn_apply.setEnabled(False)
        self.btn_build.setEnabled(False)
        self.lbl_status.setText("Applying the approved local plan…")
        self._apply_worker = _NaturalRuleApplyWorker(
            self._plan, applier=self._plan_applier, parent=self
        )
        self._apply_worker.completed.connect(self._apply_finished)
        self._apply_worker.failed.connect(self._apply_failed)
        self._apply_worker.finished.connect(self._apply_worker_finished)
        self._apply_worker.start()

    def _apply_worker_finished(self) -> None:
        worker = self._apply_worker
        self._apply_worker = None
        self.btn_build.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def _apply_finished(self, result: dict) -> None:
        applied = int(result.get("applied", 0))
        skipped = int(result.get("skipped", 0))
        errors = result.get("errors", [])
        undo_ops = list(result.get("undo_ops", []) or [])
        undo_error = ""
        if undo_ops:
            try:
                from unifile.cache import append_csv_log, save_undo_log

                save_undo_log(
                    undo_ops,
                    source_dir=str(self._plan.get("source_root", "")),
                    mode="natural-rules",
                    rule=str(self._plan.get("rule", {}).get("name", "")),
                )
                append_csv_log(undo_ops)
                parent = self.parentWidget()
                if parent is not None:
                    parent.undo_ops = undo_ops
                    if hasattr(parent, "btn_undo"):
                        parent.btn_undo.setEnabled(True)
                    if hasattr(parent, "_log"):
                        parent._log(f"Natural rule undo log saved ({len(undo_ops)} move(s))")
            except Exception as exc:
                undo_error = f" Undo log warning: {exc}"
        self.lbl_status.setText(
            f"Applied {applied:,} move(s); skipped {skipped:,}; errors {len(errors):,}. "
            f"Successful moves are available to the existing undo timeline.{undo_error}"
        )
        status_by_id = {
            str(detail.get("id", "")): str(detail.get("status", "")).title()
            for detail in result.get("details", [])
        }
        for row, action in enumerate(self._plan.get("actions", [])):
            item = self.table.item(row, 3)
            if item:
                item.setText(status_by_id.get(str(action.get("id", "")), "Pending"))
        if errors:
            self.lbl_summary.setText("The approved plan completed with one or more errors; review the status message before closing.")
        else:
            self.lbl_summary.setText("Approved plan applied successfully.")

    def _apply_failed(self, message: str) -> None:
        self.lbl_status.setText(f"Applying the approved plan failed: {message}")
        self.btn_apply.setEnabled(True)

    def closeEvent(self, event) -> None:
        for worker in (self._plan_worker, self._apply_worker):
            if worker is not None and worker.isRunning():
                worker.wait(5_000)
        super().closeEvent(event)


__all__ = ["NaturalLanguageRulesDialog"]
