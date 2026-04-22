"""UniFile — Miscellaneous tool dialogs (undo, events, schedule, plugins, etc.)."""
import os, re, sys, subprocess, math
from collections import Counter
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QCheckBox, QHeaderView, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QDialog, QFrame,
    QListWidget, QSplitter, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from unifile.config import (
    get_active_theme, get_active_stylesheet,
    load_watch_history, clear_watch_history
)
from unifile.dialogs.common import build_dialog_header
from unifile.cache import _load_undo_stack, _save_undo_stack
from unifile.engine import ScheduleManager, EventGrouper
from unifile.plugins import PluginManager, ProfileManager, _PLUGINS_DIR


class UndoBatchDialog(QDialog):
    """Shows undo batches and lets user select which to undo.

    Selecting a batch reveals a preview list of up to 10 operations (from -> to)
    so the user can see exactly what will be reversed before confirming.
    """

    _PREVIEW_LIMIT = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Undo Operations")
        self.setMinimumSize(780, 520)
        self.setStyleSheet(get_active_stylesheet())
        self.selected_indices = []
        self.stack = _load_undo_stack()
        _t = get_active_theme()

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(build_dialog_header(
            _t,
            "Recovery",
            "Undo Operations",
            "Select one or more recent batches, then review which files will be "
            "restored in the preview panel below. The newest batch appears first."
        ))

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_summary)

        # Split: batch list on the left, operation preview on the right.
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.lst = QListWidget()
        self.lst.setAlternatingRowColors(True)
        self.lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lst.itemSelectionChanged.connect(self._update_selection_state)
        self.lst.itemSelectionChanged.connect(self._update_preview)
        for batch in reversed(self.stack):
            ts = batch.get('timestamp', '?')[:19].replace('T', ' ')
            count = batch.get('count', len(batch.get('ops', [])))
            mode = batch.get('mode', '')
            status = batch.get('status', 'applied')
            tag = f" [{status}]" if status != 'applied' else ''
            mode_tag = f"  ·  {mode}" if mode else ''
            self.lst.addItem(f"{ts}  ·  {count} op{'s' if count != 1 else ''}{mode_tag}{tag}")
        splitter.addWidget(self.lst)

        # Preview panel — operation sample
        self.preview_tree = QTreeWidget()
        self.preview_tree.setHeaderLabels(["From → To"])
        self.preview_tree.setAlternatingRowColors(True)
        self.preview_tree.header().setStretchLastSection(True)
        splitter.addWidget(self.preview_tree)
        splitter.setSizes([320, 440])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        lay.addWidget(splitter, 1)

        btn_row = QHBoxLayout()
        self.btn_sel = QPushButton("Undo Selected Batches")
        self.btn_sel.setProperty("class", "primary")
        self.btn_sel.clicked.connect(self._undo_selected)
        self.btn_all = QPushButton("Undo Entire History")
        self.btn_all.clicked.connect(self._undo_all)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_sel)
        btn_row.addWidget(self.btn_all)
        btn_row.addStretch(); btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)
        self._update_selection_state()
        self._update_preview()

    def _update_selection_state(self):
        total = len(self.stack)
        selected = len(self.lst.selectedIndexes())
        if total:
            self.lbl_summary.setText(
                f"{total} undo batch{'es' if total != 1 else ''} available. "
                f"{selected} selected."
            )
        else:
            self.lbl_summary.setText("No undo history is available yet.")
        self.btn_sel.setEnabled(selected > 0)
        self.btn_all.setEnabled(total > 0)

    def _update_preview(self):
        """Show a sample of operations that would be reversed by the current selection."""
        self.preview_tree.clear()
        if not self.stack:
            placeholder = QTreeWidgetItem(["No operations to preview."])
            placeholder.setDisabled(True)
            self.preview_tree.addTopLevelItem(placeholder)
            return
        indices = [r.row() for r in self.lst.selectedIndexes()]
        total = len(self.stack)
        if not indices:
            placeholder = QTreeWidgetItem(["Select a batch above to preview the files it will restore."])
            placeholder.setDisabled(True)
            self.preview_tree.addTopLevelItem(placeholder)
            return
        _t = get_active_theme()
        shown_total = 0
        for row in indices:
            stack_idx = total - 1 - row
            if not (0 <= stack_idx < total):
                continue
            batch = self.stack[stack_idx]
            ops = batch.get('ops', [])
            ts = batch.get('timestamp', '?')[:19].replace('T', ' ')
            root = QTreeWidgetItem(self.preview_tree, [f"{ts}  ·  {len(ops)} op(s)"])
            root.setExpanded(True)
            # Take a representative slice: first N / 2 and last N / 2 — helps
            # the user see where a large batch started and ended.
            sample = ops[: self._PREVIEW_LIMIT // 2]
            if len(ops) > self._PREVIEW_LIMIT:
                sample += ops[-self._PREVIEW_LIMIT // 2:]
            for op in sample:
                src = op.get('src', '?')   # current location (post-move)
                dst = op.get('dst', '?')   # original location (where undo restores to)
                # Display as "restored-from -> restored-to" so the user reads
                # it in the direction the undo will go.
                label = f"{os.path.basename(src)} → {os.path.basename(dst) or dst}"
                node = QTreeWidgetItem(root, [label])
                node.setToolTip(0, f"FROM: {src}\n  TO: {dst}")
                shown_total += 1
            if len(ops) > self._PREVIEW_LIMIT:
                more = QTreeWidgetItem(
                    root,
                    [f"… and {len(ops) - self._PREVIEW_LIMIT} more operation(s)"]
                )
                more.setDisabled(True)

    def _undo_selected(self):
        total = len(self.stack)
        # Map reversed list indices back to stack indices
        self.selected_indices = [total - 1 - r.row() for r in self.lst.selectedIndexes()]
        if self.selected_indices:
            self.accept()

    def _undo_all(self):
        if not self.stack:
            return
        self.selected_indices = list(range(len(self.stack)))
        self.accept()


class BeforeAfterDialog(QDialog):
    """Side-by-side tree diff showing directory structure before and after."""

    def __init__(self, items, src_root, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Before / After Comparison")
        self.setMinimumSize(900, 550)
        self.setStyleSheet(get_active_stylesheet())
        _t = get_active_theme()

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(build_dialog_header(
            _t,
            "Preview",
            "Before and After",
            "Review the proposed folder structure before you apply changes. The left side shows the current source layout and the right side shows the planned destination layout."
        ))

        summary = QLabel(
            f"{len(items)} item{'s' if len(items) != 1 else ''} included from {src_root or 'the selected source'}."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Before tree
        left_w = QFrame()
        left_w.setProperty("class", "card")
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(14, 14, 14, 14)
        left_lay.setSpacing(8)
        lbl_before = QLabel("CURRENT STRUCTURE")
        lbl_before.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 12px;")
        left_lay.addWidget(lbl_before)
        lbl_before_hint = QLabel("What exists in the source right now.")
        lbl_before_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 10px;")
        left_lay.addWidget(lbl_before_hint)
        self.tree_before = QTreeWidget()
        self.tree_before.setHeaderLabels(["Path"])
        left_lay.addWidget(self.tree_before)
        splitter.addWidget(left_w)

        # After tree
        right_w = QFrame()
        right_w.setProperty("class", "card")
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(14, 14, 14, 14)
        right_lay.setSpacing(8)
        lbl_after = QLabel("PROPOSED STRUCTURE")
        lbl_after.setStyleSheet(f"color: {_t['green']}; font-weight: bold; font-size: 12px;")
        right_lay.addWidget(lbl_after)
        lbl_after_hint = QLabel("What UniFile plans to create if you apply this run.")
        lbl_after_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 10px;")
        right_lay.addWidget(lbl_after_hint)
        self.tree_after = QTreeWidget()
        self.tree_after.setHeaderLabels(["Path"])
        right_lay.addWidget(self.tree_after)
        splitter.addWidget(right_w)

        lay.addWidget(splitter, 1)

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(120)
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignRight)

        self._populate(items, src_root)

    def _populate(self, items, src_root):
        before_tree = {}
        after_tree = {}
        for it in items:
            # Before: original paths
            src = getattr(it, 'full_src', '') or getattr(it, 'full_source_path', '')
            if src:
                try:
                    rel = os.path.relpath(src, src_root)
                except ValueError:
                    rel = src
                parts = rel.replace('\\', '/').split('/')
                self._insert_tree(before_tree, parts)
            # After: destination paths
            dst = getattr(it, 'full_dst', '') or getattr(it, 'full_dest_path', '')
            name = getattr(it, 'display_name', '') or getattr(it, 'name', '')
            cat = getattr(it, 'category', '')
            if cat and name:
                after_parts = [cat, name]
                self._insert_tree(after_tree, after_parts)

        self._build_qt_tree(self.tree_before, before_tree, QColor("#8899aa"))
        self._build_qt_tree(self.tree_after, after_tree, QColor("#4ade80"))
        self.tree_before.expandAll()
        self.tree_after.expandAll()

    @staticmethod
    def _insert_tree(tree, parts):
        node = tree
        for p in parts:
            if p not in node:
                node[p] = {}
            node = node[p]

    def _build_qt_tree(self, widget, tree, color):
        def _add(parent, subtree):
            for name in sorted(subtree.keys()):
                item = QTreeWidgetItem([name])
                item.setForeground(0, color)
                if parent is None:
                    widget.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                if subtree[name]:
                    _add(item, subtree[name])
        _add(None, tree)


class EventGroupDialog(QDialog):
    """View detected events and apply as subfolders."""

    def __init__(self, event_groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Event Grouping")
        self.setMinimumSize(700, 450)
        self.setStyleSheet(get_active_stylesheet())
        self.event_groups = event_groups  # list of (event_id, [items])
        self.event_names = {}  # event_id -> name
        _t = get_active_theme()

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(18, 18, 18, 18)
        root.addWidget(build_dialog_header(
            _t,
            "Grouping",
            "AI Event Grouping",
            "Review suggested event clusters before turning them into subfolders. This keeps date- or scene-based grouping intentional rather than automatic noise."
        ))

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        root.addWidget(self.lbl_summary)

        lay = QHBoxLayout()
        lay.setSpacing(12)

        # Left: event list
        left_panel = QFrame()
        left_panel.setProperty("class", "card")
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(16, 16, 16, 16)
        left.setSpacing(8)
        lbl_h = QLabel("Detected events")
        lbl_h.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 13px;")
        left.addWidget(lbl_h)
        lbl_h_hint = QLabel("Select a suggested event to preview the files it would group together.")
        lbl_h_hint.setWordWrap(True)
        lbl_h_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        left.addWidget(lbl_h_hint)
        self.lst_events = QListWidget()
        self.lst_events.setAlternatingRowColors(True)
        self.lst_events.currentRowChanged.connect(self._on_event_selected)
        left.addWidget(self.lst_events, 1)
        lay.addWidget(left_panel, 1)

        # Right: files in event
        right_panel = QFrame()
        right_panel.setProperty("class", "card")
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(16, 16, 16, 16)
        right.setSpacing(8)
        self.lbl_event_name = QLabel("")
        self.lbl_event_name.setStyleSheet(f"color: {_t['fg_bright']}; font-weight: bold; font-size: 13px;")
        right.addWidget(self.lbl_event_name)
        self.lbl_event_hint = QLabel("Select an event to inspect the files it contains before applying a subfolder.")
        self.lbl_event_hint.setWordWrap(True)
        self.lbl_event_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        right.addWidget(self.lbl_event_hint)
        self.lst_files = QListWidget()
        self.lst_files.setAlternatingRowColors(True)
        right.addWidget(self.lst_files, 1)

        btn_row = QHBoxLayout()
        self.btn_subfolder = QPushButton("Apply as Subfolder")
        self.btn_subfolder.setProperty("class", "success")
        self.btn_subfolder.setEnabled(False)
        self.btn_subfolder.clicked.connect(self._apply_subfolder)
        btn_row.addWidget(self.btn_subfolder)
        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        right.addLayout(btn_row)
        lay.addWidget(right_panel, 2)

        root.addLayout(lay, 1)
        self._populate()

    def _populate(self):
        self.lst_events.clear()
        for eid, items in self.event_groups:
            descs = [it.vision_description for it in items if it.vision_description]
            name = EventGrouper.suggest_event_name(descs)
            self.event_names[eid] = name
            self.lst_events.addItem(f"Event {eid}: {name} ({len(items)} files)")
        count = len(self.event_groups)
        self.lbl_summary.setText(
            f"{count} suggested event group{'s' if count != 1 else ''} detected."
            if count else
            "No event groups were detected for the current selection."
        )
        if count:
            self.lst_events.setCurrentRow(0)
        else:
            self.lbl_event_name.setText("No event selected")
            self.lbl_event_hint.setText("No event groups are available to preview right now.")

    def _on_event_selected(self, row):
        if row < 0 or row >= len(self.event_groups):
            self.btn_subfolder.setEnabled(False)
            return
        eid, items = self.event_groups[row]
        self.lbl_event_name.setText(self.event_names.get(eid, f"Event {eid}"))
        self.lst_files.clear()
        for it in items:
            self.lst_files.addItem(it.name)
        self.lbl_event_hint.setText(
            f"{len(items)} file{'s' if len(items) != 1 else ''} would be placed into a shared subfolder for this event."
        )
        self.btn_subfolder.setEnabled(True)

    def _apply_subfolder(self):
        row = self.lst_events.currentRow()
        if row < 0 or row >= len(self.event_groups):
            return
        eid, items = self.event_groups[row]
        event_name = self.event_names.get(eid, f"Event_{eid}")
        # Sanitize
        event_name = re.sub(r'[<>:"/\\|?*]', '_', event_name).strip()
        for it in items:
            if hasattr(it, 'full_dst') and it.full_dst:
                base_dir = os.path.dirname(it.full_dst)
                it.full_dst = os.path.join(base_dir, event_name, os.path.basename(it.full_dst))
        self.lbl_summary.setText(
            f"Applied '{event_name}' as a subfolder to {len(items)} file{'s' if len(items) != 1 else ''}."
        )


class RelationshipGraphWidget(QWidget):
    """Network graph visualization of file relationships."""

    node_clicked = pyqtSignal(int)  # item index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        _t = get_active_theme()
        self.setStyleSheet(f"background: {_t['header_bg']};")
        self.setMouseTracking(True)
        self._nodes = []   # list of {'x': float, 'y': float, 'label': str, 'color': str, 'idx': int}
        self._edges = []   # list of {'a': int, 'b': int, 'color': str, 'type': str}
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag_start = None
        self._hover_node = -1

    def load_items(self, items):
        """Build nodes and edges from file items."""
        self._nodes.clear()
        self._edges.clear()
        if not items:
            self.update()
            return
        # Create nodes
        for i, it in enumerate(items[:200]):  # cap at 200 for performance
            cat_color = '#4ade80'
            self._nodes.append({
                'x': (hash(it.name) % 600) - 300 + i * 0.1,
                'y': (hash(it.full_src) % 400) - 200 + i * 0.1,
                'label': it.name[:20],
                'color': cat_color,
                'idx': i,
            })
        # Build edges
        for i, it_a in enumerate(items[:200]):
            for j, it_b in enumerate(items[:200]):
                if j <= i:
                    continue
                # Same category
                if it_a.category == it_b.category:
                    self._edges.append({'a': i, 'b': j, 'color': '#2e5c3e', 'type': 'category'})
                # Duplicate pair
                if it_a.dup_group > 0 and it_a.dup_group == it_b.dup_group:
                    self._edges.append({'a': i, 'b': j, 'color': '#ef4444', 'type': 'duplicate'})
                # Same date (within 1 hour)
                try:
                    ta = os.path.getmtime(it_a.full_src)
                    tb = os.path.getmtime(it_b.full_src)
                    if abs(ta - tb) < 3600:
                        self._edges.append({'a': i, 'b': j, 'color': '#38bdf8', 'type': 'time'})
                except Exception:
                    pass
        # Simple force-directed layout
        self._layout_nodes()
        self.update()

    def _layout_nodes(self):
        """Fruchterman-Reingold force-directed layout."""
        if len(self._nodes) < 2:
            return
        import random
        random.seed(42)
        for n in self._nodes:
            n['x'] = random.uniform(-300, 300)
            n['y'] = random.uniform(-200, 200)
        k = 50.0  # ideal edge length
        for _ in range(80):
            # Repulsion
            for i, n1 in enumerate(self._nodes):
                dx_total = dy_total = 0.0
                for j, n2 in enumerate(self._nodes):
                    if i == j:
                        continue
                    dx = n1['x'] - n2['x']
                    dy = n1['y'] - n2['y']
                    dist = max(0.1, math.sqrt(dx * dx + dy * dy))
                    force = k * k / dist
                    dx_total += (dx / dist) * force
                    dy_total += (dy / dist) * force
                n1['x'] += max(-5, min(5, dx_total * 0.01))
                n1['y'] += max(-5, min(5, dy_total * 0.01))
            # Attraction
            for edge in self._edges:
                n1 = self._nodes[edge['a']]
                n2 = self._nodes[edge['b']]
                dx = n2['x'] - n1['x']
                dy = n2['y'] - n1['y']
                dist = max(0.1, math.sqrt(dx * dx + dy * dy))
                force = (dist - k) * 0.01
                n1['x'] += dx / dist * force
                n1['y'] += dy / dist * force
                n2['x'] -= dx / dist * force
                n2['y'] -= dy / dist * force

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QBrush, QPen, QFont
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2 + self._pan_x, h / 2 + self._pan_y
        # Draw edges
        for edge in self._edges:
            n1 = self._nodes[edge['a']]
            n2 = self._nodes[edge['b']]
            p.setPen(QPen(QColor(edge['color']), 1))
            p.drawLine(int(cx + n1['x'] * self._zoom), int(cy + n1['y'] * self._zoom),
                      int(cx + n2['x'] * self._zoom), int(cy + n2['y'] * self._zoom))
        # Draw nodes
        for i, n in enumerate(self._nodes):
            x = int(cx + n['x'] * self._zoom)
            y = int(cy + n['y'] * self._zoom)
            radius = 8 if i == self._hover_node else 5
            p.setBrush(QBrush(QColor(n['color'])))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)
            if i == self._hover_node:
                p.setPen(QPen(QColor("#cdd6f4")))
                f = QFont(); f.setPixelSize(10); p.setFont(f)
                p.drawText(x + 10, y + 4, n['label'])
        p.end()

    def mouseMoveEvent(self, event):
        pos = event.position()
        w, h = self.width(), self.height()
        cx, cy = w / 2 + self._pan_x, h / 2 + self._pan_y
        closest = -1
        min_dist = 15
        for i, n in enumerate(self._nodes):
            x = cx + n['x'] * self._zoom
            y = cy + n['y'] * self._zoom
            d = math.sqrt((pos.x() - x)**2 + (pos.y() - y)**2)
            if d < min_dist:
                min_dist = d
                closest = i
        if closest != self._hover_node:
            self._hover_node = closest
            self.update()
        # Pan with drag
        if self._drag_start:
            dx = pos.x() - self._drag_start[0]
            dy = pos.y() - self._drag_start[1]
            self._pan_x += dx
            self._pan_y += dy
            self._drag_start = (pos.x(), pos.y())
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._hover_node >= 0:
                self.node_clicked.emit(self._nodes[self._hover_node]['idx'])
            else:
                self._drag_start = (event.position().x(), event.position().y())

    def mouseReleaseEvent(self, event):
        self._drag_start = None

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom = min(5.0, self._zoom * 1.15)
        else:
            self._zoom = max(0.2, self._zoom / 1.15)
        self.update()


class ScheduleDialog(QDialog):
    """Configuration dialog for scheduled scans."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scheduled Scans")
        self.setMinimumSize(560, 460)
        self.setStyleSheet(get_active_stylesheet())

        _t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(build_dialog_header(
            _t,
            "Automation",
            "Scheduled Scans",
            "Create recurring organizer runs through Windows Task Scheduler. Keep routine cleanup predictable, and only enable auto-apply when you trust the profile."
        ))

        self.lbl_task_summary = QLabel("")
        self.lbl_task_summary.setWordWrap(True)
        self.lbl_task_summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_task_summary)

        # Profile
        prof_row = QHBoxLayout()
        prof_row.addWidget(QLabel("Profile"))
        self.cmb_profile = QComboBox()
        for p in ProfileManager.list_profiles():
            self.cmb_profile.addItem(p)
        prof_row.addWidget(self.cmb_profile, 1)
        lay.addLayout(prof_row)

        # Schedule type
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Schedule"))
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Daily", "Weekly", "On Logon"])
        self.cmb_type.currentIndexChanged.connect(self._on_schedule_type_changed)
        type_row.addWidget(self.cmb_type)
        type_row.addStretch()
        lay.addLayout(type_row)

        # Time
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Time"))
        self.txt_time = QLineEdit("09:00")
        self.txt_time.setFixedWidth(80)
        self.txt_time.setPlaceholderText("09:00")
        time_row.addWidget(self.txt_time)
        time_row.addStretch()
        lay.addLayout(time_row)

        self.lbl_time_hint = QLabel("")
        self.lbl_time_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_time_hint)

        # Auto-apply
        self.chk_auto = QCheckBox("Auto-apply results without an approval step")
        lay.addWidget(self.chk_auto)

        # Buttons
        btn_row = QHBoxLayout()
        btn_create = QPushButton("Create Scheduled Scan")
        btn_create.setStyleSheet(f"QPushButton {{ background: {_t['green_pressed']}; color: {_t['green']}; border: 1px solid {_t['sidebar_profile_border']}; border-radius: 4px; padding: 6px 12px; }} QPushButton:hover {{ background: {_t['green_hover']}; }}")
        btn_create.clicked.connect(self._create)
        btn_row.addWidget(btn_create)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Existing tasks
        lbl_ex = QLabel("Existing Scheduled Tasks")
        lbl_ex.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding-top: 10px;")
        lay.addWidget(lbl_ex)
        self.lst_tasks = QListWidget()
        self.lst_tasks.itemSelectionChanged.connect(self._update_task_controls)
        lay.addWidget(self.lst_tasks, 1)

        self.btn_del = QPushButton("Delete Selected Task")
        self.btn_del.clicked.connect(self._delete)
        lay.addWidget(self.btn_del)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close)

        self._refresh_tasks()
        self._on_schedule_type_changed(self.cmb_type.currentIndex())

    def _refresh_tasks(self):
        self.lst_tasks.clear()
        tasks = ScheduleManager.list_tasks()
        for t in tasks:
            self.lst_tasks.addItem(f"{t['name']}  |  Next: {t.get('next_run', '?')}  |  {t.get('status', '?')}")
        if tasks:
            self.lbl_task_summary.setText(
                f"{len(tasks)} scheduled scan{'s' if len(tasks) != 1 else ''} configured."
            )
        else:
            self.lbl_task_summary.setText("No scheduled scans yet. Create one to automate a trusted profile.")
        self._update_task_controls()

    def _on_schedule_type_changed(self, idx):
        on_logon = idx == 2
        self.txt_time.setEnabled(not on_logon)
        if on_logon:
            self.lbl_time_hint.setText("On Logon runs when you sign in, so no clock time is needed.")
        else:
            self.lbl_time_hint.setText("Use 24-hour time, for example 09:00 or 18:30.")

    def _update_task_controls(self):
        self.btn_del.setEnabled(self.lst_tasks.currentRow() >= 0)

    def _create(self):
        profile = self.cmb_profile.currentText()
        if not profile:
            return
        stype = ['daily', 'weekly', 'on_logon'][self.cmb_type.currentIndex()]
        name = f"{profile}_{stype}"
        ScheduleManager.create_task(name, profile, stype,
                                     self.txt_time.text(), auto_apply=self.chk_auto.isChecked())
        self._refresh_tasks()

    def _delete(self):
        row = self.lst_tasks.currentRow()
        if row >= 0:
            text = self.lst_tasks.item(row).text()
            name = text.split('|')[0].strip()
            ScheduleManager.delete_task(name)
            self._refresh_tasks()


class UndoTimelineDialog(QDialog):
    """Visual timeline of past operations with before/after trees per batch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Undo Timeline")
        self.setMinimumSize(760, 500)
        self.setStyleSheet(get_active_stylesheet())
        self.selected_indices = []
        _t = get_active_theme()
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(18, 18, 18, 18)
        root.addWidget(build_dialog_header(
            _t,
            "History",
            "Undo Timeline",
            "Inspect past organize batches before rolling them back. The detail view shows each move so you can restore changes with confidence."
        ))

        self.lbl_timeline_summary = QLabel("")
        self.lbl_timeline_summary.setWordWrap(True)
        self.lbl_timeline_summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        root.addWidget(self.lbl_timeline_summary)

        lay = QHBoxLayout()
        lay.setSpacing(12)

        # Left: timeline
        left = QVBoxLayout()
        lbl_h = QLabel("Operation History")
        lbl_h.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 13px;")
        left.addWidget(lbl_h)
        self.lst_timeline = QListWidget()
        self.lst_timeline.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lst_timeline.currentRowChanged.connect(self._on_batch_selected)
        self.lst_timeline.itemSelectionChanged.connect(self._update_selection_state)
        left.addWidget(self.lst_timeline, 1)

        btn_row = QHBoxLayout()
        self.btn_undo = QPushButton("Undo Selected Batches")
        self.btn_undo.setStyleSheet("QPushButton { background: #4a1a1a; color: #ef4444; border: 1px solid #5c2e2e; border-radius: 4px; padding: 6px 12px; } QPushButton:hover { background: #5c2e2e; }")  # semantic: danger
        self.btn_undo.clicked.connect(self._undo_selected)
        btn_row.addWidget(self.btn_undo)
        self.btn_undo_all = QPushButton("Undo Entire History")
        self.btn_undo_all.clicked.connect(self._undo_all)
        btn_row.addWidget(self.btn_undo_all)
        btn_row.addStretch()
        left.addLayout(btn_row)
        lay.addLayout(left, 1)

        # Right: batch details
        right = QVBoxLayout()
        self.lbl_batch_info = QLabel("Select a batch to inspect its moves and affected categories.")
        self.lbl_batch_info.setStyleSheet(f"color: {_t['fg_bright']}; font-weight: bold; font-size: 12px;")
        right.addWidget(self.lbl_batch_info)
        self.tree_ops = QTreeWidget()
        self.tree_ops.setHeaderLabels(["Source", "->", "Destination"])
        self.tree_ops.setStyleSheet(f"QTreeWidget {{ background: {_t['header_bg']}; color: {_t['muted']}; }}")
        right.addWidget(self.tree_ops, 1)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        right.addWidget(btn_close)
        lay.addLayout(right, 2)
        root.addLayout(lay, 1)

        self.stack = _load_undo_stack()
        self._populate()

    def _populate(self):
        self.lst_timeline.clear()
        for batch in reversed(self.stack):
            ts = batch.get('timestamp', '?')[:19].replace('T', ' ')
            count = batch.get('count', len(batch.get('ops', [])))
            status = batch.get('status', 'applied')
            dot = {'applied': 'Applied', 'undone': 'Undone', 'partial': 'Partial'}.get(status, 'Unknown')
            mode = batch.get('mode', '')
            src_dir = batch.get('source_dir', '')
            meta = ''
            if mode:
                meta += f'  [{mode}]'
            if src_dir:
                import os as _os
                meta += f'  {_os.path.basename(src_dir) or src_dir}'
            self.lst_timeline.addItem(f"{ts}  -  {count} ops  -  {dot}{meta}")
        self.lbl_timeline_summary.setText(
            f"{len(self.stack)} batch{'es' if len(self.stack) != 1 else ''} available in history."
            if self.stack else
            "No operation history is available yet."
        )
        self._update_selection_state()

    def _on_batch_selected(self, row):
        self.tree_ops.clear()
        if row < 0:
            return
        actual_idx = len(self.stack) - 1 - row
        if actual_idx < 0 or actual_idx >= len(self.stack):
            return
        batch = self.stack[actual_idx]
        ops = batch.get('ops', [])
        timestamp = batch.get('timestamp', '?')[:19].replace('T', ' ')
        cats = Counter()
        for op in ops:
            cats[op.get('category', '?')] += 1
            item = QTreeWidgetItem([op.get('src', '?'), '->', op.get('dst', '?')])
            self.tree_ops.addTopLevelItem(item)
        category_summary = ", ".join(
            f"{name} ({count})" for name, count in cats.most_common(3) if name and name != '?'
        )
        self.lbl_batch_info.setText(
            f"{len(ops)} operation{'s' if len(ops) != 1 else ''} from {timestamp}"
            + (f"  |  Mode: {batch.get('mode', '?')}" if batch.get('mode') else "")
            + (f"  |  Src: {batch.get('source_dir', '')}" if batch.get('source_dir') else "")
            + (f"  -  Top categories: {category_summary}" if category_summary else "")
        )

    def _update_selection_state(self):
        selected = len(self.lst_timeline.selectedIndexes())
        has_history = bool(self.stack)
        self.btn_undo.setEnabled(selected > 0)
        self.btn_undo_all.setEnabled(has_history)

    def _undo_selected(self):
        rows = [idx.row() for idx in self.lst_timeline.selectedIndexes()]
        total = len(self.stack)
        indices = sorted([total - 1 - r for r in rows], reverse=True)
        if not indices:
            return
        self._perform_undo(indices)

    def _undo_all(self):
        indices = sorted(range(len(self.stack)), reverse=True)
        self._perform_undo(indices)

    def _perform_undo(self, indices):
        import shutil as _shutil
        import os as _os
        ok = err = skipped = 0
        for idx in indices:
            if idx >= len(self.stack):
                continue
            batch = self.stack[idx]
            if batch.get('status') == 'undone':
                skipped += 1
                continue
            for op in reversed(batch.get('ops', [])):
                src = op.get('src', '')
                dst = op.get('dst', '')
                try:
                    if _os.path.exists(src):
                        _os.makedirs(_os.path.dirname(dst), exist_ok=True)
                        _shutil.move(src, dst)
                        ok += 1
                    else:
                        skipped += 1
                except Exception:
                    err += 1
            self.stack[idx]['status'] = 'undone'
        _save_undo_stack(self.stack)
        self.selected_indices = indices
        msg = f"Undo complete: {ok} restored"
        if err:
            msg += f", {err} errors"
        if skipped:
            msg += f", {skipped} skipped"
        QMessageBox.information(self, "Undo", msg)
        self._populate()
        self.accept()


class PluginManagerDialog(QDialog):
    """Manage UniFile plugins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Manager")
        self.setMinimumSize(580, 420)
        self.setStyleSheet(get_active_stylesheet())

        lay = QVBoxLayout(self)
        _t = get_active_theme()
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(build_dialog_header(
            _t,
            "Extensions",
            "Plugin Manager",
            "Inspect discovered plugins, confirm which hooks they register, and jump straight to the plugin folder when you need to manage files directly."
        ))

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_summary)

        self.lst_plugins = QListWidget()
        self.lst_plugins.setAlternatingRowColors(True)
        lay.addWidget(self.lst_plugins, 1)

        self.lbl_info = QLabel("Select a plugin to inspect its hooks, description, and path.")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px; padding: 10px 12px; "
            f"background: {_t['bg_alt']}; border: 1px solid {_t['border']}; border-radius: 10px;"
        )
        lay.addWidget(self.lbl_info)

        btn_row = QHBoxLayout()
        btn_open = QPushButton("Open Plugins Folder")
        btn_open.setProperty("class", "toolbar")
        btn_open.clicked.connect(self._open_folder)
        btn_row.addWidget(btn_open)
        btn_reload = QPushButton("Reload Plugins")
        btn_reload.setProperty("class", "primary")
        btn_reload.clicked.connect(self._reload)
        btn_row.addWidget(btn_reload)
        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        self.lst_plugins.currentRowChanged.connect(self._on_selected)
        self._refresh()

    def _refresh(self):
        self.lst_plugins.clear()
        self._discovered = PluginManager.discover()
        for p in self._discovered:
            hooks = ', '.join(p.get('hooks', []))
            self.lst_plugins.addItem(f"{p['name']}  [{hooks}]")
        count = len(self._discovered)
        self.lbl_summary.setText(
            f"{count} plugin{'s' if count != 1 else ''} discovered."
            if count else
            "No plugins were discovered. Open the plugins folder to add one."
        )
        if not count:
            self.lbl_info.setText("No plugin metadata is available yet.")

    def _on_selected(self, row):
        if 0 <= row < len(self._discovered):
            p = self._discovered[row]
            self.lbl_info.setText(
                f"Name: {p['name']}\n"
                f"Hooks: {', '.join(p.get('hooks', []))}\n"
                f"Description: {p['description']}\n"
                f"Path: {p['path']}")
        else:
            self.lbl_info.setText("Select a plugin to inspect its hooks, description, and path.")

    def _open_folder(self):
        if sys.platform == 'win32':
            os.startfile(_PLUGINS_DIR)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', _PLUGINS_DIR])
        else:
            subprocess.Popen(['xdg-open', _PLUGINS_DIR])

    def _reload(self):
        PluginManager.load_all()
        self._refresh()


class WatchHistoryDialog(QDialog):
    """Shows a log of all Watch Mode auto-organize events."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Watch History")
        self.setMinimumSize(700, 500)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            _t,
            "Monitoring",
            "Watch Mode History",
            "Review recent background organize events triggered by Watch Mode. Use this log to confirm what ran, where it ran, and what happened."
        ))

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_summary)

        self.tbl = QTableWidget()
        self.tbl.setColumnCount(4)
        self.tbl.setHorizontalHeaderLabels(["Timestamp", "Folder", "Action", "Details"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setAlternatingRowColors(True)
        lay.addWidget(self.tbl, 1)

        bb = QHBoxLayout()
        self.btn_clear = QPushButton("Clear Watch History")
        self.btn_clear.setProperty("class", "danger")
        self.btn_clear.clicked.connect(self._clear)
        bb.addWidget(self.btn_clear)
        bb.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bb.addWidget(btn_close)
        lay.addLayout(bb)

        self._populate()

    def _populate(self):
        history = load_watch_history()
        self.tbl.setRowCount(0)
        for event in reversed(history):
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            ts = event.get('timestamp', '')
            if 'T' in ts:
                ts = ts.replace('T', ' ')[:19]
            self.tbl.setItem(r, 0, QTableWidgetItem(ts))
            self.tbl.setItem(r, 1, QTableWidgetItem(event.get('folder', '')))
            self.tbl.setItem(r, 2, QTableWidgetItem(event.get('action', '')))
            self.tbl.setItem(r, 3, QTableWidgetItem(event.get('details', '')))
        if history:
            latest = history[-1].get('timestamp', '').replace('T', ' ')[:19]
            self.lbl_summary.setText(
                f"{len(history)} event{'s' if len(history) != 1 else ''} recorded. Latest event: {latest or 'unknown'}."
            )
        else:
            self.lbl_summary.setText("No Watch Mode events have been recorded yet.")
        self.btn_clear.setEnabled(bool(history))

    def _clear(self):
        clear_watch_history()
        self.tbl.setRowCount(0)
        self.lbl_summary.setText("Watch Mode history cleared.")
        self.btn_clear.setEnabled(False)


class CsvRulesDialog(QDialog):
    """Edit user-defined CSV sort rules (regex-based folder classification)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sort Rules Editor")
        self.setMinimumSize(700, 520)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()
        self._load()

    def _build_ui(self):
        from unifile.csv_rules import get_rules_for_editor, rules_file_exists, get_rules_file
        self._get_rules_for_editor = get_rules_for_editor
        self._rules_file_exists = rules_file_exists
        self._get_rules_file = get_rules_file

        _t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            _t,
            "Automation",
            "Sort Rules Editor",
            "Define regex patterns that map folder names to categories. Rules are matched in order — the first match wins. "
            "Applied before the AI — zero tokens consumed."
        ))

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        lay.addWidget(self.lbl_summary)

        # Table
        self.tbl = QTableWidget(0, 2)
        self.tbl.setHorizontalHeaderLabels(["Category", "Pattern (regex)"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.itemSelectionChanged.connect(self._update_summary)
        lay.addWidget(self.tbl, 1)

        # Row controls
        row_btns = QHBoxLayout()
        self.btn_add = QPushButton("Add Row")
        self.btn_add.setProperty("class", "primary")
        self.btn_add.clicked.connect(self._add_row)
        self.btn_del = QPushButton("Remove Selected")
        self.btn_del.setProperty("class", "danger")
        self.btn_del.clicked.connect(self._remove_row)
        self.btn_open = QPushButton("Open rules.csv")
        self.btn_open.setProperty("class", "toolbar")
        self.btn_open.clicked.connect(self._open_file)
        row_btns.addWidget(self.btn_add)
        row_btns.addWidget(self.btn_del)
        row_btns.addStretch()
        row_btns.addWidget(self.btn_open)
        lay.addLayout(row_btns)

        # Test section
        test_row = QHBoxLayout()
        self.txt_test = QLineEdit()
        self.txt_test.setPlaceholderText("Test folder name...")
        self.btn_test = QPushButton("Test Rule")
        self.btn_test.setProperty("class", "toolbar")
        self.btn_test.clicked.connect(self._test)
        self.lbl_test_result = QLabel("")
        self.lbl_test_result.setStyleSheet(f"color: {_t['accent']}; font-size: 11px;")
        test_row.addWidget(QLabel("Test:"))
        test_row.addWidget(self.txt_test, 1)
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.lbl_test_result, 1)
        lay.addLayout(test_row)

        # Dialog buttons
        bb = QHBoxLayout()
        self.btn_save = QPushButton("Save Rules")
        self.btn_save.setProperty("class", "success")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bb.addStretch()
        bb.addWidget(btn_cancel)
        bb.addWidget(self.btn_save)
        lay.addLayout(bb)

    def _load(self):
        rows = self._get_rules_for_editor()
        self.tbl.setRowCount(0)
        for cat, pat in rows:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, QTableWidgetItem(cat))
            self.tbl.setItem(r, 1, QTableWidgetItem(pat))
        self.btn_open.setEnabled(self._rules_file_exists())
        self._update_summary()

    def _add_row(self):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        self.tbl.setItem(r, 0, QTableWidgetItem("Category"))
        self.tbl.setItem(r, 1, QTableWidgetItem(".*pattern.*"))
        self.tbl.editItem(self.tbl.item(r, 0))
        self._update_summary()

    def _remove_row(self):
        rows = sorted({i.row() for i in self.tbl.selectedItems()}, reverse=True)
        for r in rows:
            self.tbl.removeRow(r)
        self._update_summary()

    def _open_file(self):
        path = self._get_rules_file()
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.information(self, "Sort Rules", "Save rules first to create the file.")

    def _test(self):
        from unifile.csv_rules import test_rules
        name = self.txt_test.text().strip()
        if not name:
            self.lbl_test_result.setText("Enter a folder name to test")
            return
        rules = self._collect_rules()
        result = test_rules(name, rules)
        if result:
            self.lbl_test_result.setText(f"Matched: {result[0]}  (pattern: {result[1]})")
        else:
            self.lbl_test_result.setText("No match")

    def _collect_rules(self):
        rules = []
        for r in range(self.tbl.rowCount()):
            cat_item = self.tbl.item(r, 0)
            pat_item = self.tbl.item(r, 1)
            cat = cat_item.text().strip() if cat_item else ''
            pat = pat_item.text().strip() if pat_item else ''
            if cat and pat:
                rules.append((cat, pat))
        return rules

    def _save(self):
        from unifile.csv_rules import save_rules
        rules = self._collect_rules()
        try:
            save_rules(rules)
            self.btn_open.setEnabled(True)
            self._update_summary()
            QMessageBox.information(self, "Sort Rules", f"Saved {len(rules)} rule{'s' if len(rules) != 1 else ''}.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save rules:\n{e}")

    def _update_summary(self):
        count = self.tbl.rowCount()
        selected = len({i.row() for i in self.tbl.selectedItems()})
        self.lbl_summary.setText(
            f"{count} CSV rule{'s' if count != 1 else ''} in the editor. Rules are evaluated top to bottom."
            if count else
            "No CSV rules yet. Add a specific regex rule to catch obvious folder patterns before AI is needed."
        )
        self.btn_del.setEnabled(selected > 0)
