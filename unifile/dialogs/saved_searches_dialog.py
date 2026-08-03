"""Saved Searches dialog — create, apply, and manage named Smart Views."""

from __future__ import annotations

import os
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.saved_searches import (
    SavedSearch,
    add_search,
    delete_search,
    export_cached_results,
    load_saved_searches,
    set_refresh_schedule,
    update_cache,
)


def resolve_saved_search_paths(parent, search: SavedSearch) -> list[str]:
    """Resolve a Smart View against the open tag library or current scan."""
    if parent:
        panel = getattr(parent, '_tag_panel', None)
        library = getattr(panel, 'library', None)
        if library is not None and library.is_open:
            entries = library.search_entries(search.query)
            if search.category:
                category = search.category.lower().lstrip('.')
                entries = [entry for entry in entries
                           if entry.suffix.lower() == category
                           or category in {tag.lower() for tag in entry.tag_names}]
            return [str(entry.path) for entry in entries]

        if hasattr(parent, '_items'):
            from unifile.search_parser import item_matches, parse_query
            spec = parse_query(search.query)
            paths = []
            for item in parent._items():
                if search.query and not item_matches(spec, item):
                    continue
                if search.category:
                    category = getattr(item, 'category', '').lower()
                    if search.category.lower() not in category:
                        continue
                path = (getattr(item, 'full_src', None)
                        or getattr(item, 'full_source_path', None)
                        or getattr(item, 'full_current_path', None))
                if path:
                    paths.append(str(path))
            return paths
    return []


class SavedSearchesDialog(QDialog):
    """Browse, apply, and manage saved searches / Smart Views."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Saved Searches")
        self.setMinimumSize(580, 500)
        self._selected: SavedSearch | None = None
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()
        self._populate()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            t,
            "Smart Views",
            "Saved Searches",
            "Save the current search filters as a named Smart View and replay them "
            "instantly from here or the Command Palette.",
        ))

        # ── Save current state row ────────────────────────────────────────────
        save_row = QHBoxLayout()
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Smart View name…")
        self.txt_name.returnPressed.connect(self._save_current)
        save_row.addWidget(self.txt_name)
        btn_save = QPushButton("Save Current Search")
        btn_save.setProperty("class", "apply")
        btn_save.clicked.connect(self._save_current)
        save_row.addWidget(btn_save)
        lay.addLayout(save_row)

        schedule_row = QHBoxLayout()
        self.chk_nightly = QCheckBox("Refresh nightly")
        self.chk_nightly.setToolTip("Refresh this Smart View when the app is open at the selected hour")
        self.chk_nightly.toggled.connect(self._schedule_changed)
        schedule_row.addWidget(self.chk_nightly)
        schedule_row.addWidget(QLabel("at"))
        self.spn_refresh_hour = QSpinBox()
        self.spn_refresh_hour.setRange(0, 23)
        self.spn_refresh_hour.setValue(2)
        self.spn_refresh_hour.setSuffix(":00")
        self.spn_refresh_hour.setToolTip("Local hour for the optional nightly refresh")
        self.spn_refresh_hour.valueChanged.connect(self._schedule_changed)
        schedule_row.addWidget(self.spn_refresh_hour)
        schedule_row.addStretch()
        lay.addLayout(schedule_row)

        # Hint
        self.lbl_hint = QLabel(
            "The search query and confidence threshold are captured from the main window."
        )
        self.lbl_hint.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        lay.addWidget(self.lbl_hint)

        # ── List ──────────────────────────────────────────────────────────────
        self.lst = QListWidget()
        self.lst.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.lst, 1)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_apply = QPushButton("Apply Search")
        self.btn_apply.setProperty("class", "primary")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_selected)
        btn_row.addWidget(self.btn_apply)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setProperty("class", "danger")
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.btn_delete)

        self.btn_refresh = QPushButton("Refresh Cache")
        self.btn_refresh.setProperty("class", "toolbar")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.clicked.connect(self._refresh_selected)
        btn_row.addWidget(self.btn_refresh)

        self.btn_export_json = QPushButton("Export JSON")
        self.btn_export_json.setProperty("class", "toolbar")
        self.btn_export_json.setEnabled(False)
        self.btn_export_json.clicked.connect(lambda: self._export_selected("json"))
        btn_row.addWidget(self.btn_export_json)

        self.btn_export_csv = QPushButton("Export CSV")
        self.btn_export_csv.setProperty("class", "toolbar")
        self.btn_export_csv.setEnabled(False)
        self.btn_export_csv.clicked.connect(lambda: self._export_selected("csv"))
        btn_row.addWidget(self.btn_export_csv)

        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _populate(self):
        self.lst.clear()
        for s in load_saved_searches():
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, s)
            label = s.name
            meta_parts = []
            if s.query:
                meta_parts.append(f'"{s.query}"')
            if s.category:
                meta_parts.append(s.category)
            if s.conf_min:
                meta_parts.append(f">={s.conf_min}%")
            meta = "  |  " + "  ·  ".join(meta_parts) if meta_parts else ""
            if s.result_count:
                meta += f"  ({s.result_count} results)"
            if s.cached_at:
                meta += f"  • updated {self._age_text(s.cached_at)}"
            if s.cache_changed:
                meta += "  • changed"
            if s.nightly_refresh:
                meta += f"  • nightly {s.refresh_hour:02d}:00"
            item.setText(f"{label}{meta}")
            self.lst.addItem(item)

    @staticmethod
    def _age_text(timestamp: float) -> str:
        seconds = max(0, int(time.time() - timestamp))
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"

    def _save_current(self):
        name = self.txt_name.text().strip()
        if not name:
            return
        parent = self.parent()
        query = ""
        category = ""
        conf_min = 0
        if parent:
            if hasattr(parent, 'txt_search'):
                query = parent.txt_search.text()
            if hasattr(parent, 'cmb_type_filter'):
                txt = parent.cmb_type_filter.currentText()
                if txt and txt not in ("All", "All Types"):
                    category = txt
            if hasattr(parent, 'sld_conf'):
                conf_min = parent.sld_conf.value()
        search = SavedSearch(
            name=name, query=query, category=category,
            conf_min=conf_min, created_at=time.time(),
            nightly_refresh=self.chk_nightly.isChecked(),
            refresh_hour=self.spn_refresh_hour.value(),
        )
        add_search(search)
        self._refresh_cache(search)
        self.txt_name.clear()
        self._populate()
        if parent and hasattr(parent, '_refresh_smart_views_sidebar'):
            parent._refresh_smart_views_sidebar()

    def _on_select(self):
        items = self.lst.selectedItems()
        has = bool(items)
        self.btn_apply.setEnabled(has)
        self.btn_delete.setEnabled(has)
        self.btn_refresh.setEnabled(has)
        self.btn_export_json.setEnabled(has)
        self.btn_export_csv.setEnabled(has)
        self._selected = items[0].data(Qt.ItemDataRole.UserRole) if has else None
        if self._selected:
            self.chk_nightly.blockSignals(True)
            self.chk_nightly.setChecked(self._selected.nightly_refresh)
            self.chk_nightly.blockSignals(False)
            self.spn_refresh_hour.setValue(self._selected.refresh_hour)

    def _apply_selected(self):
        if not self._selected:
            return
        s = self._selected
        parent = self.parent()
        if parent:
            if hasattr(parent, 'txt_search'):
                parent.txt_search.setText(s.query)
            if hasattr(parent, 'cmb_type_filter') and s.category:
                idx = parent.cmb_type_filter.findText(s.category)
                if idx >= 0:
                    parent.cmb_type_filter.setCurrentIndex(idx)
            if hasattr(parent, 'sld_conf') and s.conf_min:
                parent.sld_conf.setValue(s.conf_min)
            if hasattr(parent, '_apply_filter'):
                parent._apply_filter()
        self.accept()

    def _resolve_paths(self, search: SavedSearch) -> list[str]:
        """Resolve a Smart View against the open tag library or current scan."""
        return resolve_saved_search_paths(self.parent(), search)

    def _refresh_cache(self, search: SavedSearch) -> None:
        try:
            paths = self._resolve_paths(search)
            update_cache(search.name, paths)
            self._selected = next(
                (item for item in load_saved_searches() if item.name == search.name),
                self._selected)
            self.lbl_hint.setText(
                f"Cached {len(paths)} result{'s' if len(paths) != 1 else ''} for '{search.name}'."
            )
        except Exception as exc:
            self.lbl_hint.setText(f"Cache refresh failed: {exc}")

    def _refresh_selected(self):
        if not self._selected:
            return
        self._refresh_cache(self._selected)
        name = self._selected.name
        self._populate()
        for row in range(self.lst.count()):
            item = self.lst.item(row)
            if item and item.data(Qt.ItemDataRole.UserRole).name == name:
                self.lst.setCurrentItem(item)
                break
        parent = self.parent()
        if parent and hasattr(parent, '_refresh_smart_views_sidebar'):
            parent._refresh_smart_views_sidebar()

    def _export_selected(self, fmt: str):
        if not self._selected:
            return
        default_name = f"{self._selected.name}.{fmt}".replace(os.sep, "_")
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {fmt.upper()}", default_name,
            f"{fmt.upper()} Files (*.{fmt})")
        if not path:
            return
        try:
            export_cached_results(self._selected.name, path, format=fmt)
            self.lbl_hint.setText(f"Exported {self._selected.result_count} cached results.")
        except Exception as exc:
            self.lbl_hint.setText(f"Export failed: {exc}")

    def _delete_selected(self):
        if not self._selected:
            return
        delete_search(self._selected.name)
        self._selected = None
        self._populate()
        self.btn_apply.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.btn_export_json.setEnabled(False)
        self.btn_export_csv.setEnabled(False)
        parent = self.parent()
        if parent and hasattr(parent, '_refresh_smart_views_sidebar'):
            parent._refresh_smart_views_sidebar()

    def _schedule_changed(self):
        if self._selected:
            set_refresh_schedule(
                self._selected.name,
                self.chk_nightly.isChecked(),
                self.spn_refresh_hour.value(),
            )
