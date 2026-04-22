"""UniFile — Main application window."""
import os, re, json, shutil, csv, time, math, subprocess, sys
from datetime import datetime
from pathlib import Path
from collections import Counter

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QCheckBox, QTextEdit, QHeaderView, QFileDialog, QAbstractItemView,
    QSlider, QMenu, QTreeWidget, QTreeWidgetItem, QDialog, QDialogButtonBox, QSpinBox,
    QListWidget, QListWidgetItem, QInputDialog, QSplitter, QMessageBox, QFrame,
    QProgressBar, QScrollArea, QSystemTrayIcon, QStackedWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QMimeData, QUrl, QTimer, QSize
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QAction, QPixmap, QImage, QTextCursor, QIcon

from unifile.config import (
    _APP_DATA_DIR, _CUSTOM_CATS_FILE, _LAST_CONFIG_FILE,
    CONF_HIGH, CONF_MEDIUM, DARK_STYLE,
    THEMES, get_active_theme, get_active_stylesheet, load_theme_name, _build_theme_qss
)
from unifile.cache import (
    cache_lookup, cache_store, cache_clear, cache_count,
    save_correction, check_corrections, load_corrections,
    save_undo_log, load_undo_log, clear_undo_log, _load_undo_stack, _save_undo_stack,
    append_csv_log, create_backup_snapshot,
    export_rules_bundle, import_rules_bundle
)
from unifile.categories import (
    CATEGORIES, BUILTIN_CATEGORIES, get_all_categories, get_all_category_names,
    load_custom_categories, save_custom_categories, _CategoryIndex
)
from unifile.naming import _beautify_name, _smart_name
from unifile.classifier import tiered_classify, _SCAN_FILTERS
from unifile.ollama import load_ollama_settings, save_ollama_settings
from unifile.photos import (
    load_photo_settings, save_photo_settings, FaceDB,
    load_face_db, save_face_db, _convert_image_to_jpg,
    _PHOTO_FOLDER_PRESETS
)
from unifile.duplicates import ProgressiveDuplicateDetector, ConflictResolver
from unifile.files import _load_pc_categories, _save_pc_categories
from unifile.engine import RuleEngine, EventGrouper, ScheduleManager, RenameTemplateEngine
from unifile.plugins import PluginManager, ProfileManager, CategoryPresetManager, CloudPathResolver
from unifile.models import RenameItem, CategorizeItem, FileItem
from unifile.workers import (
    ScanAepWorker, ScanCategoryWorker, ScanLLMWorker, OllamaSetupWorker,
    ApplyAepWorker, ApplyCatWorker, ApplyFilesWorker,
    ScanFilesWorker, ScanFilesLLMWorker,
    safe_merge_move, format_size
)
from unifile.dialogs import (
    CustomCategoriesDialog, DestTreeDialog, OllamaSettingsDialog,
    PhotoSettingsDialog, FaceManagerDialog, ModelManagerDialog,
    TemplateBuilderWidget, PCCategoryEditorDialog, _FileBrowserDialog,
    UndoBatchDialog, BeforeAfterDialog, DuplicateCompareDialog,
    EventGroupDialog, RuleEditorDialog, ScheduleDialog,
    UndoTimelineDialog, PluginManagerDialog, CleanupToolsDialog,
    CsvRulesDialog,
    DuplicateFinderDialog, CleanupPanel, DuplicatePanel,
    ProtectedPathsDialog, ThemePickerDialog, WatchHistoryDialog
)
from unifile.dialogs.tag_library import TagLibraryPanel
from unifile.dialogs.media_lookup import MediaLookupPanel
from unifile.widgets import (
    CategoryBarChart, FlowLayout, ThumbnailLoader, ThumbnailCard,
    _ThumbSignals, PhotoMapWidget, WatchSettingsDialog, WatchModeManager,
    FilePreviewPanel, _load_watch_settings, _save_watch_settings
)
from unifile.dialogs import RelationshipGraphWidget
from unifile.profiles import (
    get_active_profile, get_active_profile_name, get_profile_names,
    set_active_profile, BUILTIN_PROFILES
)
from unifile.scan_mixin import ScanMixin
from unifile.apply_mixin import ApplyMixin
from unifile.theme_mixin import ThemeMixin
from unifile.learning import get_learner
from unifile.engine import CategoryBalancer
from unifile import __version__

class UniFile(ScanMixin, ApplyMixin, ThemeMixin, QMainWindow):
    OP_AEP   = 0
    OP_CAT   = 1
    OP_SMART = 2   # Categorize + rename from project files (combined)
    OP_FILES = 3   # PC File Organizer
    OP_TAGS  = 4   # Tag Library (from TagStudio integration)
    OP_MEDIA = 5   # Media Lookup (from mnamer integration)
    OP_VLIB  = 6   # Virtual Library (non-destructive overlay)

    # Classification method → display color (shared by Categorize + PC Files modes)
    _METHOD_COLORS_CAT = {
        'extension': '#a78bfa', 'keyword': '#4ade80', 'fuzzy': '#facc15',
        'metadata': '#38bdf8', 'metadata+keyword': '#2dd4bf',
        'keyword_low': '#f97316', 'Manual': '#38bdf8',
        'envato_api': '#f472b6', 'composition': '#a3e635',
        'context': '#e879f9', 'llm': '#f472b6', 'learned': '#06b6d4',
    }
    _METHOD_COLORS_FILES = {
        'extension': '#a78bfa', 'folder_contents': '#38bdf8',
        'llm': '#f472b6', 'vision': '#22d3ee', 'rule_fallback': '#f59e0b',
        'no_ext_match': '#6b7280', 'folder_no_match': '#6b7280',
    }

    @staticmethod
    def _confidence_bg(conf: float, alpha: int = 15) -> 'QColor':
        """Smooth heatmap: red(0) → amber(50) → green(100)."""
        t = max(0.0, min(100.0, conf)) / 100.0
        if t < 0.5:
            f = t / 0.5
            r, g, b = int(239 + (245 - 239) * f), int(68 + (158 - 68) * f), int(68 + (11 - 68) * f)
        else:
            f = (t - 0.5) / 0.5
            r, g, b = int(245 + (74 - 245) * f), int(158 + (222 - 158) * f), int(11 + (128 - 11) * f)
        return QColor(r, g, b, alpha)

    @staticmethod
    def _confidence_text_color(conf: float) -> str:
        """Smooth text color: red(0) → amber(50) → green(100)."""
        t = max(0.0, min(100.0, conf)) / 100.0
        if t < 0.5:
            f = t / 0.5
            return f"#{int(239 + (245 - 239) * f):02x}{int(68 + (158 - 68) * f):02x}{int(68 + (11 - 68) * f):02x}"
        f = (t - 0.5) / 0.5
        return f"#{int(245 + (74 - 245) * f):02x}{int(158 + (222 - 158) * f):02x}{int(11 + (128 - 11) * f):02x}"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"UniFile v{__version__}")
        self.setMinimumSize(1120, 740)
        self.aep_items  = []
        self.cat_items  = []
        self.file_items = []           # PC File Organizer items
        self._pc_categories = _load_pc_categories()   # loaded once, re-loaded on editor close
        self._rename_counters = {}     # per-category counter for {counter} token
        self._cat_unmatched = 0
        self.undo_ops = []
        self.settings = QSettings("UniFile", "UniFile")
        self._ollama_ready = False

        # Enable drag & drop
        self.setAcceptDrops(True)

        self._build_ui()
        self._load_settings()

        # Launch Ollama auto-setup in background
        self._start_ollama_setup()

    # ═══ DRAG & DROP ═══════════════════════════════════════════════════════════
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        paths = [u.toLocalFile() for u in urls if u.toLocalFile()]
        if not paths:
            return
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p)]
        # Directory drop — set as source
        if dirs:
            path = dirs[0]
            op = self.cmb_op.currentIndex()
            if op == self.OP_FILES and hasattr(self, 'txt_pc_src'):
                self.txt_pc_src.setText(path)
            else:
                self.txt_src.setText(path)
            self._log(f"Dropped folder: {path}")
        # File drop — add to tag library if open, otherwise log
        if files:
            stack_idx = self.content_stack.currentIndex()
            if stack_idx == 3 and hasattr(self, 'tag_lib_panel'):
                lib = self.tag_lib_panel._lib
                if lib and lib.is_open:
                    count = lib.add_entries_bulk(files)
                    self.tag_lib_panel._refresh_entries()
                    self._log(f"Added {count} file(s) to tag library via drag-and-drop")
                    return
            self._log(f"Dropped {len(files)} file(s)")

    # ═══ SETTINGS PERSISTENCE ═════════════════════════════════════════════════
    def _load_settings(self):
        src = self.settings.value("last_source", "")
        dst = self.settings.value("last_dest", "")
        op = self.settings.value("last_op", 0, type=int)
        thresh = self.settings.value("confidence_threshold", 0, type=int)
        use_llm = self.settings.value("use_llm", True, type=bool)
        scan_depth = self.settings.value("scan_depth", 0, type=int)
        if src: self.txt_src.setText(src)
        if dst: self.txt_dst.setText(dst)
        if op < self.cmb_op.count(): self.cmb_op.setCurrentIndex(op)
        self.sld_conf.setValue(thresh)
        self.chk_llm.setChecked(use_llm)
        self.spn_depth.setValue(scan_depth)
        type_filter = self.settings.value("type_filter", "All Files")
        idx_tf = self.cmb_type_filter.findText(type_filter)
        if idx_tf >= 0:
            self.cmb_type_filter.setCurrentIndex(idx_tf)
        # Initialise PC source panel to Desktop (index 0)
        self.cmb_pc_src.setCurrentIndex(0)
        self._on_pc_src_changed(0)

    def _save_settings(self):
        self.settings.setValue("last_source", self.txt_src.text())
        self.settings.setValue("last_dest", self.txt_dst.text())
        self.settings.setValue("last_op", self.cmb_op.currentIndex())
        self.settings.setValue("confidence_threshold", self.sld_conf.value())
        self.settings.setValue("use_llm", self.chk_llm.isChecked())
        self.settings.setValue("scan_depth", self.spn_depth.value())
        self.settings.setValue("type_filter", self.cmb_type_filter.currentText())

    # ═══ OLLAMA AUTO-SETUP ════════════════════════════════════════════════════
    def _start_ollama_setup(self):
        """Launch background Ollama setup (install + pull model) on app start."""
        self._log("Ollama LLM: initializing...")
        s = load_ollama_settings()
        self._ollama_worker = OllamaSetupWorker(s['model'], s['url'])
        self._ollama_worker.log.connect(self._log)
        self._ollama_worker.status.connect(self._on_ollama_status)
        self._ollama_worker.finished.connect(self._on_ollama_ready)
        self._ollama_worker.start()

    def _on_ollama_status(self, msg):
        self.lbl_llm_status.setText(msg)
        color = '#4ade80' if 'ready' in msg.lower() or ':' in msg and 'failed' not in msg.lower() \
                else '#ef4444' if 'failed' in msg.lower() else '#f59e0b'
        self.lbl_llm_status.setStyleSheet(f"color: {color}; font-size: 11px;")
        if hasattr(self, 'lbl_workspace_ai'):
            state = "AI READY" if color == '#4ade80' else "AI UNAVAILABLE" if color == '#ef4444' else "AI CHECKING"
            bg = get_active_theme()['selection'] if color != '#ef4444' else '#3b1f24'
            border = get_active_theme()['border'] if color != '#ef4444' else '#6b2737'
            self.lbl_workspace_ai.setText(state)
            self.lbl_workspace_ai.setStyleSheet(
                f"background: {bg}; color: {color}; border: 1px solid {border}; "
                "border-radius: 999px; padding: 4px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
            )
        if hasattr(self, 'lbl_workspace_meta'):
            self._refresh_workspace_copy()

    def _on_ollama_ready(self, success):
        self._ollama_ready = success
        _t = get_active_theme()
        if success:
            s = load_ollama_settings()
            self.lbl_llm_status.setText(f"LLM: {s['model']}")
            self.lbl_llm_status.setStyleSheet(f"color: {_t['green']}; font-size: 11px;")
            self.lbl_ollama.setText("● Ollama")
            self.lbl_ollama.setStyleSheet(f"color: {_t['green']}; font-size: 11px; font-family: monospace;")
            self.lbl_ollama.setToolTip(f"Connected — model: {s['model']}")
            self._log("Ollama LLM: ready")
        else:
            self.lbl_llm_status.setText("LLM: unavailable")
            self.lbl_llm_status.setStyleSheet("color: #ef4444; font-size: 11px;")
            self.lbl_ollama.setText("● Ollama")
            self.lbl_ollama.setStyleSheet("color: #ef4444; font-size: 11px; font-family: monospace;")
            self.lbl_ollama.setToolTip("Ollama not available — rule-based engine will be used")
            self._log("Ollama LLM: not available (rule-based engine will be used)")
        if hasattr(self, 'lbl_workspace_meta'):
            self._refresh_workspace_copy()

    # ═══ BUILD UI ═════════════════════════════════════════════════════════════

    def _build_ui(self):
        _t = get_active_theme()

        # ── Shared inline button styles ─────────────────────────────────
        _SEC_BTN = (
            f"QPushButton {{ font-size: 11px; padding: 2px 12px; background: {_t['bg_alt']};"
            f"color: {_t['sidebar_btn_active_fg']}; border: 1px solid {_t['border']}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}"
            f"QPushButton:disabled {{ color: {_t['muted']}; background: {_t['header_bg']}; border-color: {_t['btn_bg']}; }}")
        _TOGGLE_BTN = (
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {_t['bg_alt']};"
            f"color: {_t['sidebar_btn_active_fg']}; border: 1px solid {_t['border']}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}"
            f"QPushButton:checked {{ background: {_t['selection']}; color: {_t['fg_bright']}; border-color: {_t['accent']}; }}")

        cw = QWidget(); self.setCentralWidget(cw)
        root = QHBoxLayout(cw)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ══════════════════════════════════════════════════════════════════════
        #  LEFT SIDEBAR — Navigation panel (Czkawka/Krokiet-inspired)
        # ══════════════════════════════════════════════════════════════════════
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        sidebar.setStyleSheet(
            f"QWidget#sidebar {{ background: {_t['sidebar_bg']}; border-right: 1px solid {_t['sidebar_border']}; }}"
        )
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)

        # ── Brand header ──────────────────────────────────────────────────
        brand_w = QWidget()
        brand_w.setFixedHeight(64)
        brand_w.setStyleSheet(f"background: {_t['sidebar_brand']}; border-bottom: 1px solid {_t['sidebar_border']};")
        self._brand_w = brand_w
        brand_lay = QVBoxLayout(brand_w)
        brand_lay.setContentsMargins(16, 11, 16, 10)
        brand_lay.setSpacing(2)
        lbl_brand = QLabel("UniFile")
        self.lbl_brand = lbl_brand
        lbl_brand.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 16px; font-weight: 700; letter-spacing: -0.5px;"
            "background: transparent;")
        brand_lay.addWidget(lbl_brand)
        lbl_ver = QLabel(f"v{__version__}  •  review-first organization")
        self.lbl_brand_meta = lbl_ver
        lbl_ver.setStyleSheet(
            f"color: {_t['muted']}; font-size: 10px; font-weight: 600; background: transparent;")
        brand_lay.addWidget(lbl_ver)
        sb_lay.addWidget(brand_w)

        # ── Sidebar nav button style ─────────────────────────────────────
        _NAV_BTN = (
            f"QPushButton {{ background: transparent; color: {_t['sidebar_btn']}; border: none;"
            f"border-left: 3px solid transparent; padding: 10px 14px; font-size: 12px;"
            f"font-weight: 500; text-align: left; }}"
            f"QPushButton:hover {{ background: {_t['sidebar_btn_hover_bg']}; color: {_t['fg']};"
            f"border-left: 3px solid {_t['sidebar_btn_hover_border']}; }}"
            f"QPushButton:checked {{ background: {_t['sidebar_btn_active_bg']}; color: {_t['sidebar_btn_active_fg']};"
            f"border-left: 3px solid {_t['sidebar_btn_active_border']}; font-weight: 600; }}"
        )
        _NAV_SECTION = (
            f"color: {_t['sidebar_section']}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;"
            f"padding: 12px 16px 4px 16px; background: transparent;"
        )

        # ── ORGANIZE section ─────────────────────────────────────────────
        lbl_sec_org = QLabel("ORGANIZE")
        lbl_sec_org.setStyleSheet(_NAV_SECTION)
        sb_lay.addWidget(lbl_sec_org)
        self._nav_section_labels = [lbl_sec_org]

        self._nav_buttons = []
        _nav_items_organize = [
            ("Rename .aep Folders",           self.OP_AEP),
            ("Categorize Folders",            self.OP_CAT),
            ("Categorize + Smart Rename",     self.OP_SMART),
            ("PC File Organizer",             self.OP_FILES),
            ("Tag Library",                   self.OP_TAGS),
            ("Media Lookup",                  self.OP_MEDIA),
            ("Virtual Library",               self.OP_VLIB),
        ]
        for label, op_idx in _nav_items_organize:
            btn = QPushButton(f"  {label}")
            btn.setCheckable(True)
            btn.setStyleSheet(_NAV_BTN)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=op_idx: self._on_sidebar_nav(idx))
            sb_lay.addWidget(btn)
            self._nav_buttons.append(('op', op_idx, btn))

        # ── TOOLS section ────────────────────────────────────────────────
        lbl_sec_tools = QLabel("TOOLS")
        lbl_sec_tools.setStyleSheet(_NAV_SECTION)
        sb_lay.addWidget(lbl_sec_tools)
        self._nav_section_labels.append(lbl_sec_tools)

        _nav_items_tools = [
            ("Duplicate Finder",  'duplicates', None),
            ("Empty Folders",     'cleanup', 0),
            ("Empty Files",       'cleanup', 1),
            ("Temp / Junk Files", 'cleanup', 2),
            ("Broken Files",      'cleanup', 3),
            ("Big Files",         'cleanup', 4),
            ("Old Downloads",     'cleanup', 5),
        ]
        for label, tool_type, tab_idx in _nav_items_tools:
            btn = QPushButton(f"  {label}")
            btn.setCheckable(True)
            btn.setStyleSheet(_NAV_BTN)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked, t=tool_type, ti=tab_idx: self._on_sidebar_tool(t, ti))
            sb_lay.addWidget(btn)
            self._nav_buttons.append(('tool', (tool_type, tab_idx), btn))

        sb_lay.addStretch()

        # ── Profile selector (bottom of sidebar) ─────────────────────────
        prof_w = QWidget()
        prof_w.setStyleSheet("background: transparent;")
        prof_lay = QVBoxLayout(prof_w)
        prof_lay.setContentsMargins(12, 8, 12, 4)
        prof_lay.setSpacing(4)
        lbl_prof = QLabel("PROFILE")
        lbl_prof.setStyleSheet(
            f"color: {_t['sidebar_section']}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;"
            "background: transparent;")
        self._nav_section_labels.append(lbl_prof)
        prof_lay.addWidget(lbl_prof)
        self.cmb_profile = QComboBox()
        self.cmb_profile.addItems(get_profile_names())
        self.cmb_profile.setToolTip(
            "Scan profile — changes categories, LLM persona, and scan behavior.\n"
            "Design Assets = original behavior for creative marketplace files."
        )
        self.cmb_profile.setStyleSheet(
            f"QComboBox {{ background: {_t['sidebar_profile_bg']}; color: {_t['sidebar_profile_fg']}; "
            f"border: 1px solid {_t['sidebar_profile_border']};"
            f"border-radius: 4px; padding: 6px 10px; font-size: 11px; font-weight: bold; }}"
            f"QComboBox:hover {{ border-color: {_t['sidebar_profile_fg']}; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {_t['sidebar_profile_bg']}; color: {_t['fg']};"
            f"selection-background-color: {_t['selection']}; border: 1px solid {_t['sidebar_profile_border']}; }}")
        idx_prof = self.cmb_profile.findText(get_active_profile_name())
        if idx_prof >= 0:
            self.cmb_profile.setCurrentIndex(idx_prof)
        self.cmb_profile.currentTextChanged.connect(self._on_profile_changed)
        prof_lay.addWidget(self.cmb_profile)
        sb_lay.addWidget(prof_w)

        # ── LLM status indicator (bottom of sidebar) ─────────────────────
        llm_w = QWidget()
        llm_w.setFixedHeight(40)
        llm_w.setStyleSheet(f"background: {_t['sidebar_brand']}; border-top: 1px solid {_t['sidebar_border']};")
        self._llm_w = llm_w
        llm_lay = QHBoxLayout(llm_w)
        llm_lay.setContentsMargins(14, 0, 14, 0)
        self.lbl_llm_status = QLabel("LLM: checking...")
        self.lbl_llm_status.setStyleSheet(
            "color: #f59e0b; font-size: 10px; background: transparent;")
        llm_lay.addWidget(self.lbl_llm_status)
        sb_lay.addWidget(llm_w)

        root.addWidget(sidebar)

        # Select first nav button (AEP rename) by default
        if self._nav_buttons:
            self._nav_buttons[0][2].setChecked(True)

        # ══════════════════════════════════════════════════════════════════════
        #  RIGHT CONTENT AREA
        # ══════════════════════════════════════════════════════════════════════
        right_panel = QWidget()
        right_col = QVBoxLayout(right_panel)
        right_col.setSpacing(0)
        right_col.setContentsMargins(0, 0, 0, 0)

        # ── Menu bar ─────────────────────────────────────────────────────
        mbar = self.menuBar()
        menu_tools = mbar.addMenu("Settings")
        menu_tools.addAction("Edit Categories", self._open_custom_cats)
        menu_tools.addAction("Envato API Key", self._set_envato_key)
        menu_tools.addAction("Ollama LLM", self._open_ollama_settings)
        menu_tools.addSeparator()
        menu_tools.addAction("Import Rules", self._import_rules)
        menu_tools.addAction("Export Rules", self._export_rules)
        menu_tools.addSeparator()
        menu_tools.addAction("Clear Cache", self._clear_cache)
        if sys.platform == 'win32':
            menu_tools.addSeparator()
            menu_tools.addAction("Register Shell Extension", self._register_shell_extension)
            menu_tools.addAction("Unregister Shell Extension", self._unregister_shell_extension)
        menu_tools.addSeparator()
        menu_tools.addAction("Classification Rules...", self._open_rule_editor)
        if sys.platform == 'win32':
            menu_tools.addAction("Scheduled Scans...", self._open_schedule_dialog)
        menu_tools.addAction("Plugins...", self._open_plugin_manager)
        menu_tools.addSeparator()
        menu_tools.addAction("Protected Paths...", self._open_protected_paths)
        menu_tools.addAction("Color Theme...", self._open_theme_picker)
        menu_tools.addSeparator()
        menu_ai = menu_tools.addMenu("AI & Intelligence")
        menu_ai.addAction("AI Providers...", self._open_ai_providers)
        menu_ai.addAction("Whisper Audio...", self._open_whisper_settings)
        menu_ai.addAction("Semantic Search...", self._open_semantic_settings)
        menu_ai.addAction("Metadata Embedding...", self._open_embedding_settings)
        menu_ai.addAction("Adaptive Learning...", self._open_learning_stats)
        self.menu_presets = menu_tools.addMenu("Category Presets")
        self._refresh_presets_menu()

        self.menu_profiles = mbar.addMenu("Profiles")
        self.menu_profiles.addAction("Save Profile...", self._save_profile)
        self.menu_profiles.addAction("Manage Profiles...", self._manage_profiles)
        self.menu_profiles.addSeparator()
        self._refresh_profiles_menu()

        menu_cleanup = mbar.addMenu("Tools")
        menu_cleanup.addAction("Duplicate Finder...",
                               lambda: self._open_cleanup_tab(mode='duplicates'))
        menu_cleanup.addAction("Cleanup Tools...", self._open_cleanup_tools)
        menu_cleanup.addSeparator()
        menu_cleanup.addAction("Find Empty Folders", lambda: self._open_cleanup_tab(0))
        menu_cleanup.addAction("Find Empty Files", lambda: self._open_cleanup_tab(1))
        menu_cleanup.addAction("Find Temp/Junk Files", lambda: self._open_cleanup_tab(2))
        menu_cleanup.addAction("Find Broken Files", lambda: self._open_cleanup_tab(3))
        menu_cleanup.addAction("Find Big Files", lambda: self._open_cleanup_tab(4))
        menu_cleanup.addAction("Find Old Downloads", lambda: self._open_cleanup_tab(5))
        menu_cleanup.addSeparator()
        menu_cleanup.addAction("Watch History...", self._open_watch_history)
        menu_cleanup.addSeparator()
        menu_cleanup.addAction("Sort Rules...", self._open_sort_rules)

        # ── Top Action Bar ───────────────────────────────────────────────
        action_bar = QWidget()
        self._themed_action_bar = action_bar
        action_bar.setMinimumHeight(88)
        action_bar.setStyleSheet(
            f"QWidget#action_bar {{ background: {_t['header_bg']}; border-bottom: 1px solid {_t['btn_bg']}; }}")
        action_bar.setObjectName("action_bar")
        action_wrap = QVBoxLayout(action_bar)
        action_wrap.setContentsMargins(16, 10, 16, 10)
        action_wrap.setSpacing(8)

        action_meta = QHBoxLayout()
        action_meta.setSpacing(8)
        self.lbl_action_kicker = QLabel("WORKFLOW ACTIONS")
        self.lbl_action_kicker.setStyleSheet(
            f"color: {_t['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;"
        )
        action_meta.addWidget(self.lbl_action_kicker)
        self.lbl_action_hint = QLabel(
            "Build a plan first, review uncertain matches, then apply with undo close by."
        )
        self.lbl_action_hint.setWordWrap(True)
        self.lbl_action_hint.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px;"
        )
        action_meta.addWidget(self.lbl_action_hint, 1)
        action_wrap.addLayout(action_meta)

        ab_lay = QHBoxLayout()
        ab_lay.setSpacing(10)

        self.btn_scan = QPushButton("Scan")
        self.btn_scan.setProperty("class", "primary")
        self.btn_scan.setFixedHeight(38)
        self.btn_scan.setDefault(True)
        self.btn_scan.clicked.connect(self._on_scan)
        ab_lay.addWidget(self.btn_scan)

        self.btn_apply = QPushButton("Apply Changes")
        self.btn_apply.setProperty("class", "apply")
        self.btn_apply.setFixedHeight(38)
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._on_apply)
        ab_lay.addWidget(self.btn_apply)

        self.btn_preview = QPushButton("Preview Plan")
        self.btn_preview.setFixedHeight(38)
        self.btn_preview.clicked.connect(self._show_preview)
        self.btn_preview.setEnabled(False)
        ab_lay.addWidget(self.btn_preview)

        self.btn_undo = QPushButton("Undo History")
        self.btn_undo.setFixedHeight(38)
        self.btn_undo.clicked.connect(self._show_undo_timeline)
        self.btn_undo.setEnabled(bool(load_undo_log()))
        ab_lay.addWidget(self.btn_undo)

        sep_ab = QFrame(); sep_ab.setFrameShape(QFrame.Shape.VLine)
        sep_ab.setStyleSheet(f"QFrame{{background-color:{_t['btn_bg']};}}"); sep_ab.setFixedHeight(22)
        ab_lay.addWidget(sep_ab)

        self.btn_replay = QPushButton("Repeat Last Scan")
        self.btn_replay.setFixedHeight(32)
        self.btn_replay.setToolTip("Replay the last scan configuration")
        self.btn_replay.setStyleSheet(_SEC_BTN)
        self.btn_replay.setEnabled(os.path.isfile(_LAST_CONFIG_FILE))
        self.btn_replay.clicked.connect(self._replay_last_config)
        ab_lay.addWidget(self.btn_replay)

        self.btn_export = QPushButton("Export CSV")
        self.btn_export.setFixedHeight(32); self.btn_export.setEnabled(False)
        self.btn_export.setToolTip("Export the classification plan as CSV")
        self.btn_export.setStyleSheet(_SEC_BTN)
        self.btn_export.clicked.connect(self._export_plan)
        ab_lay.addWidget(self.btn_export)

        self.btn_export_html = QPushButton("Export HTML")
        self.btn_export_html.setFixedHeight(32); self.btn_export_html.setEnabled(False)
        self.btn_export_html.setToolTip("Export scan results as a styled HTML report")
        self.btn_export_html.setStyleSheet(_SEC_BTN)
        self.btn_export_html.clicked.connect(self._export_html)
        ab_lay.addWidget(self.btn_export_html)

        self.btn_open_dest = QPushButton("Open Folder")
        self.btn_open_dest.setFixedHeight(32)
        self.btn_open_dest.setToolTip("Open the current destination folder in Explorer")
        self.btn_open_dest.setStyleSheet(_SEC_BTN)
        self.btn_open_dest.clicked.connect(self._open_destination)
        ab_lay.addWidget(self.btn_open_dest)

        ab_lay.addStretch()

        # Watch Mode toggle (right side of action bar)
        self.btn_watch = QPushButton("Watch Mode")
        self.btn_watch.setFixedHeight(32)
        self.btn_watch.setCheckable(True)
        self.btn_watch.setToolTip("Auto-organize watched folders")
        self.btn_watch.setStyleSheet(_TOGGLE_BTN)
        self.btn_watch.clicked.connect(self._toggle_watch_mode)
        ab_lay.addWidget(self.btn_watch)
        action_wrap.addLayout(ab_lay)

        # ══════════════════════════════════════════════════════════════
        #  STACKED WIDGET — page 0 = Organizer, page 1 = Cleanup, page 2 = Duplicates
        # ══════════════════════════════════════════════════════════════
        self._content_stack = QStackedWidget()

        # ── Page 0: Organizer ────────────────────────────────────────
        organizer_page = QWidget()
        org_lay = QVBoxLayout(organizer_page)
        org_lay.setSpacing(0)
        org_lay.setContentsMargins(0, 0, 0, 0)
        org_lay.addWidget(action_bar)

        # ── Directory / Options Panel ────────────────────────────────────
        dir_panel = QWidget()
        self._themed_dir_panel = dir_panel
        dir_panel.setObjectName("dir_panel")
        dir_panel.setStyleSheet(
            f"QWidget#dir_panel {{ background: {_t['bg_alt']}; border-bottom: 1px solid {_t['btn_bg']}; }}")
        dp_lay = QVBoxLayout(dir_panel)
        dp_lay.setContentsMargins(16, 12, 16, 12)
        dp_lay.setSpacing(8)

        self.workspace_intro = QFrame()
        self.workspace_intro.setObjectName("workspace_intro")
        self.workspace_intro.setStyleSheet(
            f"QFrame#workspace_intro {{ background: {_t['header_bg']}; border: 1px solid {_t['border']}; border-radius: 18px; }}"
        )
        intro_lay = QVBoxLayout(self.workspace_intro)
        intro_lay.setContentsMargins(18, 16, 18, 16)
        intro_lay.setSpacing(6)

        intro_top = QHBoxLayout()
        self.lbl_workspace_section = QLabel("CURRENT WORKFLOW")
        self.lbl_workspace_section.setStyleSheet(
            f"color: {_t['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;"
        )
        intro_top.addWidget(self.lbl_workspace_section)
        intro_top.addStretch()
        self.lbl_workspace_ai = QLabel("AI CHECKING")
        self.lbl_workspace_ai.setStyleSheet(
            f"background: {_t['selection']}; color: #f59e0b; border: 1px solid {_t['border']}; "
            "border-radius: 999px; padding: 4px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
        )
        intro_top.addWidget(self.lbl_workspace_ai)
        intro_lay.addLayout(intro_top)

        self.lbl_workspace_title = QLabel("Rename After Effects Folders")
        self.lbl_workspace_title.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 20px; font-weight: 700; letter-spacing: -0.3px;"
        )
        intro_lay.addWidget(self.lbl_workspace_title)

        self.lbl_workspace_desc = QLabel(
            "Clean up source folders with clearer names, better structure, and a reviewable plan before anything changes."
        )
        self.lbl_workspace_desc.setWordWrap(True)
        self.lbl_workspace_desc.setStyleSheet(
            f"color: {_t['fg']}; font-size: 12px; line-height: 1.4em;"
        )
        intro_lay.addWidget(self.lbl_workspace_desc)

        self.lbl_workspace_meta = QLabel("")
        self.lbl_workspace_meta.setWordWrap(True)
        self.lbl_workspace_meta.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px;"
        )
        intro_lay.addWidget(self.lbl_workspace_meta)
        trust_row = QHBoxLayout()
        trust_row.setSpacing(8)
        self.lbl_workspace_trust = QLabel("Preview-first")
        self.lbl_workspace_guard = QLabel("Protected paths")
        for badge in (self.lbl_workspace_trust, self.lbl_workspace_guard):
            badge.setStyleSheet(
                f"background: {_t['bg_alt']}; color: {_t['fg']}; border: 1px solid {_t['border']}; "
                "border-radius: 999px; padding: 4px 10px; font-size: 10px; font-weight: 600;"
            )
            trust_row.addWidget(badge)
        trust_row.addStretch()
        intro_lay.addLayout(trust_row)
        dp_lay.addWidget(self.workspace_intro)

        # Hidden mode combo (kept for backward compat — controlled by sidebar)
        self.cmb_op = QComboBox()
        self.cmb_op.addItems([
            "Rename Folders by Best .aep File",
            "Categorize Folders into Groups",
            "Categorize + Smart Rename from Files",
            "PC File Organizer",
        ])
        self.cmb_op.hide()
        self.cmb_op.currentIndexChanged.connect(self._on_op_changed)

        # Source path
        row_src = QHBoxLayout(); row_src.setSpacing(10)
        lbl_src = QLabel("SOURCE")
        lbl_src.setStyleSheet(
            f"color: {_t['muted']}; font-weight: 700; font-size: 10px; letter-spacing: 1px;"
            "background: transparent;")
        lbl_src.setFixedWidth(64)
        row_src.addWidget(lbl_src)
        self.txt_src = QLineEdit()
        self.txt_src.setClearButtonEnabled(True)
        self.txt_src.setPlaceholderText("Drag a source folder here or browse…")
        row_src.addWidget(self.txt_src, 1)
        btn_src = QPushButton("Browse"); btn_src.setFixedWidth(84); btn_src.setFixedHeight(32)
        btn_src.clicked.connect(self._browse_src)
        row_src.addWidget(btn_src)
        self.row_src_w = QWidget()
        self.row_src_w.setStyleSheet("background: transparent;")
        self.row_src_w.setLayout(row_src)
        dp_lay.addWidget(self.row_src_w)

        # Destination path (categorize modes)
        self.row_dst_w = QWidget()
        self.row_dst_w.setStyleSheet("background: transparent;")
        row_dst = QHBoxLayout(self.row_dst_w)
        row_dst.setContentsMargins(0, 0, 0, 0); row_dst.setSpacing(10)
        lbl_dst = QLabel("OUTPUT")
        lbl_dst.setStyleSheet(
            f"color: {_t['muted']}; font-weight: 700; font-size: 10px; letter-spacing: 1px;"
            "background: transparent;")
        lbl_dst.setFixedWidth(64)
        row_dst.addWidget(lbl_dst)
        self.txt_dst = QLineEdit()
        self.txt_dst.setClearButtonEnabled(True)
        self.txt_dst.setPlaceholderText("Choose the output root for organized folders…")
        row_dst.addWidget(self.txt_dst, 1)
        btn_dst = QPushButton("Browse"); btn_dst.setFixedWidth(84); btn_dst.setFixedHeight(32)
        btn_dst.clicked.connect(self._browse_dst)
        row_dst.addWidget(btn_dst)
        self.row_dst_w.hide()
        dp_lay.addWidget(self.row_dst_w)

        # PC File Organizer I/O panel
        self.row_pc_io_w = QWidget()
        self.row_pc_io_w.setStyleSheet("background: transparent;")
        self.row_pc_io_w.hide()
        pc_io = QVBoxLayout(self.row_pc_io_w)
        pc_io.setContentsMargins(0, 0, 0, 4); pc_io.setSpacing(4)

        row_pc_src = QHBoxLayout(); row_pc_src.setSpacing(10)
        lbl_pc_src = QLabel("SOURCE")
        lbl_pc_src.setStyleSheet(
            f"color: {_t['muted']}; font-weight: 700; font-size: 10px; letter-spacing: 1px;"
            "background: transparent;")
        lbl_pc_src.setFixedWidth(64)
        row_pc_src.addWidget(lbl_pc_src)
        self.cmb_pc_src = QComboBox()
        self.cmb_pc_src.setFixedWidth(150)
        self._pc_src_presets = self._build_pc_src_presets()
        for label, _ in self._pc_src_presets:
            self.cmb_pc_src.addItem(label)
        self.cmb_pc_src.currentIndexChanged.connect(self._on_pc_src_changed)
        row_pc_src.addWidget(self.cmb_pc_src)
        self.txt_pc_src = QLineEdit()
        self.txt_pc_src.setClearButtonEnabled(True)
        self.txt_pc_src.setPlaceholderText("Use a custom source path…")
        row_pc_src.addWidget(self.txt_pc_src, 1)
        btn_pc_src = QPushButton("Browse"); btn_pc_src.setFixedWidth(84); btn_pc_src.setFixedHeight(32)
        btn_pc_src.clicked.connect(self._browse_pc_src)
        row_pc_src.addWidget(btn_pc_src)
        pc_io.addLayout(row_pc_src)

        lbl_map = QLabel("  OUTPUT MAPPING — set where each category's files will go:")
        lbl_map.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px; padding-left: 66px; background: transparent;")
        pc_io.addWidget(lbl_map)
        self.pc_dst_map_w = QWidget()
        self.pc_dst_map_w.setStyleSheet(
            f"background:{_t['sidebar_brand']}; border: 1px solid {_t['border']}; border-radius:12px; padding:6px;"
        )
        self._pc_dst_rows = {}
        self._pc_dst_grid = QGridLayout(self.pc_dst_map_w)
        self._pc_dst_grid.setContentsMargins(8, 6, 8, 6); self._pc_dst_grid.setSpacing(4)
        pc_dst_scroll = QScrollArea()
        pc_dst_scroll.setWidget(self.pc_dst_map_w)
        pc_dst_scroll.setWidgetResizable(True)
        pc_dst_scroll.setMaximumHeight(180)
        pc_dst_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        pc_io.addWidget(pc_dst_scroll)
        self._rebuild_pc_dst_map()

        dp_lay.addWidget(self.row_pc_io_w)

        # ── Options row (inline with directory panel) ────────────────────
        opts_row = QHBoxLayout(); opts_row.setSpacing(12)

        self.chk_llm = QCheckBox("Use AI guidance")
        self.chk_llm.setToolTip("Use Ollama LLM for AI-powered classification")
        self.chk_llm.setStyleSheet(
            f"QCheckBox {{ color: {_t['sidebar_profile_fg']}; font-weight: bold; font-size: 12px;"
            "background: transparent; }")
        opts_row.addWidget(self.chk_llm)

        self.chk_hash = QCheckBox("Check duplicates")
        self.chk_hash.setToolTip("Progressive duplicate detection:\nSize > Prefix hash > Suffix hash > Full SHA-256 + image perceptual hash")
        self.chk_hash.setStyleSheet("QCheckBox { background: transparent; }")
        opts_row.addWidget(self.chk_hash)

        self.chk_inc_files = QCheckBox("Include Files")
        self.chk_inc_files.setChecked(True)
        self.chk_inc_files.setToolTip("Include individual files")
        self.chk_inc_files.setStyleSheet("QCheckBox { background: transparent; }")
        self.chk_inc_files.setVisible(False)
        opts_row.addWidget(self.chk_inc_files)

        self.chk_inc_folders = QCheckBox("Include Folders")
        self.chk_inc_folders.setChecked(False)
        self.chk_inc_folders.setToolTip("Include subfolders as items to organize")
        self.chk_inc_folders.setStyleSheet("QCheckBox { background: transparent; }")
        self.chk_inc_folders.setVisible(False)
        opts_row.addWidget(self.chk_inc_folders)

        lbl_depth = QLabel("Depth")
        lbl_depth.setStyleSheet(
            f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 11px; background: transparent;")
        opts_row.addWidget(lbl_depth)
        self.spn_depth = QSpinBox()
        self.spn_depth.setRange(0, 99); self.spn_depth.setValue(0)
        self.spn_depth.setFixedWidth(48)
        self.spn_depth.setToolTip("Scan depth: 0=top-level only, 1+=subfolders, 99=full recursive")
        self.spn_depth.setSpecialValueText("0")
        opts_row.addWidget(self.spn_depth)

        self.lbl_type_filter = QLabel("File Type")
        self.lbl_type_filter.setStyleSheet(
            f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 11px; background: transparent;")
        self.lbl_type_filter.setVisible(False)
        opts_row.addWidget(self.lbl_type_filter)
        self.cmb_type_filter = QComboBox()
        self.cmb_type_filter.addItems(list(_SCAN_FILTERS.keys()))
        self.cmb_type_filter.setFixedWidth(130)
        self.cmb_type_filter.setToolTip("Filter scan to specific file types")
        self.cmb_type_filter.setStyleSheet(
            f"QComboBox {{ background: {_t['input_bg']}; color: {_t['accent_hover']}; border: 1px solid {_t['border']};"
            f"border-radius: 3px; padding: 2px 6px; font-size: 11px; font-weight: bold; }}"
            f"QComboBox:hover {{ border-color: {_t['accent_hover']}; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {_t['input_bg']}; color: {_t['fg']};"
            f"selection-background-color: {_t['selection']}; border: 1px solid {_t['border']}; }}")
        self.cmb_type_filter.setVisible(False)
        opts_row.addWidget(self.cmb_type_filter)

        opts_row.addStretch()

        # PC mode config buttons
        self.btn_pc_cats = QPushButton("Categories")
        self.btn_pc_cats.setFixedHeight(28)
        self.btn_pc_cats.setToolTip("Edit PC file categories and extension rules")
        self.btn_pc_cats.setStyleSheet(_SEC_BTN)
        self.btn_pc_cats.setVisible(False)
        self.btn_pc_cats.clicked.connect(self._open_pc_cat_editor)
        opts_row.addWidget(self.btn_pc_cats)

        self.btn_photo = QPushButton("Photo Settings")
        self.btn_photo.setFixedHeight(28)
        self.btn_photo.setToolTip("Configure photo library organization features")
        self.btn_photo.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {_t['selection']};"
            f"color: {_t['green']}; border: 1px solid {_t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
        self.btn_photo.setVisible(False)
        self.btn_photo.clicked.connect(self._open_photo_settings)
        opts_row.addWidget(self.btn_photo)

        dp_lay.addLayout(opts_row)
        org_lay.addWidget(dir_panel)

        # ══════════════════════════════════════════════════════════════════
        #  MAIN CONTENT BODY (results area)
        # ══════════════════════════════════════════════════════════════════
        body = QWidget()
        main = QVBoxLayout(body)
        main.setSpacing(6)
        main.setContentsMargins(12, 8, 12, 6)

        # ── Selection toolbar + filter ───────────────────────────────────
        toolbar = QHBoxLayout(); toolbar.setSpacing(4)

        for text, slot in [("Select all", self._sel_all), ("Clear", self._sel_none), ("Invert", self._sel_inv)]:
            b = QPushButton(text); b.setProperty("class", "toolbar")
            b.clicked.connect(slot); toolbar.addWidget(b)

        btn_chk = QPushButton("Check rows"); btn_chk.setProperty("class", "toolbar")
        btn_chk.setToolTip("Check highlighted rows"); btn_chk.clicked.connect(self._check_selected)
        toolbar.addWidget(btn_chk)
        btn_uchk = QPushButton("Uncheck rows"); btn_uchk.setProperty("class", "toolbar")
        btn_uchk.setToolTip("Uncheck highlighted rows"); btn_uchk.clicked.connect(self._uncheck_selected)
        toolbar.addWidget(btn_uchk)

        sep_t = QFrame(); sep_t.setFrameShape(QFrame.Shape.VLine)
        sep_t.setStyleSheet(f"QFrame{{background-color:{_t['btn_bg']};}}"); sep_t.setFixedHeight(20)
        toolbar.addWidget(sep_t)

        # View toggles
        self.btn_grid_toggle = QPushButton("Grid View")
        self.btn_grid_toggle.setFixedHeight(28)
        self.btn_grid_toggle.setCheckable(True)
        self.btn_grid_toggle.setToolTip("Toggle thumbnail grid view")
        self.btn_grid_toggle.setStyleSheet(_TOGGLE_BTN)
        self.btn_grid_toggle.setVisible(False)
        self.btn_grid_toggle.clicked.connect(self._toggle_grid_view)
        toolbar.addWidget(self.btn_grid_toggle)

        self.btn_map_toggle = QPushButton("Map")
        self.btn_map_toggle.setFixedHeight(28)
        self.btn_map_toggle.setCheckable(True)
        self.btn_map_toggle.setToolTip("Show geotagged photos on map")
        self.btn_map_toggle.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px; background: {_t['selection']};"
            f"color: {_t['green']}; border: 1px solid {_t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}"
            f"QPushButton:checked {{ background: {_t['green']}; color: {_t['sidebar_brand']}; }}")
        self.btn_map_toggle.setVisible(False)
        self.btn_map_toggle.clicked.connect(self._toggle_map_view)
        toolbar.addWidget(self.btn_map_toggle)

        self.btn_graph_toggle = QPushButton("Graph")
        self.btn_graph_toggle.setFixedHeight(28)
        self.btn_graph_toggle.setCheckable(True)
        self.btn_graph_toggle.setToolTip("Show file relationship graph")
        self.btn_graph_toggle.setStyleSheet(_TOGGLE_BTN)
        self.btn_graph_toggle.setVisible(False)
        self.btn_graph_toggle.clicked.connect(self._toggle_graph_view)
        toolbar.addWidget(self.btn_graph_toggle)

        self.btn_preview_toggle = QPushButton("File Info")
        self.btn_preview_toggle.setFixedHeight(28)
        self.btn_preview_toggle.setCheckable(True)
        self.btn_preview_toggle.setToolTip("Toggle file preview panel")
        self.btn_preview_toggle.setStyleSheet(_TOGGLE_BTN)
        self.btn_preview_toggle.setVisible(False)
        self.btn_preview_toggle.clicked.connect(self._toggle_preview_panel)
        toolbar.addWidget(self.btn_preview_toggle)

        self.btn_before_after = QPushButton("Before/After")
        self.btn_before_after.setFixedHeight(28)
        self.btn_before_after.setToolTip("Show before/after directory comparison")
        self.btn_before_after.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px; background: {_t['selection']};"
            f"color: {_t['accent_hover']}; border: 1px solid {_t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
        self.btn_before_after.setVisible(False)
        self.btn_before_after.clicked.connect(self._show_before_after)
        toolbar.addWidget(self.btn_before_after)

        self.btn_events = QPushButton("Events")
        self.btn_events.setFixedHeight(28)
        self.btn_events.setToolTip("AI Event Grouping - cluster photos by event")
        self.btn_events.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px; background: {_t['selection']};"
            f"color: {_t['accent_hover']}; border: 1px solid {_t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
        self.btn_events.setVisible(False)
        self.btn_events.clicked.connect(self._show_event_grouping)
        toolbar.addWidget(self.btn_events)

        toolbar.addStretch()

        # Filter / search
        self.txt_search = QLineEdit()
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setPlaceholderText("Filter names, folders, categories, or methods…")
        self.txt_search.setFixedWidth(280)
        self.txt_search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.txt_search)

        lbl_cf = QLabel("Confidence floor")
        self._themed_lbl_cf = lbl_cf
        lbl_cf.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        toolbar.addWidget(lbl_cf)
        self.sld_conf = QSlider(Qt.Orientation.Horizontal)
        self.sld_conf.setRange(0, 100); self.sld_conf.setValue(0)
        self.sld_conf.setFixedWidth(90)
        self.sld_conf.valueChanged.connect(self._on_conf_changed)
        toolbar.addWidget(self.sld_conf)
        self.lbl_conf = QLabel("0%"); self.lbl_conf.setFixedWidth(30)
        self.lbl_conf.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        toolbar.addWidget(self.lbl_conf)

        self.cmb_face_filter = QComboBox()
        self.cmb_face_filter.setFixedWidth(130)
        self.cmb_face_filter.setToolTip("Filter by detected face/person")
        self.cmb_face_filter.setStyleSheet(
            f"QComboBox {{ font-size: 11px; background: {_t['selection']}; color: {_t['green']};"
            f"border: 1px solid {_t['border']}; border-radius: 4px; padding: 2px 6px; }}")
        self.cmb_face_filter.addItem("All Persons")
        self.cmb_face_filter.currentTextChanged.connect(self._apply_filter)
        self.cmb_face_filter.hide()
        toolbar.addWidget(self.cmb_face_filter)

        main.addLayout(toolbar)

        # ── Scan Results Dashboard ───────────────────────────────────────
        self.dashboard_panel = QWidget()
        self.dashboard_panel.setStyleSheet(
            f"background: {_t['header_bg']}; border: 1px solid {_t['border']}; border-radius: 14px; padding: 6px;"
        )
        self.dashboard_panel.setFixedHeight(82)
        self.dashboard_panel.hide()
        dash_lay = QVBoxLayout(self.dashboard_panel)
        dash_lay.setContentsMargins(12, 8, 12, 8); dash_lay.setSpacing(4)
        dash_top = QHBoxLayout()
        dash_copy = QVBoxLayout()
        dash_copy.setSpacing(1)
        self.lbl_dash_kicker = QLabel("SCAN OVERVIEW")
        self.lbl_dash_kicker.setStyleSheet(
            f"color: {_t['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1.3px;"
        )
        dash_copy.addWidget(self.lbl_dash_kicker)
        self.lbl_dash_summary = QLabel("")
        self.lbl_dash_summary.setStyleSheet(f"color: {_t['fg_bright']}; font-size: 13px; font-weight: 700;")
        dash_copy.addWidget(self.lbl_dash_summary)
        dash_top.addLayout(dash_copy)
        dash_top.addStretch()
        btn_hide_dash = QPushButton("Hide overview")
        self._themed_btn_hide_dash = btn_hide_dash
        btn_hide_dash.setFixedHeight(28)
        btn_hide_dash.setStyleSheet(f"QPushButton{{font-size:10px;color:{_t['muted']};background:{_t['sidebar_brand']};"
                                     f"border:1px solid {_t['border']};border-radius:3px}}"
                                     f"QPushButton:hover{{color:{_t['fg']}}}")
        btn_hide_dash.clicked.connect(lambda: self.dashboard_panel.hide())
        dash_top.addWidget(btn_hide_dash)
        dash_lay.addLayout(dash_top)
        self.bar_chart = CategoryBarChart()
        self.bar_chart.segment_clicked.connect(self._filter_by_category)
        self.bar_chart.category_drop.connect(self._on_category_drop)
        dash_lay.addWidget(self.bar_chart)
        main.addWidget(self.dashboard_panel)

        # ── Results Table ────────────────────────────────────────────────
        self.tbl = QTableWidget()
        self.tbl.setObjectName("main_table")
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSortingEnabled(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._context_menu)
        self.tbl.setShowGrid(False)
        self.tbl.setDragEnabled(True)
        self.tbl.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tbl.currentCellChanged.connect(self._on_row_selected)
        self._setup_aep_tbl()

        # Thumbnail Grid View (hidden by default)
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet(f"QScrollArea {{ background: {_t['header_bg']}; border: none; }}")
        self._grid_container = QWidget()
        self._grid_layout = FlowLayout(self._grid_container, margin=8, spacing=8)
        self.grid_scroll.setWidget(self._grid_container)
        self.grid_scroll.hide()

        # Map View (hidden by default)
        self.map_widget = PhotoMapWidget()
        self.map_widget.hide()

        # Relationship Graph (hidden by default)
        self.graph_widget = RelationshipGraphWidget()
        self.graph_widget.node_clicked.connect(self._on_graph_node_clicked)
        self.graph_widget.hide()

        # Content splitter: left = table/grid/map/graph, right = preview
        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_content = QWidget()
        left_lay = QVBoxLayout(left_content)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        left_lay.addWidget(self.tbl, 1)
        left_lay.addWidget(self.grid_scroll, 1)
        left_lay.addWidget(self.map_widget, 1)
        left_lay.addWidget(self.graph_widget, 1)
        self._content_splitter.addWidget(left_content)

        self.preview_panel = FilePreviewPanel()
        self.preview_panel.hide()
        self._content_splitter.addWidget(self.preview_panel)
        self._content_splitter.setSizes([800, 300])
        main.addWidget(self._content_splitter, 1)

        # ── System Tray (for Watch Mode) ─────────────────────────────────
        self._watch_manager = None
        self._tray = None
        self._setup_tray()

        # Empty state (overlay on top of table)
        self.empty_state = QFrame(self.tbl.viewport())
        self.empty_state.setObjectName("empty_state")
        self.empty_state.setStyleSheet(
            f"QFrame#empty_state {{ background: {_t['header_bg']}; border: 1px solid {_t['border']}; border-radius: 16px; }}"
        )
        empty_lay = QVBoxLayout(self.empty_state)
        empty_lay.setContentsMargins(24, 22, 24, 22)
        empty_lay.setSpacing(6)
        self.lbl_empty_kicker = QLabel("READY WHEN YOU ARE")
        self.lbl_empty_kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_kicker.setStyleSheet(
            f"color: {_t['sidebar_btn_active_fg']}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;"
        )
        empty_lay.addWidget(self.lbl_empty_kicker)
        self.lbl_empty = QLabel("Select a source folder and run a scan")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 18px; font-weight: 700;"
        )
        empty_lay.addWidget(self.lbl_empty)
        self.lbl_empty_detail = QLabel(
            "UniFile previews changes before it applies them, keeps undo history close by, and protects sensitive paths by default."
        )
        self.lbl_empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_detail.setWordWrap(True)
        self.lbl_empty_detail.setStyleSheet(
            f"color: {_t['muted']}; font-size: 12px; line-height: 1.4em;"
        )
        empty_lay.addWidget(self.lbl_empty_detail)
        self.lbl_empty_actions = QLabel(
            "Browse a source folder, run a scan, review the plan, then apply only what you want."
        )
        self.lbl_empty_actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_actions.setWordWrap(True)
        self.lbl_empty_actions.setStyleSheet(
            f"color: {_t['sidebar_btn_active_fg']}; font-size: 11px; font-weight: 600;"
        )
        empty_lay.addWidget(self.lbl_empty_actions)
        self.empty_state.show()

        # Scan Summary Toast (overlay banner on table)
        self.lbl_toast = QLabel("", self.tbl)
        self.lbl_toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_toast.setWordWrap(True)
        self.lbl_toast.setStyleSheet(
            f"QLabel {{ background: {_t['header_bg']};"
            f"color: {_t['fg_bright']}; font-size: 13px; font-weight: bold;"
            f"padding: 12px 20px; border-radius: 12px;"
            f"border: 1px solid {_t['border']}; }}")
        self.lbl_toast.setFixedHeight(50)
        self.lbl_toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.lbl_toast.hide)

        # Stats bar
        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("stats_label")
        self.lbl_stats.setStyleSheet(f"color: {_t['muted']}; font-size: 12px; padding: 6px 2px 2px 2px;")
        main.addWidget(self.lbl_stats)

        # ── Progress Panel ───────────────────────────────────────────────
        self.prog_panel = QWidget()
        self.prog_panel.setVisible(False)
        self.prog_panel.setStyleSheet(
            f"QWidget#prog_panel {{ background: {_t['bg_alt']}; border: 1px solid {_t['border']}; "
            f"border-radius: 14px; margin: 2px 0; }}")
        self.prog_panel.setObjectName("prog_panel")
        prog_layout = QVBoxLayout(self.prog_panel)
        prog_layout.setContentsMargins(14, 12, 14, 12)
        prog_layout.setSpacing(6)

        prog_top = QHBoxLayout()
        self.lbl_prog_phase = QLabel("Preparing scan")
        self.lbl_prog_phase.setStyleSheet(
            f"color: {_t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;")
        prog_top.addWidget(self.lbl_prog_phase)
        prog_top.addStretch()
        self.lbl_prog_counter = QLabel("0 / 0")
        self.lbl_prog_counter.setStyleSheet(f"color: {_t['fg']}; font-size: 11px; font-family: monospace;")
        prog_top.addWidget(self.lbl_prog_counter)
        self.lbl_prog_eta = QLabel("")
        self.lbl_prog_eta.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; padding-left: 10px;")
        prog_top.addWidget(self.lbl_prog_eta)
        prog_layout.addLayout(prog_top)

        self.pbar = QProgressBar()
        self.pbar.setObjectName("main_progress")
        self.pbar.setTextVisible(False)
        self.pbar.setFixedHeight(8)
        self.pbar.setStyleSheet(
            f"QProgressBar {{ background:{_t['header_bg']}; border:none; border-radius:3px; }}"
            f"QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {_t['accent']}, stop:0.5 {_t['sidebar_btn_active_fg']}, stop:1 {_t['accent']}); border-radius:3px; }}")
        prog_layout.addWidget(self.pbar)

        prog_bottom = QHBoxLayout()
        self.lbl_prog_method = QLabel("")
        self.lbl_prog_method.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; font-style: italic;")
        prog_bottom.addWidget(self.lbl_prog_method)
        prog_bottom.addStretch()
        self.lbl_prog_speed = QLabel("")
        self.lbl_prog_speed.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; font-family: monospace;")
        prog_bottom.addWidget(self.lbl_prog_speed)
        prog_layout.addLayout(prog_bottom)

        main.addWidget(self.prog_panel)

        # ── Console Log (collapsible) ────────────────────────────────────
        self.log_container = QWidget()
        log_outer = QVBoxLayout(self.log_container)
        log_outer.setContentsMargins(0, 0, 0, 0)
        log_outer.setSpacing(0)

        log_header = QHBoxLayout()
        log_header.setContentsMargins(0, 2, 0, 2)
        self.btn_toggle_log = QPushButton("Activity log")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(False)
        self.btn_toggle_log.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_t['muted']}; font-size: 11px; "
            f"border: none; padding: 2px 4px; text-align: left; font-family: monospace; }}"
            f"QPushButton:hover {{ color: {_t['fg']}; }}"
            f"QPushButton:checked {{ color: {_t['sidebar_btn_active_fg']}; }}")
        self.btn_toggle_log.clicked.connect(self._toggle_log)
        log_header.addWidget(self.btn_toggle_log)
        log_header.addStretch()
        btn_clear_log = QPushButton("Clear log")
        self._themed_btn_clear_log = btn_clear_log
        btn_clear_log.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_t['muted']}; font-size: 11px; "
            f"border: none; padding: 2px 6px; }}"
            f"QPushButton:hover {{ color: #ef4444; }}")
        btn_clear_log.clicked.connect(lambda: self.txt_log.clear())
        log_header.addWidget(btn_clear_log)
        log_outer.addLayout(log_header)

        self.txt_log = QTextEdit()
        self.txt_log.setObjectName("console_log")
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(140)
        self.txt_log.setStyleSheet(
            f"QTextEdit {{ background:{_t['header_bg']}; color:{_t['muted']}; font-family: 'Consolas','Courier New',monospace; "
            f"font-size: 11px; border: 1px solid {_t['border']}; border-radius: 4px; padding: 4px; }}")
        self.txt_log.setVisible(False)
        log_outer.addWidget(self.txt_log)
        main.addWidget(self.log_container)

        org_lay.addWidget(body, 1)

        self._content_stack.addWidget(organizer_page)   # index 0

        # ── Page 1: Cleanup Tools (inline) ───────────────────────────
        self._cleanup_panel = CleanupPanel()
        self._content_stack.addWidget(self._cleanup_panel)  # index 1

        # ── Page 2: Duplicate Finder (inline) ────────────────────────
        self._duplicate_panel = DuplicatePanel()
        self._content_stack.addWidget(self._duplicate_panel)  # index 2

        # ── Page 3: Tag Library (from TagStudio integration) ─────────
        self._tag_panel = TagLibraryPanel()
        self._content_stack.addWidget(self._tag_panel)  # index 3

        # ── Page 4: Media Lookup (from mnamer integration) ─────────────
        self._media_panel = MediaLookupPanel()
        self._media_panel.metadata_applied.connect(self._on_media_metadata_applied)
        self._content_stack.addWidget(self._media_panel)  # index 4

        # ── Page 5: Virtual Library (non-destructive overlay) ──────────
        from unifile.dialogs.virtual_library_panel import VirtualLibraryPanel
        self._vlib_panel = VirtualLibraryPanel()
        self._content_stack.addWidget(self._vlib_panel)  # index 5

        self._content_stack.setCurrentIndex(0)
        right_col.addWidget(self._content_stack, 1)

        # ── Bottom Status Bar ────────────────────────────────────────────
        status = QWidget()
        self._themed_status_bar = status
        status.setFixedHeight(30)
        status.setStyleSheet(f"background-color: {_t['sidebar_brand']}; border-top: 1px solid {_t['sidebar_border']};")
        s_lay = QHBoxLayout(status)
        s_lay.setContentsMargins(16, 0, 16, 0)
        self.lbl_statusbar = QLabel("Ready to build a plan")
        self.lbl_statusbar.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; font-family: monospace;")
        s_lay.addWidget(self.lbl_statusbar)
        s_lay.addStretch()
        self.lbl_ollama = QLabel("AI optional")
        self.lbl_ollama.setStyleSheet(f"color: {_t['muted']}; font-size: 11px; font-family: monospace;")
        self.lbl_ollama.setToolTip("Checking Ollama status...")
        s_lay.addWidget(self.lbl_ollama)
        self.lbl_prog = self.lbl_statusbar   # backward-compat alias
        right_col.addWidget(status)

        root.addWidget(right_panel, 1)

        self.setStyleSheet(get_active_stylesheet())
        self._apply_sidebar_theme(get_active_theme())

        # Tab order: source → scan → apply → table
        self.setTabOrder(self.txt_src, self.btn_scan)
        self.setTabOrder(self.btn_scan, self.btn_apply)
        self.setTabOrder(self.btn_apply, self.tbl)

        self._mode_labels = [self.cmb_op.itemText(i) for i in range(self.cmb_op.count())]
        self._refresh_workspace_copy()

    def _mode_presentation(self, idx: int) -> dict:
        return {
            self.OP_AEP: {
                "title": "Rename After Effects Folders",
                "desc": "Use the strongest project file name to clean up archive folders without losing context.",
                "meta": "Review-first workflow • Great for project dumps, archives, and client handoff folders",
                "scan": "Scan Folders",
                "apply": "Rename Folders",
                "preview": "Preview Changes",
                "open": "Open Source",
                "hint": "Scan archive folders, review the strongest project-file match, then rename only the folders you trust.",
                "search": "Filter source names, destinations, or statuses…",
                "empty_title": "Choose a source folder to scan",
                "empty_detail": "UniFile will inspect folders, propose clearer names, and keep everything reviewable before you rename anything.",
                "next": "Browse a source folder, scan for candidates, preview the rename plan, then apply the final set."
            },
            self.OP_CAT: {
                "title": "Categorize Folder Collections",
                "desc": "Sort folders into clear destinations with rules, metadata, and optional AI assistance.",
                "meta": "Preview-first workflow • Best for asset packs, vendor drops, and creative libraries",
                "scan": "Scan & Categorize",
                "apply": "Apply Folder Moves",
                "preview": "Preview Destinations",
                "open": "Open Output",
                "hint": "Build a category plan from folders, review uncertain matches, then move approved items into clean destinations.",
                "search": "Filter by folder, category, confidence, or method…",
                "empty_title": "Select a source and output folder",
                "empty_detail": "You’ll get a categorized move plan first, then decide what should actually be applied.",
                "next": "Choose a source and output root, scan to build the move plan, then apply only the rows you keep checked."
            },
            self.OP_SMART: {
                "title": "Categorize & Smart Rename",
                "desc": "Organize folders and generate cleaner names in the same reviewed pass.",
                "meta": "Preview-first workflow • Best when noisy source names need cleanup as well as categorization",
                "scan": "Scan, Categorize & Rename",
                "apply": "Apply Folder Changes",
                "preview": "Preview Destinations",
                "open": "Open Output",
                "hint": "Combine categorization and rename cleanup in one pass, then review both structure and naming before apply.",
                "search": "Filter renamed folders, categories, confidence, or methods…",
                "empty_title": "Select a source and output folder",
                "empty_detail": "UniFile can categorize folders, clean up awkward names, and show the full move plan before anything changes.",
                "next": "Set the source and output folders, scan to generate the combined plan, then preview the final structure."
            },
            self.OP_FILES: {
                "title": "Organize Mixed File Collections",
                "desc": "Triage loose files into category destinations with photo tools, duplicate awareness, and optional AI.",
                "meta": "Preview-first workflow • Best for desktops, downloads, and mixed working folders",
                "scan": "Scan Files",
                "apply": "Organize Files",
                "preview": "Preview Moves",
                "open": "Open Output",
                "hint": "Scan loose files, tune the confidence floor or filters, then apply a calmer destination plan with duplicates in view.",
                "search": "Filter names, folders, categories, tags, or methods…",
                "empty_title": "Choose a file source to scan",
                "empty_detail": "UniFile will map loose files into category destinations, flag uncertain matches, and keep the plan reviewable.",
                "next": "Pick a source folder, scan to classify files, review confidence and filters, then apply the checked rows."
            },
        }.get(idx, {
            "title": "UniFile",
            "desc": "Organize files with a calmer, reviewable workflow.",
            "meta": "Preview-first workflow",
            "scan": "Scan",
            "apply": "Apply Changes",
            "preview": "Preview Plan",
            "open": "Open Folder",
            "hint": "Build a plan first, review the result list, then apply only the changes you want.",
            "search": "Filter results…",
            "empty_title": "Select a source and run a scan",
            "empty_detail": "Review the proposed plan before you apply it.",
            "next": "Choose a source, run a scan, review the plan, and apply the checked results."
        })

    def _refresh_workspace_copy(self):
        if not hasattr(self, 'lbl_workspace_title'):
            return
        copy = self._mode_presentation(self.cmb_op.currentIndex())
        profile_name = self.cmb_profile.currentText() if hasattr(self, 'cmb_profile') else get_active_profile_name()
        ai_status = "AI ready" if getattr(self, '_ollama_ready', False) else "AI optional"
        self.lbl_workspace_title.setText(copy["title"])
        self.lbl_workspace_desc.setText(copy["desc"])
        self.lbl_workspace_meta.setText(
            f"Profile: {profile_name}  •  {copy['meta']}  •  {ai_status}"
        )
        if hasattr(self, 'lbl_action_hint'):
            self.lbl_action_hint.setText(copy["hint"])
        self.btn_scan.setText(copy["scan"])
        self.btn_apply.setText(copy["apply"])
        self.btn_preview.setText(copy["preview"])
        self.btn_open_dest.setText(copy["open"])
        self.txt_search.setPlaceholderText(copy["search"])
        if hasattr(self, 'lbl_empty_actions'):
            self.lbl_empty_actions.setText(copy["next"])

    def _show_empty_state(self, title: str, detail: str = "", kicker: str = "READY WHEN YOU ARE"):
        if hasattr(self, 'lbl_empty_kicker'):
            self.lbl_empty_kicker.setText(kicker)
        if hasattr(self, 'lbl_empty'):
            self.lbl_empty.setText(title)
        if hasattr(self, 'lbl_empty_detail'):
            self.lbl_empty_detail.setText(detail)
        if hasattr(self, 'empty_state'):
            self.empty_state.show()
            self._position_table_overlays()
        elif hasattr(self, 'lbl_empty'):
            self.lbl_empty.show()

    def _hide_empty_state(self):
        if hasattr(self, 'empty_state'):
            self.empty_state.hide()
        elif hasattr(self, 'lbl_empty'):
            self.lbl_empty.hide()

    def _position_table_overlays(self):
        if not hasattr(self, 'tbl'):
            return
        if hasattr(self, 'empty_state'):
            vp = self.tbl.viewport()
            max_w = max(320, min(620, vp.width() - 32))
            self.empty_state.setFixedWidth(max_w)
            self.empty_state.adjustSize()
            h = self.empty_state.sizeHint().height()
            y = max(18, (vp.height() - h) // 2 - 18)
            self.empty_state.setGeometry((vp.width() - max_w) // 2, y, max_w, h)
        if hasattr(self, 'lbl_toast') and self.lbl_toast.isVisible():
            tw = self.tbl.viewport().width()
            toast_w = self.lbl_toast.width()
            self.lbl_toast.move((tw - toast_w) // 2, 12)

        # Backward compat refs (moved to menu bar)
        self.btn_custom_cats = None
        self.btn_envato = None
        self.btn_ollama = None
        self.btn_export_rules = None
        self.btn_import_rules = None
        self.btn_clear_cache = None

    # ═══ CONTEXT MENU (RIGHT-CLICK) ══════════════════════════════════════════
    def _context_menu(self, pos):
        row = self.tbl.rowAt(pos.y())
        if row < 0: return
        menu = QMenu(self)
        op = self.cmb_op.currentIndex()
        is_cat   = op in (self.OP_CAT, self.OP_SMART)
        is_files = op == self.OP_FILES

        # Check/uncheck selected rows
        sel_rows = sorted(set(idx.row() for idx in self.tbl.selectionModel().selectedRows()))
        act_check = act_uncheck = None
        if len(sel_rows) > 1:
            act_check   = menu.addAction(f"\u2611 Check {len(sel_rows)} Rows")
            act_uncheck = menu.addAction(f"\u2610 Uncheck {len(sel_rows)} Rows")
            menu.addSeparator()

        # Open in explorer
        act_open = menu.addAction("Open in Explorer")

        # Rename from files inside (cat modes only)
        act_rename_from_file = None
        if is_cat and row < len(self.cat_items):
            menu.addSeparator()
            act_rename_from_file = menu.addAction("📂  Rename from Files Inside…")
            act_rename_from_file.setToolTip("Browse files inside this folder and use one as the new name")

        # Reassign category
        act_reassign = None; act_batch = None
        if is_cat and row < len(self.cat_items):
            act_reassign = menu.addAction("Change Category...")
            if len(sel_rows) > 1:
                act_batch = menu.addAction(f"Batch Reassign ({len(sel_rows)} rows)...")

        act_reassign_file = None
        if is_files:
            menu.addSeparator()
            act_reassign_file = menu.addAction("Change Category…")

        # Re-classify with LLM
        act_reclassify = None
        if self._ollama_ready and (is_cat or is_files):
            menu.addSeparator()
            n = max(1, len(sel_rows))
            act_reclassify = menu.addAction(f"🔄 Re-classify {n} row(s) with LLM")

        # Compare Duplicates (for duplicate rows)
        act_compare_dups = None
        _ctx_idx = self._item_idx_from_row(row)
        if is_files and _ctx_idx < len(self.file_items) and self.file_items[_ctx_idx].dup_group > 0:
            menu.addSeparator()
            act_compare_dups = menu.addAction("🔍 Compare Duplicates…")

        # Create Rule from File
        act_create_rule = None
        if is_files and _ctx_idx < len(self.file_items):
            act_create_rule = menu.addAction("📏 Create Rule from This File…")

        # Conflict resolution strategies
        conflict_actions = {}
        if is_files:
            conflict_sub = menu.addMenu("Resolve Conflicts")
            for strat in ConflictResolver.STRATEGIES:
                label = strat.replace('_', ' ').title()
                a = conflict_sub.addAction(label)
                conflict_actions[a] = strat

        action = menu.exec(self.tbl.viewport().mapToGlobal(pos))
        if action == act_check:
            self._check_selected()
        elif action == act_uncheck:
            self._uncheck_selected()
        elif action == act_open:
            _oi = self._item_idx_from_row(row)
            if is_files and _oi < len(self.file_items):
                path = self.file_items[_oi].full_src
            elif is_cat and _oi < len(self.cat_items):
                path = self.cat_items[_oi].full_source_path
            elif not is_cat and not is_files and _oi < len(self.aep_items):
                path = self.aep_items[_oi].full_current_path
            else:
                path = None
            if path:
                target = path if os.path.isdir(path) else os.path.dirname(path)
                if sys.platform == 'win32': os.startfile(target)
                elif sys.platform == 'darwin': subprocess.Popen(['open', target])
                else: subprocess.Popen(['xdg-open', target])
        elif action == act_rename_from_file and is_cat:
            self._rename_from_file_picker(row)
        elif action == act_reassign and is_cat:
            self._reassign_category(row)
        elif action == act_batch and is_cat:
            self._batch_reassign(sel_rows)
        elif action == act_reassign_file and is_files:
            self._reassign_file_category(row)
        elif action == act_reclassify and self._ollama_ready:
            self._reclassify_rows(sel_rows if len(sel_rows) > 1 else [row])
        elif action == act_compare_dups and is_files and _ctx_idx < len(self.file_items):
            self._show_dup_compare(self.file_items[_ctx_idx].dup_group)
        elif action == act_create_rule and is_files:
            self._create_rule_from_file(row)
        elif action in conflict_actions:
            strat = conflict_actions[action]
            self.settings.setValue("conflict_strategy", strat)
            conflicts = ConflictResolver.detect(self.file_items)
            n = ConflictResolver.resolve(conflicts, strat, self.file_items)
            self._log(f"Resolved {n} conflict(s) via '{strat}'")
            self._stats_files()

    def _reassign_file_category(self, row: int):
        """Let the user manually reassign a file to a different category.
        `row` is the visual table row from the context menu."""
        idx = self._item_idx_from_row(row)
        if idx < 0 or idx >= len(self.file_items):
            return
        it = self.file_items[idx]
        cat_names = [c['name'] for c in self._pc_categories]
        cur_idx   = cat_names.index(it.category) if it.category in cat_names else 0
        new_cat, ok = QInputDialog.getItem(
            self, "Change Category", f"Category for: {it.name}", cat_names, cur_idx, False)
        if ok and new_cat:
            it.category = new_cat; it.method = 'Manual'
            # Re-resolve rename template for the new category
            template = self._pc_template_for(new_cat)
            if template and not it.is_folder:
                self._rename_counters[new_cat] = self._rename_counters.get(new_cat, 0) + 1
                counter = self._rename_counters[new_cat]
                new_stem = RenameTemplateEngine.resolve(
                    template, it.full_src, it.metadata, new_cat, counter)
                ext = os.path.splitext(it.name)[1]
                it.display_name = new_stem + ext
            else:
                it.display_name = it.name
            raw_dst  = os.path.join(self._pc_dst_for(new_cat), it.display_name)
            it.full_dst = self._dedup_file_dst(raw_dst)
            # Update visual cells using the visual row (not stale tbl_row)
            cat_color = next((c.get('color', '#4ade80') for c in self._pc_categories
                              if c['name'] == new_cat), '#4ade80')
            ci = self.tbl.item(row, 5)
            if ci:
                ci.setText(f"\u2B24 {new_cat}"); ci.setForeground(QColor(cat_color))
            ri = self.tbl.item(row, 6)
            if ri:
                renamed = it.display_name != it.name
                ri.setText(it.display_name if renamed else "—")
                _rt = get_active_theme()
                ri.setForeground(QColor(_rt['sidebar_btn_active_fg']) if renamed else QColor(_rt['muted']))
            mi = self.tbl.item(row, 9)
            if mi: mi.setText("manual"); mi.setForeground(QColor(get_active_theme()['accent_hover']))
            # Feed to adaptive learner
            get_learner().record_correction(it.name, it.full_src, new_cat)

    def _reclassify_rows(self, rows: list):
        """Re-classify selected visual rows using LLM in a background thread."""
        op = self.cmb_op.currentIndex()
        is_cat = op in (self.OP_CAT, self.OP_SMART)
        is_files = op == self.OP_FILES
        items_to_reclassify = []
        for visual_row in rows:
            idx = self._item_idx_from_row(visual_row)
            if is_cat and idx < len(self.cat_items):
                items_to_reclassify.append(('cat', visual_row, idx, self.cat_items[idx]))
            elif is_files and idx < len(self.file_items):
                items_to_reclassify.append(('files', visual_row, idx, self.file_items[idx]))
        if not items_to_reclassify:
            return

        self._log(f"Re-classifying {len(items_to_reclassify)} item(s) with LLM...")
        s = load_ollama_settings()

        class _ReclassifyWorker(QThread):
            result = pyqtSignal(int, int, str, dict)  # visual_row, list_idx, mode, result_dict
            done = pyqtSignal()

            def __init__(self, items, url, model):
                super().__init__()
                self._items = items
                self._url, self._model = url, model

            def run(self):
                for mode, visual_row, list_idx, it in self._items:
                    name = it.folder_name if mode == 'cat' else it.name
                    path = it.full_source_path if mode == 'cat' else it.full_src
                    r = tiered_classify(name, path)
                    self.result.emit(visual_row, list_idx, mode, r)
                self.done.emit()

        def _on_result(visual_row, list_idx, mode, r):
            if mode == 'cat' and list_idx < len(self.cat_items):
                it = self.cat_items[list_idx]
                if r.get('category'):
                    it.category = r['category']
                    it.confidence = r.get('confidence', 0)
                    it.method = r.get('method', 'llm')
                    it.detail = r.get('detail', '')
                    it.cleaned_name = r.get('cleaned_name', it.cleaned_name)
                    # Update table cells using visual row
                    di = self.tbl.item(visual_row, 3)
                    if di:
                        dst = self.txt_dst.text()
                        it.full_dest_path = os.path.join(dst, it.category, it.cleaned_name)
                        di.setText(it.full_dest_path)
                        di.setForeground(QColor(get_active_theme()['green']))
                    ci = self.tbl.item(visual_row, 4)
                    if ci:
                        ci.setText(f"{it.confidence:.0f}%")
                        ci.setForeground(QColor(self._confidence_text_color(it.confidence)))
                    mi = self.tbl.item(visual_row, 5)
                    if mi:
                        mi.setText(it.method.replace('_', ' '))
                        mi.setForeground(QColor(self._METHOD_COLORS_CAT.get(it.method, '#888')))
            elif mode == 'files' and list_idx < len(self.file_items):
                it = self.file_items[list_idx]
                if r.get('category'):
                    it.category = r['category']
                    it.confidence = r.get('confidence', 0)
                    it.method = r.get('method', 'llm')
                    it.detail = r.get('detail', '')
                    ci = self.tbl.item(visual_row, 5)
                    cat_color = next((c.get('color', '#4ade80') for c in self._pc_categories
                                      if c['name'] == it.category), '#4ade80')
                    if ci:
                        ci.setText(it.category); ci.setForeground(QColor(cat_color))
                    cfi = self.tbl.item(visual_row, 8)
                    if cfi:
                        cfi.setText(f"{it.confidence}%")
                        cfi.setForeground(QColor(self._confidence_text_color(it.confidence)))
                    mi = self.tbl.item(visual_row, 9)
                    if mi:
                        mi.setText(it.method.replace('_', ' '))
                        mi.setForeground(QColor(self._METHOD_COLORS_FILES.get(it.method, '#888')))

        def _on_done():
            self._log("Re-classification complete")
            if is_cat: self._stats_cat()
            elif is_files: self._stats_files()

        self._reclassify_worker = _ReclassifyWorker(items_to_reclassify, s['url'], s['model'])
        self._reclassify_worker.result.connect(_on_result)
        self._reclassify_worker.done.connect(_on_done)
        self._reclassify_worker.start()

    def _rename_from_file_picker(self, row):
        """Open a file browser showing all files inside the source folder.
        The user picks a file; its stem becomes the new destination folder name.
        `row` is the visual table row."""
        idx = self._item_idx_from_row(row)
        if idx < 0 or idx >= len(self.cat_items):
            return
        it = self.cat_items[idx]
        src_path = it.full_source_path
        if not os.path.isdir(src_path):
            QMessageBox.warning(self, "Not Found", f"Source folder not found:\n{src_path}")
            return

        dlg = _FileBrowserDialog(src_path, it.folder_name, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen_name:
            new_name = dlg.chosen_name
            dst_dir = self.txt_dst.text()
            it.cleaned_name = new_name
            raw_dest = os.path.join(dst_dir, it.category, new_name)
            it.full_dest_path = self._deduplicate_dest_path(raw_dest)
            di = self.tbl.item(row, 3)
            if di:
                di.setText(it.full_dest_path)
                di.setForeground(QColor(get_active_theme()['accent_hover']))
                di.setToolTip(f"Manually renamed → \"{new_name}\"")
            it.method = 'Manual'; it.detail = f'Renamed from file: {dlg.chosen_file}'

    def _reassign_category(self, row):
        """Reassign a single cat_item. `row` is visual table row."""
        idx = self._item_idx_from_row(row)
        if idx < 0 or idx >= len(self.cat_items):
            return
        it = self.cat_items[idx]
        all_cats = get_all_category_names()
        current_idx = all_cats.index(it.category) if it.category in all_cats else 0
        new_cat, ok = QInputDialog.getItem(self, "Change Category",
            f"Select category for: {it.folder_name}", all_cats, current_idx, False)
        if ok and new_cat:
            it.category = new_cat; it.method = 'Manual'; it.detail = 'User override'; it.topic = ''
            dst_dir = self.txt_dst.text()
            it.full_dest_path = os.path.join(dst_dir, new_cat, it.folder_name)
            # Update dest path column (use visual row)
            di = self.tbl.item(row, 3)
            _rt = get_active_theme()
            if di: di.setText(it.full_dest_path); di.setForeground(QColor(_rt['accent_hover'])); di.setToolTip(it.full_dest_path)
            cfi = self.tbl.item(row, 4)
            if cfi: cfi.setText("--"); cfi.setForeground(QColor(_rt['accent_hover']))
            mi = self.tbl.item(row, 5)
            if mi: mi.setText("Manual"); mi.setForeground(QColor(_rt['accent_hover']))
            self._log(f"  Reassigned: {it.folder_name}  ->  {new_cat}")
            save_correction(it.folder_name, new_cat)
            # Feed correction to adaptive learner
            get_learner().record_correction(
                it.folder_name, it.full_source_path, new_cat, old_category=it.category)
            self._stats_cat()

    def _batch_reassign(self, rows):
        """Reassign multiple selected visual rows to a single category."""
        all_cats = get_all_category_names()
        new_cat, ok = QInputDialog.getItem(self, "Batch Reassign",
            f"Select category for {len(rows)} folders:", all_cats, 0, False)
        if not ok or not new_cat: return
        dst_dir = self.txt_dst.text()
        corrections = []
        for visual_row in rows:
            idx = self._item_idx_from_row(visual_row)
            if idx >= len(self.cat_items): continue
            it = self.cat_items[idx]
            old_cat = it.category
            it.category = new_cat; it.method = 'Manual'; it.detail = 'Batch user override'; it.topic = ''
            it.full_dest_path = os.path.join(dst_dir, new_cat, it.folder_name)
            # Update table cells (use visual row)
            _rt = get_active_theme()
            di = self.tbl.item(visual_row, 3)
            if di: di.setText(it.full_dest_path); di.setForeground(QColor(_rt['accent_hover'])); di.setToolTip(it.full_dest_path)
            cfi = self.tbl.item(visual_row, 4)
            if cfi: cfi.setText("--"); cfi.setForeground(QColor(_rt['accent_hover']))
            mi = self.tbl.item(visual_row, 5)
            if mi: mi.setText("Manual"); mi.setForeground(QColor(_rt['accent_hover']))
            save_correction(it.folder_name, new_cat)
            corrections.append({'filename': it.folder_name,
                                'filepath': it.full_source_path,
                                'category': new_cat, 'old_category': old_cat})
        # Feed batch corrections to adaptive learner
        if corrections:
            get_learner().record_batch_corrections(corrections)
        self._log(f"  Batch reassigned {len(rows)} folders  ->  {new_cat}")
        self._stats_cat()

    # ═══ CUSTOM CATEGORIES DIALOG ════════════════════════════════════════════
    def _open_custom_cats(self):
        dlg = CustomCategoriesDialog(self)
        if dlg.exec():
            save_custom_categories(dlg.get_categories())
            self._log(f"Custom categories saved ({len(dlg.get_categories())} categories)")

    # ═══ ENVATO API KEY ══════════════════════════════════════════════════════
    def _set_envato_key(self):
        current = _load_envato_api_key()
        key, ok = QInputDialog.getText(self, "Envato API Key",
            "Enter your Envato personal token (from build.envato.com):\n"
            "Leave blank to disable API enrichment.",
            text=current)
        if ok:
            key = key.strip()
            _save_envato_api_key(key)
            if key:
                self._log(f"Envato API key saved ({len(key)} chars)")
            else:
                self._log("Envato API key cleared")

    # ═══ OLLAMA LLM SETTINGS ═════════════════════════════════════════════════
    def _open_ollama_settings(self):
        dlg = OllamaSettingsDialog(self)
        if dlg.exec():
            self._log(f"Ollama settings saved: {dlg.settings['url']} / {dlg.settings['model']}")

    def _open_ai_providers(self):
        from unifile.dialogs.advanced_settings import AIProviderSettingsDialog
        dlg = AIProviderSettingsDialog(self)
        if dlg.exec():
            self._log("AI provider settings saved")

    def _open_whisper_settings(self):
        from unifile.dialogs.advanced_settings import WhisperSettingsDialog
        dlg = WhisperSettingsDialog(self)
        if dlg.exec():
            from unifile.whisper_backend import get_transcriber
            model = dlg.get_model_size()
            get_transcriber(model)
            self._log(f"Whisper model set to: {model}")

    def _open_semantic_settings(self):
        from unifile.dialogs.advanced_settings import SemanticSearchSettingsDialog
        dlg = SemanticSearchSettingsDialog(self)
        dlg.exec()

    def _open_embedding_settings(self):
        from unifile.dialogs.advanced_settings import EmbeddingSettingsDialog
        dlg = EmbeddingSettingsDialog(self)
        if dlg.exec():
            self.settings.setValue("auto_embed", dlg.chk_auto.isChecked())
            self.settings.setValue("embed_tags", dlg.chk_tags.isChecked())
            self._log(f"Metadata embedding: auto={dlg.chk_auto.isChecked()}")

    def _open_learning_stats(self):
        from unifile.dialogs.advanced_settings import LearningStatsDialog
        dlg = LearningStatsDialog(self)
        dlg.exec()

    # ═══ DESTINATION TREE PREVIEW ════════════════════════════════════════════
    def _show_preview(self):
        op = self.cmb_op.currentIndex()
        if op == self.OP_FILES:
            self._apply_files(dry_run=True)
            return
        if op == self.OP_AEP:
            self._apply_aep(dry_run=True)
            return
        if op not in (self.OP_CAT, self.OP_SMART): return
        dst = self.txt_dst.text()
        if not dst: return
        dlg = DestTreeDialog(self.cat_items, dst, self)
        dlg.exec()

    # ═══ UNDO ════════════════════════════════════════════════════════════════
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

    # ═══ FILTER / SEARCH ════════════════════════════════════════════════════
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
        text = self.txt_search.text().lower()
        face = self.cmb_face_filter.currentText() if self.cmb_face_filter.isVisible() else "All Persons"
        for row in range(self.tbl.rowCount()):
            # Check if any cell in the row contains the search text
            show = True
            if text:
                show = False
                for col in range(self.tbl.columnCount()):
                    item = self.tbl.item(row, col)
                    if item and text in item.text().lower():
                        show = True; break
            # Face filter (PC Files mode only)
            if show and face != "All Persons" and self.cmb_op.currentIndex() == self.OP_FILES:
                if row < len(self.file_items):
                    it = self.file_items[row]
                    persons = it.metadata.get('_photo_face_persons', [])
                    if face not in persons:
                        show = False
            self.tbl.setRowHidden(row, not show)

    # ═══ CONFIDENCE THRESHOLD ════════════════════════════════════════════════
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

    # ═══ OPERATION SWITCH ════════════════════════════════════════════════════
    def _on_sidebar_nav(self, op_idx: int):
        """Handle sidebar ORGANIZE button click — switch to organizer mode."""
        # Update checked state: check this op button, uncheck all tool buttons
        for kind, idx, btn in self._nav_buttons:
            if kind == 'op':
                btn.setChecked(idx == op_idx)
            elif kind == 'tool':
                btn.setChecked(False)

        # Tag Library, Media Lookup, and Virtual Library get their own content stack pages
        if op_idx == self.OP_TAGS:
            self._content_stack.setCurrentIndex(3)
            return
        if op_idx == self.OP_MEDIA:
            self._content_stack.setCurrentIndex(4)
            return
        if op_idx == self.OP_VLIB:
            self._content_stack.setCurrentIndex(5)
            return

        # Show organizer page
        self._content_stack.setCurrentIndex(0)
        # Switch mode via the hidden combo (triggers _on_op_changed)
        if self.cmb_op.currentIndex() != op_idx:
            self.cmb_op.setCurrentIndex(op_idx)
        else:
            self._on_op_changed(op_idx)

    def _on_sidebar_tool(self, tool_type: str, tab_idx: int = None):
        """Handle sidebar TOOLS button click — switch to inline tool panel."""
        # Update checked state: uncheck all op buttons, check this tool button
        for kind, idx, btn in self._nav_buttons:
            if kind == 'op':
                btn.setChecked(False)
            elif kind == 'tool':
                btn.setChecked(idx == (tool_type, tab_idx))
        # Switch stack to the right panel
        if tool_type == 'duplicates':
            self._content_stack.setCurrentIndex(2)
        else:
            # Cleanup panel — switch to the right tab
            self._cleanup_panel.tabs.setCurrentIndex(tab_idx or 0)
            self._content_stack.setCurrentIndex(1)

    def _on_op_changed(self, idx):
        is_cat_like = idx in (self.OP_CAT, self.OP_SMART)
        is_files    = idx == self.OP_FILES
        copy = self._mode_presentation(idx)
        # Keep sidebar buttons in sync
        if hasattr(self, '_nav_buttons'):
            for kind, nav_idx, btn in self._nav_buttons:
                if kind == 'op':
                    btn.setChecked(nav_idx == idx)
        # Source row: hidden in PC mode (PC panel has its own)
        self.row_src_w.setVisible(not is_files)
        self.row_dst_w.setVisible(is_cat_like)
        self.row_pc_io_w.setVisible(is_files)
        self.btn_preview.setVisible(is_cat_like or is_files)
        self.btn_pc_cats.setVisible(is_files)
        self.btn_photo.setVisible(is_files)
        self.chk_inc_files.setVisible(is_files)
        self.chk_inc_folders.setVisible(is_files)
        self.lbl_type_filter.setVisible(is_files)
        self.cmb_type_filter.setVisible(is_files)
        self.cmb_face_filter.hide()
        # Reset grid/map/graph views when switching modes
        self.btn_grid_toggle.setVisible(is_files)
        self.btn_grid_toggle.setChecked(False); self.btn_grid_toggle.setText("Grid View")
        self.grid_scroll.hide()
        self.btn_map_toggle.setVisible(False)
        self.btn_map_toggle.setChecked(False)
        self.map_widget.hide()
        # Reset v7 widgets
        self.graph_widget.hide()
        self.btn_graph_toggle.setVisible(False)
        self.btn_graph_toggle.setChecked(False)
        self.preview_panel.hide()
        self.btn_preview_toggle.setVisible(False)
        self.btn_preview_toggle.setChecked(False)
        self.btn_before_after.setVisible(False)
        self.btn_events.setVisible(False)
        self.tbl.show()
        self.tbl.setRowCount(0)
        self.aep_items.clear(); self.cat_items.clear(); self.file_items.clear()
        self.lbl_stats.clear(); self.btn_apply.setEnabled(False); self.btn_preview.setEnabled(False)
        if is_files:
            self._setup_files_tbl()
        elif is_cat_like:
            self._setup_cat_tbl()
        else:
            self._setup_aep_tbl()
        self._refresh_workspace_copy()
        self._show_empty_state(copy["empty_title"], copy["empty_detail"])

    def _on_profile_changed(self, name):
        """Handle profile selector change."""
        set_active_profile(name)
        profile = get_active_profile()
        # Update mode selector to match profile's default mode
        default_mode = profile.get("default_mode")
        if default_mode is not None and default_mode != self.cmb_op.currentIndex():
            self.cmb_op.setCurrentIndex(default_mode)
        # Apply scan depth from profile
        depth = profile.get("scan_depth")
        if depth is not None:
            self.spn_depth.setValue(depth)
        # Apply smart source path preset if defined
        default_src = profile.get("default_source")
        if default_src:
            expanded = os.path.expanduser(default_src)
            if os.path.isdir(expanded):
                self.txt_src.setText(expanded)
                # Also set PC source if in files mode
                if hasattr(self, 'cmb_pc_source'):
                    idx = self.cmb_pc_source.findText("Custom Path")
                    if idx >= 0:
                        self.cmb_pc_source.setCurrentIndex(idx)
                    if hasattr(self, 'txt_pc_src'):
                        self.txt_pc_src.setText(expanded)
        # Clear results since categories changed
        self.tbl.setRowCount(0)
        self.aep_items.clear(); self.cat_items.clear(); self.file_items.clear()
        self.lbl_stats.clear()
        self.btn_apply.setEnabled(False)
        copy = self._mode_presentation(self.cmb_op.currentIndex())
        self._refresh_workspace_copy()
        self._show_empty_state(
            f"{copy['empty_title']}",
            f"{copy['empty_detail']} Current profile: {name}.",
            kicker="PROFILE UPDATED"
        )
        self._log(f"Switched to profile: {name}")

    def _setup_aep_tbl(self):
        self.tbl.setColumnCount(7)
        self.tbl.setHorizontalHeaderLabels(["","Source Path","\u2192","New Path","AEP File","Size","Status"])
        h = self.tbl.horizontalHeader(); h.setFixedHeight(36)
        for c,m in [(0,"Fixed"),(1,"Stretch"),(2,"Fixed"),(3,"Stretch"),(4,"Stretch"),(5,"Fixed"),(6,"Fixed")]:
            h.setSectionResizeMode(c, getattr(QHeaderView.ResizeMode, m))
        self.tbl.setColumnWidth(0,40); self.tbl.setColumnWidth(2,30); self.tbl.setColumnWidth(5,80); self.tbl.setColumnWidth(6,80)

    def _setup_cat_tbl(self):
        self.tbl.setColumnCount(7)
        self.tbl.setHorizontalHeaderLabels(["","Source Path","\u2192","Destination Path","Conf","Method","Status"])
        h = self.tbl.horizontalHeader(); h.setFixedHeight(36)
        for c,m in [(0,"Fixed"),(1,"Stretch"),(2,"Fixed"),(3,"Stretch"),(4,"Fixed"),(5,"Fixed"),(6,"Fixed")]:
            h.setSectionResizeMode(c, getattr(QHeaderView.ResizeMode, m))
        self.tbl.setColumnWidth(0,40); self.tbl.setColumnWidth(2,30); self.tbl.setColumnWidth(4,55); self.tbl.setColumnWidth(5,80); self.tbl.setColumnWidth(6,70)

    def _setup_files_tbl(self):
        self.tbl.setColumnCount(11)
        self.tbl.setHorizontalHeaderLabels(["","","Name","Directory","\u2192","Category","Rename To","Size","Conf","Method","Status"])
        h = self.tbl.horizontalHeader(); h.setFixedHeight(36)
        for c,m in [(0,"Fixed"),(1,"Fixed"),(2,"Fixed"),(3,"Stretch"),(4,"Fixed"),(5,"Fixed"),(6,"Stretch"),(7,"Fixed"),(8,"Fixed"),(9,"Fixed"),(10,"Fixed")]:
            h.setSectionResizeMode(c, getattr(QHeaderView.ResizeMode, m))
        self.tbl.setColumnWidth(0,40); self.tbl.setColumnWidth(1,48)
        self.tbl.setColumnWidth(2,180)
        self.tbl.setColumnWidth(4,30); self.tbl.setColumnWidth(5,100)
        self.tbl.setColumnWidth(7,70); self.tbl.setColumnWidth(8,45)
        self.tbl.setColumnWidth(9,80); self.tbl.setColumnWidth(10,60)
        self.tbl.verticalHeader().setDefaultSectionSize(40)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._position_table_overlays()

    def _update_phase(self, phase_label: str, method_label: str):
        """Called when a worker transitions to a new processing phase."""
        self.lbl_prog_phase.setText(phase_label)
        self.lbl_prog_method.setText(method_label)
        self.pbar.setValue(0)
        self.lbl_prog_counter.setText("0 / ?")
        self.lbl_prog_eta.setText("")
        self.lbl_prog_speed.setText("")
        self._scan_start_time = time.time()   # reset timer for this phase

    def _toggle_log(self, checked):
        self.txt_log.setVisible(checked)
        self.btn_toggle_log.setText("Activity log  [hide]" if checked else "Activity log  [show]")

    # ═══ MEDIA METADATA → TAG LIBRARY ═══════════════════════════════════════
    def _on_media_metadata_applied(self, meta: dict):
        """Apply media metadata from Media Lookup to the Tag Library."""
        if not hasattr(self, '_tag_panel') or not self._tag_panel.library.is_open:
            self._log("  Media Lookup: Tag Library not open — metadata not saved")
            return
        lib = self._tag_panel.library
        media_type = meta.get("media_type", "")
        title = meta.get("title", "") or meta.get("series", "")

        # Create a genre tag for each genre
        for genre in meta.get("genres", []):
            tag = lib.get_tag_by_name(genre)
            if not tag:
                lib.add_tag(genre, is_category=True, color_slug="purple")

        # Store metadata fields on any selected entries in the tag panel
        fields_map = {
            "title": "title",
            "synopsis": "ai_summary",
            "id_imdb": "imdb_id",
            "id_tmdb": "tmdb_id",
        }
        if media_type == "episode":
            fields_map["series"] = "series"

        saved = 0
        rows = set(idx.row() for idx in self._tag_panel.tbl_entries.selectedIndexes())
        for r in rows:
            item = self._tag_panel.tbl_entries.item(r, 0)
            if not item:
                continue
            entry_id = item.data(Qt.ItemDataRole.UserRole)
            for src_key, field_key in fields_map.items():
                val = meta.get(src_key, "")
                if val:
                    lib.set_entry_field(entry_id, field_key, str(val))
            # Apply genre tags
            for genre in meta.get("genres", []):
                tag = lib.get_tag_by_name(genre)
                if tag:
                    lib.add_tags_to_entry(entry_id, [tag.id])
            saved += 1

        if saved:
            self._log(f"  Media Lookup: applied metadata to {saved} entries")
            self._tag_panel._refresh_tags()
            self._tag_panel._refresh_entries()
            self._tag_panel._update_stats()
        else:
            self._log(f"  Media Lookup: {title} — metadata ready (select entries in Tag Library to apply)")

    _LOG_MAX_BLOCKS = 10000

    def _log(self, m):
        doc = self.txt_log.document()
        if doc.blockCount() > self._LOG_MAX_BLOCKS:
            # Trim oldest 20% to avoid trimming on every single append
            trim_count = self._LOG_MAX_BLOCKS // 5
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down,
                                QTextCursor.MoveMode.KeepAnchor, trim_count)
            cursor.removeSelectedText()
            cursor.deleteChar()  # remove leftover newline
        self.txt_log.append(m)
        self.txt_log.verticalScrollBar().setValue(self.txt_log.verticalScrollBar().maximum())
        # Mirror key messages to status bar (first non-indented line)
        if m and not m.startswith("  ") and not m.startswith("["):
            self.lbl_statusbar.setText(m[:80])

    def _update_dashboard(self):
        """Update the scan results dashboard with current items."""
        op = self.cmb_op.currentIndex()
        if op == self.OP_FILES:
            items = self.file_items
        elif op in (self.OP_CAT, self.OP_SMART):
            items = self.cat_items
        else:
            self.dashboard_panel.hide(); return
        if not items:
            self.dashboard_panel.hide(); return
        # Count per category
        cat_counts = Counter()
        total_size = 0
        for it in items:
            cat_counts[it.category] += 1
            total_size += getattr(it, 'size', 0)
        # Build segments with colors
        segments = []
        for cat, count in cat_counts.most_common():
            color = '#4ade80'
            if op == self.OP_FILES:
                color = next((c.get('color', '#4ade80') for c in self._pc_categories
                              if c['name'] == cat), '#4ade80')
            segments.append((cat, count, color))
        # Format size
        sz = total_size
        for u in ['B', 'KB', 'MB', 'GB', 'TB']:
            if sz < 1024: break
            sz /= 1024
        size_str = f"{sz:.1f} {u}"
        self.lbl_dash_summary.setText(
            f"{len(items):,} items ready  •  {len(cat_counts):,} categories  •  {size_str} in scope")
        self.bar_chart.set_data(segments)
        self.dashboard_panel.show()

    def _filter_by_category(self, name: str):
        """Set search filter to show only a specific category."""
        self.txt_search.setText(name)

    def _show_scan_toast(self, text, duration_ms=6000):
        """Show a toast banner overlaid on the table and flash the taskbar."""
        self.lbl_toast.setText(text)
        self.lbl_toast.adjustSize()
        tw = self.tbl.viewport().width()
        toast_w = min(tw - 40, self.lbl_toast.sizeHint().width() + 40)
        self.lbl_toast.setFixedWidth(toast_w)
        self.lbl_toast.move((tw - toast_w) // 2, 12)
        self.lbl_toast.raise_()
        self.lbl_toast.show()
        self._position_table_overlays()
        # Flash taskbar if the window isn't focused
        from PyQt6.QtWidgets import QApplication
        if not self.isActiveWindow():
            QApplication.alert(self, 0)
        self._toast_timer.start(duration_ms)

    def _browse_src(self):
        d = QFileDialog.getExistingDirectory(self, "Select Source Folder", self.txt_src.text())
        if d: self.txt_src.setText(d)

    def _browse_dst(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.txt_dst.text())
        if d: self.txt_dst.setText(d)

    def _get_current_profile_config(self) -> dict:
        """Capture current UI state as a profile config dict."""
        op = self.cmb_op.currentIndex()
        return {
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

    def _apply_profile_config(self, cfg: dict):
        """Apply a profile config dict to UI."""
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

    def _save_profile(self):
        """Save current config as a named profile."""
        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        cfg = self._get_current_profile_config()
        ProfileManager.save(name, cfg)
        self._log(f"Profile saved: {name}")
        self._refresh_profiles_menu()

    def _load_profile_by_name(self, name: str):
        """Load and apply a saved profile."""
        try:
            cfg = ProfileManager.load(name)
            self._apply_profile_config(cfg)
            self._log(f"Profile loaded: {name}")
        except Exception as e:
            self._log(f"Error loading profile '{name}': {e}")

    def _manage_profiles(self):
        """Simple dialog to delete profiles."""
        profiles = ProfileManager.list_profiles()
        if not profiles:
            self._log("No saved profiles"); return
        name, ok = QInputDialog.getItem(self, "Delete Profile", "Select profile to delete:",
                                         profiles, 0, False)
        if ok and name:
            ProfileManager.delete(name)
            self._log(f"Profile deleted: {name}")
            self._refresh_profiles_menu()

    def _refresh_profiles_menu(self):
        """Rebuild the dynamic profile entries in the Profiles menu."""
        # Remove old dynamic entries (after separator)
        actions = self.menu_profiles.actions()
        sep_found = False
        for a in actions:
            if a.isSeparator():
                sep_found = True; continue
            if sep_found:
                self.menu_profiles.removeAction(a)
        # Add current profiles
        for name in ProfileManager.list_profiles():
            self.menu_profiles.addAction(name, lambda n=name: self._load_profile_by_name(n))

    # ═══ TABLE HELPERS ═══════════════════════════════════════════════════════
    class _NumericItem(QTableWidgetItem):
        """QTableWidgetItem that sorts by a numeric value instead of text."""
        def __init__(self, text: str, sort_value: float = 0.0):
            super().__init__(str(text))
            self._sort_value = sort_value
            self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)
        def __lt__(self, other):
            if isinstance(other, UniFile._NumericItem):
                return self._sort_value < other._sort_value
            return super().__lt__(other)

    def _it(self, text):
        i = QTableWidgetItem(str(text)); i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable); return i

    def _nit(self, text, sort_value: float):
        """Numeric-sortable table item."""
        return self._NumericItem(str(text), sort_value)

    def _make_cb(self, checked, callback, idx):
        w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb = QCheckBox(); cb.setChecked(checked)
        cb.stateChanged.connect(lambda st, i=idx: callback(i, st))
        l.addWidget(cb); return w

    def _make_arrow(self):
        a = self._it("\u2192"); a.setTextAlignment(Qt.AlignmentFlag.AlignCenter); return a

    def _set_status(self, row, text, color, col):
        i = self.tbl.item(row, col)
        if i:
            i.setText(text); i.setForeground(QColor(color))

    def _add_aep_row(self, it, idx):
        r = self.tbl.rowCount(); self.tbl.insertRow(r)
        it.tbl_row = r   # remember the actual table row for later hiding
        self.tbl.setCellWidget(r, 0, self._make_cb(it.selected, self._aep_cb, idx))
        # Col 1: Full source path
        _rt = get_active_theme()
        src_item = self._it(it.full_current_path)
        src_item.setForeground(QColor(_rt['muted'])); src_item.setToolTip(it.full_current_path)
        src_item.setData(Qt.ItemDataRole.UserRole, idx)  # store item list index (sort-safe)
        self.tbl.setItem(r, 1, src_item)
        self.tbl.setItem(r, 2, self._make_arrow())
        # Col 3: Full new path
        ni = self._it(it.full_new_path); ni.setForeground(QColor("#4ade80")); ni.setToolTip(it.full_new_path)
        f=ni.font(); f.setBold(True); ni.setFont(f); self.tbl.setItem(r, 3, ni)
        self.tbl.setItem(r, 4, self._it(it.aep_file))
        si = self._nit(it.file_size, getattr(it, 'file_size_bytes', 0)); si.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); self.tbl.setItem(r, 5, si)
        sti = self._it("Pending"); sti.setTextAlignment(Qt.AlignmentFlag.AlignCenter); sti.setForeground(QColor("#f59e0b")); self.tbl.setItem(r, 6, sti)

    def _aep_cb(self, idx, st):
        if idx < len(self.aep_items):
            self.aep_items[idx].selected = bool(st); self._upd_stats()

    def _update_mode_badges(self):
        """Update mode dropdown with item count badges."""
        counts = {0: len(self.aep_items), 1: len(self.cat_items),
                  2: len(self.cat_items), 3: len(self.file_items)}
        for i, base in enumerate(self._mode_labels):
            n = counts.get(i, 0)
            self.cmb_op.setItemText(i, f"{base}  ({n})" if n else base)

    def _stats_aep(self):
        sel = sum(1 for it in self.aep_items if it.selected)
        done = sum(1 for it in self.aep_items if it.status == "Done")
        self.lbl_stats.setText(f"{len(self.aep_items)} eligible | {sel} selected | {done} renamed")
        self._update_mode_badges()

    def _add_cat_row(self, it, idx):
        r = self.tbl.rowCount(); self.tbl.insertRow(r)
        it.tbl_row = r   # remember the actual table row for later hiding
        self.tbl.setCellWidget(r, 0, self._make_cb(it.selected, self._cat_cb, idx))

        # Col 1: Source Path (full path, dimmed)
        src_item = self._it(it.full_source_path)
        src_item.setForeground(QColor(get_active_theme()['muted']))
        src_item.setToolTip(it.full_source_path)
        src_item.setData(Qt.ItemDataRole.UserRole, idx)  # store item list index (sort-safe)
        self.tbl.setItem(r, 1, src_item)

        # Col 2: Arrow
        self.tbl.setItem(r, 2, self._make_arrow())

        # Col 3: Destination Path (full path, colored by method)
        dest_item = self._it(it.full_dest_path if it.full_dest_path else '[No match]')
        dest_basename = os.path.basename(it.full_dest_path)
        is_llm_renamed = dest_basename != it.folder_name and it.method == 'llm'
        if is_llm_renamed:
            dest_item.setForeground(QColor("#f472b6"))  # pink = LLM renamed
            dest_item.setToolTip(f"LLM renamed \"{it.folder_name}\" \u2192 \"{dest_basename}\"")
        elif it.topic:
            dest_item.setForeground(QColor("#e879f9"))  # purple = context override
            dest_item.setToolTip(f"Topic \"{it.topic}\" overridden to \"{it.category}\"")
        else:
            dest_item.setForeground(QColor("#4ade80"))
            dest_item.setToolTip(it.full_dest_path)
        f = dest_item.font(); f.setBold(True); dest_item.setFont(f)
        self.tbl.setItem(r, 3, dest_item)

        # Col 4: Confidence (smooth heatmap, numeric sort)
        cfi = self._nit(f"{it.confidence:.0f}%", it.confidence)
        cfi.setForeground(QColor(self._confidence_text_color(it.confidence)))
        cfi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tbl.setItem(r, 4, cfi)

        # Col 5: Method with color coding
        method_label = it.method.replace('_', ' ').replace('+', '+') if it.method else ''
        mi = self._it(method_label); mi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        mi.setForeground(QColor(self._METHOD_COLORS_CAT.get(it.method, '#888')))
        if it.detail: mi.setToolTip(it.detail)
        self.tbl.setItem(r, 5, mi)

        # Col 6: Status
        sti = self._it("Pending"); sti.setTextAlignment(Qt.AlignmentFlag.AlignCenter); sti.setForeground(QColor("#f59e0b"))
        self.tbl.setItem(r, 6, sti)

        # Row background tinting — category color at 10% opacity
        if it.category == '[Uncategorized]':
            bg = QColor(239, 68, 68, 25)
        elif 'Possible duplicate' in (it.detail or ''):
            bg = QColor(251, 191, 36, 25)
        else:
            cat_color_hex = next((c.get('color', '#4ade80') for c in self._pc_categories
                                  if c['name'] == it.category), '#4ade80')
            cat_qcolor = QColor(cat_color_hex)
            bg = QColor(cat_qcolor.red(), cat_qcolor.green(), cat_qcolor.blue(), 18)
        for col in range(self.tbl.columnCount()):
            item = self.tbl.item(r, col)
            if item:
                item.setBackground(bg)

    def _cat_cb(self, idx, st):
        if idx < len(self.cat_items):
            self.cat_items[idx].selected = bool(st); self._upd_stats()

    def _stats_cat(self):
        items = self.cat_items
        dupes = sum(1 for it in items if 'Possible duplicate' in (it.detail or ''))
        uncat = sum(1 for it in items if it.category == '[Uncategorized]')
        sel = sum(1 for it in items if it.selected)
        done = sum(1 for it in items if it.status == "Done")
        cats = len(set(it.category for it in items))
        avg_conf = sum(it.confidence for it in items) / len(items) if items else 0
        parts = [f"{len(items)} matched", f"{sel} selected", f"{cats} categories",
                 f"{self._cat_unmatched} uncategorized", f"{done} moved"]
        if avg_conf > 0:
            parts.append(f"avg {avg_conf:.0f}%")
        if dupes:
            parts.append(f"{dupes} dupes")
        self.lbl_stats.setText(" | ".join(parts))
        self._update_mode_badges()

    # ═══ SELECTION HELPERS ═══════════════════════════════════════════════════
    def _items(self):
        op = self.cmb_op.currentIndex()
        if op in (self.OP_CAT, self.OP_SMART): return self.cat_items
        if op == self.OP_FILES: return self.file_items
        return self.aep_items

    def _upd_stats(self):
        op = self.cmb_op.currentIndex()
        if op in (self.OP_CAT, self.OP_SMART):
            self._stats_cat()
        elif op == self.OP_FILES:
            self._stats_files()
        else:
            self._stats_aep()

    def _sel_all(self):
        for it in self._items(): it.selected = True
        for r in range(self.tbl.rowCount()):
            cb = self.tbl.cellWidget(r, 0)
            if cb:
                inner = cb.findChild(QCheckBox)
                if inner: inner.blockSignals(True); inner.setChecked(True); inner.blockSignals(False)
        self._upd_stats()

    def _sel_none(self):
        for it in self._items(): it.selected = False
        for r in range(self.tbl.rowCount()):
            cb = self.tbl.cellWidget(r, 0)
            if cb:
                inner = cb.findChild(QCheckBox)
                if inner: inner.blockSignals(True); inner.setChecked(False); inner.blockSignals(False)
        self._upd_stats()

    def _sel_inv(self):
        for it in self._items():
            it.selected = not it.selected
        for r in range(self.tbl.rowCount()):
            cb = self.tbl.cellWidget(r, 0)
            if cb:
                inner = cb.findChild(QCheckBox)
                if inner: inner.blockSignals(True); inner.setChecked(not inner.isChecked()); inner.blockSignals(False)
        self._upd_stats()

    def _check_selected(self):
        """Check (tick) only the highlighted/selected rows in the table."""
        self._set_highlighted_check(True)

    def _uncheck_selected(self):
        """Uncheck (untick) only the highlighted/selected rows in the table."""
        self._set_highlighted_check(False)

    def _set_highlighted_check(self, checked: bool):
        """Toggle checkboxes for all currently highlighted rows."""
        rows = sorted(set(idx.row() for idx in self.tbl.selectionModel().selectedRows()))
        if not rows:
            return
        items = self._items()
        for r in rows:
            item_idx = self._item_idx_from_row(r)
            if 0 <= item_idx < len(items):
                items[item_idx].selected = checked
                cb = self.tbl.cellWidget(r, 0)
                if cb:
                    inner = cb.findChild(QCheckBox)
                    if inner:
                        inner.blockSignals(True)
                        inner.setChecked(checked)
                        inner.blockSignals(False)
        self._upd_stats()

    # ═══════════════════════════════════════════════════════════════════════════
    # PC FILE ORGANIZER — Scan, Display, Apply
    # ═══════════════════════════════════════════════════════════════════════════

    # ── PC panel helpers ──────────────────────────────────────────────────────

    def _build_pc_src_presets(self) -> list:
        """Return [(label, path)] for source preset dropdown."""
        h = os.path.expanduser('~')
        presets = [
            ("Desktop",   os.path.join(h, 'Desktop')),
            ("Documents", os.path.join(h, 'Documents')),
            ("Downloads", os.path.join(h, 'Downloads')),
            ("Pictures",  os.path.join(h, 'Pictures')),
            ("Videos",    os.path.join(h, 'Videos')),
            ("Music",     os.path.join(h, 'Music')),
            ("Home",      h),
        ]
        # Append detected cloud storage folders
        try:
            cloud_folders = CloudPathResolver.detect_cloud_folders()
            for cf in cloud_folders:
                label = f"☁ {cf['name']} — {os.path.basename(cf['path'])}"
                presets.append((label, cf['path']))
        except Exception:
            pass
        presets.append(("Custom…", ""))
        return presets

    @staticmethod
    def _default_pc_dst_static(cat_name: str) -> str:
        """Return the sensible default destination for a category."""
        h = os.path.expanduser('~')
        mapping = {
            "Documents":   os.path.join(h, 'Documents'),
            "Images":      os.path.join(h, 'Pictures'),
            "Videos":      os.path.join(h, 'Videos'),
            "Audio":       os.path.join(h, 'Music'),
            "Archives":    os.path.join(h, 'Downloads', 'Archives'),
            "Code":        os.path.join(h, 'Documents', 'Code'),
            "Executables": os.path.join(h, 'Downloads', 'Executables'),
            "Fonts":       os.path.join(h, 'Documents', 'Fonts'),
            "Data":        os.path.join(h, 'Documents', 'Data'),
            "Design":      os.path.join(h, 'Documents', 'Design'),
            "Shortcuts":   os.path.join(h, 'Desktop'),
            "Other":       os.path.join(h, 'Downloads', 'Other'),
        }
        return mapping.get(cat_name, os.path.join(h, 'Downloads', cat_name))

    def _default_pc_dst(self, cat_name: str) -> str:
        return self._default_pc_dst_static(cat_name)

    def _rebuild_pc_dst_map(self):
        """Rebuild the category→destination grid from current categories."""
        # Clear existing widgets
        while self._pc_dst_grid.count():
            item = self._pc_dst_grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._pc_dst_rows.clear()

        cats = self._pc_categories
        cols = 2   # two category columns side by side
        for i, cat in enumerate(cats):
            row_g = i // cols
            col_g = (i % cols) * 3   # each col = label + lineedit + browse

            # Coloured category label
            lbl = QLabel(cat['name'])
            color = cat.get('color', '#cdd6f4')
            lbl.setStyleSheet(f"color:{color}; font-weight:bold; font-size:11px; min-width:72px;")
            self._pc_dst_grid.addWidget(lbl, row_g, col_g)

            # Destination path field — use custom_dst if set, else default
            txt = QLineEdit()
            custom = cat.get('custom_dst', '').strip()
            txt.setText(custom if custom else self._default_pc_dst(cat['name']))
            txt.setPlaceholderText("Destination folder…")
            _t = get_active_theme()
            _clr = "#f59e0b" if custom else _t['fg']
            txt.setStyleSheet(f"background:{_t['header_bg']}; color:{_clr}; border:1px solid {_t['sidebar_profile_border']};"
                              "border-radius:3px; padding:3px 6px; font-size:11px;")
            txt.setFixedHeight(28)
            txt.editingFinished.connect(lambda n=cat['name'], t=txt: self._on_dst_edited(n, t))
            self._pc_dst_rows[cat['name']] = txt
            self._pc_dst_grid.addWidget(txt, row_g, col_g + 1)

            # Browse button
            btn = QPushButton("…")
            btn.setFixedSize(28, 28)
            btn.setToolTip(f"Browse destination for {cat['name']}")
            btn.setStyleSheet(f"QPushButton{{background:{_t['selection']};color:{_t['sidebar_btn_active_fg']};border:none;"
                              "border-radius:3px;font-size:12px;padding:0}"
                              f"QPushButton:hover{{background:{_t['sidebar_btn_hover_border']}}}")
            btn.clicked.connect(lambda _=False, t=txt, n=cat['name']: self._browse_pc_dst(t, n))
            self._pc_dst_grid.addWidget(btn, row_g, col_g + 2)

        # Column stretching: stretch the text fields
        for c in range(cols):
            self._pc_dst_grid.setColumnStretch(c * 3,     0)   # label
            self._pc_dst_grid.setColumnStretch(c * 3 + 1, 1)   # text
            self._pc_dst_grid.setColumnStretch(c * 3 + 2, 0)   # button

    def _on_pc_src_changed(self, idx):
        label, path = self._pc_src_presets[idx]
        if label == "Custom…":
            self.txt_pc_src.setReadOnly(False)
            self.txt_pc_src.setPlaceholderText("Enter or browse custom path…")
            self.txt_pc_src.clear()
        else:
            self.txt_pc_src.setReadOnly(True)
            self.txt_pc_src.setText(path)

    def _browse_pc_src(self):
        start = self.txt_pc_src.text() or os.path.expanduser('~')
        d = QFileDialog.getExistingDirectory(self, "Select Source Folder", start)
        if d:
            self.txt_pc_src.setText(d)
            self.txt_pc_src.setReadOnly(False)
            # Switch combo to Custom
            for i, (lbl, _) in enumerate(self._pc_src_presets):
                if lbl == "Custom…":
                    self.cmb_pc_src.blockSignals(True)
                    self.cmb_pc_src.setCurrentIndex(i)
                    self.cmb_pc_src.blockSignals(False)
                    break

    def _on_dst_edited(self, cat_name: str, txt: QLineEdit):
        """Persist custom destination path back to category JSON."""
        val = txt.text().strip()
        default = self._default_pc_dst(cat_name)
        custom = val if val and val != default else ''
        for c in self._pc_categories:
            if c['name'] == cat_name:
                if custom:
                    c['custom_dst'] = custom
                    _t = get_active_theme()
                    txt.setStyleSheet(f"background:{_t['header_bg']}; color:#f59e0b; border:1px solid {_t['sidebar_profile_border']};"
                                      "border-radius:3px; padding:3px 6px; font-size:10px;")
                else:
                    c.pop('custom_dst', None)
                    _t = get_active_theme()
                    txt.setStyleSheet(f"background:{_t['header_bg']}; color:{_t['fg']}; border:1px solid {_t['sidebar_profile_border']};"
                                      "border-radius:3px; padding:3px 6px; font-size:10px;")
                break
        _save_pc_categories(self._pc_categories)

    def _browse_pc_dst(self, txt_widget: QLineEdit, cat_name: str):
        start = txt_widget.text() or os.path.expanduser('~')
        d = QFileDialog.getExistingDirectory(self, f"Destination for {cat_name}", start)
        if d:
            txt_widget.setText(d)
            self._on_dst_edited(cat_name, txt_widget)

    def _pc_src_path(self) -> str:
        """Return the currently selected PC source path."""
        return self.txt_pc_src.text().strip()

    def _pc_dst_for(self, cat_name: str) -> str:
        """Return the destination path configured for a category.
        Priority: grid line-edit > category custom_dst > default mapping."""
        txt = self._pc_dst_rows.get(cat_name)
        if txt:
            p = txt.text().strip()
            if p: return p
        # Fallback: check persisted custom_dst in category data
        for c in self._pc_categories:
            if c['name'] == cat_name and c.get('custom_dst', '').strip():
                return c['custom_dst'].strip()
        return self._default_pc_dst(cat_name)

    def _pc_template_for(self, cat_name: str) -> str:
        """Return the rename template configured for a category, or ''."""
        for c in self._pc_categories:
            if c['name'] == cat_name:
                return c.get('rename_template', '')
        return ''

    def _open_pc_cat_editor(self):
        dlg = PCCategoryEditorDialog(self)
        dlg.exec()
        self._pc_categories = _load_pc_categories()   # reload after edits
        self._rebuild_pc_dst_map()                     # refresh destination rows
        self._log("PC categories reloaded.")

    def _open_photo_settings(self):
        dlg = PhotoSettingsDialog(self)
        dlg.exec()

    _THUMB_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tif', '.tiff'}

    def _make_thumbnail(self, path: str, size: int = 36) -> QLabel:
        """Create a QLabel with a scaled thumbnail for image files."""
        lbl = QLabel()
        lbl.setFixedSize(size, size)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("background:transparent;border:none;")
        try:
            pix = QPixmap(path)
            if not pix.isNull():
                pix = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                lbl.setPixmap(pix)
                lbl.setToolTip(path)
            else:
                lbl.setText("--")
                lbl.setStyleSheet(f"background:transparent;border:none;color:{get_active_theme()['muted']};font-size:11px;")
        except Exception:
            lbl.setText("--")
            lbl.setStyleSheet(f"background:transparent;border:none;color:{get_active_theme()['muted']};font-size:11px;")
        return lbl

    def _item_idx_from_row(self, row: int) -> int:
        """Get the item list index stored in a visual table row (sort-safe)."""
        item = self.tbl.item(row, 2)  # Name column always has a QTableWidgetItem
        if item is None:
            item = self.tbl.item(row, 1)
        if item is not None:
            val = item.data(Qt.ItemDataRole.UserRole)
            if val is not None:
                return val
        return row  # fallback to visual row if no data stored

    def _visual_row_for_idx(self, list_idx: int) -> int:
        """Find the visual table row that maps to a given item list index (sort-safe)."""
        for r in range(self.tbl.rowCount()):
            if self._item_idx_from_row(r) == list_idx:
                return r
        return -1

    def _add_files_row(self, it: 'FileItem', idx: int):
        r = self.tbl.rowCount(); self.tbl.insertRow(r)
        it.tbl_row = r
        self.tbl.setRowHeight(r, 40)

        self.tbl.setCellWidget(r, 0, self._make_cb(it.selected, self._files_cb, idx))

        # Col 1: thumbnail preview (images only)
        ext = os.path.splitext(it.name)[1].lower()
        if not it.is_folder and ext in self._THUMB_EXTS and os.path.isfile(it.full_src):
            self.tbl.setCellWidget(r, 1, self._make_thumbnail(it.full_src))
        else:
            ph = self._it("📁" if it.is_folder else "--")
            ph.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setForeground(QColor(get_active_theme()['border']))
            self.tbl.setItem(r, 1, ph)

        # Col 2: filename with folder/file icon
        icon = "📁 " if it.is_folder else ""
        dup_badge = ""
        if it.dup_group > 0:
            if it.dup_is_original:
                dup_badge = f" ⟨G{it.dup_group} ✓⟩"
            else:
                dup_badge = f" ⟨G{it.dup_group} ✗⟩"
        ni = self._it(icon + it.name + dup_badge)
        _rt = get_active_theme()
        ni.setForeground(QColor(_rt['fg']))
        f = ni.font(); f.setBold(True); ni.setFont(f)
        if it.is_duplicate:
            ni.setForeground(QColor("#f59e0b"))
            tip = it.dup_detail or "Possible duplicate — auto-deselected"
            ni.setToolTip(f"{it.full_src}\n{'─' * 30}\n{tip}")
        elif it.dup_group > 0 and it.dup_is_original:
            ni.setForeground(QColor("#4ade80"))
            ni.setToolTip(f"{it.full_src}\n{'─' * 30}\n{it.dup_detail}")
        else:
            # Build rich tooltip: path + vision + metadata
            tip_parts = [it.full_src]
            if it.vision_description:
                tip_parts.append("─" * 30)
                tip_parts.append(f"👁 {it.vision_description}")
            if it.vision_ocr:
                tip_parts.append(f"📝 OCR: {it.vision_ocr}")
            if it.metadata:
                meta_tip = MetadataExtractor.format_tooltip(it.metadata)
                if meta_tip:
                    tip_parts.append("─" * 30)
                    tip_parts.append(meta_tip)
            ni.setToolTip('\n'.join(tip_parts))
        ni.setData(Qt.ItemDataRole.UserRole, idx)  # store item list index (sort-safe)
        self.tbl.setItem(r, 2, ni)

        # Col 3: directory (relative to source, or folder name for root files)
        abs_dir = os.path.dirname(it.full_src)
        src_root = self._pc_src_path()
        try:
            rel_dir = os.path.relpath(abs_dir, src_root)
            if rel_dir == ".":
                dir_display = os.path.basename(abs_dir) or abs_dir
            else:
                dir_display = os.path.join(os.path.basename(src_root), rel_dir)
        except ValueError:
            dir_display = abs_dir
        di = self._it(dir_display)
        di.setForeground(QColor(_rt['muted']))
        di.setToolTip(abs_dir)
        self.tbl.setItem(r, 3, di)

        self.tbl.setItem(r, 4, self._make_arrow())

        # Col 5: category (coloured dot + category name)
        cat_color = next((c.get('color', '#4ade80') for c in self._pc_categories
                          if c['name'] == it.category), '#4ade80')
        ci = self._it(f"\u2B24 {it.category}")
        ci.setForeground(QColor(cat_color))
        f = ci.font(); f.setBold(True); ci.setFont(f)
        self.tbl.setItem(r, 5, ci)

        # Col 6: Rename To (template-resolved display name)
        renamed = it.display_name != it.name
        rn_text = it.display_name if renamed else "—"
        ri = self._it(rn_text)
        ri.setForeground(QColor(_rt['sidebar_btn_active_fg']) if renamed else QColor(_rt['muted']))
        if renamed:
            ri.setToolTip(f"Renamed: {it.name} → {it.display_name}")
        else:
            ri.setToolTip("No rename template for this category")
        self.tbl.setItem(r, 6, ri)

        # Col 7: size (numeric sort by bytes)
        sz = format_size(it.size) if it.size else ("—" if it.is_folder else "0 B")
        si = self._nit(sz, it.size or 0)
        si.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        si.setForeground(QColor(_rt['muted']))
        self.tbl.setItem(r, 7, si)

        # Col 8: confidence (smooth heatmap, numeric sort)
        cfi = self._nit(f"{it.confidence}%", it.confidence)
        cfi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        cfi.setForeground(QColor(self._confidence_text_color(it.confidence)))
        self.tbl.setItem(r, 8, cfi)

        # Col 9: method
        mi = self._it(it.method.replace('_', ' '))
        mi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        mi.setForeground(QColor(self._METHOD_COLORS_FILES.get(it.method, '#888')))
        # Build tooltip with detail + vision info + metadata summary
        tip_lines = []
        if it.detail:
            tip_lines.append(it.detail)
        if it.vision_description:
            if tip_lines:
                tip_lines.append("─" * 25)
            tip_lines.append(f"👁 {it.vision_description}")
        if it.vision_ocr:
            tip_lines.append(f"📝 OCR: {it.vision_ocr}")
        if it.metadata:
            meta_summary = MetadataExtractor.format_summary(it.metadata)
            if meta_summary:
                if tip_lines:
                    tip_lines.append("─" * 25)
                tip_lines.append(f"📋 {meta_summary}")
        if tip_lines:
            mi.setToolTip('\n'.join(tip_lines))
        self.tbl.setItem(r, 9, mi)

        # Col 10: status
        sti = self._it("Skip" if it.is_duplicate else "Pending")
        sti.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        sti.setForeground(QColor("#6b7280" if it.is_duplicate else "#f59e0b"))
        self.tbl.setItem(r, 10, sti)

        # Row tinting — category color at 10% opacity (duplicates keep yellow/green)
        if it.is_duplicate:
            bg = QColor(245, 158, 11, 20)
        elif it.dup_group > 0 and it.dup_is_original:
            bg = QColor(74, 222, 128, 18)
        else:
            cat_color_hex = next((c.get('color', '#4ade80') for c in self._pc_categories
                                  if c['name'] == it.category), '#4ade80')
            cat_qcolor = QColor(cat_color_hex)
            bg = QColor(cat_qcolor.red(), cat_qcolor.green(), cat_qcolor.blue(), 18)
        for col in range(self.tbl.columnCount()):
            item = self.tbl.item(r, col)
            if item: item.setBackground(bg)

    def _files_cb(self, idx, st):
        if idx < len(self.file_items):
            self.file_items[idx].selected = bool(st); self._stats_files()

    def _stats_files(self):
        items = self.file_items
        total = len(items)
        sel   = sum(1 for it in items if it.selected)
        done  = sum(1 for it in items if it.status == "Done")
        dups  = sum(1 for it in items if it.is_duplicate)
        renamed = sum(1 for it in items if it.display_name != it.name)
        dup_groups = len(set(it.dup_group for it in items if it.dup_group > 0))
        vision = sum(1 for it in items if it.method == 'vision')
        avg_conf = sum(it.confidence for it in items) / total if total else 0
        cats = len(set(it.category for it in items if it.category))
        parts = [f"{total} items", f"{sel} selected", f"{done} moved"]
        if cats:
            parts.append(f"{cats} categories")
        if avg_conf > 0:
            parts.append(f"avg {avg_conf:.0f}%")
        if renamed:
            parts.append(f"{renamed} renamed")
        if vision:
            parts.append(f"{vision} vision")
        if dups:
            parts.append(f"{dups} dupes in {dup_groups} groups")
        self.lbl_stats.setText(" | ".join(parts))
        self._update_mode_badges()

    # ═══ DRY-RUN / EXPORT PLAN ═══════════════════════════════════════════════
    def _export_plan(self):
        """Export the current classification plan as CSV (dry-run report)."""
        op = self.cmb_op.currentIndex()
        if op == self.OP_FILES:
            items = self.file_items
        elif op in (self.OP_CAT, self.OP_SMART):
            items = self.cat_items
        else:
            items = self.aep_items
        if not items: self._log("No items to export"); return
        path, _ = QFileDialog.getSaveFileName(self, "Export Plan", "", "CSV Files (*.csv)")
        if not path: return
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                if op == self.OP_FILES:
                    w.writerow(["Selected", "Name", "Rename To", "Source Path", "Destination",
                                "Category", "Size", "Confidence", "Method", "Status",
                                "Dup Group", "Dup Detail", "Metadata"])
                    for it in items:
                        meta_str = MetadataExtractor.format_summary(it.metadata) if it.metadata else ''
                        rename_to = it.display_name if it.display_name != it.name else ''
                        dup_grp = f"G{it.dup_group}" if it.dup_group > 0 else ''
                        w.writerow([it.selected, it.name, rename_to, it.full_src, it.full_dst,
                                    it.category, it.size, it.confidence, it.method,
                                    it.status, dup_grp, it.dup_detail, meta_str])
                elif op in (self.OP_CAT, self.OP_SMART):
                    w.writerow(["Selected", "Source Path", "Destination Path", "Category", "Confidence", "Method", "Detail", "Status"])
                    for it in items:
                        w.writerow([it.selected, it.full_source_path, it.full_dest_path,
                                    it.category, f"{it.confidence:.0f}", it.method, it.detail, it.status])
                else:
                    w.writerow(["Selected", "Source Path", "New Path", "AEP File", "Size", "Status"])
                    for it in items:
                        w.writerow([it.selected, it.full_current_path, it.full_new_path,
                                    it.aep_file, it.file_size, it.status])
            self._log(f"Plan exported to: {path}")
        except Exception as e:
            self._log(f"Export error: {e}")

    def _open_destination(self):
        """Open the current destination folder in the system file explorer."""
        op = self.cmb_op.currentIndex()
        if op == self.OP_FILES:
            # For PC Files, open the first custom_dst or user home
            for c in self._pc_categories:
                p = c.get('custom_dst', '').strip() or self._default_pc_dst(c['name'])
                if os.path.isdir(p):
                    target = p; break
            else:
                target = os.path.expanduser("~")
        elif op in (self.OP_CAT, self.OP_SMART):
            target = self.txt_dst.text() if self.txt_dst.text() else os.path.expanduser("~")
        else:
            target = self.txt_src.text() if self.txt_src.text() else os.path.expanduser("~")
        if not os.path.isdir(target):
            self._log(f"Destination not found: {target}"); return
        if sys.platform == 'win32': os.startfile(target)
        elif sys.platform == 'darwin': subprocess.Popen(['open', target])
        else: subprocess.Popen(['xdg-open', target])

    def _export_html(self):
        """Export scan results as a styled HTML report."""
        op = self.cmb_op.currentIndex()
        if op == self.OP_FILES:
            items = self.file_items
        elif op in (self.OP_CAT, self.OP_SMART):
            items = self.cat_items
        else:
            items = self.aep_items
        if not items: self._log("No items to export"); return
        path, _ = QFileDialog.getSaveFileName(self, "Export HTML Report", "UniFile_Report.html", "HTML Files (*.html)")
        if not path: return
        try:
            html = ['<!DOCTYPE html><html><head><meta charset="utf-8">',
                    '<title>UniFile Report</title>',
                    '<style>',
                    'body{background:#0a1520;color:#c5cdd8;font-family:"Segoe UI",sans-serif;margin:20px;}',
                    'h1{color:#4fc3f7;border-bottom:2px solid #1a3050;padding-bottom:8px;}',
                    '.stats{color:#6b9ab8;margin-bottom:16px;font-size:14px;}',
                    'table{border-collapse:collapse;width:100%;margin-top:12px;}',
                    'th{background:#0d1b2a;color:#4fc3f7;padding:10px 12px;text-align:left;border-bottom:2px solid #1a3050;font-size:12px;}',
                    'td{padding:8px 12px;border-bottom:1px solid #111c28;font-size:12px;}',
                    'tr:hover{background:#0d1b2a;}',
                    '.hi{color:#4ade80;} .med{color:#f59e0b;} .lo{color:#ef4444;}',
                    '.method{font-weight:bold;} .cat{font-weight:bold;}',
                    '</style></head><body>',
                    f'<h1>UniFile Report</h1>',
                    f'<div class="stats">{self.lbl_stats.text()}</div>',
                    '<table><thead><tr>']
            if op == self.OP_FILES:
                for h in ['Name', 'Category', 'Rename To', 'Size', 'Confidence', 'Method', 'Status']:
                    html.append(f'<th>{h}</th>')
                html.append('</tr></thead><tbody>')
                for it in items:
                    cc = 'hi' if it.confidence >= CONF_HIGH else 'med' if it.confidence >= CONF_MEDIUM else 'lo'
                    rename = it.display_name if it.display_name != it.name else '—'
                    sz = format_size(it.size) if it.size else '—'
                    html.append(f'<tr><td>{it.name}</td><td class="cat">{it.category}</td>'
                                f'<td>{rename}</td><td>{sz}</td>'
                                f'<td class="{cc}">{it.confidence}%</td>'
                                f'<td class="method">{it.method}</td><td>{it.status}</td></tr>')
            elif op in (self.OP_CAT, self.OP_SMART):
                for h in ['Source', 'Destination', 'Category', 'Confidence', 'Method', 'Status']:
                    html.append(f'<th>{h}</th>')
                html.append('</tr></thead><tbody>')
                for it in items:
                    cc = 'hi' if it.confidence >= CONF_HIGH else 'med' if it.confidence >= CONF_MEDIUM else 'lo'
                    html.append(f'<tr><td>{it.full_source_path}</td><td>{it.full_dest_path}</td>'
                                f'<td class="cat">{it.category}</td>'
                                f'<td class="{cc}">{it.confidence:.0f}%</td>'
                                f'<td class="method">{it.method}</td><td>{it.status}</td></tr>')
            else:
                for h in ['Source', 'New Path', 'AEP File', 'Size', 'Status']:
                    html.append(f'<th>{h}</th>')
                html.append('</tr></thead><tbody>')
                for it in items:
                    html.append(f'<tr><td>{it.full_current_path}</td><td>{it.full_new_path}</td>'
                                f'<td>{it.aep_file}</td><td>{it.file_size}</td><td>{it.status}</td></tr>')
            html.append('</tbody></table></body></html>')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(html))
            self._log(f"HTML report exported to: {path}")
        except Exception as e:
            self._log(f"HTML export error: {e}")

    def keyPressEvent(self, event):
        """Keyboard navigation for the main table."""
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.tbl.clearSelection()
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            # Toggle checkbox on selected rows
            sel_rows = sorted(set(idx.row() for idx in self.tbl.selectionModel().selectedRows()))
            for r in sel_rows:
                w = self.tbl.cellWidget(r, 0)
                if isinstance(w, QCheckBox):
                    w.setChecked(not w.isChecked())
        elif key == Qt.Key.Key_Space:
            # Open in explorer for the first selected row
            sel_rows = sorted(set(idx.row() for idx in self.tbl.selectionModel().selectedRows()))
            if sel_rows:
                row = sel_rows[0]
                op = self.cmb_op.currentIndex()
                path = None
                if op == self.OP_FILES and row < len(self.file_items):
                    path = self.file_items[row].full_src
                elif op in (self.OP_CAT, self.OP_SMART) and row < len(self.cat_items):
                    path = self.cat_items[row].full_source_path
                elif row < len(self.aep_items):
                    path = self.aep_items[row].full_current_path
                if path:
                    target = path if os.path.isdir(path) else os.path.dirname(path)
                    if sys.platform == 'win32': os.startfile(target)
                    elif sys.platform == 'darwin': subprocess.Popen(['open', target])
                    else: subprocess.Popen(['xdg-open', target])
        elif key == Qt.Key.Key_Delete:
            # Uncheck selected rows
            sel_rows = sorted(set(idx.row() for idx in self.tbl.selectionModel().selectedRows()))
            for r in sel_rows:
                w = self.tbl.cellWidget(r, 0)
                if isinstance(w, QCheckBox):
                    w.setChecked(False)
        else:
            super().keyPressEvent(event)

    # ═══ EXPORT/IMPORT RULES ═════════════════════════════════════════════════
    def _export_rules(self):
        """Export custom categories + corrections as JSON."""
        path, _ = QFileDialog.getSaveFileName(self, "Export Rules", "unifile_rules.json", "JSON Files (*.json)")
        if not path: return
        try:
            export_rules_bundle(path)
            corr_count = len(load_corrections())
            cat_count = len(load_custom_categories())
            self._log(f"Rules exported: {cat_count} custom categories, {corr_count} corrections -> {path}")
        except Exception as e:
            self._log(f"Export error: {e}")

    def _import_rules(self):
        """Import custom categories + corrections from JSON."""
        path, _ = QFileDialog.getOpenFileName(self, "Import Rules", "", "JSON Files (*.json)")
        if not path: return
        try:
            bundle = import_rules_bundle(path)
            cats = len(bundle.get('custom_categories', []))
            corrs = len(bundle.get('corrections', {}))
            self._log(f"Rules imported: {cats} custom categories, {corrs} corrections from {path}")
        except Exception as e:
            self._log(f"Import error: {e}")

    def _clear_cache(self):
        """Clear the classification cache."""
        n = cache_count()
        cache_clear()
        self._log(f"Cache cleared ({n} entries removed)")

    # ═══ WINDOWS SHELL INTEGRATION ═══════════════════════════════════════════
    def _register_shell_extension(self):
        """Register 'Organize with UniFile' context menu for folders (Windows only)."""
        if sys.platform != 'win32':
            self._log("Shell integration is Windows-only"); return
        import winreg
        script_path = os.path.abspath(__file__) if '__file__' in dir() else ''
        if not script_path:
            self._log("Cannot determine script path"); return
        cmd = f'"{sys.executable}" "{script_path}" --source "%V"'
        try:
            key_path = r"Software\Classes\Directory\shell\UniFile"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Organize with UniFile")
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, sys.executable)
            cmd_path = key_path + r"\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cmd)
            # Also for directory background
            bg_path = r"Software\Classes\Directory\Background\shell\UniFile"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Organize with UniFile")
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, sys.executable)
            bg_cmd_path = bg_path + r"\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_cmd_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cmd)
            self._log("Shell extension registered (right-click folders to organize)")
        except Exception as e:
            self._log(f"Failed to register shell extension: {e}")

    def _unregister_shell_extension(self):
        """Remove the shell context menu entry."""
        if sys.platform != 'win32':
            return
        import winreg
        for base in [r"Software\Classes\Directory\shell\UniFile",
                     r"Software\Classes\Directory\Background\shell\UniFile"]:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + r"\command")
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
            except OSError:
                pass
        self._log("Shell extension unregistered")

    # ═══ THUMBNAIL GRID VIEW ═════════════════════════════════════════════════
    def _toggle_grid_view(self):
        """Toggle between table view and thumbnail grid view."""
        show_grid = self.btn_grid_toggle.isChecked()
        if show_grid:
            self.tbl.hide()
            self.grid_scroll.show()
            self.map_widget.hide()
            self.btn_map_toggle.setChecked(False)
            self.graph_widget.hide()
            self.btn_graph_toggle.setChecked(False)
            self.btn_grid_toggle.setText("Table View")
            self._populate_grid()
        else:
            self.grid_scroll.hide()
            self.tbl.show()
            self.btn_grid_toggle.setText("Grid View")

    def _populate_grid(self):
        """Populate the thumbnail grid with current file_items."""
        # Clear existing
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        # Add cards
        _IMAGE_EXTS = ThumbnailCard._IMAGE_EXTS
        pool = QThreadPool.globalInstance()
        for idx, it in enumerate(self.file_items):
            cat_color = next(
                (c.get('color', '#4ade80') for c in self._pc_categories
                 if c['name'] == it.category), '#4ade80')
            card = ThumbnailCard(
                idx, os.path.basename(it.full_src), it.category,
                cat_color, it.full_src, self._grid_container)
            card.clicked.connect(self._on_grid_card_clicked)
            self._grid_layout.addWidget(card)
            # Load thumbnail in background for image files
            ext = os.path.splitext(it.full_src)[1].lower()
            if ext in _IMAGE_EXTS:
                loader = ThumbnailLoader(it.full_src, 150)
                loader.signals.ready.connect(self._on_thumb_loaded)
                pool.start(loader)

    def _on_thumb_loaded(self, file_path: str, pm: QPixmap):
        """Called when a thumbnail finishes loading."""
        for i in range(self._grid_layout.count()):
            item = self._grid_layout.itemAt(i)
            if item and item.widget():
                card = item.widget()
                if isinstance(card, ThumbnailCard) and card.file_path == file_path:
                    card.set_pixmap(pm)
                    break

    def _on_grid_card_clicked(self, idx: int):
        """Handle click on a grid card — toggle selection on the item."""
        if 0 <= idx < len(self.file_items):
            self.file_items[idx].selected = not self.file_items[idx].selected

    # ═══ MAP VIEW ════════════════════════════════════════════════════════════
    def _toggle_map_view(self):
        """Toggle the map view panel."""
        show_map = self.btn_map_toggle.isChecked()
        if show_map:
            self.tbl.hide()
            self.grid_scroll.hide()
            self.btn_grid_toggle.setChecked(False)
            self.btn_grid_toggle.setText("Grid View")
            self.graph_widget.hide()
            self.btn_graph_toggle.setChecked(False)
            self.map_widget.show()
            self.map_widget.load_markers(self.file_items)
        else:
            self.map_widget.hide()
            self.tbl.show()

    def _update_map_button_visibility(self):
        """Show map button only when GPS data exists in file_items."""
        if self.cmb_op.currentIndex() == self.OP_FILES and self.file_items:
            has_gps = self.map_widget.has_gps_items(self.file_items)
            self.btn_map_toggle.setVisible(has_gps)
        else:
            self.btn_map_toggle.setVisible(False)

    # ═══ WATCH FOLDER MODE ═══════════════════════════════════════════════════
    def _setup_tray(self):
        """Set up the system tray icon for watch mode."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("UniFile — Watch Mode")
        # Use app icon if available
        icon = self.windowIcon()
        if not icon.isNull():
            self._tray.setIcon(icon)
        else:
            self._tray.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_ComputerIcon))
        # Tray menu
        tray_menu = QMenu()
        tray_menu.setStyleSheet(get_active_stylesheet())
        act_show = tray_menu.addAction("Show UniFile")
        act_show.triggered.connect(self._tray_show)
        act_pause = tray_menu.addAction("Pause Watch")
        act_pause.triggered.connect(self._watch_pause)
        tray_menu.addSeparator()
        act_exit = tray_menu.addAction("Exit")
        act_exit.triggered.connect(self._tray_exit)
        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        """Show window on tray icon double-click."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show()

    def _tray_show(self):
        """Restore window from system tray."""
        self.showNormal()
        self.activateWindow()

    def _tray_exit(self):
        """Exit the application from tray."""
        if self._watch_manager and self._watch_manager.is_active:
            self._watch_manager.stop()
        self._save_settings()
        QApplication.instance().quit()

    def _watch_pause(self):
        """Pause/resume watch mode from tray."""
        if self._watch_manager and self._watch_manager.is_active:
            self._watch_manager.stop()
            self.btn_watch.setChecked(False)
            self._log("Watch mode paused")
            if self._tray:
                self._tray.showMessage("UniFile", "Watch mode paused",
                                       QSystemTrayIcon.MessageIcon.Information, 2000)

    def _toggle_watch_mode(self):
        """Toggle watch folder auto-organize mode."""
        if self.btn_watch.isChecked():
            # Open settings dialog
            settings = _load_watch_settings()
            dlg = WatchSettingsDialog(settings, self)
            if dlg.exec():
                new_settings = dlg.get_settings()
                _save_watch_settings(new_settings)
                # Start watching
                if not self._watch_manager:
                    self._watch_manager = WatchModeManager(self)
                folders = new_settings.get('folders', [])
                if folders:
                    self._watch_manager.start(folders, new_settings.get('delay_seconds', 5))
                    self._log(f"Watch mode active: monitoring {len(folders)} folder(s)")
                    _t = get_active_theme()
                    self.btn_watch.setStyleSheet(
                        f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {_t['sidebar_profile_fg']};"
                        f"color: {_t['sidebar_brand']}; border: 1px solid {_t['sidebar_profile_fg']}; border-radius: 4px; font-weight: bold; }}"
                        f"QPushButton:hover {{ background: {_t['accent_hover']}; }}")
                    if self._tray:
                        self._tray.show()
                        self._tray.showMessage("UniFile", f"Watching {len(folders)} folder(s)",
                                               QSystemTrayIcon.MessageIcon.Information, 3000)
                else:
                    self._log("No folders configured for watch mode")
                    self.btn_watch.setChecked(False)
            else:
                self.btn_watch.setChecked(False)
        else:
            # Stop watching
            if self._watch_manager and self._watch_manager.is_active:
                self._watch_manager.stop()
            self._log("Watch mode stopped")
            _t = get_active_theme()
            self.btn_watch.setStyleSheet(
                f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {_t['sidebar_profile_border']};"
                f"color: {_t['sidebar_profile_fg']}; border: 1px solid {_t['border']}; border-radius: 4px; }}"
                f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
            if self._tray:
                self._tray.hide()

    # ═══ FILE PREVIEW PANEL ═════════════════════════════════════════════════
    def _on_row_selected(self, row, col, prev_row, prev_col):
        """Called when the user clicks a table row — update preview panel."""
        if not self.btn_preview_toggle.isChecked():
            return
        if row < 0:
            self.preview_panel.clear(); return
        op = self.cmb_op.currentIndex()
        idx = self._item_idx_from_row(row)
        if op == self.OP_FILES and 0 <= idx < len(self.file_items):
            it = self.file_items[idx]
            self.preview_panel.show_file(it.full_src, it.metadata if it.metadata else {})
        elif op in (self.OP_CAT, self.OP_SMART) and 0 <= idx < len(self.cat_items):
            self.preview_panel.show_file(self.cat_items[idx].full_source_path, {})
        else:
            self.preview_panel.clear()

    def _toggle_preview_panel(self):
        """Toggle file preview side panel."""
        show = self.btn_preview_toggle.isChecked()
        self.preview_panel.setVisible(show)
        if show and self.tbl.currentRow() >= 0:
            self._on_row_selected(self.tbl.currentRow(), 0, -1, -1)

    # ═══ GRAPH VIEW ══════════════════════════════════════════════════════════
    def _toggle_graph_view(self):
        """Toggle the file relationship graph view."""
        show = self.btn_graph_toggle.isChecked()
        if show:
            self.tbl.hide()
            self.grid_scroll.hide()
            self.map_widget.hide()
            self.graph_widget.show()
            self.btn_grid_toggle.setChecked(False)
            self.btn_map_toggle.setChecked(False)
            if self.file_items:
                self.graph_widget.load_items(self.file_items)
        else:
            self.graph_widget.hide()
            self.tbl.show()

    def _on_graph_node_clicked(self, idx: int):
        """Select the corresponding row in the table when graph node is clicked."""
        if 0 <= idx < len(self.file_items):
            self.btn_graph_toggle.setChecked(False)
            self._toggle_graph_view()
            # Find the visual row that stores this item index
            for r in range(self.tbl.rowCount()):
                if self._item_idx_from_row(r) == idx:
                    self.tbl.selectRow(r); break

    # ═══ BEFORE/AFTER COMPARISON ═════════════════════════════════════════════
    def _show_before_after(self):
        """Show before/after directory structure comparison."""
        op = self.cmb_op.currentIndex()
        items = self.file_items if op == self.OP_FILES else self.cat_items
        if not items:
            self._log("No items to compare"); return
        src_root = self._pc_src_path() if op == self.OP_FILES else ''
        dlg = BeforeAfterDialog(items, src_root, self)
        dlg.exec()

    # ═══ EVENT GROUPING ══════════════════════════════════════════════════════
    def _show_event_grouping(self):
        """Launch AI event grouping on vision-analyzed items."""
        vision_items = [it for it in self.file_items if it.vision_description]
        if not vision_items:
            self._log("No vision-analyzed items for event grouping"); return
        self._log(f"Grouping {len(vision_items)} items by event…")
        groups = EventGrouper.group_by_time(vision_items)
        if not groups:
            self._log("No event groups detected"); return
        dlg = EventGroupDialog(groups, self)
        dlg.exec()

    # ═══ DUPLICATE COMPARISON ════════════════════════════════════════════════
    def _show_dup_compare(self, group_id: int):
        """Show duplicate comparison dialog for a specific group."""
        group_items = [it for it in self.file_items if it.dup_group == group_id]
        if len(group_items) < 2:
            self._log("No duplicate group found"); return
        dlg = DuplicateCompareDialog(self.file_items, group_id, self)
        dlg.exec()

    # ═══ CATEGORY PRESETS ════════════════════════════════════════════════════
    def _refresh_presets_menu(self):
        """Rebuild the Category Presets submenu."""
        self.menu_presets.clear()
        self.menu_presets.addAction("Save Current…", self._save_category_preset)
        self.menu_presets.addAction("Import from File…", self._import_category_preset)
        self.menu_presets.addSeparator()
        # Built-in presets
        builtins = CategoryPresetManager.builtin_presets()
        for name in builtins:
            self.menu_presets.addAction(f"📦 {name}", lambda n=name: self._load_category_preset(n, builtin=True))
        # User presets
        user_presets = CategoryPresetManager.list_presets()
        if user_presets:
            self.menu_presets.addSeparator()
            for name in user_presets:
                self.menu_presets.addAction(f"📄 {name}", lambda n=name: self._load_category_preset(n))

    def _save_category_preset(self):
        """Save current categories as a named preset."""
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if ok and name.strip():
            CategoryPresetManager.save(name.strip(), self._pc_categories)
            self._log(f"Saved category preset: {name}")
            self._refresh_presets_menu()

    def _load_category_preset(self, name: str, builtin=False):
        """Load a category preset and replace current categories."""
        if builtin:
            presets = CategoryPresetManager.builtin_presets()
            categories = presets.get(name)
        else:
            categories = CategoryPresetManager.load(name)
        if categories:
            self._pc_categories = categories
            self._log(f"Loaded preset: {name} ({len(categories)} categories)")
            self._refresh_presets_menu()
            # Refresh the category editor if open
            if hasattr(self, '_rebuild_cat_ui'):
                self._rebuild_cat_ui()

    def _import_category_preset(self):
        """Import a category preset from an external .json file."""
        path, _ = QFileDialog.getOpenFileName(self, "Import Category Preset", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    name = os.path.splitext(os.path.basename(path))[0]
                    CategoryPresetManager.save(name, data)
                    self._log(f"Imported preset: {name}")
                    self._refresh_presets_menu()
            except Exception as e:
                self._log(f"Import error: {e}")

    # ═══ DRAG-TO-RECATEGORIZE ════════════════════════════════════════════════
    def _on_category_drop(self, cat_name: str, row_indices: list):
        """Handle drag-drop from table rows onto bar chart category segments."""
        op = self.cmb_op.currentIndex()
        if op != self.OP_FILES:
            return
        cat_color = next((c.get('color', '#4ade80') for c in self._pc_categories
                          if c['name'] == cat_name), '#4ade80')
        changed = 0
        corrections = []
        for visual_row in row_indices:
            idx = self._item_idx_from_row(visual_row)
            if 0 <= idx < len(self.file_items):
                it = self.file_items[idx]
                if it.category != cat_name:
                    old_cat = it.category
                    it.category = cat_name
                    it.method = 'drag_drop'
                    changed += 1
                    corrections.append((it.filename, it.full_src, old_cat, cat_name))
                    ci = self.tbl.item(visual_row, 5)
                    if ci:
                        ci.setText(f"\u2B24 {cat_name}")
                        ci.setForeground(QColor(cat_color))
        if changed:
            self._log(f"Recategorized {changed} item(s) → {cat_name}")
            self._stats_files()
            self._update_dashboard()
            # Record as learning corrections
            try:
                learner = get_learner()
                for fname, fpath, old_cat, new_cat in corrections:
                    learner.record_correction(fname, fpath, new_cat)
            except Exception:
                pass

    # ═══ RULE EDITOR ═════════════════════════════════════════════════════════
    def _open_rule_editor(self):
        """Open the classification rule editor dialog."""
        dlg = RuleEditorDialog(self._pc_categories, self)
        dlg.exec()

    def _create_rule_from_file(self, row: int):
        """Pre-fill a rule from the selected file's metadata. `row` is visual table row."""
        idx = self._item_idx_from_row(row)
        if idx < 0 or idx >= len(self.file_items):
            return
        it = self.file_items[idx]
        ext = os.path.splitext(it.name)[1].lower()
        conditions = []
        if ext:
            conditions.append({'field': 'extension', 'op': 'eq', 'value': ext})
        if it.size:
            conditions.append({'field': 'size', 'op': 'gte', 'value': str(it.size // 2)})
        rule = {
            'name': f"Rule from {it.name}",
            'enabled': True, 'priority': 50,
            'conditions': conditions, 'logic': 'all',
            'action_category': it.category, 'action_rename': '',
        }
        rules = RuleEngine.load_rules()
        rules.append(rule)
        RuleEngine.save_rules(rules)
        self._log(f"Created rule from: {it.name}")

    # ═══ SCHEDULED SCANS ═════════════════════════════════════════════════════
    def _open_schedule_dialog(self):
        """Open the scheduled scans dialog (Windows only)."""
        dlg = ScheduleDialog(self)
        dlg.exec()

    # ═══ PLUGIN MANAGER ══════════════════════════════════════════════════════
    def _open_plugin_manager(self):
        """Open the plugin manager dialog."""
        dlg = PluginManagerDialog(self)
        dlg.exec()

    def _open_protected_paths(self):
        """Open the protected paths settings dialog."""
        dlg = ProtectedPathsDialog(self)
        dlg.exec()

    def _open_watch_history(self):
        """Open the watch history dialog."""
        dlg = WatchHistoryDialog(self)
        dlg.exec()

    def _open_sort_rules(self):
        """Open the CSV sort rules editor."""
        dlg = CsvRulesDialog(self)
        dlg.exec()

    def _open_theme_picker(self):
        """Open the theme picker dialog."""
        dlg = ThemePickerDialog(self)
        dlg.theme_changed.connect(self._on_theme_changed)
        dlg.exec()

    # Theme methods are provided by ThemeMixin (theme_mixin.py)

    # ═══ CLEANUP TOOLS ═══════════════════════════════════════════════════════
    def _open_cleanup_tools(self):
        """Navigate to inline cleanup panel (first tab)."""
        self._on_sidebar_tool('cleanup', 0)

    def _open_cleanup_tab(self, tab_index: int = None, *, mode: str = None):
        """Navigate to inline cleanup or duplicate panel."""
        if mode == 'duplicates':
            self._on_sidebar_tool('duplicates')
            return
        self._on_sidebar_tool('cleanup', tab_index or 0)

    # ═══ UNDO TIMELINE ═══════════════════════════════════════════════════════
    def _show_undo_timeline(self):
        """Show the visual undo timeline dialog."""
        stack = _load_undo_stack()
        if not stack:
            self._log("No undo history available"); return
        dlg = UndoTimelineDialog(self)
        dlg.exec()
        self.btn_undo.setEnabled(bool(_load_undo_stack()))

    def closeEvent(self, event):
        """Override close event to minimize to tray when watch mode is active."""
        if (self._watch_manager and self._watch_manager.is_active
                and self._tray and self._tray.isVisible()):
            settings = _load_watch_settings()
            if settings.get('minimize_to_tray', True):
                self.hide()
                self._tray.showMessage("UniFile", "Minimized to tray — Watch mode active",
                                       QSystemTrayIcon.MessageIcon.Information, 2000)
                event.ignore()
                return
        self._save_settings()
        if self._watch_manager and self._watch_manager.is_active:
            self._watch_manager.stop()
        super().closeEvent(event)

# ── Crash Handler ─────────────────────────────────────────────────────────────
