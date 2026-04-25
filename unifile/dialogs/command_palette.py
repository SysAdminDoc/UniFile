"""UniFile — Ctrl+K Command Palette.

A Spotlight-style command launcher that overlays the main window.
Trigger with Ctrl+K; dismiss with Escape or clicking outside.

Sections surfaced:
  - Built-in commands (Scan, Apply, Settings, dialogs, etc.)
  - Saved profiles
  - All known categories

Each result shows a section badge, command name, and optional hint.
Arrow keys navigate, Enter executes, Escape closes.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme


class _Command(NamedTuple):
    section: str        # "Command" | "Profile" | "Category"
    label: str
    hint: str
    callback: Callable


class CommandPalette(QDialog):
    """Floating, search-driven command palette.

    Pass a list of *static* commands at construction time. Dynamic commands
    (profiles, categories) are fetched lazily when the palette opens via
    `refresh_commands()`.

    Example::

        palette = CommandPalette(parent=main_window, commands=_build_commands(main_window))
        palette.open()
    """

    executed = pyqtSignal(str)   # emitted with the label of the command that ran

    def __init__(self, parent=None, commands: list[_Command] | None = None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setMinimumWidth(580)
        self.setMaximumWidth(700)

        self._all_commands: list[_Command] = commands or []
        self._theme = get_active_theme()
        self._build_ui()
        self._connect_signals()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        t = self._theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Card container
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
            f"border-radius: 14px; }}"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        # ── Search input ──────────────────────────────────────────────────────
        search_row = QWidget()
        search_row.setStyleSheet(
            f"QWidget {{ background: transparent; border-bottom: 1px solid {t['border']}; }}"
        )
        row_lay = QHBoxLayout(search_row)
        row_lay.setContentsMargins(14, 10, 14, 10)
        row_lay.setSpacing(10)

        icon_lbl = QLabel("⌘")
        icon_lbl.setStyleSheet(
            f"color: {t['accent']}; font-size: 18px; background: transparent; border: none;"
        )
        row_lay.addWidget(icon_lbl)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search commands, profiles, categories…")
        self.search.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; color: {t['fg_bright']}; "
            f"font-size: 16px; padding: 0; }}"
        )
        self.search.installEventFilter(self)
        row_lay.addWidget(self.search, 1)

        hint_lbl = QLabel("esc to close")
        hint_lbl.setStyleSheet(
            f"color: {t['muted']}; font-size: 11px; background: transparent; border: none;"
        )
        row_lay.addWidget(hint_lbl)

        card_lay.addWidget(search_row)

        # ── Results list ──────────────────────────────────────────────────────
        self.lst = QListWidget()
        self.lst.setMinimumHeight(60)
        self.lst.setMaximumHeight(460)
        self.lst.setFrameShape(QFrame.Shape.NoFrame)
        self.lst.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{ padding: 0px; }}"
            f"QListWidget::item:selected {{ background: {t['accent']}22; "
            f"  border-left: 3px solid {t['accent']}; }}"
            f"QListWidget::item:hover {{ background: {t['bg_alt']}; }}"
        )
        self.lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        card_lay.addWidget(self.lst)

        # ── Footer hint ───────────────────────────────────────────────────────
        footer = QLabel("↑↓ navigate   ↵ run   esc close")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(
            f"color: {t['muted']}; font-size: 10px; padding: 6px; "
            f"background: transparent; border-top: 1px solid {t['border']};"
        )
        card_lay.addWidget(footer)

        outer.addWidget(card)

    def _connect_signals(self) -> None:
        self.search.textChanged.connect(self._filter)
        self.lst.itemActivated.connect(self._execute_item)
        self.lst.itemDoubleClicked.connect(self._execute_item)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_commands(self, commands: list[_Command]) -> None:
        """Replace the full command list and refresh the displayed results."""
        self._all_commands = commands
        self._filter(self.search.text())

    def open(self) -> None:
        """Centre over the parent window and show."""
        self._center_on_parent()
        self._filter("")
        self.search.clear()
        self.search.setFocus()
        super().show()
        super().raise_()

    # ── Filtering ─────────────────────────────────────────────────────────────

    def _filter(self, query: str) -> None:
        q = query.strip().lower()
        self.lst.clear()
        matches = [c for c in self._all_commands
                   if not q or q in c.label.lower() or q in c.hint.lower()
                   or q in c.section.lower()]
        if not matches:
            item = QListWidgetItem("  No results")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor(self._theme["muted"]))
            self.lst.addItem(item)
            return

        # Group by section
        section_order = ["Command", "Profile", "Category"]
        section_order += sorted({c.section for c in matches
                                  if c.section not in section_order})
        sections_seen: set[str] = set()
        for section in section_order:
            group = [c for c in matches if c.section == section]
            if not group:
                continue
            if section not in sections_seen:
                sections_seen.add(section)
                hdr = QListWidgetItem(f"  {section.upper()}")
                hdr.setFlags(Qt.ItemFlag.NoItemFlags)
                hdr.setForeground(QColor(self._theme["accent"]))
                f = hdr.font()
                f.setPointSize(9)
                f.setBold(True)
                hdr.setFont(f)
                self.lst.addItem(hdr)
            for cmd in group:
                self.lst.addItem(self._make_item(cmd))

        # Auto-select the first selectable item
        for i in range(self.lst.count()):
            item = self.lst.item(i)
            if item and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                self.lst.setCurrentItem(item)
                break

        self._adjust_height()

    def _make_item(self, cmd: _Command) -> QListWidgetItem:
        t = self._theme
        widget = QWidget()
        lay = QHBoxLayout(widget)
        lay.setContentsMargins(16, 6, 16, 6)
        lay.setSpacing(10)

        lbl = QLabel(cmd.label)
        lbl.setStyleSheet(f"color: {t['fg_bright']}; font-size: 13px;")
        lay.addWidget(lbl, 1)

        if cmd.hint:
            hint = QLabel(cmd.hint)
            hint.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
            lay.addWidget(hint)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, cmd)
        self.lst.addItem(item)
        self.lst.setItemWidget(item, widget)
        return item

    # ── Execution ─────────────────────────────────────────────────────────────

    def _execute_item(self, item: QListWidgetItem) -> None:
        cmd: _Command | None = item.data(Qt.ItemDataRole.UserRole)
        if not cmd:
            return
        self.close()
        self.executed.emit(cmd.label)
        try:
            cmd.callback()
        except Exception:
            pass

    def _execute_selected(self) -> None:
        item = self.lst.currentItem()
        if item:
            self._execute_item(item)

    # ── Navigation ────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event: QEvent) -> bool:
        if obj is self.search and isinstance(event, QKeyEvent):
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._execute_selected()
                return True
            if key == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
        return super().eventFilter(obj, event)

    def _move_selection(self, delta: int) -> None:
        """Move selection up (delta=-1) or down (delta=1), skipping headers."""
        cur = self.lst.currentRow()
        count = self.lst.count()
        step = delta
        new = cur
        for _ in range(count):
            new = (new + step) % count
            item = self.lst.item(new)
            if item and (item.flags() & Qt.ItemFlag.ItemIsEnabled):
                self.lst.setCurrentRow(new)
                self.lst.scrollToItem(item)
                break

    # ── Geometry ─────────────────────────────────────────────────────────────

    def _center_on_parent(self) -> None:
        parent = self.parent()
        if parent:
            pg = parent.geometry()
            w = self.sizeHint().width() or 620
            x = pg.x() + (pg.width() - w) // 2
            y = pg.y() + max(40, pg.height() // 6)
            self.setGeometry(x, y, w, self.sizeHint().height() or 300)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.availableGeometry()
                w = 620
                self.setGeometry(
                    sg.x() + (sg.width() - w) // 2,
                    sg.y() + sg.height() // 6,
                    w, 300,
                )

    def _adjust_height(self) -> None:
        total = 0
        for i in range(self.lst.count()):
            item = self.lst.item(i)
            if item:
                sh = item.sizeHint().height()
                total += sh if sh > 0 else 36
        self.lst.setMaximumHeight(min(total + 8, 460))
        self.adjustSize()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


# ── Factory ───────────────────────────────────────────────────────────────────

def build_commands(main_window) -> list[_Command]:
    """Build the full command list from the main window's exposed slots.

    Categories and profiles are resolved at call time, so this should be
    called each time the palette opens to pick up any new profiles or
    category edits.
    """
    mw = main_window
    commands: list[_Command] = []

    # ── Built-in Commands ─────────────────────────────────────────────────────
    def _add(label: str, hint: str, fn_name: str | None = None, fn=None):
        if fn is None and fn_name:
            fn = getattr(mw, fn_name, None)
        if fn is None:
            return
        commands.append(_Command("Command", label, hint, fn))

    _add("Scan",              "Scan the selected source folder",      "_on_scan")
    _add("Apply",             "Apply pending moves / renames",        "_on_apply")
    _add("Open Settings",     "Open the Settings Hub",                "_open_settings_hub")
    _add("Open Tag Library",  "Manage and browse your tag database",  "_open_tag_library")
    _add("Open Media Lookup", "Fetch metadata from TMDb / OMDb",      "_open_media_lookup")
    _add("Open Duplicates",   "Find and remove duplicate files",      "_open_duplicates")
    _add("Open Cleanup",      "Remove empty folders & junk files",    "_open_cleanup")
    _add("Semantic Search",   "Natural-language file search",         "_open_semantic_search")
    _add("Rule Editor",       "Create if/then classification rules",  "_open_rule_editor")
    _add("Theme Picker",      "Change the color theme",               "_open_theme_picker")
    _add("View Undo History", "Step back through past operations",    "_open_undo_timeline")
    _add("Statistics",        "File-type breakdown charts",           "_open_stats")
    _add("Watch Mode",        "Auto-organize new files on arrival",   "_toggle_watch_mode")
    _add("Export Rules",      "Save custom rules to a JSON file",     "_export_rules")
    _add("Import Rules",      "Load rules from a JSON file",          "_import_rules")
    _add("Clear Cache",       "Reset classification cache + learner", "_clear_cache")
    _add("Virtual Library",   "Non-destructive library overlay",      "_open_virtual_library")
    _add("Shell Integration", "Install / remove Explorer context menu",
         fn=lambda: _open_shell_integration(mw))

    # ── Profiles ──────────────────────────────────────────────────────────────
    try:
        from unifile.plugins import ProfileManager
        for name in ProfileManager.list_profiles():
            profile_name = name  # capture

            def _load_profile(n=profile_name):
                profile = ProfileManager.load(n)
                if profile:
                    fn = getattr(mw, '_apply_profile_config',
                                 getattr(mw, '_apply_profile', None))
                    if fn:
                        fn(profile)
                        mw._log(f"Loaded profile: {n}")

            commands.append(_Command("Profile", name, "Load profile", _load_profile))
    except Exception:
        pass

    # ── Categories ────────────────────────────────────────────────────────────
    try:
        from unifile.categories import get_all_category_names
        for cat in get_all_category_names():
            cat_name = cat  # capture

            def _filter_by_cat(c=cat_name):
                # Focus the search bar and pre-fill with the category name
                try:
                    mw._filter_table(c)
                except Exception:
                    pass

            commands.append(_Command("Category", cat, "Filter results by category",
                                     _filter_by_cat))
    except Exception:
        pass

    return commands


def _open_shell_integration(mw) -> None:
    """Open the Shell Integration tab in the settings hub."""
    try:
        from unifile.dialogs.settings_hub import SettingsHubDialog
        dlg = SettingsHubDialog(mw)
        # Navigate to the System tab which hosts shell integration
        if hasattr(dlg, 'tabs'):
            for i in range(dlg.tabs.count()):
                if "System" in dlg.tabs.tabText(i):
                    dlg.tabs.setCurrentIndex(i)
                    break
        dlg.exec()
    except Exception:
        pass
