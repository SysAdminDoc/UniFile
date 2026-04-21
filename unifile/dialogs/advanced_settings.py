"""UniFile dialogs -- Advanced settings (AI Providers, Whisper, Semantic, Embedding, Learning)."""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QDialog, QDialogButtonBox, QSpinBox,
    QSlider, QFrame, QGroupBox, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from unifile.config import get_active_theme, get_active_stylesheet


def _build_dialog_header(t: dict, kicker: str, title: str, description: str) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
        f"border-radius: 14px; }}"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(4)

    lbl_kicker = QLabel(kicker.upper())
    lbl_kicker.setStyleSheet(
        f"color: {t['accent']}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;"
    )
    layout.addWidget(lbl_kicker)

    lbl_title = QLabel(title)
    lbl_title.setStyleSheet(f"color: {t['fg_bright']}; font-size: 20px; font-weight: 700;")
    layout.addWidget(lbl_title)

    lbl_desc = QLabel(description)
    lbl_desc.setWordWrap(True)
    lbl_desc.setStyleSheet(f"color: {t['muted']}; font-size: 12px; line-height: 1.4;")
    layout.addWidget(lbl_desc)
    return frame


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

        layout.addWidget(_build_dialog_header(
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

        layout.addWidget(_build_dialog_header(
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

        layout.addWidget(_build_dialog_header(
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

        layout.addWidget(_build_dialog_header(
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

        layout.addWidget(_build_dialog_header(
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
