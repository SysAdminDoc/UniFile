"""Tests for the customizable sidebar's ordering and collapse state."""

from PyQt6.QtCore import QSettings

from unifile.sidebar import (
    SIDEBAR_SECTION_ORDER,
    SidebarSection,
    SidebarSectionHost,
    load_sidebar_state,
    save_sidebar_state,
)


def test_sidebar_state_round_trips_and_repairs_unknown_order(tmp_path):
    settings = QSettings(str(tmp_path / "sidebar.ini"), QSettings.Format.IniFormat)
    save_sidebar_state(
        settings,
        ["profile", "tools", "tools", "unknown"],
        {"tools": True, "profile": True},
    )

    order, collapsed = load_sidebar_state(settings)
    assert order == ["profile", "tools", "organize", "library", "smart_views"]
    assert collapsed["tools"] is True
    assert collapsed["profile"] is True
    assert collapsed["organize"] is False


def test_sidebar_host_reorders_sections_and_collapses_body(qtbot):
    sections = {
        key: SidebarSection(key, [], "")
        for key in SIDEBAR_SECTION_ORDER
    }
    host = SidebarSectionHost()
    qtbot.addWidget(host)
    host.set_sections(sections, list(SIDEBAR_SECTION_ORDER))

    host.reorder("library", 0)
    assert host.order() == ["library", "organize", "tools", "smart_views", "profile"]
    host.reorder("library", 3)
    assert host.order() == ["organize", "tools", "library", "smart_views", "profile"]

    sections["tools"].set_collapsed(True)
    assert not sections["tools"].header.isChecked()
    assert sections["tools"].body.isHidden()
    sections["tools"].set_collapsed(False)
    assert sections["tools"].header.isChecked()
