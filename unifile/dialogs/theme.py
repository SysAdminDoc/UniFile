"""UniFile — Theme picker and protected paths dialogs."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from unifile.config import (
    THEMES,
    get_active_stylesheet,
    get_active_theme,
    load_protected_paths,
    load_theme_name,
    save_protected_paths,
    save_theme_name,
)
from unifile.dialogs.common import build_dialog_header


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
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            t,
            "Safety",
            "Protected Paths",
            "Keep high-risk folders, files, and names out of automated moves, renames, and deletes. "
            "Built-in rules cover common system locations, while custom rules let you protect your own."
        ))

        # Enable toggle
        self.chk_enabled = QCheckBox("Keep protected paths locked")
        self.chk_enabled.setStyleSheet(f"color: {t['fg']}; font-weight: 600;")
        self.chk_enabled.toggled.connect(self._update_summary)
        lay.addWidget(self.chk_enabled)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {t['muted']}; font-size: 11px; padding: 0 2px 2px 2px;")
        lay.addWidget(self.lbl_summary)

        # System paths (read-only)
        lbl_sys = QLabel("BUILT-IN RULES")
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
        lbl_cust = QLabel("CUSTOM RULES")
        lbl_cust.setStyleSheet(
            f"color: {t['muted']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1.5px; margin-top: 6px;")
        lay.addWidget(lbl_cust)

        self.list_custom = QListWidget()
        self.list_custom.setMinimumHeight(120)
        self.list_custom.itemSelectionChanged.connect(self._update_controls)
        lay.addWidget(self.list_custom)

        self.lbl_custom_hint = QLabel(
            "Add exact folders, specific files, or simple names such as '.env' or 'node_modules'."
        )
        self.lbl_custom_hint.setWordWrap(True)
        self.lbl_custom_hint.setStyleSheet(f"color: {t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_custom_hint)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_add_folder = QPushButton("Add Folder")
        self.btn_add_folder.clicked.connect(self._add_folder)
        btn_row.addWidget(self.btn_add_folder)

        self.btn_add_file = QPushButton("Add File")
        self.btn_add_file.clicked.connect(self._add_file)
        btn_row.addWidget(self.btn_add_file)

        self.btn_add_pattern = QPushButton("Protect by Name")
        self.btn_add_pattern.setToolTip(
            "Add a file/folder name pattern (e.g. '.env', 'node_modules')")
        self.btn_add_pattern.clicked.connect(self._add_pattern)
        btn_row.addWidget(self.btn_add_pattern)

        self.btn_remove = QPushButton("Remove Selection")
        self.btn_remove.setProperty("class", "toolbar")
        self.btn_remove.clicked.connect(self._remove_selected)
        btn_row.addWidget(self.btn_remove)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Dialog buttons
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Save Protection Rules")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        # Tab order: master toggle → custom list → actions → dialog buttons.
        # Qt's default is creation-order and matches visual order here, but
        # pinning it explicitly guards against future widget reorderings.
        self.setTabOrder(self.chk_enabled, self.list_custom)
        self.setTabOrder(self.list_custom, self.btn_add_folder)
        self.setTabOrder(self.btn_add_folder, self.btn_add_file)
        self.setTabOrder(self.btn_add_file, self.btn_add_pattern)
        self.setTabOrder(self.btn_add_pattern, self.btn_remove)
        self.setTabOrder(self.btn_remove, bb)

        # Initial focus on the master toggle — the user can spacebar-lock
        # protection without mousing before touching anything else.
        self.chk_enabled.setFocus()

    def _load(self):
        data = load_protected_paths()
        self.chk_enabled.setChecked(data['enabled'])
        self.list_system.clear()
        for p in data['system']:
            self.list_system.addItem(p)
        self.list_custom.clear()
        for p in data['custom']:
            self.list_custom.addItem(p)
        self._update_summary()
        self._update_controls()

    def _add_custom_item(self, value: str):
        value = value.strip()
        if not value:
            return
        existing = [self.list_custom.item(i).text() for i in range(self.list_custom.count())]
        if value in existing:
            self._update_summary(extra_message=f"'{value}' is already protected.")
            return
        self.list_custom.addItem(value)
        self._update_summary()
        self._update_controls()

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder to Protect")
        if d:
            self._add_custom_item(d)

    def _add_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select File to Protect")
        if f:
            self._add_custom_item(f)

    def _add_pattern(self):
        name, ok = QInputDialog.getText(
            self, "Add Protected Name",
            "File or folder name to protect (e.g. '.env', 'desktop.ini'):")
        if ok and name.strip():
            self._add_custom_item(name)

    def _remove_selected(self):
        for item in self.list_custom.selectedItems():
            self.list_custom.takeItem(self.list_custom.row(item))
        self._update_summary()
        self._update_controls()

    def _update_summary(self, *_args, extra_message: str = ""):
        system_count = self.list_system.count()
        custom_count = self.list_custom.count()
        status = "Protection is active." if self.chk_enabled.isChecked() else "Protection is paused."
        custom_state = (
            f"{custom_count} custom rule{'s' if custom_count != 1 else ''} ready."
            if custom_count else
            "No custom rules yet."
        )
        msg = f"{status} {system_count} built-in safeguards loaded. {custom_state}"
        if extra_message:
            msg = f"{msg} {extra_message}"
        self.lbl_summary.setText(msg)

    def _update_controls(self):
        has_selection = bool(self.list_custom.selectedItems())
        self.btn_remove.setEnabled(has_selection)
        self.lbl_custom_hint.setText(
            "Select one or more custom rules to remove them."
            if has_selection else
            "Add exact folders, specific files, or simple names such as '.env' or 'node_modules'."
        )

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
        self.setMinimumSize(560, 520)
        self._current = load_theme_name()
        self._selected = self._current
        self._card_status = {}
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(18, 18, 18, 18)

        t = get_active_theme()
        lay.addWidget(build_dialog_header(
            t,
            "Appearance",
            "Color Theme",
            "Preview the visual language used throughout the workspace, tables, dialogs, and tools. "
            "Pick the theme that keeps long sessions readable and calm."
        ))

        self.lbl_theme_summary = QLabel("")
        self.lbl_theme_summary.setWordWrap(True)
        self.lbl_theme_summary.setStyleSheet(f"color: {t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_theme_summary)

        # Theme cards
        self._cards = {}
        for name, palette in THEMES.items():
            card = self._make_card(name, palette)
            lay.addWidget(card)

        lay.addStretch()

        # Buttons
        bb = QHBoxLayout()
        bb.addStretch()
        self.btn_apply = QPushButton("Apply Theme")
        self.btn_apply.setProperty("class", "primary")
        self.btn_apply.clicked.connect(self._apply)
        bb.addWidget(self.btn_apply)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self._cancel)
        bb.addWidget(btn_cancel)
        lay.addLayout(bb)
        self._refresh_card_states()

    def _make_card(self, name: str, palette: dict) -> QFrame:
        card = QFrame()
        card.setFixedHeight(74)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setProperty('theme_name', name)
        self._style_card(card, name, palette, selected=(name == self._selected))

        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(14, 10, 14, 10)
        card_lay.setSpacing(12)

        # Color swatches
        swatch_w = QWidget()
        swatch_lay = QHBoxLayout(swatch_w)
        swatch_lay.setContentsMargins(0, 0, 0, 0)
        swatch_lay.setSpacing(5)
        for color_key in ('bg', 'btn_bg', 'accent', 'green', 'border'):
            sw = QFrame()
            sw.setFixedSize(20, 20)
            sw.setStyleSheet(
                f"background: {palette[color_key]}; border-radius: 4px; "
                f"border: 1px solid {palette['border']};")
            swatch_lay.addWidget(sw)
        card_lay.addWidget(swatch_w)

        info = QVBoxLayout()
        info.setSpacing(2)
        lbl = QLabel(name)
        lbl.setStyleSheet(
            f"color: {palette['fg']}; font-size: 13px; font-weight: 600; "
            f"background: transparent;")
        info.addWidget(lbl)

        lbl_sub = QLabel(self._theme_subtitle(name))
        lbl_sub.setStyleSheet(
            f"color: {palette['muted']}; font-size: 11px; background: transparent;"
        )
        info.addWidget(lbl_sub)
        card_lay.addLayout(info, 1)
        card_lay.addStretch()

        status = QLabel("")
        status.setStyleSheet(
            f"color: {palette['accent']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; background: transparent;"
        )
        card_lay.addWidget(status)
        self._card_status[name] = status

        card.mousePressEvent = lambda e, n=name: self._select(n)
        self._cards[name] = card
        return card

    def _style_card(self, card: QFrame, name: str, palette: dict, selected: bool):
        border = palette['accent'] if selected else palette['btn_bg']
        bg = palette['bg_alt'] if selected else palette['bg']
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 2px solid {border}; "
            f"border-radius: 12px; }}")

    def _theme_subtitle(self, name: str) -> str:
        descriptions = {
            "Steam Dark": "Balanced contrast with a calm accent for daily file work.",
            "Catppuccin Mocha": "Soft contrast and warmer tones for long evening sessions.",
            "OLED Black": "Maximum depth with minimal glow for very dark setups.",
            "GitHub Dark": "Neutral, practical contrast tuned for dense detail work.",
            "Nord": "Cool, composed contrast with a softer information rhythm.",
            "Dracula": "Bold accent energy with a richer editorial feel.",
        }
        return descriptions.get(name, "A focused dark theme for the UniFile workspace.")

    def _refresh_card_states(self):
        selected = self._selected
        for name, card in self._cards.items():
            palette = THEMES[name]
            self._style_card(card, name, palette, selected=(name == selected))
            label = self._card_status.get(name)
            if not label:
                continue
            if name == self._current and name == selected:
                label.setText("CURRENT")
            elif name == selected:
                label.setText("PREVIEW")
            else:
                label.setText("")

        if selected == self._current:
            self.lbl_theme_summary.setText(
                f"{selected} is already active across the main workspace and supporting dialogs."
            )
            self.btn_apply.setText("Keep Current Theme")
        else:
            self.lbl_theme_summary.setText(
                f"Previewing {selected}. Click Apply Theme to make it the new default."
            )
            self.btn_apply.setText("Apply Theme")

    def _select(self, name: str):
        self._selected = name
        self._refresh_card_states()
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
