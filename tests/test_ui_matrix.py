"""Pointer-free offscreen UI matrix for themes, fonts, RTL, and accessibility."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt, qInstallMessageHandler
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

from unifile.config import THEMES, _build_theme_qss

_KNOWN_OFFSCREEN_MESSAGES = (
    "QFontDatabase: Cannot find font directory",
    "This plugin does not support propagateSizeHints()",
)


def _panel_factories():
    from unifile.dialogs.archive_indexer_dialog import ArchiveIndexerDialog
    from unifile.dialogs.cleanup import CleanupPanel
    from unifile.dialogs.cloud_remotes import CloudRemotesDialog
    from unifile.dialogs.duplicates import DuplicatePanel
    from unifile.dialogs.media_lookup import MediaLookupPanel
    from unifile.dialogs.saved_searches_dialog import SavedSearchesDialog
    from unifile.dialogs.tag_library import TagLibraryPanel
    from unifile.dialogs.theme import ThemePickerDialog
    from unifile.dialogs.tools import PluginManagerDialog
    from unifile.dialogs.virtual_library_panel import VirtualLibraryPanel
    from unifile.stats_panel import StatsPanel

    return (
        ("tag-library", TagLibraryPanel),
        ("cleanup", CleanupPanel),
        ("duplicates", DuplicatePanel),
        ("media", MediaLookupPanel),
        ("plugins", PluginManagerDialog),
        ("theme", ThemePickerDialog),
        ("saved-searches", SavedSearchesDialog),
        ("archive", ArchiveIndexerDialog),
        ("cloud", CloudRemotesDialog),
        ("virtual-library", VirtualLibraryPanel),
        ("stats", StatsPanel),
    )


def _interactive_children(widget: QWidget):
    control_types = (
        QAbstractButton,
        QAbstractItemView,
        QAbstractSlider,
        QAbstractSpinBox,
        QComboBox,
        QLineEdit,
        QPlainTextEdit,
        QTextEdit,
    )
    return [child for child in widget.findChildren(QWidget)
            if isinstance(child, control_types)]


def _render_and_assert(widget: QWidget, app: QApplication, width: int = 1280, height: int = 900):
    minimum = widget.minimumSizeHint()
    assert minimum.width() <= 1600, f"{type(widget).__name__} minimum width is {minimum.width()}"
    assert minimum.height() <= 1200, f"{type(widget).__name__} minimum height is {minimum.height()}"
    widget.resize(max(width, minimum.width()), max(height, minimum.height()))
    widget.show()
    app.processEvents()

    pixmap = widget.grab()
    assert not pixmap.isNull(), type(widget).__name__
    image = pixmap.toImage()
    samples = []
    x_step = max(1, image.width() // 32)
    y_step = max(1, image.height() // 32)
    for y in range(0, image.height(), y_step):
        for x in range(0, image.width(), x_step):
            color = image.pixelColor(x, y)
            samples.append((color.red(), color.green(), color.blue(), color.alpha()))
    assert len(set(samples)) >= 3, f"{type(widget).__name__} rendered blank or unchanged"

    direct_children = [child for child in widget.findChildren(QWidget)
                       if child.parentWidget() is widget and child.isVisible()]
    for child in direct_children:
        assert widget.rect().contains(child.geometry()), (
            f"{type(widget).__name__} child {type(child).__name__} overflows "
            f"{widget.size()}: {child.geometry()}"
        )
    for child in _interactive_children(widget):
        assert child.accessibleName(), (
            f"{type(widget).__name__} missing accessible name for "
            f"{type(child).__name__} ({child.objectName()})"
        )
        assert child.accessibleDescription(), (
            f"{type(widget).__name__} missing accessible description for "
            f"{child.accessibleName()}"
        )
    widget.hide()


@pytest.mark.parametrize("theme_name", tuple(THEMES), ids=lambda value: value.lower().replace(" ", "-"))
@pytest.mark.parametrize("font_size", (8, 20))
@pytest.mark.parametrize(
    "factory_name,factory",
    _panel_factories(),
    ids=[name for name, _factory in _panel_factories()],
)
def test_major_panels_render_across_themes_and_font_extremes(
    qapp, qtbot, theme_name, font_size, factory_name, factory
):
    app = qapp
    previous_font = app.font()
    previous_direction = app.layoutDirection()
    previous_style = app.styleSheet()
    app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    font = QFont(previous_font)
    font.setPointSize(font_size)
    app.setFont(font)
    app.setStyleSheet(_build_theme_qss(THEMES[theme_name], font_size))
    messages = []
    previous_handler = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message)
    )
    try:
        widget = factory()
        qtbot.addWidget(widget)
        _render_and_assert(widget, app)
        unexpected_messages = [
            message for message in messages
            if not message.startswith(_KNOWN_OFFSCREEN_MESSAGES)
        ]
        assert not unexpected_messages, (
            f"Qt warnings for {factory_name}/{theme_name}/{font_size}: "
            f"{unexpected_messages}"
        )
    finally:
        qInstallMessageHandler(previous_handler)
        app.setStyleSheet(previous_style)
        app.setFont(previous_font)
        app.setLayoutDirection(previous_direction)


@pytest.mark.parametrize(
    "factory_name,factory",
    _panel_factories(),
    ids=[name for name, _factory in _panel_factories()],
)
@pytest.mark.parametrize("font_size", (8, 20))
def test_major_panels_render_in_rtl_layout(
    qapp, qtbot, factory_name, factory, font_size
):
    app = qapp
    previous_font = app.font()
    previous_direction = app.layoutDirection()
    previous_style = app.styleSheet()
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    font = QFont(previous_font)
    font.setPointSize(font_size)
    app.setFont(font)
    app.setStyleSheet(_build_theme_qss(THEMES["High Contrast"], font_size))
    messages = []
    previous_handler = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message)
    )
    try:
        widget = factory()
        qtbot.addWidget(widget)
        widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        _render_and_assert(widget, app)
        unexpected_messages = [
            message for message in messages
            if not message.startswith(_KNOWN_OFFSCREEN_MESSAGES)
        ]
        assert not unexpected_messages, (
            f"Qt warnings for RTL/{factory_name}/{font_size}: "
            f"{unexpected_messages}"
        )
    finally:
        qInstallMessageHandler(previous_handler)
        app.setStyleSheet(previous_style)
        app.setFont(previous_font)
        app.setLayoutDirection(previous_direction)


@pytest.mark.parametrize("theme_name", tuple(THEMES), ids=lambda value: value.lower().replace(" ", "-"))
@pytest.mark.parametrize("font_size", (8, 20))
def test_main_window_renders_across_themes_and_font_extremes(
    qapp, qtbot, theme_name, font_size
):
    from unifile.main_window import UniFile

    app = qapp
    previous_font = app.font()
    previous_direction = app.layoutDirection()
    previous_style = app.styleSheet()
    app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    font = QFont(previous_font)
    font.setPointSize(font_size)
    app.setFont(font)
    app.setStyleSheet(_build_theme_qss(THEMES[theme_name], font_size))
    messages = []
    previous_handler = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message)
    )
    try:
        window = UniFile()
        qtbot.addWidget(window)
        _render_and_assert(window, app, width=1440, height=900)
        unexpected_messages = [
            message for message in messages
            if not message.startswith(_KNOWN_OFFSCREEN_MESSAGES)
        ]
        assert not unexpected_messages, (
            f"Qt warnings for main window/{theme_name}/{font_size}: "
            f"{unexpected_messages}"
        )
    finally:
        qInstallMessageHandler(previous_handler)
        app.setStyleSheet(previous_style)
        app.setFont(previous_font)
        app.setLayoutDirection(previous_direction)
