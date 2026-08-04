"""UniFile — Media Lookup Panel (inline stacked widget page).

Provides movie/TV metadata lookup via TMDb, OMDb, and TVMaze APIs.
Parses media filenames with guessit and lets users search, browse results,
and apply metadata to tag library entries.
"""
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_theme
from unifile.media.providers import (
    AudioResult,
    BookResult,
    EpisodeResult,
    MediaType,
    MovieResult,
    clear_media_provider_errors,
    googlebooks_book_details,
    load_media_api_keys,
    media_provider_statuses,
    musicbrainz_recording_details,
    omdb_details,
    openlibrary_book_details,
    parse_media_filename,
    save_media_api_keys,
    search_media,
    tmdb_movie_details,
    tmdb_show_details,
    tmdb_show_episodes,
    tvdb_show_details,
    tvdb_show_episodes,
    tvmaze_show_details,
    tvmaze_show_episodes,
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
            elif isinstance(self.result, BookResult):
                if self.result.id_openlibrary:
                    full = openlibrary_book_details(self.result.id_openlibrary)
                    if full:
                        detail = full
                elif self.result.id_googlebooks:
                    full = googlebooks_book_details(self.result.id_googlebooks)
                    if full:
                        detail = full
                if isinstance(detail, BookResult) and isinstance(self.result, BookResult):
                    for attribute in (
                        "authors", "year", "synopsis", "isbn", "language", "genres",
                        "series", "publisher", "cover_url", "source_url",
                        "id_openlibrary", "id_googlebooks",
                    ):
                        if not getattr(detail, attribute) and getattr(self.result, attribute):
                            setattr(detail, attribute, getattr(self.result, attribute))
            elif isinstance(self.result, AudioResult) and self.result.id_musicbrainz:
                full = musicbrainz_recording_details(self.result.id_musicbrainz)
                if full:
                    detail = full
                if isinstance(detail, AudioResult) and isinstance(self.result, AudioResult):
                    for attribute in ("artist", "album", "year", "genre", "release_id", "cover_url", "source_url"):
                        if not getattr(detail, attribute) and getattr(self.result, attribute):
                            setattr(detail, attribute, getattr(self.result, attribute))
            elif isinstance(self.result, EpisodeResult):
                if self.result.id_tvdb:
                    full = tvdb_show_details(self.result.id_tvdb)
                    if full:
                        detail = full
                elif self.result.id_tmdb:
                    full = tmdb_show_details(self.result.id_tmdb)
                    if full:
                        detail = full
            self.detail_ready.emit(detail)

            # Fetch poster
            poster_url = getattr(detail, "poster_url", "") or getattr(detail, "cover_url", "")
            if self.fetch_poster and poster_url:
                import requests
                resp = requests.get(poster_url, timeout=10)
                if resp.status_code == 200:
                    self.poster_ready.emit(resp.content)

            # Fetch episodes for TV shows
            if self.fetch_episodes and isinstance(detail, EpisodeResult):
                if detail.id_tvdb:
                    episodes = tvdb_show_episodes(detail.id_tvdb)
                elif detail.id_tmdb:
                    episodes = tmdb_show_episodes(detail.id_tmdb)
                elif detail.id_tvmaze:
                    episodes = tvmaze_show_episodes(int(detail.id_tvmaze))
                else:
                    episodes = []
                show = tvmaze_show_details(int(detail.id_tvmaze)) if detail.id_tvmaze else None
                series_name = show.get("name", "") if show else detail.series
                for ep in episodes:
                    ep.series = ep.series or series_name
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
            "Search movie, TV, book, audiobook, and audio catalogs, then review a richer detail card before sending metadata into your library."
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
        self.cmb_type.addItems(["Movie", "TV Show", "Book", "Audiobook", "Audio"])
        self.cmb_type.setAccessibleName("Media type")
        self.cmb_type.setToolTip("Choose the catalog to search")
        self.cmb_type.currentIndexChanged.connect(self._update_search_placeholder)
        self.cmb_type.setFixedWidth(110)
        self.cmb_type.setFixedHeight(28)
        sb_lay.addWidget(self.cmb_type)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search movies, TV, books, or audio…")
        self.txt_search.setAccessibleName("Media search query")
        self.txt_search.setFixedHeight(28)
        self.txt_search.returnPressed.connect(self._on_search)
        sb_lay.addWidget(self.txt_search, 1)

        self.txt_year = QLineEdit()
        self.txt_year.setPlaceholderText("Year")
        self.txt_year.setAccessibleName("Release or publication year")
        self.txt_year.setFixedWidth(60)
        self.txt_year.setFixedHeight(28)
        sb_lay.addWidget(self.txt_year)

        self.btn_search = QPushButton("Search")
        self.btn_search.setProperty("class", "primary")
        self.btn_search.setAccessibleName("Search media providers")
        self.btn_search.clicked.connect(self._on_search)
        sb_lay.addWidget(self.btn_search)

        self.btn_parse = QPushButton("Parse Filename")
        self.btn_parse.setToolTip("Parse a video, book, audiobook, or audio filename to auto-fill the search query")
        self.btn_parse.setAccessibleName("Parse media filename")
        self.btn_parse.setProperty("class", "success")
        self.btn_parse.clicked.connect(self._on_parse_filename)
        sb_lay.addWidget(self.btn_parse)

        lay.addWidget(self.search_bar)

        # Provider credentials/status
        self.credentials_bar = QFrame()
        self.credentials_bar.setProperty("class", "card")
        key_lay = QHBoxLayout(self.credentials_bar)
        key_lay.setContentsMargins(16, 10, 16, 10)
        key_lay.setSpacing(8)

        self.lbl_key_status = QLabel("")
        self.lbl_key_status.setWordWrap(True)
        self.lbl_key_status.setMinimumWidth(260)
        key_lay.addWidget(self.lbl_key_status, 1)

        self.txt_tmdb_key = QLineEdit()
        self.txt_tmdb_key.setPlaceholderText("TMDb API key")
        self.txt_tmdb_key.setAccessibleName("TMDb API key")
        self.txt_tmdb_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_tmdb_key.setFixedHeight(28)
        key_lay.addWidget(self.txt_tmdb_key)

        self.txt_omdb_key = QLineEdit()
        self.txt_omdb_key.setPlaceholderText("OMDb API key")
        self.txt_omdb_key.setAccessibleName("OMDb API key")
        self.txt_omdb_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_omdb_key.setFixedHeight(28)
        key_lay.addWidget(self.txt_omdb_key)

        self.txt_tvdb_key = QLineEdit()
        self.txt_tvdb_key.setPlaceholderText("TVDB API key")
        self.txt_tvdb_key.setAccessibleName("TVDB API key")
        self.txt_tvdb_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_tvdb_key.setFixedHeight(28)
        key_lay.addWidget(self.txt_tvdb_key)

        self.txt_tvdb_pin = QLineEdit()
        self.txt_tvdb_pin.setPlaceholderText("TVDB PIN (optional)")
        self.txt_tvdb_pin.setAccessibleName("TVDB subscriber PIN")
        self.txt_tvdb_pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_tvdb_pin.setFixedHeight(28)
        self.txt_tvdb_pin.setFixedWidth(115)
        key_lay.addWidget(self.txt_tvdb_pin)

        self.btn_save_keys = QPushButton("Save Keys")
        self.btn_save_keys.setProperty("class", "toolbar")
        self.btn_save_keys.clicked.connect(self._on_save_api_keys)
        key_lay.addWidget(self.btn_save_keys)

        lay.addWidget(self.credentials_bar)

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
        self._load_api_key_fields()
        self._refresh_provider_status()
        self.apply_theme()

    def _load_api_key_fields(self):
        keys = load_media_api_keys()
        statuses = media_provider_statuses()
        fields = {
            "tmdb": self.txt_tmdb_key,
            "omdb": self.txt_omdb_key,
            "tvdb": self.txt_tvdb_key,
        }
        for provider, field in fields.items():
            status = statuses.get(provider, {})
            if status.get("source") == "environment":
                field.setText("")
                field.setPlaceholderText(f"Using {status.get('env_var', '')}")
                field.setEnabled(False)
            else:
                field.setEnabled(True)
                field.setText(keys.get(provider, ""))
                field.setPlaceholderText(f"{status.get('label', provider)} API key")

        tvdb_status = statuses.get("tvdb", {})
        if tvdb_status.get("pin_source") == "environment":
            self.txt_tvdb_pin.setText("")
            self.txt_tvdb_pin.setPlaceholderText(
                f"Using {tvdb_status.get('pin_env_var', 'API_KEY_TVDB_PIN')}"
            )
            self.txt_tvdb_pin.setEnabled(False)
        else:
            self.txt_tvdb_pin.setEnabled(True)
            self.txt_tvdb_pin.setText(keys.get("tvdb_pin", ""))
            self.txt_tvdb_pin.setPlaceholderText("TVDB PIN (optional)")

    def _refresh_provider_status(self) -> str:
        statuses = media_provider_statuses()
        parts = []
        for provider in ("tmdb", "tvdb", "omdb", "tvmaze", "openlibrary", "googlebooks", "musicbrainz"):
            status = statuses.get(provider, {})
            label = status.get("label", provider)
            last_error = status.get("last_error", "")
            if last_error:
                parts.append(f"{label}: {last_error}")
            elif not status.get("requires_key", False):
                parts.append(f"{label}: ready (no key)")
            elif status.get("configured", False):
                source = "env" if status.get("source") == "environment" else "settings"
                parts.append(f"{label}: key from {source}")
            else:
                parts.append(f"{label}: missing {status.get('env_var', 'API key')}")
        text = " | ".join(parts)
        self.lbl_key_status.setText(text)
        return text

    def _provider_issue_text(self, media_type: MediaType) -> str:
        statuses = media_provider_statuses()
        providers = {
            MediaType.MOVIE: ("tmdb", "omdb"),
            MediaType.EPISODE: ("tvdb", "tmdb", "tvmaze"),
            MediaType.BOOK: ("openlibrary", "googlebooks"),
            MediaType.AUDIOBOOK: ("openlibrary", "googlebooks"),
            MediaType.AUDIO: ("musicbrainz",),
        }.get(media_type, ())
        issues = []
        for provider in providers:
            status = statuses.get(provider, {})
            label = status.get("label", provider)
            if status.get("last_error"):
                issues.append(f"{label}: {status['last_error']}")
            elif status.get("requires_key") and not status.get("configured"):
                issues.append(f"{label}: missing API key")
        if not issues:
            return ""
        if media_type == MediaType.MOVIE and len(issues) == 2:
            return "Movie lookup needs a TMDb or OMDb key. Add one above or set API_KEY_TMDB/API_KEY_OMDB."
        return "Provider status: " + "; ".join(issues)

    def _selected_media_type(self) -> MediaType:
        return (
            MediaType.MOVIE,
            MediaType.EPISODE,
            MediaType.BOOK,
            MediaType.AUDIOBOOK,
            MediaType.AUDIO,
        )[min(max(self.cmb_type.currentIndex(), 0), 4)]

    def _set_media_type(self, media_type: MediaType) -> None:
        index = {
            MediaType.MOVIE: 0,
            MediaType.EPISODE: 1,
            MediaType.BOOK: 2,
            MediaType.AUDIOBOOK: 3,
            MediaType.AUDIO: 4,
        }.get(media_type, 0)
        self.cmb_type.setCurrentIndex(index)

    def _update_search_placeholder(self, _index: int = 0) -> None:
        placeholders = {
            MediaType.MOVIE: "Search movie titles…",
            MediaType.EPISODE: "Search TV show titles…",
            MediaType.BOOK: "Search book titles or authors…",
            MediaType.AUDIOBOOK: "Search audiobook titles or authors…",
            MediaType.AUDIO: "Search song titles or artists…",
        }
        self.txt_search.setPlaceholderText(placeholders[self._selected_media_type()])

    def _on_save_api_keys(self):
        keys = load_media_api_keys()
        if self.txt_tmdb_key.isEnabled():
            keys["tmdb"] = self.txt_tmdb_key.text().strip()
        if self.txt_omdb_key.isEnabled():
            keys["omdb"] = self.txt_omdb_key.text().strip()
        if self.txt_tvdb_key.isEnabled():
            keys["tvdb"] = self.txt_tvdb_key.text().strip()
        if self.txt_tvdb_pin.isEnabled():
            keys["tvdb_pin"] = self.txt_tvdb_pin.text().strip()
        if save_media_api_keys(keys):
            clear_media_provider_errors()
            self.lbl_status.setText("Media provider keys saved")
            self.lbl_results_hint.setText("Provider settings updated. Search again to refresh results.")
            self._load_api_key_fields()
            self._refresh_provider_status()
        else:
            self.lbl_status.setText("Could not save media provider keys")

    # ── Search ─────────────────────────────────────────────────────────────

    def _on_search(self):
        query = self.txt_search.text().strip()
        if not query:
            self.lbl_status.setText("Enter a title, then search")
            return

        media_type = self._selected_media_type()
        year = self.txt_year.text().strip() or None
        self._refresh_provider_status()

        self.lbl_status.setText("Searching connected providers…")
        self.lbl_results_hint.setText(self._provider_chain_text(media_type))
        self.tbl_results.setRowCount(0)
        self.tbl_episodes.setRowCount(0)
        self.tbl_episodes.setVisible(False)
        self.lbl_episodes.setVisible(False)
        self._clear_detail()

        self._worker = _SearchWorker(query, year or "", media_type)
        self._worker.results_ready.connect(self._on_search_results)
        self._worker.error.connect(self._on_search_error)
        self._worker.start()

    @staticmethod
    def _provider_chain_text(media_type: MediaType) -> str:
        chains = {
            MediaType.MOVIE: "Reviewing TMDb, then OMDb, for the best movie matches.",
            MediaType.EPISODE: "Reviewing TVDB, then TMDb, then TVMaze, for the best TV matches.",
            MediaType.BOOK: "Reviewing OpenLibrary, then Google Books, for the best book matches.",
            MediaType.AUDIOBOOK: "Reviewing OpenLibrary, then Google Books, for the best audiobook matches.",
            MediaType.AUDIO: "Reviewing MusicBrainz for recording, artist, and release metadata.",
        }
        return chains.get(media_type, "Reviewing connected providers.")

    def _on_parse_filename(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Media File",
            filter="Media Files (*.mp4 *.mkv *.avi *.m4v *.wmv *.ts *.mov *.srt *.sub *.epub *.pdf *.mobi *.azw3 *.m4b *.aax *.mp3 *.flac *.m4a *.wav *.ogg *.opus);;All Files (*)")
        if not files:
            return

        filename = Path(files[0]).name
        parsed = parse_media_filename(filename)

        self.txt_search.setText(parsed.get("title", ""))
        self.txt_year.setText(parsed.get("year", "") or "")

        self._set_media_type(parsed.get("type", MediaType.MOVIE))

        # Auto-search
        self._on_search()

    def search_for_filename(self, filename: str):
        """Programmatic search — called from context menus in other panels."""
        parsed = parse_media_filename(filename)
        self.txt_search.setText(parsed.get("title", ""))
        self.txt_year.setText(parsed.get("year", "") or "")
        self._set_media_type(parsed.get("type", MediaType.MOVIE))
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
                self.tbl_results.setItem(row, 0, QTableWidgetItem(result.series or result.title))
                self.tbl_results.setItem(row, 1, QTableWidgetItem(result.year))
                self.tbl_results.setItem(row, 2, QTableWidgetItem("TV Show"))
                id_str = result.id_tvdb or result.id_tmdb or result.id_tvmaze or result.id_imdb
                self.tbl_results.setItem(row, 3, QTableWidgetItem(id_str))
            elif isinstance(result, BookResult):
                self.tbl_results.setItem(row, 0, QTableWidgetItem(result.title))
                self.tbl_results.setItem(row, 1, QTableWidgetItem(result.year))
                label = "Audiobook" if self._selected_media_type() == MediaType.AUDIOBOOK else "Book"
                self.tbl_results.setItem(row, 2, QTableWidgetItem(label))
                id_str = result.id_openlibrary or result.id_googlebooks
                self.tbl_results.setItem(row, 3, QTableWidgetItem(id_str))
            elif isinstance(result, AudioResult):
                self.tbl_results.setItem(row, 0, QTableWidgetItem(result.title))
                self.tbl_results.setItem(row, 1, QTableWidgetItem(result.year))
                self.tbl_results.setItem(row, 2, QTableWidgetItem("Audio"))
                self.tbl_results.setItem(row, 3, QTableWidgetItem(result.id_musicbrainz))

        count = len(results)
        media_type = self._selected_media_type()
        provider_issue = self._provider_issue_text(media_type)
        self._refresh_provider_status()
        self.lbl_status.setText(
            f"{count} result{'s' if count != 1 else ''} found"
            if count else
            "No matches found"
        )
        self.lbl_results_title.setText(f"Results ({count})")
        self.lbl_results_hint.setText(
            "Select a result to load artwork, synopsis, and IDs."
            if count else
            provider_issue or "No provider returned a confident match for that search."
        )

    @pyqtSlot(str)
    def _on_search_error(self, error_msg):
        self._refresh_provider_status()
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
            if detail.id_tvdb:
                ids.append(f"TVDB: {detail.id_tvdb}")
            if detail.id_tmdb:
                ids.append(f"TMDb: {detail.id_tmdb}")
            if detail.id_tvmaze:
                ids.append(f"TVMaze: {detail.id_tvmaze}")
            if detail.id_imdb:
                ids.append(f"IMDb: {detail.id_imdb}")
            self.lbl_ids.setText("  |  ".join(ids))

        elif isinstance(detail, BookResult):
            label = "Audiobook" if self._selected_media_type() == MediaType.AUDIOBOOK else "Book"
            self.lbl_detail_title.setText(detail.title)
            author_text = ", ".join(detail.authors)
            meta = f"{label}  |  {detail.year}" if detail.year else label
            if author_text:
                meta += f"  |  {author_text}"
            self.lbl_detail_meta.setText(meta)
            self.lbl_genres.setText(", ".join(detail.genres) if detail.genres else "")
            self.txt_synopsis.setText(detail.synopsis or "No synopsis available.")
            ids = []
            if detail.id_openlibrary:
                ids.append(f"OpenLibrary: {detail.id_openlibrary}")
            if detail.id_googlebooks:
                ids.append(f"Google Books: {detail.id_googlebooks}")
            if detail.isbn:
                ids.append(f"ISBN: {detail.isbn}")
            self.lbl_ids.setText("  |  ".join(ids))

        elif isinstance(detail, AudioResult):
            self.lbl_detail_title.setText(detail.title)
            meta = "Audio"
            if detail.year:
                meta += f"  |  {detail.year}"
            if detail.artist:
                meta += f"  |  {detail.artist}"
            if detail.album:
                meta += f"  |  {detail.album}"
            self.lbl_detail_meta.setText(meta)
            self.lbl_genres.setText(detail.genre)
            self.txt_synopsis.setText(detail.synopsis or "No synopsis available.")
            ids = []
            if detail.id_musicbrainz:
                ids.append(f"MusicBrainz: {detail.id_musicbrainz}")
            if detail.release_id:
                ids.append(f"Release: {detail.release_id}")
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
        ids = []
        if ep.id_tvdb:
            ids.append(f"TVDB: {ep.id_tvdb}")
        if ep.id_tmdb:
            ids.append(f"TMDb: {ep.id_tmdb}")
        if ep.id_tvmaze:
            ids.append(f"TVMaze: {ep.id_tvmaze}")
        if ep.id_imdb:
            ids.append(f"IMDb: {ep.id_imdb}")
        self.lbl_ids.setText("  |  ".join(ids))
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
            meta["id_tvdb"] = detail.id_tvdb
            meta["id_tmdb"] = detail.id_tmdb
            meta["id_imdb"] = detail.id_imdb
            meta["media_type"] = "episode"
        elif isinstance(detail, BookResult):
            meta["title"] = detail.title
            meta["author"] = "; ".join(detail.authors)
            meta["authors"] = detail.authors
            meta["year"] = detail.year
            meta["synopsis"] = detail.synopsis
            meta["genres"] = detail.genres
            meta["isbn"] = detail.isbn
            meta["language"] = detail.language
            meta["series"] = detail.series
            meta["publisher"] = detail.publisher
            meta["published"] = detail.year
            meta["cover_url"] = detail.cover_url
            meta["source_url"] = detail.source_url
            meta["id_openlibrary"] = detail.id_openlibrary
            meta["id_googlebooks"] = detail.id_googlebooks
            meta["media_type"] = (
                "audiobook" if self._selected_media_type() == MediaType.AUDIOBOOK else "book"
            )
        elif isinstance(detail, AudioResult):
            meta["title"] = detail.title
            meta["artist"] = detail.artist
            meta["album"] = detail.album
            meta["year"] = detail.year
            meta["synopsis"] = detail.synopsis
            meta["genre"] = detail.genre
            meta["genres"] = [detail.genre] if detail.genre else []
            meta["id_musicbrainz"] = detail.id_musicbrainz
            meta["release_id"] = detail.release_id
            meta["cover_url"] = detail.cover_url
            meta["source_url"] = detail.source_url
            meta["media_type"] = "audio"
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
        for panel in (self.search_bar, self.credentials_bar, self.results_panel, self.detail_panel):
            panel.setStyleSheet(
                f"QFrame {{ background: {t['bg_alt']}; border: 1px solid {t['border']}; border-radius: 18px; }}"
            )
        self.lbl_key_status.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
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
