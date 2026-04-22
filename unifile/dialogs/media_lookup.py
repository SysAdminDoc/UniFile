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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────
        self.header = QFrame()
        self.header.setProperty("class", "card")
        h_lay = QHBoxLayout(self.header)
        h_lay.setContentsMargins(18, 16, 18, 16)
        h_lay.setSpacing(16)

        header_copy = QVBoxLayout()
        header_copy.setSpacing(4)
        self.lbl_header_kicker = QLabel("METADATA LOOKUP")
        header_copy.addWidget(self.lbl_header_kicker)
        self.lbl_header_title = QLabel("Media Lookup")
        header_copy.addWidget(self.lbl_header_title)
        self.lbl_header_subtitle = QLabel(
            "Search TMDb, OMDb, and TVMaze, then review a richer detail card before sending metadata into your library."
        )
        self.lbl_header_subtitle.setWordWrap(True)
        header_copy.addWidget(self.lbl_header_subtitle)
        h_lay.addLayout(header_copy)
        h_lay.addStretch()

        self.lbl_status = QLabel("")
        self.lbl_status.setMinimumWidth(220)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h_lay.addWidget(self.lbl_status)
        lay.addWidget(self.header)

        # ── Search Bar ────────────────────────────────────────────────────
        self.search_bar = QFrame()
        self.search_bar.setProperty("class", "card")
        sb_lay = QHBoxLayout(self.search_bar)
        sb_lay.setContentsMargins(16, 12, 16, 12)
        sb_lay.setSpacing(8)

        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Movie", "TV Show"])
        self.cmb_type.setFixedWidth(100)
        self.cmb_type.setFixedHeight(28)
        sb_lay.addWidget(self.cmb_type)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search movies or TV shows…")
        self.txt_search.setFixedHeight(28)
        self.txt_search.returnPressed.connect(self._on_search)
        sb_lay.addWidget(self.txt_search, 1)

        self.txt_year = QLineEdit()
        self.txt_year.setPlaceholderText("Year")
        self.txt_year.setFixedWidth(60)
        self.txt_year.setFixedHeight(28)
        sb_lay.addWidget(self.txt_year)

        self.btn_search = QPushButton("Search")
        self.btn_search.setProperty("class", "primary")
        self.btn_search.clicked.connect(self._on_search)
        sb_lay.addWidget(self.btn_search)

        self.btn_parse = QPushButton("Parse Filename")
        self.btn_parse.setToolTip("Parse a media filename to auto-fill the search query")
        self.btn_parse.setProperty("class", "success")
        self.btn_parse.clicked.connect(self._on_parse_filename)
        sb_lay.addWidget(self.btn_parse)

        lay.addWidget(self.search_bar)

        # ── Main Content: Results (left) | Detail (right) ─────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Search Results ──────────────────────────────────────────
        self.results_panel = QFrame()
        self.results_panel.setProperty("class", "card")
        rp_lay = QVBoxLayout(self.results_panel)
        rp_lay.setContentsMargins(16, 16, 16, 16)
        rp_lay.setSpacing(8)

        self.lbl_results_title = QLabel("Results")
        rp_lay.addWidget(self.lbl_results_title)
        self.lbl_results_hint = QLabel("Search by title or parse a filename to load candidate matches from the connected providers.")
        self.lbl_results_hint.setWordWrap(True)
        rp_lay.addWidget(self.lbl_results_hint)

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

        splitter.addWidget(self.results_panel)

        # ── Right: Detail Panel ───────────────────────────────────────────
        self.detail_panel = QFrame()
        self.detail_panel.setProperty("class", "card")
        dp_lay = QVBoxLayout(self.detail_panel)
        dp_lay.setContentsMargins(16, 16, 16, 16)
        dp_lay.setSpacing(10)

        self.lbl_detail_section = QLabel("Selected metadata")
        dp_lay.addWidget(self.lbl_detail_section)
        self.lbl_detail_hint = QLabel("Pick a result to load synopsis, genres, artwork, and IDs before applying anything.")
        self.lbl_detail_hint.setWordWrap(True)
        dp_lay.addWidget(self.lbl_detail_hint)

        # Poster
        self.lbl_poster = QLabel()
        self.lbl_poster.setFixedSize(200, 300)
        self.lbl_poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_poster.setText("Select a result")
        dp_lay.addWidget(self.lbl_poster, 0, Qt.AlignmentFlag.AlignHCenter)

        # Title
        self.lbl_detail_title = QLabel("No title selected")
        self.lbl_detail_title.setWordWrap(True)
        dp_lay.addWidget(self.lbl_detail_title)

        # Meta info line
        self.lbl_detail_meta = QLabel("")
        self.lbl_detail_meta.setWordWrap(True)
        dp_lay.addWidget(self.lbl_detail_meta)

        # Genres
        self.lbl_genres = QLabel("")
        self.lbl_genres.setWordWrap(True)
        dp_lay.addWidget(self.lbl_genres)

        # Synopsis
        self.txt_synopsis = QTextEdit()
        self.txt_synopsis.setReadOnly(True)
        self.txt_synopsis.setMaximumHeight(160)
        self.txt_synopsis.setText("Pick a result to load synopsis, genres, artwork, and external IDs.")
        dp_lay.addWidget(self.txt_synopsis)

        # IDs
        self.lbl_ids = QLabel("")
        self.lbl_ids.setWordWrap(True)
        dp_lay.addWidget(self.lbl_ids)

        dp_lay.addStretch()

        # Action buttons
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.btn_apply_tags = QPushButton("Apply to Tag Library")
        self.btn_apply_tags.setProperty("class", "primary")
        self.btn_apply_tags.setEnabled(False)
        self.btn_apply_tags.clicked.connect(self._on_apply_to_tags)
        action_row.addWidget(self.btn_apply_tags)

        self.btn_copy = QPushButton("Copy Metadata")
        self.btn_copy.setProperty("class", "toolbar")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._on_copy_metadata)
        action_row.addWidget(self.btn_copy)

        action_row.addStretch()
        dp_lay.addLayout(action_row)

        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        lay.addWidget(splitter, 1)
        self.apply_theme()

    # ── Search ─────────────────────────────────────────────────────────────

    def _on_search(self):
        query = self.txt_search.text().strip()
        if not query:
            self.lbl_status.setText("Enter a title, then search")
            return

        media_type = MediaType.MOVIE if self.cmb_type.currentIndex() == 0 else MediaType.EPISODE
        year = self.txt_year.text().strip() or None

        self.lbl_status.setText("Searching connected providers…")
        self.lbl_results_hint.setText("Reviewing TMDb, OMDb, and TVMaze for the best matches.")
        self.tbl_results.setRowCount(0)
        self.tbl_episodes.setRowCount(0)
        self.tbl_episodes.setVisible(False)
        self.lbl_episodes.setVisible(False)
        self._clear_detail()

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
        if not results:
            self._clear_detail()

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
        self.lbl_status.setText(
            f"{count} result{'s' if count != 1 else ''} found"
            if count else
            "No matches found"
        )
        self.lbl_results_title.setText(f"Results ({count})")
        self.lbl_results_hint.setText(
            "Select a result to load artwork, synopsis, and IDs."
            if count else
            "No provider returned a confident match for that search."
        )

    @pyqtSlot(str)
    def _on_search_error(self, error_msg):
        self.lbl_status.setText(f"Search failed: {error_msg}")
        self.lbl_results_hint.setText("Check your provider settings or adjust the title and year, then try again.")
        self._clear_detail()

    # ── Result Selection ───────────────────────────────────────────────────

    def _on_result_selected(self):
        rows = self.tbl_results.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx >= len(self._results):
            return

        result = self._results[idx]
        self.lbl_status.setText("Loading details…")
        self.lbl_detail_hint.setText("Pulling artwork, synopsis, genres, and provider IDs for the selected result.")
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

        self.lbl_status.setText("Metadata ready")
        self.lbl_detail_hint.setText("Review the metadata, then send it to Tag Library or copy it out.")
        self.btn_apply_tags.setEnabled(True)
        self.btn_copy.setEnabled(True)

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
        self.lbl_results_hint.setText("Choose a specific episode if you need episode-level metadata.")

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
        self.lbl_detail_hint.setText("Episode-level metadata is ready to review or send to Tag Library.")
        self.btn_apply_tags.setEnabled(True)
        self.btn_copy.setEnabled(True)

    def _clear_detail(self):
        self.lbl_detail_title.setText("No title selected")
        self.lbl_detail_meta.setText("")
        self.lbl_genres.setText("")
        self.txt_synopsis.setText("Pick a result to load synopsis, genres, artwork, and external IDs.")
        self.lbl_ids.setText("")
        self.lbl_poster.clear()
        self.lbl_poster.setText("Select a result")
        self._current_detail = None
        self.btn_apply_tags.setEnabled(False)
        self.btn_copy.setEnabled(False)

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
            self.lbl_detail_hint.setText("Metadata sent. You can keep reviewing results or copy the same payload.")

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
        self.lbl_detail_hint.setText("Copied the active metadata payload for reuse outside UniFile.")

    def apply_theme(self, theme: dict | None = None):
        t = theme or get_active_theme()
        self.header.setStyleSheet(
            f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; border-radius: 18px; }}"
        )
        self.lbl_header_kicker.setStyleSheet(
            f"color: {t['accent']}; font-size: 10px; font-weight: 700; letter-spacing: 1.6px;"
        )
        self.lbl_header_title.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 22px; font-weight: 700;"
        )
        self.lbl_header_subtitle.setStyleSheet(
            f"color: {t['muted']}; font-size: 12px; line-height: 1.4em;"
        )
        self.lbl_status.setStyleSheet(
            f"background: {t['header_bg']}; color: {t['muted']}; border: 1px solid {t['border']}; "
            "border-radius: 999px; padding: 6px 12px; font-size: 11px; font-weight: 600;"
        )
        for panel in (self.search_bar, self.results_panel, self.detail_panel):
            panel.setStyleSheet(
                f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; border-radius: 18px; }}"
            )
        self.lbl_results_title.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 14px; font-weight: 700;"
        )
        self.lbl_results_hint.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        self.lbl_detail_section.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 14px; font-weight: 700;"
        )
        self.lbl_detail_hint.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        self.lbl_episodes.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 12px; font-weight: 700;"
        )
        self.lbl_poster.setStyleSheet(
            f"background: {t['header_bg']}; border: 1px solid {t['border']}; border-radius: 14px; color: {t['muted']};"
        )
        self.lbl_detail_title.setStyleSheet(
            f"color: {t['fg_bright']}; font-size: 18px; font-weight: 700;"
        )
        self.lbl_detail_meta.setStyleSheet(
            f"color: {t['accent']}; font-size: 12px; font-weight: 600;"
        )
        self.lbl_genres.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        self.txt_synopsis.setStyleSheet(
            f"QTextEdit {{ background: {t['header_bg']}; color: {t['fg']}; border: 1px solid {t['border']}; "
            f"border-radius: 14px; padding: 10px 12px; font-size: 12px; }}"
        )
        self.lbl_ids.setStyleSheet(f"color: {t['muted']}; font-size: 10px;")
