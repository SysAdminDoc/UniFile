"""Search / face / confidence filter slots — extracted from `main_window.py`
in v9.3.9.

Three tightly-coupled methods moved here together because they all touch
the same filter widgets (`txt_search`, `cmb_face_filter`, `sld_conf`) and
the same result tables (`tbl`, `file_items`, `cat_items`).
"""
from PyQt6.QtWidgets import QCheckBox


class FilterMixin:
    """Mixin providing search / face / confidence filter behavior.

    Expected attributes (all owned by UniFile via `_build_ui`):
      - `self.tbl`, `self.file_items`, `self.cat_items`
      - `self.txt_search`, `self.cmb_face_filter`, `self.cmb_op`
      - `self.lbl_conf`
      - `self.OP_FILES`, `self.OP_CAT`, `self.OP_SMART` (class constants)

    Expected methods on the composed class:
      - `self._items() -> list`
      - `self._item_idx_from_row(row) -> int`
      - `self._upd_stats()`
    """

    def _populate_face_filter(self):
        """Populate the face filter dropdown from scanned file metadata."""
        self.cmb_face_filter.blockSignals(True)
        self.cmb_face_filter.clear()
        self.cmb_face_filter.addItem("All Persons")
        persons = set()
        for it in self.file_items:
            for p in it.metadata.get('_photo_face_persons', []):
                persons.add(p)
        for p in sorted(persons):
            self.cmb_face_filter.addItem(p)
        self.cmb_face_filter.blockSignals(False)
        # Show only in files mode when faces were detected
        self.cmb_face_filter.setVisible(
            self.cmb_op.currentIndex() == self.OP_FILES and len(persons) > 0)

    def _apply_filter(self):
        from unifile.search_parser import parse_query, item_matches
        raw = self.txt_search.text()
        face = self.cmb_face_filter.currentText() if self.cmb_face_filter.isVisible() else "All Persons"
        spec = parse_query(raw)
        all_items = self._items()

        for row in range(self.tbl.rowCount()):
            show = True
            if raw.strip():
                if spec.is_chainable:
                    # Structured token match against the item object
                    idx = self._item_idx_from_row(row)
                    if idx is not None and 0 <= idx < len(all_items):
                        show = item_matches(spec, all_items[idx])
                    else:
                        # Fallback: plain substring scan across cell text
                        tl = spec.text
                        show = False
                        for col in range(self.tbl.columnCount()):
                            cell = self.tbl.item(row, col)
                            if cell and tl in cell.text().lower():
                                show = True
                                break
                else:
                    tl = spec.text  # already lower-cased
                    show = False
                    for col in range(self.tbl.columnCount()):
                        cell = self.tbl.item(row, col)
                        if cell and tl in cell.text().lower():
                            show = True
                            break

            # Face filter (PC Files mode only)
            if show and face != "All Persons" and self.cmb_op.currentIndex() == self.OP_FILES:
                idx = self._item_idx_from_row(row)
                if idx is not None and 0 <= idx < len(self.file_items):
                    persons = self.file_items[idx].metadata.get('_photo_face_persons', [])
                    if face not in persons:
                        show = False

            self.tbl.setRowHidden(row, not show)

    def _on_conf_changed(self, val):
        self.lbl_conf.setText(f"{val}%")
        op = self.cmb_op.currentIndex()
        if op in (self.OP_CAT, self.OP_SMART):
            items = self.cat_items
        elif op == self.OP_FILES:
            items = [it for it in self.file_items if not it.is_duplicate]
        else:
            return
        # Build reverse map: item list index → visual row (sort-safe)
        all_items = self._items()
        visual_map = {}
        for r in range(self.tbl.rowCount()):
            visual_map[self._item_idx_from_row(r)] = r
        # Auto-deselect items below threshold
        for it in items:
            should_select = it.confidence >= val
            if it.selected != should_select:
                it.selected = should_select
                # Find the item's list index
                try:
                    list_idx = all_items.index(it)
                except ValueError:
                    continue
                visual_row = visual_map.get(list_idx)
                if visual_row is not None:
                    cb = self.tbl.cellWidget(visual_row, 0)
                    if cb:
                        cb_inner = cb.findChild(QCheckBox)
                        if cb_inner:
                            cb_inner.blockSignals(True)
                            cb_inner.setChecked(should_select)
                            cb_inner.blockSignals(False)
        self._upd_stats()
