"""Voice command dialog and optional Whisper transcription worker."""
from __future__ import annotations

import os

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.voice import VoiceIntent, VoiceIntentParser


class _WhisperWorker(QThread):
    result_ready = pyqtSignal(dict)

    def __init__(self, path: str, model_size: str = "base", parent=None):
        super().__init__(parent)
        self._path = path
        self._model_size = model_size

    def run(self):
        try:
            from unifile.whisper_backend import get_transcriber

            result = get_transcriber(self._model_size).transcribe(self._path)
        except Exception as exc:
            result = {"text": "", "error": str(exc)}
        self.result_ready.emit(result)


class VoiceControlDialog(QDialog):
    """Parse, preview, and explicitly execute a UniFile voice command."""

    intent_ready = pyqtSignal(object)
    hotkey_changed = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        *,
        parser: VoiceIntentParser | None = None,
        execute_callback=None,
        preview_callback=None,
        shortcut: str = "Ctrl+Shift+V",
    ):
        super().__init__(parent)
        self.setWindowTitle("Voice Control")
        self.setMinimumSize(620, 520)
        self.setStyleSheet(get_active_stylesheet())
        self._parser = parser or VoiceIntentParser()
        self._execute_callback = execute_callback
        self._preview_callback = preview_callback
        self._intent: VoiceIntent | None = None
        self._worker: _WhisperWorker | None = None
        self._build_ui(shortcut)

    def _build_ui(self, shortcut: str):
        theme = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(build_dialog_header(
            theme,
            "OFFLINE COMMANDS",
            "Voice Control",
            "Use the configurable hotkey to open this panel, transcribe an existing audio file with Whisper, and review the action before it runs.",
        ))

        hotkey_box = QGroupBox("Activation")
        hotkey_form = QFormLayout(hotkey_box)
        self.edit_hotkey = QKeySequenceEdit(QKeySequence(shortcut), hotkey_box)
        self.edit_hotkey.setAccessibleName("Voice activation shortcut")
        self.edit_hotkey.setToolTip("Press the key combination that should open Voice Control")
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.edit_hotkey)
        self.btn_save_hotkey = QPushButton("Save shortcut")
        self.btn_save_hotkey.clicked.connect(self._save_hotkey)
        hotkey_row.addWidget(self.btn_save_hotkey)
        hotkey_row.addStretch()
        hotkey_form.addRow("Hotkey:", hotkey_row)
        hotkey_hint = QLabel(
            "UniFile does not capture the microphone. Choose a recorded audio/video file for Whisper, or type a transcript below."
        )
        hotkey_hint.setWordWrap(True)
        hotkey_hint.setStyleSheet(f"color: {theme['muted']}; font-size: 10px;")
        hotkey_form.addRow("", hotkey_hint)
        layout.addWidget(hotkey_box)

        transcript_box = QGroupBox("Command")
        transcript_layout = QVBoxLayout(transcript_box)
        self.edit_transcript = QTextEdit()
        self.edit_transcript.setPlaceholderText(
            'Try: “tag all 2024 Florida photos as vacation” or “show me large video files”'
        )
        self.edit_transcript.setAccessibleName("Voice command transcript")
        self.edit_transcript.setFixedHeight(78)
        transcript_layout.addWidget(self.edit_transcript)
        command_row = QHBoxLayout()
        self.btn_transcribe = QPushButton("Transcribe audio file…")
        self.btn_transcribe.setToolTip("Run the configured offline Whisper model on an existing audio/video file")
        self.btn_transcribe.clicked.connect(self._transcribe_audio)
        command_row.addWidget(self.btn_transcribe)
        self.chk_ai = QCheckBox("Allow configured AI fallback for unknown phrasing")
        self.chk_ai.setToolTip("Only enabled when you explicitly request it; local grammar remains the default")
        command_row.addWidget(self.chk_ai)
        command_row.addStretch()
        self.btn_parse = QPushButton("Parse command")
        self.btn_parse.setProperty("class", "primary")
        self.btn_parse.clicked.connect(self._parse_command)
        command_row.addWidget(self.btn_parse)
        transcript_layout.addLayout(command_row)
        layout.addWidget(transcript_box)

        result_box = QGroupBox("Review")
        result_layout = QVBoxLayout(result_box)
        self.lbl_intent = QLabel("No command parsed yet.")
        self.lbl_intent.setWordWrap(True)
        self.lbl_intent.setAccessibleName("Parsed voice intent")
        result_layout.addWidget(self.lbl_intent)
        self.lbl_preview = QLabel("")
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        result_layout.addWidget(self.lbl_preview)
        self.btn_execute = QPushButton("Run reviewed command")
        self.btn_execute.setProperty("class", "success")
        self.btn_execute.setEnabled(False)
        self.btn_execute.clicked.connect(self._execute_command)
        result_layout.addWidget(self.btn_execute)
        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setWordWrap(True)
        result_layout.addWidget(self.lbl_feedback)
        layout.addWidget(result_box, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save_hotkey(self):
        shortcut = self.edit_hotkey.keySequence().toString()
        self.hotkey_changed.emit(shortcut)
        self.lbl_feedback.setText(
            f"Activation shortcut saved: {shortcut or 'disabled'}"
        )

    def _parse_command(self):
        text = self.edit_transcript.toPlainText().strip()
        self._intent = self._parser.parse(text, use_llm=self.chk_ai.isChecked())
        intent = self._intent
        self.intent_ready.emit(intent)
        self.lbl_intent.setText(self._format_intent(intent))
        preview = ""
        if self._preview_callback:
            try:
                preview = str(self._preview_callback(intent) or "")
            except Exception as exc:
                preview = f"Preview unavailable: {exc}"
        self.lbl_preview.setText(preview)
        self.btn_execute.setEnabled(intent.action != "unknown")
        self.lbl_feedback.setText("")

    @staticmethod
    def _format_intent(intent: VoiceIntent) -> str:
        if intent.action == "scan":
            detail = f"Scan folder: {intent.path}"
        elif intent.action == "tag":
            detail = f"Apply tag “{intent.tag}” to: {intent.selector}"
        elif intent.action == "search":
            detail = f"Search: {intent.query}"
        else:
            detail = intent.reason
        confidence = f"{intent.confidence:.0%}" if intent.confidence else "—"
        return f"Action: {intent.action.upper()}  ·  confidence {confidence}\n{detail}"

    def _transcribe_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose audio or video for Whisper",
            "",
            "Audio/video (*.mp3 *.wav *.flac *.m4a *.ogg *.opus *.wma *.aac *.mp4 *.mkv *.avi *.mov *.webm);;All files (*)",
        )
        if not path:
            return
        if not os.path.isfile(path):
            self.lbl_feedback.setText("The selected audio file no longer exists.")
            return
        self.btn_transcribe.setEnabled(False)
        self.btn_parse.setEnabled(False)
        self.lbl_feedback.setText("Whisper is transcribing the selected file…")
        self._worker = _WhisperWorker(path, parent=self)
        self._worker.result_ready.connect(self._on_transcription)
        self._worker.finished.connect(self._on_transcription_finished)
        self._worker.start()

    def _on_transcription(self, result: dict):
        text = str(result.get("text", "") or "").strip()
        if text:
            self.edit_transcript.setPlainText(text)
            self.lbl_feedback.setText(
                f"Whisper transcription ready{(' (cached)' if result.get('cached') else '')}."
            )
        else:
            self.lbl_feedback.setText(
                f"Whisper could not transcribe the file: {result.get('error', 'no text returned')}"
            )

    def _on_transcription_finished(self):
        self.btn_transcribe.setEnabled(True)
        self.btn_parse.setEnabled(True)
        self._worker = None

    def _execute_command(self):
        if self._intent is None or self._intent.action == "unknown":
            return
        if not self._execute_callback:
            self.lbl_feedback.setText("No application executor is connected.")
            return
        try:
            result = self._execute_callback(self._intent)
            self.lbl_feedback.setText(str(result or "Command completed."))
        except Exception as exc:
            self.lbl_feedback.setText(f"Command failed: {exc}")

