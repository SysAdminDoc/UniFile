"""Empty-state recovery action wiring.

v9.3.5 added an optional primary-action button to the full-viewport empty
state overlay, so the three "No X found" paths in `scan_mixin.py` can
offer one-click recovery ("Reset scan depth", "Lower confidence filter",
"Reset file-type filter").

These tests pin down the wiring without standing up a full QApplication:
  1. `_show_empty_state` accepts the new keyword arguments.
  2. The click handler safely no-ops when no handler is set.
  3. `_on_empty_action_clicked` invokes the stored callable exactly once
     per click, and exceptions surface through `_log`.
"""

import inspect
from types import SimpleNamespace

import pytest


# ── Signature check — catches accidental removal of the new kwargs ─────────────

def test_show_empty_state_accepts_action_kwargs():
    from unifile.main_window import UniFile
    sig = inspect.signature(UniFile._show_empty_state)
    params = set(sig.parameters)
    assert 'action_label' in params, (
        f"_show_empty_state missing `action_label` — got {sorted(params)}"
    )
    assert 'action_callback' in params, (
        f"_show_empty_state missing `action_callback` — got {sorted(params)}"
    )
    # Both must be optional (default None)
    assert sig.parameters['action_label'].default is None
    assert sig.parameters['action_callback'].default is None


def test_show_empty_state_keeps_kicker_title_detail_kwargs():
    """The pre-existing kwargs must still be there — three scan_mixin call
    sites depend on them (kicker= is passed positionally on some, as a
    kwarg on others)."""
    from unifile.main_window import UniFile
    sig = inspect.signature(UniFile._show_empty_state)
    for required in ('title', 'detail', 'kicker'):
        assert required in sig.parameters, f"lost param `{required}`"


# ── _on_empty_action_clicked dispatch — tested against a SimpleNamespace ───────

def test_empty_action_click_with_no_handler_is_noop():
    """If no handler was stored, clicking the button must not raise."""
    from unifile.main_window import UniFile
    stub = SimpleNamespace(_empty_action_handler=None)
    # Call the unbound method with our stub as `self`.
    UniFile._on_empty_action_clicked(stub)
    # No assertion — success is "didn't raise".


def test_empty_action_click_invokes_handler():
    from unifile.main_window import UniFile
    calls = []
    stub = SimpleNamespace(_empty_action_handler=lambda: calls.append("tick"))
    UniFile._on_empty_action_clicked(stub)
    assert calls == ["tick"]


def test_empty_action_click_swallows_handler_exception():
    """A handler raising shouldn't crash the UI — it should route to _log."""
    from unifile.main_window import UniFile
    logs = []

    def boom():
        raise ValueError("synthetic failure")

    stub = SimpleNamespace(
        _empty_action_handler=boom,
        _log=logs.append,
    )
    # Should not raise
    UniFile._on_empty_action_clicked(stub)
    assert any("synthetic failure" in msg for msg in logs), (
        f"handler error was not logged; got {logs!r}"
    )


# ── scan_mixin call sites still pass the new kwargs in at least one path ───────

def test_scan_mixin_passes_action_kwargs_somewhere():
    """Guards against the 3 recovery-action hooks being deleted during
    unrelated refactors. We read the source file once and require that at
    least one of the empty-state call sites threads `action_callback=`.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "unifile" / "scan_mixin.py").read_text(encoding="utf-8")
    # Expect at least 3 action_callback= occurrences — one per call site.
    occurrences = src.count("action_callback=")
    assert occurrences >= 3, (
        f"scan_mixin.py has only {occurrences} action_callback= sites; "
        "expected >=3 (one per `_show_empty_state` call)."
    )
