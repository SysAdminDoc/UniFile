"""UniFile — Miscellaneous tool dialogs (undo, events, schedule, plugins, etc.)."""
import os, re, sys, subprocess, math
from collections import Counter
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QCheckBox, QHeaderView, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QDialog,
    QListWidget, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from unifile.config import (
    get_active_theme, get_active_stylesheet,
    load_watch_history, clear_watch_history
)
from unifile.cache import _load_undo_stack
from unifile.engine import ScheduleManager, EventGrouper
from unifile.plugins import PluginManager, ProfileManager, _PLUGINS_DIR


class UndoBatchDialog(QDialog):
    """Shows undo batches and lets user select which to undo."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Undo Operations")
        self.setMinimumSize(500, 350)
        self.setStyleSheet(get_active_stylesheet())
        self.selected_indices = []

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Select batch(es) to undo (most recent first):"))

        self.lst = QListWidget()
        self.lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        stack = _load_undo_stack()
        for i, batch in enumerate(reversed(stack)):
            ts = batch.get('timestamp', '?')[:19].replace('T', ' ')
            count = batch.get('count', len(batch.get('ops', [])))
            self.lst.addItem(f"[{ts}]  {count} operations")
        lay.addWidget(self.lst, 1)

        btn_row = QHBoxLayout()
        btn_sel = QPushButton("Undo Selected")
        btn_sel.clicked.connect(self._undo_selected)
        btn_all = QPushButton("Undo All")
        btn_all.clicked.connect(self._undo_all)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_sel); btn_row.addWidget(btn_all)
        btn_row.addStretch(); btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

    def _undo_selected(self):
        stack = _load_undo_stack()
        total = len(stack)
        # Map reversed list indices back to stack indices
        self.selected_indices = [total - 1 - r.row() for r in self.lst.selectedIndexes()]
        if self.selected_indices:
            self.accept()

    def _undo_all(self):
        stack = _load_undo_stack()
        self.selected_indices = list(range(len(stack)))
        self.accept()


class BeforeAfterDialog(QDialog):
    """Side-by-side tree diff showing directory structure before and after."""

    def __init__(self, items, src_root, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Before / After Comparison")
        self.setMinimumSize(900, 550)
        self.setStyleSheet(get_active_stylesheet())

        lay = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Before tree
        left_w = QWidget()
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(4, 4, 4, 4)
        lbl_before = QLabel("BEFORE (Current)")
        lbl_before.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 12px;")  # semantic: before=red
        left_lay.addWidget(lbl_before)
        self.tree_before = QTreeWidget()
        self.tree_before.setHeaderLabels(["Path"])
        _t = get_active_theme()
        self.tree_before.setStyleSheet(f"QTreeWidget {{ background: {_t['header_bg']}; color: {_t['muted']}; }}")
        left_lay.addWidget(self.tree_before)
        splitter.addWidget(left_w)

        # After tree
        right_w = QWidget()
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(4, 4, 4, 4)
        lbl_after = QLabel("AFTER (Proposed)")
        lbl_after.setStyleSheet(f"color: {_t['green']}; font-weight: bold; font-size: 12px;")
        right_lay.addWidget(lbl_after)
        self.tree_after = QTreeWidget()
        self.tree_after.setHeaderLabels(["Path"])
        self.tree_after.setStyleSheet(f"QTreeWidget {{ background: {_t['header_bg']}; color: {_t['fg_bright']}; }}")
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

        lay = QHBoxLayout(self)

        # Left: event list
        left = QVBoxLayout()
        lbl_h = QLabel("Detected Events")
        _t = get_active_theme()
        lbl_h.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 13px;")
        left.addWidget(lbl_h)
        self.lst_events = QListWidget()
        self.lst_events.currentRowChanged.connect(self._on_event_selected)
        left.addWidget(self.lst_events, 1)
        lay.addLayout(left, 1)

        # Right: files in event
        right = QVBoxLayout()
        self.lbl_event_name = QLabel("")
        self.lbl_event_name.setStyleSheet(f"color: {_t['fg_bright']}; font-weight: bold; font-size: 13px;")
        right.addWidget(self.lbl_event_name)
        self.lst_files = QListWidget()
        self.lst_files.setStyleSheet(f"QListWidget {{ background: {_t['header_bg']}; color: {_t['muted']}; }}")
        right.addWidget(self.lst_files, 1)

        btn_row = QHBoxLayout()
        btn_subfolder = QPushButton("Apply as Subfolder")
        btn_subfolder.setStyleSheet(f"QPushButton {{ background: {_t['green_pressed']}; color: {_t['green']}; border: 1px solid {_t['sidebar_profile_border']}; border-radius: 4px; padding: 6px 12px; }} QPushButton:hover {{ background: {_t['green_hover']}; }}")
        btn_subfolder.clicked.connect(self._apply_subfolder)
        btn_row.addWidget(btn_subfolder)
        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        right.addLayout(btn_row)
        lay.addLayout(right, 2)

        self._populate()

    def _populate(self):
        for eid, items in self.event_groups:
            descs = [it.vision_description for it in items if it.vision_description]
            name = EventGrouper.suggest_event_name(descs)
            self.event_names[eid] = name
            self.lst_events.addItem(f"Event {eid}: {name} ({len(items)} files)")

    def _on_event_selected(self, row):
        if row < 0 or row >= len(self.event_groups):
            return
        eid, items = self.event_groups[row]
        self.lbl_event_name.setText(self.event_names.get(eid, f"Event {eid}"))
        self.lst_files.clear()
        for it in items:
            self.lst_files.addItem(it.name)

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
        self.setMinimumSize(500, 400)
        self.setStyleSheet(get_active_stylesheet())

        lay = QVBoxLayout(self)

        lbl_h = QLabel("Scheduled Scans (Windows Task Scheduler)")
        _t = get_active_theme()
        lbl_h.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 13px;")
        lay.addWidget(lbl_h)

        # Profile
        prof_row = QHBoxLayout()
        prof_row.addWidget(QLabel("Profile:"))
        self.cmb_profile = QComboBox()
        for p in ProfileManager.list_profiles():
            self.cmb_profile.addItem(p)
        prof_row.addWidget(self.cmb_profile, 1)
        lay.addLayout(prof_row)

        # Schedule type
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Schedule:"))
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Daily", "Weekly", "On Logon"])
        type_row.addWidget(self.cmb_type)
        type_row.addStretch()
        lay.addLayout(type_row)

        # Time
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Time:"))
        self.txt_time = QLineEdit("09:00")
        self.txt_time.setFixedWidth(80)
        time_row.addWidget(self.txt_time)
        time_row.addStretch()
        lay.addLayout(time_row)

        # Auto-apply
        self.chk_auto = QCheckBox("Auto-apply (move files without confirmation)")
        lay.addWidget(self.chk_auto)

        # Buttons
        btn_row = QHBoxLayout()
        btn_create = QPushButton("Create Schedule")
        btn_create.setStyleSheet(f"QPushButton {{ background: {_t['green_pressed']}; color: {_t['green']}; border: 1px solid {_t['sidebar_profile_border']}; border-radius: 4px; padding: 6px 12px; }} QPushButton:hover {{ background: {_t['green_hover']}; }}")
        btn_create.clicked.connect(self._create)
        btn_row.addWidget(btn_create)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Existing tasks
        lbl_ex = QLabel("Existing Scheduled Tasks:")
        lbl_ex.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding-top: 10px;")
        lay.addWidget(lbl_ex)
        self.lst_tasks = QListWidget()
        lay.addWidget(self.lst_tasks, 1)

        btn_del = QPushButton("Delete Selected")
        btn_del.clicked.connect(self._delete)
        lay.addWidget(btn_del)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close)

        self._refresh_tasks()

    def _refresh_tasks(self):
        self.lst_tasks.clear()
        for t in ScheduleManager.list_tasks():
            self.lst_tasks.addItem(f"{t['name']}  |  Next: {t.get('next_run', '?')}  |  {t.get('status', '?')}")

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
        self.setMinimumSize(700, 450)
        self.setStyleSheet(get_active_stylesheet())
        self.selected_indices = []

        lay = QHBoxLayout(self)

        # Left: timeline
        left = QVBoxLayout()
        lbl_h = QLabel("Operation History")
        _t = get_active_theme()
        lbl_h.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 13px;")
        left.addWidget(lbl_h)
        self.lst_timeline = QListWidget()
        self.lst_timeline.currentRowChanged.connect(self._on_batch_selected)
        left.addWidget(self.lst_timeline, 1)

        btn_row = QHBoxLayout()
        btn_undo = QPushButton("Undo Selected")
        btn_undo.setStyleSheet("QPushButton { background: #4a1a1a; color: #ef4444; border: 1px solid #5c2e2e; border-radius: 4px; padding: 6px 12px; } QPushButton:hover { background: #5c2e2e; }")  # semantic: danger
        btn_undo.clicked.connect(self._undo_selected)
        btn_row.addWidget(btn_undo)
        btn_undo_all = QPushButton("Undo All")
        btn_undo_all.clicked.connect(self._undo_all)
        btn_row.addWidget(btn_undo_all)
        btn_row.addStretch()
        left.addLayout(btn_row)
        lay.addLayout(left, 1)

        # Right: batch details
        right = QVBoxLayout()
        self.lbl_batch_info = QLabel("")
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

        self.stack = _load_undo_stack()
        self._populate()

    def _populate(self):
        for i, batch in enumerate(reversed(self.stack)):
            ts = batch.get('timestamp', '?')[:19].replace('T', ' ')
            count = batch.get('count', len(batch.get('ops', [])))
            status = batch.get('status', 'applied')
            dot = {'applied': '+', 'undone': '-', 'partial': '~'}.get(status, '?')
            self.lst_timeline.addItem(f"[{dot}] {ts}  ({count} ops)")

    def _on_batch_selected(self, row):
        self.tree_ops.clear()
        if row < 0:
            return
        actual_idx = len(self.stack) - 1 - row
        if actual_idx < 0 or actual_idx >= len(self.stack):
            return
        batch = self.stack[actual_idx]
        ops = batch.get('ops', [])
        self.lbl_batch_info.setText(f"Batch: {len(ops)} operations  |  {batch.get('timestamp', '?')[:19]}")
        cats = Counter()
        for op in ops:
            cats[op.get('category', '?')] += 1
            item = QTreeWidgetItem([op.get('dst', '?'), '->', op.get('src', '?')])
            self.tree_ops.addTopLevelItem(item)

    def _undo_selected(self):
        rows = [idx.row() for idx in self.lst_timeline.selectedIndexes()]
        total = len(self.stack)
        self.selected_indices = [total - 1 - r for r in rows]
        if self.selected_indices:
            self.accept()

    def _undo_all(self):
        self.selected_indices = list(range(len(self.stack)))
        self.accept()


class PluginManagerDialog(QDialog):
    """Manage UniFile plugins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Manager")
        self.setMinimumSize(550, 350)
        self.setStyleSheet(get_active_stylesheet())

        lay = QVBoxLayout(self)
        lbl_h = QLabel("Installed Plugins")
        _t = get_active_theme()
        lbl_h.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 13px;")
        lay.addWidget(lbl_h)

        self.lst_plugins = QListWidget()
        lay.addWidget(self.lst_plugins, 1)

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 6px;")
        lay.addWidget(self.lbl_info)

        btn_row = QHBoxLayout()
        btn_open = QPushButton("Open Plugins Folder")
        btn_open.clicked.connect(self._open_folder)
        btn_row.addWidget(btn_open)
        btn_reload = QPushButton("Reload Plugins")
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

    def _on_selected(self, row):
        if 0 <= row < len(self._discovered):
            p = self._discovered[row]
            self.lbl_info.setText(
                f"Name: {p['name']}\n"
                f"Hooks: {', '.join(p.get('hooks', []))}\n"
                f"Description: {p['description']}\n"
                f"Path: {p['path']}")

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
        lay.setSpacing(8)
        lay.setContentsMargins(16, 16, 16, 16)

        hdr = QLabel("Watch Mode History")
        hdr.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {_t['fg_bright']};")
        lay.addWidget(hdr)

        desc = QLabel("Recent auto-organize events triggered by Watch Mode.")
        desc.setStyleSheet(f"color: {_t['muted']}; font-size: 12px; margin-bottom: 4px;")
        lay.addWidget(desc)

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
        btn_clear = QPushButton("Clear History")
        btn_clear.setStyleSheet("QPushButton { color: #ef4444; }")
        btn_clear.clicked.connect(self._clear)
        bb.addWidget(btn_clear)
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

    def _clear(self):
        clear_watch_history()
        self.tbl.setRowCount(0)
