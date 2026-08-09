"""Pointer-free accessibility metadata defaults for Qt control surfaces."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)


def ensure_accessible_metadata(root: QWidget, scope: str) -> None:
    """Fill missing control names/descriptions without replacing authored text."""
    controls = root.findChildren(QWidget)
    counts: dict[str, int] = {}
    for control in controls:
        if not isinstance(control, (
            QAbstractButton,
            QAbstractItemView,
            QAbstractSlider,
            QAbstractSpinBox,
            QComboBox,
            QLineEdit,
            QPlainTextEdit,
            QTextEdit,
        )):
            continue
        if control.accessibleName():
            if not control.accessibleDescription():
                control.setAccessibleDescription(f"{scope} control")
            continue

        if isinstance(control, QAbstractButton):
            label = control.text().strip()
        elif isinstance(control, QLineEdit):
            label = control.placeholderText().strip()
        else:
            label = ""
        label = label or control.objectName().replace("_", " ").strip()
        class_name = type(control).__name__.removesuffix("Widget")
        if not label:
            counts[class_name] = counts.get(class_name, 0) + 1
            label = f"{scope} {class_name} {counts[class_name]}"
        control.setAccessibleName(label)
        if not control.accessibleDescription():
            control.setAccessibleDescription(f"{scope}: {label}")


__all__ = ["ensure_accessible_metadata"]
