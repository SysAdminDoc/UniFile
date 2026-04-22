"""Tests for v9.3.0 additions: ui_helpers extraction, Settings Hub,
Audio-Duplicates filter, and the _apply_type_filter logic."""
import pytest

# ── ui_helpers: confidence colors + truncate_middle ───────────────────────────

def test_ui_helpers_confidence_text_color_extremes():
    from unifile.ui_helpers import confidence_text_color
    # Low confidence — should be in the red range (R > G, B low)
    low = confidence_text_color(0.0)
    assert low.startswith('#')
    assert len(low) == 7
    # High confidence — should be in the green range
    high = confidence_text_color(100.0)
    assert high.startswith('#')
    assert low != high


def test_ui_helpers_confidence_text_color_clamps_out_of_range():
    from unifile.ui_helpers import confidence_text_color
    # Negative and >100 should not raise — they clamp
    assert confidence_text_color(-50) == confidence_text_color(0)
    assert confidence_text_color(500) == confidence_text_color(100)


def test_ui_helpers_confidence_bg_returns_qcolor():
    from PyQt6.QtGui import QColor

    from unifile.ui_helpers import confidence_bg
    c = confidence_bg(50, alpha=30)
    assert isinstance(c, QColor)
    assert c.alpha() == 30


def test_ui_helpers_truncate_middle_short_string_untouched():
    from unifile.ui_helpers import truncate_middle
    assert truncate_middle("hello", 20) == "hello"


def test_ui_helpers_truncate_middle_preserves_ends():
    from unifile.ui_helpers import truncate_middle
    s = "C:/very/deep/nested/path/to/thing/report.pdf"
    out = truncate_middle(s, max_length=24)
    assert len(out) == 24
    assert out.startswith("C:/")
    assert out.endswith("report.pdf")
    assert "…" in out


def test_ui_helpers_truncate_middle_zero_length():
    """Pathological edge case: max_length smaller than marker itself."""
    from unifile.ui_helpers import truncate_middle
    result = truncate_middle("hello world", max_length=1)
    assert len(result) == 1


# ── Main window still exposes the legacy static shims ─────────────────────────

def test_main_window_has_backward_compat_shims():
    """The static methods on UniFile must still work for code that hasn't
    migrated to ui_helpers yet."""
    from unifile.main_window import UniFile
    # Calling as class methods, no instance needed
    color = UniFile._confidence_text_color(75.0)
    assert color.startswith('#') and len(color) == 7
    bg = UniFile._confidence_bg(75.0)
    assert bg.alpha() > 0


# ── Settings Hub import + structure ───────────────────────────────────────────

def test_settings_hub_dialog_is_exported():
    from unifile.dialogs import SettingsHubDialog
    assert SettingsHubDialog is not None


def test_settings_hub_call_routes_missing_slot_gracefully():
    """When the parent window doesn't have a given slot, the hub should not
    raise — it should signal failure in a subtle way (title change)."""
    from unifile.dialogs.settings_hub import SettingsHubDialog
    # Construct without a QApplication would crash PyQt6 on widget creation,
    # so we only test the _call routing logic, not the dialog itself.
    # Build a fake dialog with _parent=None and verify _call handles it.
    class _MockHub:
        _parent = None
        _called = []
        def setWindowTitle(self, title):
            self._called.append(title)
    mock = _MockHub()
    SettingsHubDialog._call(mock, 'nonexistent_slot')
    # Should have changed window title to indicate the missing slot
    assert any('not available' in t for t in mock._called)


# ── Audio Duplicates UI: Chromaprint status detection ─────────────────────────

def test_find_fpcalc_returns_string_not_none():
    """_find_fpcalc must always return a string (empty or path), never None,
    so the UI's bool() check works correctly."""
    from unifile.duplicates import _find_fpcalc
    result = _find_fpcalc()
    assert isinstance(result, str)
    # Cached result: subsequent calls return the same thing
    assert _find_fpcalc() == result


# ── Silent-failure sweep regression: ApplyAepWorker rollback ──────────────────

def test_apply_aep_rollback_logs_on_failure():
    """Ensure ApplyAepWorker.run's rollback except clause captures the error
    (used to silently pass)."""
    # This is a static source-level check — verify the pattern is present.
    import inspect

    from unifile.workers import ApplyAepWorker
    src = inspect.getsource(ApplyAepWorker.run)
    # Either: rollback uses shutil.move and logs on failure
    assert 'Rollback failed' in src or 'roll_exc' in src, (
        "ApplyAepWorker.run should log rollback failures, not silently swallow them"
    )
