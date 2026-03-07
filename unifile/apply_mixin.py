"""Apply logic mixin for UniFile main window."""
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor

from unifile.cache import (
    create_backup_snapshot, save_undo_log, append_csv_log
)
from unifile.workers import ApplyAepWorker, ApplyCatWorker, ApplyFilesWorker


class ApplyMixin:
    """Mixin containing all apply-related methods for UniFile."""

    # ═══ APPLY DISPATCHER ════════════════════════════════════════════════════

    def _on_apply(self):
        op = self.cmb_op.currentIndex()
        if op in (self.OP_CAT, self.OP_SMART):
            self._apply_cat()
        elif op == self.OP_FILES:
            self._apply_files()
        else:
            self._apply_aep()

    # ═══ AEP APPLY ═══════════════════════════════════════════════════════════

    def _apply_aep(self, dry_run=False):
        work = [(i,it) for i,it in enumerate(self.aep_items) if it.selected and it.status=="Pending"]
        if not work: self._log("No items selected"); return
        if not dry_run:
            snap = create_backup_snapshot(self.txt_src.text(), [it for _,it in work])
            if snap: self._log(f"Backup snapshot saved: {snap}")
        self.btn_apply.setEnabled(False); self.cmb_op.setEnabled(False)
        self.btn_scan.setText("Cancel"); self.btn_scan.setStyleSheet("QPushButton { color: #ef4444; font-weight: bold; }")
        label = "Dry Run" if dry_run else "Renaming"
        self._log(f"{'Simulating' if dry_run else 'Renaming'} {len(work)} folders...")
        self._scan_start_time = time.time()
        self.lbl_prog_phase.setText(label)
        self.lbl_prog_method.setText("Simulating AEP renames…" if dry_run else "Applying AEP renames to disk…")
        self.pbar.setValue(0); self.prog_panel.setVisible(True)
        self.apply_worker = ApplyAepWorker(work, check_hashes=self.chk_hash.isChecked(), dry_run=dry_run)
        self.apply_worker.log.connect(self._log)
        self.apply_worker.progress.connect(self._update_progress)
        self.apply_worker.item_done.connect(self._on_aep_item_done)
        self.apply_worker.finished.connect(
            lambda ok, err, ops: self._on_aep_apply_done(ok, err, ops, dry_run))
        self.apply_worker.start()

    def _on_aep_item_done(self, row_idx, status):
        it = self.aep_items[row_idx]
        it.status = status
        vr = self._visual_row_for_idx(row_idx)
        if status == "Done":
            if vr >= 0:
                QTimer.singleShot(350, lambda r=vr: self.tbl.setRowHidden(r, True))
        else:
            if vr >= 0:
                self._set_status(vr, status, "#ef4444", 6)
                self.tbl.scrollToItem(self.tbl.item(vr, 1))

    def _on_aep_apply_done(self, ok, err, undo_ops, dry_run=False):
        self.btn_scan.setText("Scan"); self.btn_scan.setStyleSheet("")
        self.btn_scan.setEnabled(True); self.cmb_op.setEnabled(True); self._stats_aep()
        remaining = sum(1 for it in self.aep_items if it.status == "Pending" and it.selected)
        self.btn_apply.setEnabled(remaining > 0)
        self.prog_panel.setVisible(False)
        verb = "simulated" if dry_run else "renamed"
        msg = f"{'Dry run' if dry_run else 'Complete'}: {ok} {verb}, {err} errors"
        self._log(msg); self.lbl_statusbar.setText(msg)
        if undo_ops and not dry_run:
            save_undo_log(undo_ops); self.undo_ops = undo_ops; self.btn_undo.setEnabled(True)
            append_csv_log(undo_ops)
            self._log(f"Undo log and CSV log saved")

    # ═══ CATEGORY APPLY ══════════════════════════════════════════════════════

    def _apply_cat(self):
        work = [(i,it) for i,it in enumerate(self.cat_items) if it.selected and it.status=="Pending"]
        if not work: self._log("No items selected"); return
        snap = create_backup_snapshot(self.txt_src.text(), [it for _,it in work])
        if snap: self._log(f"Backup snapshot saved: {snap}")
        self.btn_apply.setEnabled(False); self.cmb_op.setEnabled(False)
        self.btn_scan.setText("Cancel"); self.btn_scan.setStyleSheet("QPushButton { color: #ef4444; font-weight: bold; }")
        self._log(f"Moving {len(work)} folders...")
        self._scan_start_time = time.time()
        self.lbl_prog_phase.setText("Moving")
        self.lbl_prog_method.setText("Moving folders to destination…")
        self.pbar.setValue(0); self.prog_panel.setVisible(True)
        self.apply_worker = ApplyCatWorker(work, check_hashes=self.chk_hash.isChecked())
        self.apply_worker.log.connect(self._log)
        self.apply_worker.progress.connect(self._update_progress)
        self.apply_worker.item_done.connect(self._on_cat_item_done)
        self.apply_worker.finished.connect(self._on_cat_apply_done)
        self.apply_worker.start()

    def _on_cat_item_done(self, row_idx, status):
        it = self.cat_items[row_idx]
        it.status = status
        vr = self._visual_row_for_idx(row_idx)
        if status == "Done":
            if vr >= 0:
                QTimer.singleShot(350, lambda r=vr: self.tbl.setRowHidden(r, True))
        else:
            if vr >= 0:
                self._set_status(vr, status, "#ef4444", 6)
                self.tbl.scrollToItem(self.tbl.item(vr, 1))

    def _on_cat_apply_done(self, ok, err, undo_ops):
        self.btn_scan.setText("Scan"); self.btn_scan.setStyleSheet("")
        self.btn_scan.setEnabled(True); self.cmb_op.setEnabled(True); self._stats_cat()
        remaining = sum(1 for it in self.cat_items if it.status == "Pending" and it.selected)
        self.btn_apply.setEnabled(remaining > 0)
        self.prog_panel.setVisible(False)
        msg = f"Complete: {ok} moved, {err} errors"
        self._log(msg); self.lbl_statusbar.setText(msg)
        if undo_ops:
            save_undo_log(undo_ops); self.undo_ops = undo_ops; self.btn_undo.setEnabled(True)
            append_csv_log(undo_ops)
            self._log(f"Undo log and CSV log saved")

    # ═══ PC FILES APPLY ══════════════════════════════════════════════════════

    def _apply_files(self, dry_run=False):
        work = [(i, it) for i, it in enumerate(self.file_items)
                if it.selected and it.status == "Pending"]
        if not work:
            self._log("No items selected"); return
        label = "Dry Run" if dry_run else "Moving"
        self.btn_apply.setEnabled(False); self.cmb_op.setEnabled(False)
        self.btn_scan.setText("Cancel"); self.btn_scan.setStyleSheet("QPushButton { color: #ef4444; font-weight: bold; }")
        self._log(f"{label}: {len(work)} items…")
        self._scan_start_time = time.time()
        self.lbl_prog_phase.setText(label)
        self.lbl_prog_method.setText("Moving files to destination…" if not dry_run
                                      else "Simulating moves (no files changed)…")
        self.pbar.setValue(0); self.prog_panel.setVisible(True)
        self.apply_worker = ApplyFilesWorker(
            work, check_hashes=self.chk_hash.isChecked(), dry_run=dry_run)
        self.apply_worker.log.connect(self._log)
        self.apply_worker.progress.connect(self._update_progress)
        self.apply_worker.item_done.connect(self._on_files_item_done)
        self.apply_worker.finished.connect(
            lambda ok, err, ops: self._on_files_apply_done(ok, err, ops, dry_run))
        self.apply_worker.start()

    def _on_files_item_done(self, list_idx: int, status: str):
        it = self.file_items[list_idx]
        it.status = status
        vr = self._visual_row_for_idx(list_idx)
        if status == "Done":
            if vr >= 0:
                QTimer.singleShot(350, lambda r=vr: self.tbl.setRowHidden(r, True))
        else:
            if vr >= 0:
                si = self.tbl.item(vr, 10)   # Status col
                if si:
                    si.setText(status); si.setForeground(QColor("#ef4444"))

    def _on_files_apply_done(self, ok: int, err: int, undo_ops: list, dry_run: bool):
        self.btn_scan.setText("Scan"); self.btn_scan.setStyleSheet("")
        self.btn_scan.setEnabled(True); self.cmb_op.setEnabled(True)
        remaining = sum(1 for it in self.file_items if it.status == "Pending" and it.selected)
        self.btn_apply.setEnabled(remaining > 0)
        self.prog_panel.setVisible(False)
        verb = "simulated" if dry_run else "moved"
        msg = f"{'Dry run' if dry_run else 'Complete'}: {ok} {verb}, {err} errors"
        self._log(msg); self.lbl_statusbar.setText(msg)
        self._stats_files()
        if undo_ops and not dry_run:
            save_undo_log(undo_ops); self.undo_ops = undo_ops; self.btn_undo.setEnabled(True)
            append_csv_log(undo_ops)
            self._log("Undo log saved")
