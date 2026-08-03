"""UniFile — Duplicate finder dialogs and panels."""
import os
import shutil
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.workers import format_size


def _duplicate_match_type(info) -> str:
    """Return the stable result type used by both duplicate surfaces."""
    if getattr(info, "is_semantic", False):
        return "Semantic"
    if "(audio" in info.detail.lower():
        return "Audio"
    return "Visual" if info.is_perceptual else "Exact"


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _new_duplicate_tree() -> QTreeWidget:
    tree = QTreeWidget()
    tree.setHeaderLabels(["", "File", "Size", "Modified", "Match Type"])
    tree.setColumnWidth(0, 30)
    tree.setColumnWidth(1, 400)
    tree.setColumnWidth(2, 80)
    tree.setColumnWidth(3, 140)
    tree.setColumnWidth(4, 140)
    tree.setAlternatingRowColors(True)
    tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    tree.setRootIsDecorated(True)
    return tree


def _populate_duplicate_tree(tree: QTreeWidget, groups: dict) -> tuple[int, int, int]:
    """Populate a result tree and return (groups, duplicate_count, wasted_bytes)."""
    tree.clear()
    total_waste = 0
    total_dupes = 0
    for gid, members in sorted(
        groups.items(),
        key=lambda group: sum(_file_size(path) for path, info in group[1]
                              if not info.is_original),
        reverse=True,
    ):
        members.sort(key=lambda item: (not item[1].is_original, item[0]))
        first = members[0]
        match_type = _duplicate_match_type(first[1])
        group_size = sum(_file_size(path) for path, _ in members)
        header = QTreeWidgetItem([
            "", f"Group {gid} — {len(members)} files",
            format_size(group_size), "", match_type,
        ])
        header.setForeground(1, QColor("#4fc3f7"))
        header.setForeground(4, QColor("#a78bfa") if match_type != "Exact"
                             else QColor("#4ade80"))
        tree.addTopLevelItem(header)

        for path, info in members:
            try:
                size = os.path.getsize(path)
                modified = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            except OSError:
                size = 0
                modified = "-"
            child = QTreeWidgetItem([
                "", path, format_size(size), modified,
                "KEEP" if info.is_original else "DUPLICATE",
            ])
            child.setCheckState(0, Qt.CheckState.Unchecked)
            child.setForeground(4, QColor("#4ade80") if info.is_original
                                else QColor("#f87171"))
            child.setData(0, Qt.ItemDataRole.UserRole, path)
            child.setData(1, Qt.ItemDataRole.UserRole, info)
            header.addChild(child)
            if not info.is_original:
                total_dupes += 1
                total_waste += size
        header.setExpanded(True)
    return len(groups), total_dupes, total_waste


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
        btn_auto.setProperty("class", "success")
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
            _border = _t['green'] if it is best else _t['btn_bg']
            row_w.setStyleSheet(
                f"QWidget {{ background: {_t['bg']}; border: 1px solid {_border}; "
                "border-radius: 6px; padding: 6px; margin: 2px; }}")
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
        self.total_scanned = 0
        self.total_skipped = 0

    def cancel(self):
        self._cancelled = True

    def run(self):
        from unifile.duplicates import ProgressiveDuplicateDetector
        try:
            self.progress.emit("Collecting files...")
            entries = []
            skipped = 0
            depth = self.opts.get('depth', 99)
            root_depth = self.root.rstrip(os.sep).count(os.sep)
            min_size = self.opts.get('min_size', 1)

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
                        if sz >= min_size:
                            entries.append((fpath, sz))
                        else:
                            skipped += 1
                    except OSError:
                        skipped += 1

            self.total_scanned = len(entries)
            self.total_skipped = skipped
            self.progress.emit(f"Scanning {len(entries)} files for duplicates...")
            det = ProgressiveDuplicateDetector(
                enable_perceptual=self.opts.get('perceptual', True),
                enable_audio=self.opts.get('audio', True),
                enable_semantic=self.opts.get('semantic', False),
                semantic_threshold=self.opts.get('semantic_threshold', 0.92),
                semantic_model_dir=self.opts.get('semantic_model_dir'),
                semantic_provider=self.opts.get('semantic_provider', 'auto'),
                semantic_batch_size=self.opts.get('semantic_batch_size', 32),
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
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)

        # ── Header ────────────────────────────────────────────────────────
        lay.addWidget(build_dialog_header(
            _t,
            "Duplicates",
            "Duplicate Finder",
            "Review exact and likely duplicates using content hashes, perceptual image matching, optional semantic image embeddings, and audio fingerprinting before you remove anything."
        ))
        self.lbl_status = QLabel("Choose a folder to scan, then review duplicate groups before applying an action.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_status)

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

        # Chromaprint availability check — surface fpcalc status so users
        # don't wonder why audio matches aren't showing up.
        from unifile.duplicates import _find_fpcalc
        fpcalc_path = _find_fpcalc()
        self.chk_audio = QCheckBox(
            "Similar audio (acoustic fingerprint)"
            if fpcalc_path else
            "Similar audio  —  requires Chromaprint  (install fpcalc)"
        )
        self.chk_audio.setChecked(bool(fpcalc_path))
        self.chk_audio.setEnabled(bool(fpcalc_path))
        tip = ("Find songs/audio that sound the same even in different "
               "formats or bitrates.")
        if fpcalc_path:
            tip += f"\nChromaprint detected: {fpcalc_path}"
        else:
            tip += ("\n\nChromaprint (`fpcalc`) is not on PATH. Install it "
                    "from https://acoustid.org/chromaprint and restart UniFile.")
        self.chk_audio.setToolTip(tip)
        opts.addWidget(self.chk_audio)

        self.chk_semantic = QCheckBox("Semantic duplicates (CLIP/SigLIP)")
        self.chk_semantic.setChecked(False)
        self.chk_semantic.setToolTip(
            "Optional local ONNX image embeddings. Enable only after selecting an exported "
            "CLIP/SigLIP image model below; no model is downloaded automatically."
        )
        opts.addWidget(self.chk_semantic)

        opts.addWidget(QLabel("Threshold:"))
        from unifile.clip_duplicates import load_clip_settings
        clip_settings = load_clip_settings()
        self.spn_semantic_threshold = QDoubleSpinBox()
        self.spn_semantic_threshold.setRange(0.80, 0.99)
        self.spn_semantic_threshold.setSingleStep(0.01)
        self.spn_semantic_threshold.setDecimals(2)
        self.spn_semantic_threshold.setValue(clip_settings["threshold"])
        self.spn_semantic_threshold.setFixedWidth(70)
        self.spn_semantic_threshold.setToolTip(
            "Cosine similarity required for a semantic duplicate; higher values are stricter."
        )
        opts.addWidget(self.spn_semantic_threshold)

        opts.addWidget(QLabel("Min size:"))
        self.spn_min = QComboBox()
        self.spn_min.addItems(["No minimum", "1 KB", "64 KB", "1 MB", "10 MB", "100 MB"])
        self.spn_min.setCurrentIndex(1)
        self.spn_min.setFixedWidth(110)
        opts.addWidget(self.spn_min)

        opts.addStretch()
        lay.addLayout(opts)

        semantic_model_row = QHBoxLayout()
        semantic_model_row.addWidget(QLabel("Local image model:"))
        self.txt_semantic_model = QLineEdit(clip_settings["model_dir"])
        self.txt_semantic_model.setPlaceholderText(
            "Folder containing model.onnx or vision_model.onnx"
        )
        semantic_model_row.addWidget(self.txt_semantic_model, 1)
        btn_semantic_browse = QPushButton("Browse")
        btn_semantic_browse.setFixedWidth(75)
        btn_semantic_browse.clicked.connect(self._browse_semantic_model)
        semantic_model_row.addWidget(btn_semantic_browse)
        lay.addLayout(semantic_model_row)

        # ── Match-type filter row — hides groups of unwanted types ────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)
        filter_row.addWidget(QLabel("Show:"))
        self.cmb_type_filter = QComboBox()
        self.cmb_type_filter.addItems([
            "All match types",
            "Exact matches only",
            "Visual (image) matches only",
            "Audio matches only",
        ])
        self.cmb_type_filter.setFixedWidth(200)
        self.cmb_type_filter.setToolTip(
            "Filter the results tree to show only one kind of duplicate group."
        )
        self.cmb_type_filter.currentIndexChanged.connect(self._apply_type_filter)
        filter_row.addWidget(self.cmb_type_filter)
        filter_row.addStretch()
        lay.addLayout(filter_row)

        # ── Scan button + progress ────────────────────────────────────────
        scan_row = QHBoxLayout()
        self.btn_scan = QPushButton("Scan for Duplicates")
        self.btn_scan.setFixedHeight(34)
        self.btn_scan.setProperty("class", "success")
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

        scan_row.addWidget(self.lbl_status)
        lay.addLayout(scan_row)

        # ── Results tabs (hash/audio vs semantic image matches) ───────────
        self.result_tabs = QTabWidget()
        hash_page = QWidget()
        hash_layout = QVBoxLayout(hash_page)
        hash_layout.setContentsMargins(0, 8, 0, 0)
        self.tree = _new_duplicate_tree()
        hash_layout.addWidget(self.tree)
        self.result_tabs.addTab(hash_page, "Hash & Audio")

        semantic_page = QWidget()
        semantic_layout = QVBoxLayout(semantic_page)
        semantic_layout.setContentsMargins(0, 8, 0, 0)
        semantic_hint = QLabel(
            "Semantic Duplicates uses the selected local CLIP/SigLIP ONNX model and the "
            "configured cosine threshold. Exact and perceptual-hash matches are kept in the first tab."
        )
        semantic_hint.setWordWrap(True)
        semantic_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        semantic_layout.addWidget(semantic_hint)
        self.semantic_tree = _new_duplicate_tree()
        semantic_layout.addWidget(self.semantic_tree)
        self.result_tabs.addTab(semantic_page, "Semantic Duplicates")
        lay.addWidget(self.result_tabs, 1)

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
        self.btn_select_dupes.setProperty("class", "toolbar")
        self.btn_select_dupes.clicked.connect(self._auto_select)
        action_row.addWidget(self.btn_select_dupes)

        self.btn_select_none = QPushButton("Deselect All")
        self.btn_select_none.setEnabled(False)
        self.btn_select_none.setProperty("class", "toolbar")
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
        self.btn_apply.setProperty("class", "danger")
        self.btn_apply.clicked.connect(self._apply_action)
        action_row.addWidget(self.btn_apply)

        lay.addLayout(action_row)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Scan")
        if folder:
            self.txt_path.setText(folder)

    def _browse_semantic_model(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Local CLIP/SigLIP Model Folder")
        if folder:
            self.txt_semantic_model.setText(folder)

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
        self.semantic_tree.clear()
        self.progress.setVisible(True)
        self.progress.setValue(0)

        opts = {
            'depth': 99,
            'min_size': self._get_min_size(),
            'perceptual': self.chk_perceptual.isChecked(),
            'audio': self.chk_audio.isChecked(),
            'semantic': self.chk_semantic.isChecked(),
            'semantic_threshold': self.spn_semantic_threshold.value(),
            'semantic_model_dir': self.txt_semantic_model.text().strip(),
        }
        from unifile.clip_duplicates import save_clip_settings
        save_clip_settings({
            'model_dir': opts['semantic_model_dir'],
            'threshold': opts['semantic_threshold'],
        })

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
            scanned = getattr(self._worker, 'total_scanned', 0)
            skipped = getattr(self._worker, 'total_skipped', 0)
            criteria = []
            if self.chk_perceptual.isChecked(): criteria.append("perceptual image hash")
            if self.chk_semantic.isChecked(): criteria.append("semantic CLIP/SigLIP embeddings")
            if self.chk_audio.isChecked() and self.chk_audio.isEnabled(): criteria.append("audio fingerprint")
            criteria.append("SHA-256 content hash")
            criteria_str = ", ".join(criteria)
            parts = [f"No duplicates found among {scanned} file{'s' if scanned != 1 else ''}"]
            if skipped:
                parts.append(f"{skipped} file{'s' if skipped != 1 else ''} skipped (below minimum size)")
            parts.append(f"Criteria used: {criteria_str}")
            self.lbl_status.setText(". ".join(parts) + ".")
            self.lbl_summary.setText("")
            return

        # Group results
        self._groups = {}
        for path, info in dup_map.items():
            self._groups.setdefault(info.group_id, []).append((path, info))

        hash_groups = {
            gid: members for gid, members in self._groups.items()
            if _duplicate_match_type(members[0][1]) != "Semantic"
        }
        semantic_groups = {
            gid: members for gid, members in self._groups.items()
            if _duplicate_match_type(members[0][1]) == "Semantic"
        }
        _populate_duplicate_tree(self.tree, hash_groups)
        _populate_duplicate_tree(self.semantic_tree, semantic_groups)
        total_waste = sum(
            _file_size(path) for members in self._groups.values()
            for path, info in members if not info.is_original
        )
        total_dupes = sum(
            1 for members in self._groups.values()
            for _, info in members if not info.is_original
        )

        self.lbl_summary.setText(
            f"{len(self._groups)} duplicate groups  |  "
            f"{total_dupes} duplicate files  |  "
            f"{format_size(total_waste)} wasted space")
        self.lbl_status.setText("Scan complete.")
        self.btn_select_dupes.setEnabled(True)
        self.btn_select_none.setEnabled(True)
        self.btn_apply.setEnabled(True)
        # Reset filter to "All" after fresh scan (previous filter may hide
        # brand-new results the user expects to see).
        if hasattr(self, 'cmb_type_filter'):
            self.cmb_type_filter.blockSignals(True)
            self.cmb_type_filter.setCurrentIndex(0)
            self.cmb_type_filter.blockSignals(False)
            self._apply_type_filter()

    def _apply_type_filter(self):
        """Hide/show top-level groups based on the selected match type filter."""
        if self.tree.topLevelItemCount() == 0:
            return
        # Filter index → allowed match types. Empty set means "show all".
        idx = self.cmb_type_filter.currentIndex() if hasattr(self, 'cmb_type_filter') else 0
        allowed = {
            0: None,
            1: {'Exact'},
            2: {'Visual'},
            3: {'Audio'},
        }.get(idx)
        shown = 0
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            match_type = group.text(4)
            visible = allowed is None or match_type in allowed
            group.setHidden(not visible)
            if visible:
                shown += 1
        # Status line so users know why results may look trimmed
        if allowed is not None:
            total = self.tree.topLevelItemCount()
            self.lbl_status.setText(
                f"Showing {shown} of {total} duplicate group{'s' if total != 1 else ''} "
                f"(filter: {self.cmb_type_filter.currentText()})."
            )

    def _auto_select(self):
        """Auto-check all non-original (duplicate) files for action."""
        for tree in self._result_trees():
            for i in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(i)
                for j in range(group.childCount()):
                    child = group.child(j)
                    info = child.data(1, Qt.ItemDataRole.UserRole)
                    if info and not info.is_original:
                        child.setCheckState(0, Qt.CheckState.Checked)
                    else:
                        child.setCheckState(0, Qt.CheckState.Unchecked)

    def _deselect_all(self):
        for tree in self._result_trees():
            for i in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(i)
                for j in range(group.childCount()):
                    group.child(j).setCheckState(0, Qt.CheckState.Unchecked)

    def _get_checked_paths(self) -> list:
        """Collect all checked file paths."""
        paths = []
        for tree in self._result_trees():
            for i in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(i)
                for j in range(group.childCount()):
                    child = group.child(j)
                    if child.checkState(0) == Qt.CheckState.Checked:
                        path = child.data(0, Qt.ItemDataRole.UserRole)
                        if path:
                            paths.append(path)
        return paths

    def _result_trees(self):
        return (self.tree, self.semantic_tree)

    def _apply_action(self):
        paths = self._get_checked_paths()
        if not paths:
            self.lbl_status.setText("No files selected.")
            return

        action_idx = self.cmb_action.currentIndex()

        total_size = sum(_file_size(path) for path in paths)
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
            for tree in self._result_trees():
                for i in range(tree.topLevelItemCount()):
                    group = tree.topLevelItem(i)
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

        header = QWidget()
        header.setStyleSheet(f"background: {_t['bg_alt']}; border-bottom: 1px solid {_t['btn_bg']};")
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(16, 14, 16, 14)
        header_lay.setSpacing(2)
        lbl_title = QLabel("Duplicate Finder")
        lbl_title.setStyleSheet(f"color: {_t['fg_bright']}; font-size: 16px; font-weight: 700;")
        header_lay.addWidget(lbl_title)
        hdr = QLabel("Review exact and likely duplicates using content hashes, perceptual image matching, optional semantic image embeddings, and audio fingerprinting.")
        hdr.setWordWrap(True)
        hdr.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        header_lay.addWidget(hdr)
        lay.addWidget(header)

        # ── Folder selector ───────────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Scan folder:"))
        self.txt_path = QLineEdit()
        self.txt_path.setPlaceholderText("Select a folder to scan for duplicates…")
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

        from unifile.duplicates import _find_fpcalc as _find_fpcalc_panel
        _fpcalc_panel = _find_fpcalc_panel()
        self.chk_audio = QCheckBox(
            "Similar audio (acoustic fingerprint)"
            if _fpcalc_panel else
            "Similar audio  —  requires Chromaprint  (install fpcalc)"
        )
        self.chk_audio.setChecked(bool(_fpcalc_panel))
        self.chk_audio.setEnabled(bool(_fpcalc_panel))
        _tip = ("Find songs/audio that sound the same even in different "
                "formats or bitrates.")
        if _fpcalc_panel:
            _tip += f"\nChromaprint detected: {_fpcalc_panel}"
        else:
            _tip += ("\n\nChromaprint (`fpcalc`) is not on PATH. Install it "
                     "from https://acoustid.org/chromaprint and restart UniFile.")
        self.chk_audio.setToolTip(_tip)
        opts.addWidget(self.chk_audio)

        self.chk_semantic = QCheckBox("Semantic duplicates (CLIP/SigLIP)")
        self.chk_semantic.setChecked(False)
        self.chk_semantic.setToolTip(
            "Optional local ONNX image embeddings. Select an exported CLIP/SigLIP "
            "model below; no model is downloaded automatically."
        )
        opts.addWidget(self.chk_semantic)
        opts.addWidget(QLabel("Threshold:"))
        from unifile.clip_duplicates import load_clip_settings
        clip_settings = load_clip_settings()
        self.spn_semantic_threshold = QDoubleSpinBox()
        self.spn_semantic_threshold.setRange(0.80, 0.99)
        self.spn_semantic_threshold.setSingleStep(0.01)
        self.spn_semantic_threshold.setDecimals(2)
        self.spn_semantic_threshold.setValue(clip_settings["threshold"])
        self.spn_semantic_threshold.setFixedWidth(70)
        self.spn_semantic_threshold.setToolTip(
            "Cosine similarity required for a semantic duplicate; higher values are stricter."
        )
        opts.addWidget(self.spn_semantic_threshold)

        opts.addWidget(QLabel("Min size:"))
        self.spn_min = QComboBox()
        self.spn_min.addItems(["No minimum", "1 KB", "64 KB", "1 MB", "10 MB", "100 MB"])
        self.spn_min.setCurrentIndex(1)
        self.spn_min.setFixedWidth(110)
        opts.addWidget(self.spn_min)
        opts.addStretch()
        lay.addLayout(opts)

        semantic_model_row = QHBoxLayout()
        semantic_model_row.addWidget(QLabel("Local image model:"))
        self.txt_semantic_model = QLineEdit(clip_settings["model_dir"])
        self.txt_semantic_model.setPlaceholderText(
            "Folder containing model.onnx or vision_model.onnx"
        )
        semantic_model_row.addWidget(self.txt_semantic_model, 1)
        btn_semantic_browse = QPushButton("Browse")
        btn_semantic_browse.setFixedWidth(75)
        btn_semantic_browse.clicked.connect(self._browse_semantic_model)
        semantic_model_row.addWidget(btn_semantic_browse)
        lay.addLayout(semantic_model_row)

        # Match-type filter for the panel too, mirroring the standalone dialog.
        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)
        filter_row.addWidget(QLabel("Show:"))
        self.cmb_type_filter = QComboBox()
        self.cmb_type_filter.addItems([
            "All match types",
            "Exact matches only",
            "Visual (image) matches only",
            "Audio matches only",
        ])
        self.cmb_type_filter.setFixedWidth(200)
        self.cmb_type_filter.currentIndexChanged.connect(self._apply_type_filter)
        filter_row.addWidget(self.cmb_type_filter)
        filter_row.addStretch()
        lay.addLayout(filter_row)

        # ── Scan button + progress ────────────────────────────────────────
        scan_row = QHBoxLayout()
        self.btn_scan = QPushButton("Scan for Duplicates")
        self.btn_scan.setFixedHeight(34)
        self.btn_scan.setProperty("class", "success")
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

        # ── Results tabs (hash/audio vs semantic image matches) ───────────
        self.result_tabs = QTabWidget()
        hash_page = QWidget()
        hash_layout = QVBoxLayout(hash_page)
        hash_layout.setContentsMargins(0, 8, 0, 0)
        self.tree = _new_duplicate_tree()
        hash_layout.addWidget(self.tree)
        self.result_tabs.addTab(hash_page, "Hash & Audio")

        semantic_page = QWidget()
        semantic_layout = QVBoxLayout(semantic_page)
        semantic_layout.setContentsMargins(0, 8, 0, 0)
        semantic_hint = QLabel(
            "Semantic Duplicates uses the selected local CLIP/SigLIP ONNX model and "
            "cosine threshold. Hash and audio matches remain in the first tab."
        )
        semantic_hint.setWordWrap(True)
        semantic_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        semantic_layout.addWidget(semantic_hint)
        self.semantic_tree = _new_duplicate_tree()
        semantic_layout.addWidget(self.semantic_tree)
        self.result_tabs.addTab(semantic_page, "Semantic Duplicates")
        lay.addWidget(self.result_tabs, 1)

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
        self.btn_select_dupes.setProperty("class", "toolbar")
        self.btn_select_dupes.clicked.connect(self._auto_select)
        action_row.addWidget(self.btn_select_dupes)

        self.btn_select_none = QPushButton("Deselect All")
        self.btn_select_none.setEnabled(False)
        self.btn_select_none.setProperty("class", "toolbar")
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
        self.btn_apply.setProperty("class", "danger")
        self.btn_apply.clicked.connect(self._apply_action)
        action_row.addWidget(self.btn_apply)
        lay.addLayout(action_row)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Scan")
        if folder:
            self.txt_path.setText(folder)

    def _browse_semantic_model(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Local CLIP/SigLIP Model Folder")
        if folder:
            self.txt_semantic_model.setText(folder)

    def _get_min_size(self) -> int:
        idx = self.spn_min.currentIndex()
        return [0, 1024, 65536, 1048576, 10485760, 104857600][idx]

    def _start_scan(self):
        path = self.txt_path.text().strip()
        if not path or not os.path.isdir(path):
            self.lbl_status.setText("Choose a valid folder to scan.")
            return
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Scanning…")
        self.btn_select_dupes.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.tree.clear()
        self.semantic_tree.clear()
        self.progress.setVisible(True)
        self.progress.setValue(0)
        opts = {
            'depth': 99,
            'min_size': self._get_min_size(),
            'perceptual': self.chk_perceptual.isChecked(),
            'audio': self.chk_audio.isChecked(),
            'semantic': self.chk_semantic.isChecked(),
            'semantic_threshold': self.spn_semantic_threshold.value(),
            'semantic_model_dir': self.txt_semantic_model.text().strip(),
        }
        from unifile.clip_duplicates import save_clip_settings
        save_clip_settings({
            'model_dir': opts['semantic_model_dir'],
            'threshold': opts['semantic_threshold'],
        })
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
            self.lbl_status.setText("No duplicates found")
            self.lbl_summary.setText("")
            return
        self._groups = {}
        for path, info in dup_map.items():
            self._groups.setdefault(info.group_id, []).append((path, info))
        hash_groups = {
            gid: members for gid, members in self._groups.items()
            if _duplicate_match_type(members[0][1]) != "Semantic"
        }
        semantic_groups = {
            gid: members for gid, members in self._groups.items()
            if _duplicate_match_type(members[0][1]) == "Semantic"
        }
        _populate_duplicate_tree(self.tree, hash_groups)
        _populate_duplicate_tree(self.semantic_tree, semantic_groups)
        total_waste = sum(
            _file_size(path) for members in self._groups.values()
            for path, info in members if not info.is_original
        )
        total_dupes = sum(
            1 for members in self._groups.values()
            for _, info in members if not info.is_original
        )
        self.lbl_summary.setText(
            f"{len(self._groups)} duplicate groups  •  "
            f"{total_dupes} duplicate files  •  "
            f"{format_size(total_waste)} recoverable space")
        self.lbl_status.setText("Scan complete")
        self.btn_select_dupes.setEnabled(True)
        self.btn_select_none.setEnabled(True)
        self.btn_apply.setEnabled(True)
        if hasattr(self, 'cmb_type_filter'):
            self.cmb_type_filter.blockSignals(True)
            self.cmb_type_filter.setCurrentIndex(0)
            self.cmb_type_filter.blockSignals(False)
            self._apply_type_filter()

    def _apply_type_filter(self):
        """Hide top-level groups whose match type doesn't match the selection."""
        if self.tree.topLevelItemCount() == 0:
            return
        idx = self.cmb_type_filter.currentIndex() if hasattr(self, 'cmb_type_filter') else 0
        allowed = {
            0: None, 1: {'Exact'}, 2: {'Visual'}, 3: {'Audio'},
        }.get(idx)
        shown = 0
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            visible = allowed is None or group.text(4) in allowed
            group.setHidden(not visible)
            if visible:
                shown += 1
        if allowed is not None:
            total = self.tree.topLevelItemCount()
            self.lbl_status.setText(
                f"Showing {shown} of {total} group{'s' if total != 1 else ''} "
                f"(filter: {self.cmb_type_filter.currentText()})."
            )

    def _auto_select(self):
        for tree in self._result_trees():
            for i in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(i)
                for j in range(group.childCount()):
                    child = group.child(j)
                    info = child.data(1, Qt.ItemDataRole.UserRole)
                    if info and not info.is_original:
                        child.setCheckState(0, Qt.CheckState.Checked)
                    else:
                        child.setCheckState(0, Qt.CheckState.Unchecked)

    def _deselect_all(self):
        for tree in self._result_trees():
            for i in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(i)
                for j in range(group.childCount()):
                    group.child(j).setCheckState(0, Qt.CheckState.Unchecked)

    def _get_checked_paths(self) -> list:
        paths = []
        for tree in self._result_trees():
            for i in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(i)
                for j in range(group.childCount()):
                    child = group.child(j)
                    if child.checkState(0) == Qt.CheckState.Checked:
                        path = child.data(0, Qt.ItemDataRole.UserRole)
                        if path:
                            paths.append(path)
        return paths

    def _result_trees(self):
        return (self.tree, self.semantic_tree)

    def _apply_action(self):
        paths = self._get_checked_paths()
        if not paths:
            self.lbl_status.setText("Select at least one duplicate first.")
            return
        action_idx = self.cmb_action.currentIndex()
        total_size = sum(_file_size(path) for path in paths)
        confirm = QMessageBox.question(
            self, "Confirm Action",
            f"Apply action to {len(paths)} files ({format_size(total_size)})?\n\n"
            f"Action: {self.cmb_action.currentText()}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        import shutil

        from unifile.workers import action_delete, action_hardlink
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
            for tree in self._result_trees():
                for i in range(tree.topLevelItemCount()):
                    group = tree.topLevelItem(i)
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
