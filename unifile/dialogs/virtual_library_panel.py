"""UniFile -- Virtual Library panel (non-destructive overlay organization)."""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QFileDialog, QProgressBar, QHeaderView,
    QMenu, QInputDialog, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from unifile.config import get_active_theme
from unifile.virtual_library import VirtualLibrary


class _VLibScanWorker(QThread):
    """Background worker for scanning + optional AI classification."""
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int)

    def __init__(self, library: VirtualLibrary):
        super().__init__()
        self._lib = library

    def run(self):
        count = self._lib.scan_directory(
            callback=lambda c, t: self.progress.emit(c, t))
        self.finished.emit(count)


class VirtualLibraryPanel(QWidget):
    """Non-destructive overlay organization panel.

    Scans a directory, assigns virtual categories, and lets the user
    browse/search/export without moving files.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lib = VirtualLibrary()
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        lbl_title = QLabel("Virtual Library")
        lbl_title.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 16px; font-weight: 700;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Organize files virtually without moving them. "
            "Creates a .unifile/ database in your source directory.")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        layout.addWidget(lbl_desc)

        # Directory selector
        dir_row = QHBoxLayout()
        self.txt_dir = QLineEdit()
        self.txt_dir.setPlaceholderText("Select directory to create virtual library...")
        dir_row.addWidget(self.txt_dir)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(btn_browse)
        btn_open = QPushButton("Open Library")
        btn_open.clicked.connect(self._open_library)
        dir_row.addWidget(btn_open)
        layout.addLayout(dir_row)

        # Stats bar
        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_stats)

        # Progress
        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        self.pbar.setMaximumHeight(6)
        layout.addWidget(self.pbar)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_scan = QPushButton("Scan Directory")
        self.btn_scan.clicked.connect(self._scan)
        self.btn_scan.setEnabled(False)
        btn_row.addWidget(self.btn_scan)

        self.btn_classify = QPushButton("AI Classify Uncategorized")
        self.btn_classify.clicked.connect(self._ai_classify)
        self.btn_classify.setEnabled(False)
        btn_row.addWidget(self.btn_classify)

        self.btn_export = QPushButton("Export to Real Folders")
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)
        btn_row.addWidget(self.btn_export)

        self.btn_check = QPushButton("Check Broken Links")
        self.btn_check.clicked.connect(self._check_broken)
        self.btn_check.setEnabled(False)
        btn_row.addWidget(self.btn_check)
        layout.addLayout(btn_row)

        # Search
        search_row = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search files...")
        self.txt_search.returnPressed.connect(self._search)
        search_row.addWidget(self.txt_search)
        btn_search = QPushButton("Search")
        btn_search.clicked.connect(self._search)
        search_row.addWidget(btn_search)
        layout.addLayout(search_row)

        # Tree view (virtual folder structure)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", "Confidence", "Method"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 4):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Directory")
        if d:
            self.txt_dir.setText(d)

    def _open_library(self):
        d = self.txt_dir.text().strip()
        if not d or not os.path.isdir(d):
            return
        self._lib.open(d)
        self.btn_scan.setEnabled(True)
        self.btn_classify.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_check.setEnabled(True)
        self._update_stats()
        self._refresh_tree()

    def _scan(self):
        if not self._lib.is_open:
            return
        self.pbar.setVisible(True)
        self.pbar.setValue(0)
        self._worker = _VLibScanWorker(self._lib)
        self._worker.progress.connect(lambda c, t: (
            self.pbar.setMaximum(t), self.pbar.setValue(c)))
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_scan_done(self, count):
        self.pbar.setVisible(False)
        self._update_stats()
        self._refresh_tree()

    def _ai_classify(self):
        """Classify uncategorized files using the AI provider chain."""
        if not self._lib.is_open:
            return
        uncategorized = self._lib.get_uncategorized()
        if not uncategorized:
            return
        from unifile.ai_providers import ProviderChain
        chain = ProviderChain()
        assignments = []
        for f in uncategorized:
            prompt = (
                f"Classify this file into a single category. "
                f"Filename: {f['filename']}, Extension: {f['extension']}. "
                f"Reply with ONLY the category name, nothing else.")
            result, provider = chain.classify(prompt)
            if result:
                cat = result.strip().strip('"').strip("'")
                if cat and len(cat) < 80:
                    assignments.append({
                        'rel_path': f['rel_path'],
                        'category': cat,
                        'confidence': 70,
                        'method': f'ai:{provider}',
                    })
        if assignments:
            self._lib.assign_batch(assignments)
        self._update_stats()
        self._refresh_tree()

    def _export(self):
        if not self._lib.is_open:
            return
        dest = QFileDialog.getExistingDirectory(self, "Export Destination")
        if not dest:
            return
        stats = self._lib.export_to_real_folders(dest)
        self.lbl_stats.setText(
            f"Exported: {stats['copied']} copied, {stats['failed']} failed, {stats['skipped']} skipped")

    def _check_broken(self):
        if not self._lib.is_open:
            return
        broken = self._lib.check_broken_links()
        self.lbl_stats.setText(f"Broken links found: {len(broken)}")
        self._refresh_tree()

    def _search(self):
        query = self.txt_search.text().strip()
        if not query or not self._lib.is_open:
            self._refresh_tree()
            return
        results = self._lib.search(query)
        self.tree.clear()
        _t = get_active_theme()
        for r in results:
            item = QTreeWidgetItem([
                r['filename'],
                '',
                f"{r.get('confidence', 0):.0f}%",
                r.get('category', '')
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, r['rel_path'])
            self.tree.addTopLevelItem(item)

    def _refresh_tree(self):
        self.tree.clear()
        if not self._lib.is_open:
            return
        _t = get_active_theme()
        tree_data = self._lib.get_virtual_tree()

        # Add categorized items
        for cat, files in sorted(tree_data.items()):
            cat_item = QTreeWidgetItem([f"{cat} ({len(files)})", "", "", ""])
            cat_item.setForeground(0, QColor(_t['accent']))
            for f in files:
                child = QTreeWidgetItem([
                    f['filename'],
                    self._format_size(f.get('size', 0)),
                    f"{f.get('confidence', 0):.0f}%",
                    f.get('method', ''),
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, f['rel_path'])
                child.setToolTip(0, f['full_path'])
                cat_item.addChild(child)
            self.tree.addTopLevelItem(cat_item)

        # Add uncategorized
        uncat = self._lib.get_uncategorized()
        if uncat:
            uncat_item = QTreeWidgetItem([f"[Uncategorized] ({len(uncat)})", "", "", ""])
            uncat_item.setForeground(0, QColor(_t['muted']))
            for f in uncat:
                child = QTreeWidgetItem([
                    f['filename'],
                    self._format_size(f.get('size', 0)),
                    "",
                    "",
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, f['rel_path'])
                uncat_item.addChild(child)
            self.tree.addTopLevelItem(uncat_item)

        self.tree.expandAll()

    def _update_stats(self):
        if not self._lib.is_open:
            self.lbl_stats.setText("")
            return
        stats = self._lib.get_stats()
        self.lbl_stats.setText(
            f"Files: {stats['total_files']} | "
            f"Categorized: {stats['categorized']} | "
            f"Uncategorized: {stats['uncategorized']} | "
            f"Categories: {stats['categories']} | "
            f"Broken: {stats['broken_links']}")

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        rel_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not rel_path:
            return
        _t = get_active_theme()
        menu = QMenu(self)
        act_assign = menu.addAction("Assign Category...")
        act_tag = menu.addAction("Add Tag...")
        act_open = menu.addAction("Open in Explorer")
        action = menu.exec(self.tree.viewport().mapToGlobal(pos))

        if action == act_assign:
            cat, ok = QInputDialog.getText(self, "Assign Category", "Category name:")
            if ok and cat:
                self._lib.assign_category(rel_path, cat, confidence=100, method='manual')
                self._refresh_tree()
                self._update_stats()
        elif action == act_tag:
            tag, ok = QInputDialog.getText(self, "Add Tag", "Tag:")
            if ok and tag:
                self._lib.add_tag(rel_path, tag)
        elif action == act_open:
            full_path = os.path.join(self._lib.root_dir, rel_path)
            if os.path.exists(full_path):
                import subprocess
                subprocess.Popen(['explorer', '/select,', full_path])

    @staticmethod
    def _format_size(b):
        if b >= 1_073_741_824:
            return f"{b / 1_073_741_824:.1f} GB"
        if b >= 1_048_576:
            return f"{b / 1_048_576:.1f} MB"
        if b >= 1024:
            return f"{b / 1024:.1f} KB"
        return f"{b} B" if b else ""

    def close_library(self):
        self._lib.close()
