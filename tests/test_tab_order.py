"""Source-level regression test for the tab-order / initial-focus pass
landed in v9.3.12.

We don't instantiate the dialogs here — a full Qt widget tree for every
dialog is overkill for a smoke test. Instead we grep the source to
confirm each audited dialog keeps its explicit `setTabOrder` + `setFocus`
calls. If someone rearranges widgets later and the explicit calls get
dropped, this test fires immediately.
"""
from pathlib import Path

import pytest

UNIFILE_ROOT = Path(__file__).resolve().parent.parent / "unifile"


# (file, class-name, required-substrings)
AUDITED = [
    (
        "main_window.py",
        "UniFile",
        [
            "self.setTabOrder(nav_widgets[-1], self.cmb_profile)",
            "self.setTabOrder(self.cmb_profile, self.cmb_archive_mode)",
            "self.setTabOrder(self.cmb_archive_mode, self.txt_src)",
            "self.setTabOrder(self.txt_src, self.btn_scan)",
            "self.setTabOrder(self.sld_conf, self.tbl)",
            "self.tbl.installEventFilter(self)",
            "self._toggle_selected_result_rows()",
        ],
    ),
    (
        "dialogs/tag_library.py",
        "TagLibraryPanel",
        [
            "self.tag_tree = KeyboardTreeWidget()",
            "self.tag_tree.activated.connect",
            "self._quick_tag_buttons = []",
            "self.btn_collections,",
            "self.tbl_entries,",
            "self.cmb_assign_tag,",
        ],
    ),
    (
        "dialogs/virtual_library_panel.py",
        "VirtualLibraryPanel",
        [
            "self.tree = KeyboardTreeWidget()",
            "self.tree.activated.connect(self._on_tree_keyboard_activate)",
            "self.txt_dir,",
            "self.btn_search,",
            "self.tree,",
        ],
    ),
    (
        "dialogs/theme.py",
        "ProtectedPathsDialog",
        [
            "self.setTabOrder(self.chk_enabled, self.list_custom)",
            "self.chk_enabled.setFocus()",
        ],
    ),
    (
        "dialogs/settings.py",
        "PhotoSettingsDialog",
        [
            "self.setTabOrder(self.chk_enabled, self.cmb_preset)",
            "self.chk_enabled.setFocus()",
        ],
    ),
    (
        "dialogs/settings.py",
        "OllamaSettingsDialog",
        [
            "self.setTabOrder(self.txt_url, self.lst_models)",
            "self.txt_url.setFocus()",
        ],
    ),
]


@pytest.mark.parametrize("rel_path,class_name,required", AUDITED,
                         ids=[a[1] for a in AUDITED])
def test_dialog_retains_explicit_tab_order(rel_path, class_name, required):
    src = (UNIFILE_ROOT / rel_path).read_text(encoding="utf-8")
    assert f"class {class_name}" in src, (
        f"{class_name} missing from {rel_path} — did the class get renamed?"
    )
    missing = [line for line in required if line not in src]
    assert not missing, (
        f"{class_name} in {rel_path} lost required tab-order calls:\n  "
        + "\n  ".join(missing)
    )
