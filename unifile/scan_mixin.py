"""Scan logic mixin for UniFile main window."""
import json
import os
import re
import time
from collections import Counter

from PyQt6.QtCore import QTimer

from unifile.bootstrap import HAS_MAGIC, HAS_RAPIDFUZZ
from unifile.cache import compute_file_fingerprint
from unifile.categories import is_generic_aep
from unifile.classifier import _SCAN_FILTERS
from unifile.config import _LAST_CONFIG_FILE
from unifile.duplicates import ConflictResolver
from unifile.engine import CategoryBalancer, RenameTemplateEngine
from unifile.metadata import MetadataExtractor
from unifile.models import CategorizeItem, FileItem, RenameItem
from unifile.naming import _beautify_name, _extract_name_hints, _smart_name
from unifile.photos import _PHOTO_FOLDER_PRESETS, load_photo_settings
from unifile.plugins import PluginManager
from unifile.workers import (
    ScanAepWorker,
    ScanCategoryWorker,
    ScanFilesLLMWorker,
    ScanFilesWorker,
    ScanLLMWorker,
    format_size,
)


class ScanMixin:
    """Mixin containing all scan-related methods for UniFile."""

    # ═══ LAST CONFIG SAVE / REPLAY ═══════════════════════════════════════════

    def _save_last_config(self):
        """Save current scan config for Repeat Last."""
        op = self.cmb_op.currentIndex()
        cfg = {
            'mode': op,
            'src': self.txt_src.text() if op != self.OP_FILES else self._pc_src_path(),
            'dst': self.txt_dst.text() if op in (self.OP_CAT, self.OP_SMART) else '',
            'llm': self.chk_llm.isChecked(),
            'dedup': self.chk_hash.isChecked(),
            'depth': self.spn_depth.value(),
            'pc_src_preset': self.cmb_pc_src.currentIndex() if op == self.OP_FILES else 0,
            'inc_files': self.chk_inc_files.isChecked(),
            'inc_folders': self.chk_inc_folders.isChecked(),
            'type_filter': self.cmb_type_filter.currentText(),
        }
        try:
            with open(_LAST_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
            self.btn_replay.setEnabled(True)
        except Exception:
            pass

    def _replay_last_config(self):
        """Load last scan config and auto-start scan."""
        try:
            with open(_LAST_CONFIG_FILE, encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception:
            self._log("No saved scan config found"); return
        op = cfg.get('mode', 0)
        self.cmb_op.setCurrentIndex(op)
        if op == self.OP_FILES:
            idx = cfg.get('pc_src_preset', 0)
            if 0 <= idx < self.cmb_pc_src.count():
                self.cmb_pc_src.setCurrentIndex(idx)
            src = cfg.get('src', '')
            if src and hasattr(self, 'txt_pc_src'):
                self.txt_pc_src.setText(src)
            self.chk_inc_files.setChecked(cfg.get('inc_files', True))
            self.chk_inc_folders.setChecked(cfg.get('inc_folders', False))
            tf = cfg.get('type_filter', 'All Files')
            idx_tf = self.cmb_type_filter.findText(tf)
            if idx_tf >= 0:
                self.cmb_type_filter.setCurrentIndex(idx_tf)
        else:
            self.txt_src.setText(cfg.get('src', ''))
            if op in (self.OP_CAT, self.OP_SMART):
                self.txt_dst.setText(cfg.get('dst', ''))
        self.chk_llm.setChecked(cfg.get('llm', False))
        self.chk_hash.setChecked(cfg.get('dedup', False))
        self.spn_depth.setValue(cfg.get('depth', 0))
        self._log("Replaying last scan config...")
        QTimer.singleShot(100, self._on_scan)

    # ═══ SCAN DISPATCHER ═════════════════════════════════════════════════════

    def _on_scan(self):
        # If an apply worker is running, cancel it
        if hasattr(self, 'apply_worker') and self.apply_worker and self.apply_worker.isRunning():
            self.apply_worker.cancel()
            self._log("Cancelling apply...")
            return
        # If already scanning, cancel
        if getattr(self, '_scanning', False):
            self._cancel_scan()
            return

        op = self.cmb_op.currentIndex()
        self._save_last_config()

        # In PC Files mode, source comes from the PC panel, not txt_src
        if op == self.OP_FILES:
            src = self._pc_src_path()
            if not src or not os.path.isdir(src):
                self._log("Select a valid source location first"); return
            self._hide_empty_state(); self.tbl.setRowCount(0)
            self._scanning = True
            self.tbl.setSortingEnabled(False)
            self.btn_scan.setText("Cancel Scan"); self.btn_scan.setStyleSheet("QPushButton { color: #ef4444; font-weight: bold; }")
            self.btn_apply.setEnabled(False); self.btn_preview.setEnabled(False); self.btn_export.setEnabled(False); self.btn_export_html.setEnabled(False)
            self._scan_start_time = time.time()
            self._scan_files(src)
            return

        src = self.txt_src.text()
        if not src or not os.path.isdir(src):
            self._log("Invalid source directory"); return
        self._hide_empty_state(); self.tbl.setRowCount(0)
        self._scanning = True
        self.tbl.setSortingEnabled(False)
        self.btn_scan.setText("Cancel Scan"); self.btn_scan.setStyleSheet("QPushButton { color: #ef4444; font-weight: bold; }")
        self.btn_apply.setEnabled(False); self.btn_preview.setEnabled(False); self.btn_export.setEnabled(False)
        self._scan_start_time = time.time()
        if op in (self.OP_CAT, self.OP_SMART):
            dst = self.txt_dst.text()
            if not dst:
                self._log("Set output directory first")
                self._reset_scan_ui(); return
            # Validate source/destination don't overlap
            src_real = os.path.realpath(src)
            dst_real = os.path.realpath(dst)
            if src_real == dst_real:
                self._log("ERROR: Source and destination are the same directory")
                self._reset_scan_ui(); return
            if dst_real.startswith(src_real + os.sep):
                self._log("ERROR: Destination is inside the source directory — this would cause recursive moves")
                self._reset_scan_ui(); return
            if src_real.startswith(dst_real + os.sep):
                self._log("WARNING: Source is inside the destination — results may be unexpected")
            self._scan_cat(src, dst)
        else:
            self._scan_aep(src)

    def _cancel_scan(self):
        """Signal the worker to stop."""
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            self.worker.cancel()
            self._log("Cancelling scan...")

    def _disconnect_worker(self):
        """Disconnect signals from the previous worker to prevent ghost callbacks."""
        if hasattr(self, 'worker') and self.worker:
            try: self.worker.disconnect()
            except (TypeError, RuntimeError): pass
            self.worker = None

    def _reset_scan_ui(self):
        """Restore Scan button and state after scan completes or is cancelled."""
        self._scanning = False
        self._refresh_workspace_copy()
        self.btn_scan.setStyleSheet("")
        self.btn_scan.setEnabled(True)
        self.prog_panel.setVisible(False)
        self.lbl_statusbar.setText("Ready")
        # Re-enable Apply if there are already pending results (e.g. after cancel)
        op = self.cmb_op.currentIndex()
        if op in (self.OP_CAT, self.OP_SMART):
            pending = sum(1 for it in self.cat_items if it.selected and it.status == "Pending")
        elif op == self.OP_FILES:
            pending = sum(1 for it in self.file_items if it.selected and it.status == "Pending")
        else:
            pending = sum(1 for it in self.aep_items if it.selected and it.status == "Pending")
        self.btn_apply.setEnabled(pending > 0)

    # Throttle for per-file status label updates so we don't spam the UI thread
    # when scanning tens of thousands of files. 100 ms is the empirical sweet
    # spot — short enough to feel live, long enough to avoid repaint thrash.
    _CURRENT_ITEM_UPDATE_MS = 100

    def _update_progress(self, current, total):
        """Update premium progress bar with ETA and speed."""
        self.prog_panel.setVisible(True)
        if total <= 0:
            return
        self.pbar.setMaximum(total)
        self.pbar.setValue(current)
        self.lbl_prog_counter.setText(f"{current:,} / {total:,}")

        if current == 0:
            self.lbl_prog_eta.setText("")
            self.lbl_prog_speed.setText("")
            return

        elapsed = time.time() - getattr(self, '_scan_start_time', time.time())
        if current > 2 and elapsed > 0.5:
            rate = current / elapsed
            remaining = (total - current) / rate
            if remaining >= 60:
                eta = f"~{remaining/60:.0f}m remaining"
            else:
                eta = f"~{remaining:.0f}s remaining"
            self.lbl_prog_eta.setText(eta)
            self.lbl_prog_speed.setText(f"{rate:.1f} folders/s")
        else:
            self.lbl_prog_eta.setText("")
            self.lbl_prog_speed.setText("")

        pct = int(current / total * 100)
        self.lbl_statusbar.setText(f"{self.lbl_prog_phase.text()}… {pct}%  ({current:,}/{total:,})")

    def _set_current_scan_item(self, name: str) -> None:
        """Surface the currently-processed file/folder name on the progress
        label, throttled so streams of thousands of items don't freeze the UI.

        Safe to call from the main thread only. Workers should emit a signal
        connected to this slot.
        """
        now_ms = int(time.time() * 1000)
        last = getattr(self, '_last_current_item_ms', 0)
        if now_ms - last < self._CURRENT_ITEM_UPDATE_MS:
            return
        self._last_current_item_ms = now_ms
        # Only update if the progress panel is visible (i.e. an active scan)
        if not getattr(self, 'prog_panel', None) or not self.prog_panel.isVisible():
            return
        method_lbl = getattr(self, 'lbl_prog_method', None)
        if method_lbl is None:
            return
        # Truncate to avoid layout thrash with very long paths
        shown = name if len(name) <= 80 else '…' + name[-77:]
        method_lbl.setText(f"Processing: {shown}")

    # ═══ AEP SCAN ════════════════════════════════════════════════════════════

    def _scan_aep(self, src):
        self._disconnect_worker()
        self._log(f"Scanning for .aep files in: {src}")
        self.aep_items.clear(); self.tbl.setRowCount(0)
        self._aep_dest_paths = {}  # collision tracking for AEP renames
        self.lbl_prog_phase.setText("AEP Scan")
        self.lbl_prog_method.setText("Locating After Effects project files…")
        self.pbar.setValue(0); self.prog_panel.setVisible(True)
        self.worker = ScanAepWorker(src, scan_depth=self.spn_depth.value())
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._update_progress)
        if hasattr(self.worker, 'current_item'):
            self.worker.current_item.connect(self._set_current_scan_item)
        self.worker.result_ready.connect(self._on_aep_result)
        self.worker.finished.connect(self._on_aep_scan_done)
        self.worker.start()

    def _deduplicate_aep_path(self, dest_path):
        """Auto-suffix AEP rename paths that collide."""
        key = dest_path.lower()
        if key not in self._aep_dest_paths and not os.path.exists(dest_path):
            self._aep_dest_paths[key] = 1
            return dest_path

        parent = os.path.dirname(dest_path)
        base = os.path.basename(dest_path)
        n = self._aep_dest_paths.get(key, 1) + 1
        for _ in range(10000):
            new_name = f"{base} ({n})"
            new_path = os.path.join(parent, new_name)
            new_key = new_path.lower()
            if new_key not in self._aep_dest_paths and not os.path.exists(new_path):
                self._aep_dest_paths[key] = n
                self._aep_dest_paths[new_key] = 1
                return new_path
            n += 1
        return os.path.join(parent, f"{base} ({n})")  # safety fallback

    def _on_aep_result(self, r):
        """Process a single AEP scan result live."""
        if not r['largest_aep']: return
        aep_stem = os.path.splitext(r['largest_aep'])[0]
        if is_generic_aep(aep_stem): return
        new_name = f"{r['folder_name']} - {aep_stem}"
        if r['folder_name'] in new_name and aep_stem in r['folder_name']: return
        it = RenameItem(); it.current_name = r['folder_name']; it.new_name = new_name
        it.aep_file = r.get('aep_rel_path', r['largest_aep'])
        it.file_size = format_size(r['aep_size'])
        it.file_size_bytes = r['aep_size']
        it.full_current_path = r['folder_path']
        raw_path = os.path.join(os.path.dirname(r['folder_path']), new_name)
        it.full_new_path = self._deduplicate_aep_path(raw_path)
        # Update display name if deduped
        deduped_name = os.path.basename(it.full_new_path)
        if deduped_name != new_name:
            it.new_name = deduped_name
        it.status = "Pending"; it.selected = True
        self.aep_items.append(it); self._add_aep_row(it, len(self.aep_items)-1)

    def _on_aep_scan_done(self):
        """Finalize after AEP scan completes."""
        self._reset_scan_ui()
        self.tbl.setSortingEnabled(True)
        shown = len(self.aep_items)
        self.btn_apply.setEnabled(shown > 0)
        self.btn_export.setEnabled(shown > 0)
        self.btn_export_html.setEnabled(shown > 0)
        # Hide v7 buttons not applicable to AEP mode
        self.btn_graph_toggle.setVisible(False)
        self.btn_preview_toggle.setVisible(False)
        self.btn_before_after.setVisible(False)
        self.btn_events.setVisible(False)
        self._stats_aep()
        self._log(f"Scan complete: {shown} eligible folders found")
        if shown > 0:
            self._show_scan_toast(f"Scan complete: {shown} folders found")
        if shown == 0:
            depth = self.spn_depth.value() if hasattr(self, 'spn_depth') else 0
            action_label = None
            action_cb = None
            if depth > 0:
                action_label = f"Reset scan depth ({depth} → 0)"
                def _reset_depth():
                    self.spn_depth.setValue(0)
                action_cb = _reset_depth
            self._show_empty_state(
                "No eligible folders found",
                "Try a different source folder or lower the scan depth if your projects are nested more deeply.",
                kicker="NOTHING TO RENAME",
                action_label=action_label, action_callback=action_cb,
            )

    # ═══ CATEGORY SCAN ═══════════════════════════════════════════════════════

    def _scan_cat(self, src, dst):
        self._disconnect_worker()
        self._log(f"Scanning & categorizing: {src}")
        self.cat_items.clear(); self.tbl.setRowCount(0)
        self._cat_unmatched = 0
        self._cat_context_count = 0
        self._cat_llm_renamed = 0
        self._cat_method_counts = Counter()
        self._cat_dest_paths = {}  # dest_path_lower -> count for collision detection
        self._cat_fingerprints = {}  # file_fingerprint -> first folder_name for duplicate detection
        depth = self.spn_depth.value()

        op = self.cmb_op.currentIndex()
        if self.chk_llm.isChecked():
            self._log("  Mode: LLM-powered (all folders processed through Ollama)")
            self.worker = ScanLLMWorker(src, dst, scan_depth=depth)
            self.lbl_prog_phase.setText("AI Classify")
            self.lbl_prog_method.setText("Classifying via Ollama LLM…")
        else:
            self.worker = ScanCategoryWorker(src, dst, scan_depth=depth)
            if op == self.OP_SMART:
                self._log("  Mode: Categorize + Smart Rename from project files")
                self.lbl_prog_phase.setText("Smart Scan")
                self.lbl_prog_method.setText("Categorizing + extracting names from project files…")
            else:
                self.lbl_prog_phase.setText("Categorizing")
                self.lbl_prog_method.setText("Rule-based classification…")

        self.pbar.setValue(0); self.prog_panel.setVisible(True)
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._update_progress)
        self.worker.phase.connect(self._update_phase)
        if hasattr(self.worker, 'current_item'):
            self.worker.current_item.connect(self._set_current_scan_item)
        self.worker.result_ready.connect(self._on_cat_result)
        self.worker.finished.connect(self._on_cat_scan_done)
        self.worker.start()

    def _deduplicate_dest_path(self, dest_path):
        """If dest_path already claimed by another item (or exists on disk),
        append (2), (3), etc. to the folder name to avoid collisions."""
        key = dest_path.lower()
        if key not in self._cat_dest_paths and not os.path.exists(dest_path):
            self._cat_dest_paths[key] = 1
            return dest_path

        parent = os.path.dirname(dest_path)
        base = os.path.basename(dest_path)
        n = self._cat_dest_paths.get(key, 1) + 1
        for _ in range(10000):
            new_name = f"{base} ({n})"
            new_path = os.path.join(parent, new_name)
            new_key = new_path.lower()
            if new_key not in self._cat_dest_paths and not os.path.exists(new_path):
                self._cat_dest_paths[key] = n
                self._cat_dest_paths[new_key] = 1
                return new_path
            n += 1
        return os.path.join(parent, f"{base} ({n})")  # safety fallback

    def _on_cat_result(self, r):
        """Process a single categorization result live into the table."""
        dst = self.txt_dst.text()
        thresh = self.sld_conf.value()

        if not r['category']:
            self._cat_unmatched += 1
            # Show uncategorized folders in the table
            it = CategorizeItem(); it.folder_name = r['folder_name']; it.category = '[Uncategorized]'
            it.cleaned_name = r.get('cleaned_name', r['folder_name'])
            it.confidence = 0; it.full_source_path = r['folder_path']
            it.full_dest_path = ''
            it.method = ''; it.detail = 'No classification match'; it.topic = ''
            it.status = "Skip"; it.selected = False
            self.cat_items.append(it); self._add_cat_row(it, len(self.cat_items)-1)
            self._stats_cat()
            return

        it = CategorizeItem(); it.folder_name = r['folder_name']; it.category = r['category']
        it.cleaned_name = r.get('cleaned_name', r['folder_name'])
        it.confidence = r['confidence']; it.full_source_path = r['folder_path']

        # Use LLM-cleaned name for dest path if available (rename-on-move)
        llm_name = r.get('llm_name')
        op = self.cmb_op.currentIndex()
        if llm_name and llm_name != r['folder_name']:
            dest_folder_name = llm_name
        elif op == self.OP_SMART:
            # Smart mode: always look inside the folder for the best project-file name.
            # This ignores the folder name entirely and derives the name from .aep/.psd/etc.
            hints = _extract_name_hints(r.get('folder_path', ''))
            if hints:
                best_name, _src, _pri = hints[0]
                dest_folder_name = _beautify_name(best_name)
            else:
                # No project files found — fall back to smart_name (still better than raw folder name)
                dest_folder_name = _smart_name(r['folder_name'], r.get('folder_path'), r.get('category'))
        else:
            # Normal Categorize mode: smart naming only improves ID-only / noisy names
            dest_folder_name = _smart_name(r['folder_name'], r.get('folder_path'), r.get('category'))

        # ── Preserve distinguishing suffix from original folder name ──────────
        # If the cleaned name is shorter than the original, the original may have
        # a meaningful suffix (version, range, number) that was stripped.
        # Extract it and append so collisions become e.g. "Resume CV Template v03"
        # instead of "Resume CV Template (51)".
        orig = r['folder_name']
        if dest_folder_name and orig and dest_folder_name.lower() != orig.lower():
            # Find what was stripped from the end of the original
            orig_norm = re.sub(r'(?i)(graphicriver|videohive|cm_?|vh[-_]?|gr[-_]?|ah[-_]?)'
                               r'[-_\s]*\d+[-_\s]*', '', orig).strip()
            orig_norm = re.sub(r'^\d{5,}[-_\s]*', '', orig_norm).strip()
            # Extract trailing version/number/range suffix not in cleaned name
            suffix_match = re.search(
                r'[-_\s]+(v\s*\d[\d.]*'          # v03, v1.2
                r'|#?\d{1,4}'                      # -93, #7
                r'|\d{1,4}\s*[-\u2013]\s*\d{1,4}'      # 93-96, 97-100
                r'|pack\s*\d+'                     # pack 2
                r'|\bset\s*\d+'                    # set 3
                r'|\bvol\s*\d+)$',
                orig_norm, re.IGNORECASE
            )
            if suffix_match:
                raw_suffix = suffix_match.group(0).strip().strip('-_')
                # Only append if not already present in dest name
                if raw_suffix.lower() not in dest_folder_name.lower():
                    dest_folder_name = f"{dest_folder_name} {raw_suffix}"

        raw_dest = os.path.join(dst, r['category'], dest_folder_name)
        it.full_dest_path = self._deduplicate_dest_path(raw_dest)

        it.method = r.get('method', ''); it.detail = r.get('detail', '')
        it.topic = r.get('topic', '') or ''
        it.status = "Pending"
        it.selected = it.confidence >= thresh

        if it.topic:
            self._cat_context_count += 1
        if llm_name and llm_name != r['folder_name']:
            self._cat_llm_renamed += 1
        self._cat_method_counts[it.method or 'unknown'] += 1

        # Duplicate detection
        fp = compute_file_fingerprint(r['folder_path'])
        if fp and fp in self._cat_fingerprints:
            it.detail = f"Possible duplicate of: {self._cat_fingerprints[fp]}"
        elif fp:
            self._cat_fingerprints[fp] = r['folder_name']

        self.cat_items.append(it); self._add_cat_row(it, len(self.cat_items)-1)
        self._stats_cat()

    def _on_cat_scan_done(self):
        """Finalize after category scan completes."""
        self._reset_scan_ui()
        self.tbl.setSortingEnabled(True)
        matched = len(self.cat_items)
        self.btn_apply.setEnabled(matched > 0)
        self.btn_preview.setEnabled(matched > 0)
        self.btn_export.setEnabled(len(self.cat_items) > 0)
        self.btn_export_html.setEnabled(len(self.cat_items) > 0)
        # Auto-tag entries in tag library if open
        self._auto_tag_scan_results()
        # Hide v7 buttons not applicable to Cat mode
        self.btn_graph_toggle.setVisible(False)
        self.btn_preview_toggle.setVisible(False)
        self.btn_events.setVisible(False)
        self._stats_cat()
        methods_str = ', '.join(f"{k}:{v}" for k, v in self._cat_method_counts.most_common())
        self._log(f"Categorization complete: {matched} matched, {self._cat_unmatched} uncategorized")
        if methods_str:
            self._log(f"  Methods used: {methods_str}")
        if self._cat_context_count:
            self._log(f"  Context overrides: {self._cat_context_count} (topic → asset type)")
        if self._cat_llm_renamed:
            self._log(f"  LLM renamed: {self._cat_llm_renamed} folders will be renamed on move")
        if matched > 0:
            self._show_scan_toast(f"Scan complete: {matched} folders categorized")
            self._update_dashboard()
            # Category balancing — suggest merges/splits for imbalanced categories
            self._run_category_balancer('cat')
        if matched == 0:
            # Prefer lowering the confidence filter first (cheapest recovery);
            # fall back to offering AI toggle if the filter was already at 0.
            conf_threshold = self.sld_conf.value() if hasattr(self, 'sld_conf') else 0
            llm_on = self.chk_llm.isChecked() if hasattr(self, 'chk_llm') else False
            action_label = None
            action_cb = None
            if conf_threshold > 0:
                action_label = f"Lower confidence filter ({conf_threshold}% → 0%)"
                def _lower_conf():
                    self.sld_conf.setValue(0)
                action_cb = _lower_conf
            elif not llm_on and hasattr(self, 'chk_llm'):
                action_label = "Enable AI mode for next scan"
                def _enable_llm():
                    self.chk_llm.setChecked(True)
                action_cb = _enable_llm
            self._show_empty_state(
                "No folders could be categorized",
                "Try enabling AI, lowering the confidence filter, or choosing a source with clearer folder contents.",
                kicker="NO MATCHES FOUND",
                action_label=action_label, action_callback=action_cb,
            )

    # ═══ PC FILE SCAN ════════════════════════════════════════════════════════

    def _scan_files(self, src):
        self._disconnect_worker()
        self._log(f"PC File Scan: {src}")
        # Log classification capabilities
        signals = ['extension']
        if HAS_MAGIC:
            signals.append('content(python-magic)')
        signals.append('filename_patterns')
        if HAS_RAPIDFUZZ:
            signals.append('keyword_fuzzy')
        self._log(f"  Classification signals: {', '.join(signals)}")
        # Log metadata extraction capabilities
        caps = MetadataExtractor.capabilities()
        avail = [k for k, v in caps.items() if v]
        missing = [k for k, v in caps.items() if not v]
        if avail:
            self._log(f"  Metadata extractors: {', '.join(avail)}")
        if missing:
            libs_hint = {'images': 'Pillow/exifread', 'audio': 'mutagen',
                         'video': 'ffprobe', 'pdf': 'pypdf', 'docx': 'python-docx',
                         'xlsx': 'openpyxl'}
            hints = [f"{k} ({libs_hint.get(k, '?')})" for k in missing]
            self._log(f"  Missing: {', '.join(hints)} — install for richer metadata")
        if not HAS_MAGIC:
            self._log("  Tip: pip install python-magic-bin — enables content-based MIME detection")
        # Log active rename templates
        tmpl_cats = [c['name'] for c in self._pc_categories if c.get('rename_template')]
        if tmpl_cats:
            self._log(f"  Rename templates active: {', '.join(tmpl_cats)}")
        self.file_items.clear(); self.tbl.setRowCount(0)
        self._files_dest_paths = {}   # collision tracking per full path
        self._rename_counters  = {}   # per-category counter for {counter} token
        depth = self.spn_depth.value()
        inc_files   = self.chk_inc_files.isChecked()
        inc_folders = self.chk_inc_folders.isChecked()
        if not inc_files and not inc_folders:
            self._log("  Enable at least Files or Folders."); self._reset_scan_ui(); return

        # Resolve file type filter
        filter_name = self.cmb_type_filter.currentText()
        ext_filter = _SCAN_FILTERS.get(filter_name)
        if ext_filter:
            self._log(f"  File type filter: {filter_name} ({len(ext_filter)} extensions)")

        use_llm = self.chk_llm.isChecked()
        if use_llm:
            self._log("  Mode: LLM-powered file classification")
            self.worker = ScanFilesLLMWorker(
                src, "", self._pc_categories, depth,
                self.chk_hash.isChecked(), inc_folders, inc_files,
                ext_filter=ext_filter)
            self.lbl_prog_phase.setText("AI Classify")
            self.lbl_prog_method.setText("LLM classifying files…")
        else:
            self.worker = ScanFilesWorker(
                src, "", self._pc_categories, depth,
                self.chk_hash.isChecked(), inc_folders, inc_files,
                ext_filter=ext_filter)
            self.lbl_prog_phase.setText("Scanning")
            self.lbl_prog_method.setText("Multi-signal classification…")

        self.pbar.setValue(0); self.prog_panel.setVisible(True)
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._update_progress)
        self.worker.phase.connect(self._update_phase)
        if hasattr(self.worker, 'current_item'):
            self.worker.current_item.connect(self._set_current_scan_item)
        self.worker.result_ready.connect(self._on_files_result)
        self.worker.finished.connect(self._on_files_scan_done)
        self.worker.start()

    def _on_files_result(self, r: dict):
        """Process a single file/folder result from the scanner."""
        it = FileItem()
        it.name        = r['name']
        it.full_src    = r['full_src']
        it.category    = r['category']
        it.confidence  = r['confidence']
        it.method      = r['method']
        it.detail      = r['detail']
        it.size        = r['size']
        it.is_folder   = r['is_folder']
        it.is_duplicate = r['is_duplicate']
        it.dup_group    = r.get('dup_group', 0)
        it.dup_detail   = r.get('dup_detail', '')
        it.dup_is_original = r.get('dup_is_original', False)
        it.metadata    = r.get('metadata', {})
        it.vision_description = r.get('vision_description', '')
        it.vision_ocr  = r.get('vision_ocr', '')
        it.selected    = not it.is_duplicate   # auto-deselect dupes

        # ── Rename resolution ─────────────────────────────────────────────────
        # Vision AI name takes priority (pure AI-generated descriptive name)
        _vision_used = False
        if r.get('vision_suggested_name') and not it.is_folder:
            suggested = r['vision_suggested_name']
            suggested = re.sub(r'[<>:"/\\|?*]', '_', suggested)[:60].strip(' _-.')
            _poison_chk = suggested.lower().replace('-', '_').replace(' ', '_')
            _poison_words = ('category', 'confidence', 'reason', 'suggested_name',
                             'detected_text', 'description', 'the_image_is', 'image_is',
                             'according_to', 'here_is', 'classified', 'given_input')
            if any(p in _poison_chk for p in _poison_words):
                suggested = ''
            if suggested and len(suggested) >= 3:
                ext = os.path.splitext(it.name)[1]
                it.display_name = suggested + ext
                _vision_used = True

        # Fallback: rename template (for non-vision items like audio, video, docs)
        if not _vision_used:
            template = self._pc_template_for(it.category)
            if template and not it.is_folder:
                self._rename_counters[it.category] = self._rename_counters.get(it.category, 0) + 1
                counter = self._rename_counters[it.category]
                new_stem = RenameTemplateEngine.resolve(
                    template, it.full_src, it.metadata, it.category, counter)
                ext = os.path.splitext(it.name)[1]
                it.display_name = new_stem + ext
            else:
                it.display_name = it.name

        # Compute destination path with collision avoidance
        # Photo folder structure override for image files
        _photo_s_dst = load_photo_settings()
        _img_exts_photo = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif',
                           '.tiff', '.tif', '.bmp', '.raw', '.cr2', '.nef', '.arw', '.dng'}
        if (_photo_s_dst.get('enabled') and not it.is_folder
                and os.path.splitext(it.name)[1].lower() in _img_exts_photo):
            preset_key = _photo_s_dst.get('folder_preset', 'flat')
            preset = _PHOTO_FOLDER_PRESETS.get(preset_key, {})
            folder_template = preset.get('template', '')
            if folder_template:
                counter = self._rename_counters.get(it.category, 0)
                folder_path = RenameTemplateEngine.resolve(
                    folder_template.rstrip('/'), it.full_src, it.metadata, it.category, counter)
                folder_path = re.sub(r'[<>:"|?*]', '_', folder_path)
                base_dst = self._pc_dst_for(it.category)
                raw_dst = os.path.join(base_dst, folder_path, it.display_name)
            else:
                raw_dst = os.path.join(self._pc_dst_for(it.category), it.display_name)
        else:
            raw_dst = os.path.join(self._pc_dst_for(it.category), it.display_name)
        it.full_dst = self._dedup_file_dst(raw_dst)

        self.file_items.append(it)
        self._add_files_row(it, len(self.file_items) - 1)
        self._stats_files()

    def _dedup_file_dst(self, dst_path: str) -> str:
        """Avoid collisions in destination — append (2), (3) etc. as needed."""
        key = dst_path.lower()
        if key not in self._files_dest_paths and not os.path.exists(dst_path):
            self._files_dest_paths[key] = 1
            return dst_path
        base, ext2 = os.path.splitext(dst_path)
        n = 2
        for _ in range(10000):
            candidate = f"{base} ({n}){ext2}"
            ckey = candidate.lower()
            if ckey not in self._files_dest_paths and not os.path.exists(candidate):
                self._files_dest_paths[ckey] = 1
                return candidate
            n += 1
        return f"{base} ({n}){ext2}"  # safety fallback

    def _on_files_scan_done(self):
        self._reset_scan_ui()
        self.tbl.setSortingEnabled(True)
        total = len(self.file_items)
        self.btn_apply.setEnabled(total > 0)
        self.btn_preview.setEnabled(total > 0)
        self.btn_export.setEnabled(total > 0)
        self.btn_export_html.setEnabled(total > 0)
        self._stats_files()
        self._log(f"Scan complete: {total} items found")
        if total > 0:
            cats = len(set(it.category for it in self.file_items if it.category))
            dups = sum(1 for it in self.file_items if it.is_duplicate)
            parts = [f"{total} files", f"{cats} categories"]
            if dups:
                parts.append(f"{dups} duplicates")
            self._show_scan_toast("Scan complete: " + " | ".join(parts))
            self._populate_face_filter()
            self._resolve_conflicts()
            self._update_dashboard()
            self._update_map_button_visibility()
            # Show new v7 toolbar buttons
            self.btn_graph_toggle.setVisible(True)
            self.btn_preview_toggle.setVisible(True)
            self.btn_before_after.setVisible(True)
            # Events button — show only when vision items exist
            has_vision = any(it.vision_description for it in self.file_items)
            self.btn_events.setVisible(has_vision and self._ollama_ready)
            # Plugin post-scan hooks
            try:
                PluginManager.run_post_scan(self.file_items)
            except Exception:
                pass
            # Auto-tag entries in tag library if open
            self._auto_tag_scan_results()
            # Category balancing — suggest merges/splits for imbalanced categories
            self._run_category_balancer('files')
        if total == 0:
            action_label = None
            action_cb = None
            # If the user narrowed the file-type filter, offer a one-click reset.
            if hasattr(self, 'cmb_type_filter') and self.cmb_type_filter.currentText() != 'All Files':
                narrowed = self.cmb_type_filter.currentText()
                action_label = f"Reset filter ({narrowed} → All Files)"
                _cmb = self.cmb_type_filter  # capture
                def _reset_filter():
                    idx = _cmb.findText('All Files')
                    if idx >= 0:
                        _cmb.setCurrentIndex(idx)
                action_cb = _reset_filter
            self._show_empty_state(
                "No files or folders were found",
                "Check the selected source, include more depth, or broaden the current file-type filter.",
                kicker="SCAN COMPLETE",
                action_label=action_label, action_callback=action_cb,
            )

    def _auto_tag_scan_results(self):
        """Auto-tag scan results in the tag library if it's open."""
        if not hasattr(self, '_tag_panel') or not self._tag_panel.library.is_open:
            return
        lib = self._tag_panel.library
        tagged = 0
        # Process categorize items
        for item in getattr(self, 'cat_items', []):
            if item.category and item.full_source_path:
                entry = lib.add_entry(item.full_source_path)
                if entry:
                    lib.auto_tag_from_category(
                        entry.id, item.category, item.method, item.confidence)
                    tagged += 1
        # Process file items
        for item in getattr(self, 'file_items', []):
            if item.category and item.full_src:
                entry = lib.add_entry(item.full_src)
                if entry:
                    lib.auto_tag_from_category(
                        entry.id, item.category, item.method, item.confidence)
                    tagged += 1
        if tagged:
            self._log(f"  Tag Library: auto-tagged {tagged} entries")
            self._tag_panel._refresh_tags()
            self._tag_panel._refresh_entries()
            self._tag_panel._update_stats()

    def _resolve_conflicts(self):
        """Auto-resolve destination path conflicts using saved strategy."""
        conflicts = ConflictResolver.detect(self.file_items)
        if not conflicts:
            return
        strategy = self.settings.value("conflict_strategy", "auto_suffix")
        count = ConflictResolver.resolve(conflicts, strategy, self.file_items)
        if count:
            self._log(f"  Resolved {count} destination conflict(s) via '{strategy}'")

    def _run_category_balancer(self, mode: str):
        """Run category balancing and log suggestions for merges/splits."""
        if not self.settings.value("category_balancing", True, type=bool):
            return
        balancer = CategoryBalancer()
        if mode == 'cat':
            items = self.cat_items
            cats = set(it.category for it in items if it.category and it.category != '[Uncategorized]')
        else:
            items = self.file_items
            cats = set(it.category for it in items if it.category)
        if len(items) < 10 or len(cats) < 3:
            return
        suggestions = balancer.balance(items, all_categories=cats)
        merges = suggestions.get('merges', {})
        splits = suggestions.get('splits', {})
        if merges:
            merge_str = ', '.join(f"{k} -> {v}" for k, v in list(merges.items())[:5])
            self._log(f"  [BALANCE] Merge suggestions: {merge_str}")
        if splits:
            split_str = ', '.join(f"{k} ({len(v)} sub-groups)" for k, v in list(splits.items())[:5])
            self._log(f"  [BALANCE] Split suggestions: {split_str}")
