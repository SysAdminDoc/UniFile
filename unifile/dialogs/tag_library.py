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
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────
        self.header = QFrame()
        self.header.setProperty("class", "card")
        h_lay = QHBoxLayout(self.header)
        h_lay.setContentsMargins(18, 16, 18, 16)
        h_lay.setSpacing(16)

        header_copy = QVBoxLayout()
        header_copy.setSpacing(4)
        self.lbl_header_kicker = QLabel("LIBRARY WORKSPACE")
        header_copy.addWidget(self.lbl_header_kicker)
        self.lbl_header_title = QLabel("Tag Library")
        header_copy.addWidget(self.lbl_header_title)
        self.lbl_header_subtitle = QLabel(
            "Browse tagged files, review saved fields, and keep reusable tags organized in one calmer workspace."
        )
        self.lbl_header_subtitle.setWordWrap(True)
        header_copy.addWidget(self.lbl_header_subtitle)
        h_lay.addLayout(header_copy)
        h_lay.addStretch()

        self.lbl_stats = QLabel("")
        self.lbl_stats.setMinimumWidth(260)
        self.lbl_stats.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h_lay.addWidget(self.lbl_stats)
        self.btn_open_library = QPushButton("Open Library Folder")
        self.btn_open_library.setProperty("class", "primary")
        self.btn_open_library.clicked.connect(self._on_open_library)
        h_lay.addWidget(self.btn_open_library)

        lay.addWidget(self.header)

        # ── Main splitter: Tags (left) | Entries (right) ─────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Tag Management ──────────────────────────────────────────
        self.tag_panel = QFrame()
        self.tag_panel.setProperty("class", "card")
        tag_lay = QVBoxLayout(self.tag_panel)
        tag_lay.setContentsMargins(16, 16, 16, 16)
        tag_lay.setSpacing(10)

        self.lbl_tag_section = QLabel("Tag structure")
        tag_lay.addWidget(self.lbl_tag_section)
        self.lbl_tag_hint = QLabel("Filter reusable tags, create quick presets, and import or export tag packs.")
        self.lbl_tag_hint.setWordWrap(True)
        tag_lay.addWidget(self.lbl_tag_hint)

        # Tag search
        tag_search_row = QHBoxLayout()
        tag_search_row.setSpacing(6)
        self.txt_tag_search = QLineEdit()
        self.txt_tag_search.setPlaceholderText("Search tags…")
        self.txt_tag_search.textChanged.connect(self._on_tag_search)
        tag_search_row.addWidget(self.txt_tag_search, 1)
        self.btn_add_tag = QPushButton("New Tag")
        self.btn_add_tag.setProperty("class", "success")
        self.btn_add_tag.setToolTip("Create a new reusable tag")
        self.btn_add_tag.clicked.connect(self._on_add_tag)
        tag_search_row.addWidget(self.btn_add_tag)
        tag_lay.addLayout(tag_search_row)

        # Namespace filter
        ns_row = QHBoxLayout()
        ns_row.setSpacing(6)
        self.lbl_ns_filter = QLabel("Namespace:")
        self.lbl_ns_filter.setFixedWidth(70)
        ns_row.addWidget(self.lbl_ns_filter)
        self.cmb_ns_filter = QComboBox()
        self.cmb_ns_filter.addItem("All namespaces")
        self.cmb_ns_filter.currentTextChanged.connect(self._on_ns_filter_changed)
        ns_row.addWidget(self.cmb_ns_filter, 1)
        self.chk_show_hidden = QCheckBox("Hidden")
        self.chk_show_hidden.setToolTip("Show hidden tags")
        self.chk_show_hidden.stateChanged.connect(lambda _: self._refresh_tags())
        ns_row.addWidget(self.chk_show_hidden)
        tag_lay.addLayout(ns_row)

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
        self.lbl_quick = QLabel("Quick tags")
        quick_row.addWidget(self.lbl_quick)
        for preset_name in ["Favorite", "Important", "Review", "Archive"]:
            btn = QPushButton(preset_name)
            btn.setProperty("class", "toolbar")
            btn.clicked.connect(lambda checked, n=preset_name: self._quick_create_tag(n))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        tag_lay.addLayout(quick_row)

        # Tag Pack import/export buttons
        pack_row = QHBoxLayout()
        pack_row.setSpacing(4)
        self.btn_import = QPushButton("Import Tag Pack")
        self.btn_import.setProperty("class", "toolbar")
        self.btn_import.clicked.connect(self._import_tag_pack)
        pack_row.addWidget(self.btn_import)
        self.btn_export_pack = QPushButton("Export Tag Pack")
        self.btn_export_pack.setProperty("class", "toolbar")
        self.btn_export_pack.clicked.connect(self._export_tag_pack)
        pack_row.addWidget(self.btn_export_pack)
        self.btn_broken_links = QPushButton("Scan Broken Links")
        self.btn_broken_links.setProperty("class", "toolbar")
        self.btn_broken_links.clicked.connect(self._on_scan_broken_links)
        pack_row.addWidget(self.btn_broken_links)
        pack_row.addStretch()
        tag_lay.addLayout(pack_row)

        splitter.addWidget(self.tag_panel)

        # ── Right: Entry List + Preview ──────────────────────────────────
        self.entry_panel = QFrame()
        self.entry_panel.setProperty("class", "card")
        entry_lay = QVBoxLayout(self.entry_panel)
        entry_lay.setContentsMargins(16, 16, 16, 16)
        entry_lay.setSpacing(10)

        self.lbl_entry_section = QLabel("Library files")
        entry_lay.addWidget(self.lbl_entry_section)
        self.lbl_entry_hint = QLabel("Review files, search by metadata, and send tags or fields where they belong.")
        self.lbl_entry_hint.setWordWrap(True)
        entry_lay.addWidget(self.lbl_entry_hint)

        # Entry header
        entry_header = QHBoxLayout()
        entry_header.setSpacing(6)
        self.lbl_entry_title = QLabel("All Files")
        entry_header.addWidget(self.lbl_entry_title)
        entry_header.addStretch()

        self.txt_entry_search = QLineEdit()
        self.txt_entry_search.setPlaceholderText(
            "Search… (tag:Name, ext:pdf, rating:3, inbox:true, ns:namespace, group:name)"
        )
        self.txt_entry_search.setFixedWidth(250)
        self.txt_entry_search.textChanged.connect(self._on_entry_search)
        entry_header.addWidget(self.txt_entry_search)

        # Semantic search (natural language)
        self.txt_semantic = QLineEdit()
        self.txt_semantic.setPlaceholderText("Semantic search in natural language…")
        self.txt_semantic.setFixedWidth(200)
        self.txt_semantic.returnPressed.connect(self._on_semantic_search)
        entry_header.addWidget(self.txt_semantic)

        self.btn_add_files = QPushButton("Add Files")
        self.btn_add_files.setProperty("class", "primary")
        self.btn_add_files.clicked.connect(self._on_add_files)
        entry_header.addWidget(self.btn_add_files)

        self.btn_scan_dir = QPushButton("Scan Folder")
        self.btn_scan_dir.setProperty("class", "success")
        self.btn_scan_dir.clicked.connect(self._on_scan_directory)
        entry_header.addWidget(self.btn_scan_dir)

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
        self.detail_bar = QFrame()
        db_lay = QHBoxLayout(self.detail_bar)
        db_lay.setContentsMargins(12, 8, 12, 8)
        db_lay.setSpacing(8)
        self.lbl_assign = QLabel("Assign tag")
        db_lay.addWidget(self.lbl_assign)
        self.cmb_assign_tag = QComboBox()
        self.cmb_assign_tag.setMinimumWidth(160)
        self.cmb_assign_tag.setEditable(True)
        self.cmb_assign_tag.setPlaceholderText("Select or type tag...")
        db_lay.addWidget(self.cmb_assign_tag)
        self.btn_assign = QPushButton("Apply Tag")
        self.btn_assign.setProperty("class", "primary")
        self.btn_assign.clicked.connect(self._on_apply_tag_to_selected)
        db_lay.addWidget(self.btn_assign)
        self.btn_remove_tag = QPushButton("Remove Tag")
        self.btn_remove_tag.setProperty("class", "danger")
        self.btn_remove_tag.clicked.connect(self._on_remove_tag_from_selected)
        db_lay.addWidget(self.btn_remove_tag)
        db_lay.addStretch()

        # Rating stars
        self.lbl_rating = QLabel("Rating:")
        db_lay.addWidget(self.lbl_rating)
        self._rating_btns = []
        for star_i in range(5):
            sb = QPushButton("☆")
            sb.setFixedSize(22, 22)
            sb.setProperty("class", "toolbar")
            sb.clicked.connect(lambda checked, si=star_i: self._set_rating(si + 1))
            db_lay.addWidget(sb)
            self._rating_btns.append(sb)

        # Inbox toggle
        self.btn_inbox = QPushButton("Inbox")
        self.btn_inbox.setProperty("class", "toolbar")
        self.btn_inbox.setCheckable(True)
        self.btn_inbox.setToolTip("Toggle Inbox/Archive state for selected entries")
        self.btn_inbox.clicked.connect(self._on_toggle_inbox)
        db_lay.addWidget(self.btn_inbox)

        self.lbl_selection_info = QLabel("")
        db_lay.addWidget(self.lbl_selection_info)
        entry_lay.addWidget(self.detail_bar)

        splitter.addWidget(self.entry_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        lay.addWidget(splitter, 1)
        self.apply_theme()

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
        if entry.rating:
            meta_parts.append(f"Rating: {'★' * entry.rating}{'☆' * (5 - entry.rating)}")
        if entry.is_inbox is not None:
            meta_parts.append("Inbox" if entry.is_inbox else "Archived")
        if entry.source_url:
            meta_parts.append(f"Source: {entry.source_url[:40]}...")
        if entry.word_count:
            meta_parts.append(f"{entry.word_count:,} words")
        if entry.media_duration:
            mins = int(entry.media_duration // 60)
            secs = int(entry.media_duration % 60)
            meta_parts.append(f"{mins}:{secs:02d}")
        if entry.media_width and entry.media_height:
            meta_parts.append(f"{entry.media_width}×{entry.media_height}")
        meta_parts.append(str(entry.path))
        self._preview_meta.setText("  |  ".join(meta_parts))

        # Update rating display
        if hasattr(self, '_rating_btns'):
            self._update_rating_display(entry.rating or 0)
        # Update inbox toggle
        if hasattr(self, 'btn_inbox'):
            self.btn_inbox.setChecked(entry.is_inbox if entry.is_inbox is not None else True)

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
        self._preview_meta.setText("Select a single file to inspect its preview, tags, and saved fields.")
        self._preview_thumb.setPixmap(QPixmap())
        self._preview_thumb.setText("Preview")
        self._preview_thumb.setStyleSheet(
            f"background: {_t['bg']}; border: 1px solid {_t['border']}; border-radius: 6px;")
        self._clear_tag_chips()
        self._preview_fields.setHtml("<i style='color: gray;'>Fields and AI metadata will appear here.</i>")

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
        self.lbl_header_subtitle.setStyleSheet(
            f"color: {t['muted']}; font-size: 12px; line-height: 1.4em;"
        )
        self.lbl_stats.setStyleSheet(
            f"background: {t['header_bg']}; color: {t['muted']}; border: 1px solid {t['border']}; "
            "border-radius: 999px; padding: 6px 12px; font-size: 11px; font-weight: 600;"
        )
        for panel in (self.tag_panel, self.entry_panel):
            panel.setStyleSheet(
                f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; border-radius: 18px; }}"
            )
        self.lbl_tag_section.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 15px; font-weight: 700;"
        )
        self.lbl_tag_hint.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        self.lbl_quick.setStyleSheet(
            f"color: {t['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1.2px;"
        )
        self.lbl_entry_section.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 15px; font-weight: 700;"
        )
        self.lbl_entry_hint.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        self.lbl_entry_title.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 13px; font-weight: 700;"
        )
        self.detail_bar.setStyleSheet(
            f"QFrame {{ background: {t['header_bg']}; border: 1px solid {t['border']}; border-radius: 14px; }}"
        )
        self.lbl_assign.setStyleSheet(
            f"color: {t['muted']}; font-size: 11px; font-weight: 600;"
        )
        self.lbl_selection_info.setStyleSheet(
            f"color: {t['muted']}; font-size: 11px;"
        )
        self._preview_widget.setStyleSheet(
            f"QFrame {{ background: {t['header_bg']}; border: 1px solid {t['border']}; border-radius: 16px; }}"
        )
        if self.tbl_entries.selectionModel() and self.tbl_entries.selectionModel().selectedRows():
            self._on_entry_selection_changed()
        else:
            self._clear_preview()

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
            self.lbl_stats.setText("Open a library folder to browse tags and entries")
            return
        stats = self._lib.get_stats()
        self.lbl_stats.setText(
            f"{stats['entries']} files  •  {stats['tags']} tags  •  "
            f"{stats['tagged_entries']} tagged")

    # ── Tag Operations ────────────────────────────────────────────────────

    def _refresh_tags(self, namespace_filter: str | None = None):
        self.tag_tree.clear()
        self.cmb_assign_tag.clear()
        if not self._lib.is_open:
            return

        tags = self._lib.get_all_tags()
        # Apply namespace filter
        show_hidden = self.chk_show_hidden.isChecked() if hasattr(self, 'chk_show_hidden') else False
        if not show_hidden:
            tags = [t for t in tags if not t.is_hidden]
        if namespace_filter:
            ns_tag_ids = {t.id for t in self._lib.get_tags_by_namespace(namespace_filter)}
            tags = [t for t in tags if t.id in ns_tag_ids]

        # Fetch all entry counts in one query (avoids N+1)
        entry_counts = self._lib.get_tag_entry_counts()

        # Build hierarchy: category tags at top, children below
        categories = [t for t in tags if t.is_category]
        non_cat = [t for t in tags if not t.is_category]

        for cat in sorted(categories, key=lambda t: t.name):
            display_name = f"{cat.icon} {cat.name}" if cat.icon else cat.name
            if cat.namespace:
                display_name = f"[{cat.namespace}] {display_name}"
            item = QTreeWidgetItem([display_name, ""])
            item.setData(0, Qt.ItemDataRole.UserRole, cat.id)
            color = TAG_COLORS.get(cat.color_slug or "blue", "#3b82f6")
            item.setForeground(0, QColor(color))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable)
            count = entry_counts.get(cat.id, 0)
            item.setText(1, str(count) if count else "")
            self.tag_tree.addTopLevelItem(item)

            # Add child tags
            children = [t for t in non_cat if cat.id in t.parent_ids]
            for child in sorted(children, key=lambda t: t.name):
                child_display = f"{child.icon} {child.name}" if child.icon else child.name
                if child.namespace:
                    child_display = f"[{child.namespace}] {child_display}"
                c_item = QTreeWidgetItem([child_display, ""])
                c_item.setData(0, Qt.ItemDataRole.UserRole, child.id)
                c_count = entry_counts.get(child.id, 0)
                c_item.setText(1, str(c_count) if c_count else "")
                item.addChild(c_item)
                non_cat = [t for t in non_cat if t.id != child.id]

        # Orphan tags (no parent, not category)
        if non_cat:
            orphan_root = QTreeWidgetItem(["Uncategorized", ""])
            orphan_root.setForeground(0, QColor(TAG_COLORS.get("slate", "#64748b")))
            for t in sorted(non_cat, key=lambda t: t.name):
                orphan_display = f"{t.icon} {t.name}" if t.icon else t.name
                if t.namespace:
                    orphan_display = f"[{t.namespace}] {orphan_display}"
                o_item = QTreeWidgetItem([orphan_display, ""])
                o_item.setData(0, Qt.ItemDataRole.UserRole, t.id)
                o_count = entry_counts.get(t.id, 0)
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
            self.lbl_entry_title.setText("All Files")
            self._refresh_entries()
            return
        self._current_tag_id = tag_id
        tag = self._lib.get_tag(tag_id)
        self.lbl_entry_title.setText(f"Tag: {tag.name}" if tag else "All Files")
        self._refresh_entries(tag_id=tag_id)

    def _on_add_tag(self):
        if not self._lib.is_open:
            self.lbl_selection_info.setText("Open a library before creating tags")
            return
        name, ok = QInputDialog.getText(self, "Add Tag", "Tag name:")
        if ok and name.strip():
            self._lib.add_tag(name.strip())
            self._refresh_tags()
            self._update_stats()
            self.lbl_selection_info.setText(f"Created tag '{name.strip()}'")

    def _quick_create_tag(self, name: str):
        if not self._lib.is_open:
            self.lbl_selection_info.setText("Open a library before creating quick tags")
            return
        self._lib.add_tag(name, is_category=True, color_slug="blue")
        self._refresh_tags()
        self._update_stats()
        self.lbl_selection_info.setText(f"Created quick tag '{name}'")

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
        menu.addAction("Set Parent Tag...", lambda: self._set_parent_tag(tag_id))
        menu.addAction("Toggle Category", lambda: self._toggle_category(tag_id))
        menu.addSeparator()
        menu.addAction("Set Description...", lambda: self._set_tag_description(tag_id))
        menu.addAction("Set Namespace...", lambda: self._set_tag_namespace(tag_id))
        menu.addAction("Set Icon...", lambda: self._set_tag_icon(tag_id))
        menu.addAction("Toggle Hidden", lambda: self._toggle_hidden(tag_id))
        menu.addSeparator()
        menu.addAction("Merge Into...", lambda: self._merge_tag_into(tag_id))
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

    def _set_parent_tag(self, tag_id: int):
        tag = self._lib.get_tag(tag_id)
        if not tag:
            return
        all_tags = self._lib.get_all_tags()
        candidates = [t for t in all_tags if t.id != tag_id]
        if not candidates:
            return
        names = [t.name for t in candidates]
        name, ok = QInputDialog.getItem(
            self, "Set Parent Tag",
            f"Select parent tag for '{tag.name}':",
            names, 0, False)
        if ok and name:
            parent = next((t for t in candidates if t.name == name), None)
            if parent:
                self._lib.add_parent_tag(tag_id, parent.id)
                self._refresh_tags()

    def _import_tag_pack(self):
        if not self._lib.is_open:
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Import Tag Pack", "", "Tag Packs (*.json *.toml);;JSON (*.json);;TOML (*.toml);;All Files (*)")
        if not filepath:
            return
        result = self._lib.import_tag_pack(filepath)
        self._refresh_tags()
        self._update_stats()
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Tag Pack Imported",
            f"Imported: {result['imported']}\n"
            f"Skipped (existing): {result['skipped']}\n"
            f"Errors: {result['errors']}")

    def _export_tag_pack(self):
        if not self._lib.is_open:
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Tag Pack", "tag_pack.toml",
            "Tag Packs (*.toml *.json);;TOML (*.toml);;JSON (*.json);;All Files (*)")
        if not filepath:
            return
        selected_ids = None
        sel = self.tag_tree.selectedItems()
        if sel:
            ids = [item.data(0, Qt.ItemDataRole.UserRole) for item in sel]
            ids = [i for i in ids if i is not None]
            if ids:
                selected_ids = ids
        self._lib.export_tag_pack(filepath, tag_ids=selected_ids)

    def _on_semantic_search(self):
        query = self.txt_semantic.text().strip()
        if not self._lib.is_open:
            self.lbl_selection_info.setText("Open a library before running semantic search")
            return
        if not query:
            self.lbl_selection_info.setText("Enter a natural-language prompt to search semantically")
            return
        try:
            from unifile.semantic import SemanticIndex
            idx = SemanticIndex()
            if not idx.is_available():
                self.lbl_selection_info.setText("Semantic search unavailable (no embedding model)")
                return
            results = idx.search(query, top_k=50)
            if not results:
                self.lbl_selection_info.setText("No semantic matches found")
                self.tbl_entries.setRowCount(0)
                return
            paths = [r['path'] for r in results]
            entries = []
            for p in paths:
                entry = self._lib.get_entry_by_path(p)
                if entry:
                    entries.append(entry)
            self.tbl_entries.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                item_name = QTableWidgetItem(entry.filename)
                item_name.setData(Qt.ItemDataRole.UserRole, entry.id)
                self.tbl_entries.setItem(row, 0, item_name)
                tag_str = ", ".join(entry.tag_names) if hasattr(entry, 'tag_names') else ""
                self.tbl_entries.setItem(row, 1, QTableWidgetItem(tag_str))
                self.tbl_entries.setItem(row, 2, QTableWidgetItem(entry.suffix.upper()))
                mod = entry.date_modified.strftime("%Y-%m-%d") if entry.date_modified else ""
                self.tbl_entries.setItem(row, 3, QTableWidgetItem(mod))
                self.tbl_entries.setItem(row, 4, QTableWidgetItem(str(entry.path)))
            self.lbl_selection_info.setText(f"{len(entries)} semantic matches")
        except Exception as e:
            self.lbl_selection_info.setText(f"Semantic search error: {e}")

    # ── Entry Operations ──────────────────────────────────────────────────

    def _refresh_entries(self, tag_id: int | None = None):
        self.tbl_entries.setRowCount(0)
        if not self._lib.is_open:
            self.lbl_entry_title.setText("Open a library to begin")
            self.lbl_selection_info.setText("No library open")
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

        self.lbl_selection_info.setText(
            f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}"
            if entries else
            "No files yet. Add files directly or scan a folder into the library."
        )

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
        self.lbl_selection_info.setText(
            f"{len(entries)} result{'s' if len(entries) != 1 else ''}"
            if entries else
            "No matching files found"
        )

    def _on_add_files(self):
        if not self._lib.is_open:
            self.lbl_selection_info.setText("Open a library before adding files")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Add Files to Library")
        if files:
            count = self._lib.add_entries_bulk(files)
            self._refresh_entries()
            self._update_stats()
            self.lbl_selection_info.setText(f"Added {count} file{'s' if count != 1 else ''} to the library")

    def _on_scan_directory(self):
        if not self._lib.is_open:
            self.lbl_selection_info.setText("Open a library before scanning a folder")
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
            self.lbl_selection_info.setText(
                f"Scanned {count} file{'s' if count != 1 else ''} from {os.path.basename(path) or path}"
            )

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
        menu.addSeparator()
        menu.addAction("Set Source URL...", lambda: self._set_source_url(entry_ids))
        menu.addAction("Set Inbox", lambda: self._set_entries_inbox(entry_ids, True))
        menu.addAction("Set Archived", lambda: self._set_entries_inbox(entry_ids, False))
        menu.addSeparator()
        # Entry groups submenu
        groups = self._lib.get_all_groups() if self._lib.is_open else []
        if groups:
            grp_menu = menu.addMenu("Add to Group")
            for g in groups:
                grp_menu.addAction(g.name, lambda checked, gid=g.id: self._lib.add_entries_to_group(gid, entry_ids))
        menu.addAction("Create Group from Selection...", lambda: self._create_group_from_selection(entry_ids))
        menu.exec(self.tbl_entries.mapToGlobal(pos))

    def _on_apply_tag_to_selected(self):
        if not self._lib.is_open:
            self.lbl_selection_info.setText("Open a library before applying tags")
            return
        tag_name = self.cmb_assign_tag.currentText().strip()
        if not tag_name:
            self.lbl_selection_info.setText("Choose or type a tag name first")
            return

        # Get or create the tag
        tag = self._lib.get_tag_by_name(tag_name)
        if not tag:
            tag = self._lib.add_tag(tag_name)
        if not tag:
            return

        rows = set(idx.row() for idx in self.tbl_entries.selectedIndexes())
        if not rows:
            self.lbl_selection_info.setText("Select one or more files before applying a tag")
            return
        for r in rows:
            item = self.tbl_entries.item(r, 0)
            if item:
                entry_id = item.data(Qt.ItemDataRole.UserRole)
                self._lib.add_tags_to_entry(entry_id, [tag.id])

        self._refresh_entries(tag_id=self._current_tag_id)
        self._refresh_tags()
        self._update_stats()
        self.tag_applied.emit(tag_name)
        self.lbl_selection_info.setText(
            f"Applied '{tag_name}' to {len(rows)} file{'s' if len(rows) != 1 else ''}"
        )

    def _on_remove_tag_from_selected(self):
        if not self._lib.is_open:
            self.lbl_selection_info.setText("Open a library before removing tags")
            return
        tag_name = self.cmb_assign_tag.currentText().strip()
        if not tag_name:
            self.lbl_selection_info.setText("Choose a tag to remove")
            return
        tag = self._lib.get_tag_by_name(tag_name)
        if not tag:
            self.lbl_selection_info.setText(f"Tag '{tag_name}' does not exist in this library")
            return

        rows = set(idx.row() for idx in self.tbl_entries.selectedIndexes())
        if not rows:
            self.lbl_selection_info.setText("Select one or more files before removing a tag")
            return
        for r in rows:
            item = self.tbl_entries.item(r, 0)
            if item:
                entry_id = item.data(Qt.ItemDataRole.UserRole)
                self._lib.remove_tags_from_entry(entry_id, [tag.id])

        self._refresh_entries(tag_id=self._current_tag_id)
        self._refresh_tags()
        self._update_stats()
        self.lbl_selection_info.setText(
            f"Removed '{tag_name}' from {len(rows)} file{'s' if len(rows) != 1 else ''}"
        )

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
        self.lbl_selection_info.setText(
            f"Removed {len(entry_ids)} item{'s' if len(entry_ids) != 1 else ''} from the library"
        )

    def _on_ns_filter_changed(self, ns_text: str):
        """Refresh tags filtered by selected namespace."""
        if not self._lib.is_open:
            return
        self._refresh_tags(namespace_filter=ns_text if ns_text != "All namespaces" else None)

    def _refresh_ns_filter(self):
        """Repopulate the namespace filter combo."""
        if not self._lib.is_open:
            return
        current = self.cmb_ns_filter.currentText()
        self.cmb_ns_filter.blockSignals(True)
        self.cmb_ns_filter.clear()
        self.cmb_ns_filter.addItem("All namespaces")
        for ns in self._lib.get_all_namespaces():
            self.cmb_ns_filter.addItem(ns)
        idx = self.cmb_ns_filter.findText(current)
        if idx >= 0:
            self.cmb_ns_filter.setCurrentIndex(idx)
        self.cmb_ns_filter.blockSignals(False)

    def _set_tag_description(self, tag_id: int):
        tag = self._lib.get_tag(tag_id)
        if not tag:
            return
        desc, ok = QInputDialog.getMultiLineText(
            self, "Set Description", "Tag description:", tag.description or "")
        if ok:
            self._lib.update_tag(tag_id, description=desc.strip() or None)

    def _set_tag_namespace(self, tag_id: int):
        tag = self._lib.get_tag(tag_id)
        if not tag:
            return
        ns, ok = QInputDialog.getText(
            self, "Set Namespace",
            "Namespace (e.g. 'genre', 'year', 'project'):",
            text=tag.namespace or "")
        if ok:
            self._lib.update_tag(tag_id, namespace=ns.strip() or None)
            self._refresh_tags()
            self._refresh_ns_filter()

    def _set_tag_icon(self, tag_id: int):
        tag = self._lib.get_tag(tag_id)
        if not tag:
            return
        icon, ok = QInputDialog.getText(
            self, "Set Icon",
            "Icon character or emoji (single char):",
            text=tag.icon or "")
        if ok:
            self._lib.update_tag(tag_id, icon=icon.strip()[:2] or None)
            self._refresh_tags()

    def _toggle_hidden(self, tag_id: int):
        tag = self._lib.get_tag(tag_id)
        if tag:
            self._lib.update_tag(tag_id, is_hidden=not tag.is_hidden)
            self._refresh_tags()

    def _merge_tag_into(self, source_id: int):
        all_tags = self._lib.get_all_tags()
        candidates = [t for t in all_tags if t.id != source_id]
        if not candidates:
            return
        names = [t.name for t in candidates]
        name, ok = QInputDialog.getItem(
            self, "Merge Tag",
            "Merge INTO this tag (source tag entries will be moved to target, source deleted):",
            names, 0, False)
        if ok and name:
            target = next((t for t in candidates if t.name == name), None)
            if target:
                from PyQt6.QtWidgets import QMessageBox
                ok2 = QMessageBox.question(
                    self, "Confirm Merge",
                    f"Merge all entries from source tag into '{target.name}' and delete source tag?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                ) == QMessageBox.StandardButton.Yes
                if ok2:
                    self._lib.merge_tags(source_id, target.id)
                    self._refresh_tags()
                    self._refresh_entries()
                    self._update_stats()

    def _set_rating(self, rating: int):
        if not self._lib.is_open:
            return
        rows = set(idx.row() for idx in self.tbl_entries.selectedIndexes())
        if not rows:
            return
        for r in rows:
            item = self.tbl_entries.item(r, 0)
            if item:
                self._lib.set_entry_rating(item.data(Qt.ItemDataRole.UserRole), rating)
        self._update_rating_display(rating)

    def _update_rating_display(self, rating: int):
        for i, btn in enumerate(self._rating_btns):
            btn.setText("★" if i < rating else "☆")

    def _on_toggle_inbox(self, checked: bool):
        if not self._lib.is_open:
            return
        rows = set(idx.row() for idx in self.tbl_entries.selectedIndexes())
        for r in rows:
            item = self.tbl_entries.item(r, 0)
            if item:
                self._lib.set_entry_inbox(item.data(Qt.ItemDataRole.UserRole), checked)

    def _set_source_url(self, entry_ids: list[int]):
        url, ok = QInputDialog.getText(self, "Set Source URL", "URL (where this file was downloaded from):")
        if ok and url.strip():
            for eid in entry_ids:
                self._lib.set_entry_source_url(eid, url.strip())

    def _set_entries_inbox(self, entry_ids: list[int], is_inbox: bool):
        for eid in entry_ids:
            self._lib.set_entry_inbox(eid, is_inbox)
        state = "Inbox" if is_inbox else "Archived"
        self.lbl_selection_info.setText(f"Marked {len(entry_ids)} file(s) as {state}")

    def _create_group_from_selection(self, entry_ids: list[int]):
        if not entry_ids:
            return
        name, ok = QInputDialog.getText(self, "Create Group", "Group name:")
        if ok and name.strip():
            group = self._lib.create_entry_group(name.strip())
            self._lib.add_entries_to_group(group.id, entry_ids)
            self.lbl_selection_info.setText(f"Created group '{name.strip()}' with {len(entry_ids)} file(s)")

    def _on_scan_broken_links(self):
        if not self._lib.is_open:
            self.lbl_selection_info.setText("Open a library first")
            return
        broken = self._lib.scan_broken_links()
        if not broken:
            self.lbl_selection_info.setText("No broken links found — all files are present")
            return
        # Show broken entries in the table
        self.tbl_entries.setRowCount(len(broken))
        for row, entry in enumerate(broken):
            item_name = QTableWidgetItem(entry.filename)
            item_name.setData(Qt.ItemDataRole.UserRole, entry.id)
            item_name.setForeground(QColor("#ef4444"))
            self.tbl_entries.setItem(row, 0, item_name)
            self.tbl_entries.setItem(row, 1, QTableWidgetItem("BROKEN LINK"))
            self.tbl_entries.setItem(row, 2, QTableWidgetItem(entry.suffix.upper()))
            self.tbl_entries.setItem(row, 3, QTableWidgetItem(""))
            self.tbl_entries.setItem(row, 4, QTableWidgetItem(str(entry.path)))
        self.lbl_entry_title.setText(f"Broken Links ({len(broken)})")
        self.lbl_selection_info.setText(
            f"{len(broken)} broken link{'s' if len(broken) != 1 else ''}. Right-click to relink.")
