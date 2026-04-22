"""UniFile — Analytics dashboard panel."""
import os
from collections import Counter, defaultdict
from datetime import datetime

from PyQt6.QtCore import QRect, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from unifile.config import DARK_STYLE, get_active_stylesheet, get_active_theme  # noqa: F401

# ── Stats worker ───────────────────────────────────────────────────────────────

class _StatsWorker(QThread):
    stats_ready = pyqtSignal(dict)

    def __init__(self, library, parent=None):
        super().__init__(parent)
        # Store engine only — Session is NOT thread-safe; we create our own below
        self._engine = library.engine if (library and library.is_open) else None

    def run(self):
        if not self._engine:
            self.stats_ready.emit(self._empty())
            return
        try:
            from sqlalchemy.orm import Session as _Session
            with _Session(self._engine) as session:
                stats = self._collect(session)
        except Exception:
            stats = self._empty()
        self.stats_ready.emit(stats)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _empty() -> dict:
        return {
            'total_entries': 0,
            'total_tags':    0,
            'untagged':      0,
            'root_count':    0,
            'ext_counts':    [],
            'tag_counts':    [],
            'ext_sizes':     [],
            'monthly_adds':  [],
        }

    def _collect(self, session) -> dict:
        from sqlalchemy import func, select
        from sqlalchemy.orm import joinedload

        from unifile.tagging.models import Entry, Folder, Tag, TagEntry

        # Aggregate counts in SQL — no Python-side iteration for totals
        total_entries = session.execute(select(func.count(Entry.id))).scalar() or 0
        total_tags    = session.execute(select(func.count(Tag.id))).scalar() or 0
        root_count    = session.execute(select(func.count(Folder.id))).scalar() or 0
        untagged      = session.execute(
            select(func.count(Entry.id)).where(
                ~Entry.id.in_(select(TagEntry.entry_id).distinct())
            )
        ).scalar() or 0

        # Per-extension counters (paginated to avoid loading whole library)
        batch_size   = 5000
        offset       = 0
        ext_counter: Counter     = Counter()
        ext_sizes:   defaultdict = defaultdict(int)
        tag_counter: Counter     = Counter()
        monthly:     Counter     = Counter()

        while True:
            batch = list(session.execute(
                select(Entry).options(joinedload(Entry.tags))
                .order_by(Entry.id).limit(batch_size).offset(offset)
            ).unique().scalars().all())
            if not batch:
                break
            for entry in batch:
                ext = (entry.suffix or '').lower() or '(none)'
                ext_counter[ext] += 1
                try:
                    ext_sizes[ext] += os.path.getsize(str(entry.path))
                except OSError:
                    pass
                for tag in entry.tags:
                    tag_counter[tag.name] += 1
                if entry.date_added:
                    try:
                        d  = entry.date_added
                        monthly[f'{d.year}-{d.month:02d}'] += 1
                    except Exception:
                        pass
            offset += batch_size
            if len(batch) < batch_size:
                break

        now = datetime.now()
        months: list[str] = []
        y, m = now.year, now.month
        for _ in range(12):
            months.append(f'{y}-{m:02d}')
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        months.reverse()
        monthly_adds = [(mo, monthly.get(mo, 0)) for mo in months]

        return {
            'total_entries': total_entries,
            'total_tags':    total_tags,
            'untagged':      untagged,
            'root_count':    root_count,
            'ext_counts':    ext_counter.most_common(10),
            'tag_counts':    tag_counter.most_common(10),
            'ext_sizes':     sorted(
                ext_sizes.items(), key=lambda x: x[1], reverse=True
            )[:10],
            'monthly_adds':  monthly_adds,
        }


# ── Custom chart widgets ───────────────────────────────────────────────────────

class _MiniBarChart(QWidget):
    """Horizontal stacked bar chart showing share of each extension."""

    _COLORS = [
        '#5e81ac', '#a3be8c', '#f59e0b', '#ec4899', '#8b5cf6',
        '#06b6d4', '#ef4444', '#84cc16', '#f97316', '#14b8a6',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []
        self.setMinimumHeight(36)
        self.setMaximumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, data: list[tuple[str, int]]):
        self._data = data
        self.update()

    def paintEvent(self, event):
        if not self._data:
            return
        total = sum(v for _, v in self._data)
        if total == 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h   = self.width(), self.height()
        bar_h  = min(28, h - 4)
        y      = (h - bar_h) // 2
        font   = QFont('Segoe UI', 8)
        painter.setFont(font)

        x = 0
        for i, (label, count) in enumerate(self._data):
            bar_w = max(2, int(round(w * count / total)))
            # Clamp last segment to fill remaining width
            if i == len(self._data) - 1:
                bar_w = w - x
            color = QColor(self._COLORS[i % len(self._COLORS)])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(x, y, bar_w, bar_h, 3, 3)

            if bar_w > 36:
                painter.setPen(QPen(QColor('#ffffff')))
                painter.drawText(
                    QRect(x + 4, y, bar_w - 8, bar_h),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f'{label} ({count})',
                )
            x += bar_w
        painter.end()


class _TimelineChart(QWidget):
    """Simple vertical bar chart for monthly file adds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []
        self.setMinimumHeight(90)
        self.setMaximumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, data: list[tuple[str, int]]):
        self._data = data
        self.update()

    def paintEvent(self, event):
        if not self._data:
            return
        t = get_active_theme()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h        = self.width(), self.height()
        n           = len(self._data)
        max_val     = max((v for _, v in self._data), default=1) or 1
        pad_top     = 8
        pad_bottom  = 18
        pad_h       = 4
        chart_w     = w - 2 * pad_h
        chart_h     = h - pad_top - pad_bottom
        step        = chart_w / n
        bar_w       = max(4, int(step * 0.7))
        accent      = QColor(t['accent'])

        for i, (label, count) in enumerate(self._data):
            bar_h = int(chart_h * count / max_val) if count else 2
            x = int(pad_h + i * step + (step - bar_w) / 2)
            y = pad_top + chart_h - bar_h
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(x, y, bar_w, bar_h, 2, 2)

        # Labels: first, middle, last — slice last 5 chars of "YYYY-MM" → "YY-MM"
        painter.setPen(QPen(QColor(t['muted'])))
        painter.setFont(QFont('Segoe UI', 7))
        for i in [0, n // 2, n - 1]:
            label = self._data[i][0][-5:]  # last 5 chars: MM-YY
            x = int(pad_h + i * step)
            painter.drawText(
                QRect(x, h - pad_bottom, int(step), pad_bottom),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        painter.end()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    if n >= 1_073_741_824:
        return f'{n / 1_073_741_824:.1f} GB'
    if n >= 1_048_576:
        return f'{n / 1_048_576:.1f} MB'
    if n >= 1_024:
        return f'{n / 1_024:.1f} KB'
    return f'{n} B'


def _card_frame(t: dict) -> QFrame:
    """Return a styled card/section frame (shared helper)."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setStyleSheet(
        f'QFrame {{'
        f'  background: {t["bg_alt"]};'
        f'  border: 1px solid {t["border"]};'
        f'  border-radius: 8px;'
        f'}}'
    )
    return frame


# Alias kept for callers that use the section-frame name
_section_frame = _card_frame


def _section_title(text: str, t: dict) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f'font-weight: 600; color: {t["fg_bright"]}; '
        f'background: transparent; border: none;'
    )
    return lbl


def _list_style(t: dict) -> str:
    return (
        f'QListWidget {{'
        f'  background: {t["bg"]}; border: 1px solid {t["border"]};'
        f'  border-radius: 4px;'
        f'}}'
        f'QListWidget::item {{ padding: 3px 6px; }}'
        f'QListWidget::item:alternate {{ background: {t["bg_alt"]}; }}'
        f'QListWidget::item:selected {{'
        f'  background: {t["selection"]}; color: {t["fg_bright"]};'
        f'}}'
    )


# ── Main panel ─────────────────────────────────────────────────────────────────

class StatsPanel(QWidget):
    """Analytics dashboard panel for a TagLibrary."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library               = None
        self._worker: _StatsWorker | None = None
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    def set_library(self, lib):
        self._library = lib
        self._refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        t = get_active_theme()

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QHBoxLayout()
        header_title = QLabel('Library Analytics')
        header_title.setStyleSheet(
            f'font-size: 15px; font-weight: 700; color: {t["fg_bright"]};'
        )
        self._refresh_btn = QPushButton('Refresh')
        self._refresh_btn.clicked.connect(self._refresh)
        header.addWidget(header_title)
        header.addStretch()
        header.addWidget(self._refresh_btn)
        root.addLayout(header)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('QScrollArea { border: none; }')
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setSpacing(10)
        body_lay.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(body)
        root.addWidget(scroll)

        # ── Summary cards ──────────────────────────────────────────────────
        self._cards: dict[str, QLabel] = {}
        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        for label, key in [
            ('Total Files',    'total_entries'),
            ('Total Tags',     'total_tags'),
            ('Untagged Files', 'untagged'),
            ('Library Roots',  'root_count'),
        ]:
            frame = _card_frame(t)
            fl = QVBoxLayout(frame)
            fl.setSpacing(4)
            fl.setContentsMargins(12, 10, 12, 10)
            num_lbl = QLabel('—')
            num_lbl.setStyleSheet(
                f'font-size: 22px; font-weight: 700; color: {t["fg_bright"]};'
                f' background: transparent; border: none;'
            )
            num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            txt_lbl = QLabel(label)
            txt_lbl.setStyleSheet(
                f'font-size: 11px; color: {t["muted"]};'
                f' background: transparent; border: none;'
            )
            txt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fl.addWidget(num_lbl)
            fl.addWidget(txt_lbl)
            cards_row.addWidget(frame)
            self._cards[key] = num_lbl
        body_lay.addLayout(cards_row)

        # ── File type distribution bar ──────────────────────────────────────
        bar_frame = _section_frame(t)
        bar_lay = QVBoxLayout(bar_frame)
        bar_lay.setContentsMargins(10, 8, 10, 10)
        bar_lay.setSpacing(6)
        bar_lay.addWidget(_section_title('File Type Distribution', t))
        self._bar_chart = _MiniBarChart()
        bar_lay.addWidget(self._bar_chart)
        body_lay.addWidget(bar_frame)

        # ── Tags + sizes lists ──────────────────────────────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        tags_frame = _section_frame(t)
        tl = QVBoxLayout(tags_frame)
        tl.setContentsMargins(10, 8, 10, 8)
        tl.setSpacing(4)
        tl.addWidget(_section_title('Top 10 Tags', t))
        self._tags_list = QListWidget()
        self._tags_list.setAlternatingRowColors(True)
        self._tags_list.setStyleSheet(_list_style(t))
        tl.addWidget(self._tags_list)
        bottom.addWidget(tags_frame)

        sizes_frame = _section_frame(t)
        sl = QVBoxLayout(sizes_frame)
        sl.setContentsMargins(10, 8, 10, 8)
        sl.setSpacing(4)
        sl.addWidget(_section_title('Storage by Extension', t))
        self._sizes_list = QListWidget()
        self._sizes_list.setAlternatingRowColors(True)
        self._sizes_list.setStyleSheet(_list_style(t))
        sl.addWidget(self._sizes_list)
        bottom.addWidget(sizes_frame)

        body_lay.addLayout(bottom)

        # ── Timeline chart ──────────────────────────────────────────────────
        tl_frame = _section_frame(t)
        tl_lay = QVBoxLayout(tl_frame)
        tl_lay.setContentsMargins(10, 8, 10, 8)
        tl_lay.setSpacing(4)
        tl_lay.addWidget(
            _section_title('Files Added per Month (Last 12 Months)', t)
        )
        self._timeline = _TimelineChart()
        tl_lay.addWidget(self._timeline)
        body_lay.addWidget(tl_frame)

        body_lay.addStretch()

    # ── Data loading ─────────────────────────────────────────────────────────

    def _refresh(self):
        if self._worker and self._worker.isRunning():
            return
        if not self._library:
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText('Loading…')
        self._worker = _StatsWorker(self._library, self)
        self._worker.stats_ready.connect(self._apply_stats)
        self._worker.start()

    def _apply_stats(self, stats: dict):
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText('Refresh')

        self._cards['total_entries'].setText(str(stats['total_entries']))
        self._cards['total_tags'].setText(str(stats['total_tags']))
        self._cards['untagged'].setText(str(stats['untagged']))
        self._cards['root_count'].setText(str(stats['root_count']))

        self._bar_chart.set_data(stats['ext_counts'])

        self._tags_list.clear()
        for tag_name, count in stats['tag_counts']:
            item = QListWidgetItem(f'{tag_name}  ({count})')
            self._tags_list.addItem(item)

        self._sizes_list.clear()
        for ext, total_bytes in stats['ext_sizes']:
            item = QListWidgetItem(f'{ext}  {_fmt_size(total_bytes)}')
            self._sizes_list.addItem(item)

        self._timeline.set_data(stats['monthly_adds'])
