"""Regression coverage for the large-library model/view surfaces."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QListView

from unifile.models import FileItem
from unifile.virtualized_view import (
    VirtualizedItemStore,
    VirtualizedResultsModel,
    VirtualizedResultsView,
    VirtualizedThumbnailView,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([sys.argv[0], "-platform", "offscreen"])


def _item(name: str, category: str = "Photos", confidence: int = 90) -> FileItem:
    item = FileItem()
    item.name = name
    item.display_name = name
    item.full_src = os.path.join("/library", name)
    item.category = category
    item.confidence = confidence
    item.method = "extension"
    return item


def test_item_store_loads_pages_lazily_and_evicts_old_pages():
    calls = []
    store = VirtualizedItemStore(
        count=600,
        loader=lambda index: calls.append(index) or index,
        page_size=100,
        max_pages=2,
    )

    assert calls == []
    assert store.item_at(250) == 250
    assert calls == list(range(200, 300))
    assert store.item_at(251) == 251
    assert len(calls) == 100
    store.item_at(0)
    store.item_at(400)
    store.item_at(250)
    assert calls[-100:] == list(range(200, 300))


def test_results_model_preserves_source_sequence_and_maps_filtered_rows(qapp):
    del qapp
    items = [_item("z.jpg"), _item("a.jpg", confidence=40), _item("m.pdf", "Documents")]
    model = VirtualizedResultsModel()
    model.set_items(items, source_root="/library")

    assert model.store.source is items
    assert model.rowCount() == 3
    assert model.data(model.index(0, 2)) == "z.jpg"
    assert model.data(model.index(0, 3)) == "library"

    assert model.setData(model.index(1, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert items[1].selected is False

    model.set_filter(lambda index, item: index != 1)
    assert model.rowCount() == 2
    assert model.item_index(1) == 2

    items.append(_item("new.png"))
    model.set_filter(None)
    model.sync_appended_items()
    assert model.rowCount() == 4


def test_results_view_and_thumbnail_grid_are_model_backed(qapp):
    del qapp
    items = [_item("one.jpg"), _item("two.png", "Design")]

    results = VirtualizedResultsView()
    results.set_items(items, category_colors={"Photos": "#4ade80", "Design": "#a78bfa"})
    assert results.rowCount() == 2
    assert results.item(1, 2).text() == "two.png"
    assert results.item_index(1) == 1

    grid = VirtualizedThumbnailView()
    grid.set_items(items, category_colors={"Photos": "#4ade80", "Design": "#a78bfa"})
    assert isinstance(grid, QListView)
    assert grid.model().rowCount() == 2
    assert grid.item_index(grid.model().index(0, 0)) == 0
    assert grid.item_at(grid.model().index(1, 0)).name == "two.png"
    assert grid.itemDelegate().sizeHint(None, grid.model().index(0, 0)).width() == 180
