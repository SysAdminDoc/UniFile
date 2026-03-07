"""UniFile — Theme picker and protected paths dialogs."""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox,
    QFileDialog, QAbstractItemView,
    QDialog, QDialogButtonBox,
    QListWidget, QInputDialog, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from unifile.config import (
    THEMES, load_protected_paths, save_protected_paths,
    load_theme_name, save_theme_name, get_active_theme, get_active_stylesheet
)


class ProtectedPathsDialog(QDialog):
    """Manage system and custom protected paths that UniFile will never touch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Protected Paths")
        self.setMinimumSize(600, 520)
        theme = get_active_theme()
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui(theme)
        self._load()

    def _build_ui(self, t):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(16, 16, 16, 16)

        # Header
        hdr = QLabel("Protected Paths")
        hdr.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {t['fg_bright']};")
        lay.addWidget(hdr)
        desc = QLabel(
            "Files and folders listed below will never be moved, renamed, or deleted by UniFile.\n"
            "System paths are built-in defaults. Custom paths are yours to add/remove.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {t['muted']}; font-size: 12px; margin-bottom: 6px;")
        lay.addWidget(desc)

        # Enable toggle
        self.chk_enabled = QCheckBox("Protection enabled")
        self.chk_enabled.setStyleSheet(f"color: {t['fg']}; font-weight: 600;")
        lay.addWidget(self.chk_enabled)

        # System paths (read-only)
        lbl_sys = QLabel("SYSTEM (built-in)")
        lbl_sys.setStyleSheet(
            f"color: {t['muted']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1.5px; margin-top: 8px;")
        lay.addWidget(lbl_sys)

        self.list_system = QListWidget()
        self.list_system.setMaximumHeight(140)
        self.list_system.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_system.setStyleSheet(
            f"QListWidget {{ background: {t['input_bg']}; color: {t['disabled']}; "
            f"border: 1px solid {t['btn_bg']}; border-radius: 4px; }}"
            f"QListWidget::item {{ padding: 3px 8px; }}")
        lay.addWidget(self.list_system)

        # Custom paths
        lbl_cust = QLabel("CUSTOM")
        lbl_cust.setStyleSheet(
            f"color: {t['muted']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1.5px; margin-top: 6px;")
        lay.addWidget(lbl_cust)

        self.list_custom = QListWidget()
        self.list_custom.setMinimumHeight(120)
        lay.addWidget(self.list_custom)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_add_folder = QPushButton("Add Folder...")
        self.btn_add_folder.clicked.connect(self._add_folder)
        btn_row.addWidget(self.btn_add_folder)

        self.btn_add_file = QPushButton("Add File...")
        self.btn_add_file.clicked.connect(self._add_file)
        btn_row.addWidget(self.btn_add_file)

        self.btn_add_pattern = QPushButton("Add Name...")
        self.btn_add_pattern.setToolTip(
            "Add a file/folder name pattern (e.g. '.env', 'node_modules')")
        self.btn_add_pattern.clicked.connect(self._add_pattern)
        btn_row.addWidget(self.btn_add_pattern)

        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.setProperty("class", "toolbar")
        self.btn_remove.clicked.connect(self._remove_selected)
        btn_row.addWidget(self.btn_remove)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Dialog buttons
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _load(self):
        data = load_protected_paths()
        self.chk_enabled.setChecked(data['enabled'])
        self.list_system.clear()
        for p in data['system']:
            self.list_system.addItem(p)
        self.list_custom.clear()
        for p in data['custom']:
            self.list_custom.addItem(p)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder to Protect")
        if d:
            self.list_custom.addItem(d)

    def _add_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select File to Protect")
        if f:
            self.list_custom.addItem(f)

    def _add_pattern(self):
        name, ok = QInputDialog.getText(
            self, "Add Protected Name",
            "File or folder name to protect (e.g. '.env', 'desktop.ini'):")
        if ok and name.strip():
            self.list_custom.addItem(name.strip())

    def _remove_selected(self):
        for item in self.list_custom.selectedItems():
            self.list_custom.takeItem(self.list_custom.row(item))

    def _save(self):
        custom = [self.list_custom.item(i).text()
                  for i in range(self.list_custom.count())]
        save_protected_paths(custom, self.chk_enabled.isChecked())
        self.accept()


class ThemePickerDialog(QDialog):
    """Choose and preview color themes. Emits theme_changed signal on accept."""
    theme_changed = pyqtSignal(str)  # theme name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Color Theme")
        self.setMinimumSize(520, 480)
        self._current = load_theme_name()
        self._selected = self._current
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(16, 16, 16, 16)

        t = get_active_theme()
        hdr = QLabel("Color Theme")
        hdr.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {t['fg_bright']};")
        lay.addWidget(hdr)

        desc = QLabel("Select a theme. The preview updates instantly. Click Apply to save.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {t['muted']}; font-size: 12px; margin-bottom: 4px;")
        lay.addWidget(desc)

        # Theme cards
        self._cards = {}
        for name, palette in THEMES.items():
            card = self._make_card(name, palette)
            lay.addWidget(card)

        lay.addStretch()

        # Buttons
        bb = QHBoxLayout()
        bb.addStretch()
        self.btn_apply = QPushButton("  Apply  ")
        self.btn_apply.setProperty("class", "primary")
        self.btn_apply.clicked.connect(self._apply)
        bb.addWidget(self.btn_apply)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self._cancel)
        bb.addWidget(btn_cancel)
        lay.addLayout(bb)

    def _make_card(self, name: str, palette: dict) -> QFrame:
        card = QFrame()
        card.setFixedHeight(52)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setProperty('theme_name', name)
        self._style_card(card, name, palette, selected=(name == self._selected))

        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(12, 6, 12, 6)
        card_lay.setSpacing(10)

        # Color swatches
        swatch_w = QWidget()
        swatch_lay = QHBoxLayout(swatch_w)
        swatch_lay.setContentsMargins(0, 0, 0, 0)
        swatch_lay.setSpacing(4)
        for color_key in ('bg', 'btn_bg', 'accent', 'green', 'border'):
            sw = QFrame()
            sw.setFixedSize(18, 18)
            sw.setStyleSheet(
                f"background: {palette[color_key]}; border-radius: 3px; "
                f"border: 1px solid {palette['border']};")
            swatch_lay.addWidget(sw)
        card_lay.addWidget(swatch_w)

        # Name
        lbl = QLabel(name)
        lbl.setStyleSheet(
            f"color: {palette['fg']}; font-size: 13px; font-weight: 600; "
            f"background: transparent;")
        card_lay.addWidget(lbl)
        card_lay.addStretch()

        # Active indicator
        if name == self._current:
            active = QLabel("active")
            active.setStyleSheet(
                f"color: {palette['accent']}; font-size: 10px; font-weight: 700; "
                f"letter-spacing: 1px; background: transparent;")
            card_lay.addWidget(active)

        card.mousePressEvent = lambda e, n=name: self._select(n)
        self._cards[name] = card
        return card

    def _style_card(self, card: QFrame, name: str, palette: dict, selected: bool):
        border = palette['accent'] if selected else palette['btn_bg']
        bg = palette['bg_alt'] if selected else palette['bg']
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 2px solid {border}; "
            f"border-radius: 8px; }}")

    def _select(self, name: str):
        self._selected = name
        for n, card in self._cards.items():
            palette = THEMES[n]
            self._style_card(card, n, palette, selected=(n == name))
        # Live preview: apply theme to parent window immediately
        self.theme_changed.emit(name)

    def _apply(self):
        if self._selected != self._current:
            save_theme_name(self._selected)
        self.accept()

    def _cancel(self):
        # Revert to original theme if user changed it during preview
        if self._selected != self._current:
            self.theme_changed.emit(self._current)
        self.reject()
