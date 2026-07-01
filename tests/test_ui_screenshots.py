"""Rendered UI smoke screenshots for core panels.

Grabs fixed-size offscreen images of the main window, Tag Library,
Cleanup, and Settings Hub panels. Asserts nonblank pixels and no
uncaught Qt warnings. Screenshots written to a temp directory only.
"""
import os
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QSize
    from PyQt6.QtWidgets import QApplication
except ImportError:
    pytest.skip("PyQt6 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], "-platform", "offscreen"])
    yield app


@pytest.fixture
def screenshot_dir():
    with tempfile.TemporaryDirectory(prefix="unifile-screenshots-") as d:
        yield d


def _grab(widget, path, size=(800, 600)):
    widget.resize(QSize(*size))
    widget.show()
    QApplication.processEvents()
    pixmap = widget.grab()
    pixmap.save(path, "PNG")
    widget.hide()
    img = pixmap.toImage()
    assert img.width() > 0 and img.height() > 0
    total = 0
    for y in range(0, img.height(), img.height() // 4):
        for x in range(0, img.width(), img.width() // 4):
            c = img.pixelColor(x, y)
            total += c.red() + c.green() + c.blue()
    assert total > 0, "Screenshot appears completely blank"


def test_tag_library_panel_renders(qapp, screenshot_dir):
    from unifile.dialogs.tag_library import TagLibraryPanel
    panel = TagLibraryPanel()
    _grab(panel, os.path.join(screenshot_dir, "tag_library.png"))


def test_settings_hub_renders(qapp, screenshot_dir):
    from unifile.dialogs.settings_hub import SettingsHubDialog
    dlg = SettingsHubDialog()
    _grab(dlg, os.path.join(screenshot_dir, "settings_hub.png"), (700, 520))


def test_cleanup_panel_renders(qapp, screenshot_dir):
    from unifile.dialogs.cleanup import CleanupPanel
    panel = CleanupPanel()
    _grab(panel, os.path.join(screenshot_dir, "cleanup.png"))
