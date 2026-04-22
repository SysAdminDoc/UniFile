"""Shared dialog UI helpers."""

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout


def build_dialog_header(t: dict, kicker: str, title: str, description: str) -> QFrame:
    """Create a consistent dialog header card used across settings and tools."""
    frame = QFrame()
    frame.setProperty("class", "card")
    frame.setStyleSheet(
        f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
        f"border-radius: 16px; }}"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(4)

    lbl_kicker = QLabel(kicker.upper())
    lbl_kicker.setStyleSheet(
        f"color: {t['accent']}; font-size: 10px; font-weight: 700; letter-spacing: 1.6px;"
    )
    layout.addWidget(lbl_kicker)

    lbl_title = QLabel(title)
    lbl_title.setStyleSheet(f"color: {t['fg_bright']}; font-size: 21px; font-weight: 700;")
    layout.addWidget(lbl_title)

    lbl_desc = QLabel(description)
    lbl_desc.setWordWrap(True)
    lbl_desc.setStyleSheet(f"color: {t['muted']}; font-size: 12px; line-height: 1.4;")
    layout.addWidget(lbl_desc)
    return frame
