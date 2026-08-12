"""Contracts for the bounded desktop controller facades."""

from types import SimpleNamespace

from tools.complexity_contract import check_complexity
from unifile.window_controllers import (
    CleanupController,
    MediaController,
    WorkerLifecycleController,
)


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class _Worker:
    def __init__(self):
        self.finished = _Signal()
        self.error = _Signal()
        self.running = False
        self.started = False
        self.cancelled = False
        self.interrupted = False
        self.closed = False

    def isRunning(self):
        return self.running

    def start(self):
        self.started = True
        self.running = True

    def cancel(self):
        self.cancelled = True

    def requestInterruption(self):
        self.interrupted = True

    def wait(self, _timeout):
        self.running = False
        self.finished.emit()
        return True

    def close(self):
        self.closed = True


class _Library:
    is_open = True

    def __init__(self):
        self.tags = {}
        self.fields = []
        self.entry_tags = []

    def get_tag_by_name(self, name):
        return self.tags.get(name)

    def add_tag(self, name, **_kwargs):
        tag = SimpleNamespace(id=len(self.tags) + 1, name=name)
        self.tags[name] = tag
        return tag

    def set_entry_field(self, entry_id, field, value):
        self.fields.append((entry_id, field, value))

    def add_tags_to_entry(self, entry_id, tag_ids):
        self.entry_tags.append((entry_id, tag_ids))


def test_worker_lifecycle_owns_cancel_wait_close_and_errors():
    controller = WorkerLifecycleController()
    worker = _Worker()
    controller.start("scan", worker)
    worker.error.emit("network unavailable")
    assert controller.last_error("scan") == "network unavailable"
    assert controller.cancel("scan")
    assert worker.cancelled and worker.interrupted
    assert controller.close("scan")
    assert worker.closed
    assert controller.active_names() == ()


def test_media_controller_applies_reviewed_fields_and_genres():
    library = _Library()
    result = MediaController.apply_metadata(
        {
            "media_type": "episode",
            "series": "Example Show",
            "season": 2,
            "episode": 3,
            "genres": ["Drama"],
            "synopsis": "A summary",
        },
        library,
        [42],
    )
    assert result.title == "Example Show"
    assert result.saved_entries == 1
    assert (42, "series", "Example Show") in library.fields
    assert (42, "ai_summary", "A summary") in library.fields
    assert library.entry_tags == [(42, [1])]


def test_cleanup_controller_selects_a_bounded_tab():
    class _Tabs:
        def __init__(self):
            self.index = None

        def setCurrentIndex(self, index):
            self.index = index

    panel = SimpleNamespace(tabs=_Tabs())
    CleanupController.select_tab(panel, -3)
    assert panel.tabs.index == 0


def test_orchestration_complexity_budgets_are_green():
    assert check_complexity() == []
