"""UniFile dialogs -- Advanced settings (AI Providers, Whisper, Semantic, Embedding, Learning)."""
import os
import subprocess
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header


class AIProviderSettingsDialog(QDialog):
    """Configure multi-provider AI backend (Ollama, OpenAI-compatible, Groq, OpenAI)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Provider Settings")
        self.setMinimumSize(600, 520)
        self.setStyleSheet(get_active_stylesheet())
        from unifile.ai_providers import load_providers
        self._providers = load_providers()
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        layout.addWidget(build_dialog_header(
            _t,
            "Providers",
            "AI Provider Settings",
            "Configure fallback providers for classification. Lower priority numbers run first, so keep your fastest or most trusted provider at the top."
        ))

        lbl = QLabel("Enable only the providers you want UniFile to try automatically. Local backends can leave the API key blank.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        layout.addWidget(lbl)

        self._provider_widgets = {}
        for key, cfg in self._providers.items():
            grp = QGroupBox(cfg.get('name', key))
            grp.setCheckable(True)
            grp.setChecked(cfg.get('enabled', False))
            g_lay = QGridLayout(grp)
            g_lay.setHorizontalSpacing(10)
            g_lay.setVerticalSpacing(8)

            helper = QLabel(
                f"Type: {cfg.get('type', 'provider')}  -  Set a lower priority number to try this provider earlier."
            )
            helper.setWordWrap(True)
            helper.setStyleSheet(f"color: {_t['muted']}; font-size: 10px;")
            g_lay.addWidget(helper, 0, 0, 1, 2)

            row = 1
            g_lay.addWidget(QLabel("URL:"), row, 0)
            url_edit = QLineEdit(cfg.get('url', ''))
            url_edit.setPlaceholderText("http://localhost:11434")
            g_lay.addWidget(url_edit, row, 1)

            row += 1
            g_lay.addWidget(QLabel("Model:"), row, 0)
            model_edit = QLineEdit(cfg.get('model', ''))
            g_lay.addWidget(model_edit, row, 1)

            row += 1
            g_lay.addWidget(QLabel("Vision Model:"), row, 0)
            vision_edit = QLineEdit(cfg.get('vision_model', ''))
            vision_edit.setPlaceholderText("(optional)")
            g_lay.addWidget(vision_edit, row, 1)

            row += 1
            g_lay.addWidget(QLabel("API Key:"), row, 0)
            key_edit = QLineEdit(cfg.get('api_key', ''))
            key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            key_edit.setPlaceholderText("(leave empty for local)")
            g_lay.addWidget(key_edit, row, 1)

            row += 1
            g_lay.addWidget(QLabel("Priority:"), row, 0)
            prio_spin = QSpinBox()
            prio_spin.setRange(1, 99)
            prio_spin.setValue(cfg.get('priority', 99))
            g_lay.addWidget(prio_spin, row, 1)

            row += 1
            btn_test = QPushButton("Test Connection")
            lbl_status = QLabel("Not checked yet")
            lbl_status.setStyleSheet(f"color: {_t['muted']}; font-size: 10px;")
            btn_test.clicked.connect(
                lambda _, u=url_edit, k=key_edit, t=cfg.get('type', 'ollama'), s=lbl_status:
                self._test_provider(u.text(), k.text(), t, s))
            h = QHBoxLayout()
            h.addWidget(btn_test)
            h.addWidget(lbl_status)
            h.addStretch()
            g_lay.addLayout(h, row, 0, 1, 2)

            layout.addWidget(grp)
            self._provider_widgets[key] = {
                'group': grp, 'url': url_edit, 'model': model_edit,
                'vision': vision_edit, 'api_key': key_edit, 'priority': prio_spin,
            }

        layout.addStretch()

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Save Provider Settings")
        btns.accepted.connect(self._save_and_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _test_provider(self, url, api_key, prov_type, status_label):
        from unifile.ai_providers import AIProvider
        provider = AIProvider({'type': prov_type, 'url': url, 'api_key': api_key, 'timeout': 5})
        if provider.is_available():
            status_label.setText("Connected and ready")
            status_label.setStyleSheet(f"color: {get_active_theme()['green']}; font-size: 10px;")
        else:
            status_label.setText("Connection failed")
            status_label.setStyleSheet("color: #ef4444; font-size: 10px;")

    def _save_and_accept(self):
        from unifile.ai_providers import save_providers
        for key, widgets in self._provider_widgets.items():
            self._providers[key]['enabled'] = widgets['group'].isChecked()
            self._providers[key]['url'] = widgets['url'].text().strip()
            self._providers[key]['model'] = widgets['model'].text().strip()
            self._providers[key]['vision_model'] = widgets['vision'].text().strip()
            self._providers[key]['api_key'] = widgets['api_key'].text().strip()
            self._providers[key]['priority'] = widgets['priority'].value()
        save_providers(self._providers)
        self.accept()


class WhisperSettingsDialog(QDialog):
    """Configure Whisper audio transcription for content-based classification."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Whisper Audio Settings")
        self.setMinimumSize(400, 300)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        from unifile.whisper_backend import WHISPER_MODELS, get_transcriber
        transcriber = get_transcriber()

        layout.addWidget(build_dialog_header(
            _t,
            "Audio",
            "Whisper Audio Settings",
            "Use transcription to classify audio and video files by spoken content, not just by filename."
        ))

        # Availability
        avail = transcriber.is_available
        self.lbl_status = QLabel(
            "Whisper is available."
            if avail else
            "Whisper is not installed yet. Install it with: pip install openai-whisper"
        )
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {_t['green'] if avail else '#ef4444'}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # Model selection
        h = QHBoxLayout()
        h.addWidget(QLabel("Model Size"))
        self.cmb_model = QComboBox()
        for key, desc in WHISPER_MODELS.items():
            self.cmb_model.addItem(f"{key} - {desc}", key)
        idx = list(WHISPER_MODELS.keys()).index(transcriber._model_size) if transcriber._model_size in WHISPER_MODELS else 1
        self.cmb_model.setCurrentIndex(idx)
        h.addWidget(self.cmb_model)
        layout.addLayout(h)

        helper = QLabel("Smaller models run faster. Larger models usually improve accuracy on noisy recordings.")
        helper.setWordWrap(True)
        helper.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        layout.addWidget(helper)

        # Clear cache button
        btn_clear = QPushButton("Clear Transcription Cache")
        btn_clear.clicked.connect(self._clear_cache)
        layout.addWidget(btn_clear)

        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setWordWrap(True)
        self.lbl_feedback.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_feedback)

        layout.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Save Whisper Settings")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _clear_cache(self):
        from unifile.whisper_backend import get_transcriber
        get_transcriber().clear_cache()
        self.lbl_feedback.setText("Transcription cache cleared.")

    def get_model_size(self) -> str:
        return self.cmb_model.currentData() or "base"


class SemanticSearchSettingsDialog(QDialog):
    """Configure semantic/natural-language search via embeddings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Semantic Search Settings")
        self.setMinimumSize(420, 300)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        layout.addWidget(build_dialog_header(
            _t,
            "Search",
            "Semantic Search Settings",
            "Semantic search finds files by meaning rather than exact keywords. Keep the embedding model available and the similarity threshold practical for your library."
        ))

        from unifile.semantic import SemanticIndex
        idx = SemanticIndex()

        # Status
        avail = idx.is_available()
        status = QLabel(
            "Embedding model is available."
            if avail else
            "Embedding model is not available. Semantic search needs Ollama plus nomic-embed-text."
        )
        status.setStyleSheet(f"color: {_t['green'] if avail else '#ef4444'}; font-size: 11px;")
        layout.addWidget(status)

        count = idx.get_indexed_count()
        lbl_count = QLabel(f"{count:,} file{'s' if count != 1 else ''} are currently indexed.")
        lbl_count.setStyleSheet(f"color: {_t['fg']}; font-size: 12px;")
        layout.addWidget(lbl_count)

        # Model
        h = QHBoxLayout()
        h.addWidget(QLabel("Embedding Model"))
        self.txt_model = QLineEdit(idx._model)
        self.txt_model.setPlaceholderText("nomic-embed-text")
        h.addWidget(self.txt_model)
        layout.addLayout(h)

        # Threshold
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Similarity Threshold"))
        self.spn_thresh = QSpinBox()
        self.spn_thresh.setRange(10, 90)
        self.spn_thresh.setValue(30)
        self.spn_thresh.setSuffix("%")
        h2.addWidget(self.spn_thresh)
        layout.addLayout(h2)

        thresh_hint = QLabel("Lower thresholds return broader matches. Higher thresholds are stricter and more precise.")
        thresh_hint.setWordWrap(True)
        thresh_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        layout.addWidget(thresh_hint)

        # Clear button
        btn_clear = QPushButton("Clear Semantic Index")
        btn_clear.clicked.connect(self._clear_index)
        layout.addWidget(btn_clear)

        layout.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Save Search Settings")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        idx.close()

    def _clear_index(self):
        from unifile.semantic import SemanticIndex
        idx = SemanticIndex()
        idx.clear()
        idx.close()


class _SemanticSearchWorker(QThread):
    """Background worker so the UI stays responsive during embedding + query."""

    finished_ok = pyqtSignal(list)          # list[dict] of results
    finished_err = pyqtSignal(str)          # error message

    def __init__(self, query: str, limit: int, threshold: float, model: str):
        super().__init__()
        self.query = query
        self.limit = limit
        self.threshold = threshold
        self.model = model

    def run(self):
        try:
            from unifile.semantic import SemanticIndex
            idx = SemanticIndex(model=self.model)
            if not idx.is_available():
                idx.close()
                self.finished_err.emit(
                    "Embedding model not reachable. Make sure Ollama is running "
                    f"and `ollama pull {self.model}` has completed."
                )
                return
            results = idx.search(self.query, limit=self.limit,
                                 threshold=self.threshold)
            idx.close()
            self.finished_ok.emit(results)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {e}")


class SemanticSearchDialog(QDialog):
    """Natural-language search across previously-indexed files.

    Lets the user type a free-form query, runs it against the embedding
    index, and shows matching files sorted by similarity. Double-clicking
    a result reveals it in the OS file manager.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Semantic Search")
        self.setMinimumSize(820, 560)
        self.setStyleSheet(get_active_stylesheet())
        self._worker: _SemanticSearchWorker | None = None
        self._build_ui()
        self._refresh_status()

    # ── UI construction ─────────────────────────────────────────────────────

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        layout.addWidget(build_dialog_header(
            _t,
            "Search",
            "Semantic Search",
            "Find files by meaning. Queries like \"photos from last summer\" "
            "or \"invoices with large totals\" match against the semantic "
            "index built by previous scans."
        ))

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;"
        )
        layout.addWidget(self.lbl_status)

        # ── Query row ──────────────────────────────────────────────────────
        query_row = QHBoxLayout()
        self.txt_query = QLineEdit()
        self.txt_query.setPlaceholderText(
            "Describe what you're looking for, e.g. \"tax documents from 2023\"…"
        )
        self.txt_query.returnPressed.connect(self._on_search)
        query_row.addWidget(self.txt_query, 1)

        self.btn_search = QPushButton("Search")
        self.btn_search.setProperty("class", "primary")
        self.btn_search.clicked.connect(self._on_search)
        query_row.addWidget(self.btn_search)
        layout.addLayout(query_row)

        # ── Parameters row ─────────────────────────────────────────────────
        params = QHBoxLayout()
        params.addWidget(QLabel("Model"))
        self.txt_model = QLineEdit("nomic-embed-text")
        self.txt_model.setMaximumWidth(220)
        params.addWidget(self.txt_model)

        params.addSpacing(12)
        params.addWidget(QLabel("Similarity"))
        self.spn_thresh = QSpinBox()
        self.spn_thresh.setRange(5, 95)
        self.spn_thresh.setSuffix("%")
        self.spn_thresh.setValue(30)
        self.spn_thresh.setMaximumWidth(90)
        params.addWidget(self.spn_thresh)

        params.addSpacing(12)
        params.addWidget(QLabel("Max results"))
        self.spn_limit = QSpinBox()
        self.spn_limit.setRange(5, 500)
        self.spn_limit.setValue(50)
        self.spn_limit.setMaximumWidth(90)
        params.addWidget(self.spn_limit)
        params.addStretch()
        layout.addLayout(params)

        # ── Results table ──────────────────────────────────────────────────
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Score", "File", "Description"])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive)
        self.tbl.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.tbl.setColumnWidth(1, 280)
        self.tbl.itemDoubleClicked.connect(self._on_result_double_clicked)
        layout.addWidget(self.tbl, 1)

        # ── Footer ─────────────────────────────────────────────────────────
        footer = QHBoxLayout()
        self.lbl_hint = QLabel(
            "Double-click a row to reveal the file in your OS file manager."
        )
        self.lbl_hint.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        footer.addWidget(self.lbl_hint)
        footer.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        footer.addWidget(btn_close)
        layout.addLayout(footer)

    # ── Actions ─────────────────────────────────────────────────────────────

    def _refresh_status(self):
        from unifile.semantic import SemanticIndex
        idx = SemanticIndex()
        try:
            count = idx.get_indexed_count()
            avail = idx.is_available()
        finally:
            idx.close()
        parts = [f"{count:,} file{'s' if count != 1 else ''} indexed"]
        if count == 0:
            parts.append(
                "Run a PC File Organizer scan with semantic search enabled "
                "to populate the index first."
            )
        parts.append(
            "Embedding model reachable."
            if avail else
            "Embedding model is not reachable — semantic search will fail "
            "until Ollama + `nomic-embed-text` are available."
        )
        self.lbl_status.setText("  •  ".join(parts))

    def _on_search(self):
        if self._worker is not None and self._worker.isRunning():
            return
        query = self.txt_query.text().strip()
        if not query:
            self.lbl_status.setText("Enter a query above and click Search.")
            return
        self.tbl.setRowCount(0)
        self.btn_search.setEnabled(False)
        self.btn_search.setText("Searching…")
        self._worker = _SemanticSearchWorker(
            query=query,
            limit=self.spn_limit.value(),
            threshold=self.spn_thresh.value() / 100.0,
            model=self.txt_model.text().strip() or "nomic-embed-text",
        )
        self._worker.finished_ok.connect(self._on_results)
        self._worker.finished_err.connect(self._on_search_error)
        self._worker.finished.connect(self._reset_search_button)
        self._worker.start()

    def _reset_search_button(self):
        self.btn_search.setEnabled(True)
        self.btn_search.setText("Search")

    def _on_results(self, results: list):
        if not results:
            self.lbl_status.setText(
                "No matches above the similarity threshold. Try lowering "
                "it, or rephrase the query."
            )
            return
        for r in results:
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            score_item = QTableWidgetItem(f"{r['score']*100:.1f}%")
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            file_item = QTableWidgetItem(os.path.basename(r.get('filepath', '')))
            file_item.setToolTip(r.get('filepath', ''))
            # Store absolute path on the file-cell for the double-click handler
            file_item.setData(Qt.ItemDataRole.UserRole, r.get('filepath', ''))
            desc = r.get('description', '') or ''
            desc_item = QTableWidgetItem(desc[:200] + ('…' if len(desc) > 200 else ''))
            desc_item.setToolTip(desc)
            self.tbl.setItem(row, 0, score_item)
            self.tbl.setItem(row, 1, file_item)
            self.tbl.setItem(row, 2, desc_item)
        self.lbl_status.setText(
            f"{len(results)} match{'es' if len(results) != 1 else ''} "
            f"(best {results[0]['score']*100:.1f}% similarity)."
        )

    def _on_search_error(self, message: str):
        self.lbl_status.setText(f"Search failed: {message}")

    def _on_result_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        path_item = self.tbl.item(row, 1)
        path = path_item.data(Qt.ItemDataRole.UserRole) if path_item else ''
        if not path or not os.path.exists(path):
            self.lbl_status.setText(f"File no longer exists: {path}")
            return
        _reveal_in_file_manager(path)


def _reveal_in_file_manager(path: str) -> None:
    """Cross-platform: open the OS file manager with `path` selected."""
    try:
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', path])
        else:
            subprocess.Popen(['xdg-open', os.path.dirname(path) or path])
    except (OSError, FileNotFoundError):
        pass


class EmbeddingSettingsDialog(QDialog):
    """Configure metadata embedding (write-back to files)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metadata Embedding Settings")
        self.setMinimumSize(420, 320)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        layout.addWidget(build_dialog_header(
            _t,
            "Metadata",
            "Metadata Embedding Settings",
            "Write categories and tags back into supported file formats so other media tools can read the same organization data."
        ))

        from unifile.embedding import MetadataEmbedder
        embedder = MetadataEmbedder()
        caps = embedder.capabilities()
        ready_count = sum(1 for avail in caps.values() if avail)

        # Show capabilities
        grp = QGroupBox("Format Support")
        g_lay = QVBoxLayout(grp)
        for fmt, avail in caps.items():
            lbl_fmt = QLabel(f"{'Ready' if avail else 'Unavailable'}  -  {fmt}")
            lbl_fmt.setStyleSheet(f"color: {_t['green'] if avail else _t['muted']}; font-size: 11px;")
            g_lay.addWidget(lbl_fmt)
        layout.addWidget(grp)

        summary = QLabel(
            f"{ready_count} format{'s' if ready_count != 1 else ''} can accept embedded metadata right now."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 0 2px;")
        layout.addWidget(summary)

        # Options
        self.chk_auto = QCheckBox("Automatically embed categories after Apply")
        self.chk_auto.setToolTip("When enabled, classification results are written into files after organizing")
        layout.addWidget(self.chk_auto)

        self.chk_tags = QCheckBox("Include tags in metadata")
        self.chk_tags.setChecked(True)
        layout.addWidget(self.chk_tags)

        layout.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Save Embedding Settings")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


class LearningStatsDialog(QDialog):
    """View and manage adaptive learning patterns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adaptive Learning")
        self.setMinimumSize(380, 280)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        from unifile.learning import get_learner
        learner = get_learner()
        stats = learner.get_stats()

        layout.addWidget(build_dialog_header(
            _t,
            "Learning",
            "Adaptive Learning",
            "UniFile improves future classifications by learning from your corrections. Review what has been learned before deciding whether to reset it."
        ))

        info = QLabel(
            f"Total corrections: {stats['total_corrections']}\n"
            f"Extension patterns: {stats['extension_patterns']}\n"
            f"Token patterns: {stats['token_patterns']}\n"
            f"Folder patterns: {stats['folder_patterns']}\n"
            f"Size patterns: {stats['size_patterns']}"
        )
        info.setStyleSheet(
            f"color: {_t['fg']}; font-size: 12px; padding: 10px 12px; "
            f"background: {_t['bg_alt']}; border: 1px solid {_t['border']}; border-radius: 10px;"
        )
        layout.addWidget(info)

        btn_clear = QPushButton("Reset All Learned Patterns")
        btn_clear.setStyleSheet("QPushButton { color: #ef4444; }")
        btn_clear.clicked.connect(self._clear)
        layout.addWidget(btn_clear)

        layout.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)

    def _clear(self):
        from unifile.learning import get_learner
        get_learner().clear()
        self.close()
