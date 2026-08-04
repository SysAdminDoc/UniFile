"""Reusable sidebar section widgets and persisted layout state."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QToolButton, QVBoxLayout, QWidget

SIDEBAR_SECTION_ORDER = ("organize", "tools", "library", "smart_views", "profile")
SIDEBAR_SECTION_TITLES = {
    "organize": "ORGANIZE",
    "tools": "TOOLS",
    "library": "LIBRARY",
    "smart_views": "SMART VIEWS",
    "profile": "PROFILE",
}
SIDEBAR_DRAG_MIME = "application/x-unifile-sidebar-section"


class SidebarSection(QWidget):
    """A labelled, collapsible section whose header also starts a reorder drag."""

    collapse_changed = pyqtSignal(str, bool)

    def __init__(self, key: str, widgets: list[QWidget], header_style: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._drag_start: QPoint | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QToolButton()
        self.header.setText(SIDEBAR_SECTION_TITLES[key])
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setArrowType(Qt.ArrowType.DownArrow)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setAccessibleName(f"{self.header.text().title()} sidebar section")
        self.header.setAccessibleDescription(
            "Click to collapse or expand this section. Drag the header to reorder it."
        )
        self.header.setToolTip("Click to collapse or expand. Drag to reorder sidebar sections.")
        self.header.setStyleSheet(header_style)
        self.header.toggled.connect(self._on_toggled)
        self.header.installEventFilter(self)
        layout.addWidget(self.header)

        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        for widget in widgets:
            widget.setParent(self.body)
            body_layout.addWidget(widget)
        layout.addWidget(self.body)

    def _on_toggled(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.collapse_changed.emit(self.key, not expanded)

    def set_collapsed(self, collapsed: bool) -> None:
        self.header.setChecked(not collapsed)

    def set_header_style(self, style: str) -> None:
        self.header.setStyleSheet(style)

    def eventFilter(self, watched, event):
        if watched is self.header:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_start = event.position().toPoint()
            elif event.type() == QEvent.Type.MouseMove and self._drag_start is not None:
                if not event.buttons() & Qt.MouseButton.LeftButton:
                    self._drag_start = None
                elif (event.position().toPoint() - self._drag_start).manhattanLength() >= 8:
                    drag = QDrag(self.header)
                    mime = QMimeData()
                    mime.setData(SIDEBAR_DRAG_MIME, self.key.encode("utf-8"))
                    drag.setMimeData(mime)
                    drag.exec(Qt.DropAction.MoveAction)
                    self._drag_start = None
                    return True
        return super().eventFilter(watched, event)


class SidebarSectionHost(QWidget):
    """Drop target that orders sidebar sections and emits the new order."""

    order_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: dict[str, SidebarSection] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setAcceptDrops(True)
        self.setStyleSheet("background: transparent;")

    def set_sections(self, sections: dict[str, SidebarSection], order: list[str]) -> None:
        self._sections = dict(sections)
        for section in self._sections.values():
            self._layout.removeWidget(section)
            section.setParent(self)
        self._apply_order(order)

    def order(self) -> list[str]:
        return [
            self._layout.itemAt(index).widget().key
            for index in range(self._layout.count())
            if self._layout.itemAt(index).widget() is not None
        ]

    def _normalized_order(self, order) -> list[str]:
        result = []
        for key in order or ():
            if key in self._sections and key not in result:
                result.append(key)
        result.extend(key for key in self._sections if key not in result)
        return result

    def _apply_order(self, order: list[str]) -> None:
        for section in self._sections.values():
            self._layout.removeWidget(section)
        for index, key in enumerate(self._normalized_order(order)):
            self._layout.insertWidget(index, self._sections[key])

    def reorder(self, key: str, target_index: int) -> None:
        order = self.order()
        if key not in order:
            return
        source_index = order.index(key)
        order.remove(key)
        if target_index > source_index:
            target_index -= 1
        order.insert(max(0, min(target_index, len(order))), key)
        self._apply_order(order)
        self.order_changed.emit(self.order())

    def reset_order(self) -> None:
        self._apply_order(list(SIDEBAR_SECTION_ORDER))
        self.order_changed.emit(self.order())

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(SIDEBAR_DRAG_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(SIDEBAR_DRAG_MIME):
            event.ignore()
            return
        key = bytes(event.mimeData().data(SIDEBAR_DRAG_MIME)).decode("utf-8")
        position = event.position().toPoint()
        target_index = self._layout.count()
        for index in range(self._layout.count()):
            widget = self._layout.itemAt(index).widget()
            if widget is not None and position.y() < widget.geometry().center().y():
                target_index = index
                break
        self.reorder(key, target_index)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()


def load_sidebar_state(settings: QSettings) -> tuple[list[str], dict[str, bool]]:
    """Load a validated section order and collapsed-state map from QSettings."""
    raw_order = settings.value("sidebar/order", list(SIDEBAR_SECTION_ORDER))
    if isinstance(raw_order, str):
        raw_order = [item for item in raw_order.split(",") if item]
    order = []
    for key in raw_order or ():
        if key in SIDEBAR_SECTION_ORDER and key not in order:
            order.append(key)
    order.extend(key for key in SIDEBAR_SECTION_ORDER if key not in order)

    collapsed = {}
    for key in SIDEBAR_SECTION_ORDER:
        value = settings.value(f"sidebar/collapsed/{key}", False)
        if isinstance(value, str):
            value = value.strip().lower() in {"1", "true", "yes", "on"}
        collapsed[key] = bool(value)
    return order, collapsed


def save_sidebar_state(settings: QSettings, order: list[str], collapsed: dict[str, bool]) -> None:
    """Persist a validated sidebar order and each section's expanded state."""
    normalized = [key for key in order if key in SIDEBAR_SECTION_ORDER]
    normalized.extend(key for key in SIDEBAR_SECTION_ORDER if key not in normalized)
    settings.setValue("sidebar/order", normalized)
    for key in SIDEBAR_SECTION_ORDER:
        settings.setValue(f"sidebar/collapsed/{key}", bool(collapsed.get(key, False)))
    settings.sync()
