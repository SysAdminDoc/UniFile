"""UniFile — Tag Library Panel (inline stacked widget page)."""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QMenu, QInputDialog, QFileDialog, QTreeWidget, QTreeWidgetItem,
    QSplitter, QTextEdit, QCheckBox, QFrame, QScrollArea, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QColor, QAction, QPixmap, QImage

from unifile.config import get_active_theme, _APP_DATA_DIR
from unifile.tagging.library import TagLibrary
from unifile.tagging.models import Tag, Entry, TAG_COLORS


class TagLibraryPanel(QWidget):
    """Full-featured tag library browser panel for the content stack."""

    tag_applied = pyqtSignal(str)  # emits tag name when applied

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lib = TagLibrary()
        self._current_tag_id = None
        self._build_ui()

    @property
    def library(self) -> TagLibrary:
        return self._lib

    def open_library(self, path: str) -> bool:
        result = self._lib.open(path)
        if result:
            self._refresh_tags()
            self._refresh_entries()
            self._update_stats()
        return result

    def close_library(self):
        self._lib.close()

    def _build_ui(self):
        _t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {_t['bg_alt']}; border-bottom: 1px solid {_t['btn_bg']};")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(16, 0, 16, 0)

        lbl_title = QLabel("Tag Library")
        lbl_title.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 14px; font-weight: 700; background: transparent;")
        h_lay.addWidget(lbl_title)
        h_lay.addStretch()

        btn_open = QPushButton("Open Library")
        btn_open.setFixedHeight(28)
        btn_open.setStyleSheet(
            f"QPushButton {{ background: {_t['accent']}; color: #fff; border: none; "
            f"border-radius: 4px; padding: 4px 14px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_t['accent_hover']}; }}")
        btn_open.clicked.connect(self._on_open_library)
        h_lay.addWidget(btn_open)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px; background: transparent; margin-left: 12px;")
        h_lay.addWidget(self.lbl_stats)

        lay.addWidget(header)

        # ── Main splitter: Tags (left) | Entries (right) ─────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Tag Management ──────────────────────────────────────────
        tag_panel = QWidget()
        tag_lay = QVBoxLayout(tag_panel)
        tag_lay.setContentsMargins(12, 8, 6, 8)
        tag_lay.setSpacing(6)

        # Tag search
        tag_search_row = QHBoxLayout()
        tag_search_row.setSpacing(6)
        self.txt_tag_search = QLineEdit()
        self.txt_tag_search.setPlaceholderText("Search tags...")
        self.txt_tag_search.textChanged.connect(self._on_tag_search)
        tag_search_row.addWidget(self.txt_tag_search, 1)
        btn_add_tag = QPushButton("+")
        btn_add_tag.setFixedSize(28, 28)
        btn_add_tag.setToolTip("Add new tag")
        btn_add_tag.setStyleSheet(
            f"QPushButton {{ background: {_t['green']}; color: #fff; border: none; "
            f"border-radius: 4px; font-size: 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {_t['green_hover']}; }}")
        btn_add_tag.clicked.connect(self._on_add_tag)
        tag_search_row.addWidget(btn_add_tag)
        tag_lay.addLayout(tag_search_row)

        # Tag tree (hierarchical)
        self.tag_tree = QTreeWidget()
        self.tag_tree.setHeaderLabels(["Tag", "Count"])
        self.tag_tree.setColumnWidth(0, 180)
        self.tag_tree.setColumnWidth(1, 50)
        self.tag_tree.setRootIsDecorated(True)
        self.tag_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tag_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tag_tree.customContextMenuRequested.connect(self._on_tag_context_menu)
        self.tag_tree.itemClicked.connect(self._on_tag_clicked)
        tag_lay.addWidget(self.tag_tree, 1)

        # Quick tag buttons
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        lbl_quick = QLabel("Quick:")
        lbl_quick.setStyleSheet(f"color: {_t['muted']}; font-size: 10px;")
        quick_row.addWidget(lbl_quick)
        for preset_name in ["Favorite", "Important", "Review", "Archive"]:
            btn = QPushButton(preset_name)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 10px; padding: 2px 8px; background: {_t['selection']};"
                f"color: {_t['fg']}; border: 1px solid {_t['border']}; border-radius: 3px; }}"
                f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
            btn.clicked.connect(lambda checked, n=preset_name: self._quick_create_tag(n))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        tag_lay.addLayout(quick_row)

        splitter.addWidget(tag_panel)

        # ── Right: Entry List + Preview ──────────────────────────────────
        entry_panel = QWidget()
        entry_lay = QVBoxLayout(entry_panel)
        entry_lay.setContentsMargins(6, 8, 12, 8)
        entry_lay.setSpacing(6)

        # Entry header
        entry_header = QHBoxLayout()
        entry_header.setSpacing(6)
        self.lbl_entry_title = QLabel("All Entries")
        self.lbl_entry_title.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 12px; font-weight: 600;")
        entry_header.addWidget(self.lbl_entry_title)
        entry_header.addStretch()

        self.txt_entry_search = QLineEdit()
        self.txt_entry_search.setPlaceholderText("Search files... (tag:Name, ext:pdf, field:key=val)")
        self.txt_entry_search.setFixedWidth(300)
        self.txt_entry_search.textChanged.connect(self._on_entry_search)
        entry_header.addWidget(self.txt_entry_search)

        btn_add_files = QPushButton("Add Files")
        btn_add_files.setFixedHeight(28)
        btn_add_files.setStyleSheet(
            f"QPushButton {{ background: {_t['accent']}; color: #fff; border: none; "
            f"border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_t['accent_hover']}; }}")
        btn_add_files.clicked.connect(self._on_add_files)
        entry_header.addWidget(btn_add_files)

        btn_scan_dir = QPushButton("Scan Directory")
        btn_scan_dir.setFixedHeight(28)
        btn_scan_dir.setStyleSheet(
            f"QPushButton {{ background: {_t['green']}; color: #fff; border: none; "
            f"border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_t['green_hover']}; }}")
        btn_scan_dir.clicked.connect(self._on_scan_directory)
        entry_header.addWidget(btn_scan_dir)

        entry_lay.addLayout(entry_header)

        # Vertical splitter: Entry table (top) | Preview panel (bottom)
        v_splitter = QSplitter(Qt.Orientation.Vertical)

        # Entry table
        self.tbl_entries = QTableWidget()
        self.tbl_entries.setColumnCount(5)
        self.tbl_entries.setHorizontalHeaderLabels(["Filename", "Tags", "Type", "Modified", "Path"])
        self.tbl_entries.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_entries.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_entries.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_entries.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_entries.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tbl_entries.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_entries.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl_entries.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_entries.customContextMenuRequested.connect(self._on_entry_context_menu)
        self.tbl_entries.setAlternatingRowColors(True)
        self.tbl_entries.itemSelectionChanged.connect(self._on_entry_selection_changed)
        v_splitter.addWidget(self.tbl_entries)

        # ── Preview Panel ──────────────────────────────────────────────
        self._preview_widget = self._build_preview_panel(_t)
        v_splitter.addWidget(self._preview_widget)
        v_splitter.setStretchFactor(0, 3)
        v_splitter.setStretchFactor(1, 1)

        entry_lay.addWidget(v_splitter, 1)

        # Entry detail / tag assignment bar
        detail_bar = QWidget()
        detail_bar.setFixedHeight(36)
        detail_bar.setStyleSheet(f"background: {_t['bg_alt']}; border-top: 1px solid {_t['btn_bg']};")
        db_lay = QHBoxLayout(detail_bar)
        db_lay.setContentsMargins(8, 0, 8, 0)
        db_lay.setSpacing(8)
        lbl_assign = QLabel("Assign tag:")
        lbl_assign.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; background: transparent;")
        db_lay.addWidget(lbl_assign)
        self.cmb_assign_tag = QComboBox()
        self.cmb_assign_tag.setMinimumWidth(160)
        self.cmb_assign_tag.setEditable(True)
        self.cmb_assign_tag.setPlaceholderText("Select or type tag...")
        db_lay.addWidget(self.cmb_assign_tag)
        btn_assign = QPushButton("Apply Tag")
        btn_assign.setFixedHeight(26)
        btn_assign.setStyleSheet(
            f"QPushButton {{ background: {_t['accent']}; color: #fff; border: none; "
            f"border-radius: 3px; padding: 2px 12px; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {_t['accent_hover']}; }}")
        btn_assign.clicked.connect(self._on_apply_tag_to_selected)
        db_lay.addWidget(btn_assign)
        btn_remove_tag = QPushButton("Remove Tag")
        btn_remove_tag.setFixedHeight(26)
        btn_remove_tag.setStyleSheet(
            f"QPushButton {{ background: {_t['btn_bg']}; color: {_t['fg']}; "
            f"border: 1px solid {_t['border']}; border-radius: 3px; padding: 2px 12px; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
        btn_remove_tag.clicked.connect(self._on_remove_tag_from_selected)
        db_lay.addWidget(btn_remove_tag)
        db_lay.addStretch()
        self.lbl_selection_info = QLabel("")
        self.lbl_selection_info.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px; background: transparent;")
        db_lay.addWidget(self.lbl_selection_info)
        entry_lay.addWidget(detail_bar)

        splitter.addWidget(entry_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        lay.addWidget(splitter, 1)

    # ── Preview Panel ────────────────────────────────────────────────────

    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif", ".svg"}
    _TEXT_EXTS = {".txt", ".md", ".log", ".csv", ".json", ".xml", ".yaml", ".yml",
                  ".ini", ".cfg", ".conf", ".py", ".js", ".ts", ".html", ".css",
                  ".bat", ".sh", ".ps1", ".c", ".cpp", ".h", ".java", ".rs", ".go"}

    def _build_preview_panel(self, _t: dict) -> QWidget:
        """Build the file preview panel shown below the entry table."""
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background: {_t['bg_alt']}; border-top: 1px solid {_t['btn_bg']}; }}")

        lay = QHBoxLayout(panel)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        # Left: Thumbnail / icon
        self._preview_thumb = QLabel()
        self._preview_thumb.setFixedSize(140, 140)
        self._preview_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_thumb.setStyleSheet(
            f"background: {_t['bg']}; border: 1px solid {_t['border']}; border-radius: 6px;")
        lay.addWidget(self._preview_thumb)

        # Middle: File info + tags
        mid = QVBoxLayout()
        mid.setSpacing(4)

        self._preview_filename = QLabel("No file selected")
        self._preview_filename.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 13px; font-weight: 700; background: transparent;")
        self._preview_filename.setWordWrap(True)
        mid.addWidget(self._preview_filename)

        self._preview_meta = QLabel("")
        self._preview_meta.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px; background: transparent;")
        self._preview_meta.setWordWrap(True)
        mid.addWidget(self._preview_meta)

        # Tag chips container
        self._preview_tags_container = QWidget()
        self._preview_tags_container.setStyleSheet("background: transparent;")
        self._preview_tags_flow = QHBoxLayout(self._preview_tags_container)
        self._preview_tags_flow.setContentsMargins(0, 2, 0, 2)
        self._preview_tags_flow.setSpacing(4)
        self._preview_tags_flow.addStretch()
        mid.addWidget(self._preview_tags_container)

        mid.addStretch()
        lay.addLayout(mid, 1)

        # Right: Fields / text excerpt
        right = QVBoxLayout()
        right.setSpacing(2)

        lbl_fields = QLabel("Fields")
        lbl_fields.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 11px; font-weight: 600; background: transparent;")
        right.addWidget(lbl_fields)

        self._preview_fields = QTextEdit()
        self._preview_fields.setReadOnly(True)
        self._preview_fields.setStyleSheet(
            f"QTextEdit {{ background: {_t['bg']}; color: {_t['fg']}; border: 1px solid {_t['border']}; "
            f"border-radius: 4px; font-size: 11px; padding: 4px; }}")
        self._preview_fields.setMaximumHeight(120)
        right.addWidget(self._preview_fields, 1)

        lay.addLayout(right, 1)

        return panel

    def _on_entry_selection_changed(self):
        """Update preview panel when entry selection changes."""
        rows = set(idx.row() for idx in self.tbl_entries.selectedIndexes())
        if len(rows) != 1:
            self._clear_preview()
            if len(rows) > 1:
                self._preview_filename.setText(f"{len(rows)} files selected")
            return

        row = next(iter(rows))
        item = self.tbl_entries.item(row, 0)
        if not item:
            self._clear_preview()
            return

        entry_id = item.data(Qt.ItemDataRole.UserRole)
        entry = self._lib.get_entry(entry_id)
        if not entry:
            self._clear_preview()
            return

        _t = get_active_theme()

        # Filename
        self._preview_filename.setText(entry.filename)

        # File metadata
        full_path = str(entry.path)
        meta_parts = [entry.suffix.upper().lstrip('.')]
        if os.path.exists(full_path):
            size = os.path.getsize(full_path)
            if size < 1024:
                meta_parts.append(f"{size} B")
            elif size < 1024 * 1024:
                meta_parts.append(f"{size / 1024:.1f} KB")
            else:
                meta_parts.append(f"{size / (1024 * 1024):.1f} MB")
        if entry.date_modified:
            meta_parts.append(f"Modified: {entry.date_modified.strftime('%Y-%m-%d %H:%M')}")
        if entry.date_created:
            meta_parts.append(f"Created: {entry.date_created.strftime('%Y-%m-%d')}")
        meta_parts.append(str(entry.path))
        self._preview_meta.setText("  |  ".join(meta_parts))

        # Thumbnail
        suffix = entry.suffix.lower()
        if suffix in self._IMAGE_EXTS and os.path.exists(full_path):
            pixmap = QPixmap(full_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    QSize(136, 136),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self._preview_thumb.setPixmap(scaled)
            else:
                self._preview_thumb.setText(suffix.upper())
        elif suffix in self._TEXT_EXTS and os.path.exists(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                    excerpt = f.read(500)
                self._preview_thumb.setText("")
                self._preview_thumb.setStyleSheet(
                    self._preview_thumb.styleSheet())
                # Show text excerpt in the thumbnail area
                lbl_text = excerpt[:80].replace('\n', ' ')
                self._preview_thumb.setText(lbl_text[:60] + "..." if len(lbl_text) > 60 else lbl_text)
                self._preview_thumb.setStyleSheet(
                    f"background: {_t['bg']}; border: 1px solid {_t['border']}; border-radius: 6px; "
                    f"color: {_t['muted']}; font-size: 9px; padding: 6px;")
            except Exception:
                self._preview_thumb.setText(suffix.upper())
        else:
            self._preview_thumb.setPixmap(QPixmap())
            self._preview_thumb.setText(suffix.upper().lstrip('.') if suffix else "FILE")
            self._preview_thumb.setStyleSheet(
                f"background: {_t['bg']}; border: 1px solid {_t['border']}; border-radius: 6px; "
                f"color: {_t['muted']}; font-size: 18px; font-weight: 700;")

        # Tags as colored chips
        self._clear_tag_chips()
        from unifile.tagging.models import TAG_COLORS
        for tag in sorted(entry.tags, key=lambda t: t.name):
            color = TAG_COLORS.get(tag.color_slug or "blue", "#3b82f6")
            chip = QLabel(tag.name)
            chip.setStyleSheet(
                f"background: {color}22; color: {color}; border: 1px solid {color}44; "
                f"border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: 600;")
            # Insert before the stretch
            self._preview_tags_flow.insertWidget(
                self._preview_tags_flow.count() - 1, chip)

        # Fields
        fields = self._lib.get_entry_fields(entry_id)
        if fields:
            lines = []
            for key, value in fields.items():
                if value:
                    lines.append(f"<b>{key.replace('_', ' ').title()}:</b> {value}")
            self._preview_fields.setHtml("<br>".join(lines) if lines else
                                          "<i style='color: gray;'>No fields set</i>")
        else:
            self._preview_fields.setHtml("<i style='color: gray;'>No fields set</i>")

    def _clear_preview(self):
        _t = get_active_theme()
        self._preview_filename.setText("No file selected")
        self._preview_meta.setText("")
        self._preview_thumb.setPixmap(QPixmap())
        self._preview_thumb.setText("")
        self._preview_thumb.setStyleSheet(
            f"background: {_t['bg']}; border: 1px solid {_t['border']}; border-radius: 6px;")
        self._clear_tag_chips()
        self._preview_fields.setHtml("")

    def _clear_tag_chips(self):
        while self._preview_tags_flow.count() > 1:
            item = self._preview_tags_flow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── Library Operations ────────────────────────────────────────────────

    def _on_open_library(self):
        path = QFileDialog.getExistingDirectory(self, "Select Library Folder")
        if path:
            self.open_library(path)

    def _update_stats(self):
        if not self._lib.is_open:
            self.lbl_stats.setText("")
            return
        stats = self._lib.get_stats()
        self.lbl_stats.setText(
            f"{stats['entries']} files  |  {stats['tags']} tags  |  "
            f"{stats['tagged_entries']} tagged")

    # ── Tag Operations ────────────────────────────────────────────────────

    def _refresh_tags(self):
        self.tag_tree.clear()
        self.cmb_assign_tag.clear()
        if not self._lib.is_open:
            return

        tags = self._lib.get_all_tags()
        # Build hierarchy: category tags at top, children below
        categories = [t for t in tags if t.is_category]
        non_cat = [t for t in tags if not t.is_category]

        for cat in sorted(categories, key=lambda t: t.name):
            item = QTreeWidgetItem([cat.name, ""])
            item.setData(0, Qt.ItemDataRole.UserRole, cat.id)
            color = TAG_COLORS.get(cat.color_slug or "blue", "#3b82f6")
            item.setForeground(0, QColor(color))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable)
            # Count entries with this tag
            count = len(self._lib.get_entries_by_tag(cat.id))
            item.setText(1, str(count) if count else "")
            self.tag_tree.addTopLevelItem(item)

            # Add child tags
            children = [t for t in non_cat if cat.id in t.parent_ids]
            for child in sorted(children, key=lambda t: t.name):
                c_item = QTreeWidgetItem([child.name, ""])
                c_item.setData(0, Qt.ItemDataRole.UserRole, child.id)
                c_count = len(self._lib.get_entries_by_tag(child.id))
                c_item.setText(1, str(c_count) if c_count else "")
                item.addChild(c_item)
                non_cat = [t for t in non_cat if t.id != child.id]

        # Orphan tags (no parent, not category)
        if non_cat:
            orphan_root = QTreeWidgetItem(["Uncategorized", ""])
            orphan_root.setForeground(0, QColor(TAG_COLORS.get("slate", "#64748b")))
            for t in sorted(non_cat, key=lambda t: t.name):
                o_item = QTreeWidgetItem([t.name, ""])
                o_item.setData(0, Qt.ItemDataRole.UserRole, t.id)
                o_count = len(self._lib.get_entries_by_tag(t.id))
                o_item.setText(1, str(o_count) if o_count else "")
                orphan_root.addChild(o_item)
            self.tag_tree.addTopLevelItem(orphan_root)

        # Populate assign combo
        self.cmb_assign_tag.addItems([t.name for t in sorted(tags, key=lambda t: t.name)])

        self.tag_tree.expandAll()

    def _on_tag_search(self, text):
        if not self._lib.is_open:
            return
        for i in range(self.tag_tree.topLevelItemCount()):
            item = self.tag_tree.topLevelItem(i)
            self._filter_tree_item(item, text.lower())

    def _filter_tree_item(self, item: QTreeWidgetItem, query: str):
        match = query in item.text(0).lower() if query else True
        child_match = False
        for i in range(item.childCount()):
            if self._filter_tree_item(item.child(i), query):
                child_match = True
        visible = match or child_match
        item.setHidden(not visible)
        return visible

    def _on_tag_clicked(self, item: QTreeWidgetItem, column: int):
        tag_id = item.data(0, Qt.ItemDataRole.UserRole)
        if tag_id is None:
            self._current_tag_id = None
            self.lbl_entry_title.setText("All Entries")
            self._refresh_entries()
            return
        self._current_tag_id = tag_id
        tag = self._lib.get_tag(tag_id)
        self.lbl_entry_title.setText(f"Tag: {tag.name}" if tag else "All Entries")
        self._refresh_entries(tag_id=tag_id)

    def _on_add_tag(self):
        if not self._lib.is_open:
            return
        name, ok = QInputDialog.getText(self, "Add Tag", "Tag name:")
        if ok and name.strip():
            self._lib.add_tag(name.strip())
            self._refresh_tags()
            self._update_stats()

    def _quick_create_tag(self, name: str):
        if not self._lib.is_open:
            return
        self._lib.add_tag(name, is_category=True, color_slug="blue")
        self._refresh_tags()
        self._update_stats()

    def _on_tag_context_menu(self, pos):
        item = self.tag_tree.itemAt(pos)
        if not item:
            return
        tag_id = item.data(0, Qt.ItemDataRole.UserRole)
        if tag_id is None:
            return

        menu = QMenu(self)
        menu.addAction("Rename Tag", lambda: self._rename_tag(tag_id))
        menu.addAction("Add Alias", lambda: self._add_tag_alias(tag_id))

        color_menu = menu.addMenu("Set Color")
        for color_name, color_hex in TAG_COLORS.items():
            action = color_menu.addAction(color_name.title())
            action.triggered.connect(
                lambda checked, s=color_name: self._set_tag_color(tag_id, s))

        menu.addSeparator()
        menu.addAction("Toggle Category", lambda: self._toggle_category(tag_id))
        menu.addSeparator()
        menu.addAction("Delete Tag", lambda: self._delete_tag(tag_id))
        menu.exec(self.tag_tree.mapToGlobal(pos))

    def _rename_tag(self, tag_id: int):
        tag = self._lib.get_tag(tag_id)
        if not tag:
            return
        name, ok = QInputDialog.getText(self, "Rename Tag", "New name:", text=tag.name)
        if ok and name.strip():
            self._lib.update_tag(tag_id, name=name.strip())
            self._refresh_tags()

    def _add_tag_alias(self, tag_id: int):
        name, ok = QInputDialog.getText(self, "Add Alias", "Alias name:")
        if ok and name.strip():
            self._lib.add_alias(tag_id, name.strip())

    def _set_tag_color(self, tag_id: int, color_slug: str):
        self._lib.update_tag(tag_id, color_slug=color_slug)
        self._refresh_tags()

    def _toggle_category(self, tag_id: int):
        tag = self._lib.get_tag(tag_id)
        if tag:
            self._lib.update_tag(tag_id, is_category=not tag.is_category)
            self._refresh_tags()

    def _delete_tag(self, tag_id: int):
        self._lib.delete_tag(tag_id)
        self._refresh_tags()
        self._update_stats()

    # ── Entry Operations ──────────────────────────────────────────────────

    def _refresh_entries(self, tag_id: int | None = None):
        self.tbl_entries.setRowCount(0)
        if not self._lib.is_open:
            return

        if tag_id:
            entries = self._lib.get_entries_by_tag(tag_id)
        else:
            entries = self._lib.get_all_entries()

        self.tbl_entries.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            # Filename
            item_name = QTableWidgetItem(entry.filename)
            item_name.setData(Qt.ItemDataRole.UserRole, entry.id)
            self.tbl_entries.setItem(row, 0, item_name)

            # Tags
            tag_str = ", ".join(entry.tag_names) if hasattr(entry, 'tag_names') else ""
            self.tbl_entries.setItem(row, 1, QTableWidgetItem(tag_str))

            # Type
            self.tbl_entries.setItem(row, 2, QTableWidgetItem(entry.suffix.upper()))

            # Modified
            mod = entry.date_modified.strftime("%Y-%m-%d") if entry.date_modified else ""
            self.tbl_entries.setItem(row, 3, QTableWidgetItem(mod))

            # Path
            self.tbl_entries.setItem(row, 4, QTableWidgetItem(str(entry.path)))

        self.lbl_selection_info.setText(f"{len(entries)} entries")

    def _on_entry_search(self, text):
        if not self._lib.is_open:
            return
        if not text.strip():
            self._refresh_entries(tag_id=self._current_tag_id)
            return
        entries = self._lib.search_entries(text.strip())
        self.tbl_entries.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            item_name = QTableWidgetItem(entry.filename)
            item_name.setData(Qt.ItemDataRole.UserRole, entry.id)
            self.tbl_entries.setItem(row, 0, item_name)
            self.tbl_entries.setItem(row, 1, QTableWidgetItem(""))
            self.tbl_entries.setItem(row, 2, QTableWidgetItem(entry.suffix.upper()))
            mod = entry.date_modified.strftime("%Y-%m-%d") if entry.date_modified else ""
            self.tbl_entries.setItem(row, 3, QTableWidgetItem(mod))
            self.tbl_entries.setItem(row, 4, QTableWidgetItem(str(entry.path)))
        self.lbl_selection_info.setText(f"{len(entries)} results")

    def _on_add_files(self):
        if not self._lib.is_open:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Add Files to Library")
        if files:
            count = self._lib.add_entries_bulk(files)
            self._refresh_entries()
            self._update_stats()

    def _on_scan_directory(self):
        if not self._lib.is_open:
            return
        path = QFileDialog.getExistingDirectory(self, "Scan Directory")
        if not path:
            return
        file_paths = []
        for root, dirs, files in os.walk(path):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if not f.startswith('.'):
                    file_paths.append(os.path.join(root, f))
        if file_paths:
            count = self._lib.add_entries_bulk(file_paths)
            self._refresh_entries()
            self._update_stats()

    def _on_entry_context_menu(self, pos):
        rows = set(idx.row() for idx in self.tbl_entries.selectedIndexes())
        if not rows:
            return
        entry_ids = []
        for r in rows:
            item = self.tbl_entries.item(r, 0)
            if item:
                entry_ids.append(item.data(Qt.ItemDataRole.UserRole))

        menu = QMenu(self)
        # Tag submenu
        tag_menu = menu.addMenu("Add Tag")
        for tag in self._lib.get_all_tags():
            action = tag_menu.addAction(tag.name)
            action.triggered.connect(
                lambda checked, tid=tag.id, eids=entry_ids: self._batch_add_tag(eids, tid))

        menu.addSeparator()
        menu.addAction("Remove from Library", lambda: self._batch_remove_entries(entry_ids))
        menu.exec(self.tbl_entries.mapToGlobal(pos))

    def _on_apply_tag_to_selected(self):
        if not self._lib.is_open:
            return
        tag_name = self.cmb_assign_tag.currentText().strip()
        if not tag_name:
            return

        # Get or create the tag
        tag = self._lib.get_tag_by_name(tag_name)
        if not tag:
            tag = self._lib.add_tag(tag_name)
        if not tag:
            return

        rows = set(idx.row() for idx in self.tbl_entries.selectedIndexes())
        for r in rows:
            item = self.tbl_entries.item(r, 0)
            if item:
                entry_id = item.data(Qt.ItemDataRole.UserRole)
                self._lib.add_tags_to_entry(entry_id, [tag.id])

        self._refresh_entries(tag_id=self._current_tag_id)
        self._refresh_tags()
        self._update_stats()
        self.tag_applied.emit(tag_name)

    def _on_remove_tag_from_selected(self):
        if not self._lib.is_open:
            return
        tag_name = self.cmb_assign_tag.currentText().strip()
        if not tag_name:
            return
        tag = self._lib.get_tag_by_name(tag_name)
        if not tag:
            return

        rows = set(idx.row() for idx in self.tbl_entries.selectedIndexes())
        for r in rows:
            item = self.tbl_entries.item(r, 0)
            if item:
                entry_id = item.data(Qt.ItemDataRole.UserRole)
                self._lib.remove_tags_from_entry(entry_id, [tag.id])

        self._refresh_entries(tag_id=self._current_tag_id)
        self._refresh_tags()
        self._update_stats()

    def _batch_add_tag(self, entry_ids: list[int], tag_id: int):
        for eid in entry_ids:
            self._lib.add_tags_to_entry(eid, [tag_id])
        self._refresh_entries(tag_id=self._current_tag_id)
        self._refresh_tags()
        self._update_stats()

    def _batch_remove_entries(self, entry_ids: list[int]):
        for eid in entry_ids:
            self._lib.remove_entry(eid)
        self._refresh_entries(tag_id=self._current_tag_id)
        self._update_stats()
