"""UniFile dialogs — Cleanup tools (scanner worker, dialog, and panel)."""
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
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
    QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header


class _CleanupScanWorker(QThread):
    """Background worker for cleanup scans."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)  # list of CleanupItem
    item_found = pyqtSignal(object)  # CleanupItem

    def __init__(self, scanner_fn, kwargs):
        super().__init__()
        self._fn = scanner_fn
        self._kwargs = kwargs

    def run(self):
        try:
            results = self._fn(progress_cb=self.progress.emit,
                              item_cb=self.item_found.emit, **self._kwargs)
            self.finished.emit(results)
        except Exception as e:
            self.progress.emit(f"Error: {e}")
            self.finished.emit([])


class CleanupToolsDialog(QDialog):
    """Multi-tab cleanup scanner dialog with Empty Folders, Temp Files,
    Broken Files, Big Files, and Old Downloads scanners."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cleanup Tools")
        self.resize(900, 620)
        self.setStyleSheet(get_active_stylesheet())
        self._results = []
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        # Tab widget
        from PyQt6.QtWidgets import QDoubleSpinBox, QTabWidget
        _t = get_active_theme()
        layout.addWidget(build_dialog_header(
            _t,
            "Cleanup",
            "Cleanup Tools",
            "Inspect clutter, stale downloads, broken files, and oversized items in a calmer review-first workflow before deleting anything."
        ))
        self.lbl_progress = QLabel("Choose a scan type, point UniFile at a folder, and review the results before deleting.")
        self.lbl_progress.setWordWrap(True)
        self.lbl_progress.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        layout.addWidget(self.lbl_progress)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {_t['border']}; background: {_t['bg_alt']}; border-radius: 14px; }}"
            f"QTabBar::tab {{ background: {_t['bg_alt']}; color: {_t['muted']}; padding: 8px 18px;"
            f"border: 1px solid transparent; border-bottom: none; margin-right: 4px;"
            f"font-size: 12px; }}"
            f"QTabBar::tab:selected {{ background: {_t['selection']}; color: {_t['sidebar_btn_active_fg']}; font-weight: 700; border-color: {_t['border']}; }}")

        # ── Empty Folders tab ─────────────────────────────────────────────
        tab_empty = QWidget()
        vb = QVBoxLayout(tab_empty)
        row = QHBoxLayout()
        row.addWidget(QLabel("Scan folder:"))
        self.txt_empty_path = QLineEdit()
        self.txt_empty_path.setPlaceholderText("Select folder to scan for empty directories...")
        row.addWidget(self.txt_empty_path, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(75)
        btn_browse.clicked.connect(lambda: self._browse(self.txt_empty_path))
        row.addWidget(btn_browse)
        vb.addLayout(row)
        opts = QHBoxLayout()
        self.chk_empty_hidden = QCheckBox("Ignore hidden folders")
        self.chk_empty_hidden.setChecked(True)
        opts.addWidget(self.chk_empty_hidden)
        self.chk_empty_system = QCheckBox("Ignore system folders (.git, node_modules, etc)")
        self.chk_empty_system.setChecked(True)
        opts.addWidget(self.chk_empty_system)
        opts.addStretch()
        vb.addLayout(opts)
        self.tabs.addTab(tab_empty, "Empty Folders")

        # ── Empty Files tab ───────────────────────────────────────────────
        tab_zero = QWidget()
        vb2 = QVBoxLayout(tab_zero)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Scan folder:"))
        self.txt_zero_path = QLineEdit()
        self.txt_zero_path.setPlaceholderText("Select folder to scan for zero-byte files...")
        row2.addWidget(self.txt_zero_path, 1)
        btn_b2 = QPushButton("Browse")
        btn_b2.setFixedWidth(75)
        btn_b2.clicked.connect(lambda: self._browse(self.txt_zero_path))
        row2.addWidget(btn_b2)
        vb2.addLayout(row2)
        self.tabs.addTab(tab_zero, "Empty Files")

        # ── Temp Files tab ────────────────────────────────────────────────
        tab_temp = QWidget()
        vb3 = QVBoxLayout(tab_temp)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Scan folder:"))
        self.txt_temp_path = QLineEdit()
        self.txt_temp_path.setPlaceholderText("Select folder to scan for temporary files...")
        row3.addWidget(self.txt_temp_path, 1)
        btn_b3 = QPushButton("Browse")
        btn_b3.setFixedWidth(75)
        btn_b3.clicked.connect(lambda: self._browse(self.txt_temp_path))
        row3.addWidget(btn_b3)
        vb3.addLayout(row3)
        opts3 = QHBoxLayout()
        self.chk_include_logs = QCheckBox("Include log files")
        self.chk_include_logs.setChecked(False)
        opts3.addWidget(self.chk_include_logs)
        opts3.addWidget(QLabel("Min age (days):"))
        self.spn_temp_age = QSpinBox()
        self.spn_temp_age.setRange(0, 365)
        self.spn_temp_age.setValue(0)
        self.spn_temp_age.setFixedWidth(60)
        opts3.addWidget(self.spn_temp_age)
        opts3.addStretch()
        vb3.addLayout(opts3)
        self.tabs.addTab(tab_temp, "Temp Files")

        # ── Broken Files tab ──────────────────────────────────────────────
        tab_broken = QWidget()
        vb4 = QVBoxLayout(tab_broken)
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Scan folder:"))
        self.txt_broken_path = QLineEdit()
        self.txt_broken_path.setPlaceholderText("Select folder to scan for corrupt/broken files...")
        row4.addWidget(self.txt_broken_path, 1)
        btn_b4 = QPushButton("Browse")
        btn_b4.setFixedWidth(75)
        btn_b4.clicked.connect(lambda: self._browse(self.txt_broken_path))
        row4.addWidget(btn_b4)
        vb4.addLayout(row4)
        opts4 = QHBoxLayout()
        self.chk_check_archives = QCheckBox("Validate archive integrity (slower)")
        self.chk_check_archives.setChecked(True)
        opts4.addWidget(self.chk_check_archives)
        opts4.addStretch()
        vb4.addLayout(opts4)
        self.tabs.addTab(tab_broken, "Broken Files")

        # ── Big Files tab ─────────────────────────────────────────────────
        tab_big = QWidget()
        vb5 = QVBoxLayout(tab_big)
        row5 = QHBoxLayout()
        row5.addWidget(QLabel("Scan folder:"))
        self.txt_big_path = QLineEdit()
        self.txt_big_path.setPlaceholderText("Select folder to find large files...")
        row5.addWidget(self.txt_big_path, 1)
        btn_b5 = QPushButton("Browse")
        btn_b5.setFixedWidth(75)
        btn_b5.clicked.connect(lambda: self._browse(self.txt_big_path))
        row5.addWidget(btn_b5)
        vb5.addLayout(row5)
        opts5 = QHBoxLayout()
        opts5.addWidget(QLabel("Minimum size (MB):"))
        self.spn_big_size = QDoubleSpinBox()
        self.spn_big_size.setRange(1.0, 100000.0)
        self.spn_big_size.setValue(100.0)
        self.spn_big_size.setFixedWidth(100)
        opts5.addWidget(self.spn_big_size)
        opts5.addStretch()
        vb5.addLayout(opts5)
        self.tabs.addTab(tab_big, "Big Files")

        # ── Old Downloads tab ─────────────────────────────────────────────
        tab_old = QWidget()
        vb6 = QVBoxLayout(tab_old)
        row6 = QHBoxLayout()
        row6.addWidget(QLabel("Scan folder:"))
        self.txt_old_path = QLineEdit()
        downloads = os.path.expanduser("~/Downloads")
        if os.path.isdir(downloads):
            self.txt_old_path.setText(downloads)
        self.txt_old_path.setPlaceholderText("Typically ~/Downloads")
        row6.addWidget(self.txt_old_path, 1)
        btn_b6 = QPushButton("Browse")
        btn_b6.setFixedWidth(75)
        btn_b6.clicked.connect(lambda: self._browse(self.txt_old_path))
        row6.addWidget(btn_b6)
        vb6.addLayout(row6)
        opts6 = QHBoxLayout()
        opts6.addWidget(QLabel("Older than (days):"))
        self.spn_old_days = QSpinBox()
        self.spn_old_days.setRange(7, 3650)
        self.spn_old_days.setValue(90)
        self.spn_old_days.setFixedWidth(80)
        opts6.addWidget(self.spn_old_days)
        opts6.addStretch()
        vb6.addLayout(opts6)
        self.tabs.addTab(tab_old, "Old Downloads")

        layout.addWidget(self.tabs)

        # ── Scan button + progress ────────────────────────────────────────
        scan_row = QHBoxLayout()
        self.btn_scan = QPushButton("Run Scan")
        self.btn_scan.setFixedHeight(34)
        self.btn_scan.setProperty("class", "success")
        self.btn_scan.clicked.connect(self._start_scan)
        scan_row.addWidget(self.btn_scan)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        scan_row.addWidget(self.lbl_progress, 1)
        layout.addLayout(scan_row)

        # ── Results table ─────────────────────────────────────────────────
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(5)
        self.tbl.setHorizontalHeaderLabels(["", "Path", "Size", "Reason", "Modified"])
        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.tbl.setColumnWidth(0, 30)
        self.tbl.setColumnWidth(2, 80)
        self.tbl.setColumnWidth(3, 200)
        self.tbl.setColumnWidth(4, 140)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setAlternatingRowColors(True)
        layout.addWidget(self.tbl, 1)

        # ── Action buttons ────────────────────────────────────────────────
        action_row = QHBoxLayout()
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-size: 12px;")
        action_row.addWidget(self.lbl_summary, 1)

        btn_select_all = QPushButton("Select All")
        btn_select_all.setProperty("class", "toolbar")
        btn_select_all.clicked.connect(lambda: self._toggle_all(True))
        action_row.addWidget(btn_select_all)
        btn_deselect = QPushButton("Deselect All")
        btn_deselect.setProperty("class", "toolbar")
        btn_deselect.clicked.connect(lambda: self._toggle_all(False))
        action_row.addWidget(btn_deselect)
        btn_invert = QPushButton("Invert Selection")
        btn_invert.setProperty("class", "toolbar")
        btn_invert.clicked.connect(self._invert_selection)
        action_row.addWidget(btn_invert)

        self.btn_delete = QPushButton("Delete Selected")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setProperty("class", "danger")
        self.btn_delete.clicked.connect(self._delete_selected)
        action_row.addWidget(self.btn_delete)
        layout.addLayout(action_row)

    def _browse(self, target: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            target.setText(folder)

    def _start_scan(self):
        from unifile.cleanup import (
            scan_big_files,
            scan_broken_files,
            scan_empty_files,
            scan_empty_folders,
            scan_old_downloads,
            scan_temp_files,
        )

        tab_idx = self.tabs.currentIndex()
        tab_map = {
            0: (scan_empty_folders, self.txt_empty_path, lambda: {
                'root': self.txt_empty_path.text(),
                'ignore_hidden': self.chk_empty_hidden.isChecked(),
                'ignore_system': self.chk_empty_system.isChecked(),
            }),
            1: (scan_empty_files, self.txt_zero_path, lambda: {
                'root': self.txt_zero_path.text(),
            }),
            2: (scan_temp_files, self.txt_temp_path, lambda: {
                'root': self.txt_temp_path.text(),
                'include_logs': self.chk_include_logs.isChecked(),
                'min_age_days': self.spn_temp_age.value(),
            }),
            3: (scan_broken_files, self.txt_broken_path, lambda: {
                'root': self.txt_broken_path.text(),
                'check_archives': self.chk_check_archives.isChecked(),
            }),
            4: (scan_big_files, self.txt_big_path, lambda: {
                'root': self.txt_big_path.text(),
                'min_size_mb': self.spn_big_size.value(),
            }),
            5: (scan_old_downloads, self.txt_old_path, lambda: {
                'root': self.txt_old_path.text(),
                'days_old': self.spn_old_days.value(),
            }),
        }

        scanner_fn, path_field, kwargs_fn = tab_map[tab_idx]
        if not path_field.text() or not os.path.isdir(path_field.text()):
            self.lbl_progress.setText("Please select a valid folder.")
            return

        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Scanning...")
        self.btn_delete.setEnabled(False)
        self.tbl.setRowCount(0)
        self._results = []
        self.lbl_progress.setText("Scanning...")

        kwargs = kwargs_fn()
        self._worker = _CleanupScanWorker(scanner_fn, kwargs)
        self._worker.progress.connect(lambda msg: self.lbl_progress.setText(msg))
        self._worker.item_found.connect(self._on_item_found)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_item_found(self, item):
        """Add a single discovered item to the table immediately."""
        from datetime import datetime

        from unifile.cleanup import _fmt_size

        row = len(self._results)
        self._results.append(item)
        self.tbl.insertRow(row)

        chk = QCheckBox()
        chk.setChecked(item.selected)
        chk.stateChanged.connect(lambda state, r=row: self._on_check(r, state))
        self.tbl.setCellWidget(row, 0, chk)
        self.tbl.setItem(row, 1, QTableWidgetItem(item.path))
        size_txt = _fmt_size(item.size) if item.size > 0 else "-"
        si = QTableWidgetItem(size_txt)
        si.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.tbl.setItem(row, 2, si)
        self.tbl.setItem(row, 3, QTableWidgetItem(item.reason))
        if item.modified > 0:
            dt = datetime.fromtimestamp(item.modified).strftime("%Y-%m-%d %H:%M")
        else:
            dt = "-"
        self.tbl.setItem(row, 4, QTableWidgetItem(dt))

        total_size = sum(r.size for r in self._results)
        self.lbl_summary.setText(
            f"Found {len(self._results)} items ({_fmt_size(total_size)})")

    def _on_scan_done(self, results):
        from unifile.cleanup import _fmt_size
        self.btn_scan.setText("Run Scan")
        self.btn_scan.setEnabled(True)
        total_size = sum(r.size for r in self._results)
        self.lbl_summary.setText(
            f"Found {len(self._results)} items ({_fmt_size(total_size)})")
        self.lbl_progress.setText(f"Scan complete: {len(self._results)} results")
        self.btn_delete.setEnabled(len(self._results) > 0)

    def _on_check(self, row, state):
        if row < len(self._results):
            self._results[row].selected = bool(state)

    def _toggle_all(self, checked: bool):
        for row in range(self.tbl.rowCount()):
            chk = self.tbl.cellWidget(row, 0)
            if chk:
                chk.setChecked(checked)

    def _invert_selection(self):
        for row in range(self.tbl.rowCount()):
            chk = self.tbl.cellWidget(row, 0)
            if chk:
                chk.setChecked(not chk.isChecked())

    def _delete_selected(self):
        selected = [item for item in self._results if item.selected]
        if not selected:
            return

        from unifile.cleanup import _fmt_size, delete_items
        total = sum(i.size for i in selected)
        confirm = QMessageBox.question(
            self, "Confirm Deletion",
            f"Delete {len(selected)} items ({_fmt_size(total)})?\n\n"
            f"Items will be sent to Trash if possible.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.btn_delete.setEnabled(False)
        success, failed, freed = delete_items(
            selected, use_trash=True,
            progress_cb=lambda msg: self.lbl_progress.setText(msg))

        self.lbl_progress.setText(
            f"Deleted {success} items, freed {_fmt_size(freed)}"
            + (f", {failed} failed" if failed else ""))

        # Remove deleted items from results and refresh table
        remaining = [item for item in self._results if os.path.exists(item.path)]
        self._results = []
        self.tbl.setRowCount(0)
        for item in remaining:
            self._on_item_found(item)
        self.btn_delete.setEnabled(len(self._results) > 0)


class CleanupPanel(QWidget):
    """Embeddable cleanup scanner panel — same functionality as CleanupToolsDialog
    but renders inline inside the main window content area."""

    def __init__(self, parent=None, initial_tab: int = 0):
        super().__init__(parent)
        self._results = []
        self._worker = None
        self._build_ui()
        if initial_tab > 0:
            self.tabs.setCurrentIndex(initial_tab)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        from PyQt6.QtWidgets import QDoubleSpinBox, QTabWidget

        _t = get_active_theme()
        header = QWidget()
        header.setStyleSheet(f"background: {_t['bg_alt']}; border-bottom: 1px solid {_t['btn_bg']};")
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(16, 14, 16, 14)
        header_lay.setSpacing(2)
        lbl_title = QLabel("Cleanup Tools")
        lbl_title.setStyleSheet(f"color: {_t['fg_bright']}; font-size: 16px; font-weight: 700;")
        header_lay.addWidget(lbl_title)
        lbl_desc = QLabel("Find clutter, stale downloads, broken files, and oversized items before you decide what should go.")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        header_lay.addWidget(lbl_desc)
        layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {_t['border']}; background: {_t['bg_alt']}; }}"
            f"QTabBar::tab {{ background: {_t['bg_alt']}; color: {_t['muted']}; padding: 8px 18px;"
            f"border: 1px solid {_t['border']}; border-bottom: none; margin-right: 2px;"
            f"font-size: 12px; }}"
            f"QTabBar::tab:selected {{ background: {_t['selection']}; color: {_t['sidebar_btn_active_fg']}; font-weight: 600; }}")

        # ── Empty Folders tab ─────────────────────────────────────────────
        tab_empty = QWidget()
        vb = QVBoxLayout(tab_empty)
        row = QHBoxLayout()
        row.addWidget(QLabel("Scan folder:"))
        self.txt_empty_path = QLineEdit()
        self.txt_empty_path.setPlaceholderText("Select a folder to scan for empty directories…")
        row.addWidget(self.txt_empty_path, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(75)
        btn_browse.clicked.connect(lambda: self._browse(self.txt_empty_path))
        row.addWidget(btn_browse)
        vb.addLayout(row)
        opts = QHBoxLayout()
        self.chk_empty_hidden = QCheckBox("Ignore hidden folders")
        self.chk_empty_hidden.setChecked(True)
        opts.addWidget(self.chk_empty_hidden)
        self.chk_empty_system = QCheckBox("Ignore system folders (.git, node_modules, etc)")
        self.chk_empty_system.setChecked(True)
        opts.addWidget(self.chk_empty_system)
        opts.addStretch()
        vb.addLayout(opts)
        self.tabs.addTab(tab_empty, "Empty Folders")

        # ── Empty Files tab ───────────────────────────────────────────────
        tab_zero = QWidget()
        vb2 = QVBoxLayout(tab_zero)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Scan folder:"))
        self.txt_zero_path = QLineEdit()
        self.txt_zero_path.setPlaceholderText("Select a folder to scan for zero-byte files…")
        row2.addWidget(self.txt_zero_path, 1)
        btn_b2 = QPushButton("Browse")
        btn_b2.setFixedWidth(75)
        btn_b2.clicked.connect(lambda: self._browse(self.txt_zero_path))
        row2.addWidget(btn_b2)
        vb2.addLayout(row2)
        self.tabs.addTab(tab_zero, "Empty Files")

        # ── Temp Files tab ────────────────────────────────────────────────
        tab_temp = QWidget()
        vb3 = QVBoxLayout(tab_temp)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Scan folder:"))
        self.txt_temp_path = QLineEdit()
        self.txt_temp_path.setPlaceholderText("Select a folder to scan for temporary files…")
        row3.addWidget(self.txt_temp_path, 1)
        btn_b3 = QPushButton("Browse")
        btn_b3.setFixedWidth(75)
        btn_b3.clicked.connect(lambda: self._browse(self.txt_temp_path))
        row3.addWidget(btn_b3)
        vb3.addLayout(row3)
        opts3 = QHBoxLayout()
        self.chk_include_logs = QCheckBox("Include log files")
        self.chk_include_logs.setChecked(False)
        opts3.addWidget(self.chk_include_logs)
        opts3.addWidget(QLabel("Min age (days):"))
        self.spn_temp_age = QSpinBox()
        self.spn_temp_age.setRange(0, 365)
        self.spn_temp_age.setValue(0)
        self.spn_temp_age.setFixedWidth(60)
        opts3.addWidget(self.spn_temp_age)
        opts3.addStretch()
        vb3.addLayout(opts3)
        self.tabs.addTab(tab_temp, "Temp Files")

        # ── Broken Files tab ──────────────────────────────────────────────
        tab_broken = QWidget()
        vb4 = QVBoxLayout(tab_broken)
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Scan folder:"))
        self.txt_broken_path = QLineEdit()
        self.txt_broken_path.setPlaceholderText("Select a folder to scan for corrupt or broken files…")
        row4.addWidget(self.txt_broken_path, 1)
        btn_b4 = QPushButton("Browse")
        btn_b4.setFixedWidth(75)
        btn_b4.clicked.connect(lambda: self._browse(self.txt_broken_path))
        row4.addWidget(btn_b4)
        vb4.addLayout(row4)
        opts4 = QHBoxLayout()
        self.chk_check_archives = QCheckBox("Validate archive integrity (slower)")
        self.chk_check_archives.setChecked(True)
        opts4.addWidget(self.chk_check_archives)
        opts4.addStretch()
        vb4.addLayout(opts4)
        self.tabs.addTab(tab_broken, "Broken Files")

        # ── Big Files tab ─────────────────────────────────────────────────
        tab_big = QWidget()
        vb5 = QVBoxLayout(tab_big)
        row5 = QHBoxLayout()
        row5.addWidget(QLabel("Scan folder:"))
        self.txt_big_path = QLineEdit()
        self.txt_big_path.setPlaceholderText("Select a folder to find large files…")
        row5.addWidget(self.txt_big_path, 1)
        btn_b5 = QPushButton("Browse")
        btn_b5.setFixedWidth(75)
        btn_b5.clicked.connect(lambda: self._browse(self.txt_big_path))
        row5.addWidget(btn_b5)
        vb5.addLayout(row5)
        opts5 = QHBoxLayout()
        opts5.addWidget(QLabel("Minimum size (MB):"))
        self.spn_big_size = QDoubleSpinBox()
        self.spn_big_size.setRange(1.0, 100000.0)
        self.spn_big_size.setValue(100.0)
        self.spn_big_size.setFixedWidth(100)
        opts5.addWidget(self.spn_big_size)
        opts5.addStretch()
        vb5.addLayout(opts5)
        self.tabs.addTab(tab_big, "Big Files")

        # ── Old Downloads tab ─────────────────────────────────────────────
        tab_old = QWidget()
        vb6 = QVBoxLayout(tab_old)
        row6 = QHBoxLayout()
        row6.addWidget(QLabel("Scan folder:"))
        self.txt_old_path = QLineEdit()
        downloads = os.path.expanduser("~/Downloads")
        if os.path.isdir(downloads):
            self.txt_old_path.setText(downloads)
        self.txt_old_path.setPlaceholderText("Typically ~/Downloads")
        row6.addWidget(self.txt_old_path, 1)
        btn_b6 = QPushButton("Browse")
        btn_b6.setFixedWidth(75)
        btn_b6.clicked.connect(lambda: self._browse(self.txt_old_path))
        row6.addWidget(btn_b6)
        vb6.addLayout(row6)
        opts6 = QHBoxLayout()
        opts6.addWidget(QLabel("Older than (days):"))
        self.spn_old_days = QSpinBox()
        self.spn_old_days.setRange(7, 3650)
        self.spn_old_days.setValue(90)
        self.spn_old_days.setFixedWidth(80)
        opts6.addWidget(self.spn_old_days)
        opts6.addStretch()
        vb6.addLayout(opts6)
        self.tabs.addTab(tab_old, "Old Downloads")

        layout.addWidget(self.tabs)

        # ── Scan button + progress ────────────────────────────────────────
        scan_row = QHBoxLayout()
        self.btn_scan = QPushButton("Run Scan")
        self.btn_scan.setFixedHeight(34)
        self.btn_scan.setProperty("class", "success")
        self.btn_scan.clicked.connect(self._start_scan)
        scan_row.addWidget(self.btn_scan)
        scan_row.addWidget(self.lbl_progress, 1)
        layout.addLayout(scan_row)

        # ── Results table ─────────────────────────────────────────────────
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(5)
        self.tbl.setHorizontalHeaderLabels(["", "Path", "Size", "Reason", "Modified"])
        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.tbl.setColumnWidth(0, 30)
        self.tbl.setColumnWidth(2, 80)
        self.tbl.setColumnWidth(3, 200)
        self.tbl.setColumnWidth(4, 140)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setAlternatingRowColors(True)
        layout.addWidget(self.tbl, 1)

        # ── Action buttons ────────────────────────────────────────────────
        action_row = QHBoxLayout()
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-size: 12px;")
        action_row.addWidget(self.lbl_summary, 1)

        btn_select_all = QPushButton("Select All")
        btn_select_all.setProperty("class", "toolbar")
        btn_select_all.clicked.connect(lambda: self._toggle_all(True))
        action_row.addWidget(btn_select_all)
        btn_deselect = QPushButton("Deselect All")
        btn_deselect.setProperty("class", "toolbar")
        btn_deselect.clicked.connect(lambda: self._toggle_all(False))
        action_row.addWidget(btn_deselect)
        btn_invert = QPushButton("Invert Selection")
        btn_invert.setProperty("class", "toolbar")
        btn_invert.clicked.connect(self._invert_selection)
        action_row.addWidget(btn_invert)

        self.btn_delete = QPushButton("Remove Selected")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setProperty("class", "danger")
        self.btn_delete.clicked.connect(self._delete_selected)
        action_row.addWidget(self.btn_delete)
        layout.addLayout(action_row)

    def _browse(self, target: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            target.setText(folder)

    def _start_scan(self):
        from unifile.cleanup import (
            scan_big_files,
            scan_broken_files,
            scan_empty_files,
            scan_empty_folders,
            scan_old_downloads,
            scan_temp_files,
        )
        tab_idx = self.tabs.currentIndex()
        tab_map = {
            0: (scan_empty_folders, self.txt_empty_path, lambda: {
                'root': self.txt_empty_path.text(),
                'ignore_hidden': self.chk_empty_hidden.isChecked(),
                'ignore_system': self.chk_empty_system.isChecked(),
            }),
            1: (scan_empty_files, self.txt_zero_path, lambda: {
                'root': self.txt_zero_path.text(),
            }),
            2: (scan_temp_files, self.txt_temp_path, lambda: {
                'root': self.txt_temp_path.text(),
                'include_logs': self.chk_include_logs.isChecked(),
                'min_age_days': self.spn_temp_age.value(),
            }),
            3: (scan_broken_files, self.txt_broken_path, lambda: {
                'root': self.txt_broken_path.text(),
                'check_archives': self.chk_check_archives.isChecked(),
            }),
            4: (scan_big_files, self.txt_big_path, lambda: {
                'root': self.txt_big_path.text(),
                'min_size_mb': self.spn_big_size.value(),
            }),
            5: (scan_old_downloads, self.txt_old_path, lambda: {
                'root': self.txt_old_path.text(),
                'days_old': self.spn_old_days.value(),
            }),
        }
        scanner_fn, path_field, kwargs_fn = tab_map[tab_idx]
        if not path_field.text() or not os.path.isdir(path_field.text()):
            self.lbl_progress.setText("Choose a valid folder to scan.")
            return
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Scanning…")
        self.btn_delete.setEnabled(False)
        self.tbl.setRowCount(0)
        self._results = []
        self.lbl_progress.setText("Scanning…")
        kwargs = kwargs_fn()
        self._worker = _CleanupScanWorker(scanner_fn, kwargs)
        self._worker.progress.connect(lambda msg: self.lbl_progress.setText(msg))
        self._worker.item_found.connect(self._on_item_found)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_item_found(self, item):
        """Add a single discovered item to the table immediately."""
        from datetime import datetime

        from unifile.cleanup import _fmt_size

        row = len(self._results)
        self._results.append(item)
        self.tbl.insertRow(row)

        chk = QCheckBox()
        chk.setChecked(item.selected)
        chk.stateChanged.connect(lambda state, r=row: self._on_check(r, state))
        self.tbl.setCellWidget(row, 0, chk)
        self.tbl.setItem(row, 1, QTableWidgetItem(item.path))
        size_txt = _fmt_size(item.size) if item.size > 0 else "-"
        si = QTableWidgetItem(size_txt)
        si.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.tbl.setItem(row, 2, si)
        self.tbl.setItem(row, 3, QTableWidgetItem(item.reason))
        if item.modified > 0:
            dt = datetime.fromtimestamp(item.modified).strftime("%Y-%m-%d %H:%M")
        else:
            dt = "-"
        self.tbl.setItem(row, 4, QTableWidgetItem(dt))

        total_size = sum(r.size for r in self._results)
        self.lbl_summary.setText(
            f"Found {len(self._results)} items ({_fmt_size(total_size)})")

    def _on_scan_done(self, results):
        from unifile.cleanup import _fmt_size
        self.btn_scan.setText("Run Scan")
        self.btn_scan.setEnabled(True)
        total_size = sum(r.size for r in self._results)
        self.lbl_summary.setText(
            f"Found {len(self._results)} item{'s' if len(self._results) != 1 else ''} ({_fmt_size(total_size)})")
        self.lbl_progress.setText(
            f"Scan complete — {len(self._results)} result{'s' if len(self._results) != 1 else ''}"
        )
        self.btn_delete.setEnabled(len(self._results) > 0)

    def _on_check(self, row, state):
        if row < len(self._results):
            self._results[row].selected = bool(state)

    def _toggle_all(self, checked: bool):
        for row in range(self.tbl.rowCount()):
            chk = self.tbl.cellWidget(row, 0)
            if chk:
                chk.setChecked(checked)

    def _invert_selection(self):
        for row in range(self.tbl.rowCount()):
            chk = self.tbl.cellWidget(row, 0)
            if chk:
                chk.setChecked(not chk.isChecked())

    def _delete_selected(self):
        selected = [item for item in self._results if item.selected]
        if not selected:
            return
        from unifile.cleanup import _fmt_size, delete_items
        total = sum(i.size for i in selected)
        confirm = QMessageBox.question(
            self, "Confirm Deletion",
            f"Delete {len(selected)} items ({_fmt_size(total)})?\n\n"
            f"Items will be sent to Trash when possible.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.btn_delete.setEnabled(False)
        success, failed, freed = delete_items(
            selected, use_trash=True,
            progress_cb=lambda msg: self.lbl_progress.setText(msg))
        self.lbl_progress.setText(
            f"Deleted {success} items, freed {_fmt_size(freed)}"
            + (f", {failed} failed" if failed else ""))
        remaining = [item for item in self._results if os.path.exists(item.path)]
        self._results = []
        self.tbl.setRowCount(0)
        for item in remaining:
            self._on_item_found(item)
        self.btn_delete.setEnabled(len(self._results) > 0)
