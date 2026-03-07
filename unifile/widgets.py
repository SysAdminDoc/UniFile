"""UniFile — Custom Qt widgets: charts, flow layout, thumbnails, map, preview panel."""
import os, re, json, math
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QTextEdit,
    QHeaderView, QFileDialog, QFrame, QScrollArea, QLayout, QLayoutItem,
    QDialog, QDialogButtonBox, QSpinBox, QListWidget, QListWidgetItem,
    QSplitter, QWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QRunnable, QThreadPool, QObject, QRect, QFileSystemWatcher
from PyQt6.QtGui import QColor, QPixmap, QImage, QIcon

import sys, subprocess

from unifile.config import _APP_DATA_DIR, DARK_STYLE, get_active_stylesheet, get_active_theme, append_watch_event
from unifile.bootstrap import HAS_PILLOW
from unifile.metadata import ArchivePeeker
try:
    from PIL import Image as _PILImage
except ImportError:
    pass

class CategoryBarChart(QWidget):
    """Horizontal stacked bar chart showing file count per category."""
    segment_clicked = pyqtSignal(str)
    category_drop = pyqtSignal(str, list)  # (category_name, row_indices)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []  # list of (name, count, color_hex)
        self._total = 0
        self.setFixedHeight(32)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(True)

    def set_data(self, segments: list):
        """Set segments: [(name, count, color_hex), ...]"""
        self.segments = segments
        self._total = max(1, sum(s[1] for s in segments))
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QBrush, QPen, QFont
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        x = 0
        for name, count, color in self.segments:
            seg_w = max(2, int(w * count / self._total))
            p.setBrush(QBrush(QColor(color)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(int(x), 0, seg_w, h, 3, 3)
            if seg_w > 40:
                p.setPen(QPen(QColor(get_active_theme()['header_bg'])))
                f = QFont(); f.setPixelSize(10); f.setBold(True); p.setFont(f)
                p.drawText(int(x) + 4, 0, seg_w - 8, h,
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           f"{name} ({count})")
            x += seg_w
        p.end()

    def mousePressEvent(self, event):
        if not self.segments:
            return
        x = event.position().x()
        w = self.width()
        cum = 0
        for name, count, color in self.segments:
            seg_w = max(2, int(w * count / self._total))
            if cum <= x <= cum + seg_w:
                self.segment_clicked.emit(name)
                return
            cum += seg_w

    def _segment_at(self, x):
        """Return the category name at pixel x, or None."""
        w = self.width()
        cum = 0
        for name, count, color in self.segments:
            seg_w = max(2, int(w * count / self._total))
            if cum <= x <= cum + seg_w:
                return name
            cum += seg_w
        return None

    def dragEnterEvent(self, event):
        # Accept QTableWidget drag (application/x-qabstractitemmodeldatalist) or text
        if event.mimeData().hasFormat('application/x-qabstractitemmodeldatalist') or event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        cat = self._segment_at(event.position().x())
        if not cat:
            return
        rows = []
        # Try text MIME first (custom drag source)
        if event.mimeData().hasText():
            try:
                rows = [int(r) for r in event.mimeData().text().split(',') if r.strip()]
            except ValueError:
                pass
        # Fallback: extract selected rows from source QTableWidget
        if not rows:
            src = event.source()
            if src and hasattr(src, 'selectionModel'):
                sel = src.selectionModel().selectedRows()
                rows = sorted(set(idx.row() for idx in sel))
        if rows:
            self.category_drop.emit(cat, rows)


# ══════════════════════════════════════════════════════════════════════════════
# THUMBNAIL GRID VIEW — FlowLayout + ThumbnailCard + ThumbnailLoader
# ══════════════════════════════════════════════════════════════════════════════

class FlowLayout(QLayout):
    """Wrapping flow layout that arranges widgets left-to-right, wrapping to next row."""

    def __init__(self, parent=None, margin=6, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only=False):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = effective.x(), effective.y(), 0
        for item in self._items:
            w = item.widget()
            if w is None:
                continue
            space_x = self._spacing
            item_w = item.sizeHint().width()
            item_h = item.sizeHint().height()
            next_x = x + item_w + space_x
            if next_x - space_x > effective.right() and line_h > 0:
                x = effective.x()
                y += line_h + self._spacing
                next_x = x + item_w + space_x
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(int(x), int(y), int(item_w), int(item_h)))
            x = next_x
            line_h = max(line_h, item_h)
        return y + line_h - rect.y() + m.bottom()



class _ThumbSignals(QObject):
    """Signals for ThumbnailLoader."""
    ready = pyqtSignal(str, QPixmap)  # file_path, pixmap


class ThumbnailLoader(QRunnable):
    """Background loader for image thumbnails."""

    def __init__(self, file_path: str, size: int = 150):
        super().__init__()
        self.file_path = file_path
        self.size = size
        self.signals = _ThumbSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            img = QImage(self.file_path)
            if img.isNull():
                return
            scaled = img.scaled(self.size, self.size,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            pm = QPixmap.fromImage(scaled)
            self.signals.ready.emit(self.file_path, pm)
        except Exception:
            pass


class ThumbnailCard(QWidget):
    """Single thumbnail card for grid view: 170x200, thumbnail + name + category badge."""
    clicked = pyqtSignal(int)  # item index

    _IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.ico', '.svg'}

    def __init__(self, index: int, name: str, category: str, cat_color: str, file_path: str, parent=None):
        super().__init__(parent)
        self._t = get_active_theme()
        _t = self._t
        self.index = index
        self.file_path = file_path
        self._selected = False
        self.setFixedSize(170, 200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        # Thumbnail label
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(162, 140)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumb.setStyleSheet(
            f"QLabel {{ background: {_t['header_bg']}; border-radius: 6px; border: 1px solid {_t['border']}; }}")
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self._IMAGE_EXTS:
            self.lbl_thumb.setText(ext.upper() if ext else "?")
            self.lbl_thumb.setStyleSheet(
                self.lbl_thumb.styleSheet() +
                f"QLabel {{ color: {_t['muted']}; font-size: 24px; font-weight: bold; }}")
        lay.addWidget(self.lbl_thumb)

        # Name
        lbl_name = QLabel(name[:25] + "..." if len(name) > 28 else name)
        lbl_name.setStyleSheet(f"color: {_t['fg_bright']}; font-size: 10px;")
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl_name)

        # Category badge
        lbl_cat = QLabel(f" {category} ")
        lbl_cat.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_cat.setStyleSheet(
            f"background: {cat_color}; color: {_t['header_bg']}; font-size: 9px;"
            f"font-weight: bold; border-radius: 3px; padding: 1px 4px;")
        lay.addWidget(lbl_cat)

        self._update_style()

    def set_pixmap(self, pm: QPixmap):
        self.lbl_thumb.setPixmap(pm.scaled(
            162, 140, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _update_style(self):
        _t = self._t
        border = f"2px solid {_t['sidebar_btn_active_fg']}" if self._selected else f"1px solid {_t['border']}"
        bg = _t['selection'] if self._selected else _t['bg_alt']
        self.setStyleSheet(
            f"ThumbnailCard {{ background: {bg}; border: {border}; border-radius: 8px; }}"
            f"ThumbnailCard:hover {{ background: {_t['selection']}; }}")

    def mousePressEvent(self, event):
        self._selected = not self._selected
        self._update_style()
        self.clicked.emit(self.index)


# ══════════════════════════════════════════════════════════════════════════════
# MAP VIEW — Leaflet-based geotagged photo map (optional PyQtWebEngine)
# ══════════════════════════════════════════════════════════════════════════════

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False



class PhotoMapWidget(QWidget):
    """Map view for geotagged photos using Leaflet via QWebEngineView."""

    _TILE_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    _TILE_ATTR = '&copy; <a href="https://carto.com/">CARTO</a>'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = get_active_theme()
        _t = self._t
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if HAS_WEBENGINE:
            self._web = QWebEngineView()
            self._web.setStyleSheet(f"background: {_t['header_bg']};")
            lay.addWidget(self._web)
        else:
            lbl = QLabel("Map view requires PyQtWebEngine.\npip install PyQt6-WebEngine")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color: {_t['muted']}; font-size: 13px; padding: 40px;")
            lay.addWidget(lbl)
            self._web = None

    def load_markers(self, items: list):
        """Load markers from file items that have GPS metadata.
        Each item should have .full_src and optionally ._photo_lat, ._photo_lon attributes."""
        if not self._web:
            return
        markers = []
        for it in items:
            lat = getattr(it, '_photo_lat', None)
            lon = getattr(it, '_photo_lon', None)
            if lat is not None and lon is not None:
                name = os.path.basename(getattr(it, 'full_src', ''))
                markers.append((lat, lon, name.replace("'", "\\'")))
        if not markers:
            _t = self._t
            self._web.setHtml(
                f"<html><body style='background:{_t['header_bg']};color:{_t['muted']};display:flex;"
                "align-items:center;justify-content:center;height:100vh;font-family:sans-serif;'>"
                "<p>No geotagged photos found</p></body></html>")
            return
        center_lat = sum(m[0] for m in markers) / len(markers)
        center_lon = sum(m[1] for m in markers) / len(markers)
        marker_js = "\n".join(
            f"L.marker([{lat},{lon}]).addTo(map).bindPopup('{name}');"
            for lat, lon, name in markers
        )
        html = f"""<!DOCTYPE html><html><head>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{{margin:0;padding:0;background:{self._t['header_bg']};}} #map{{width:100%;height:100vh;}}</style>
</head><body><div id="map"></div><script>
var map = L.map('map').setView([{center_lat},{center_lon}], 10);
L.tileLayer('{self._TILE_URL}', {{attribution: '{self._TILE_ATTR}', subdomains: 'abcd', maxZoom: 19}}).addTo(map);
{marker_js}
</script></body></html>"""
        self._web.setHtml(html)

    def has_gps_items(self, items: list) -> bool:
        """Check if any items have GPS coordinates."""
        return any(getattr(it, '_photo_lat', None) is not None for it in items)


# ══════════════════════════════════════════════════════════════════════════════
# WATCH FOLDER — Auto-organize with QFileSystemWatcher + system tray
# ══════════════════════════════════════════════════════════════════════════════

_WATCH_SETTINGS_FILE = os.path.join(_APP_DATA_DIR, 'watch_settings.json')


def _load_watch_settings() -> dict:
    defaults = {'enabled': False, 'folders': [], 'delay_seconds': 5,
                'auto_apply': False, 'minimize_to_tray': True}
    if os.path.isfile(_WATCH_SETTINGS_FILE):
        try:
            with open(_WATCH_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            defaults.update(data)
        except Exception:
            pass
    return defaults


def _save_watch_settings(settings: dict):
    try:
        with open(_WATCH_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


class WatchSettingsDialog(QDialog):
    """Configuration dialog for Watch Folder mode."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        _t = get_active_theme()
        self.setWindowTitle("Watch Folder Settings")
        self.setMinimumWidth(450)
        self.setStyleSheet(get_active_stylesheet())
        self.settings = dict(settings)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # Header
        lbl_h = QLabel("Watch Folder — Auto-Organize")
        lbl_h.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-size: 14px; font-weight: bold;")
        lay.addWidget(lbl_h)

        # Folder list
        lbl_f = QLabel("Watched Folders:")
        lbl_f.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        lay.addWidget(lbl_f)
        self.lst_folders = QListWidget()
        self.lst_folders.setMaximumHeight(120)
        for f in self.settings.get('folders', []):
            self.lst_folders.addItem(f)
        lay.addWidget(self.lst_folders)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Add Folder")
        btn_add.clicked.connect(self._add_folder)
        btn_row.addWidget(btn_add)
        btn_rm = QPushButton("Remove Selected")
        btn_rm.clicked.connect(self._remove_folder)
        btn_row.addWidget(btn_rm)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Delay
        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Delay before scan (seconds):"))
        self.spn_delay = QSpinBox()
        self.spn_delay.setRange(1, 300)
        self.spn_delay.setValue(self.settings.get('delay_seconds', 5))
        delay_row.addWidget(self.spn_delay)
        delay_row.addStretch()
        lay.addLayout(delay_row)

        # Auto-apply
        self.chk_auto = QCheckBox("Auto-apply (move files without confirmation)")
        self.chk_auto.setChecked(self.settings.get('auto_apply', False))
        lay.addWidget(self.chk_auto)

        # Minimize to tray
        self.chk_tray = QCheckBox("Minimize to system tray instead of closing")
        self.chk_tray.setChecked(self.settings.get('minimize_to_tray', True))
        lay.addWidget(self.chk_tray)

        # Buttons
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Watch Folder")
        if d:
            self.lst_folders.addItem(d)

    def _remove_folder(self):
        row = self.lst_folders.currentRow()
        if row >= 0:
            self.lst_folders.takeItem(row)

    def get_settings(self) -> dict:
        folders = [self.lst_folders.item(i).text() for i in range(self.lst_folders.count())]
        return {
            'enabled': True,
            'folders': folders,
            'delay_seconds': self.spn_delay.value(),
            'auto_apply': self.chk_auto.isChecked(),
            'minimize_to_tray': self.chk_tray.isChecked()
        }


class WatchModeManager:
    """Manages QFileSystemWatcher for auto-organizing watched folders.

    Enhanced features:
    - Snapshot-based change detection to learn from manual file moves
    - Download-folder cooldown (longer delay for Downloads-like dirs)
    - Tray notification per organized file
    """

    _DOWNLOAD_NAMES = {'downloads', 'download', 'descargas', 'téléchargements'}

    def __init__(self, parent_window):
        self.parent = parent_window
        self.settings = _load_watch_settings()
        self._watcher = QFileSystemWatcher()
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._delay_timers = {}  # folder -> QTimer
        self._active = False
        self._snapshots = {}  # folder -> set of filenames at last snapshot
        self._files_organized = 0

    def start(self, folders: list, delay: int = 5):
        """Start watching the given folders."""
        watched = self._watcher.directories()
        if watched:
            self._watcher.removePaths(watched)
        for folder in folders:
            if os.path.isdir(folder):
                self._watcher.addPath(folder)
                self._snapshots[folder] = self._snapshot_dir(folder)
        self._delay = delay
        self._active = True
        self._files_organized = 0

    def stop(self):
        """Stop watching all folders."""
        watched = self._watcher.directories()
        if watched:
            self._watcher.removePaths(watched)
        for t in self._delay_timers.values():
            t.stop()
        self._delay_timers.clear()
        self._snapshots.clear()
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    @staticmethod
    def _snapshot_dir(folder: str) -> set:
        try:
            return set(os.listdir(folder))
        except OSError:
            return set()

    def _is_download_folder(self, folder: str) -> bool:
        return os.path.basename(folder).lower() in self._DOWNLOAD_NAMES

    def _on_dir_changed(self, path: str):
        """Called when a watched directory changes. Delays then triggers scan."""
        if path in self._delay_timers:
            self._delay_timers[path].stop()

        # Detect manual moves (files disappeared) and learn from them
        self._detect_manual_moves(path)

        # Use longer cooldown for download folders (files may still be writing)
        delay = self._delay
        if self._is_download_folder(path):
            delay = max(delay, 15)

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda p=path: self._trigger_scan(p))
        timer.start(delay * 1000)
        self._delay_timers[path] = timer

    def _detect_manual_moves(self, folder: str):
        """Compare folder snapshot to detect manually moved/deleted files and learn."""
        old_snap = self._snapshots.get(folder, set())
        new_snap = self._snapshot_dir(folder)
        self._snapshots[folder] = new_snap

        disappeared = old_snap - new_snap
        appeared = new_snap - old_snap

        if not disappeared:
            return

        # Check if disappeared files moved to subdirectories (manual organization)
        try:
            from unifile.learning import get_learner
            learner = get_learner()
        except Exception:
            return

        for fname in disappeared:
            old_path = os.path.join(folder, fname)
            if os.path.isdir(old_path):
                continue
            # Search subdirs for the file
            for sub in os.listdir(folder):
                sub_path = os.path.join(folder, sub)
                if os.path.isdir(sub_path) and os.path.isfile(os.path.join(sub_path, fname)):
                    # User manually moved fname into sub/ — learn this as a correction
                    learner.record_correction(fname, old_path, sub)
                    if hasattr(self.parent, '_log'):
                        self.parent._log(f"Watch: learned manual move {fname} -> {sub}/")
                    append_watch_event({
                        'folder': folder,
                        'action': 'learned_move',
                        'details': f'{fname} -> {sub}/',
                    })
                    break

    def _trigger_scan(self, folder: str):
        """Trigger a mini-scan for the changed folder."""
        if hasattr(self.parent, '_log'):
            self.parent._log(f"Watch: change detected in {folder}")
        append_watch_event({
            'folder': folder,
            'action': 'scan_triggered',
            'details': 'Directory change detected, auto-scan started',
        })
        # Set source to the changed folder and trigger scan
        if hasattr(self.parent, 'cmb_pc_src'):
            self.parent.cmb_pc_src.setCurrentText(folder)
        if hasattr(self.parent, 'txt_pc_src'):
            self.parent.txt_pc_src.setText(folder)
        self.parent.cmb_op.setCurrentIndex(3)  # OP_FILES
        QTimer.singleShot(100, self.parent._on_scan)

        # Update snapshot after scan trigger
        self._snapshots[folder] = self._snapshot_dir(folder)

    def notify_file_organized(self, filename: str, category: str):
        """Called after a file is organized to show tray notification."""
        self._files_organized += 1
        tray = getattr(self.parent, '_tray', None)
        if tray and tray.isVisible():
            tray.showMessage(
                "UniFile — File Organized",
                f"{filename} -> {category}",
                QSystemTrayIcon.MessageIcon.Information, 2000)


# ══════════════════════════════════════════════════════════════════════════════
# FILE PREVIEW PANEL — Side panel for file details and thumbnail
# ══════════════════════════════════════════════════════════════════════════════


class FilePreviewPanel(QWidget):
    """Split-view side panel showing image preview, text excerpt, metadata."""

    open_requested = pyqtSignal(str)  # filepath

    def __init__(self, parent=None):
        super().__init__(parent)
        _t = get_active_theme()
        self._t = _t
        self.setMinimumWidth(260)
        self.setMaximumWidth(400)
        self.setStyleSheet(f"background: {_t['header_bg']}; border-left: 1px solid {_t['btn_bg']};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self.lbl_preview_img = QLabel()
        self.lbl_preview_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview_img.setFixedHeight(250)
        self.lbl_preview_img.setStyleSheet(f"background: {_t['header_bg']}; border-radius: 6px; border: 1px solid {_t['btn_bg']};")
        lay.addWidget(self.lbl_preview_img)

        self.lbl_preview_name = QLabel("")
        self.lbl_preview_name.setWordWrap(True)
        self.lbl_preview_name.setStyleSheet(f"color: {_t['fg_bright']}; font-size: 13px; font-weight: bold;")
        lay.addWidget(self.lbl_preview_name)

        self.lbl_preview_meta = QLabel("")
        self.lbl_preview_meta.setWordWrap(True)
        self.lbl_preview_meta.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        lay.addWidget(self.lbl_preview_meta)

        self.txt_preview_text = QTextEdit()
        self.txt_preview_text.setReadOnly(True)
        self.txt_preview_text.setMaximumHeight(120)
        self.txt_preview_text.setStyleSheet(
            f"QTextEdit {{ background: {_t['header_bg']}; color: {_t['muted']}; font-size: 11px;"
            f"border: 1px solid {_t['btn_bg']}; border-radius: 4px; padding: 4px; }}")
        self.txt_preview_text.hide()
        lay.addWidget(self.txt_preview_text)

        # Archive contents display
        self.txt_archive = QTextEdit()
        self.txt_archive.setReadOnly(True)
        self.txt_archive.setMaximumHeight(120)
        self.txt_archive.setStyleSheet(
            f"QTextEdit {{ background: {_t['header_bg']}; color: {_t['accent']}; font-size: 11px;"
            f"border: 1px solid {_t['btn_bg']}; border-radius: 4px; padding: 4px; }}")
        self.txt_archive.hide()
        lay.addWidget(self.txt_archive)

        self.btn_preview_open = QPushButton("Open Externally")
        self.btn_preview_open.setFixedHeight(28)
        self.btn_preview_open.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {_t['btn_bg']};"
            f"color: {_t['sidebar_btn_active_fg']}; border: 1px solid {_t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
        self.btn_preview_open.clicked.connect(self._open_file)
        lay.addWidget(self.btn_preview_open)

        lay.addStretch()
        self._current_path = ""

    def show_file(self, filepath: str, metadata: dict = None):
        """Display preview for a file."""
        self._current_path = filepath
        if not filepath or not os.path.exists(filepath):
            self.clear()
            return
        name = os.path.basename(filepath)
        self.lbl_preview_name.setText(name)
        ext = os.path.splitext(name)[1].lower()

        # Image preview
        img_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp',
                    '.ico', '.svg', '.heic', '.heif', '.avif'}
        if ext in img_exts:
            pix = QPixmap(filepath)
            if not pix.isNull():
                scaled = pix.scaled(280, 230, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                self.lbl_preview_img.setPixmap(scaled)
            else:
                self.lbl_preview_img.setText("Preview unavailable")
                _t = self._t
                self.lbl_preview_img.setStyleSheet(f"background: {_t['header_bg']}; color: {_t['muted']}; border-radius: 6px; border: 1px solid {_t['btn_bg']};")
        else:
            self.lbl_preview_img.clear()
            self.lbl_preview_img.setText(ext.upper() if ext else "FILE")
            _t = self._t
            self.lbl_preview_img.setStyleSheet(
                f"background: {_t['header_bg']}; color: {_t['muted']}; font-size: 28px; font-weight: bold;"
                f"border-radius: 6px; border: 1px solid {_t['btn_bg']};")

        # Metadata
        meta_parts = []
        try:
            stat = os.stat(filepath)
            sz = stat.st_size
            for u in ['B', 'KB', 'MB', 'GB']:
                if sz < 1024:
                    meta_parts.append(f"Size: {sz:.1f} {u}")
                    break
                sz /= 1024
            mt = datetime.fromtimestamp(stat.st_mtime)
            meta_parts.append(f"Modified: {mt.strftime('%Y-%m-%d %H:%M')}")
        except OSError:
            pass
        if metadata:
            if 'width' in metadata and 'height' in metadata:
                meta_parts.append(f"Dimensions: {metadata['width']}x{metadata['height']}")
            if 'duration' in metadata:
                meta_parts.append(f"Duration: {metadata['duration']}")
            if 'artist' in metadata:
                meta_parts.append(f"Artist: {metadata['artist']}")
            if 'camera' in metadata:
                meta_parts.append(f"Camera: {metadata['camera']}")
            if 'pages' in metadata:
                meta_parts.append(f"Pages: {metadata['pages']}")
        self.lbl_preview_meta.setText('\n'.join(meta_parts))

        # Text excerpt for text-like files
        text_exts = {'.txt', '.md', '.py', '.js', '.ts', '.html', '.css', '.json', '.xml',
                     '.yaml', '.yml', '.csv', '.log', '.ini', '.cfg', '.sh', '.bat'}
        if ext in text_exts:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    excerpt = f.read(500)
                self.txt_preview_text.setPlainText(excerpt[:200])
                self.txt_preview_text.show()
            except Exception:
                self.txt_preview_text.hide()
        else:
            self.txt_preview_text.hide()

        # Archive peek
        archive_exts = {'.zip', '.rar', '.7z'}
        if ext in archive_exts:
            peek = ArchivePeeker.peek(filepath)
            if peek['file_count'] > 0:
                lines = [f"Archive: {peek['file_count']} files, {peek['total_size']} bytes"]
                top_exts = peek['extensions'].most_common(5)
                if top_exts:
                    lines.append("Top types: " + ', '.join(f"{e}({c})" for e, c in top_exts))
                for n in peek['names'][:8]:
                    lines.append(f"  {n}")
                self.txt_archive.setPlainText('\n'.join(lines))
                self.txt_archive.show()
            else:
                self.txt_archive.hide()
        else:
            self.txt_archive.hide()

    def clear(self):
        self._current_path = ""
        self.lbl_preview_img.clear()
        self.lbl_preview_img.setText("")
        self.lbl_preview_name.setText("")
        self.lbl_preview_meta.setText("")
        self.txt_preview_text.hide()
        self.txt_archive.hide()

    def _open_file(self):
        if self._current_path and os.path.exists(self._current_path):
            if sys.platform == 'win32':
                os.startfile(self._current_path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self._current_path])
            else:
                subprocess.Popen(['xdg-open', self._current_path])


# ══════════════════════════════════════════════════════════════════════════════
# BEFORE/AFTER COMPARISON VIEW — Side-by-side tree diff
# ══════════════════════════════════════════════════════════════════════════════

