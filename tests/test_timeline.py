"""Coverage for timeline bucketing and scan-result date filtering."""

from datetime import date, datetime


def _item(name: str, **metadata):
    from unifile.models import FileItem

    item = FileItem()
    item.name = name
    item.metadata = metadata
    return item


def test_timeline_parses_exif_and_builds_contiguous_month_buckets():
    from unifile.timeline import build_timeline, item_timeline_datetime

    items = [
        _item("january.jpg", date_taken="2024:01:02 12:00:00"),
        _item("february.jpg", date_taken="2024-02-10T09:00:00"),
        _item("march.jpg", date_taken="2024-03-15"),
        _item("unknown.txt"),
    ]

    assert item_timeline_datetime(items[0], "created") == datetime(2024, 1, 2, 12)
    timeline = build_timeline(items, "created")

    assert timeline.granularity == "month"
    assert [bucket.label for bucket in timeline.buckets] == [
        "Jan 2024", "Feb 2024", "Mar 2024"
    ]
    assert [bucket.count for bucket in timeline.buckets] == [1, 1, 1]
    assert timeline.dated_count == 3
    assert timeline.undated_count == 1


def test_timeline_view_scrub_filters_items_and_keeps_undated_visible(qtbot):
    from unifile.timeline import TimelineView

    items = [
        _item("january.txt", modified="2024-01-02"),
        _item("february.txt", modified="2024-02-10"),
        _item("march.txt", modified="2024-03-15"),
        _item("unknown.txt"),
    ]
    view = TimelineView()
    qtbot.addWidget(view)
    view.set_items(items)

    assert view.data.granularity == "month"
    view.set_range(1, 1)
    assert view.has_active_range()
    assert view.matches(items[0]) is False
    assert view.matches(items[1]) is True
    assert view.matches(items[2]) is False
    assert view.matches(items[3]) is True

    view.reset_range()
    assert view.has_active_range() is False
    assert all(view.matches(item) for item in items)


def test_timeline_view_can_switch_between_creation_and_modification_dates(qtbot):
    from unifile.timeline import TimelineView

    item = _item(
        "asset.bin",
        creation_date="2020-01-01",
        modified="2026-08-03",
    )
    view = TimelineView()
    qtbot.addWidget(view)
    view.set_items([item])
    assert view.date_mode == "modified"
    assert view.data.buckets[0].start == date(2026, 8, 3)

    view._mode_combo.setCurrentIndex(1)
    assert view.date_mode == "created"
    assert view.data.buckets[0].start == date(2020, 1, 1)
