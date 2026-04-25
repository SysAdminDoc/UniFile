"""UniFile — Archive Content Indexer Dialog.

Lets users scan a directory to index files inside archives (.zip, .7z, .rar,
.tar.*) and search the resulting index. Useful for finding files that are
buried inside compressed archives without extracting them first.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header


class ArchiveIndexerDialog(QDialog):
    """GUI for building and querying the archive content index."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Archive Content Indexer")
        self.setMinimumSize(640, 500)
        self.setStyleSheet(get_active_stylesheet())
        self._t = get_active_theme()
        self._worker = None
        self._build_ui()
        self._refresh_stats()

    def _build_ui(self) -> None:
        t = self._t
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(18, 18, 18, 18)

        lay.addWidget(build_dialog_header(
            t, "Tools",
            "Archive Content Indexer",
            "Build a searchable index of files inside .zip, .7z, .rar, and "
            ".tar archives. No files are extracted — only the internal file "
            "listing is read and stored.",
        ))

        # ── Index section ─────────────────────────────────────────────────────
        idx_frame = QFrame()
        idx_frame.setStyleSheet(
            f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
            f"border-radius: 10px; }}"
        )
        idx_lay = QVBoxLayout(idx_frame)
        idx_lay.setContentsMargins(14, 12, 14, 12)
        idx_lay.setSpacing(8)

        lbl_idx = QLabel("Index a Directory")
        lbl_idx.setStyleSheet(f"color: {t['fg_bright']}; font-size: 14px; font-weight: 700;")
        idx_lay.addWidget(lbl_idx)

        dir_row = QHBoxLayout()
        self.txt_dir = QLineEdit()
        self.txt_dir.setPlaceholderText("Select a folder to scan for archives…")
        dir_row.addWidget(self.txt_dir, 1)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._browse)
        dir_row.addWidget(btn_browse)
        idx_lay.addLayout(dir_row)

        self.btn_scan = QPushButton("Scan Archives")
        self.btn_scan.setProperty("class", "primary")
        self.btn_scan.clicked.connect(self._start_scan)
        idx_lay.addWidget(self.btn_scan)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        idx_lay.addWidget(self.progress)

        self.lbl_scan_status = QLabel("")
        self.lbl_scan_status.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        idx_lay.addWidget(self.lbl_scan_status)

        lay.addWidget(idx_frame)

        # ── Search section ────────────────────────────────────────────────────
        srch_frame = QFrame()
        srch_frame.setStyleSheet(
            f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
            f"border-radius: 10px; }}"
        )
        srch_lay = QVBoxLayout(srch_frame)
        srch_lay.setContentsMargins(14, 12, 14, 12)
        srch_lay.setSpacing(8)

        lbl_srch = QLabel("Search Index")
        lbl_srch.setStyleSheet(f"color: {t['fg_bright']}; font-size: 14px; font-weight: 700;")
        srch_lay.addWidget(lbl_srch)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Type a filename to search…")
        self.txt_search.textChanged.connect(self._do_search)
        srch_lay.addWidget(self.txt_search)

        self.lst_results = QListWidget()
        self.lst_results.setMinimumHeight(140)
        self.lst_results.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; }}"
        )
        srch_lay.addWidget(self.lst_results)

        self.lbl_results = QLabel("")
        self.lbl_results.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        srch_lay.addWidget(self.lbl_results)

        lay.addWidget(srch_frame, 1)

        # ── Stats + footer ────────────────────────────────────────────────────
        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        lay.addWidget(self.lbl_stats)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("Clear Index")
        btn_clear.clicked.connect(self._clear_index)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        footer.rejected.connect(self.reject)
        footer.button(QDialogButtonBox.StandardButton.Close).setText("Done")
        lay.addWidget(footer)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select folder to scan")
        if d:
            self.txt_dir.setText(d)

    def _start_scan(self) -> None:
        from unifile.archive_indexer import ArchiveIndexWorker
        d = self.txt_dir.text().strip()
        if not d:
            return
        self.btn_scan.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.lbl_scan_status.setText("Scanning…")

        self._worker = ArchiveIndexWorker(d, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, scanned: int, total: int, path: str) -> None:
        if total > 0:
            self.progress.setValue(int(scanned * 100 / total))
        name = path.split("\\")[-1].split("/")[-1]
        self.lbl_scan_status.setText(f"Scanned {scanned}/{total}: {name}")

    def _on_finished(self, results: list) -> None:
        self.btn_scan.setEnabled(True)
        self.progress.setVisible(False)
        ok = sum(1 for r in results if not r.error)
        errors = sum(1 for r in results if r.error)
        total_entries = sum(len(r.entries) for r in results)
        self.lbl_scan_status.setText(
            f"Done: {ok} archives indexed, {total_entries} files, {errors} errors."
        )
        self._refresh_stats()

    def _on_error(self, msg: str) -> None:
        self.btn_scan.setEnabled(True)
        self.progress.setVisible(False)
        self.lbl_scan_status.setText(f"Error: {msg}")

    def _do_search(self, query: str) -> None:
        from unifile.archive_indexer import search
        self.lst_results.clear()
        q = query.strip()
        if len(q) < 2:
            self.lbl_results.setText("")
            return
        results = search(q, limit=100)
        for entry in results:
            archive_name = entry.archive_path.split("\\")[-1].split("/")[-1]
            item = QListWidgetItem(f"{entry.name}  ({archive_name}:{entry.inner_path})")
            item.setToolTip(entry.archive_path)
            self.lst_results.addItem(item)
        self.lbl_results.setText(f"{len(results)} result(s)")

    def _clear_index(self) -> None:
        from unifile.archive_indexer import clear_index
        clear_index()
        self.lst_results.clear()
        self.lbl_results.setText("")
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        try:
            from unifile.archive_indexer import index_stats
            s = index_stats()
            self.lbl_stats.setText(
                f"Index: {s['indexed_archives']} archives, "
                f"{s['indexed_files']} files, "
                f"{s['errors']} error(s)"
            )
        except Exception:
            pass
