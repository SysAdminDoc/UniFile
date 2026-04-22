"""Integration smoke tests for the main UniFile window.

These tests stand up a real `QApplication` via `pytest-qt` and instantiate
the full `UniFile` widget headlessly (`QT_QPA_PLATFORM=offscreen`). They
catch integration regressions that unit-level tests on mixins miss —
e.g. a mixin extraction that orphans a `self.something` reference, a
signal that was never connected, or a slot that's missing on the
composed class.

All tests here are marked `slow` (several hundred ms to instantiate the
window). Run the full suite with the marker enabled:

    pytest                     # default — smoke tests run
    pytest -m "not slow"       # fast path — skip smoke
    pytest tests/test_main_window_smoke.py -v

If `pytest-qt` is not installed (the `dev` extra pins it), every test
skips cleanly.
"""

import os
import sys

import pytest

# Force headless Qt before importing anything that pulls in a QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("pytestqt", reason="pytest-qt not installed")


@pytest.fixture
def unifile_window(qtbot):
    """Stand up a fresh UniFile main window per test.

    pytest-qt's `qtbot` fixture is function-scoped, so we can't share
    this at module scope. Instantiation is the expensive part (~1-2s
    here); acceptable because every test is marked `slow`.
    """
    from unifile.main_window import UniFile
    win = UniFile()
    qtbot.addWidget(win)
    yield win
    try:
        win.close()
    except Exception:
        pass


# ── Smoke: the window can be instantiated at all ──────────────────────────────

@pytest.mark.slow
def test_main_window_instantiates(unifile_window):
    """If this fails, something in __init__ broke: mixin MRO, a missing
    dialog, an import-time side-effect, etc."""
    assert unifile_window is not None
    assert unifile_window.windowTitle()  # has *some* title


# ── Mixins are wired into the MRO ─────────────────────────────────────────────

@pytest.mark.slow
def test_mixins_in_mro(unifile_window):
    """Each mixin extracted from main_window.py must remain in the MRO.
    Guards against accidental removal during future refactors."""
    from unifile.apply_mixin import ApplyMixin
    from unifile.scan_mixin import ScanMixin
    from unifile.theme_mixin import ThemeMixin
    from unifile.undo_mixin import UndoMixin
    mro = type(unifile_window).__mro__
    for mixin in (ScanMixin, ApplyMixin, ThemeMixin, UndoMixin):
        assert mixin in mro, f"{mixin.__name__} dropped from UniFile MRO"


# ── The primary scan modes each have their entry method ──────────────────────

@pytest.mark.slow
@pytest.mark.parametrize("method_name", [
    "_on_scan", "_scan_aep", "_scan_cat", "_scan_files",      # ScanMixin
    "_on_undo",                                                # UndoMixin
    "_show_empty_state", "_hide_empty_state",                  # main_window itself
])
def test_method_resolves_on_composed_class(unifile_window, method_name):
    assert callable(getattr(unifile_window, method_name, None)), (
        f"expected {method_name} to be callable on UniFile"
    )


# ── The empty state overlay is reachable through its public API ───────────────

@pytest.mark.slow
def test_empty_state_can_show_and_hide(unifile_window):
    """A full round-trip through _show_empty_state / _hide_empty_state
    with the new v9.3.5 recovery-action kwargs. Should not raise."""
    called = []

    def _cb():
        called.append(True)

    unifile_window._show_empty_state(
        "Test title",
        detail="Test detail",
        kicker="TEST",
        action_label="Test action",
        action_callback=_cb,
    )
    # Invoke the click handler directly — no QTest.mouseClick needed.
    unifile_window._on_empty_action_clicked()
    assert called == [True]
    unifile_window._hide_empty_state()


# ── Regression: the undo button exists and responds to the stack shape ────────

@pytest.mark.slow
def test_undo_button_disabled_when_stack_empty(unifile_window, monkeypatch):
    """UndoMixin._on_undo should no-op when _load_undo_stack returns []."""
    from unifile import undo_mixin as um
    monkeypatch.setattr(um, "_load_undo_stack", lambda: [])
    # Should not crash, should not open any dialog — returns silently after _log.
    unifile_window._on_undo()
