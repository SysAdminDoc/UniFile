"""UniFile — pure UI helpers with no `self` or Qt-widget dependencies.

These live outside main_window.py so they're:
  - importable from other dialogs and workers without circular deps
  - unit-testable without instantiating a QMainWindow

Add more here as main_window.py is gradually refactored. The rule is:
a function belongs here iff it has no `self` and no side effects on Qt
widget state. Anything that mutates `self.tbl`, `self.btn_scan`, etc.
stays on UniFile (possibly as a mixin method).
"""
from __future__ import annotations

from PyQt6.QtGui import QColor


def confidence_bg(conf: float, alpha: int = 15) -> QColor:
    """Return a Qt background color for a confidence value in [0, 100].

    Smooth heatmap: red(0) → amber(50) → green(100). Clamps input so callers
    don't have to.
    """
    t = max(0.0, min(100.0, conf)) / 100.0
    if t < 0.5:
        f = t / 0.5
        r, g, b = (
            int(239 + (245 - 239) * f),
            int(68 + (158 - 68) * f),
            int(68 + (11 - 68) * f),
        )
    else:
        f = (t - 0.5) / 0.5
        r, g, b = (
            int(245 + (74 - 245) * f),
            int(158 + (222 - 158) * f),
            int(11 + (128 - 11) * f),
        )
    return QColor(r, g, b, alpha)


def confidence_text_color(conf: float) -> str:
    """Return a hex color string for confidence text (red → amber → green).

    Same gradient as `confidence_bg` but without alpha, suitable for
    stylesheet fragments or `QLabel.setStyleSheet("color: ...")`.
    """
    t = max(0.0, min(100.0, conf)) / 100.0
    if t < 0.5:
        f = t / 0.5
        return (
            f"#{int(239 + (245 - 239) * f):02x}"
            f"{int(68 + (158 - 68) * f):02x}"
            f"{int(68 + (11 - 68) * f):02x}"
        )
    f = (t - 0.5) / 0.5
    return (
        f"#{int(245 + (74 - 245) * f):02x}"
        f"{int(158 + (222 - 158) * f):02x}"
        f"{int(11 + (128 - 11) * f):02x}"
    )


def truncate_middle(text: str, max_length: int = 80, marker: str = "…") -> str:
    """Shorten a long string for label display by replacing the middle with
    the ellipsis marker. Preserves the ends so users can still read filenames
    whose important parts are at the beginning (scheme) or end (filename).

    >>> truncate_middle("C:/very/deep/nested/path/to/some/thing/report.pdf", 24)
    'C:/very/de…g/report.pdf'
    """
    if max_length <= len(marker):
        return text[:max_length]
    if len(text) <= max_length:
        return text
    keep = max_length - len(marker)
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + text[-tail:]
