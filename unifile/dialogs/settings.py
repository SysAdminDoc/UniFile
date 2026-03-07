"""UniFile dialogs — Settings dialogs (Ollama, Photo, Face, Model Manager)."""
import os, re, base64

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QDialog, QDialogButtonBox, QSpinBox,
    QListWidget, QListWidgetItem, QInputDialog, QSlider, QFrame,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPixmap, QIcon

from unifile.config import (
    get_active_theme, get_active_stylesheet
)
from unifile.ollama import (
    load_ollama_settings, save_ollama_settings, ollama_test_connection,
    _MODEL_CATALOG, _MODEL_CATALOG_MAP,
    _OLLAMA_DEFAULTS, _ollama_list_models, _ollama_pull_model,
    _is_ollama_server_running
)
from unifile.photos import (
    load_photo_settings, save_photo_settings, FaceDB,
    _PHOTO_FOLDER_PRESETS
)
from unifile.bootstrap import (
    HAS_REVERSE_GEOCODER, HAS_FACE_RECOGNITION, HAS_CV2
)
from unifile.workers import ModelListWorker, ModelPullWorker, ModelDeleteWorker, format_size


class OllamaSettingsDialog(QDialog):
    """Dialog for configuring Ollama LLM integration with model catalog."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ollama LLM Settings")
        self.setMinimumSize(560, 520)
        self.setStyleSheet(get_active_stylesheet())
        self.settings = load_ollama_settings()
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── URL ──────────────────────────────────────────────────────────────
        row_url = QHBoxLayout()
        row_url.addWidget(QLabel("Ollama URL:"))
        self.txt_url = QLineEdit(self.settings['url'])
        self.txt_url.setPlaceholderText("http://localhost:11434")
        row_url.addWidget(self.txt_url, 1)
        layout.addLayout(row_url)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"QFrame{{background-color:{_t['border']};max-height:1px;}}"); layout.addWidget(sep)

        # ── Model Catalog ─────────────────────────────────────────────────────
        layout.addWidget(QLabel("Select Model Preset:"))

        self.lst_models = QListWidget()
        self.lst_models.setAlternatingRowColors(True)
        self.lst_models.setStyleSheet(
            f"QListWidget {{ background:{_t['input_bg']}; border:1px solid {_t['border']}; border-radius:4px; }}"
            f"QListWidget::item {{ padding:6px 10px; color:{_t['fg']}; }}"
            f"QListWidget::item:selected {{ background:{_t['selection']}; color:{_t['fg_bright']}; }}"
            f"QListWidget::item:alternate {{ background:{_t['bg_alt']}; }}"
            f"QListWidget::item[group='true'] {{ background:{_t['header_bg']}; color:{_t['muted']}; font-weight:bold; padding:4px 6px; }}"
        )
        self.lst_models.setFixedHeight(220)

        current_group = None
        for entry in _MODEL_CATALOG:
            if entry['group'] != current_group:
                current_group = entry['group']
                header = QListWidgetItem(f"  ── {current_group} ──")
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(QColor("#7c9fc4"))
                header.setBackground(QColor("#111"))
                f = header.font(); f.setBold(True); header.setFont(f)
                header.setData(Qt.ItemDataRole.UserRole, None)
                self.lst_models.addItem(header)

            item = QListWidgetItem(f"  {entry['label']}")
            item.setData(Qt.ItemDataRole.UserRole, entry['name'])
            item.setToolTip(entry['description'])
            if entry.get('vision'):
                item.setForeground(QColor("#22d3ee"))  # cyan for vision models
            self.lst_models.addItem(item)

        self.lst_models.currentItemChanged.connect(self._on_model_selected)
        layout.addWidget(self.lst_models)

        # Description label under list
        self.lbl_desc = QLabel("")
        self.lbl_desc.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding: 2px 4px;")
        self.lbl_desc.setWordWrap(True)
        layout.addWidget(self.lbl_desc)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"QFrame{{background-color:{_t['border']};max-height:1px;}}"); layout.addWidget(sep2)

        # ── Advanced / Custom Override ────────────────────────────────────────
        adv_header = QHBoxLayout()
        adv_header.addWidget(QLabel("Advanced Settings:"))
        adv_header.addStretch()
        self.lbl_custom_model = QLabel("")
        self.lbl_custom_model.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        adv_header.addWidget(self.lbl_custom_model)
        layout.addLayout(adv_header)

        grid = QHBoxLayout()

        # Custom model name (manual override / locally installed not in catalog)
        col1 = QVBoxLayout()
        col1.addWidget(QLabel("Model name:"))
        self.cmb_model = QComboBox()
        self.cmb_model.setEditable(True)
        self.cmb_model.setInsertPolicy(QComboBox.InsertPolicy.InsertAtTop)
        self.cmb_model.setMinimumWidth(180)
        col1.addWidget(self.cmb_model)
        btn_refresh = QPushButton("↻ Refresh Installed")
        btn_refresh.clicked.connect(self._refresh_models)
        col1.addWidget(btn_refresh)
        grid.addLayout(col1)

        grid.addSpacing(12)

        # Numeric options
        col2 = QVBoxLayout()
        col2.addWidget(QLabel("Temperature:"))
        self.spn_temp = QSlider(Qt.Orientation.Horizontal)
        self.spn_temp.setRange(0, 10); self.spn_temp.setSingleStep(1)
        self.spn_temp.setValue(int(self.settings.get('temperature', 0.1) * 10))
        self.lbl_temp = QLabel(f"{self.settings.get('temperature', 0.1):.1f}")
        self.spn_temp.valueChanged.connect(lambda v: self.lbl_temp.setText(f"{v/10:.1f}"))
        r = QHBoxLayout(); r.addWidget(self.spn_temp, 1); r.addWidget(self.lbl_temp)
        col2.addLayout(r)

        col2.addWidget(QLabel("Max tokens (num_predict):"))
        self.spn_tokens = QSpinBox()
        self.spn_tokens.setRange(256, 8192); self.spn_tokens.setSingleStep(512)
        self.spn_tokens.setValue(self.settings.get('num_predict', 4096))
        col2.addWidget(self.spn_tokens)
        grid.addLayout(col2)

        grid.addSpacing(12)

        col3 = QVBoxLayout()
        col3.addWidget(QLabel("Batch size:"))
        self.spn_batch = QSpinBox()
        self.spn_batch.setRange(1, 10); self.spn_batch.setValue(self.settings.get('batch_size', 3))
        self.spn_batch.setToolTip("Folders per Ollama request. Lower = more reliable, higher = faster.")
        col3.addWidget(self.spn_batch)

        col3.addWidget(QLabel(" "))
        self.chk_think = QCheckBox("Enable thinking mode")
        self.chk_think.setChecked(self.settings.get('think', False))
        self.chk_think.setToolTip("Enable Qwen3.x chain-of-thought reasoning (slower but may improve accuracy)")
        col3.addWidget(self.chk_think)
        grid.addLayout(col3)

        grid.addSpacing(12)

        col4 = QVBoxLayout()
        col4.addWidget(QLabel("Vision:"))
        self.chk_vision = QCheckBox("Enable vision classification")
        self.chk_vision.setChecked(self.settings.get('vision_enabled', True))
        self.chk_vision.setToolTip("When a vision model is selected, send images for visual classification")
        col4.addWidget(self.chk_vision)

        col4.addWidget(QLabel("Max image size (MB):"))
        self.spn_vision_mb = QSpinBox()
        self.spn_vision_mb.setRange(1, 100); self.spn_vision_mb.setValue(self.settings.get('vision_max_file_mb', 20))
        self.spn_vision_mb.setToolTip("Skip images larger than this (MB)")
        col4.addWidget(self.spn_vision_mb)

        col4.addWidget(QLabel("Max resize (px):"))
        self.spn_vision_px = QSpinBox()
        self.spn_vision_px.setRange(256, 4096); self.spn_vision_px.setSingleStep(256)
        self.spn_vision_px.setValue(self.settings.get('vision_max_pixels', 1024))
        self.spn_vision_px.setToolTip("Resize images to this max dimension before sending to model")
        col4.addWidget(self.spn_vision_px)

        col4.addWidget(QLabel(" "))
        col4.addWidget(QLabel("Content Extraction:"))
        self.chk_content = QCheckBox("Read file content for AI naming")
        self.chk_content.setChecked(self.settings.get('content_extraction', True))
        self.chk_content.setToolTip("Extract text from PDFs, docs, code files for smarter naming")
        col4.addWidget(self.chk_content)
        col4.addWidget(QLabel("Content max chars:"))
        self.spn_content_chars = QSpinBox()
        self.spn_content_chars.setRange(200, 2000); self.spn_content_chars.setSingleStep(100)
        self.spn_content_chars.setValue(self.settings.get('content_max_chars', 800))
        col4.addWidget(self.spn_content_chars)

        col4.addWidget(QLabel(" "))
        col4.addWidget(QLabel("Image Conversion:"))
        self.chk_convert_heic = QCheckBox("Convert HEIC/HEIF -> JPG during scan")
        self.chk_convert_heic.setChecked(self.settings.get('convert_heic_to_jpg', True))
        self.chk_convert_heic.setToolTip("Auto-convert .heic/.heif files to .jpg (quality 95) before classification")
        col4.addWidget(self.chk_convert_heic)
        self.chk_convert_webp = QCheckBox("Convert WEBP -> JPG during scan")
        self.chk_convert_webp.setChecked(self.settings.get('convert_webp_to_jpg', True))
        self.chk_convert_webp.setToolTip("Auto-convert .webp files to .jpg (quality 95) before classification")
        col4.addWidget(self.chk_convert_webp)
        grid.addLayout(col4)

        layout.addLayout(grid)

        # Select the current model in the list (or populate the combobox)
        self._populate_models(self.settings['model'])
        self._select_catalog_model(self.settings['model'])

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"QFrame{{background-color:{_t['border']};max-height:1px;}}"); layout.addWidget(sep3)

        # ── Test / Pull / Status ──────────────────────────────────────────────
        row_test = QHBoxLayout()
        btn_test = QPushButton("Test Connection")
        btn_test.clicked.connect(self._test)
        row_test.addWidget(btn_test)
        self.btn_pull = QPushButton("Pull Model")
        self.btn_pull.setVisible(False)
        self.btn_pull.clicked.connect(self._pull_model)
        row_test.addWidget(self.btn_pull)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        row_test.addWidget(self.lbl_status, 1)
        layout.addLayout(row_test)

        # ── Model Manager ─────────────────────────────────────────────────────
        row_mgr = QHBoxLayout()
        btn_mgr = QPushButton("Model Manager...")
        btn_mgr.setToolTip("Browse, download, and delete Ollama models")
        btn_mgr.setStyleSheet(
            f"QPushButton {{ background: {_t['selection']}; color: {_t['fg_bright']}; border: 1px solid {_t['border']};"
            f"  border-radius: 4px; padding: 6px 16px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {_t['border_hover']}; }}"
        )
        btn_mgr.clicked.connect(self._open_model_manager)
        row_mgr.addWidget(btn_mgr)
        row_mgr.addStretch()
        layout.addLayout(row_mgr)

        # ── Save / Cancel ─────────────────────────────────────────────────────
        row_btns = QHBoxLayout()
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row_btns.addStretch()
        row_btns.addWidget(btn_save)
        row_btns.addWidget(btn_cancel)
        layout.addLayout(row_btns)

    def _on_model_selected(self, item):
        if item is None:
            return
        model_name = item.data(Qt.ItemDataRole.UserRole)
        if not model_name:
            return  # group header
        entry = _MODEL_CATALOG_MAP.get(model_name)
        if not entry:
            return
        # Apply catalog defaults to controls
        self.cmb_model.setCurrentText(model_name)
        self.spn_temp.setValue(int(entry['temperature'] * 10))
        self.spn_tokens.setValue(entry['num_predict'])
        self.spn_batch.setValue(entry['batch_size'])
        self.chk_think.setChecked(entry.get('think', False))
        self.lbl_desc.setText(entry['description'])
        self.lbl_custom_model.setText(f"Preset: {model_name}")

    def _select_catalog_model(self, model_name: str):
        """Highlight the catalog row matching model_name, if any."""
        for i in range(self.lst_models.count()):
            item = self.lst_models.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == model_name:
                self.lst_models.setCurrentItem(item)
                return
        # Not in catalog — just set combo text
        self.cmb_model.setCurrentText(model_name)

    def _populate_models(self, current_model: str = ''):
        """Fetch installed models from Ollama and fill the combobox."""
        self.cmb_model.clear()
        models = _ollama_list_models(self.txt_url.text().strip() or None)
        if models:
            self.cmb_model.addItems(models)
        if current_model and current_model not in models:
            self.cmb_model.insertItem(0, current_model)
        idx = self.cmb_model.findText(current_model)
        if idx >= 0:
            self.cmb_model.setCurrentIndex(idx)
        elif current_model:
            self.cmb_model.setCurrentText(current_model)

    def _refresh_models(self):
        current = self.cmb_model.currentText().strip()
        self._populate_models(current)
        count = self.cmb_model.count()
        self.lbl_status.setText(f"{count} model(s) installed." if count else "No models installed.")
        self.lbl_status.setStyleSheet(f"color: {get_active_theme()['muted']};")

    def _test(self):
        self.lbl_status.setText("Testing...")
        self.lbl_status.setStyleSheet("color: #f59e0b;")  # semantic: warning amber
        self.btn_pull.setVisible(False)
        self.lbl_status.repaint()
        model = self.cmb_model.currentText().strip()
        ok, msg, models = ollama_test_connection(self.txt_url.text().strip(), model)
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(f"color: {get_active_theme()['green'] if ok else '#ef4444'};")
        if models is not None:
            self._populate_models(model)
            model_base = model.split(':')[0]
            model_installed = any(model_base in m for m in models)
            self.btn_pull.setVisible(ok and not model_installed)

    def _pull_model(self):
        model = self.cmb_model.currentText().strip() or self.settings['model']
        self.lbl_status.setText(f"Pulling {model}... (this may take several minutes)")
        self.lbl_status.setStyleSheet("color: #f59e0b;")
        self.btn_pull.setEnabled(False)
        self.lbl_status.repaint()

        class _PullWorker(QThread):
            done = pyqtSignal(bool)
            def __init__(self, m): super().__init__(); self.m = m
            def run(self): self.done.emit(_ollama_pull_model(self.m))

        self._pull_worker = _PullWorker(model)
        self._pull_worker.done.connect(self._on_pull_done)
        self._pull_worker.start()

    def _on_pull_done(self, success):
        model = self.cmb_model.currentText().strip()
        if success:
            self.lbl_status.setText(f"✓ {model} pulled successfully.")
            self.lbl_status.setStyleSheet(f"color: {get_active_theme()['green']};")
            self._populate_models(model)
            self.btn_pull.setVisible(False)
        else:
            self.lbl_status.setText(f"Pull failed. Run manually: ollama pull {model}")
            self.lbl_status.setStyleSheet("color: #ef4444;")
        self.btn_pull.setEnabled(True)

    def _open_model_manager(self):
        dlg = ModelManagerDialog(url=self.txt_url.text().strip() or self.settings['url'], parent=self)
        dlg.exec()
        # Refresh combobox -- models may have been added/removed
        self._populate_models(self.cmb_model.currentText().strip())

    def _save(self):
        self.settings['url'] = self.txt_url.text().strip() or _OLLAMA_DEFAULTS['url']
        self.settings['model'] = self.cmb_model.currentText().strip() or _OLLAMA_DEFAULTS['model']
        self.settings['temperature'] = round(self.spn_temp.value() / 10, 1)
        self.settings['num_predict'] = self.spn_tokens.value()
        self.settings['batch_size'] = self.spn_batch.value()
        self.settings['think'] = self.chk_think.isChecked()
        self.settings['vision_enabled'] = self.chk_vision.isChecked()
        self.settings['vision_max_file_mb'] = self.spn_vision_mb.value()
        self.settings['vision_max_pixels'] = self.spn_vision_px.value()
        self.settings['content_extraction'] = self.chk_content.isChecked()
        self.settings['content_max_chars'] = self.spn_content_chars.value()
        self.settings['convert_heic_to_jpg'] = self.chk_convert_heic.isChecked()
        self.settings['convert_webp_to_jpg'] = self.chk_convert_webp.isChecked()
        save_ollama_settings(self.settings)
        self.accept()


class PhotoSettingsDialog(QDialog):
    """Dialog for configuring photo library organization features."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Photo Organization Settings")
        self.setMinimumSize(480, 420)
        self.setStyleSheet(get_active_stylesheet())
        self.settings = load_photo_settings()
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Master enable ────────────────────────────────────────────────────
        self.chk_enabled = QCheckBox("Enable Photo Organization Mode")
        self.chk_enabled.setChecked(self.settings['enabled'])
        self.chk_enabled.setStyleSheet(f"QCheckBox {{ color: {_t['green']}; font-size: 13px; font-weight: bold; }}")
        self.chk_enabled.toggled.connect(self._on_toggle)
        layout.addWidget(self.chk_enabled)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f"QFrame{{background-color:{_t['border']};max-height:1px;}}"); layout.addWidget(sep1)

        # ── Folder structure preset ──────────────────────────────────────────
        row_preset = QHBoxLayout()
        row_preset.addWidget(QLabel("Folder Structure:"))
        self.cmb_preset = QComboBox()
        self._preset_keys = list(_PHOTO_FOLDER_PRESETS.keys())
        for key in self._preset_keys:
            self.cmb_preset.addItem(_PHOTO_FOLDER_PRESETS[key]['label'])
        current_idx = self._preset_keys.index(self.settings.get('folder_preset', 'year_month'))
        self.cmb_preset.setCurrentIndex(current_idx)
        self.cmb_preset.currentIndexChanged.connect(self._on_preset_changed)
        row_preset.addWidget(self.cmb_preset, 1)
        layout.addLayout(row_preset)

        self.lbl_preview = QLabel()
        self.lbl_preview.setStyleSheet(f"color: {_t['sidebar_btn_active_fg']}; font-size: 11px; padding: 4px 8px; "
                                       f"background: {_t['input_bg']}; border-radius: 4px;")
        layout.addWidget(self.lbl_preview)
        self._update_preview()

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"QFrame{{background-color:{_t['border']};max-height:1px;}}"); layout.addWidget(sep2)

        # ── Feature toggles ──────────────────────────────────────────────────
        lbl_feat = QLabel("Features")
        lbl_feat.setStyleSheet(f"color: {_t['sidebar_profile_fg']}; font-size: 12px; font-weight: bold;")
        layout.addWidget(lbl_feat)

        self.chk_geocoding = QCheckBox("Reverse Geocoding (GPS -> City/Country)")
        self.chk_geocoding.setChecked(self.settings['geocoding_enabled'])
        if not HAS_REVERSE_GEOCODER:
            self.chk_geocoding.setToolTip("reverse_geocoder package not installed")
            self.chk_geocoding.setEnabled(False)
            self.chk_geocoding.setChecked(False)
        layout.addWidget(self.chk_geocoding)

        self.chk_blur = QCheckBox("Blur Detection (OpenCV quality scoring)")
        self.chk_blur.setChecked(self.settings['blur_detection_enabled'])
        if not HAS_CV2:
            self.chk_blur.setToolTip("opencv-python-headless package not installed")
            self.chk_blur.setEnabled(False)
            self.chk_blur.setChecked(False)
        layout.addWidget(self.chk_blur)

        row_thresh = QHBoxLayout()
        row_thresh.addSpacing(24)
        row_thresh.addWidget(QLabel("Blur threshold:"))
        self.spn_blur = QSpinBox()
        self.spn_blur.setRange(10, 1000)
        self.spn_blur.setValue(int(self.settings.get('blur_threshold', 100)))
        self.spn_blur.setToolTip("Laplacian variance below this value = blurry (default 100)")
        self.spn_blur.setFixedWidth(80)
        row_thresh.addWidget(self.spn_blur)
        row_thresh.addStretch()
        layout.addLayout(row_thresh)

        self.chk_scene = QCheckBox("Scene Tagging (AI labels: portrait, landscape, food...)")
        self.chk_scene.setChecked(self.settings['scene_tagging_enabled'])
        layout.addWidget(self.chk_scene)

        self.chk_face = QCheckBox("Face Recognition (detect & organize by person)")
        self.chk_face.setChecked(self.settings.get('face_recognition_enabled', False))
        if not HAS_FACE_RECOGNITION and not HAS_CV2:
            self.chk_face.setToolTip("Requires face_recognition or opencv-python-headless")
            self.chk_face.setEnabled(False)
            self.chk_face.setChecked(False)
        elif not HAS_FACE_RECOGNITION:
            self.chk_face.setToolTip("face_recognition not installed - will use OpenCV face count only (no identity matching)")
        layout.addWidget(self.chk_face)

        row_face = QHBoxLayout()
        row_face.addSpacing(24)
        self.btn_face_mgr = QPushButton("Manage Faces...")
        self.btn_face_mgr.setFixedWidth(140)
        self.btn_face_mgr.setEnabled(HAS_FACE_RECOGNITION)
        if not HAS_FACE_RECOGNITION:
            self.btn_face_mgr.setToolTip("Requires face_recognition library for identity management")
        self.btn_face_mgr.clicked.connect(self._open_face_manager)
        row_face.addWidget(self.btn_face_mgr)
        row_face.addStretch()
        layout.addLayout(row_face)

        self.chk_enhanced = QCheckBox("Enhanced AI Descriptions (richer vision prompts)")
        self.chk_enhanced.setChecked(self.settings['enhanced_descriptions'])
        layout.addWidget(self.chk_enhanced)

        layout.addStretch()

        # ── Status bar ───────────────────────────────────────────────────────
        deps = []
        if HAS_REVERSE_GEOCODER:
            deps.append("reverse_geocoder")
        if HAS_CV2:
            deps.append("OpenCV")
        if HAS_FACE_RECOGNITION:
            deps.append("face_recognition")
        dep_text = f"Available: {', '.join(deps)}" if deps else "No optional photo packages installed"
        lbl_deps = QLabel(dep_text)
        lbl_deps.setStyleSheet(f"color: {_t['disabled']}; font-size: 10px;")
        layout.addWidget(lbl_deps)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._save_and_close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._on_toggle(self.chk_enabled.isChecked())

    def _on_toggle(self, checked):
        for w in (self.cmb_preset, self.chk_geocoding, self.chk_blur,
                  self.spn_blur, self.chk_scene, self.chk_face,
                  self.btn_face_mgr, self.chk_enhanced):
            w.setEnabled(checked)
        if not HAS_REVERSE_GEOCODER:
            self.chk_geocoding.setEnabled(False)
        if not HAS_CV2:
            self.chk_blur.setEnabled(False)
            self.spn_blur.setEnabled(False)
        if not HAS_FACE_RECOGNITION and not HAS_CV2:
            self.chk_face.setEnabled(False)
        if not HAS_FACE_RECOGNITION:
            self.btn_face_mgr.setEnabled(False)

    def _on_preset_changed(self, idx):
        self._update_preview()

    def _update_preview(self):
        key = self._preset_keys[self.cmb_preset.currentIndex()]
        tmpl = _PHOTO_FOLDER_PRESETS[key]['template']
        if tmpl:
            example = tmpl.replace('{year}', '2024').replace('{month_name}', 'January')
            example = example.replace('{day}', '15').replace('{city}', 'Denver')
            example = example.replace('{scene}', 'landscape')
            example = example.replace('{person}', 'Mom')
            self.lbl_preview.setText(f"Preview: Photos/ -> {example}photo.jpg")
        else:
            self.lbl_preview.setText("Preview: Photos/ -> photo.jpg")

    def _save_and_close(self):
        self.settings['enabled'] = self.chk_enabled.isChecked()
        self.settings['folder_preset'] = self._preset_keys[self.cmb_preset.currentIndex()]
        self.settings['geocoding_enabled'] = self.chk_geocoding.isChecked()
        self.settings['blur_detection_enabled'] = self.chk_blur.isChecked()
        self.settings['blur_threshold'] = float(self.spn_blur.value())
        self.settings['scene_tagging_enabled'] = self.chk_scene.isChecked()
        self.settings['face_recognition_enabled'] = self.chk_face.isChecked()
        self.settings['enhanced_descriptions'] = self.chk_enhanced.isChecked()
        save_photo_settings(self.settings)
        self.accept()

    def _open_face_manager(self):
        dlg = FaceManagerDialog(self)
        dlg.exec()


class FaceManagerDialog(QDialog):
    """Dialog to view, rename, and delete known face clusters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Face Manager")
        self.setObjectName("face_mgr")
        self.setMinimumSize(440, 400)
        _t = get_active_theme()
        self.setStyleSheet(f"""
            #face_mgr {{ background: {_t['bg_alt']}; }}
            #face_mgr QLabel {{ color: {_t['fg_bright']}; }}
            #face_mgr QListWidget {{ background: {_t['input_bg']}; color: {_t['fg_bright']}; border: 1px solid {_t['border']};
                                     border-radius: 6px; font-size: 12px; }}
            #face_mgr QListWidget::item {{ padding: 6px; border-bottom: 1px solid {_t['border']}; }}
            #face_mgr QListWidget::item:selected {{ background: {_t['selection']}; }}
            #face_mgr QPushButton {{ background: {_t['btn_bg']}; color: {_t['fg_bright']}; border: 1px solid {_t['border']};
                                     border-radius: 4px; padding: 6px 14px; }}
            #face_mgr QPushButton:hover {{ background: {_t['btn_hover']}; }}
            #face_mgr QPushButton:disabled {{ color: {_t['disabled']}; }}
            #face_mgr QSlider::groove:horizontal {{ background: {_t['btn_bg']}; height: 6px; border-radius: 3px; }}
            #face_mgr QSlider::handle:horizontal {{ background: {_t['sidebar_btn_active_fg']}; width: 14px; margin: -4px 0;
                                                     border-radius: 7px; }}
        """)
        self._face_db = FaceDB() if HAS_FACE_RECOGNITION else None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        if not HAS_FACE_RECOGNITION:
            warn = QLabel("face_recognition library not installed - face identity management unavailable.\n"
                          "Install with: pip install cmake dlib face_recognition")
            warn.setStyleSheet("color: #f38ba8; font-size: 11px; padding: 8px;")  # semantic: error
            warn.setWordWrap(True)
            layout.addWidget(warn)

        # ── Tolerance slider ────────────────────────────────────────────────
        row_tol = QHBoxLayout()
        row_tol.addWidget(QLabel("Match Tolerance:"))
        self.sld_tolerance = QSlider(Qt.Orientation.Horizontal)
        self.sld_tolerance.setRange(30, 90)
        tol_val = int((self._face_db.tolerance if self._face_db else 0.6) * 100)
        self.sld_tolerance.setValue(tol_val)
        self.sld_tolerance.valueChanged.connect(self._on_tolerance_changed)
        row_tol.addWidget(self.sld_tolerance, 1)
        self.lbl_tol = QLabel(f"{tol_val / 100:.2f}")
        self.lbl_tol.setFixedWidth(40)
        row_tol.addWidget(self.lbl_tol)
        layout.addLayout(row_tol)

        tol_hint = QLabel("Lower = stricter matching, higher = more lenient")
        tol_hint.setStyleSheet(f"color: {_t['disabled']}; font-size: 10px; margin-left: 4px;")
        layout.addWidget(tol_hint)

        # ── Face list ───────────────────────────────────────────────────────
        self.lst_faces = QListWidget()
        self.lst_faces.setIconSize(QSize(64, 64))
        layout.addWidget(self.lst_faces, 1)

        self._refresh_list()

        # ── Buttons ─────────────────────────────────────────────────────────
        row_btns = QHBoxLayout()
        btn_rename = QPushButton("Rename")
        btn_rename.clicked.connect(self._rename_face)
        row_btns.addWidget(btn_rename)
        btn_delete = QPushButton("Delete")
        btn_delete.setStyleSheet("QPushButton { color: #f38ba8; }")  # semantic: danger
        btn_delete.clicked.connect(self._delete_face)
        row_btns.addWidget(btn_delete)
        row_btns.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self._close_and_save)
        row_btns.addWidget(btn_close)
        layout.addLayout(row_btns)

    def _refresh_list(self):
        self.lst_faces.clear()
        if not self._face_db:
            return
        for face in self._face_db.get_all_summaries():
            text = f"{face['label']}  ({face['sample_count']} samples)"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, face['id'])
            if face.get('thumbnail'):
                try:
                    thumb_data = base64.b64decode(face['thumbnail'])
                    pixmap = QPixmap()
                    pixmap.loadFromData(thumb_data)
                    item.setIcon(QIcon(pixmap))
                except Exception:
                    pass
            self.lst_faces.addItem(item)

    def _on_tolerance_changed(self, val):
        self.lbl_tol.setText(f"{val / 100:.2f}")
        if self._face_db:
            self._face_db.set_tolerance(val / 100)

    def _rename_face(self):
        item = self.lst_faces.currentItem()
        if not item or not self._face_db:
            return
        face_id = item.data(Qt.ItemDataRole.UserRole)
        current_label = item.text().split('  (')[0]
        new_label, ok = QInputDialog.getText(self, "Rename Face", "New name:", text=current_label)
        if ok and new_label.strip():
            self._face_db.rename(face_id, new_label.strip())
            self._refresh_list()

    def _delete_face(self):
        item = self.lst_faces.currentItem()
        if not item or not self._face_db:
            return
        face_id = item.data(Qt.ItemDataRole.UserRole)
        self._face_db.delete(face_id)
        self._refresh_list()

    def _close_and_save(self):
        if self._face_db:
            self._face_db.save()
        self.accept()


class ModelManagerDialog(QDialog):
    """Full-featured Ollama model manager with tree view, download, and delete."""

    def __init__(self, url: str = None, parent=None):
        super().__init__(parent)
        self.url = url or load_ollama_settings()['url']
        self.setWindowTitle("Ollama Model Manager")
        self.setMinimumSize(720, 560)
        self.setStyleSheet(get_active_stylesheet())
        self._installed = {}  # name -> model_obj
        self._pull_worker = None
        self._delete_worker = None
        self._build_ui()
        self._load_models()

    def _build_ui(self):
        _t = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Ollama Model Manager")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {_t['fg_bright']};")
        hdr.addWidget(title)
        hdr.addStretch()
        self.lbl_server = QLabel("Checking server...")
        self.lbl_server.setStyleSheet("color: #f59e0b; font-size: 11px;")  # semantic: warning amber
        hdr.addWidget(self.lbl_server)
        layout.addLayout(hdr)

        # ── Summary ───────────────────────────────────────────────────────────
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(f"color: {_t['muted']}; font-size: 12px; padding: 2px 0;")
        layout.addWidget(self.lbl_summary)

        # ── Search ────────────────────────────────────────────────────────────
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("Filter models...")
        self.txt_filter.setClearButtonEnabled(True)
        self.txt_filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.txt_filter)

        # ── Tree Widget ───────────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Model", "Size", "Status", ""])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(True)
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background: {_t['input_bg']}; border: 1px solid {_t['border']}; border-radius: 4px; }}"
            f"QTreeWidget::item {{ padding: 4px 6px; color: {_t['fg']}; }}"
            f"QTreeWidget::item:alternate {{ background: {_t['bg_alt']}; }}"
            f"QTreeWidget::item:selected {{ background: {_t['selection']}; color: {_t['fg_bright']}; }}"
            f"QHeaderView::section {{ background: {_t['header_bg']}; color: {_t['muted']}; border: 1px solid {_t['border']};"
            f"  padding: 4px 8px; font-weight: bold; }}"
        )
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)

        # ── Progress Panel (hidden) ───────────────────────────────────────────
        self.progress_frame = QFrame()
        self.progress_frame.setStyleSheet(
            f"QFrame {{ background: {_t['header_bg']}; border: 1px solid {_t['border']}; border-radius: 6px; padding: 8px; }}"
        )
        self.progress_frame.setVisible(False)
        pf_lay = QVBoxLayout(self.progress_frame)
        pf_lay.setContentsMargins(10, 6, 10, 6)

        pf_top = QHBoxLayout()
        self.lbl_pull_name = QLabel("")
        self.lbl_pull_name.setStyleSheet(f"color: {_t['fg_bright']}; font-weight: bold;")
        pf_top.addWidget(self.lbl_pull_name)
        pf_top.addStretch()
        self.lbl_pull_bytes = QLabel("")
        self.lbl_pull_bytes.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        pf_top.addWidget(self.lbl_pull_bytes)
        pf_lay.addLayout(pf_top)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {_t['input_bg']}; border: 1px solid {_t['border']}; border-radius: 4px;"
            f"  height: 18px; text-align: center; color: {_t['fg']}; }}"
            f"QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f"  stop:0 {_t['accent']}; stop:1 {_t['sidebar_profile_fg']}); border-radius: 3px; }}"
        )
        pf_lay.addWidget(self.progress_bar)

        self.lbl_pull_status = QLabel("")
        self.lbl_pull_status.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        pf_lay.addWidget(self.lbl_pull_status)

        layout.addWidget(self.progress_frame)

        # ── Bottom Buttons ────────────────────────────────────────────────────
        row_btns = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self._load_models)
        row_btns.addWidget(btn_refresh)
        row_btns.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        row_btns.addWidget(btn_close)
        layout.addLayout(row_btns)

    # ── Data Loading ──────────────────────────────────────────────────────────
    def _load_models(self):
        self.lbl_summary.setText("Loading models...")
        self.lbl_server.setText("Connecting...")
        self.lbl_server.setStyleSheet("color: #f59e0b; font-size: 11px;")  # semantic: warning amber
        if hasattr(self, '_list_worker') and self._list_worker is not None:
            try: self._list_worker.finished.disconnect()
            except (TypeError, RuntimeError): pass
        self._list_worker = ModelListWorker(self.url)
        self._list_worker.finished.connect(self._on_models_loaded)
        self._list_worker.start()

    def _on_models_loaded(self, models: list):
        self._installed = {m['name']: m for m in models}

        if models or _is_ollama_server_running(self.url):
            self.lbl_server.setText("Connected")
            self.lbl_server.setStyleSheet(f"color: {get_active_theme()['green']}; font-size: 11px;")
        else:
            self.lbl_server.setText("Not connected")
            self.lbl_server.setStyleSheet("color: #ef4444; font-size: 11px;")

        total_bytes = sum(m.get('size', 0) for m in models)
        self.lbl_summary.setText(
            f"{len(models)} model{'s' if len(models) != 1 else ''} installed  --  "
            f"{format_size(total_bytes)} total disk usage"
        )
        self._populate_tree()

    # ── Tree Population ───────────────────────────────────────────────────────
    def _populate_tree(self):
        self.tree.clear()

        # Collect catalog groups
        groups = {}
        for entry in _MODEL_CATALOG:
            g = entry['group']
            if g not in groups:
                groups[g] = []
            groups[g].append(entry)

        # Track which installed models are in the catalog
        catalog_names = {e['name'] for e in _MODEL_CATALOG}
        non_catalog_installed = [n for n in self._installed if n not in catalog_names]

        for group_name, entries in groups.items():
            installed_in_group = sum(1 for e in entries if e['name'] in self._installed)
            group_item = QTreeWidgetItem(self.tree)
            count_txt = f"  ({installed_in_group}/{len(entries)} installed)" if installed_in_group else ""
            group_item.setText(0, f"{group_name}{count_txt}")
            group_item.setFirstColumnSpanned(True)
            f = group_item.font(0)
            f.setBold(True)
            group_item.setFont(0, f)
            is_vision = entries[0].get('vision', False)
            group_item.setForeground(0, QColor("#22d3ee" if is_vision else "#7c9fc4"))
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)

            for entry in entries:
                name = entry['name']
                installed = name in self._installed
                child = QTreeWidgetItem(group_item)
                child.setText(0, name)
                child.setData(0, Qt.ItemDataRole.UserRole, name)
                child.setToolTip(0, entry['description'])

                if installed:
                    m = self._installed[name]
                    child.setText(1, format_size(m.get('size', 0)))
                    child.setText(2, "Installed")
                    child.setForeground(0, QColor("#cdd6f4"))
                    child.setForeground(2, QColor("#4ade80"))
                    self._add_action_button(child, "Delete", name)
                else:
                    label = entry.get('label', '')
                    # Extract size hint from label like "~6.6 GB"
                    import re
                    size_match = re.search(r'~[\d.]+ [GMKT]B', label)
                    child.setText(1, size_match.group(0) if size_match else "")
                    child.setText(2, "Not installed")
                    child.setForeground(0, QColor("#666"))
                    child.setForeground(2, QColor("#666"))
                    self._add_action_button(child, "Download", name)

                if entry.get('vision'):
                    child.setForeground(0, QColor("#22d3ee") if installed else QColor("#1a8a9e"))

            if installed_in_group > 0:
                group_item.setExpanded(True)

        # Non-catalog installed models
        if non_catalog_installed:
            other_item = QTreeWidgetItem(self.tree)
            other_item.setText(0, f"Other Installed  ({len(non_catalog_installed)})")
            other_item.setFirstColumnSpanned(True)
            f = other_item.font(0)
            f.setBold(True)
            other_item.setFont(0, f)
            other_item.setForeground(0, QColor("#7c9fc4"))
            other_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            other_item.setExpanded(True)

            for name in sorted(non_catalog_installed):
                m = self._installed[name]
                child = QTreeWidgetItem(other_item)
                child.setText(0, name)
                child.setData(0, Qt.ItemDataRole.UserRole, name)
                child.setText(1, format_size(m.get('size', 0)))
                child.setText(2, "Installed")
                child.setForeground(0, QColor("#cdd6f4"))
                child.setForeground(2, QColor("#4ade80"))
                self._add_action_button(child, "Delete", name)

        self._apply_filter(self.txt_filter.text())

    def _add_action_button(self, item: QTreeWidgetItem, action: str, model: str):
        btn = QPushButton(action)
        btn.setFixedWidth(80)
        btn.setProperty("model", model)
        _t = get_active_theme()
        if action == "Download":
            btn.setStyleSheet(
                f"QPushButton {{ background: {_t['selection']}; color: {_t['fg_bright']}; border: 1px solid {_t['border']};"
                f"  border-radius: 3px; padding: 2px 8px; font-size: 11px; }}"
                f"QPushButton:hover {{ background: {_t['border_hover']}; }}"
                f"QPushButton:disabled {{ background: {_t['bg_alt']}; color: {_t['disabled']}; }}"
            )
            btn.clicked.connect(lambda checked, m=model: self._start_download(m))
        else:
            btn.setStyleSheet(
                "QPushButton { background: #4a1a1a; color: #ef4444; border: 1px solid #6b2c2c;"  # semantic: danger
                "  border-radius: 3px; padding: 2px 8px; font-size: 11px; }"
                "QPushButton:hover { background: #6b2c2c; color: #fca5a5; }"
                f"QPushButton:disabled {{ background: {_t['bg_alt']}; color: {_t['disabled']}; }}"
            )
            btn.clicked.connect(lambda checked, m=model: self._start_delete(m))
        self.tree.setItemWidget(item, 3, btn)

    # ── Filter ────────────────────────────────────────────────────────────────
    def _apply_filter(self, text: str):
        text = text.strip().lower()
        root = self.tree.invisibleRootItem()
        for gi in range(root.childCount()):
            group = root.child(gi)
            any_visible = False
            for ci in range(group.childCount()):
                child = group.child(ci)
                model_name = (child.data(0, Qt.ItemDataRole.UserRole) or '').lower()
                match = not text or text in model_name
                child.setHidden(not match)
                if match:
                    any_visible = True
            group.setHidden(not any_visible)

    # ── Download ──────────────────────────────────────────────────────────────
    def _start_download(self, model: str):
        if self._pull_worker and self._pull_worker.isRunning():
            return
        self._set_all_buttons_enabled(False)
        self.progress_frame.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_pull_name.setText(f"Downloading: {model}")
        self.lbl_pull_bytes.setText("")
        self.lbl_pull_status.setText("Starting download...")

        self._pull_worker = ModelPullWorker(model, self.url)
        self._pull_worker.progress.connect(self._on_pull_progress)
        self._pull_worker.log.connect(self._on_pull_log)
        self._pull_worker.finished.connect(self._on_pull_finished)
        self._pull_worker.start()

    def _on_pull_progress(self, completed: int, total: int, status: str):
        if total > 0:
            pct = int(completed * 100 / total)
            self.progress_bar.setValue(pct)
            self.lbl_pull_bytes.setText(f"{format_size(completed)} / {format_size(total)}")
        self.lbl_pull_status.setText(status)

    def _on_pull_log(self, msg: str):
        self.lbl_pull_status.setText(msg)

    def _on_pull_finished(self, success: bool, model: str):
        if success:
            self.lbl_pull_status.setText(f"{model} downloaded successfully!")
            self.lbl_pull_status.setStyleSheet(f"color: {get_active_theme()['green']}; font-size: 11px;")
            self.progress_bar.setValue(100)
        else:
            self.lbl_pull_status.setText(f"Download failed for {model}")
            self.lbl_pull_status.setStyleSheet("color: #ef4444; font-size: 11px;")
        self._set_all_buttons_enabled(True)
        self._load_models()

    # ── Delete ────────────────────────────────────────────────────────────────
    def _start_delete(self, model: str):
        if self._delete_worker and self._delete_worker.isRunning():
            return
        self._set_all_buttons_enabled(False)
        self.lbl_summary.setText(f"Deleting {model}...")
        self._delete_worker = ModelDeleteWorker(model, self.url)
        self._delete_worker.finished.connect(self._on_delete_finished)
        self._delete_worker.start()

    def _on_delete_finished(self, success: bool, model: str):
        self._set_all_buttons_enabled(True)
        if success:
            self.lbl_summary.setText(f"{model} deleted.")
        else:
            self.lbl_summary.setText(f"Failed to delete {model}")
        self._load_models()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _set_all_buttons_enabled(self, enabled: bool):
        root = self.tree.invisibleRootItem()
        for gi in range(root.childCount()):
            group = root.child(gi)
            for ci in range(group.childCount()):
                child = group.child(ci)
                w = self.tree.itemWidget(child, 3)
                if w:
                    w.setEnabled(enabled)
