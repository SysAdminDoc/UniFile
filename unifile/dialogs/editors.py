"""UniFile dialogs — Editor dialogs (Categories, Templates, Rules, File Browser)."""
import os, re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QCheckBox, QTextEdit, QHeaderView, QFileDialog, QAbstractItemView,
    QDialog, QDialogButtonBox, QSpinBox,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QFrame,
    QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from unifile.config import (
    get_active_theme, get_active_stylesheet
)
from unifile.categories import (
    load_custom_categories
)
from unifile.files import (
    _load_pc_categories, _save_pc_categories, _DEFAULT_PC_CATEGORIES,
    import_classifier_config, export_classifier_config, merge_categories,
)
from unifile.engine import RuleEngine, RenameTemplateEngine
from unifile.config import _APP_DATA_DIR


_PC_CATEGORIES_DB = os.path.join(_APP_DATA_DIR, 'pc_categories.json')


class CustomCategoriesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Categories")
        self.setMinimumSize(550, 450)
        self.setStyleSheet(get_active_stylesheet())
        self.custom_cats = load_custom_categories()

        lay = QVBoxLayout(self)
        lbl = QLabel("Add, edit, or remove custom categories. These supplement the built-in categories.")
        lbl.setWordWrap(True); lay.addWidget(lbl)

        self.lst = QListWidget()
        self._refresh_list()
        lay.addWidget(self.lst)

        btn_row = QHBoxLayout()
        for text, cb in [("Add", self._add), ("Edit Keywords", self._edit), ("Remove", self._remove)]:
            b = QPushButton(text); b.clicked.connect(cb); btn_row.addWidget(b)
        lay.addLayout(btn_row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _refresh_list(self):
        self.lst.clear()
        for name, kws in self.custom_cats:
            self.lst.addItem(f"{name}  [{', '.join(kws[:5])}{'...' if len(kws)>5 else ''}]")

    def _add(self):
        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        if not ok or not name.strip(): return
        kws, ok2 = QInputDialog.getText(self, "Keywords", "Comma-separated keywords:")
        if not ok2: return
        keywords = [k.strip().lower() for k in kws.split(',') if k.strip()]
        if not keywords: keywords = [name.strip().lower()]
        self.custom_cats.append((name.strip(), keywords))
        self._refresh_list()

    def _edit(self):
        row = self.lst.currentRow()
        if row < 0: return
        name, kws = self.custom_cats[row]
        new_kws, ok = QInputDialog.getText(self, f"Edit Keywords: {name}",
            "Comma-separated keywords:", text=', '.join(kws))
        if not ok: return
        keywords = [k.strip().lower() for k in new_kws.split(',') if k.strip()]
        if keywords:
            self.custom_cats[row] = (name, keywords)
            self._refresh_list()

    def _remove(self):
        row = self.lst.currentRow()
        if row < 0: return
        self.custom_cats.pop(row)
        self._refresh_list()

    def get_categories(self):
        return list(self.custom_cats)


class DestTreeDialog(QDialog):
    def __init__(self, items, dest_root, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Destination Preview")
        self.setMinimumSize(500, 500)
        self.setStyleSheet(get_active_stylesheet())

        import shutil
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Output structure under: {dest_root}"))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder / Category", "Count"])
        self.tree.setColumnWidth(0, 350)

        # Build tree from items
        cats = {}
        for it in items:
            if it.selected and it.status == "Pending":
                cats.setdefault(it.category, []).append(it.folder_name)

        for cat in sorted(cats.keys()):
            cat_item = QTreeWidgetItem([cat, str(len(cats[cat]))])
            cat_item.setForeground(0, QColor("#4ade80"))
            for folder in sorted(cats[cat]):
                child = QTreeWidgetItem([folder, ""])
                cat_item.addChild(child)
            self.tree.addTopLevelItem(cat_item)

        self.tree.expandAll()
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree)

        # ── Disk Space Impact ────────────────────────────────────────────────
        total_bytes = sum(getattr(it, 'size', 0) for it in items if it.selected and it.status == "Pending")
        try:
            disk = shutil.disk_usage(dest_root if os.path.isdir(dest_root) else os.path.splitdrive(dest_root)[0] or '/')
            free_bytes = disk.free
            pct = (total_bytes / free_bytes * 100) if free_bytes > 0 else 0
            def _fmt(b):
                for u in ['B', 'KB', 'MB', 'GB', 'TB']:
                    if b < 1024: return f"{b:.1f} {u}"
                    b /= 1024
                return f"{b:.1f} PB"
            space_text = f"Move size: {_fmt(total_bytes)}  |  Free: {_fmt(free_bytes)}  |  Impact: {pct:.1f}%"
            color = "#ef4444" if pct > 90 else ("#f59e0b" if pct > 70 else "#4ade80")
            if free_bytes < total_bytes:
                space_text += "  !! INSUFFICIENT SPACE !!"
                color = "#ef4444"
        except Exception:
            space_text = f"Move size: {total_bytes:,} bytes (could not read disk info)"
            color = "#6b7785"
        lbl_space = QLabel(space_text)
        lbl_space.setStyleSheet(f"color: {color}; font-size: 12px; padding: 6px 4px; font-weight: bold;")
        lay.addWidget(lbl_space)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Close)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class TemplateBuilderWidget(QWidget):
    """Visual template builder with clickable token palette and live preview."""
    template_changed = pyqtSignal(str)

    _TOKEN_GROUPS = {
        'File':    ['name', 'original_name', 'ext', 'parent', 'category', 'size'],
        'Date':    ['year', 'month', 'month_name', 'day', 'hour', 'minute', 'second'],
        'Audio':   ['artist', 'album', 'title', 'genre', 'track', 'year_tag'],
        'Photo':   ['camera', 'camera_make', 'camera_model', 'width', 'height',
                     'city', 'country', 'scene', 'blur'],
        'AI':      ['vision_name', 'vision_ocr', 'smart_name', 'person', 'face_count'],
        'Counter': ['counter', 'counter:03d'],
    }

    _TOKEN_BTN_STYLE = None  # set dynamically in __init__

    def __init__(self, parent=None):
        super().__init__(parent)
        _t = get_active_theme()
        self._TOKEN_BTN_STYLE = (
            f"QPushButton {{ background: {_t['header_bg']}; color: {_t['sidebar_btn_active_fg']}; border: 1px solid {_t['sidebar_btn_hover_border']};"
            f"border-radius: 3px; padding: 2px 8px; font-size: 10px; font-family: 'Consolas','Courier New',monospace; }}"
            f"QPushButton:hover {{ background: {_t['sidebar_btn_hover_border']}; color: {_t['fg_bright']}; }}")
        self._raw_mode = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # Template input
        self.txt_template = QLineEdit()
        self.txt_template.setPlaceholderText("e.g. {year}-{month}-{day}_{name}  or  {artist} - {title}")
        self.txt_template.setStyleSheet(
            f"QLineEdit{{background:{_t['input_bg']};color:{_t['sidebar_btn_active_fg']};border:1px solid {_t['sidebar_btn_hover_border']};"
            f"border-radius:4px;padding:5px 8px;font-size:12px;font-family:'Consolas','Courier New',monospace}}")
        self.txt_template.textChanged.connect(self._on_text_changed)
        lay.addWidget(self.txt_template)

        # Token palette container
        self.palette_widget = QWidget()
        palette_lay = QVBoxLayout(self.palette_widget)
        palette_lay.setContentsMargins(0, 2, 0, 0)
        palette_lay.setSpacing(3)
        for group_name, tokens in self._TOKEN_GROUPS.items():
            row = QHBoxLayout(); row.setSpacing(3)
            lbl = QLabel(f"{group_name}:")
            lbl.setStyleSheet(f"color:{_t['muted']};font-size:10px;font-weight:bold;min-width:50px")
            lbl.setFixedWidth(50)
            row.addWidget(lbl)
            for tok in tokens:
                btn = QPushButton(f"{{{tok}}}")
                btn.setFixedHeight(22)
                btn.setStyleSheet(self._TOKEN_BTN_STYLE)
                btn.clicked.connect(lambda checked, t=tok: self._insert_token(t))
                row.addWidget(btn)
            row.addStretch()
            palette_lay.addLayout(row)

        # Conditional syntax hint
        cond_lbl = QLabel("Conditionals: {if:city}{city}{else}Unknown{endif}")
        cond_lbl.setStyleSheet(f"color:{_t['border_hover']};font-size:9px;font-style:italic;padding-left:4px")
        palette_lay.addWidget(cond_lbl)
        lay.addWidget(self.palette_widget)

        # Raw mode toggle + preview
        bottom = QHBoxLayout()
        self.btn_raw = QPushButton("Raw Mode")
        self.btn_raw.setFixedHeight(20)
        self.btn_raw.setCheckable(True)
        self.btn_raw.setStyleSheet(f"QPushButton{{font-size:10px;color:{_t['muted']};border:none;padding:0 6px}}"
                                    f"QPushButton:checked{{color:{_t['sidebar_btn_active_fg']}}}")
        self.btn_raw.toggled.connect(self._toggle_raw)
        bottom.addWidget(self.btn_raw)
        self.lbl_preview = QLabel("")
        self.lbl_preview.setStyleSheet(f"color:{_t['border_hover']};font-size:10px;font-style:italic;padding-left:4px")
        bottom.addWidget(self.lbl_preview, 1)
        lay.addLayout(bottom)

    def _insert_token(self, token: str):
        cur = self.txt_template.cursorPosition()
        text = self.txt_template.text()
        insert = f"{{{token}}}"
        self.txt_template.setText(text[:cur] + insert + text[cur:])
        self.txt_template.setCursorPosition(cur + len(insert))
        self.txt_template.setFocus()

    def _toggle_raw(self, checked):
        self._raw_mode = checked
        self.palette_widget.setVisible(not checked)

    def _on_text_changed(self, text):
        self.template_changed.emit(text)
        # Live preview with sample data
        if text.strip():
            sample = {'name': 'photo', 'ext': 'jpg', 'year': '2024', 'month': '03',
                      'day': '15', 'hour': '14', 'minute': '30', 'second': '00',
                      'artist': 'Artist', 'album': 'Album', 'title': 'Title',
                      'category': 'Images', 'counter': 1, 'city': 'Portland',
                      'person': 'Alice', 'face_count': '2', 'scene': 'portrait',
                      'camera': 'Canon EOS R5', 'vision_name': 'sunset_beach'}
            try:
                resolved = RenameTemplateEngine._resolve_conditionals(text, sample)
                resolved = re.sub(r'\{([^}]+)\}',
                    lambda m: str(sample.get(m.group(1).split(':')[0].strip().lower(), f'?{m.group(1)}')),
                    resolved)
                self.lbl_preview.setText(f"Preview: {resolved}")
            except Exception:
                self.lbl_preview.setText("")
        else:
            self.lbl_preview.setText("")

    def text(self) -> str:
        return self.txt_template.text()

    def setText(self, t: str):
        self.txt_template.setText(t)


class PCCategoryEditorDialog(QDialog):
    """Full-featured editor for PC file categories and their extension rules."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PC File Categories")
        self.setMinimumSize(820, 580)
        self.cats = _load_pc_categories()
        self._dirty = False
        self._build_ui()
        self._populate_list()
        if self.lst_cats.count():
            self.lst_cats.setCurrentRow(0)
        self.setObjectName("pc_cat_editor")
        _t = get_active_theme()
        self.setStyleSheet(f"""
            #pc_cat_editor{{background:{_t['bg']};color:{_t['fg_bright']}}}
            #pc_cat_editor QLabel{{color:{_t['muted']};font-size:11px}}
            #pc_cat_editor QLineEdit,#pc_cat_editor QTextEdit{{background:{_t['input_bg']};color:{_t['fg_bright']};
                border:1px solid {_t['sidebar_btn_hover_border']};border-radius:4px;padding:5px 8px;font-size:12px}}
            #pc_cat_editor QListWidget{{background:{_t['header_bg']};color:{_t['fg_bright']};border:1px solid {_t['border']};
                border-radius:4px;font-size:11px;alternate-background-color:{_t['bg_alt']}}}
            #pc_cat_editor QListWidget::item{{padding:5px 8px}}
            #pc_cat_editor QListWidget::item:selected{{background:{_t['selection']};color:{_t['fg_bright']}}}
            #pc_cat_editor QPushButton{{background:{_t['selection']};color:{_t['fg_bright']};border:none;
                border-radius:4px;padding:5px 14px;font-size:11px}}
            #pc_cat_editor QPushButton:hover{{background:{_t['border_hover']}}}
            #pc_cat_editor QPushButton#btn_save{{background:{_t['green_pressed']};color:{_t['green']};font-weight:bold;padding:7px 22px}}
            #pc_cat_editor QPushButton#btn_save:hover{{background:{_t['green_hover']}}}
            #pc_cat_editor QPushButton#btn_del{{background:#3a1a1a;color:#ef4444}}
            #pc_cat_editor QPushButton#btn_del:hover{{background:#5a1a1a}}
            #pc_cat_editor QPushButton#btn_reset{{background:#2a2a1a;color:#f59e0b}}
            #pc_cat_editor QFrame#divider{{background:{_t['sidebar_btn_hover_border']}}}
        """)

    def _build_ui(self):
        _t = get_active_theme()
        root = QHBoxLayout(self)
        root.setSpacing(0); root.setContentsMargins(0, 0, 0, 0)

        # ── Left: category list ──────────────────────────────────────────────
        left = QWidget(); left.setFixedWidth(230)
        left.setStyleSheet(f"background:{_t['header_bg']};border-right:1px solid {_t['sidebar_btn_hover_border']}")
        lv = QVBoxLayout(left); lv.setContentsMargins(10, 10, 10, 10); lv.setSpacing(6)
        lv.addWidget(QLabel("Categories"))
        self.lst_cats = QListWidget()
        self.lst_cats.currentRowChanged.connect(self._on_cat_select)
        lv.addWidget(self.lst_cats, 1)
        row_add = QHBoxLayout()
        btn_add = QPushButton("+ Add"); btn_add.clicked.connect(self._add_cat)
        self.btn_del = QPushButton("Delete"); self.btn_del.setObjectName("btn_del")
        self.btn_del.clicked.connect(self._del_cat)
        row_add.addWidget(btn_add); row_add.addWidget(self.btn_del)
        lv.addLayout(row_add)
        btn_reset = QPushButton("Reset to Defaults"); btn_reset.setObjectName("btn_reset")
        btn_reset.clicked.connect(self._reset_defaults)
        lv.addWidget(btn_reset)

        # Import/Export (classifier-compatible config)
        io_row = QHBoxLayout()
        btn_import = QPushButton("Import")
        btn_import.setToolTip("Import categories from a .conf file (classifier format)")
        btn_import.clicked.connect(self._import_config)
        io_row.addWidget(btn_import)
        btn_export = QPushButton("Export")
        btn_export.setToolTip("Export categories to a .conf file (classifier format)")
        btn_export.clicked.connect(self._export_config)
        io_row.addWidget(btn_export)
        lv.addLayout(io_row)

        root.addWidget(left)

        # ── Right: editor ────────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(16, 14, 16, 14); rv.setSpacing(10)

        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("Category Name:"))
        self.txt_name = QLineEdit(); self.txt_name.setPlaceholderText("e.g. Work Documents")
        self.txt_name.textChanged.connect(lambda: setattr(self, '_dirty', True))
        row_name.addWidget(self.txt_name, 1)
        row_name.addWidget(QLabel("  Color:"))
        self.txt_color = QLineEdit(); self.txt_color.setFixedWidth(80)
        self.txt_color.setPlaceholderText("#60a5fa")
        self.txt_color.textChanged.connect(self._preview_color)
        row_name.addWidget(self.txt_color)
        self.lbl_color_swatch = QLabel("  ██")
        row_name.addWidget(self.lbl_color_swatch)
        rv.addLayout(row_name)

        rv.addWidget(QLabel("File Extensions  (comma-separated, no dots — e.g.  doc, docx, pdf)"))
        self.txt_exts = QTextEdit(); self.txt_exts.setFixedHeight(80)
        self.txt_exts.setPlaceholderText("doc, docx, pdf, txt, rtf, odt…")
        self.txt_exts.textChanged.connect(lambda: setattr(self, '_dirty', True))
        rv.addWidget(self.txt_exts)

        rv.addWidget(QLabel("LLM Keywords  (hints for AI classification — optional)"))
        self.txt_kw = QLineEdit()
        self.txt_kw.setPlaceholderText("e.g. invoice, contract, report, letter")
        self.txt_kw.textChanged.connect(lambda: setattr(self, '_dirty', True))
        rv.addWidget(self.txt_kw)

        # Custom output directory
        rv.addWidget(QLabel("Output Directory  (leave empty to use default mapping)"))
        dst_row = QHBoxLayout()
        self.txt_dst = QLineEdit()
        self.txt_dst.setPlaceholderText("Default: auto-mapped (e.g. ~/Pictures for Images)")
        self.txt_dst.setStyleSheet(
            f"QLineEdit{{background:{_t['input_bg']};color:#f59e0b;border:1px solid {_t['sidebar_btn_hover_border']};"
            f"border-radius:4px;padding:5px 8px;font-size:12px;font-family:'Consolas','Courier New',monospace}}")
        self.txt_dst.textChanged.connect(lambda: setattr(self, '_dirty', True))
        dst_row.addWidget(self.txt_dst, 1)
        btn_dst = QPushButton("Browse…")
        btn_dst.setFixedHeight(28)
        btn_dst.clicked.connect(self._browse_dst)
        dst_row.addWidget(btn_dst)
        rv.addLayout(dst_row)
        self.lbl_dst_default = QLabel("")
        self.lbl_dst_default.setStyleSheet(f"color:{_t['border_hover']};font-size:10px;font-style:italic;padding-left:4px")
        rv.addWidget(self.lbl_dst_default)

        # Rename template (TemplateBuilderWidget with token palette)
        rv.addWidget(QLabel("Rename Template  (leave empty to keep original filename)"))
        self.template_builder = TemplateBuilderWidget()
        self.template_builder.template_changed.connect(lambda: setattr(self, '_dirty', True))
        self.template_builder.template_changed.connect(self._update_template_preview)
        rv.addWidget(self.template_builder)
        # Backward compat alias
        self.txt_template = self.template_builder.txt_template
        self.lbl_template_preview = self.template_builder.lbl_preview

        rv.addStretch()

        btn_row = QHBoxLayout()
        btn_apply_cat = QPushButton("Apply Changes"); btn_apply_cat.clicked.connect(self._apply_edit)
        btn_row.addWidget(btn_apply_cat); btn_row.addStretch()
        btn_save = QPushButton("Save & Close"); btn_save.setObjectName("btn_save")
        btn_save.clicked.connect(self._save_close)
        btn_row.addWidget(btn_save)
        rv.addLayout(btn_row)
        root.addWidget(right, 1)

    def _populate_list(self):
        self.lst_cats.clear()
        for c in self.cats:
            item = QListWidgetItem(c['name'])
            item.setForeground(QColor(c.get('color', '#cdd6f4')))
            self.lst_cats.addItem(item)

    def _on_cat_select(self, row):
        if row < 0 or row >= len(self.cats): return
        c = self.cats[row]
        self.txt_name.blockSignals(True)
        self.txt_name.setText(c['name'])
        self.txt_name.blockSignals(False)
        self.txt_color.blockSignals(True)
        self.txt_color.setText(c.get('color', '#6b7280'))
        self.txt_color.blockSignals(False)
        self.txt_exts.blockSignals(True)
        self.txt_exts.setPlainText(', '.join(c.get('extensions', [])))
        self.txt_exts.blockSignals(False)
        self.txt_kw.blockSignals(True)
        self.txt_kw.setText(', '.join(c.get('keywords', [])))
        self.txt_kw.blockSignals(False)
        self.txt_dst.blockSignals(True)
        self.txt_dst.setText(c.get('custom_dst', ''))
        self.txt_dst.blockSignals(False)
        # Show default path hint
        from unifile.main_window import UniFile
        default_hint = UniFile._default_pc_dst_static(c['name'])
        self.lbl_dst_default.setText(f"Default: {default_hint}" if not c.get('custom_dst') else "")
        self.txt_template.blockSignals(True)
        self.txt_template.setText(c.get('rename_template', ''))
        self.txt_template.blockSignals(False)
        self._update_template_preview()
        self._preview_color()
        self._dirty = False

    def _browse_dst(self):
        start = self.txt_dst.text().strip() or os.path.expanduser('~')
        d = QFileDialog.getExistingDirectory(self, "Output Directory", start)
        if d:
            self.txt_dst.setText(d)
            self.lbl_dst_default.setText("")

    def _preview_color(self):
        col = self.txt_color.text().strip()
        if re.match(r'^#[0-9a-fA-F]{6}$', col):
            self.lbl_color_swatch.setStyleSheet(f"color:{col};font-size:16px")

    def _update_template_preview(self):
        """Show a live preview of the rename template with sample data."""
        tmpl = self.txt_template.text().strip()
        if not tmpl:
            self.lbl_template_preview.setText("No rename — original filename kept")
            return
        # Generate a sample preview with placeholder metadata
        sample_meta = {
            '_type': 'image', 'date_taken': '2024:06:15 14:30:00',
            'camera_make': 'Canon', 'camera_model': 'EOS R5',
            'artist': 'The Beatles', 'album': 'Abbey Road', 'title': 'Come Together',
            'track': '1', 'genre': 'Rock', 'width': 4096, 'height': 2160,
            'author': 'John Doe', 'pages': 42, 'duration': 253.4, 'bitrate': 320,
        }
        try:
            result = RenameTemplateEngine.preview(tmpl, '/sample/my_photo.jpg',
                                                   sample_meta, 'Images', counter=1)
            self.lbl_template_preview.setText(f"Preview: {result}")
            self.lbl_template_preview.setStyleSheet(f"color:{get_active_theme()['green']};font-size:10px;font-style:italic;padding-left:4px")
        except Exception:
            self.lbl_template_preview.setText("Preview: (invalid template)")
            self.lbl_template_preview.setStyleSheet("color:#ef4444;font-size:10px;font-style:italic;padding-left:4px")  # semantic: error

    def _apply_edit(self):
        row = self.lst_cats.currentRow()
        if row < 0: return
        name  = self.txt_name.text().strip()
        color = self.txt_color.text().strip() or '#6b7280'
        exts  = [e.strip().lower().lstrip('.') for e in
                 re.split(r'[,\s]+', self.txt_exts.toPlainText()) if e.strip()]
        kws   = [k.strip() for k in self.txt_kw.text().split(',') if k.strip()]
        tmpl  = self.txt_template.text().strip()
        cdst  = self.txt_dst.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Category name cannot be empty.")
            return
        cat_data = {'name': name, 'color': color, 'extensions': exts,
                    'keywords': kws, 'rename_template': tmpl}
        if cdst:
            cat_data['custom_dst'] = cdst
        self.cats[row] = cat_data
        self._populate_list()
        self.lst_cats.setCurrentRow(row)
        self._dirty = False

    def _add_cat(self):
        self.cats.append({'name': 'New Category', 'color': '#6b7280',
                          'extensions': [], 'keywords': [], 'rename_template': ''})
        self._populate_list()
        self.lst_cats.setCurrentRow(len(self.cats) - 1)
        self.txt_name.setFocus(); self.txt_name.selectAll()

    def _del_cat(self):
        row = self.lst_cats.currentRow()
        if row < 0: return
        name = self.cats[row]['name']
        r = QMessageBox.question(self, "Delete Category",
            f"Delete \"{name}\"? Files assigned to it will be moved to Other.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.cats.pop(row)
            self._populate_list()
            self.lst_cats.setCurrentRow(max(0, row - 1))

    def _reset_defaults(self):
        r = QMessageBox.question(self, "Reset to Defaults",
            "This will replace all custom categories with the defaults. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.cats = [dict(c) for c in _DEFAULT_PC_CATEGORIES]
            self._populate_list()
            if self.lst_cats.count(): self.lst_cats.setCurrentRow(0)

    def _import_config(self):
        """Import categories from a classifier-format .conf file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Category Config",
            filter="Config Files (*.conf *.txt);;All Files (*)")
        if not path:
            return
        try:
            imported = import_classifier_config(path)
            if imported:
                self.cats = merge_categories(self.cats, imported)
                self._populate_list()
                self._dirty = True
                if self.lst_cats.count():
                    self.lst_cats.setCurrentRow(0)
        except Exception as e:
            QMessageBox.warning(self, "Import Error", f"Failed to import: {e}")

    def _export_config(self):
        """Export categories to a classifier-format .conf file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Category Config",
            "unifile_categories.conf",
            filter="Config Files (*.conf);;All Files (*)")
        if not path:
            return
        try:
            export_classifier_config(self.cats, path)
        except Exception as e:
            QMessageBox.warning(self, "Export Error", f"Failed to export: {e}")

    def _save_close(self):
        if self._dirty:
            self._apply_edit()
        _save_pc_categories(self.cats)
        self.accept()


class _FileBrowserDialog(QDialog):
    """File browser dialog that shows all files inside a source folder.
    User picks a file; its beautified stem is used as the new folder name."""

    # File types shown with priority highlighting
    _PROJECT_EXTS  = {'.aep', '.aet', '.prproj', '.mogrt', '.psd', '.psb',
                      '.ai', '.eps', '.indd', '.idml', '.fla', '.xd', '.fig'}
    _IGNORED_EXTS  = {'.ds_store', '.db', '.ini', '.lnk', '.url', '.tmp',
                      '.log', '.bak', '.thumbs'}

    def __init__(self, folder_path: str, current_name: str, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.chosen_name = None   # beautified stem the caller reads
        self.chosen_file = None   # raw filename for the detail log
        self.setWindowTitle(f"Pick File to Rename From  —  {os.path.basename(folder_path)}")
        self.setMinimumSize(640, 500)
        _t = get_active_theme()
        self.setStyleSheet(f"""
            QDialog {{ background:{_t['bg']}; }}
            QLabel  {{ color:{_t['muted']}; font-size:11px; }}
            QLineEdit {{
                background:{_t['input_bg']}; color:{_t['fg_bright']}; border:1px solid {_t['sidebar_btn_hover_border']};
                border-radius:4px; padding:5px 8px; font-size:12px;
            }}
            QTreeWidget {{
                background:{_t['header_bg']}; color:{_t['fg_bright']}; border:1px solid {_t['border']};
                border-radius:4px; font-size:11px; font-family: Consolas, monospace;
                alternate-background-color:{_t['bg_alt']};
            }}
            QTreeWidget::item {{ padding:3px 4px; }}
            QTreeWidget::item:selected {{ background:{_t['selection']}; color:{_t['fg_bright']}; }}
            QTreeWidget::item:hover {{ background:{_t['row_hover']}; }}
            QHeaderView::section {{
                background:{_t['header_bg']}; color:{_t['sidebar_btn_active_fg']}; border:none;
                border-bottom:1px solid {_t['sidebar_btn_hover_border']}; padding:4px 8px; font-size:11px;
            }}
            QPushButton {{
                background:{_t['selection']}; color:{_t['fg_bright']}; border:none;
                border-radius:4px; padding:6px 18px; font-size:12px;
            }}
            QPushButton:hover  {{ background:{_t['border_hover']}; }}
            QPushButton:pressed{{ background:{_t['accent_pressed']}; }}
            QPushButton#btn_ok {{ background:{_t['green_pressed']}; color:{_t['green']}; font-weight:bold; }}
            QPushButton#btn_ok:hover {{ background:{_t['green_hover']}; }}
            QPushButton#btn_ok:disabled {{ background:{_t['green_pressed']}; color:{_t['disabled']}; }}
        """)
        self._build_ui(current_name)
        self._populate(folder_path)

    def _build_ui(self, current_name):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # Header info
        hdr = QLabel(f"Current name:  <b style='color:#f59e0b'>{current_name}</b>  "
                     f"<span style='color:#3d5a73'>  ·  double-click or select + OK to apply</span>")
        hdr.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(hdr)

        # Search bar
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍  Filter files…")
        self.txt_search.textChanged.connect(self._filter)
        layout.addWidget(self.txt_search)

        # File tree  (folder icon | filename | ext | cleaned name preview)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["File", "Type", "→ Cleaned Name Preview"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed);  self.tree.setColumnWidth(1, 72)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self._accept_item)
        self.tree.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.tree, 1)

        # Preview of resulting folder name
        prev_row = QHBoxLayout()
        prev_row.addWidget(QLabel("Result:"))
        self.lbl_preview = QLabel("—")
        self.lbl_preview.setStyleSheet(f"color:{_t['green']}; font-size:13px; font-weight:bold; padding-left:6px;")
        prev_row.addWidget(self.lbl_preview, 1)
        layout.addLayout(prev_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Apply Name")
        self.btn_ok.setObjectName("btn_ok")
        self.btn_ok.setEnabled(False)
        self.btn_ok.clicked.connect(self._accept_selected)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self.btn_ok)
        layout.addLayout(btn_row)

    def _populate(self, folder_path: str):
        from unifile.naming import _beautify_name
        self._beautify_name = _beautify_name
        self.tree.setSortingEnabled(False)
        self._all_items = []
        try:
            for root, dirs, files in os.walk(folder_path):
                # Skip hidden / system dirs
                dirs[:] = [d for d in dirs if not d.startswith('.') and
                           d.lower() not in {'__macosx', '$recycle.bin'}]
                rel_root = os.path.relpath(root, folder_path)
                depth = 0 if rel_root == '.' else rel_root.count(os.sep) + 1
                if depth > 3:
                    dirs.clear(); continue

                for fname in sorted(files):
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in self._IGNORED_EXTS:
                        continue
                    rel_path = os.path.join(rel_root, fname) if rel_root != '.' else fname
                    cleaned = self._clean_stem(fname)
                    if not cleaned:
                        continue

                    item = QTreeWidgetItem()
                    item.setText(0, rel_path)
                    item.setText(1, ext.lstrip('.').upper() or '—')
                    item.setText(2, cleaned)
                    item.setData(0, Qt.ItemDataRole.UserRole, (fname, cleaned))

                    # Colour by file type
                    if ext in self._PROJECT_EXTS:
                        item.setForeground(0, QColor("#4fc3f7"))
                        item.setForeground(1, QColor("#f59e0b"))
                        item.setForeground(2, QColor("#4ade80"))
                    else:
                        item.setForeground(0, QColor("#6b8fa8"))
                        item.setForeground(1, QColor("#3d5a73"))
                        item.setForeground(2, QColor("#4b7a5a"))

                    self.tree.addTopLevelItem(item)
                    self._all_items.append(item)
        except (PermissionError, OSError):
            pass

        self.tree.setSortingEnabled(True)
        # Sort project files first
        self.tree.sortItems(1, Qt.SortOrder.AscendingOrder)

    def _clean_stem(self, filename: str) -> str:
        """Return the beautified stem that would be used as the folder name."""
        stem = os.path.splitext(filename)[0]
        # Strip leading numbers/IDs
        stem = re.sub(r'^\d{4,}[\s\-_]*', '', stem)
        stem = re.sub(r'^[\d]+[\.\s\-_]+', '', stem)
        stem = stem.replace('-', ' ').replace('_', ' ').replace('.', ' ')
        stem = re.sub(r'\s+', ' ', stem).strip()
        if len(stem) < 2:
            return ''
        try:
            return self._beautify_name(stem)
        except Exception:
            return stem.title()

    def _filter(self, text: str):
        q = text.lower()
        for item in self._all_items:
            hidden = bool(q) and q not in item.text(0).lower() and q not in item.text(2).lower()
            item.setHidden(hidden)

    def _on_select(self):
        sel = self.tree.selectedItems()
        if sel:
            _, cleaned = sel[0].data(0, Qt.ItemDataRole.UserRole)
            self.lbl_preview.setText(cleaned)
            self.btn_ok.setEnabled(bool(cleaned))
        else:
            self.lbl_preview.setText("—")
            self.btn_ok.setEnabled(False)

    def _accept_item(self, item, _col):
        fname, cleaned = item.data(0, Qt.ItemDataRole.UserRole)
        if cleaned:
            self.chosen_name = cleaned
            self.chosen_file = fname
            self.accept()

    def _accept_selected(self):
        sel = self.tree.selectedItems()
        if sel:
            fname, cleaned = sel[0].data(0, Qt.ItemDataRole.UserRole)
            if cleaned:
                self.chosen_name = cleaned
                self.chosen_file = fname
                self.accept()


class RuleEditorDialog(QDialog):
    """UI for creating and managing classification rules."""

    _FIELDS = ['name', 'extension', 'size', 'modified_date', 'created_date',
               'path_contains', 'name_regex', 'camera_model', 'width', 'height',
               'duration', 'artist', 'album']
    _OPS = ['eq', 'neq', 'gt', 'lt', 'gte', 'lte', 'contains', 'not_contains',
            'matches', 'startswith', 'endswith']

    def __init__(self, categories, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Classification Rules")
        self.setMinimumSize(750, 500)
        self.setStyleSheet(get_active_stylesheet())
        self.categories = categories
        self.rules = RuleEngine.load_rules()

        lay = QHBoxLayout(self)

        # Left: rule list
        left = QVBoxLayout()
        self.lst_rules = QListWidget()
        self.lst_rules.currentRowChanged.connect(self._on_rule_selected)
        left.addWidget(self.lst_rules, 1)
        btn_row = QHBoxLayout()
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self._add_rule)
        btn_row.addWidget(btn_add)
        btn_del = QPushButton("Delete")
        btn_del.clicked.connect(self._delete_rule)
        btn_row.addWidget(btn_del)
        btn_clone = QPushButton("Clone")
        btn_clone.clicked.connect(self._clone_rule)
        btn_row.addWidget(btn_clone)
        left.addLayout(btn_row)
        lay.addLayout(left, 1)

        # Right: rule editor
        right = QVBoxLayout()
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Rule name...")
        right.addWidget(self.txt_name)

        self.chk_enabled = QCheckBox("Enabled")
        self.chk_enabled.setChecked(True)
        right.addWidget(self.chk_enabled)

        # Conditions
        lbl_cond = QLabel("Conditions:")
        _t = get_active_theme()
        lbl_cond.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold;")
        right.addWidget(lbl_cond)
        self.lst_conditions = QListWidget()
        self.lst_conditions.setMaximumHeight(120)
        right.addWidget(self.lst_conditions)
        cond_btns = QHBoxLayout()
        btn_add_cond = QPushButton("+ Condition")
        btn_add_cond.clicked.connect(self._add_condition)
        cond_btns.addWidget(btn_add_cond)
        btn_rm_cond = QPushButton("- Condition")
        btn_rm_cond.clicked.connect(self._remove_condition)
        cond_btns.addWidget(btn_rm_cond)
        right.addLayout(cond_btns)

        # Logic
        logic_row = QHBoxLayout()
        logic_row.addWidget(QLabel("Logic:"))
        self.cmb_logic = QComboBox()
        self.cmb_logic.addItems(["Match ALL", "Match ANY"])
        logic_row.addWidget(self.cmb_logic)
        logic_row.addStretch()
        right.addLayout(logic_row)

        # Action
        act_row = QHBoxLayout()
        act_row.addWidget(QLabel("Category:"))
        self.cmb_category = QComboBox()
        for c in categories:
            self.cmb_category.addItem(c.get('name', ''))
        act_row.addWidget(self.cmb_category)
        right.addLayout(act_row)

        rename_row = QHBoxLayout()
        rename_row.addWidget(QLabel("Rename:"))
        self.txt_rename = QLineEdit()
        self.txt_rename.setPlaceholderText("Optional rename template...")
        rename_row.addWidget(self.txt_rename)
        right.addLayout(rename_row)

        # Save/Close
        btn_save_row = QHBoxLayout()
        btn_save = QPushButton("Save Rule")
        btn_save.setStyleSheet(f"QPushButton {{ background: {_t['green_pressed']}; color: {_t['green']}; border: 1px solid {_t['sidebar_profile_border']}; border-radius: 4px; padding: 6px 12px; }} QPushButton:hover {{ background: {_t['green_hover']}; }}")
        btn_save.clicked.connect(self._save_current)
        btn_save_row.addWidget(btn_save)
        btn_save_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self._close_and_save)
        btn_save_row.addWidget(btn_close)
        right.addLayout(btn_save_row)

        lay.addLayout(right, 2)
        self._refresh_list()
        self._current_conditions = []

    def _refresh_list(self):
        self.lst_rules.clear()
        for r in self.rules:
            enabled = "+" if r.get('enabled', True) else "-"
            self.lst_rules.addItem(f"[{enabled}] {r.get('name', 'Unnamed')}")

    def _on_rule_selected(self, row):
        if row < 0 or row >= len(self.rules):
            return
        rule = self.rules[row]
        self.txt_name.setText(rule.get('name', ''))
        self.chk_enabled.setChecked(rule.get('enabled', True))
        self.cmb_logic.setCurrentIndex(0 if rule.get('logic', 'all') == 'all' else 1)
        cat = rule.get('action_category', '')
        idx = self.cmb_category.findText(cat)
        if idx >= 0:
            self.cmb_category.setCurrentIndex(idx)
        self.txt_rename.setText(rule.get('action_rename', ''))
        self._current_conditions = list(rule.get('conditions', []))
        self._refresh_conditions()

    def _refresh_conditions(self):
        self.lst_conditions.clear()
        for c in self._current_conditions:
            self.lst_conditions.addItem(f"{c.get('field', '?')} {c.get('op', '?')} \"{c.get('value', '')}\"")

    def _add_condition(self):
        self._current_conditions.append({'field': 'extension', 'op': 'eq', 'value': '.txt'})
        self._refresh_conditions()

    def _remove_condition(self):
        row = self.lst_conditions.currentRow()
        if 0 <= row < len(self._current_conditions):
            self._current_conditions.pop(row)
            self._refresh_conditions()

    def _add_rule(self):
        self.rules.append({
            'name': 'New Rule', 'enabled': True, 'priority': len(self.rules),
            'conditions': [], 'logic': 'all',
            'action_category': self.categories[0]['name'] if self.categories else '',
            'action_rename': '', 'confidence': 90,
        })
        self._refresh_list()
        self.lst_rules.setCurrentRow(len(self.rules) - 1)

    def _delete_rule(self):
        row = self.lst_rules.currentRow()
        if 0 <= row < len(self.rules):
            self.rules.pop(row)
            self._refresh_list()

    def _clone_rule(self):
        row = self.lst_rules.currentRow()
        if 0 <= row < len(self.rules):
            import copy
            cloned = copy.deepcopy(self.rules[row])
            cloned['name'] += ' (copy)'
            self.rules.append(cloned)
            self._refresh_list()

    def _save_current(self):
        row = self.lst_rules.currentRow()
        if row < 0 or row >= len(self.rules):
            return
        self.rules[row]['name'] = self.txt_name.text()
        self.rules[row]['enabled'] = self.chk_enabled.isChecked()
        self.rules[row]['logic'] = 'all' if self.cmb_logic.currentIndex() == 0 else 'any'
        self.rules[row]['action_category'] = self.cmb_category.currentText()
        self.rules[row]['action_rename'] = self.txt_rename.text()
        self.rules[row]['conditions'] = list(self._current_conditions)
        self._refresh_list()

    def _close_and_save(self):
        RuleEngine.save_rules(self.rules)
        self.accept()
