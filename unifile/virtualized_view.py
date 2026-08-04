"""Scalable model/view surfaces for large PC-file result sets.

The original results table is intentionally kept for the AEP and folder
workflows because those workflows still expose editable cell helpers.  PC
file results use these views instead: the model keeps a reference to the
existing item sequence and the view/delegate only asks for data for rows that
Qt is currently painting.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence

from PyQt6.QtCore import (
    QAbstractListModel,
    QAbstractTableModel,
    QBuffer,
    QByteArray,
    QIODevice,
    QModelIndex,
    QObject,
    QPoint,
    QRect,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from unifile.confidence import ConfidenceTiers, confidence_tier_text
from unifile.thumbnail_cache import get_thumbnail_cache, thumbnail_key


def _format_size(size: int) -> str:
    """Format byte counts without importing the worker module."""
    value = float(size or 0)
    for suffix in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or suffix == "TB":
            return f"{value:.0f} {suffix}" if suffix == "B" else f"{value:.1f} {suffix}"
        value /= 1024
    return "0 B"


class VirtualizedItemStore:
    """Paged access to a sequence or indexed loader.

    ``items`` is never copied.  A sequence can therefore remain the
    application's authoritative list while the model retains only a small
    LRU page cache.  For database-backed callers, pass ``count`` and
    ``loader`` instead of a sequence.
    """

    def __init__(
        self,
        items: Sequence | None = None,
        *,
        count: int | None = None,
        loader: Callable[[int], object] | None = None,
        page_size: int = 256,
        max_pages: int = 8,
    ) -> None:
        self.page_size = max(1, int(page_size))
        self.max_pages = max(1, int(max_pages))
        self._items = items
        self._loader = loader
        self._count = len(items) if items is not None else max(0, int(count or 0))
        self._pages: OrderedDict[int, list] = OrderedDict()

    @property
    def source(self) -> Sequence | None:
        return self._items

    def __len__(self) -> int:
        return self._count

    def set_sequence(self, items: Sequence) -> None:
        """Point at a new sequence without materializing it."""
        self._items = items
        self._loader = None
        self._count = len(items)
        self._pages.clear()

    def set_loader(self, count: int, loader: Callable[[int], object]) -> None:
        self._items = None
        self._loader = loader
        self._count = max(0, int(count))
        self._pages.clear()

    def sync_length(self) -> int:
        """Refresh the count when the referenced sequence has been appended."""
        if self._items is not None:
            self._count = len(self._items)
        return self._count

    def clear(self) -> None:
        self._items = None
        self._loader = None
        self._count = 0
        self._pages.clear()

    def invalidate(self) -> None:
        self._pages.clear()

    def _load_page(self, page: int) -> list:
        cached = self._pages.get(page)
        if cached is not None:
            self._pages.move_to_end(page)
            return cached
        start = page * self.page_size
        end = min(self._count, start + self.page_size)
        if self._items is not None:
            values = [self._items[index] for index in range(start, end)]
        elif self._loader is not None:
            values = [self._loader(index) for index in range(start, end)]
        else:
            values = []
        self._pages[page] = values
        self._pages.move_to_end(page)
        while len(self._pages) > self.max_pages:
            self._pages.popitem(last=False)
        return values

    def item_at(self, index: int):
        if index < 0 or index >= self._count:
            return None
        page, offset = divmod(index, self.page_size)
        values = self._load_page(page)
        return values[offset] if offset < len(values) else None


class VirtualizedResultsModel(QAbstractTableModel):
    """QAbstractTableModel for PC File Organizer results."""

    HEADERS = [
        "",
        "",
        "Name",
        "Directory",
        "→",
        "Category",
        "Rename To",
        "Size",
        "Conf",
        "Method",
        "Status",
    ]

    item_toggled = pyqtSignal(int, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = VirtualizedItemStore()
        self._known_count = 0
        self.source_root = ""
        self.category_colors: dict[str, str] = {}
        self._visible_indices: list[int] | None = None
        self._cell_overrides: dict[tuple[int, int], dict[int, object]] = {}
        self._tiers = ConfidenceTiers()
        self._suppress_length_sync = False

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        if not self._suppress_length_sync:
            self.store.sync_length()
        return len(self._visible_indices) if self._visible_indices is not None else len(self.store)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def item_index(self, row: int) -> int:
        if self._visible_indices is not None:
            if 0 <= row < len(self._visible_indices):
                return self._visible_indices[row]
            return -1
        return row if 0 <= row < len(self.store) else -1

    def item_at(self, row: int):
        index = self.item_index(row)
        return self.store.item_at(index) if index >= 0 else None

    def item_at_index(self, item_index: int):
        return self.store.item_at(item_index)

    def set_items(
        self,
        items: Sequence,
        *,
        source_root: str = "",
        category_colors: dict[str, str] | None = None,
    ) -> None:
        self.beginResetModel()
        self.store.set_sequence(items)
        self._known_count = len(items)
        self.source_root = source_root
        self.category_colors = dict(category_colors or {})
        self._visible_indices = None
        self._cell_overrides.clear()
        self.endResetModel()

    def set_loader(
        self,
        count: int,
        loader: Callable[[int], object],
        *,
        source_root: str = "",
        category_colors: dict[str, str] | None = None,
    ) -> None:
        self.beginResetModel()
        self.store.set_loader(count, loader)
        self._known_count = max(0, int(count))
        self.source_root = source_root
        self.category_colors = dict(category_colors or {})
        self._visible_indices = None
        self._cell_overrides.clear()
        self.endResetModel()

    def sync_appended_items(self) -> None:
        """Notify Qt after the referenced authoritative sequence grows."""
        old_count = self._known_count
        new_count = self.store.sync_length()
        if self._visible_indices is not None:
            self._visible_indices = None
        if new_count <= old_count:
            self.refresh_all()
            return
        self.store._count = old_count
        self._suppress_length_sync = True
        self.beginInsertRows(QModelIndex(), old_count, new_count - 1)
        self.store._count = new_count
        self._known_count = new_count
        self.endInsertRows()
        self._suppress_length_sync = False

    def clear(self) -> None:
        self.beginResetModel()
        self.store.clear()
        self._known_count = 0
        self._visible_indices = None
        self._cell_overrides.clear()
        self.endResetModel()

    def refresh_all(self) -> None:
        if self.rowCount() > 0:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
                [],
            )

    def refresh_item(self, item_index: int) -> None:
        for row in self.rows_for_item(item_index):
            self.dataChanged.emit(
                self.index(row, 0),
                self.index(row, self.columnCount() - 1),
                [],
            )

    def rows_for_item(self, item_index: int) -> list[int]:
        if self._visible_indices is None:
            return [item_index] if 0 <= item_index < len(self.store) else []
        return [row for row, value in enumerate(self._visible_indices) if value == item_index]

    def set_filter(self, predicate: Callable[[int, object], bool] | None) -> None:
        self.beginResetModel()
        if predicate is None:
            self._visible_indices = None
        else:
            self._visible_indices = [
                item_index
                for item_index in range(self.store.sync_length())
                if predicate(item_index, self.store.item_at(item_index))
            ]
        self.endResetModel()

    def search_text(self, item_index: int) -> str:
        item = self.item_at_index(item_index)
        if item is None:
            return ""
        return " ".join(self._display_values(item, item_index)).lower()

    def set_item_selected(self, item_index: int, selected: bool) -> None:
        item = self.item_at_index(item_index)
        if item is None:
            return
        item.selected = bool(selected)
        self.refresh_item(item_index)
        self.item_toggled.emit(item_index, bool(selected))

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section] if 0 <= section < len(self.HEADERS) else None
        return super().headerData(section, orientation, role)

    def _display_values(self, item, item_index: int) -> list[str]:
        if getattr(item, "is_folder", False):
            icon = "📁 "
        else:
            icon = ""
        name = icon + str(getattr(item, "name", ""))
        group = int(getattr(item, "dup_group", 0) or 0)
        if group:
            name += " ⟨G{} {}⟩".format(group, "✓" if getattr(item, "dup_is_original", False) else "✗")
        full_src = str(getattr(item, "full_src", "") or "")
        abs_dir = os.path.dirname(full_src)
        if self.source_root:
            try:
                relative = os.path.relpath(abs_dir, self.source_root)
                directory = os.path.basename(self.source_root) if relative == "." else os.path.join(
                    os.path.basename(self.source_root), relative
                )
            except ValueError:
                directory = abs_dir
        else:
            directory = abs_dir
        display_name = str(getattr(item, "display_name", "") or "")
        rename_to = display_name if display_name and display_name != getattr(item, "name", "") else "—"
        size = getattr(item, "size", 0) or 0
        if size:
            size_text = _format_size(size)
        else:
            size_text = "—" if getattr(item, "is_folder", False) else "0 B"
        conf = float(getattr(item, "confidence", 0) or 0)
        status = "Skip" if getattr(item, "is_duplicate", False) else str(getattr(item, "status", "Pending"))
        return [
            "",
            "📁" if getattr(item, "is_folder", False) else "--",
            name,
            directory,
            "→",
            str(getattr(item, "category", "") or ""),
            rename_to,
            size_text,
            confidence_tier_text(conf, self._tiers),
            str(getattr(item, "method", "") or "").replace("_", " "),
            status,
        ]

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item_index = self.item_index(index.row())
        item = self.item_at_index(item_index)
        if item is None:
            return None
        column = index.column()
        override = self._cell_overrides.get((item_index, column), {}).get(int(role))
        if override is not None:
            return override
        values = self._display_values(item, item_index)
        if role == Qt.ItemDataRole.DisplayRole:
            return values[column]
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return Qt.CheckState.Checked if getattr(item, "selected", False) else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.UserRole:
            return item_index
        if role == Qt.ItemDataRole.ToolTipRole:
            path = str(getattr(item, "full_src", "") or "")
            details = [path]
            if getattr(item, "detail", ""):
                details.append(str(item.detail))
            if getattr(item, "dup_detail", ""):
                details.append(str(item.dup_detail))
            return "\n".join(value for value in details if value)
        if role == Qt.ItemDataRole.ForegroundRole:
            if column == 2:
                if getattr(item, "is_duplicate", False):
                    return QColor("#f59e0b")
                if getattr(item, "dup_group", 0) and getattr(item, "dup_is_original", False):
                    return QColor("#4ade80")
            if column == 3 or column == 7:
                return QColor("#8b98a8")
            if column == 5:
                return QColor(self.category_colors.get(getattr(item, "category", ""), "#4ade80"))
            if column == 6:
                return QColor("#4fc3f7" if values[column] != "—" else "#8b98a8")
            if column == 8:
                conf = float(getattr(item, "confidence", 0) or 0)
                return QColor("#4ade80" if conf >= 80 else "#f59e0b" if conf >= 50 else "#ef4444")
            if column == 9:
                return QColor("#f59e0b")
            if column == 10:
                return QColor("#6b7280" if values[column] == "Skip" else "#f59e0b")
        if role == Qt.ItemDataRole.BackgroundRole:
            if getattr(item, "is_duplicate", False):
                return QColor(245, 158, 11, 20)
            color = QColor(self.category_colors.get(getattr(item, "category", ""), "#4ade80"))
            color.setAlpha(18)
            return color
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            if column in (2, 5):
                font.setBold(True)
            return font
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (0, 1, 4, 5, 8, 9, 10):
                return Qt.AlignmentFlag.AlignCenter
            if column == 7:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignVCenter
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value, role: Qt.ItemDataRole = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        item_index = self.item_index(index.row())
        item = self.item_at_index(item_index)
        if item is None:
            return False
        checked = value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value
        item.selected = bool(checked)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.item_toggled.emit(item_index, bool(checked))
        return True

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        if column < 0 or column >= self.columnCount():
            return
        indices = self._visible_indices if self._visible_indices is not None else list(range(self.store.sync_length()))

        def key(item_index: int):
            item = self.item_at_index(item_index)
            if item is None:
                return ""
            if column == 7:
                return getattr(item, "size", 0) or 0
            if column == 8:
                return getattr(item, "confidence", 0) or 0
            return self._display_values(item, item_index)[column].casefold()

        indices.sort(key=key, reverse=order == Qt.SortOrder.DescendingOrder)
        self.layoutAboutToBeChanged.emit()
        self._visible_indices = indices
        self.layoutChanged.emit()

    def cell_override(self, item_index: int, column: int, role: Qt.ItemDataRole, value) -> None:
        self._cell_overrides.setdefault((item_index, column), {})[int(role)] = value
        self.refresh_item(item_index)


class VirtualizedCellProxy:
    """Small compatibility facade for legacy code that updates table cells."""

    def __init__(self, view: VirtualizedResultsView, row: int, column: int) -> None:
        self.view = view
        self.row = row
        self.column = column

    @property
    def item_index(self) -> int:
        return self.view.item_index(self.row)

    def text(self) -> str:
        value = self.view.model().data(
            self.view.model().index(self.row, self.column), Qt.ItemDataRole.DisplayRole
        )
        return str(value or "")

    def data(self, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        return self.view.model().data(self.view.model().index(self.row, self.column), role)

    def setText(self, text: str) -> None:
        self.view.model().cell_override(
            self.item_index, self.column, Qt.ItemDataRole.DisplayRole, str(text)
        )

    def setForeground(self, color: QColor) -> None:
        self.view.model().cell_override(
            self.item_index, self.column, Qt.ItemDataRole.ForegroundRole, color
        )

    def setBackground(self, color: QColor) -> None:
        self.view.model().cell_override(
            self.item_index, self.column, Qt.ItemDataRole.BackgroundRole, color
        )

    def setToolTip(self, text: str) -> None:
        self.view.model().cell_override(
            self.item_index, self.column, Qt.ItemDataRole.ToolTipRole, str(text)
        )

    def setData(self, role: Qt.ItemDataRole, value) -> None:
        self.view.model().cell_override(self.item_index, self.column, role, value)

    def __bool__(self) -> bool:
        return True


class VirtualizedResultsView(QTableView):
    """Fixed-row QTableView backed by :class:`VirtualizedResultsModel`."""

    currentCellChanged = pyqtSignal(int, int, int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model = VirtualizedResultsModel(self)
        self.setModel(self._model)
        self._model.item_toggled.connect(self._on_item_toggled)
        self._previous_current = QModelIndex()
        self._row_height = 40
        self.setObjectName("virtualized_results")
        self.setAccessibleName("Virtualized results table")
        self.setAccessibleDescription(
            "Large-library results table; rows are loaded as they become visible"
        )
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(self._row_height)
        self.horizontalHeader().setFixedHeight(36)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.selectionModel().currentChanged.connect(self._current_changed)

    def _current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        self.currentCellChanged.emit(
            current.row(), current.column(), previous.row(), previous.column()
        )

    def _on_item_toggled(self, item_index: int, selected: bool) -> None:
        del item_index, selected

    def set_items(self, items: Sequence, *, source_root: str = "",
                  category_colors: dict[str, str] | None = None) -> None:
        self._model.set_items(items, source_root=source_root, category_colors=category_colors)

    def set_loader(self, count: int, loader: Callable[[int], object], *, source_root: str = "",
                   category_colors: dict[str, str] | None = None) -> None:
        self._model.set_loader(count, loader, source_root=source_root, category_colors=category_colors)

    def sync_appended_items(self) -> None:
        self._model.sync_appended_items()

    def item_index(self, row: int) -> int:
        return self._model.item_index(row)

    def rowCount(self) -> int:
        return self._model.rowCount()

    def columnCount(self) -> int:
        return self._model.columnCount()

    def row_for_item(self, item_index: int) -> int:
        rows = self._model.rows_for_item(item_index)
        return rows[0] if rows else -1

    def rowAt(self, y: int) -> int:
        point = QPoint(max(0, self.columnViewportPosition(0)), int(y))
        index = self.indexAt(point)
        return index.row() if index.isValid() else -1

    def item(self, row: int, column: int) -> VirtualizedCellProxy | None:
        if self.item_index(row) < 0 or column < 0 or column >= self.model().columnCount():
            return None
        return VirtualizedCellProxy(self, row, column)

    def cellWidget(self, row: int, column: int):
        del row, column
        return None

    def setRowCount(self, count: int) -> None:
        if int(count) == 0:
            self._model.clear()

    def insertRow(self, row: int) -> bool:
        del row
        self.sync_appended_items()
        return True

    def setRowHeight(self, row: int, height: int) -> None:
        del row
        self._row_height = max(1, int(height))
        self.verticalHeader().setDefaultSectionSize(self._row_height)

    def setColumnCount(self, count: int) -> None:
        del count

    def setHorizontalHeaderLabels(self, labels: Iterable[str]) -> None:
        self._model.HEADERS = list(labels)
        self._model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self._model.HEADERS) - 1)

    def setCellWidget(self, row: int, column: int, widget) -> None:
        del row, column, widget

    def setItem(self, row: int, column: int, item) -> None:
        del row, column, item

    def scrollToItem(self, item: VirtualizedCellProxy | QModelIndex | None, *args) -> None:
        del args
        if isinstance(item, VirtualizedCellProxy):
            self.scrollTo(self.model().index(item.row, item.column))
        elif isinstance(item, QModelIndex):
            self.scrollTo(item)


class _ThumbnailSignals(QObject):
    ready = pyqtSignal(str, bytes)


class _ThumbnailLoader(QRunnable):
    def __init__(self, path: str, size: int) -> None:
        super().__init__()
        self.path = path
        self.size = size
        self.signals = _ThumbnailSignals()

    def run(self) -> None:
        try:
            image = QImage(self.path)
            if image.isNull():
                return
            scaled = image.scaled(
                self.size,
                self.size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            payload = QByteArray()
            buffer = QBuffer(payload)
            if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                return
            try:
                if not scaled.save(buffer, "PNG"):
                    return
            finally:
                buffer.close()
            self.signals.ready.emit(self.path, bytes(payload))
        except Exception:
            return


class VirtualizedThumbnailModel(QAbstractListModel):
    """List model that exposes only item data, not one QWidget per file."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = VirtualizedItemStore()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        self.store.sync_length()
        return len(self.store)

    def set_items(self, items: Sequence) -> None:
        self.beginResetModel()
        self.store.set_sequence(items)
        self.endResetModel()

    def item_at(self, row: int):
        return self.store.item_at(row)

    def item_index(self, row: int) -> int:
        return row if 0 <= row < len(self.store) else -1

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.item_at(index.row())
        if item is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return str(getattr(item, "name", ""))
        if role == Qt.ItemDataRole.UserRole:
            return index.row()
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(getattr(item, "full_src", "") or "")
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if getattr(item, "selected", False) else Qt.CheckState.Unchecked
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable

    def setData(self, index: QModelIndex, value, role: Qt.ItemDataRole = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        item = self.item_at(index.row())
        if item is None:
            return False
        item.selected = value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True


class VirtualizedThumbnailDelegate(QStyledItemDelegate):
    """Fixed-size card delegate; thumbnails are requested only when painted."""

    def __init__(self, view: VirtualizedThumbnailView) -> None:
        super().__init__(view)
        self.view = view

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        del option, index
        return QSize(180, 205)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = self.view.model().item_at(index.row())
        if item is None:
            return
        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected) or bool(
            getattr(item, "selected", False)
        )
        theme = self.view.theme
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(theme["accent"] if selected else theme["border"]))
        painter.setBrush(QColor(theme["selection"] if selected else theme["bg_alt"]))
        painter.drawRoundedRect(rect, 8, 8)

        thumb_rect = QRect(rect.left() + 5, rect.top() + 5, rect.width() - 10, 140)
        path = str(getattr(item, "full_src", "") or "")
        pixmap = self.view.thumbnail(path)
        if pixmap is not None and not pixmap.isNull():
            painter.drawPixmap(thumb_rect, pixmap)
        else:
            painter.setPen(QColor(theme["muted"]))
            painter.drawText(
                thumb_rect,
                Qt.AlignmentFlag.AlignCenter,
                os.path.splitext(path)[1].upper() or "?",
            )

        painter.setPen(QColor(theme["fg_bright"]))
        name = str(getattr(item, "name", ""))
        painter.drawText(
            QRect(rect.left() + 7, rect.top() + 149, rect.width() - 14, 24),
            Qt.AlignmentFlag.AlignCenter,
            name if len(name) <= 28 else name[:25] + "…",
        )
        category = str(getattr(item, "category", "") or "")
        painter.setPen(QColor(self.view.category_colors.get(category, theme["green"])))
        painter.drawText(
            QRect(rect.left() + 7, rect.bottom() - 24, rect.width() - 14, 18),
            Qt.AlignmentFlag.AlignCenter,
            category,
        )
        painter.restore()


class VirtualizedThumbnailView(QListView):
    """Thumbnail grid using a QListView and fixed-size delegates."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model = VirtualizedThumbnailModel(self)
        self.setModel(self._model)
        self.theme = {
            "accent": "#4fc3f7",
            "border": "#27435b",
            "selection": "#183d56",
            "bg_alt": "#102131",
            "fg_bright": "#e6edf3",
            "muted": "#8b98a8",
            "green": "#4ade80",
        }
        self.category_colors: dict[str, str] = {}
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._loading: set[str] = set()
        self._cache_limit = 256
        self._thumbnail_cache = get_thumbnail_cache()
        self.setItemDelegate(VirtualizedThumbnailDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(180, 205))
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName("Virtualized thumbnail grid")
        self.setAccessibleDescription(
            "Large-library thumbnail grid; fixed-size cards load only while visible"
        )

    def set_items(self, items: Sequence, *, category_colors: dict[str, str] | None = None,
                  theme: dict[str, str] | None = None) -> None:
        self.category_colors = dict(category_colors or {})
        if theme:
            self.theme = {**self.theme, **theme}
        self._pixmaps.clear()
        self._loading.clear()
        self._model.set_items(items)
        self.viewport().update()

    def item_index(self, index: QModelIndex | int) -> int:
        row = index if isinstance(index, int) else index.row()
        return self._model.item_index(row)

    def item_at(self, index: QModelIndex | int):
        return self._model.item_at(self.item_index(index))

    def thumbnail(self, path: str) -> QPixmap | None:
        if not path or not os.path.isfile(path):
            return None
        cached = self._pixmaps.get(path)
        if cached is not None:
            self._pixmaps.move_to_end(path)
            return cached
        key = thumbnail_key(path, 150)
        if key:
            payload = self._thumbnail_cache.get(key)
            if payload:
                pixmap = QPixmap()
                if pixmap.loadFromData(payload):
                    self._remember_pixmap(path, pixmap)
                    return pixmap
        if path not in self._loading:
            self._loading.add(path)
            loader = _ThumbnailLoader(path, 150)
            loader.signals.ready.connect(self._thumbnail_ready)
            QThreadPool.globalInstance().start(loader)
        return None

    def _remember_pixmap(self, path: str, pixmap: QPixmap) -> None:
        self._pixmaps[path] = pixmap
        self._pixmaps.move_to_end(path)
        while len(self._pixmaps) > self._cache_limit:
            self._pixmaps.popitem(last=False)

    def _thumbnail_ready(self, path: str, payload: bytes) -> None:
        self._loading.discard(path)
        key = thumbnail_key(path, 150)
        if key:
            self._thumbnail_cache.put(key, payload)
        pixmap = QPixmap()
        pixmap.loadFromData(payload)
        if pixmap.isNull():
            return
        self._remember_pixmap(path, pixmap)
        self.viewport().update()
