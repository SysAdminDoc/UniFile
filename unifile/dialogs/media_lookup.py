"""UniFile — Media Lookup Panel (inline stacked widget page).

Provides movie/TV metadata lookup via TMDb, OMDb, and TVMaze APIs.
Parses media filenames with guessit and lets users search, browse results,
and apply metadata to tag library entries.
"""
import logging
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QSplitter, QTextEdit, QFrame, QFileDialog, QMenu,
    QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QPixmap, QImage

from unifile.config import get_active_theme
from unifile.media.providers import (
    MediaType, MovieResult, EpisodeResult,
    parse_media_filename, search_media,
    tmdb_movie_details, omdb_details,
    tvmaze_show_episodes, tvmaze_episode_lookup, tvmaze_show_details,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker thread for API calls
# ---------------------------------------------------------------------------

class _SearchWorker(QThread):
    results_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, query: str, year: str, media_type: MediaType):
        super().__init__()
        self.query = query
        self.year = year
        self.media_type = media_type

    def run(self):
        try:
            results = search_media(
                self.query,
                year=self.year or None,
                media_type=self.media_type,
                limit=20,
            )
            self.results_ready.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class _DetailWorker(QThread):
    detail_ready = pyqtSignal(object)
    poster_ready = pyqtSignal(bytes)
    episodes_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, result, fetch_poster: bool = True, fetch_episodes: bool = False):
        super().__init__()
        self.result = result
        self.fetch_poster = fetch_poster
        self.fetch_episodes = fetch_episodes

    def run(self):
        try:
            detail = self.result
            # Fetch full details if we have IDs
            if isinstance(self.result, MovieResult):
                if self.result.id_tmdb:
                    full = tmdb_movie_details(self.result.id_tmdb)
                    if full:
                        detail = full
                elif self.result.id_imdb:
                    full = omdb_details(self.result.id_imdb)
                    if full:
                        detail = full
            self.detail_ready.emit(detail)

            # Fetch poster
            if self.fetch_poster and detail.poster_url:
                import requests
                resp = requests.get(detail.poster_url, timeout=10)
                if resp.status_code == 200:
                    self.poster_ready.emit(resp.content)

            # Fetch episodes for TV shows
            if self.fetch_episodes and isinstance(detail, EpisodeResult) and detail.id_tvmaze:
                episodes = tvmaze_show_episodes(int(detail.id_tvmaze))
                show = tvmaze_show_details(int(detail.id_tvmaze))
                series_name = show.get("name", "") if show else detail.series
                for ep in episodes:
                    ep.series = series_name
                self.episodes_ready.emit(episodes)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Media Lookup Panel
# ---------------------------------------------------------------------------

class MediaLookupPanel(QWidget):
    """Media metadata lookup panel for the content stack."""

    metadata_applied = pyqtSignal(dict)  # emits metadata dict when applied to entry

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: list = []
        self._episodes: list = []
        self._current_detail = None
        self._worker = None
        self._detail_worker = None
        self._build_ui()

    def _build_ui(self):
        _t = get_active_theme()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {_t['bg_alt']}; border-bottom: 1px solid {_t['btn_bg']};")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(16, 0, 16, 0)

        lbl_title = QLabel("Media Lookup")
        lbl_title.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 14px; font-weight: 700; background: transparent;")
        h_lay.addWidget(lbl_title)
        h_lay.addStretch()

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(
            f"color: {_t['muted']}; font-size: 11px; background: transparent;")
        h_lay.addWidget(self.lbl_status)
        lay.addWidget(header)

        # ── Search Bar ────────────────────────────────────────────────────
        search_bar = QWidget()
        search_bar.setFixedHeight(44)
        search_bar.setStyleSheet(f"background: {_t['bg']}; border-bottom: 1px solid {_t['btn_bg']};")
        sb_lay = QHBoxLayout(search_bar)
        sb_lay.setContentsMargins(16, 6, 16, 6)
        sb_lay.setSpacing(8)

        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Movie", "TV Show"])
        self.cmb_type.setFixedWidth(100)
        self.cmb_type.setFixedHeight(28)
        sb_lay.addWidget(self.cmb_type)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search movies or TV shows...")
        self.txt_search.setFixedHeight(28)
        self.txt_search.returnPressed.connect(self._on_search)
        sb_lay.addWidget(self.txt_search, 1)

        self.txt_year = QLineEdit()
        self.txt_year.setPlaceholderText("Year")
        self.txt_year.setFixedWidth(60)
        self.txt_year.setFixedHeight(28)
        sb_lay.addWidget(self.txt_year)

        btn_search = QPushButton("Search")
        btn_search.setFixedHeight(28)
        btn_search.setStyleSheet(
            f"QPushButton {{ background: {_t['accent']}; color: #fff; border: none; "
            f"border-radius: 4px; padding: 4px 16px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_t['accent_hover']}; }}")
        btn_search.clicked.connect(self._on_search)
        sb_lay.addWidget(btn_search)

        btn_parse = QPushButton("Parse Filename")
        btn_parse.setFixedHeight(28)
        btn_parse.setToolTip("Parse a media filename to auto-fill search")
        btn_parse.setStyleSheet(
            f"QPushButton {{ background: {_t['green']}; color: #fff; border: none; "
            f"border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_t['green_hover']}; }}")
        btn_parse.clicked.connect(self._on_parse_filename)
        sb_lay.addWidget(btn_parse)

        lay.addWidget(search_bar)

        # ── Main Content: Results (left) | Detail (right) ─────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Search Results ──────────────────────────────────────────
        results_panel = QWidget()
        rp_lay = QVBoxLayout(results_panel)
        rp_lay.setContentsMargins(12, 8, 6, 8)
        rp_lay.setSpacing(6)

        self.lbl_results_title = QLabel("Results")
        self.lbl_results_title.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 12px; font-weight: 600;")
        rp_lay.addWidget(self.lbl_results_title)

        self.tbl_results = QTableWidget()
        self.tbl_results.setColumnCount(4)
        self.tbl_results.setHorizontalHeaderLabels(["Title", "Year", "Type", "ID"])
        self.tbl_results.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_results.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_results.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_results.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_results.setAlternatingRowColors(True)
        self.tbl_results.itemSelectionChanged.connect(self._on_result_selected)
        rp_lay.addWidget(self.tbl_results, 1)

        # Episode list (shown for TV shows)
        self.lbl_episodes = QLabel("Episodes")
        self.lbl_episodes.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 12px; font-weight: 600;")
        self.lbl_episodes.setVisible(False)
        rp_lay.addWidget(self.lbl_episodes)

        self.tbl_episodes = QTableWidget()
        self.tbl_episodes.setColumnCount(4)
        self.tbl_episodes.setHorizontalHeaderLabels(["#", "Title", "Air Date", "Season"])
        self.tbl_episodes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_episodes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl_episodes.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_episodes.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_episodes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_episodes.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_episodes.setAlternatingRowColors(True)
        self.tbl_episodes.setVisible(False)
        self.tbl_episodes.itemSelectionChanged.connect(self._on_episode_selected)
        rp_lay.addWidget(self.tbl_episodes, 1)

        splitter.addWidget(results_panel)

        # ── Right: Detail Panel ───────────────────────────────────────────
        detail_panel = QWidget()
        dp_lay = QVBoxLayout(detail_panel)
        dp_lay.setContentsMargins(6, 8, 12, 8)
        dp_lay.setSpacing(8)

        # Poster
        self.lbl_poster = QLabel()
        self.lbl_poster.setFixedSize(200, 300)
        self.lbl_poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_poster.setStyleSheet(
            f"background: {_t['bg_alt']}; border: 1px solid {_t['border']}; "
            f"border-radius: 6px;")
        self.lbl_poster.setText("No Poster")
        dp_lay.addWidget(self.lbl_poster, 0, Qt.AlignmentFlag.AlignHCenter)

        # Title
        self.lbl_detail_title = QLabel("")
        self.lbl_detail_title.setWordWrap(True)
        self.lbl_detail_title.setStyleSheet(
            f"color: {_t['fg_bright']}; font-size: 16px; font-weight: 700;")
        dp_lay.addWidget(self.lbl_detail_title)

        # Meta info line
        self.lbl_detail_meta = QLabel("")
        self.lbl_detail_meta.setWordWrap(True)
        self.lbl_detail_meta.setStyleSheet(
            f"color: {_t['accent']}; font-size: 12px; font-weight: 500;")
        dp_lay.addWidget(self.lbl_detail_meta)

        # Genres
        self.lbl_genres = QLabel("")
        self.lbl_genres.setWordWrap(True)
        self.lbl_genres.setStyleSheet(f"color: {_t['muted']}; font-size: 11px;")
        dp_lay.addWidget(self.lbl_genres)

        # Synopsis
        self.txt_synopsis = QTextEdit()
        self.txt_synopsis.setReadOnly(True)
        self.txt_synopsis.setMaximumHeight(160)
        self.txt_synopsis.setStyleSheet(
            f"QTextEdit {{ background: {_t['bg_alt']}; color: {_t['fg']}; "
            f"border: 1px solid {_t['border']}; border-radius: 4px; padding: 8px; "
            f"font-size: 12px; }}")
        dp_lay.addWidget(self.txt_synopsis)

        # IDs
        self.lbl_ids = QLabel("")
        self.lbl_ids.setWordWrap(True)
        self.lbl_ids.setStyleSheet(f"color: {_t['muted']}; font-size: 10px;")
        dp_lay.addWidget(self.lbl_ids)

        dp_lay.addStretch()

        # Action buttons
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        btn_apply_tags = QPushButton("Apply to Tag Library")
        btn_apply_tags.setFixedHeight(32)
        btn_apply_tags.setStyleSheet(
            f"QPushButton {{ background: {_t['accent']}; color: #fff; border: none; "
            f"border-radius: 4px; padding: 4px 16px; font-size: 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_t['accent_hover']}; }}")
        btn_apply_tags.clicked.connect(self._on_apply_to_tags)
        action_row.addWidget(btn_apply_tags)

        btn_copy = QPushButton("Copy Metadata")
        btn_copy.setFixedHeight(32)
        btn_copy.setStyleSheet(
            f"QPushButton {{ background: {_t['btn_bg']}; color: {_t['fg']}; "
            f"border: 1px solid {_t['border']}; border-radius: 4px; padding: 4px 16px; "
            f"font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_t['btn_hover']}; }}")
        btn_copy.clicked.connect(self._on_copy_metadata)
        action_row.addWidget(btn_copy)

        action_row.addStretch()
        dp_lay.addLayout(action_row)

        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        lay.addWidget(splitter, 1)

    # ── Search ─────────────────────────────────────────────────────────────

    def _on_search(self):
        query = self.txt_search.text().strip()
        if not query:
            return

        media_type = MediaType.MOVIE if self.cmb_type.currentIndex() == 0 else MediaType.EPISODE
        year = self.txt_year.text().strip() or None

        self.lbl_status.setText("Searching...")
        self.tbl_results.setRowCount(0)
        self.tbl_episodes.setRowCount(0)
        self.tbl_episodes.setVisible(False)
        self.lbl_episodes.setVisible(False)

        self._worker = _SearchWorker(query, year or "", media_type)
        self._worker.results_ready.connect(self._on_search_results)
        self._worker.error.connect(self._on_search_error)
        self._worker.start()

    def _on_parse_filename(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Media File",
            filter="Media Files (*.mp4 *.mkv *.avi *.m4v *.wmv *.ts *.mov *.srt *.sub);;All Files (*)")
        if not files:
            return

        filename = Path(files[0]).name
        parsed = parse_media_filename(filename)

        self.txt_search.setText(parsed.get("title", ""))
        self.txt_year.setText(parsed.get("year", "") or "")

        if parsed.get("type") == MediaType.EPISODE:
            self.cmb_type.setCurrentIndex(1)
        else:
            self.cmb_type.setCurrentIndex(0)

        # Auto-search
        self._on_search()

    def search_for_filename(self, filename: str):
        """Programmatic search — called from context menus in other panels."""
        parsed = parse_media_filename(filename)
        self.txt_search.setText(parsed.get("title", ""))
        self.txt_year.setText(parsed.get("year", "") or "")
        if parsed.get("type") == MediaType.EPISODE:
            self.cmb_type.setCurrentIndex(1)
        else:
            self.cmb_type.setCurrentIndex(0)
        self._on_search()

    @pyqtSlot(list)
    def _on_search_results(self, results):
        self._results = results
        self.tbl_results.setRowCount(len(results))

        for row, result in enumerate(results):
            if isinstance(result, MovieResult):
                self.tbl_results.setItem(row, 0, QTableWidgetItem(result.title))
                self.tbl_results.setItem(row, 1, QTableWidgetItem(result.year))
                self.tbl_results.setItem(row, 2, QTableWidgetItem("Movie"))
                id_str = result.id_tmdb or result.id_imdb or ""
                self.tbl_results.setItem(row, 3, QTableWidgetItem(id_str))
            elif isinstance(result, EpisodeResult):
                self.tbl_results.setItem(row, 0, QTableWidgetItem(result.series))
                self.tbl_results.setItem(row, 1, QTableWidgetItem(""))
                self.tbl_results.setItem(row, 2, QTableWidgetItem("TV Show"))
                self.tbl_results.setItem(row, 3, QTableWidgetItem(result.id_tvmaze))

        count = len(results)
        self.lbl_status.setText(f"{count} result{'s' if count != 1 else ''}")
        self.lbl_results_title.setText(f"Results ({count})")

    @pyqtSlot(str)
    def _on_search_error(self, error_msg):
        self.lbl_status.setText(f"Error: {error_msg}")

    # ── Result Selection ───────────────────────────────────────────────────

    def _on_result_selected(self):
        rows = self.tbl_results.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx >= len(self._results):
            return

        result = self._results[idx]
        self.lbl_status.setText("Loading details...")
        self._clear_detail()

        is_episode = isinstance(result, EpisodeResult)
        self._detail_worker = _DetailWorker(
            result,
            fetch_poster=True,
            fetch_episodes=is_episode,
        )
        self._detail_worker.detail_ready.connect(self._on_detail_ready)
        self._detail_worker.poster_ready.connect(self._on_poster_ready)
        self._detail_worker.episodes_ready.connect(self._on_episodes_ready)
        self._detail_worker.error.connect(self._on_search_error)
        self._detail_worker.start()

    @pyqtSlot(object)
    def _on_detail_ready(self, detail):
        self._current_detail = detail
        _t = get_active_theme()

        if isinstance(detail, MovieResult):
            self.lbl_detail_title.setText(detail.title)
            self.lbl_detail_meta.setText(f"Movie  |  {detail.year}" if detail.year else "Movie")
            self.lbl_genres.setText(", ".join(detail.genres) if detail.genres else "")
            self.txt_synopsis.setText(detail.synopsis or "No synopsis available.")
            ids = []
            if detail.id_tmdb:
                ids.append(f"TMDb: {detail.id_tmdb}")
            if detail.id_imdb:
                ids.append(f"IMDb: {detail.id_imdb}")
            self.lbl_ids.setText("  |  ".join(ids))

        elif isinstance(detail, EpisodeResult):
            self.lbl_detail_title.setText(detail.series or detail.title)
            ep_info = ""
            if detail.season and detail.episode:
                ep_info = f"S{detail.season:02d}E{detail.episode:02d}"
            if detail.title and detail.series:
                ep_info += f"  {detail.title}" if ep_info else detail.title
            self.lbl_detail_meta.setText(f"TV Show  |  {ep_info}" if ep_info else "TV Show")
            self.lbl_genres.setText(", ".join(detail.genres) if detail.genres else "")
            self.txt_synopsis.setText(detail.synopsis or "No synopsis available.")
            ids = []
            if detail.id_tvmaze:
                ids.append(f"TVMaze: {detail.id_tvmaze}")
            if detail.id_imdb:
                ids.append(f"IMDb: {detail.id_imdb}")
            self.lbl_ids.setText("  |  ".join(ids))

        self.lbl_status.setText("Ready")

    @pyqtSlot(bytes)
    def _on_poster_ready(self, data):
        img = QImage()
        img.loadFromData(data)
        if not img.isNull():
            pixmap = QPixmap.fromImage(img)
            self.lbl_poster.setPixmap(
                pixmap.scaled(200, 300, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation))

    @pyqtSlot(list)
    def _on_episodes_ready(self, episodes):
        self._episodes = episodes
        self.tbl_episodes.setRowCount(len(episodes))
        self.tbl_episodes.setVisible(True)
        self.lbl_episodes.setVisible(True)
        self.lbl_episodes.setText(f"Episodes ({len(episodes)})")

        for row, ep in enumerate(episodes):
            self.tbl_episodes.setItem(row, 0, QTableWidgetItem(
                f"E{ep.episode:02d}" if ep.episode else ""))
            self.tbl_episodes.setItem(row, 1, QTableWidgetItem(ep.title))
            self.tbl_episodes.setItem(row, 2, QTableWidgetItem(ep.date))
            self.tbl_episodes.setItem(row, 3, QTableWidgetItem(
                f"S{ep.season:02d}" if ep.season else ""))

    def _on_episode_selected(self):
        rows = self.tbl_episodes.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx >= len(self._episodes):
            return
        ep = self._episodes[idx]
        self._current_detail = ep
        self.lbl_detail_title.setText(f"{ep.series}")
        ep_str = f"S{ep.season:02d}E{ep.episode:02d}" if ep.season and ep.episode else ""
        self.lbl_detail_meta.setText(f"TV Show  |  {ep_str}  {ep.title}")
        self.txt_synopsis.setText(ep.synopsis or "No synopsis available.")
        self.lbl_ids.setText(f"TVMaze: {ep.id_tvmaze}" if ep.id_tvmaze else "")

    def _clear_detail(self):
        self.lbl_detail_title.setText("")
        self.lbl_detail_meta.setText("")
        self.lbl_genres.setText("")
        self.txt_synopsis.clear()
        self.lbl_ids.setText("")
        self.lbl_poster.clear()
        self.lbl_poster.setText("No Poster")
        self._current_detail = None

    # ── Actions ────────────────────────────────────────────────────────────

    def _build_metadata_dict(self) -> dict:
        """Build a metadata dict from the current detail for tag library integration."""
        detail = self._current_detail
        if not detail:
            return {}

        meta = {}
        if isinstance(detail, MovieResult):
            meta["title"] = detail.title
            meta["year"] = detail.year
            meta["synopsis"] = detail.synopsis
            meta["genres"] = detail.genres
            meta["id_imdb"] = detail.id_imdb
            meta["id_tmdb"] = detail.id_tmdb
            meta["media_type"] = "movie"
        elif isinstance(detail, EpisodeResult):
            meta["title"] = detail.title
            meta["series"] = detail.series
            meta["season"] = detail.season
            meta["episode"] = detail.episode
            meta["date"] = detail.date
            meta["synopsis"] = detail.synopsis
            meta["genres"] = detail.genres
            meta["id_tvmaze"] = detail.id_tvmaze
            meta["id_imdb"] = detail.id_imdb
            meta["media_type"] = "episode"
        return meta

    def _on_apply_to_tags(self):
        meta = self._build_metadata_dict()
        if meta:
            self.metadata_applied.emit(meta)
            self.lbl_status.setText("Metadata sent to Tag Library")

    def _on_copy_metadata(self):
        meta = self._build_metadata_dict()
        if not meta:
            return
        lines = []
        for k, v in meta.items():
            if v:
                if isinstance(v, list):
                    v = ", ".join(v)
                lines.append(f"{k}: {v}")
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self.lbl_status.setText("Metadata copied to clipboard")
