"""Undo batch dispatch — extracted from `main_window.py` in v9.3.7.

Extraction criteria (documented in the root CONTINUATION_PROMPT.md):
  * touches few shared widgets (just `self.btn_undo`, `self._log`)
  * operates on a well-defined external state (the undo stack file)
  * was self-contained enough to move without threading concerns

Nothing else in the codebase imports `_on_undo` directly; Qt wires it
through a button click, so this extraction is invisible to callers.
"""
import os
import shutil

from PyQt6.QtWidgets import QDialog

from unifile.cache import _load_undo_stack, _save_undo_stack
from unifile.dialogs import UndoBatchDialog


class UndoMixin:
    """Mixin providing the "Undo last apply" entry point.

    Expected attributes on the composed class:
      - `self.btn_undo`  — QPushButton; re-enabled only if applied batches remain.
      - `self._log(msg)` — status-log sink.
    """

    def _on_undo(self):
        stack = _load_undo_stack()
        if not stack:
            self._log("No operations to undo"); return

        dlg = UndoBatchDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        indices = sorted(dlg.selected_indices, reverse=True)
        ok = err = 0
        for idx in indices:
            if idx >= len(stack):
                continue
            batch = stack[idx]
            if batch.get('status') == 'undone':
                self._log(f"  Skipped (already undone): [{batch.get('timestamp', '?')[:19]}]")
                continue
            ops = batch.get('ops', [])
            self._log(f"Undoing batch [{batch.get('timestamp', '?')[:19]}] ({len(ops)} ops)...")
            for op in reversed(ops):
                src = op.get('src', '')
                dst = op.get('dst', '')
                try:
                    if os.path.exists(src):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.move(src, dst)
                        ok += 1
                        self._log(f"  Restored: {os.path.basename(src)}")
                    else:
                        self._log(f"  Skipped (not found): {src}")
                except Exception as e:
                    err += 1
                    self._log(f"  Error: {e}")
            # Mark as undone (archive instead of delete — preserves history)
            stack[idx]['status'] = 'undone'

        _save_undo_stack(stack)
        applied = any(b.get('status', 'applied') == 'applied' for b in stack)
        self.btn_undo.setEnabled(applied)
        self._log(f"Undo complete: {ok} restored, {err} errors")
