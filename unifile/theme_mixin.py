"""Theme application mixin for UniFile main window."""

from PyQt6.QtWidgets import QWidget

from unifile.config import DARK_STYLE, THEMES, _build_theme_qss, load_font_size


class ThemeMixin:
    """Mixin containing all theme-related methods for UniFile."""

    def _on_theme_changed(self, name: str):
        """Apply a new theme live to the entire application."""
        theme = THEMES.get(name)
        if not theme:
            return
        fs = load_font_size()
        if name == 'Steam Dark' and fs == 13:
            qss = DARK_STYLE
        else:
            qss = _build_theme_qss(theme, fs)
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
            f"border-left: 3px solid transparent; padding: 11px 15px; font-size: 12px;"
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
        if hasattr(self, 'lbl_brand'):
            self.lbl_brand.setStyleSheet(
                f"color: {t['fg_bright']}; font-size: 16px; font-weight: 700; letter-spacing: -0.5px;"
                "background: transparent;")
        if hasattr(self, 'lbl_brand_meta'):
            self.lbl_brand_meta.setStyleSheet(
                f"color: {t['muted']}; font-size: 10px; font-weight: 600; background: transparent;")

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
                f"border-radius: 10px; padding: 6px 10px; font-size: 11px; font-weight: bold; }}"
                f"QComboBox:hover {{ border-color: {t['sidebar_profile_fg']}; }}"
                f"QComboBox::drop-down {{ border: none; }}"
                f"QComboBox QAbstractItemView {{ background: {t['sidebar_profile_bg']}; color: {t['fg']};"
                f"selection-background-color: {t['selection']}; border: 1px solid {t['sidebar_profile_border']}; }}")

        # ── Action Bar ───────────────────────────────────────────────────
        if hasattr(self, '_themed_action_bar'):
            self._themed_action_bar.setStyleSheet(
                f"QWidget#action_bar {{ background: {t['header_bg']}; border-bottom: 1px solid {t['btn_bg']}; }}")
        if hasattr(self, 'lbl_action_kicker'):
            self.lbl_action_kicker.setStyleSheet(
                f"color: {t['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;"
            )
        if hasattr(self, 'lbl_action_hint'):
            self.lbl_action_hint.setStyleSheet(
                f"color: {t['muted']}; font-size: 11px;"
            )

        # ── Dir Panel ────────────────────────────────────────────────────
        if hasattr(self, '_themed_dir_panel'):
            self._themed_dir_panel.setStyleSheet(
                f"QWidget#dir_panel {{ background: {t['bg_alt']}; border-bottom: 1px solid {t['btn_bg']}; }}")
        if hasattr(self, 'workspace_intro'):
            self.workspace_intro.setStyleSheet(
                f"QFrame#workspace_intro {{ background: {t['header_bg']}; border: 1px solid {t['border']}; border-radius: 18px; }}"
            )
        if hasattr(self, 'lbl_workspace_section'):
            self.lbl_workspace_section.setStyleSheet(
                f"color: {t['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;"
            )
        if hasattr(self, 'lbl_workspace_title'):
            self.lbl_workspace_title.setStyleSheet(
                f"color: {t['fg_bright']}; font-size: 22px; font-weight: 700; letter-spacing: -0.3px;"
            )
        if hasattr(self, 'lbl_workspace_desc'):
            self.lbl_workspace_desc.setStyleSheet(
                f"color: {t['fg']}; font-size: 12px; line-height: 1.4em;"
            )
        if hasattr(self, 'lbl_workspace_meta'):
            self.lbl_workspace_meta.setStyleSheet(
                f"color: {t['muted']}; font-size: 11px;"
            )
        for attr in ('lbl_workspace_trust', 'lbl_workspace_guard'):
            if hasattr(self, attr):
                getattr(self, attr).setStyleSheet(
                    f"background: {t['bg_alt']}; color: {t['fg']}; border: 1px solid {t['border']}; "
                    "border-radius: 999px; padding: 4px 10px; font-size: 10px; font-weight: 600;"
                )

        # ── Toolbar buttons (common style helper) ────────────────────────
        _TB = (
            f"QPushButton {{ font-size: 11px; padding: 2px 12px; background: {t['header_bg']};"
            f"color: {t['sidebar_btn_active_fg']}; border: 1px solid {t['border']}; border-radius: 12px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}"
        )
        _TB_SMALL = (
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {t['header_bg']};"
            f"color: {t['sidebar_btn_active_fg']}; border: 1px solid {t['border']}; border-radius: 12px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}"
        )
        _TB_CHECK = _TB_SMALL + (
            f"QPushButton:checked {{ background: {t['selection']}; color: {t['fg_bright']}; border-color: {t['accent']}; }}"
        )

        # Replay, Export, Export HTML, Open Dest
        for btn in [self.btn_replay, self.btn_export, self.btn_export_html, self.btn_open_dest]:
            btn.setStyleSheet(_TB)

        # PC Cats button
        self.btn_pc_cats.setStyleSheet(_TB)

        # Photo button (green accent)
        self.btn_photo.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 12px; background: {t['header_bg']};"
            f"color: {t['green']}; border: 1px solid {t['border']}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}")

        # Grid, Preview, Graph toggles (checkable, standard accent)
        self.btn_grid_toggle.setStyleSheet(_TB_CHECK)
        self.btn_preview_toggle.setStyleSheet(_TB_CHECK)
        self.btn_graph_toggle.setStyleSheet(_TB_CHECK)

        # Map toggle (green checkable)
        self.btn_map_toggle.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {t['header_bg']};"
            f"color: {t['green']}; border: 1px solid {t['border']}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}"
            f"QPushButton:checked {{ background: {t['selection']}; color: {t['green']}; border-color: {t['green']}; }}")

        # Before/After
        self.btn_before_after.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {t['header_bg']};"
            f"color: {t['accent_hover']}; border: 1px solid {t['border']}; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {t['btn_hover']}; }}")

        # Events
        self.btn_events.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 10px; background: {t['header_bg']};"
            f"color: {t['accent_hover']}; border: 1px solid {t['border']}; border-radius: 10px; }}"
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
                f"border-radius: 10px; padding: 2px 8px; font-size: 11px; font-weight: bold; }}"
                f"QComboBox:hover {{ border-color: {t['accent_hover']}; }}"
                f"QComboBox::drop-down {{ border: none; }}"
                f"QComboBox QAbstractItemView {{ background: {t['input_bg']}; color: {t['fg']};"
                f"selection-background-color: {t['selection']}; border: 1px solid {t['border']}; }}")

        # ── Dashboard ────────────────────────────────────────────────────
        if hasattr(self, 'dashboard_panel'):
            self.dashboard_panel.setStyleSheet(
                f"background: {t['header_bg']}; border: 1px solid {t['border']}; border-radius: 14px; padding: 6px;")
        if hasattr(self, 'lbl_dash_kicker'):
            self.lbl_dash_kicker.setStyleSheet(
                f"color: {t['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1.3px;")
        if hasattr(self, 'lbl_dash_summary'):
            self.lbl_dash_summary.setStyleSheet(
                f"color: {t['fg_bright']}; font-size: 13px; font-weight: 700;")
        if hasattr(self, '_themed_btn_hide_dash'):
            self._themed_btn_hide_dash.setStyleSheet(
                f"QPushButton{{font-size:10px;color:{t['muted']};background:{t['sidebar_brand']};"
                f"border:1px solid {t['border']};border-radius:10px;padding: 0 10px;}}"
                f"QPushButton:hover{{color:{t['fg']}}}")

        # ── Empty / Toast / Stats ────────────────────────────────────────
        if hasattr(self, 'lbl_empty'):
            self.lbl_empty.setStyleSheet(
                f"color: {t['fg_bright']}; font-size: 18px; font-weight: 700;")
        if hasattr(self, 'empty_state'):
            self.empty_state.setStyleSheet(
                f"QFrame#empty_state {{ background: {t['header_bg']}; border: 1px solid {t['border']}; border-radius: 18px; }}"
            )
        if hasattr(self, 'lbl_empty_kicker'):
            self.lbl_empty_kicker.setStyleSheet(
                f"color: {t['sidebar_btn_active_fg']}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;"
            )
        if hasattr(self, 'lbl_empty_detail'):
            self.lbl_empty_detail.setStyleSheet(
                f"color: {t['muted']}; font-size: 12px; line-height: 1.4em;"
            )
        if hasattr(self, 'lbl_empty_actions'):
            self.lbl_empty_actions.setStyleSheet(
                f"color: {t['sidebar_btn_active_fg']}; font-size: 11px; font-weight: 600;"
            )
        if hasattr(self, 'lbl_toast'):
            self.lbl_toast.setStyleSheet(
                f"QLabel {{ background: {t['header_bg']};"
                f"color: {t['fg_bright']}; font-size: 13px; font-weight: bold;"
                f"padding: 12px 20px; border-radius: 12px;"
                f"border: 1px solid {t['border']}; }}")
        if hasattr(self, 'lbl_stats'):
            self.lbl_stats.setStyleSheet(
                f"color: {t['muted']}; font-size: 12px; padding: 4px 0;")

        # ── Progress Panel ───────────────────────────────────────────────
        if hasattr(self, 'prog_panel'):
            self.prog_panel.setStyleSheet(
                f"QWidget#prog_panel {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; "
                f"border-radius: 14px; margin: 2px 0; }}")
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
                f"font-size: 11px; border: 1px solid {t['border']}; border-radius: 10px; padding: 6px; }}")

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
        for attr in ('_tag_panel', '_media_panel', '_vlib_panel'):
            panel = getattr(self, attr, None)
            if panel and hasattr(panel, 'apply_theme'):
                panel.apply_theme(t)
        if hasattr(self, '_refresh_workspace_copy'):
            self._refresh_workspace_copy()
