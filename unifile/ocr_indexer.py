"""UniFile — OCR indexer: extracts text from images/PDFs and stores in Tag Library."""
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)
from sqlalchemy.orm import Session

from unifile.config import get_active_theme, get_active_stylesheet

_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.webp', '.gif'}
_PDF_EXTS   = {'.pdf'}


# ── OCR worker ────────────────────────────────────────────────────────────────

class OcrWorker(QThread):
    """Extracts text from image and PDF entries and stores it in the Tag Library."""

    progress   = pyqtSignal(int, int)   # current, total
    entry_done = pyqtSignal(int, str)   # entry_id, extracted_text (preview)
    finished   = pyqtSignal(int)        # total_processed

    def __init__(
        self,
        entry_paths: list[tuple[int, str]],
        library,
        parent=None,
    ):
        super().__init__(parent)
        self._entry_paths = entry_paths
        self._db_engine   = library.engine   # store Engine, not Session
        self._engine      = 'auto'
        self._lang        = 'eng'
        self._abort       = False

    def set_engine(self, engine: str):
        """Set OCR engine: 'auto', 'tesseract', or 'easyocr'."""
        self._engine = engine.lower()

    def set_lang(self, lang: str):
        self._lang = lang.strip() or 'eng'

    def stop(self):
        self._abort = True

    # ── Main thread body ─────────────────────────────────────────────────────

    def run(self):
        has_tess = self._probe_tesseract()
        has_easy = self._probe_easyocr()

        if not has_tess and not has_easy:
            self.finished.emit(0)
            return

        total     = len(self._entry_paths)
        processed = 0

        with Session(self._db_engine) as session:
            for idx, (entry_id, file_path) in enumerate(self._entry_paths):
                if self._abort:
                    break
                self.progress.emit(idx + 1, total)

                ext  = Path(file_path).suffix.lower()
                text = ''
                try:
                    if ext in _PDF_EXTS:
                        text = self._ocr_pdf(file_path, has_tess, has_easy)
                    elif ext in _IMAGE_EXTS:
                        text = self._ocr_image(file_path, has_tess, has_easy)
                except Exception:
                    text = ''

                if text.strip():
                    try:
                        from unifile.tagging.library import TagLibrary
                        TagLibrary.set_entry_field_with_session(
                            session, entry_id, 'ai_summary', text[:2000]
                        )
                    except Exception:
                        pass
                    self.entry_done.emit(entry_id, text[:200])
                    processed += 1

        self.finished.emit(processed)

    # ── Dependency probes ────────────────────────────────────────────────────

    def _probe_tesseract(self) -> bool:
        if self._engine == 'easyocr':
            return False
        try:
            import pytesseract   # noqa: F401
            return True
        except ImportError:
            return False

    def _probe_easyocr(self) -> bool:
        if self._engine == 'tesseract':
            return False
        try:
            import easyocr       # noqa: F401
            return True
        except ImportError:
            return False

    # ── OCR helpers ──────────────────────────────────────────────────────────

    def _ocr_image(self, path: str, has_tess: bool, has_easy: bool) -> str:
        if self._engine in ('auto', 'tesseract') and has_tess:
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(path)
                return pytesseract.image_to_string(img, lang=self._lang)
            except Exception:
                pass

        if self._engine in ('auto', 'easyocr') and has_easy:
            try:
                import easyocr
                reader  = easyocr.Reader([self._lang], gpu=False, verbose=False)
                results = reader.readtext(path, detail=0)
                return ' '.join(results)
            except Exception:
                pass

        return ''

    def _ocr_pdf(self, path: str, has_tess: bool, has_easy: bool) -> str:
        # Prefer pdfminer (clean digital text, no OCR needed)
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(path)
            if text and text.strip():
                return text.strip()
        except Exception:
            pass

        # Render first page to image, then OCR
        import tempfile
        img_fd, img_path = tempfile.mkstemp(suffix='.__ocr_tmp.png')
        os.close(img_fd)
        try:
            rendered = self._render_pdf_page(path, img_path)
            if rendered:
                return self._ocr_image(img_path, has_tess, has_easy)
        finally:
            try:
                os.remove(img_path)
            except OSError:
                pass

        return ''

    def _render_pdf_page(self, pdf_path: str, out_png: str) -> bool:
        """Render first page of a PDF to a PNG. Returns True on success."""
        # PyMuPDF (fitz) — fastest
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            if len(doc) == 0:
                return False
            pix = doc[0].get_pixmap(dpi=150)
            from PIL import Image
            img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
            img.save(out_png)
            return True
        except Exception:
            pass

        # pdf2image (Poppler wrapper) — fallback
        try:
            import pdf2image
            pages = pdf2image.convert_from_path(pdf_path, dpi=150, last_page=1)
            if not pages:
                return False
            pages[0].save(out_png)
            return True
        except Exception:
            pass

        return False


# ── Settings panel ────────────────────────────────────────────────────────────

class OcrSettingsPanel(QWidget):
    """Compact widget for configuring and launching OCR over the Tag Library."""

    run_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        t = get_active_theme()
        self.setStyleSheet(get_active_stylesheet())
        self._build_ui(t)

    def _build_ui(self, t: dict):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(8, 8, 8, 8)

        title = QLabel('OCR Indexer')
        title.setStyleSheet(
            f'font-size: 14px; font-weight: 700; color: {t["fg_bright"]};'
        )
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)

        self._engine_combo = QComboBox()
        self._engine_combo.addItems(['Auto', 'Tesseract', 'EasyOCR'])
        form.addRow('OCR Engine:', self._engine_combo)

        self._lang_edit = QLineEdit('eng')
        self._lang_edit.setPlaceholderText('e.g. eng, fra, deu')
        self._lang_edit.setMaximumWidth(140)
        form.addRow('Language:', self._lang_edit)

        self._max_spin = QSpinBox()
        self._max_spin.setRange(1, 100_000)
        self._max_spin.setValue(500)
        self._max_spin.setSuffix(' files')
        form.addRow('Max Files:', self._max_spin)

        root.addLayout(form)

        self._run_btn = QPushButton('Run OCR on Library')
        self._run_btn.setProperty('class', 'primary')
        self._run_btn.clicked.connect(self.run_requested)
        root.addWidget(self._run_btn)

        self._status_lbl = QLabel('No OCR run yet.')
        self._status_lbl.setStyleSheet(
            f'color: {t["muted"]}; font-size: 11px;'
        )
        self._status_lbl.setWordWrap(True)
        root.addWidget(self._status_lbl)

        root.addStretch()

    # ── Public accessors ─────────────────────────────────────────────────────

    def engine(self) -> str:
        """Return selected engine as lowercase string: 'auto', 'tesseract', 'easyocr'."""
        return self._engine_combo.currentText().lower()

    def language(self) -> str:
        return self._lang_edit.text().strip() or 'eng'

    def max_files(self) -> int:
        return self._max_spin.value()

    def set_status(self, text: str):
        self._status_lbl.setText(text)

    def set_running(self, running: bool):
        self._run_btn.setEnabled(not running)
        self._run_btn.setText(
            'Running…' if running else 'Run OCR on Library'
        )
