"""Theme application mixin for UniFile main window."""

from PyQt6.QtWidgets import QWidget, QSystemTrayIcon

from unifile.config import THEMES, DARK_STYLE, _build_theme_qss


class ThemeMixin:
    """Mixin containing all theme-related methods for UniFile."""

    def _on_theme_changed(self, name: str):
        """Apply a new theme live to the entire application."""
        theme = THEMES.get(name)
        if not theme:
            return
        if name == 'Steam Dark':
            qss = DARK_STYLE
        else:
            qss = _build_theme_qss(theme)
        self.setStyleSheet(qss)
        self._apply_theme_to_widgets(theme)
        self._log(f"Theme changed to: {name}")

    def _apply_sidebar_theme(self, t: dict):
        """Legacy wrapper — delegates to comprehensive theme applicator."""
        self._apply_theme_to_widgets(t)

    def _apply_theme_to_widgets(self, t: dict):
        """Re-apply ALL inline widget styles when the theme changes."""

        # ── Sidebar ──────────────────────────────────────────────────────
        sidebar = self.findChild(QWidget, "sidebar")
        if sidebar:
            sidebar.setStyleSheet(
                f"QWidget#sidebar {{ background: {t['sidebar_bg']}; "
                f"border-right: 1px solid {t['sidebar_border']}; }}")

        _NAV_BTN = (
            f"QPushButton {{ background: transparent; color: {t['sidebar_btn']}; border: none;"
            f"border-left: 3px solid transparent; padding: 10px 14px; font-size: 12px;"
            f"font-weight: 500; text-align: left; }}"
            f"QPushButton:hover {{ background: {t['sidebar_btn_hover_bg']}; color: {t['fg']};"
            f"border-left: 3px solid {t['sidebar_btn_hover_border']}; }}"
            f"QPushButton:checked {{ background: {t['sidebar_btn_active_bg']}; color: {t['sidebar_btn_active_fg']};"
            f"border-left: 3px solid {t['sidebar_btn_active_border']}; font-weight: 600; }}"
        )
        for _, _, btn in self._nav_buttons:
            btn.setStyleSheet(_NAV_BTN)

        # Brand header widget
        if hasattr(self, '_brand_w'):
            self._brand_w.setStyleSheet(
                f"background: {t['sidebar_brand']}; border-bottom: 1px solid {t['sidebar_border']};")

        # LLM status widget
        if hasattr(self, '_llm_w'):
            self._llm_w.setStyleSheet(
                f"background: {t['sidebar_brand']}; border-top: 1px solid {t['sidebar_border']};")

        # Section labels
        _NAV_SECTION = (
            f"color: {t['sidebar_section']}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;"
            f"padding: 12px 16px 4px 16px; background: transparent;"
        )
        if hasattr(self, '_nav_section_labels'):
            for lbl in self._nav_section_labels:
                lbl.setStyleSheet(_NAV_SECTION)

        # Profile combo
        if hasattr(self, 'cmb_profile'):
            self.cmb_profile.setStyleSheet(
                f"QComboBox {{ background: {t['sidebar_profile_bg']}; color: {t['sidebar_profile_fg']}; "
                f"border: 1px solid {t['sidebar_profile_border']};"
                f"border-radius: 4px; padding: 6px 10px; font-size: 11px; font-weight: bold; }}"
                f"QComboBox:hover {{ border-color: {t['sidebar_profile_fg']}; }}"
                f"QComboBox::drop-down {{ border: none; }}"
                f"QComboBox QAbstractItemView {{ background: {t['sidebar_profile_bg']}; color: {t['fg']};"
                f"selection-background-color: {t['selection']}; border: 1px solid {t['sidebar_profile_border']}; }}")

        # ── Action Bar ───────────────────────────────────────────────────
        if hasattr(self, '_themed_action_bar'):
            self._themed_action_bar.setStyleSheet(
                f"QWidget#action_bar {{ background: {t['header_bg']}; border-bottom: 1px solid {t['btn_bg']}; }}")

        # ── Dir Panel ────────────────────────────────────────────────────
        if hasattr(self, '_themed_dir_panel'):
            self._themed_dir_panel.setStyleSheet(
                f"QWidget#dir_panel {{ background: {t['bg_alt']}; border-bottom: 1px solid {t['btn_bg']}; }}")

        # ── Toolbar buttons (common style helper) ────────────────────────
        _TB = (
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {t['selection']};"
            f"color: {t['sidebar_btn_active_fg']}; border: 1px solid {t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}"
        )
        _TB_SMALL = (
            f"QPushButton {{ font-size: 11px; padding: 2px 8px; background: {t['selection']};"
            f"color: {t['sidebar_btn_active_fg']}; border: 1px solid {t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}"
        )
        _TB_CHECK = _TB_SMALL + (
            f"QPushButton:checked {{ background: {t['sidebar_btn_active_fg']}; color: {t['sidebar_brand']}; }}"
        )

        # Replay, Export, Export HTML, Open Dest
        for btn in [self.btn_replay, self.btn_export, self.btn_export_html, self.btn_open_dest]:
            btn.setStyleSheet(_TB)

        # PC Cats button
        self.btn_pc_cats.setStyleSheet(_TB)

        # Photo button (green accent)
        self.btn_photo.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {t['selection']};"
            f"color: {t['green']}; border: 1px solid {t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}")

        # Grid, Preview, Graph toggles (checkable, standard accent)
        self.btn_grid_toggle.setStyleSheet(_TB_CHECK)
        self.btn_preview_toggle.setStyleSheet(_TB_CHECK)
        self.btn_graph_toggle.setStyleSheet(_TB_CHECK)

        # Map toggle (green checkable)
        self.btn_map_toggle.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px; background: {t['selection']};"
            f"color: {t['green']}; border: 1px solid {t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}"
            f"QPushButton:checked {{ background: {t['green']}; color: {t['sidebar_brand']}; }}")

        # Before/After
        self.btn_before_after.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px; background: {t['selection']};"
            f"color: {t['accent_hover']}; border: 1px solid {t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}")

        # Events
        self.btn_events.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px; background: {t['selection']};"
            f"color: {t['accent_hover']}; border: 1px solid {t['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}")

        # Watch Mode button
        if hasattr(self, 'btn_watch'):
            self.btn_watch.setStyleSheet(_TB_CHECK)

        # ── Filter controls ──────────────────────────────────────────────
        if hasattr(self, 'lbl_conf'):
            self.lbl_conf.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        if hasattr(self, '_themed_lbl_cf'):
            self._themed_lbl_cf.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")

        if hasattr(self, 'cmb_face_filter'):
            self.cmb_face_filter.setStyleSheet(
                f"QComboBox {{ font-size: 11px; background: {t['selection']}; color: {t['green']};"
                f"border: 1px solid {t['border']}; border-radius: 4px; padding: 2px 6px; }}")

        if hasattr(self, 'cmb_type_filter'):
            self.cmb_type_filter.setStyleSheet(
                f"QComboBox {{ background: {t['input_bg']}; color: {t['accent_hover']}; border: 1px solid {t['border']};"
                f"border-radius: 3px; padding: 2px 6px; font-size: 11px; font-weight: bold; }}"
                f"QComboBox:hover {{ border-color: {t['accent_hover']}; }}"
                f"QComboBox::drop-down {{ border: none; }}"
                f"QComboBox QAbstractItemView {{ background: {t['input_bg']}; color: {t['fg']};"
                f"selection-background-color: {t['selection']}; border: 1px solid {t['border']}; }}")

        # ── Dashboard ────────────────────────────────────────────────────
        if hasattr(self, 'dashboard_panel'):
            self.dashboard_panel.setStyleSheet(
                f"background: {t['header_bg']}; border-radius: 6px; padding: 4px;")
        if hasattr(self, 'lbl_dash_summary'):
            self.lbl_dash_summary.setStyleSheet(
                f"color: {t['fg']}; font-size: 12px; font-weight: bold;")
        if hasattr(self, '_themed_btn_hide_dash'):
            self._themed_btn_hide_dash.setStyleSheet(
                f"QPushButton{{font-size:10px;color:{t['muted']};background:{t['sidebar_brand']};"
                f"border:1px solid {t['border']};border-radius:3px}}"
                f"QPushButton:hover{{color:{t['fg']}}}")

        # ── Empty / Toast / Stats ────────────────────────────────────────
        if hasattr(self, 'lbl_empty'):
            self.lbl_empty.setStyleSheet(
                f"color: {t['muted']}; font-size: 13px; padding: 50px; font-weight: 500;")
        if hasattr(self, 'lbl_toast'):
            self.lbl_toast.setStyleSheet(
                f"QLabel {{ background: {t['selection']};"
                f"color: {t['fg']}; font-size: 13px; font-weight: bold;"
                f"padding: 10px 20px; border-radius: 8px;"
                f"border: 1px solid {t['border']}; }}")
        if hasattr(self, 'lbl_stats'):
            self.lbl_stats.setStyleSheet(
                f"color: {t['muted']}; font-size: 12px; padding: 4px 0;")

        # ── Progress Panel ───────────────────────────────────────────────
        if hasattr(self, 'prog_panel'):
            self.prog_panel.setStyleSheet(
                f"QWidget#prog_panel {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
                f"border-radius: 6px; margin: 2px 0; }}")
        if hasattr(self, 'lbl_prog_phase'):
            self.lbl_prog_phase.setStyleSheet(
                f"color: {t['sidebar_btn_active_fg']}; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;")
        if hasattr(self, 'lbl_prog_counter'):
            self.lbl_prog_counter.setStyleSheet(
                f"color: {t['fg']}; font-size: 11px; font-family: monospace;")
        if hasattr(self, 'lbl_prog_eta'):
            self.lbl_prog_eta.setStyleSheet(
                f"color: {t['muted']}; font-size: 11px; padding-left: 10px;")
        if hasattr(self, 'pbar'):
            self.pbar.setStyleSheet(
                f"QProgressBar {{ background:{t['header_bg']}; border:none; border-radius:3px; }}"
                f"QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {t['accent']}, stop:0.5 {t['sidebar_btn_active_fg']}, stop:1 {t['accent']}); border-radius:3px; }}")
        if hasattr(self, 'lbl_prog_method'):
            self.lbl_prog_method.setStyleSheet(
                f"color: {t['muted']}; font-size: 11px; font-style: italic;")
        if hasattr(self, 'lbl_prog_speed'):
            self.lbl_prog_speed.setStyleSheet(
                f"color: {t['muted']}; font-size: 11px; font-family: monospace;")

        # ── Console Log ──────────────────────────────────────────────────
        if hasattr(self, 'btn_toggle_log'):
            self.btn_toggle_log.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t['muted']}; font-size: 11px; "
                f"border: none; padding: 2px 4px; text-align: left; font-family: monospace; }}"
                f"QPushButton:hover {{ color: {t['fg']}; }}"
                f"QPushButton:checked {{ color: {t['sidebar_btn_active_fg']}; }}")
        if hasattr(self, '_themed_btn_clear_log'):
            self._themed_btn_clear_log.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t['muted']}; font-size: 11px; "
                f"border: none; padding: 2px 6px; }}"
                f"QPushButton:hover {{ color: #ef4444; }}")
        if hasattr(self, 'txt_log'):
            self.txt_log.setStyleSheet(
                f"QTextEdit {{ background:{t['header_bg']}; color:{t['muted']}; font-family: 'Consolas','Courier New',monospace; "
                f"font-size: 11px; border: 1px solid {t['border']}; border-radius: 4px; padding: 4px; }}")

        # ── Status Bar ───────────────────────────────────────────────────
        if hasattr(self, '_themed_status_bar'):
            self._themed_status_bar.setStyleSheet(
                f"background-color: {t['sidebar_brand']}; border-top: 1px solid {t['sidebar_border']};")
        if hasattr(self, 'lbl_statusbar'):
            self.lbl_statusbar.setStyleSheet(
                f"color: {t['muted']}; font-size: 11px; font-family: monospace;")
        if hasattr(self, 'lbl_ollama') and not self._ollama_ready:
            self.lbl_ollama.setStyleSheet(
                f"color: {t['muted']}; font-size: 11px; font-family: monospace;")

        # ── Grid Scroll ──────────────────────────────────────────────────
        if hasattr(self, 'grid_scroll'):
            self.grid_scroll.setStyleSheet(
                f"QScrollArea {{ background: {t['header_bg']}; border: none; }}")
