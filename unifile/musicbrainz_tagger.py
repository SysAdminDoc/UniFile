"""UniFile — MusicBrainz auto-tagger dialog (pyacoustid + musicbrainzngs)."""
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from unifile.config import get_active_theme, get_active_stylesheet, _APP_DATA_DIR

# ── AcoustID API key management ───────────────────────────────────────────────
# Users must register their own key at https://acoustid.org/applications

_ACOUSTID_KEY_FILE = os.path.join(_APP_DATA_DIR, 'acoustid_key.txt')


def _load_acoustid_key() -> str:
    """Load saved AcoustID API key, or return empty string if not configured."""
    try:
        if os.path.isfile(_ACOUSTID_KEY_FILE):
            with open(_ACOUSTID_KEY_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except OSError:
        pass
    return ''


def _save_acoustid_key(key: str) -> None:
    os.makedirs(os.path.dirname(_ACOUSTID_KEY_FILE), exist_ok=True)
    with open(_ACOUSTID_KEY_FILE, 'w', encoding='utf-8') as f:
        f.write(key.strip())

_HAS_ACOUSTID = False
_HAS_MBZ = False
try:
    import acoustid          # noqa: F401
    _HAS_ACOUSTID = True
except ImportError:
    pass
try:
    import musicbrainzngs    # noqa: F401
    _HAS_MBZ = True
except ImportError:
    pass

# ── Column indices ─────────────────────────────────────────────────────────────
_COL_FILE   = 0
_COL_ACID   = 1
_COL_ARTIST = 2
_COL_TITLE  = 3
_COL_ALBUM  = 4
_COL_YEAR   = 5
_COL_STATUS = 6
_HEADERS = ['File', 'AcoustID', 'Artist', 'Title', 'Album', 'Year', 'Status']


# ── Workers ────────────────────────────────────────────────────────────────────

class _MBWorker(QThread):
    """Fingerprint each file via acoustid then fetch metadata from MusicBrainz."""

    result  = pyqtSignal(int, dict)   # row_index, tag_dict
    finished = pyqtSignal()

    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = file_paths
        self._abort = False

    def stop(self):
        self._abort = True

    def run(self):
        try:
            import acoustid
            import musicbrainzngs
        except ImportError:
            self.finished.emit()
            return

        api_key = _load_acoustid_key()
        if not api_key:
            self.finished.emit()
            return

        musicbrainzngs.set_useragent('UniFile', '1.0',
                                     'https://github.com/user/UniFile')

        for idx, path in enumerate(self._paths):
            if self._abort:
                break
            tags: dict = {
                'artist': '', 'title': '', 'album': '',
                'year': '', 'acoustid': '',
            }
            try:
                duration, fingerprint = acoustid.fingerprint_file(path)
                raw = acoustid.lookup(
                    api_key, fingerprint, duration,
                    meta='recordings releases',
                )
                recording_id: str | None = None
                for score, rid, title, artist in acoustid.parse_lookup_result(raw):
                    if rid:
                        tags['acoustid'] = rid
                        tags['title']    = title  or ''
                        tags['artist']   = artist or ''
                        recording_id     = rid
                        break

                if recording_id:
                    rec = musicbrainzngs.get_recording_by_id(
                        recording_id, includes=['artists', 'releases'],
                    )
                    r = rec.get('recording', {})
                    if not tags['title']:
                        tags['title'] = r.get('title', '')
                    if not tags['artist']:
                        credits = r.get('artist-credit', [])
                        if credits and isinstance(credits[0], dict):
                            tags['artist'] = (
                                credits[0].get('artist', {}).get('name', '')
                            )
                    releases = r.get('release-list', [])
                    if releases:
                        rel = releases[0]
                        tags['album'] = rel.get('title', '')
                        tags['year']  = (rel.get('date') or '')[:4]
            except Exception:
                pass

            self.result.emit(idx, tags)

        self.finished.emit()


class _TagApplyWorker(QThread):
    """Write ID3/Vorbis/MP4 tags using mutagen."""

    done     = pyqtSignal(int, bool)  # row_index, success
    all_done = pyqtSignal()

    def __init__(self, tasks: list[tuple[int, str, dict]], parent=None):
        super().__init__(parent)
        self._tasks = tasks   # list of (row_idx, filepath, tag_dict)

    def run(self):
        for row_idx, filepath, tags in self._tasks:
            ok = self._apply(filepath, tags)
            self.done.emit(row_idx, ok)
        self.all_done.emit()

    def _apply(self, filepath: str, tags: dict) -> bool:
        try:
            ext = Path(filepath).suffix.lower()
            if ext == '.mp3':
                from mutagen.easyid3 import EasyID3
                try:
                    audio = EasyID3(filepath)
                except Exception:
                    from mutagen.id3 import ID3, ID3NoHeaderError
                    try:
                        ID3(filepath).save(filepath)
                    except ID3NoHeaderError:
                        ID3().save(filepath)
                    audio = EasyID3(filepath)
                if tags.get('title'):
                    audio['title']  = [tags['title']]
                if tags.get('artist'):
                    audio['artist'] = [tags['artist']]
                if tags.get('album'):
                    audio['album']  = [tags['album']]
                if tags.get('year'):
                    audio['date']   = [tags['year']]
                audio.save()

            elif ext == '.flac':
                from mutagen.flac import FLAC
                audio = FLAC(filepath)
                if tags.get('title'):
                    audio['title']  = [tags['title']]
                if tags.get('artist'):
                    audio['artist'] = [tags['artist']]
                if tags.get('album'):
                    audio['album']  = [tags['album']]
                if tags.get('year'):
                    audio['date']   = [tags['year']]
                audio.save()

            elif ext in ('.m4a', '.mp4', '.aac'):
                from mutagen.mp4 import MP4
                audio = MP4(filepath)
                if tags.get('title'):
                    audio['\xa9nam'] = [tags['title']]
                if tags.get('artist'):
                    audio['\xa9ART'] = [tags['artist']]
                if tags.get('album'):
                    audio['\xa9alb'] = [tags['album']]
                if tags.get('year'):
                    audio['\xa9day'] = [tags['year']]
                audio.save()

            else:
                return False
            return True
        except Exception:
            return False


# ── Dialog ─────────────────────────────────────────────────────────────────────

class MusicBrainzTaggerDialog(QDialog):
    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = file_paths
        self._results: dict[int, dict] = {}
        self._worker: _MBWorker | None = None
        self._apply_worker: _TagApplyWorker | None = None

        self.setWindowTitle('MusicBrainz Auto-Tagger')
        self.resize(960, 540)
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui()
        self._check_deps()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        t = get_active_theme()
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)

        # Dependency warning (hidden when deps present)
        self._dep_label = QLabel()
        self._dep_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dep_label.setStyleSheet(
            f'color: {t["accent"]}; font-weight: 600; padding: 6px;'
        )
        self._dep_label.hide()
        root.addWidget(self._dep_label)

        # File table
        self._table = QTableWidget(len(self._paths), len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_FILE, QHeaderView.ResizeMode.Stretch,
        )
        for col in range(1, len(_HEADERS)):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents,
            )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows,
        )
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            f'QTableWidget {{ gridline-color: {t["border"]}; }}'
            f'QHeaderView::section {{'
            f'  background: {t["bg_alt"]}; color: {t["fg"]};'
            f'  border: 1px solid {t["border"]}; padding: 4px;'
            f'}}'
        )
        for row, path in enumerate(self._paths):
            self._init_row(row, path)
        root.addWidget(self._table)

        # Status line
        self._status_lbl = QLabel('Ready.')
        self._status_lbl.setStyleSheet(f'color: {t["muted"]};')
        root.addWidget(self._status_lbl)

        # Button row
        btn_row = QHBoxLayout()
        self._identify_btn = QPushButton('Identify All')
        self._identify_btn.setProperty('class', 'primary')
        self._identify_btn.clicked.connect(self._identify_all)

        self._apply_btn = QPushButton('Apply Tags')
        self._apply_btn.clicked.connect(self._apply_tags)
        self._apply_btn.setEnabled(False)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.reject)

        btn_row.addWidget(self._identify_btn)
        btn_row.addWidget(self._apply_btn)
        btn_row.addStretch()

        key_btn = QPushButton('Set API Key…')
        key_btn.setToolTip(
            'AcoustID API key — register free at https://acoustid.org/applications'
        )
        key_btn.clicked.connect(self._set_api_key)
        btn_row.addWidget(key_btn)

        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _init_row(self, row: int, path: str):
        name_item = QTableWidgetItem(Path(path).name)
        name_item.setToolTip(path)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, _COL_FILE, name_item)
        for col in range(1, len(_HEADERS)):
            cell = QTableWidgetItem('')
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, col, cell)

    # ── Dependency check ─────────────────────────────────────────────────────

    def _check_deps(self):
        missing = []
        if not _HAS_ACOUSTID:
            missing.append('pyacoustid')
        if not _HAS_MBZ:
            missing.append('musicbrainzngs')
        if missing:
            self._dep_label.setText(
                f'Missing dependencies: {", ".join(missing)}  —  '
                f'pip install {" ".join(missing)}'
            )
            self._dep_label.show()
            self._identify_btn.setEnabled(False)
            return
        if not _load_acoustid_key():
            self._dep_label.setText(
                'No AcoustID API key configured. '
                'Click "Set API Key..." to register yours at acoustid.org/applications.'
            )
            self._dep_label.show()
            self._identify_btn.setEnabled(False)

    def _set_api_key(self):
        current = _load_acoustid_key()
        key, ok = QInputDialog.getText(
            self, 'AcoustID API Key',
            'Enter your AcoustID API key\n'
            '(register free at https://acoustid.org/applications):',
            text=current,
        )
        if ok and key.strip():
            _save_acoustid_key(key.strip())
            self._dep_label.hide()
            if _HAS_ACOUSTID and _HAS_MBZ:
                self._identify_btn.setEnabled(True)
        elif ok and not key.strip():
            QMessageBox.warning(
                self, 'API Key Required',
                'AcoustID lookups require a valid API key.',
            )

    # ── Identification ───────────────────────────────────────────────────────

    def _identify_all(self):
        if self._worker and self._worker.isRunning():
            return
        self._identify_btn.setEnabled(False)
        self._apply_btn.setEnabled(False)
        self._status_lbl.setText('Identifying…')
        for row in range(self._table.rowCount()):
            self._table.item(row, _COL_STATUS).setText('Queued')

        self._worker = _MBWorker(self._paths, self)
        self._worker.result.connect(self._on_result)
        self._worker.finished.connect(self._on_identify_done)
        self._worker.start()

    def _on_result(self, row: int, tags: dict):
        self._results[row] = tags
        acid_short = (tags.get('acoustid') or '')[:12]
        self._table.item(row, _COL_ACID).setText(acid_short)
        self._table.item(row, _COL_ARTIST).setText(tags.get('artist', ''))
        self._table.item(row, _COL_TITLE).setText(tags.get('title',  ''))
        self._table.item(row, _COL_ALBUM).setText(tags.get('album',  ''))
        self._table.item(row, _COL_YEAR).setText(tags.get('year',   ''))
        found = bool(tags.get('title') or tags.get('artist'))
        self._table.item(row, _COL_STATUS).setText('Found' if found else 'No match')

    def _on_identify_done(self):
        self._identify_btn.setEnabled(True)
        matched = sum(
            1 for t in self._results.values()
            if t.get('title') or t.get('artist')
        )
        self._status_lbl.setText(
            f'Done. {matched}/{len(self._paths)} matched.'
        )
        if matched:
            self._apply_btn.setEnabled(True)

    # ── Tag application ──────────────────────────────────────────────────────

    def _apply_tags(self):
        if self._apply_worker and self._apply_worker.isRunning():
            return
        selected = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not selected:
            selected = list(range(len(self._paths)))

        tasks = [
            (row, self._paths[row], self._results[row])
            for row in selected
            if row in self._results
        ]
        if not tasks:
            self._status_lbl.setText('No identified tracks to apply.')
            return

        self._apply_btn.setEnabled(False)
        self._status_lbl.setText('Applying tags…')
        for row, _, _ in tasks:
            self._table.item(row, _COL_STATUS).setText('Writing…')

        self._apply_worker = _TagApplyWorker(tasks, self)
        self._apply_worker.done.connect(self._on_tag_done)
        self._apply_worker.all_done.connect(self._on_apply_all_done)
        self._apply_worker.start()

    def _on_tag_done(self, row: int, ok: bool):
        self._table.item(row, _COL_STATUS).setText('Tagged' if ok else 'Error')

    def _on_apply_all_done(self):
        self._apply_btn.setEnabled(True)
        self._status_lbl.setText('Tags applied.')

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        if self._apply_worker and self._apply_worker.isRunning():
            self._apply_worker.wait(2000)
        super().closeEvent(event)
