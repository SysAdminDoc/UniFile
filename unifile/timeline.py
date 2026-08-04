"""Timeline histogram and date-range filtering for scan results."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_theme

DATE_MODES = ("created", "modified")
_CREATED_KEYS = ("creation_date", "created", "date_created", "date_taken", "date_added")
_MODIFIED_KEYS = ("modified", "modification_date", "date_modified", "mtime")


@dataclass(frozen=True)
class TimelineBucket:
    """One histogram bucket and the number of files assigned to it."""

    start: date
    count: int
    label: str


@dataclass(frozen=True)
class TimelineData:
    """Computed histogram data and the dates that could not be resolved."""

    buckets: tuple[TimelineBucket, ...]
    granularity: str
    dated_count: int
    undated_count: int


def parse_timeline_datetime(value) -> datetime | None:
    """Parse common filesystem, EXIF, ISO, and epoch date representations."""

    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    exif_match = re.match(r"^(\d{4}):(\d{2}):(\d{2})(.*)$", text)
    if exif_match:
        text = (
            f"{exif_match.group(1)}-{exif_match.group(2)}-"
            f"{exif_match.group(3)}{exif_match.group(4)}"
        )
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text[: len(text)], fmt)
        except ValueError:
            continue
    return None


def _item_parts(item) -> tuple[Mapping, str]:
    if isinstance(item, Mapping):
        metadata = item.get("metadata")
        return (metadata if isinstance(metadata, Mapping) else item, str(
            item.get("full_src") or item.get("path") or ""
        ))
    metadata = getattr(item, "metadata", {})
    return (metadata if isinstance(metadata, Mapping) else {}, str(
        getattr(item, "full_src", "") or getattr(item, "path", "") or ""
    ))


def item_timeline_datetime(item, mode: str = "modified") -> datetime | None:
    """Return the best available creation or modification date for an item.

    Embedded metadata wins because it survives moves. Filesystem timestamps are
    the fallback for ordinary documents and items without extractable metadata.
    """

    mode = mode if mode in DATE_MODES else "modified"
    metadata, path = _item_parts(item)
    keys = _CREATED_KEYS if mode == "created" else _MODIFIED_KEYS
    for key in keys:
        parsed = parse_timeline_datetime(metadata.get(key))
        if parsed is not None:
            return parsed

    if mode == "created":
        parsed = parse_timeline_datetime(getattr(item, "created", None))
    else:
        parsed = parse_timeline_datetime(getattr(item, "modified", None))
    if parsed is not None:
        return parsed

    if path:
        try:
            stat = os.stat(path)
            timestamp = stat.st_ctime if mode == "created" else stat.st_mtime
            return datetime.fromtimestamp(timestamp)
        except (OSError, ValueError):
            pass
    return None


def _granularity(first: date, last: date) -> str:
    span_days = (last - first).days
    if span_days <= 62:
        return "day"
    months = (last.year - first.year) * 12 + last.month - first.month
    if months <= 240:
        return "month"
    return "year"


def _bucket_start(value: datetime | date, granularity: str) -> date:
    current = value.date() if isinstance(value, datetime) else value
    if granularity == "day":
        return current
    if granularity == "year":
        return date(current.year, 1, 1)
    return date(current.year, current.month, 1)


def _next_bucket(value: date, granularity: str) -> date:
    if granularity == "day":
        return value + timedelta(days=1)
    if granularity == "year":
        return date(value.year + 1, 1, 1)
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _bucket_label(value: date, granularity: str) -> str:
    if granularity == "day":
        return f"{value.strftime('%b')} {value.day}"
    if granularity == "year":
        return str(value.year)
    return value.strftime("%b %Y")


def build_timeline(
    items: Iterable,
    mode: str = "modified",
    dates: Sequence[datetime | None] | None = None,
) -> TimelineData:
    """Build contiguous histogram buckets for a sequence of scan items."""

    item_list = list(items)
    values = list(dates) if dates is not None else [
        item_timeline_datetime(item, mode) for item in item_list
    ]
    if len(values) != len(item_list):
        raise ValueError("dates must contain one value per item")
    dated = [value for value in values if value is not None]
    if not dated:
        return TimelineData((), "month", 0, len(item_list))

    first = min(value.date() for value in dated)
    last = max(value.date() for value in dated)
    granularity = _granularity(first, last)
    counts = Counter(_bucket_start(value, granularity) for value in dated)
    current = _bucket_start(first, granularity)
    end = _bucket_start(last, granularity)
    buckets: list[TimelineBucket] = []
    while current <= end:
        buckets.append(TimelineBucket(
            start=current,
            count=counts.get(current, 0),
            label=_bucket_label(current, granularity),
        ))
        current = _next_bucket(current, granularity)
    return TimelineData(
        tuple(buckets),
        granularity,
        len(dated),
        len(item_list) - len(dated),
    )


class _TimelineHistogram(QWidget):
    """Compact histogram with selected buckets highlighted."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = TimelineData((), "month", 0, 0)
        self._start = 0
        self._end = -1
        self.setMinimumHeight(76)
        self.setMaximumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, data: TimelineData, start: int = 0, end: int = -1):
        self._data = data
        self._start = start
        self._end = end
        self.update()

    def paintEvent(self, event):
        del event
        if not self._data.buckets:
            painter = QPainter(self)
            painter.setPen(QColor(get_active_theme()["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No file dates available")
            painter.end()
            return

        theme = get_active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        left, right, top, bottom = 6, 6, 8, 24
        chart_width = max(1, width - left - right)
        chart_height = max(1, height - top - bottom)
        buckets = self._data.buckets
        step = chart_width / len(buckets)
        max_count = max(bucket.count for bucket in buckets) or 1
        accent = QColor(theme["accent"])
        muted = QColor(theme["border"])

        for index, bucket in enumerate(buckets):
            bar_width = max(2, int(step * 0.72))
            bar_height = max(2, int(chart_height * bucket.count / max_count))
            x = int(left + index * step + (step - bar_width) / 2)
            y = top + chart_height - bar_height
            selected = self._start <= index <= self._end
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent if selected else muted)
            painter.drawRoundedRect(x, y, bar_width, bar_height, 2, 2)

        painter.setPen(QPen(QColor(theme["muted"])))
        painter.setFont(QFont("Segoe UI", 7))
        label_indices = sorted({0, len(buckets) // 2, len(buckets) - 1})
        for index in label_indices:
            x = int(left + index * step)
            painter.drawText(
                QRect(x, height - bottom, max(1, int(step)), bottom),
                Qt.AlignmentFlag.AlignCenter,
                buckets[index].label,
            )
        painter.end()


class TimelineView(QWidget):
    """Date histogram with accessible range controls for scan results."""

    range_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        self._dates: dict[int, datetime | None] = {}
        self._data = TimelineData((), "month", 0, 0)
        self._mode = "modified"
        self._updating = False

        theme = get_active_theme()
        self.setObjectName("timeline_view")
        self.setAccessibleName("File timeline filter")
        self.setAccessibleDescription(
            "Histogram of file creation or modification dates. Adjust the range to filter scan results."
        )
        self.setStyleSheet(
            f"QWidget#timeline_view {{ background: {theme['header_bg']}; "
            f"border: 1px solid {theme['border']}; border-radius: 10px; }}"
            f"QLabel {{ color: {theme['muted']}; background: transparent; border: none; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(3)

        header = QHBoxLayout()
        title = QLabel("TIMELINE")
        title.setStyleSheet(
            f"color: {theme['fg_bright']}; font-size: 10px; font-weight: 700; "
            "letter-spacing: 1.2px;"
        )
        header.addWidget(title)
        self._summary = QLabel("No dates available")
        header.addWidget(self._summary)
        header.addStretch()
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Modified", "modified")
        self._mode_combo.addItem("Created", "created")
        self._mode_combo.setFixedWidth(104)
        self._mode_combo.setToolTip("Choose which file date the timeline uses")
        self._mode_combo.setAccessibleName("Timeline date mode")
        self._mode_combo.setAccessibleDescription("Choose creation or modification dates")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        header.addWidget(self._mode_combo)
        self._reset = QPushButton("Reset")
        self._reset.setFixedWidth(58)
        self._reset.setToolTip("Show all dates")
        self._reset.setAccessibleName("Reset timeline filter")
        self._reset.clicked.connect(self.reset_range)
        header.addWidget(self._reset)
        root.addLayout(header)

        self._histogram = _TimelineHistogram()
        self._histogram.setAccessibleName("Timeline histogram")
        root.addWidget(self._histogram)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        from_label = QLabel("From")
        to_label = QLabel("To")
        self._start_slider = self._make_slider("Timeline start date")
        self._end_slider = self._make_slider("Timeline end date")
        self._start_slider.valueChanged.connect(self._on_start_changed)
        self._end_slider.valueChanged.connect(self._on_end_changed)
        controls.addWidget(from_label)
        controls.addWidget(self._start_slider, 1)
        controls.addWidget(to_label)
        controls.addWidget(self._end_slider, 1)
        root.addLayout(controls)

    @staticmethod
    def _make_slider(name: str) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 0)
        slider.setEnabled(False)
        slider.setAccessibleName(name)
        slider.setAccessibleDescription("Move the timeline range boundary")
        return slider

    @property
    def date_mode(self) -> str:
        return self._mode

    @property
    def data(self) -> TimelineData:
        return self._data

    def set_items(self, items: Iterable) -> None:
        self._items = list(items)
        self._dates = {
            id(item): item_timeline_datetime(item, self._mode)
            for item in self._items
        }
        values = [self._dates[id(item)] for item in self._items]
        self._data = build_timeline(self._items, self._mode, values)
        self._set_full_range()

    def clear(self) -> None:
        self.set_items(())

    def has_active_range(self) -> bool:
        return bool(self._data.buckets) and (
            self._start_slider.value() > 0
            or self._end_slider.value() < len(self._data.buckets) - 1
        )

    def range_indices(self) -> tuple[int, int]:
        return self._start_slider.value(), self._end_slider.value()

    def set_range(self, start: int, end: int) -> None:
        """Set a range programmatically, clamping and ordering its endpoints."""
        if not self._data.buckets:
            return
        last = len(self._data.buckets) - 1
        start = max(0, min(int(start), last))
        end = max(start, min(int(end), last))
        self._updating = True
        try:
            self._start_slider.setValue(start)
            self._end_slider.setValue(end)
        finally:
            self._updating = False
        self._selection_updated(emit=True)

    def reset_range(self) -> None:
        if not self._data.buckets:
            return
        self.set_range(0, len(self._data.buckets) - 1)

    def matches(self, item) -> bool:
        """Return whether an item belongs in the current selected date range."""
        if not self.has_active_range():
            return True
        value = self._dates.get(id(item))
        if value is None:
            # Keep files without a trustworthy date visible; the timeline is a
            # narrowing aid, not a destructive missing-metadata filter.
            return True
        bucket = _bucket_start(value, self._data.granularity)
        starts = self._data.buckets
        return starts[self._start_slider.value()].start <= bucket <= starts[self._end_slider.value()].start

    def _set_full_range(self) -> None:
        count = len(self._data.buckets)
        self._updating = True
        try:
            for slider in (self._start_slider, self._end_slider):
                slider.setRange(0, max(0, count - 1))
                slider.setEnabled(count > 1)
            self._start_slider.setValue(0)
            self._end_slider.setValue(max(0, count - 1))
        finally:
            self._updating = False
        self._histogram.set_data(self._data, 0, max(0, count - 1))
        self._update_summary()

    def _on_mode_changed(self, index: int) -> None:
        mode = self._mode_combo.itemData(index)
        if mode not in DATE_MODES or mode == self._mode:
            return
        self._mode = mode
        self.set_items(self._items)
        self.range_changed.emit(*self.range_indices())

    def _on_start_changed(self, value: int) -> None:
        if self._updating:
            return
        if value > self._end_slider.value():
            self._updating = True
            self._end_slider.setValue(value)
            self._updating = False
        self._selection_updated(emit=True)

    def _on_end_changed(self, value: int) -> None:
        if self._updating:
            return
        if value < self._start_slider.value():
            self._updating = True
            self._start_slider.setValue(value)
            self._updating = False
        self._selection_updated(emit=True)

    def _selection_updated(self, *, emit: bool) -> None:
        start, end = self.range_indices()
        self._histogram.set_data(self._data, start, end)
        self._update_summary()
        if emit:
            self.range_changed.emit(start, end)

    def _update_summary(self) -> None:
        if not self._data.buckets:
            self._summary.setText("No dates available")
            return
        start, end = self.range_indices()
        selected = sum(bucket.count for bucket in self._data.buckets[start : end + 1])
        suffix = f" · {self._data.undated_count} undated stay visible" if self._data.undated_count else ""
        self._summary.setText(f"{selected:,} dated files in range{suffix}")

