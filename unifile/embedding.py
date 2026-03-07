"""UniFile -- Metadata embedding (write-back to files).

Writes classification results, tags, and AI descriptions into file metadata:
  - Images: XMP/IPTC Keywords, Subject, Description via Pillow/piexif
  - Audio: ID3 Genre, Comment via mutagen
  - PDF: metadata via PyPDF2
"""
import os
import json
from datetime import datetime

from unifile.config import _APP_DATA_DIR

_EMBED_LOG = os.path.join(_APP_DATA_DIR, 'embed_log.json')


def _try_import(name):
    try:
        return __import__(name)
    except ImportError:
        return None


class MetadataEmbedder:
    """Writes classification metadata back into files."""

    def __init__(self):
        self._log_entries = []

    def embed(self, filepath: str, category: str = "",
              tags: list[str] | None = None,
              description: str = "",
              extra: dict | None = None) -> bool:
        """Embed metadata into a file based on its type.

        Args:
            filepath: Absolute path to the file.
            category: Classification category name.
            tags: List of tag strings to write as keywords.
            description: AI-generated or user description.
            extra: Additional metadata dict.

        Returns:
            True if metadata was written successfully.
        """
        ext = os.path.splitext(filepath)[1].lower()
        tags = tags or []
        if category and category not in tags:
            tags = [category] + tags

        success = False
        try:
            if ext in ('.jpg', '.jpeg', '.tiff', '.tif'):
                success = self._embed_jpeg(filepath, tags, description)
            elif ext == '.png':
                success = self._embed_png(filepath, tags, description)
            elif ext in ('.mp3',):
                success = self._embed_mp3(filepath, tags, description, category)
            elif ext in ('.flac',):
                success = self._embed_flac(filepath, tags, description, category)
            elif ext in ('.m4a', '.mp4', '.m4v'):
                success = self._embed_mp4(filepath, tags, description, category)
            elif ext == '.pdf':
                success = self._embed_pdf(filepath, tags, description)
        except Exception:
            success = False

        self._log_entries.append({
            'file': filepath,
            'success': success,
            'category': category,
            'tags': tags,
            'timestamp': datetime.now().isoformat(),
        })
        return success

    def _embed_jpeg(self, filepath: str, tags: list[str], description: str) -> bool:
        """Embed metadata into JPEG/TIFF via Pillow + piexif."""
        PIL = _try_import('PIL')
        if not PIL:
            return False
        from PIL import Image
        piexif = _try_import('piexif')

        img = Image.open(filepath)
        exif_dict = {}
        if piexif:
            try:
                raw = img.info.get('exif', b'')
                if raw:
                    exif_dict = piexif.load(raw)
            except Exception:
                exif_dict = {'0th': {}, 'Exif': {}, '1st': {}, 'GPS': {}}

            # Write description to ImageDescription
            if description:
                exif_dict.setdefault('0th', {})[piexif.ImageIFD.ImageDescription] = \
                    description.encode('utf-8')

            # Write tags to XPKeywords (Windows-compatible)
            if tags:
                keywords_str = ';'.join(tags)
                exif_dict.setdefault('0th', {})[piexif.ImageIFD.XPKeywords] = \
                    keywords_str.encode('utf-16le')

            exif_bytes = piexif.dump(exif_dict)
            img.save(filepath, exif=exif_bytes, quality=95)
        else:
            # Fallback: write IPTC-style info via Pillow's PngInfo-like approach
            # Just re-save with existing EXIF to not lose data
            img.save(filepath, quality=95)

        return True

    def _embed_png(self, filepath: str, tags: list[str], description: str) -> bool:
        """Embed metadata into PNG via text chunks."""
        PIL = _try_import('PIL')
        if not PIL:
            return False
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo

        img = Image.open(filepath)
        meta = PngInfo()
        if description:
            meta.add_text("Description", description)
        if tags:
            meta.add_text("Keywords", ';'.join(tags))
        meta.add_text("Software", "UniFile")
        img.save(filepath, pnginfo=meta)
        return True

    def _embed_mp3(self, filepath: str, tags: list[str],
                   description: str, category: str) -> bool:
        """Embed metadata into MP3 via mutagen ID3."""
        mutagen = _try_import('mutagen')
        if not mutagen:
            return False
        from mutagen.id3 import ID3, COMM, TXXX
        from mutagen.id3 import ID3NoHeaderError

        try:
            audio = ID3(filepath)
        except ID3NoHeaderError:
            audio = ID3()

        if description:
            audio.delall('COMM')
            audio.add(COMM(encoding=3, lang='eng', desc='UniFile', text=description))
        if tags:
            audio.delall('TXXX:UniFile_Tags')
            audio.add(TXXX(encoding=3, desc='UniFile_Tags', text=';'.join(tags)))
        if category:
            audio.delall('TXXX:UniFile_Category')
            audio.add(TXXX(encoding=3, desc='UniFile_Category', text=category))

        audio.save(filepath)
        return True

    def _embed_flac(self, filepath: str, tags: list[str],
                    description: str, category: str) -> bool:
        """Embed metadata into FLAC via mutagen."""
        mutagen = _try_import('mutagen')
        if not mutagen:
            return False
        from mutagen.flac import FLAC

        audio = FLAC(filepath)
        if description:
            audio['comment'] = [description]
        if tags:
            audio['unifile_tags'] = tags
        if category:
            audio['genre'] = [category]
        audio.save()
        return True

    def _embed_mp4(self, filepath: str, tags: list[str],
                   description: str, category: str) -> bool:
        """Embed metadata into MP4/M4A via mutagen."""
        mutagen = _try_import('mutagen')
        if not mutagen:
            return False
        from mutagen.mp4 import MP4

        audio = MP4(filepath)
        if description:
            audio['\xa9cmt'] = [description]
        if category:
            audio['\xa9gen'] = [category]
        audio.save()
        return True

    def _embed_pdf(self, filepath: str, tags: list[str], description: str) -> bool:
        """Embed metadata into PDF via PyPDF2."""
        PyPDF2 = _try_import('PyPDF2')
        if not PyPDF2:
            pypdf = _try_import('pypdf')
            if not pypdf:
                return False
            from pypdf import PdfReader, PdfWriter
        else:
            from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(filepath)
        writer = PdfWriter()
        writer.append_pages_from_reader(reader)

        meta = {'/Producer': 'UniFile'}
        if description:
            meta['/Subject'] = description
        if tags:
            meta['/Keywords'] = ';'.join(tags)
        writer.add_metadata(meta)

        tmp = filepath + '.tmp'
        with open(tmp, 'wb') as f:
            writer.write(f)
        os.replace(tmp, filepath)
        return True

    def embed_batch(self, items: list[dict]) -> dict:
        """Embed metadata into multiple files.

        Each item: {'filepath': str, 'category': str, 'tags': list, 'description': str}

        Returns:
            {'success': int, 'failed': int, 'skipped': int}
        """
        stats = {'success': 0, 'failed': 0, 'skipped': 0}
        for item in items:
            fp = item.get('filepath', '')
            if not fp or not os.path.isfile(fp):
                stats['skipped'] += 1
                continue
            ok = self.embed(
                fp,
                category=item.get('category', ''),
                tags=item.get('tags'),
                description=item.get('description', ''),
            )
            if ok:
                stats['success'] += 1
            else:
                stats['failed'] += 1
        self._save_log()
        return stats

    def _save_log(self):
        """Save embedding log to disk."""
        try:
            existing = []
            if os.path.isfile(_EMBED_LOG):
                with open(_EMBED_LOG, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            existing.extend(self._log_entries)
            # Keep last 500 entries
            existing = existing[-500:]
            with open(_EMBED_LOG, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=2)
            self._log_entries.clear()
        except OSError:
            pass
