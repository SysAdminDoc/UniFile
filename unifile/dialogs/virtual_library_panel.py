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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.header = QFrame()
        self.header.setProperty("class", "card")
        header_lay = QVBoxLayout(self.header)
        header_lay.setContentsMargins(18, 16, 18, 16)
        header_lay.setSpacing(4)
        self.lbl_header_kicker = QLabel("NON-DESTRUCTIVE OVERLAY")
        header_lay.addWidget(self.lbl_header_kicker)
        self.lbl_header_title = QLabel("Virtual Library")
        header_lay.addWidget(self.lbl_header_title)

        self.lbl_header_desc = QLabel(
            "Organize files virtually without moving them. Scan a source folder, review categorization coverage, and only export real folders when you are satisfied."
        )
        self.lbl_header_desc.setWordWrap(True)
        header_lay.addWidget(self.lbl_header_desc)
        self.lbl_status = QLabel("Choose a source folder to open or create a virtual library")
        header_lay.addWidget(self.lbl_status)
        layout.addWidget(self.header)

        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(12)

        # Directory selector
        self.dir_card = QFrame()
        self.dir_card.setProperty("class", "card")
        dir_card_lay = QVBoxLayout(self.dir_card)
        dir_card_lay.setContentsMargins(16, 16, 16, 16)
        dir_card_lay.setSpacing(8)
        self.lbl_source_section = QLabel("Library source")
        dir_card_lay.addWidget(self.lbl_source_section)
        self.lbl_source_hint = QLabel("Open the root folder you want to scan. UniFile stores the virtual overlay beside that source, not in your destination tree.")
        self.lbl_source_hint.setWordWrap(True)
        dir_card_lay.addWidget(self.lbl_source_hint)
        dir_row = QHBoxLayout()
        self.txt_dir = QLineEdit()
        self.txt_dir.setPlaceholderText("Select a directory to create a virtual library…")
        dir_row.addWidget(self.txt_dir)
        self.btn_browse = QPushButton("Browse")
        self.btn_browse.setProperty("class", "toolbar")
        self.btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(self.btn_browse)
        self.btn_open = QPushButton("Open Library")
        self.btn_open.setProperty("class", "primary")
        self.btn_open.clicked.connect(self._open_library)
        dir_row.addWidget(self.btn_open)
        dir_card_lay.addLayout(dir_row)

        # Stats bar
        self.lbl_stats = QLabel("")
        dir_card_lay.addWidget(self.lbl_stats)
        content_lay.addWidget(self.dir_card)

        # Progress
        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        self.pbar.setMaximumHeight(6)
        content_lay.addWidget(self.pbar)

        # Action buttons
        self.actions_card = QFrame()
        self.actions_card.setProperty("class", "card")
        actions_lay = QVBoxLayout(self.actions_card)
        actions_lay.setContentsMargins(16, 16, 16, 16)
        actions_lay.setSpacing(8)
        self.lbl_actions_section = QLabel("Actions")
        actions_lay.addWidget(self.lbl_actions_section)
        self.lbl_actions_hint = QLabel("Scan first, then use AI only on what still needs help. Export remains optional and review-first.")
        self.lbl_actions_hint.setWordWrap(True)
        actions_lay.addWidget(self.lbl_actions_hint)
        btn_row = QHBoxLayout()
        self.btn_scan = QPushButton("Scan Directory")
        self.btn_scan.setProperty("class", "primary")
        self.btn_scan.clicked.connect(self._scan)
        self.btn_scan.setEnabled(False)
        btn_row.addWidget(self.btn_scan)

        self.btn_classify = QPushButton("AI Classify Uncategorized")
        self.btn_classify.setProperty("class", "success")
        self.btn_classify.clicked.connect(self._ai_classify)
        self.btn_classify.setEnabled(False)
        btn_row.addWidget(self.btn_classify)

        self.btn_export = QPushButton("Export to Real Folders")
        self.btn_export.setProperty("class", "toolbar")
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)
        btn_row.addWidget(self.btn_export)

        self.btn_check = QPushButton("Check Broken Links")
        self.btn_check.setProperty("class", "toolbar")
        self.btn_check.clicked.connect(self._check_broken)
        self.btn_check.setEnabled(False)
        btn_row.addWidget(self.btn_check)
        actions_lay.addLayout(btn_row)
        content_lay.addWidget(self.actions_card)

        # Search
        self.search_card = QFrame()
        self.search_card.setProperty("class", "card")
        search_card_lay = QVBoxLayout(self.search_card)
        search_card_lay.setContentsMargins(16, 16, 16, 16)
        search_card_lay.setSpacing(8)
        self.lbl_search_section = QLabel("Review categories")
        search_card_lay.addWidget(self.lbl_search_section)
        self.lbl_search_hint = QLabel("Filter the virtual tree by filename, category, or method once the library is open.")
        self.lbl_search_hint.setWordWrap(True)
        search_card_lay.addWidget(self.lbl_search_hint)
        search_row = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search files…")
        self.txt_search.returnPressed.connect(self._search)
        search_row.addWidget(self.txt_search)
        self.btn_search = QPushButton("Search")
        self.btn_search.setProperty("class", "toolbar")
        self.btn_search.clicked.connect(self._search)
        search_row.addWidget(self.btn_search)
        search_card_lay.addLayout(search_row)

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
        search_card_lay.addWidget(self.tree, 1)
        content_lay.addWidget(self.search_card, 1)
        layout.addWidget(content, 1)
        self._show_placeholder("Open a library to start browsing virtual categories")
        self.apply_theme()

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Directory")
        if d:
            self.txt_dir.setText(d)
            self.lbl_status.setText("Source folder selected. Open the library to inspect or scan it.")

    def _open_library(self):
        d = self.txt_dir.text().strip()
        if not d:
            self.lbl_status.setText("Choose a source folder before opening a virtual library")
            return
        if not os.path.isdir(d):
            self.lbl_status.setText("That source folder does not exist. Pick a valid directory and try again.")
            return
        self._lib.open(d)
        self._set_library_actions(True)
        self._update_stats()
        self._refresh_tree()
        self.lbl_status.setText("Virtual library ready. Scan the directory to build or refresh the overlay.")

    def _scan(self):
        if not self._lib.is_open:
            self.lbl_status.setText("Open a virtual library before scanning")
            return
        self._set_library_actions(False)
        self.btn_scan.setEnabled(False)
        self.pbar.setVisible(True)
        self.pbar.setValue(0)
        self.lbl_status.setText("Scanning source directory and updating the virtual overlay…")
        self._worker = _VLibScanWorker(self._lib)
        self._worker.progress.connect(lambda c, t: (
            self.pbar.setMaximum(t), self.pbar.setValue(c)))
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_scan_done(self, count):
        self.pbar.setVisible(False)
        self._set_library_actions(True)
        self._update_stats()
        self._refresh_tree()
        self.lbl_status.setText(f"Scan complete. Indexed {count} file{'s' if count != 1 else ''} in the virtual library.")

    def _ai_classify(self):
        """Classify uncategorized files using the AI provider chain."""
        if not self._lib.is_open:
            self.lbl_status.setText("Open a virtual library before running AI classification")
            return
        uncategorized = self._lib.get_uncategorized()
        if not uncategorized:
            self.lbl_status.setText("Everything already has a category. No AI pass was needed.")
            return
        from unifile.ai_providers import ProviderChain
        chain = ProviderChain()
        assignments = []
        self.lbl_status.setText(f"Classifying {len(uncategorized)} uncategorized file{'s' if len(uncategorized) != 1 else ''} with the AI provider chain…")
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
        self.lbl_status.setText(
            f"AI classified {len(assignments)} file{'s' if len(assignments) != 1 else ''}. Review coverage before exporting."
        )

    def _export(self):
        if not self._lib.is_open:
            self.lbl_status.setText("Open a virtual library before exporting")
            return
        dest = QFileDialog.getExistingDirectory(self, "Export Destination")
        if not dest:
            return
        stats = self._lib.export_to_real_folders(dest)
        self.lbl_stats.setText(
            f"{stats['copied']} copied  •  {stats['failed']} failed  •  {stats['skipped']} skipped"
        )
        self.lbl_status.setText("Export finished. Review the destination folders and any failures before re-running.")

    def _check_broken(self):
        if not self._lib.is_open:
            self.lbl_status.setText("Open a virtual library before checking broken links")
            return
        broken = self._lib.check_broken_links()
        self.lbl_status.setText(
            f"Broken link review complete. Found {len(broken)} broken item{'s' if len(broken) != 1 else ''}."
        )
        self._refresh_tree()

    def _search(self):
        query = self.txt_search.text().strip()
        if not self._lib.is_open:
            self.lbl_status.setText("Open a virtual library before searching")
            return
        if not query:
            self.lbl_status.setText("Showing the full virtual tree")
            self._refresh_tree()
            return
        results = self._lib.search(query)
        self.tree.clear()
        if not results:
            self._show_placeholder("No matching files found", "Try a broader filename or category search.")
            self.lbl_status.setText("No virtual library matches found for that search")
            return
        for r in results:
            item = QTreeWidgetItem([
                r['filename'],
                self._format_size(r.get('size', 0)),
                f"{r.get('confidence', 0):.0f}%",
                r.get('method', '') or r.get('category', '')
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, r['rel_path'])
            item.setToolTip(0, r.get('full_path', r['rel_path']))
            self.tree.addTopLevelItem(item)
        self.lbl_status.setText(
            f"Showing {len(results)} search result{'s' if len(results) != 1 else ''} in the virtual library"
        )

    def _refresh_tree(self):
        self.tree.clear()
        if not self._lib.is_open:
            self._show_placeholder("Open a library to start browsing virtual categories")
            return
        _t = get_active_theme()
        tree_data = self._lib.get_virtual_tree()
        total_items = 0

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
                total_items += 1
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
                total_items += 1
            self.tree.addTopLevelItem(uncat_item)

        if total_items == 0:
            self._show_placeholder("No files indexed yet", "Scan the source directory to populate the virtual tree.")
            return
        self.tree.expandAll()

    def _update_stats(self):
        if not self._lib.is_open:
            self.lbl_stats.setText("No library open yet")
            return
        stats = self._lib.get_stats()
        self.lbl_stats.setText(
            f"{stats['total_files']} files  •  "
            f"{stats['categorized']} categorized  •  "
            f"{stats['uncategorized']} uncategorized  •  "
            f"{stats['categories']} categories  •  "
            f"{stats['broken_links']} broken"
        )

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

    def _set_library_actions(self, enabled: bool):
        self.btn_scan.setEnabled(enabled)
        self.btn_classify.setEnabled(enabled)
        self.btn_export.setEnabled(enabled)
        self.btn_check.setEnabled(enabled)

    def _show_placeholder(self, title: str, detail: str = ""):
        self.tree.clear()
        item = QTreeWidgetItem([title, "", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        if detail:
            child = QTreeWidgetItem([detail, "", "", ""])
            child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.addChild(child)
            item.setExpanded(True)
        self.tree.addTopLevelItem(item)

    def apply_theme(self, theme: dict | None = None):
        t = theme or get_active_theme()
        self.header.setStyleSheet(
            f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; border-radius: 18px; }}"
        )
        self.lbl_header_kicker.setStyleSheet(
            f"color: {t['accent']}; font-size: 10px; font-weight: 700; letter-spacing: 1.6px;"
        )
        self.lbl_header_title.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 22px; font-weight: 700;"
        )
        self.lbl_header_desc.setStyleSheet(f"color: {t['muted']}; font-size: 12px; line-height: 1.4em;")
        self.lbl_status.setStyleSheet(
            f"background: {t['header_bg']}; color: {t['muted']}; border: 1px solid {t['border']}; "
            "border-radius: 999px; padding: 6px 12px; font-size: 11px; font-weight: 600;"
        )
        for panel in (self.dir_card, self.actions_card, self.search_card):
            panel.setStyleSheet(
                f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; border-radius: 18px; }}"
            )
        for label in (self.lbl_source_section, self.lbl_actions_section, self.lbl_search_section):
            label.setStyleSheet(f"color: {t['fg_bright']}; font-size: 14px; font-weight: 700;")
        for label in (self.lbl_source_hint, self.lbl_actions_hint, self.lbl_search_hint):
            label.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        self.lbl_stats.setStyleSheet(f"color: {t['muted']}; font-size: 11px; font-weight: 600;")

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
