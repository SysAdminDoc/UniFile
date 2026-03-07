"""UniFile — Duplicate finder dialogs and panels."""
import os, shutil
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QCheckBox, QHeaderView, QFileDialog, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QDialog, QMessageBox,
    QProgressBar, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap

from unifile.config import get_active_theme, get_active_stylesheet
from unifile.workers import format_size


class DuplicateCompareDialog(QDialog):
    """Side-by-side panel for duplicate groups with thumbnails, dates, 'keep best'."""

    def __init__(self, file_items, group_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate Comparison")
        self.setMinimumSize(700, 450)
        self.setStyleSheet(get_active_stylesheet())
        self.file_items = file_items
        self._groups = self._build_groups()
        self._current_idx = 0
        if group_id is not None:
            for i, (gid, _) in enumerate(self._groups):
                if gid == group_id:
                    self._current_idx = i
                    break

        lay = QVBoxLayout(self)

        # Navigation
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("< Prev Group")
        self.btn_prev.clicked.connect(self._prev_group)
        nav.addWidget(self.btn_prev)
        self.lbl_group = QLabel("")
        _t = get_active_theme()
        self.lbl_group.setStyleSheet(f"color: {_t['fg_bright']}; font-size: 13px; font-weight: bold;")
        self.lbl_group.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self.lbl_group, 1)
        self.btn_next = QPushButton("Next Group >")
        self.btn_next.clicked.connect(self._next_group)
        nav.addWidget(self.btn_next)
        lay.addLayout(nav)

        # Scrollable comparison area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"QScrollArea {{ background: {_t['header_bg']}; border: none; }}")
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        lay.addWidget(self.scroll, 1)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_auto = QPushButton("Auto-Select Best")
        btn_auto.setStyleSheet(f"QPushButton {{ background: {_t['green_pressed']}; color: {_t['green']}; border: 1px solid {_t['sidebar_profile_border']}; border-radius: 4px; padding: 6px 12px; }} QPushButton:hover {{ background: {_t['green_hover']}; }}")
        btn_auto.clicked.connect(self._auto_select)
        btn_row.addWidget(btn_auto)
        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        self._show_group()

    def _build_groups(self):
        groups = {}
        for it in self.file_items:
            if it.dup_group > 0:
                groups.setdefault(it.dup_group, []).append(it)
        return sorted(groups.items())

    def _show_group(self):
        # Clear
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        if not self._groups:
            self.lbl_group.setText("No duplicate groups found")
            return
        gid, items = self._groups[self._current_idx]
        self.lbl_group.setText(f"Group #{gid} -- {len(items)} files  ({self._current_idx + 1}/{len(self._groups)})")
        self.btn_prev.setEnabled(self._current_idx > 0)
        self.btn_next.setEnabled(self._current_idx < len(self._groups) - 1)
        best = self._pick_best(items)
        _t = get_active_theme()
        for it in items:
            row_w = QWidget()
            row_w.setStyleSheet(
                "QWidget { background: %s; border: 1px solid %s; border-radius: 6px; padding: 6px; margin: 2px; }"
                % (_t['bg'], _t['green'] if it is best else _t['btn_bg']))
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(8, 6, 8, 6)
            # Thumbnail
            lbl_thumb = QLabel()
            lbl_thumb.setFixedSize(60, 60)
            ext = os.path.splitext(it.name)[1].lower()
            if ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}:
                pix = QPixmap(it.full_src)
                if not pix.isNull():
                    lbl_thumb.setPixmap(pix.scaled(58, 58, Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))
            row_lay.addWidget(lbl_thumb)
            # Info
            info_lay = QVBoxLayout()
            lbl_name = QLabel(it.name)
            lbl_name.setStyleSheet(f"color: {_t['fg_bright']}; font-weight: bold; font-size: 12px;")
            info_lay.addWidget(lbl_name)
            sz_str = f"{it.size:,} bytes" if it.size else "Unknown size"
            try:
                mt = datetime.fromtimestamp(os.path.getmtime(it.full_src)).strftime('%Y-%m-%d %H:%M')
            except Exception:
                mt = "?"
            lbl_detail = QLabel(f"{sz_str}  |  {mt}  |  {it.dup_detail}")
            lbl_detail.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
            info_lay.addWidget(lbl_detail)
            row_lay.addLayout(info_lay, 1)
            # Keep badge
            if it is best:
                badge = QLabel("KEEP")
                badge.setStyleSheet(f"color: {_t['green']}; font-weight: bold; font-size: 11px; background: {_t['green_pressed']}; padding: 2px 8px; border-radius: 3px;")
                row_lay.addWidget(badge)
            elif it.is_duplicate:
                badge = QLabel("DUP")
                badge.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px; background: #3e2e1a; padding: 2px 8px; border-radius: 3px;")  # semantic: warning
                row_lay.addWidget(badge)
            self.scroll_layout.addWidget(row_w)
        self.scroll_layout.addStretch()

    @staticmethod
    def _pick_best(items):
        """Pick the best file from a duplicate group: largest + newest."""
        if not items:
            return None
        scored = []
        for it in items:
            score = 0
            score += it.size if it.size else 0
            try:
                score += os.path.getmtime(it.full_src)
            except Exception:
                pass
            scored.append((score, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _auto_select(self):
        if not self._groups:
            return
        _, items = self._groups[self._current_idx]
        best = self._pick_best(items)
        for it in items:
            it.is_duplicate = (it is not best)
            it.dup_is_original = (it is best)
            it.selected = (it is best)
        self._show_group()

    def _prev_group(self):
        if self._current_idx > 0:
            self._current_idx -= 1
            self._show_group()

    def _next_group(self):
        if self._current_idx < len(self._groups) - 1:
            self._current_idx += 1
            self._show_group()


class _DupScanWorker(QThread):
    """Background worker for duplicate scanning."""
    progress = pyqtSignal(str)
    stage = pyqtSignal(int, int)  # current_file, total
    finished = pyqtSignal(dict)   # dup_map from ProgressiveDuplicateDetector

    def __init__(self, root, opts):
        super().__init__()
        self.root = root
        self.opts = opts
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from unifile.duplicates import ProgressiveDuplicateDetector
        try:
            # Collect files
            self.progress.emit("Collecting files...")
            entries = []
            depth = self.opts.get('depth', 99)
            root_depth = self.root.rstrip(os.sep).count(os.sep)

            for dirpath, dirnames, filenames in os.walk(self.root):
                if self._cancelled:
                    self.finished.emit({})
                    return
                current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
                if current_depth > depth:
                    dirnames.clear()
                    continue
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    try:
                        sz = os.path.getsize(fpath)
                        if sz >= self.opts.get('min_size', 1):
                            entries.append((fpath, sz))
                    except OSError:
                        continue

            self.progress.emit(f"Scanning {len(entries)} files for duplicates...")
            det = ProgressiveDuplicateDetector(
                enable_perceptual=self.opts.get('perceptual', True),
                enable_audio=self.opts.get('audio', True),
            )

            def _prog(cur, total):
                self.stage.emit(cur, total)

            result = det.detect(entries, log_cb=self.progress.emit,
                                progress_cb=_prog)
            self.finished.emit(result)

        except Exception as e:
            self.progress.emit(f"Error: {e}")
            self.finished.emit({})


class DuplicateFinderDialog(QDialog):
    """User-friendly duplicate file finder with grouped results,
    size summary, and batch actions (delete, hardlink, move)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate Finder")
        self.resize(1000, 680)
        self.setStyleSheet(get_active_stylesheet())
        self._dup_map = {}
        self._groups = {}  # group_id -> [paths]
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QLabel("Find duplicate and similar files using content hashing, "
                      "perceptual image matching, and audio fingerprinting.")
        hdr.setWordWrap(True)
        hdr.setStyleSheet(f"color: {_t['muted']}; font-size: 12px; padding: 4px 0;")
        lay.addWidget(hdr)

        # ── Folder selector ───────────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Scan folder:"))
        self.txt_path = QLineEdit()
        self.txt_path.setPlaceholderText("Select a folder to scan for duplicates...")
        row1.addWidget(self.txt_path, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(75)
        btn_browse.clicked.connect(self._browse)
        row1.addWidget(btn_browse)
        lay.addLayout(row1)

        # ── Options row ───────────────────────────────────────────────────
        opts = QHBoxLayout()
        opts.setSpacing(16)
        self.chk_perceptual = QCheckBox("Similar images (perceptual hash)")
        self.chk_perceptual.setChecked(True)
        self.chk_perceptual.setToolTip("Find images that look the same even if resized, "
                                        "compressed, or watermarked")
        opts.addWidget(self.chk_perceptual)

        self.chk_audio = QCheckBox("Similar audio (acoustic fingerprint)")
        self.chk_audio.setChecked(True)
        self.chk_audio.setToolTip("Find songs/audio that sound the same even in different "
                                   "formats or bitrates.\nRequires Chromaprint (fpcalc) installed.")
        opts.addWidget(self.chk_audio)

        opts.addWidget(QLabel("Min size:"))
        self.spn_min = QComboBox()
        self.spn_min.addItems(["No minimum", "1 KB", "64 KB", "1 MB", "10 MB", "100 MB"])
        self.spn_min.setCurrentIndex(1)
        self.spn_min.setFixedWidth(110)
        opts.addWidget(self.spn_min)

        opts.addStretch()
        lay.addLayout(opts)

        # ── Scan button + progress ────────────────────────────────────────
        scan_row = QHBoxLayout()
        self._scan_btn_style = (
            f"QPushButton {{ background: {_t['green']}; color: white; font-weight: bold;"
            f"border-radius: 4px; padding: 4px 16px; font-size: 13px; }}"
            f"QPushButton:hover {{ background: {_t['green_hover']}; }}"
            f"QPushButton:disabled {{ background: {_t['btn_bg']}; color: {_t['disabled']}; }}")
        self.btn_scan = QPushButton("Scan for Duplicates")
        self.btn_scan.setFixedHeight(34)
        self.btn_scan.setStyleSheet(self._scan_btn_style)
        self.btn_scan.clicked.connect(self._start_scan)
        scan_row.addWidget(self.btn_scan)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(18)
        self.progress.setVisible(False)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {_t['bg_alt']}; border: 1px solid {_t['border']}; border-radius: 4px;"
            f"text-align: center; color: {_t['sidebar_btn_active_fg']}; font-size: 10px; }}"
            f"QProgressBar::chunk {{ background: {_t['green']}; border-radius: 3px; }}")
        scan_row.addWidget(self.progress, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        scan_row.addWidget(self.lbl_status)
        lay.addLayout(scan_row)

        # ── Results tree (grouped by duplicate set) ───────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "File", "Size", "Modified", "Match Type"])
        self.tree.setColumnWidth(0, 30)
        self.tree.setColumnWidth(1, 400)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 140)
        self.tree.setColumnWidth(4, 140)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setRootIsDecorated(True)
        lay.addWidget(self.tree, 1)

        # ── Summary + Actions ─────────────────────────────────────────────
        summary_row = QHBoxLayout()
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-size: 12px; font-weight: 600;")
        summary_row.addWidget(self.lbl_summary, 1)
        lay.addLayout(summary_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.btn_select_dupes = QPushButton("Auto-Select Duplicates")
        self.btn_select_dupes.setToolTip("Keep the best file in each group, select the rest for deletion")
        self.btn_select_dupes.setEnabled(False)
        self.btn_select_dupes.clicked.connect(self._auto_select)
        action_row.addWidget(self.btn_select_dupes)

        self.btn_select_none = QPushButton("Deselect All")
        self.btn_select_none.setEnabled(False)
        self.btn_select_none.clicked.connect(self._deselect_all)
        action_row.addWidget(self.btn_select_none)

        action_row.addStretch()

        # Action combo
        action_row.addWidget(QLabel("Action:"))
        self.cmb_action = QComboBox()
        self.cmb_action.addItems([
            "Delete (send to Trash)",
            "Delete permanently",
            "Replace with hard links",
            "Move to folder...",
        ])
        self.cmb_action.setFixedWidth(200)
        action_row.addWidget(self.cmb_action)

        self.btn_apply = QPushButton("Apply to Selected")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet(
            f"QPushButton {{ background: {_t['btn_bg']}; color: #ef4444; font-weight: bold;"
            f"border: 1px solid #5c2e2e; border-radius: 4px; padding: 4px 18px; }}"
            f"QPushButton:hover {{ background: #4a1a1a; color: #fca5a5; }}"
            f"QPushButton:disabled {{ background: {_t['btn_bg']}; color: {_t['disabled']}; }}")
        self.btn_apply.clicked.connect(self._apply_action)
        action_row.addWidget(self.btn_apply)

        lay.addLayout(action_row)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Scan")
        if folder:
            self.txt_path.setText(folder)

    def _get_min_size(self) -> int:
        """Parse the min size combo into bytes."""
        idx = self.spn_min.currentIndex()
        return [0, 1024, 65536, 1048576, 10485760, 104857600][idx]

    def _start_scan(self):
        path = self.txt_path.text().strip()
        if not path or not os.path.isdir(path):
            self.lbl_status.setText("Please select a valid folder.")
            return

        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Scanning...")
        self.btn_select_dupes.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.tree.clear()
        self.progress.setVisible(True)
        self.progress.setValue(0)

        opts = {
            'depth': 99,
            'min_size': self._get_min_size(),
            'perceptual': self.chk_perceptual.isChecked(),
            'audio': self.chk_audio.isChecked(),
        }

        self._worker = _DupScanWorker(path, opts)
        self._worker.progress.connect(lambda msg: self.lbl_status.setText(msg))
        self._worker.stage.connect(self._on_stage_progress)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_stage_progress(self, cur, total):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(cur)

    def _on_scan_done(self, dup_map):
        self._dup_map = dup_map
        self.btn_scan.setText("Scan for Duplicates")
        self.btn_scan.setEnabled(True)
        self.progress.setVisible(False)

        if not dup_map:
            self.lbl_status.setText("No duplicates found.")
            self.lbl_summary.setText("")
            return

        # Group results
        self._groups = {}
        for path, info in dup_map.items():
            self._groups.setdefault(info.group_id, []).append((path, info))

        # Sort groups: largest wasted space first
        sorted_groups = sorted(self._groups.items(),
                               key=lambda g: sum(os.path.getsize(p)
                                                 for p, i in g[1] if not i.is_original),
                               reverse=True)

        total_waste = 0
        total_dupes = 0

        for gid, members in sorted_groups:
            members.sort(key=lambda x: (not x[1].is_original, x[0]))
            first = members[0]
            match_type = "Audio" if "(audio" in first[1].detail else \
                         "Visual" if first[1].is_perceptual else "Exact"

            # Group header
            try:
                group_size = sum(os.path.getsize(p) for p, _ in members)
                waste = sum(os.path.getsize(p) for p, i in members if not i.is_original)
            except OSError:
                group_size = 0
                waste = 0

            header = QTreeWidgetItem([
                "", f"Group {gid} — {len(members)} files",
                format_size(group_size), "", match_type
            ])
            header.setForeground(1, QColor("#4fc3f7"))
            header.setForeground(4, QColor("#a78bfa") if match_type != "Exact"
                                 else QColor("#4ade80"))
            self.tree.addTopLevelItem(header)

            for path, info in members:
                try:
                    sz = os.path.getsize(path)
                    mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
                except OSError:
                    sz = 0
                    mtime = "-"

                tag = "KEEP" if info.is_original else "DUPLICATE"
                child = QTreeWidgetItem([
                    "", path, format_size(sz), mtime, tag
                ])
                child.setCheckState(0, Qt.CheckState.Unchecked)

                if info.is_original:
                    child.setForeground(4, QColor("#4ade80"))
                else:
                    child.setForeground(4, QColor("#f87171"))
                    total_dupes += 1
                    total_waste += sz

                child.setData(0, Qt.ItemDataRole.UserRole, path)
                child.setData(1, Qt.ItemDataRole.UserRole, info)
                header.addChild(child)

            header.setExpanded(True)

        self.lbl_summary.setText(
            f"{len(self._groups)} duplicate groups  |  "
            f"{total_dupes} duplicate files  |  "
            f"{format_size(total_waste)} wasted space")
        self.lbl_status.setText("Scan complete.")
        self.btn_select_dupes.setEnabled(True)
        self.btn_select_none.setEnabled(True)
        self.btn_apply.setEnabled(True)

    def _auto_select(self):
        """Auto-check all non-original (duplicate) files for action."""
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                info = child.data(1, Qt.ItemDataRole.UserRole)
                if info and not info.is_original:
                    child.setCheckState(0, Qt.CheckState.Checked)
                else:
                    child.setCheckState(0, Qt.CheckState.Unchecked)

    def _deselect_all(self):
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                group.child(j).setCheckState(0, Qt.CheckState.Unchecked)

    def _get_checked_paths(self) -> list:
        """Collect all checked file paths."""
        paths = []
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    path = child.data(0, Qt.ItemDataRole.UserRole)
                    if path:
                        paths.append(path)
        return paths

    def _apply_action(self):
        paths = self._get_checked_paths()
        if not paths:
            self.lbl_status.setText("No files selected.")
            return

        action_idx = self.cmb_action.currentIndex()

        total_size = sum(os.path.getsize(p) for p in paths if os.path.exists(p))
        confirm = QMessageBox.question(
            self, "Confirm Action",
            f"Apply action to {len(paths)} files ({format_size(total_size)})?\n\n"
            f"Action: {self.cmb_action.currentText()}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        from unifile.workers import action_delete, action_hardlink

        success = 0
        failed = 0

        if action_idx in (0, 1):  # Delete (trash or permanent)
            use_trash = (action_idx == 0)
            for p in paths:
                ok, detail = action_delete(p, use_trash=use_trash)
                if ok:
                    success += 1
                else:
                    failed += 1

        elif action_idx == 2:  # Replace with hard links
            # For each checked file, find its group's original and hardlink
            for i in range(self.tree.topLevelItemCount()):
                group = self.tree.topLevelItem(i)
                original_path = None
                checked_in_group = []
                for j in range(group.childCount()):
                    child = group.child(j)
                    info = child.data(1, Qt.ItemDataRole.UserRole)
                    path = child.data(0, Qt.ItemDataRole.UserRole)
                    if info and info.is_original:
                        original_path = path
                    if child.checkState(0) == Qt.CheckState.Checked and path:
                        checked_in_group.append(path)

                if original_path:
                    for p in checked_in_group:
                        ok, detail = action_hardlink(original_path, p)
                        if ok:
                            success += 1
                        else:
                            failed += 1

        elif action_idx == 3:  # Move to folder
            dest = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
            if not dest:
                return
            for p in paths:
                try:
                    shutil.move(p, os.path.join(dest, os.path.basename(p)))
                    success += 1
                except Exception:
                    failed += 1

        self.lbl_status.setText(
            f"Done: {success} succeeded" + (f", {failed} failed" if failed else ""))

        # Refresh — re-scan to update tree
        if success > 0:
            self._start_scan()


class DuplicatePanel(QWidget):
    """Embeddable duplicate finder panel — same functionality as DuplicateFinderDialog
    but renders inline inside the main window content area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dup_map = {}
        self._groups = {}
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(0, 0, 0, 0)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QLabel("Find duplicate and similar files using content hashing, "
                      "perceptual image matching, and audio fingerprinting.")
        hdr.setWordWrap(True)
        hdr.setStyleSheet(f"color: {_t['muted']}; font-size: 12px; padding: 4px 0;")
        lay.addWidget(hdr)

        # ── Folder selector ───────────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Scan folder:"))
        self.txt_path = QLineEdit()
        self.txt_path.setPlaceholderText("Select a folder to scan for duplicates...")
        row1.addWidget(self.txt_path, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(75)
        btn_browse.clicked.connect(self._browse)
        row1.addWidget(btn_browse)
        lay.addLayout(row1)

        # ── Options row ───────────────────────────────────────────────────
        opts = QHBoxLayout()
        opts.setSpacing(16)
        self.chk_perceptual = QCheckBox("Similar images (perceptual hash)")
        self.chk_perceptual.setChecked(True)
        self.chk_perceptual.setToolTip("Find images that look the same even if resized, "
                                        "compressed, or watermarked")
        opts.addWidget(self.chk_perceptual)

        self.chk_audio = QCheckBox("Similar audio (acoustic fingerprint)")
        self.chk_audio.setChecked(True)
        self.chk_audio.setToolTip("Find songs/audio that sound the same even in different "
                                   "formats or bitrates.\nRequires Chromaprint (fpcalc) installed.")
        opts.addWidget(self.chk_audio)

        opts.addWidget(QLabel("Min size:"))
        self.spn_min = QComboBox()
        self.spn_min.addItems(["No minimum", "1 KB", "64 KB", "1 MB", "10 MB", "100 MB"])
        self.spn_min.setCurrentIndex(1)
        self.spn_min.setFixedWidth(110)
        opts.addWidget(self.spn_min)
        opts.addStretch()
        lay.addLayout(opts)

        # ── Scan button + progress ────────────────────────────────────────
        scan_row = QHBoxLayout()
        self._scan_btn_style = (
            f"QPushButton {{ background: {_t['green']}; color: white; font-weight: bold;"
            f"border-radius: 4px; padding: 4px 16px; font-size: 13px; }}"
            f"QPushButton:hover {{ background: {_t['green_hover']}; }}"
            f"QPushButton:disabled {{ background: {_t['btn_bg']}; color: {_t['disabled']}; }}")
        self.btn_scan = QPushButton("Scan for Duplicates")
        self.btn_scan.setFixedHeight(34)
        self.btn_scan.setStyleSheet(self._scan_btn_style)
        self.btn_scan.clicked.connect(self._start_scan)
        scan_row.addWidget(self.btn_scan)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(18)
        self.progress.setVisible(False)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {_t['bg_alt']}; border: 1px solid {_t['border']}; border-radius: 4px;"
            f"text-align: center; color: {_t['sidebar_btn_active_fg']}; font-size: 10px; }}"
            f"QProgressBar::chunk {{ background: {_t['green']}; border-radius: 3px; }}")
        scan_row.addWidget(self.progress, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        scan_row.addWidget(self.lbl_status)
        lay.addLayout(scan_row)

        # ── Results tree (grouped by duplicate set) ───────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "File", "Size", "Modified", "Match Type"])
        self.tree.setColumnWidth(0, 30)
        self.tree.setColumnWidth(1, 400)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 140)
        self.tree.setColumnWidth(4, 140)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setRootIsDecorated(True)
        lay.addWidget(self.tree, 1)

        # ── Summary + Actions ─────────────────────────────────────────────
        summary_row = QHBoxLayout()
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-size: 12px; font-weight: 600;")
        summary_row.addWidget(self.lbl_summary, 1)
        lay.addLayout(summary_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.btn_select_dupes = QPushButton("Auto-Select Duplicates")
        self.btn_select_dupes.setToolTip("Keep the best file in each group, select the rest")
        self.btn_select_dupes.setEnabled(False)
        self.btn_select_dupes.clicked.connect(self._auto_select)
        action_row.addWidget(self.btn_select_dupes)

        self.btn_select_none = QPushButton("Deselect All")
        self.btn_select_none.setEnabled(False)
        self.btn_select_none.clicked.connect(self._deselect_all)
        action_row.addWidget(self.btn_select_none)

        action_row.addStretch()

        action_row.addWidget(QLabel("Action:"))
        self.cmb_action = QComboBox()
        self.cmb_action.addItems([
            "Delete (send to Trash)",
            "Delete permanently",
            "Replace with hard links",
            "Move to folder...",
        ])
        self.cmb_action.setFixedWidth(200)
        action_row.addWidget(self.cmb_action)

        self.btn_apply = QPushButton("Apply to Selected")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet(
            f"QPushButton {{ background: {_t['btn_bg']}; color: #ef4444; font-weight: bold;"
            f"border: 1px solid #5c2e2e; border-radius: 4px; padding: 4px 18px; }}"
            f"QPushButton:hover {{ background: #4a1a1a; color: #fca5a5; }}"
            f"QPushButton:disabled {{ background: {_t['btn_bg']}; color: {_t['disabled']}; }}")
        self.btn_apply.clicked.connect(self._apply_action)
        action_row.addWidget(self.btn_apply)
        lay.addLayout(action_row)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Scan")
        if folder:
            self.txt_path.setText(folder)

    def _get_min_size(self) -> int:
        idx = self.spn_min.currentIndex()
        return [0, 1024, 65536, 1048576, 10485760, 104857600][idx]

    def _start_scan(self):
        path = self.txt_path.text().strip()
        if not path or not os.path.isdir(path):
            self.lbl_status.setText("Please select a valid folder.")
            return
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Scanning...")
        self.btn_select_dupes.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.tree.clear()
        self.progress.setVisible(True)
        self.progress.setValue(0)
        opts = {
            'depth': 99,
            'min_size': self._get_min_size(),
            'perceptual': self.chk_perceptual.isChecked(),
            'audio': self.chk_audio.isChecked(),
        }
        self._worker = _DupScanWorker(path, opts)
        self._worker.progress.connect(lambda msg: self.lbl_status.setText(msg))
        self._worker.stage.connect(self._on_stage_progress)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_stage_progress(self, cur, total):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(cur)

    def _on_scan_done(self, dup_map):
        self._dup_map = dup_map
        self.btn_scan.setText("Scan for Duplicates")
        self.btn_scan.setEnabled(True)
        self.progress.setVisible(False)
        if not dup_map:
            self.lbl_status.setText("No duplicates found.")
            self.lbl_summary.setText("")
            return
        self._groups = {}
        for path, info in dup_map.items():
            self._groups.setdefault(info.group_id, []).append((path, info))
        sorted_groups = sorted(self._groups.items(),
                               key=lambda g: sum(os.path.getsize(p)
                                                 for p, i in g[1] if not i.is_original),
                               reverse=True)
        total_waste = 0
        total_dupes = 0
        for gid, members in sorted_groups:
            members.sort(key=lambda x: (not x[1].is_original, x[0]))
            first = members[0]
            match_type = "Audio" if "(audio" in first[1].detail else \
                         "Visual" if first[1].is_perceptual else "Exact"
            try:
                group_size = sum(os.path.getsize(p) for p, _ in members)
                waste = sum(os.path.getsize(p) for p, i in members if not i.is_original)
            except OSError:
                group_size = 0
                waste = 0
            header = QTreeWidgetItem([
                "", f"Group {gid} -- {len(members)} files",
                format_size(group_size), "", match_type
            ])
            header.setForeground(1, QColor("#4fc3f7"))
            header.setForeground(4, QColor("#a78bfa") if match_type != "Exact"
                                 else QColor("#4ade80"))
            self.tree.addTopLevelItem(header)
            for path, info in members:
                try:
                    sz = os.path.getsize(path)
                    mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
                except OSError:
                    sz = 0
                    mtime = "-"
                tag = "KEEP" if info.is_original else "DUPLICATE"
                child = QTreeWidgetItem([
                    "", path, format_size(sz), mtime, tag
                ])
                child.setCheckState(0, Qt.CheckState.Unchecked)
                if info.is_original:
                    child.setForeground(4, QColor("#4ade80"))
                else:
                    child.setForeground(4, QColor("#f87171"))
                    total_dupes += 1
                    total_waste += sz
                child.setData(0, Qt.ItemDataRole.UserRole, path)
                child.setData(1, Qt.ItemDataRole.UserRole, info)
                header.addChild(child)
            header.setExpanded(True)
        self.lbl_summary.setText(
            f"{len(self._groups)} duplicate groups  |  "
            f"{total_dupes} duplicate files  |  "
            f"{format_size(total_waste)} wasted space")
        self.lbl_status.setText("Scan complete.")
        self.btn_select_dupes.setEnabled(True)
        self.btn_select_none.setEnabled(True)
        self.btn_apply.setEnabled(True)

    def _auto_select(self):
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                info = child.data(1, Qt.ItemDataRole.UserRole)
                if info and not info.is_original:
                    child.setCheckState(0, Qt.CheckState.Checked)
                else:
                    child.setCheckState(0, Qt.CheckState.Unchecked)

    def _deselect_all(self):
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                group.child(j).setCheckState(0, Qt.CheckState.Unchecked)

    def _get_checked_paths(self) -> list:
        paths = []
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    path = child.data(0, Qt.ItemDataRole.UserRole)
                    if path:
                        paths.append(path)
        return paths

    def _apply_action(self):
        paths = self._get_checked_paths()
        if not paths:
            self.lbl_status.setText("No files selected.")
            return
        action_idx = self.cmb_action.currentIndex()
        total_size = sum(os.path.getsize(p) for p in paths if os.path.exists(p))
        confirm = QMessageBox.question(
            self, "Confirm Action",
            f"Apply action to {len(paths)} files ({format_size(total_size)})?\n\n"
            f"Action: {self.cmb_action.currentText()}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        from unifile.workers import action_delete, action_hardlink
        import shutil
        success = 0
        failed = 0
        if action_idx in (0, 1):
            use_trash = (action_idx == 0)
            for p in paths:
                ok, detail = action_delete(p, use_trash=use_trash)
                if ok:
                    success += 1
                else:
                    failed += 1
        elif action_idx == 2:
            for i in range(self.tree.topLevelItemCount()):
                group = self.tree.topLevelItem(i)
                original_path = None
                checked_in_group = []
                for j in range(group.childCount()):
                    child = group.child(j)
                    info = child.data(1, Qt.ItemDataRole.UserRole)
                    path = child.data(0, Qt.ItemDataRole.UserRole)
                    if info and info.is_original:
                        original_path = path
                    if child.checkState(0) == Qt.CheckState.Checked and path:
                        checked_in_group.append(path)
                if original_path:
                    for p in checked_in_group:
                        ok, detail = action_hardlink(original_path, p)
                        if ok:
                            success += 1
                        else:
                            failed += 1
        elif action_idx == 3:
            dest = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
            if not dest:
                return
            for p in paths:
                try:
                    shutil.move(p, os.path.join(dest, os.path.basename(p)))
                    success += 1
                except Exception:
                    failed += 1
        self.lbl_status.setText(
            f"Done: {success} succeeded" + (f", {failed} failed" if failed else ""))
        if success > 0:
            self._start_scan()
