"""Book-library discovery, metadata lookup, tagging, and Calibre OPF export.

The book pipeline is deliberately additive. It never renames or moves ebook
files, network lookup is opt-in, and generated OPF files live in a separate
export tree unless the caller explicitly chooses another destination.
"""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from unifile import __version__
from unifile.network import request_bytes, request_json
from unifile.tagging.library import TagLibrary

BOOK_EXTENSIONS = frozenset({".epub", ".pdf", ".mobi", ".azw3"})
BOOK_TAG = "book"
BOOK_CACHE_NAME = "book-metadata-cache.json"
BOOK_COVER_DIR = "book-covers"
DEFAULT_USER_AGENT = f"UniFile/{__version__} (https://github.com/SysAdminDoc/UniFile)"
OPENLIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_OPENLIBRARY_FIELDS = ",".join(
    (
        "key",
        "title",
        "author_name",
        "isbn",
        "isbn10",
        "isbn13",
        "language",
        "subject",
        "subject_key",
        "first_sentence",
        "description",
        "publisher",
        "publish_date",
        "cover_i",
    )
)
_ISBN_RE = re.compile(r"(?<!\d)(?:97[89][\d\s-]{10,17}|[\dXx][\d\s-]{8,15}[\dXx])(?!\d)")
_WHITESPACE_RE = re.compile(r"\s+")
_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class BookMetadataError(RuntimeError):
    """Raised when a book metadata operation cannot be completed safely."""


@dataclass
class BookMetadata:
    path: Path
    title: str
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None
    language: str | None = None
    genres: list[str] = field(default_factory=list)
    series: str | None = None
    series_index: str | None = None
    description: str | None = None
    publisher: str | None = None
    published: str | None = None
    source_url: str | None = None
    cover_url: str | None = None
    cover_path: Path | None = None
    reading_status: str = "unread"
    provider: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation suitable for CLI output."""
        return {
            "path": str(self.path),
            "title": self.title,
            "authors": list(self.authors),
            "isbn": self.isbn,
            "language": self.language,
            "genres": list(self.genres),
            "series": self.series,
            "series_index": self.series_index,
            "description": self.description,
            "publisher": self.publisher,
            "published": self.published,
            "source_url": self.source_url,
            "cover_url": self.cover_url,
            "cover_path": str(self.cover_path) if self.cover_path else None,
            "reading_status": self.reading_status,
            "provider": self.provider,
            "warnings": list(self.warnings),
        }


@dataclass
class BookScanResult:
    source: str
    library: str | None
    books: list[BookMetadata] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    applied: int = 0
    looked_up: int = 0
    covers_downloaded: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "library": self.library,
            "books": [book.to_dict() for book in self.books],
            "count": len(self.books),
            "errors": list(self.errors),
            "applied": self.applied,
            "looked_up": self.looked_up,
            "covers_downloaded": self.covers_downloaded,
        }


@dataclass
class BookExportResult:
    library: str
    output: str
    exported: int = 0
    skipped: int = 0
    covers_copied: int = 0
    errors: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "output": self.output,
            "exported": self.exported,
            "skipped": self.skipped,
            "covers_copied": self.covers_copied,
            "errors": list(self.errors),
            "files": list(self.files),
        }


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", html.unescape(str(value))).strip()


def _first(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return _clean(value[0]) if value else ""
    if isinstance(value, dict):
        return _clean(value.get("value") or value.get("text"))
    return _clean(value)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[,;|]\s*", str(value))
    return list(dict.fromkeys(item for item in (_clean(v) for v in values) if item))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _filename_fallback(path: Path) -> BookMetadata:
    stem = _clean(path.stem).replace("_", " ")
    authors: list[str] = []
    title = stem or path.name
    if " - " in stem:
        possible_author, possible_title = (part.strip() for part in stem.split(" - ", 1))
        if possible_author and possible_title:
            authors = [possible_author]
            title = possible_title
    return BookMetadata(path=path, title=title, authors=authors)


def _isbn_checksum(value: str) -> bool:
    value = value.upper()
    if len(value) == 10:
        if not re.fullmatch(r"\d{9}[\dX]", value):
            return False
        return sum((10 - index) * (10 if digit == "X" else int(digit)) for index, digit in enumerate(value)) % 11 == 0
    if len(value) == 13 and value.isdigit():
        return sum((1 if index % 2 == 0 else 3) * int(digit) for index, digit in enumerate(value)) % 10 == 0
    return False


def _isbn13_from_isbn10(value: str) -> str:
    body = "978" + value[:9]
    check = (10 - sum((1 if index % 2 == 0 else 3) * int(digit) for index, digit in enumerate(body)) % 10) % 10
    return body + str(check)


def canonical_isbn(value: Any) -> str | None:
    """Return a validated ISBN-13 where possible, using isbnlib when present."""
    text = _clean(value)
    if not text:
        return None
    try:
        import isbnlib

        candidates = isbnlib.get_isbnlike(text, level="normal") or [text]
        for candidate in candidates:
            canonical = _clean(isbnlib.get_canonical_isbn(candidate))
            if _isbn_checksum(canonical):
                return _isbn13_from_isbn10(canonical) if len(canonical) == 10 else canonical
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    candidates = _ISBN_RE.findall(text) or [text]
    for candidate in candidates:
        canonical = re.sub(r"[^0-9Xx]", "", candidate).upper()
        if _isbn_checksum(canonical):
            return _isbn13_from_isbn10(canonical) if len(canonical) == 10 else canonical
    return None


def _extract_epub(path: Path, metadata: BookMetadata) -> BookMetadata:
    with zipfile.ZipFile(path) as archive:
        opf_name = ""
        try:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            rootfile = next((node for node in container.iter() if _local_name(node.tag) == "rootfile"), None)
            opf_name = str(rootfile.attrib.get("full-path", "")) if rootfile is not None else ""
        except (KeyError, ET.ParseError):
            pass
        if not opf_name:
            opf_files = [name for name in archive.namelist() if name.casefold().endswith(".opf")]
            if not opf_files:
                raise BookMetadataError("EPUB has no OPF package document")
            opf_name = opf_files[0]
        root = ET.fromstring(archive.read(opf_name))
        package_metadata = next((node for node in root.iter() if _local_name(node.tag) == "metadata"), None)
        if package_metadata is None:
            return metadata
        identifiers: list[str] = []
        subjects: list[str] = []
        cover_id = ""
        for node in package_metadata:
            name = _local_name(node.tag)
            value = _clean(node.text)
            if name == "title" and value:
                metadata.title = value
            elif name == "creator" and value:
                metadata.authors.append(value)
            elif name == "language" and value:
                metadata.language = value
            elif name == "subject" and value:
                subjects.append(value)
            elif name == "description" and value:
                metadata.description = value
            elif name == "publisher" and value:
                metadata.publisher = value
            elif name == "date" and value:
                metadata.published = value
            elif name == "identifier" and value:
                identifiers.append(value)
            elif name == "meta":
                meta_name = _clean(node.attrib.get("name"))
                meta_property = _clean(node.attrib.get("property"))
                meta_value = _clean(node.attrib.get("content") or node.text)
                key = (meta_name or meta_property).casefold()
                if key in {"calibre:series", "belongs-to-collection"} and meta_value:
                    metadata.series = meta_value
                elif key in {"calibre:series_index", "group-position"} and meta_value:
                    metadata.series_index = meta_value
                elif key == "calibre:tags" and meta_value:
                    subjects.extend(_as_list(meta_value))
                elif key == "cover" and meta_value:
                    cover_id = meta_value
        metadata.authors = list(dict.fromkeys(metadata.authors))
        metadata.genres = list(dict.fromkeys(subjects))
        metadata.isbn = next((canonical_isbn(candidate) for candidate in identifiers if canonical_isbn(candidate)), None)
        if cover_id:
            manifest = next((node for node in root.iter() if _local_name(node.tag) == "manifest"), None)
            if manifest is not None:
                for item in manifest:
                    if item.attrib.get("id") == cover_id:
                        href = urllib.parse.unquote(item.attrib.get("href", ""))
                        metadata.warnings.append(f"embedded cover: {Path(opf_name).parent / href}")
                        break
    return metadata


def _extract_pdf(path: Path, metadata: BookMetadata) -> BookMetadata:
    try:
        from pypdf import PdfReader
    except ImportError:
        metadata.warnings.append("pypdf is not installed; using filename metadata")
        return metadata
    reader = PdfReader(str(path))
    info = reader.metadata or {}
    metadata.title = _clean(info.get("/Title")) or metadata.title
    metadata.authors = _as_list(info.get("/Author")) or metadata.authors
    subject = _clean(info.get("/Subject"))
    keywords = _as_list(info.get("/Keywords"))
    if subject:
        metadata.description = subject
    metadata.genres = keywords
    metadata.isbn = canonical_isbn(info.get("/ISBN")) or canonical_isbn(" ".join(keywords))
    return metadata


def extract_book_metadata(path: str | os.PathLike[str]) -> BookMetadata:
    """Extract local metadata from an ebook without making network calls."""
    book_path = Path(path).expanduser()
    metadata = _filename_fallback(book_path)
    suffix = book_path.suffix.casefold()
    try:
        if suffix == ".epub":
            _extract_epub(book_path, metadata)
        elif suffix == ".pdf":
            _extract_pdf(book_path, metadata)
    except (BookMetadataError, OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        metadata.warnings.append(f"local metadata unavailable: {exc}")
    if not metadata.isbn:
        metadata.isbn = canonical_isbn(book_path.name)
    metadata.authors = list(dict.fromkeys(author for author in metadata.authors if author))
    metadata.genres = list(dict.fromkeys(metadata.genres))
    return metadata


def iter_book_files(source: str | os.PathLike[str]) -> Iterable[Path]:
    """Yield supported ebook files recursively in deterministic order."""
    root = Path(source).expanduser()
    if root.is_file():
        if root.suffix.casefold() in BOOK_EXTENSIONS:
            yield root
        return
    if not root.is_dir():
        return
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            directory
            for directory in dirs
            if not directory.startswith(".") and directory.casefold() != ".unifile"
        )
        for filename in sorted(files, key=str.casefold):
            path = Path(current) / filename
            if path.suffix.casefold() in BOOK_EXTENSIONS:
                yield path


def _url_with_params(endpoint: str, params: dict[str, Any]) -> str:
    return f"{endpoint}?{urllib.parse.urlencode(params, doseq=True)}"


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class BookMetadataClient:
    """Low-volume, cached OpenLibrary-first metadata client."""

    def __init__(
        self,
        cache_path: str | os.PathLike[str] | None = None,
        *,
        timeout: float = 10.0,
        min_interval: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: Callable[..., Any] | None = None,
        cache_ttl: float = 30 * 86400,
    ):
        self.cache_path = Path(cache_path) if cache_path else None
        self.timeout = timeout
        self.min_interval = max(0.0, min_interval)
        self.user_agent = user_agent
        self.transport = transport
        self.cache_ttl = cache_ttl
        self._last_request = 0.0
        self._cache = self._load_cache()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path:
            return {}
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            temp.write_text(json.dumps(self._cache, indent=2, ensure_ascii=False), encoding="utf-8")
            temp.replace(self.cache_path)
        except OSError:
            pass

    def _call_transport(self, url: str, *, binary: bool = False) -> Any:
        if self.transport is not None:
            try:
                return self.transport(url, {"User-Agent": self.user_agent}, self.timeout)
            except TypeError:
                return self.transport(url)
        headers = {"User-Agent": self.user_agent}
        if binary:
            return request_bytes(
                url,
                headers=headers,
                timeout=self.timeout,
                provider="books",
            ).content
        return request_json(
            url,
            headers=headers,
            timeout=self.timeout,
            provider="books",
        )

    def request_json(self, url: str) -> dict[str, Any]:
        now = time.time()
        cached = self._cache.get(_cache_key(url))
        if cached and now - float(cached.get("fetched_at", 0)) < self.cache_ttl:
            payload = cached.get("payload")
            if isinstance(payload, dict):
                return payload
        wait = self.min_interval - (now - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()
        payload = self._call_transport(url)
        if isinstance(payload, bytes):
            payload = json.loads(payload.decode("utf-8"))
        if not isinstance(payload, dict):
            raise BookMetadataError(f"metadata service returned {type(payload).__name__}")
        self._cache[_cache_key(url)] = {"fetched_at": time.time(), "payload": payload}
        self._save_cache()
        return payload

    def request_bytes(self, url: str) -> bytes:
        wait = self.min_interval - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()
        payload = self._call_transport(url, binary=True)
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, bytearray):
            return bytes(payload)
        raise BookMetadataError("cover service returned a non-binary response")

    def lookup(self, metadata: BookMetadata, providers: tuple[str, ...] = ("openlibrary", "googlebooks")) -> BookMetadata:
        """Fill missing local fields from the selected providers."""
        result = metadata
        for provider in providers:
            try:
                candidate = self._lookup_openlibrary(result) if provider == "openlibrary" else self._lookup_google_books(result)
            except (BookMetadataError, OSError, ValueError, json.JSONDecodeError):
                continue
            if candidate is None:
                continue
            result = _merge_metadata(result, candidate)
            if result.title and result.authors and result.description and result.cover_url:
                break
        return result

    def _lookup_openlibrary(self, metadata: BookMetadata) -> BookMetadata | None:
        params: dict[str, Any] = {"limit": 1, "fields": _OPENLIBRARY_FIELDS}
        if metadata.isbn:
            params["isbn"] = metadata.isbn
        else:
            params["title"] = metadata.title
            if metadata.authors:
                params["author"] = metadata.authors[0]
        payload = self.request_json(_url_with_params(OPENLIBRARY_SEARCH_URL, params))
        docs = payload.get("docs") or []
        if not docs or not isinstance(docs[0], dict):
            return None
        doc = docs[0]
        isbn = next((canonical_isbn(value) for key in ("isbn13", "isbn", "isbn10") for value in _as_list(doc.get(key)) if canonical_isbn(value)), None)
        languages = _as_list(doc.get("language"))
        subjects = _as_list(doc.get("subject")) + _as_list(doc.get("subject_key"))
        first_sentence = _first(doc.get("first_sentence")) or _first(doc.get("description"))
        source_key = _clean(doc.get("key"))
        description = first_sentence
        if not description and source_key.startswith("/works/"):
            try:
                work = self.request_json(f"https://openlibrary.org{source_key}.json")
                description = _first(work.get("description"))
                subjects.extend(_as_list(work.get("subjects")))
            except (BookMetadataError, OSError, ValueError, json.JSONDecodeError):
                pass
        cover_id = _first(doc.get("cover_i"))
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg?default=false" if cover_id else None
        return BookMetadata(
            path=metadata.path,
            title=_first(doc.get("title")),
            authors=_as_list(doc.get("author_name")),
            isbn=isbn,
            language=languages[0] if languages else None,
            genres=list(dict.fromkeys(subjects)),
            description=description or None,
            publisher=_first(doc.get("publisher")) or None,
            published=_first(doc.get("publish_date")) or (str(doc.get("first_publish_year")) if doc.get("first_publish_year") else None),
            source_url=f"https://openlibrary.org{source_key}" if source_key else None,
            cover_url=cover_url,
            provider="openlibrary",
        )

    def _lookup_google_books(self, metadata: BookMetadata) -> BookMetadata | None:
        query = f"isbn:{metadata.isbn}" if metadata.isbn else f"intitle:{metadata.title}"
        payload = self.request_json(_url_with_params(GOOGLE_BOOKS_URL, {"q": query, "maxResults": 1}))
        items = payload.get("items") or []
        if not items or not isinstance(items[0], dict):
            return None
        info = items[0].get("volumeInfo") or {}
        identifiers = info.get("industryIdentifiers") or []
        isbn = next((canonical_isbn(item.get("identifier")) for item in identifiers if isinstance(item, dict) and canonical_isbn(item.get("identifier"))), None)
        image_links = info.get("imageLinks") or {}
        return BookMetadata(
            path=metadata.path,
            title=_first(info.get("title")),
            authors=_as_list(info.get("authors")),
            isbn=isbn,
            language=_first(info.get("language")) or None,
            genres=_as_list(info.get("categories")),
            description=_first(info.get("description")) or None,
            publisher=_first(info.get("publisher")) or None,
            published=_first(info.get("publishedDate")) or None,
            source_url=_first(info.get("canonicalVolumeLink")) or _first(info.get("infoLink")) or None,
            cover_url=_first(image_links.get("thumbnail")) or None,
            provider="googlebooks",
        )

    def download_cover(self, metadata: BookMetadata, destination: str | os.PathLike[str]) -> Path | None:
        if metadata.cover_path and metadata.cover_path.is_file():
            return metadata.cover_path
        if not metadata.cover_url:
            return None
        payload = self.request_bytes(metadata.cover_url)
        if not payload or len(payload) > 10 * 1024 * 1024:
            raise BookMetadataError("cover response is empty or exceeds the 10 MiB safety limit")
        content_type = mimetypes.guess_type(urllib.parse.urlparse(metadata.cover_url).path)[0] or "image/jpeg"
        extension = ".jpg" if content_type == "image/jpeg" else (mimetypes.guess_extension(content_type) or ".img")
        target_dir = Path(destination)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{hashlib.sha256(metadata.cover_url.encode('utf-8')).hexdigest()[:32]}{extension}"
        if not target.exists():
            target.write_bytes(payload)
        metadata.cover_path = target
        return target


def _merge_metadata(base: BookMetadata, candidate: BookMetadata) -> BookMetadata:
    title_is_filename = not base.title or base.title.casefold() == base.path.stem.replace("_", " ").casefold()
    return replace(
        base,
        title=candidate.title if candidate.title and title_is_filename else base.title,
        authors=base.authors or candidate.authors,
        isbn=base.isbn or candidate.isbn,
        language=base.language or candidate.language,
        genres=list(dict.fromkeys([*base.genres, *candidate.genres])),
        series=base.series or candidate.series,
        series_index=base.series_index or candidate.series_index,
        description=base.description or candidate.description,
        publisher=base.publisher or candidate.publisher,
        published=base.published or candidate.published,
        source_url=base.source_url or candidate.source_url,
        cover_url=base.cover_url or candidate.cover_url,
        provider=base.provider or candidate.provider,
        warnings=list(dict.fromkeys([*base.warnings, *candidate.warnings])),
    )


def _tag_slug(value: str) -> str:
    slug = re.sub(r"[^\w]+", "-", _clean(value).casefold(), flags=re.UNICODE).strip("-")
    return slug[:80]


def book_tag_names(metadata: BookMetadata) -> list[str]:
    tags = [BOOK_TAG]
    tags.extend(f"genre:{_tag_slug(genre)}" for genre in metadata.genres if _tag_slug(genre))
    if metadata.language and _tag_slug(metadata.language):
        tags.append(f"language:{_tag_slug(metadata.language)}")
    if metadata.series and _tag_slug(metadata.series):
        tags.append(f"series:{_tag_slug(metadata.series)}")
    status = _tag_slug(metadata.reading_status or "unread") or "unread"
    tags.append(f"reading:{status}")
    return list(dict.fromkeys(tags))


def apply_book_metadata(
    library: TagLibrary,
    metadata: BookMetadata,
    *,
    overwrite: bool = False,
) -> bool:
    """Add one book to an open library and apply its fields and semantic tags."""
    if not library.is_open:
        return False
    entry = library.add_entry(str(metadata.path))
    if entry is None:
        return False
    existing_fields = library.get_entry_fields(entry.id)
    values = {
        "title": metadata.title,
        "author": "; ".join(metadata.authors),
        "isbn": metadata.isbn or "",
        "language": metadata.language or "",
        "genre": "; ".join(metadata.genres),
        "series": metadata.series or "",
        "series_index": metadata.series_index or "",
        "description": metadata.description or "",
        "publisher": metadata.publisher or "",
        "published": metadata.published or "",
        "source": metadata.source_url or "",
        "cover_url": metadata.cover_url or "",
        "cover_path": str(metadata.cover_path) if metadata.cover_path else "",
        "reading_status": metadata.reading_status or "unread",
    }
    for key, value in values.items():
        if value and (overwrite or not existing_fields.get(key)):
            library.set_entry_field(entry.id, key, value)
    tags = [library.add_tag(name) for name in book_tag_names(metadata)]
    library.add_tags_to_entry(entry.id, [tag.id for tag in tags if tag is not None])
    return True


def scan_book_library(
    source: str | os.PathLike[str],
    *,
    target_library: str | os.PathLike[str] | None = None,
    lookup: bool = False,
    download_covers: bool = False,
    providers: tuple[str, ...] = ("openlibrary", "googlebooks"),
    client: BookMetadataClient | None = None,
) -> BookScanResult:
    """Scan ebooks and optionally enrich/apply them to a UniFile tag library."""
    source_path = Path(source).expanduser()
    target_path = Path(target_library).expanduser() if target_library else None
    result = BookScanResult(str(source_path), str(target_path) if target_path else None)
    if not source_path.exists():
        result.errors.append(f"source does not exist: {source_path}")
        return result
    if lookup and client is None:
        cache_root = target_path or (source_path if source_path.is_dir() else source_path.parent)
        client = BookMetadataClient(cache_root / ".unifile" / BOOK_CACHE_NAME)
    library = TagLibrary(str(target_path)) if target_path else None
    if library and not library.open():
        result.errors.append(f"could not open UniFile library: {target_path}")
        return result
    try:
        cover_root = (target_path or (source_path if source_path.is_dir() else source_path.parent)) / ".unifile" / BOOK_COVER_DIR
        for path in iter_book_files(source_path):
            try:
                metadata = extract_book_metadata(path)
                if lookup and client:
                    metadata = client.lookup(metadata, providers)
                    result.looked_up += 1
                if download_covers and client and metadata.cover_url:
                    try:
                        if client.download_cover(metadata, cover_root):
                            result.covers_downloaded += 1
                    except (BookMetadataError, OSError) as exc:
                        metadata.warnings.append(f"cover download failed: {exc}")
                result.books.append(metadata)
                if library and apply_book_metadata(library, metadata):
                    result.applied += 1
            except (OSError, ValueError, BookMetadataError) as exc:
                result.errors.append(f"{path}: {exc}")
    finally:
        if library:
            library.close()
    return result


def _safe_output_name(value: str) -> str:
    value = _BAD_FILENAME_CHARS.sub("_", _clean(value)).strip(" .")
    return (value or "book")[:100]


def _split_field(value: str) -> list[str]:
    return [item for item in (_clean(part) for part in re.split(r"[;|]\s*", value or "")) if item]


def _all_library_entries(library: TagLibrary) -> list[Any]:
    entries: list[Any] = []
    offset = 0
    while True:
        batch = library.get_all_entries(limit=1000, offset=offset)
        entries.extend(batch)
        if len(batch) < 1000:
            return entries
        offset += len(batch)


def _opf_for_entry(entry: Any, fields: dict[str, str], cover_name: str | None = None) -> ET.Element:
    dc_ns = "http://purl.org/dc/elements/1.1/"
    opf_ns = "http://www.idpf.org/2007/opf"
    package = ET.Element(
        f"{{{opf_ns}}}package",
        {
            "version": "2.0",
            "unique-identifier": "unifile-id",
        },
    )
    metadata = ET.SubElement(package, f"{{{opf_ns}}}metadata")
    def dc(name: str, value: str, **attributes: str) -> None:
        if value:
            ET.SubElement(metadata, f"{{{dc_ns}}}{name}", attributes).text = value

    title = fields.get("title") or Path(entry.path).stem
    dc("title", title)
    authors = _split_field(fields.get("author", ""))
    for author in authors or ["Unknown"]:
        dc("creator", author, **{f"{{{opf_ns}}}role": "aut"})
    language = fields.get("language", "") or "und"
    dc("language", language)
    isbn = canonical_isbn(fields.get("isbn"))
    if isbn:
        dc("identifier", isbn, id="isbn", **{f"{{{opf_ns}}}scheme": "ISBN"})
    stable_id = uuid.uuid5(uuid.NAMESPACE_URL, str(entry.path))
    dc("identifier", f"urn:uuid:{stable_id}", id="unifile-id")
    for genre in _split_field(fields.get("genre", "")):
        dc("subject", genre)
    dc("description", fields.get("description", ""))
    dc("publisher", fields.get("publisher", ""))
    dc("date", fields.get("published", ""))
    if fields.get("series"):
        ET.SubElement(metadata, "meta", {"name": "calibre:series", "content": fields["series"]})
    if fields.get("series_index"):
        ET.SubElement(metadata, "meta", {"name": "calibre:series_index", "content": fields["series_index"]})
    tags = list(entry.tag_names)
    if tags:
        ET.SubElement(metadata, "meta", {"name": "calibre:tags", "content": ", ".join(tags)})
    ET.SubElement(metadata, "meta", {"name": "unifile:source_path", "content": str(entry.path)})
    if fields.get("reading_status"):
        ET.SubElement(metadata, "meta", {"name": "unifile:reading_status", "content": fields["reading_status"]})
    if fields.get("source"):
        ET.SubElement(metadata, "meta", {"name": "unifile:source_url", "content": fields["source"]})
    if fields.get("cover_url"):
        ET.SubElement(metadata, "meta", {"name": "unifile:cover_url", "content": fields["cover_url"]})
    if cover_name:
        ET.SubElement(metadata, "meta", {"name": "cover", "content": "cover"})
        manifest = ET.SubElement(package, f"{{{opf_ns}}}manifest")
        ET.SubElement(manifest, "item", {"id": "cover", "href": cover_name, "media-type": "image/jpeg"})
        ET.SubElement(package, f"{{{opf_ns}}}spine", {"toc": "nc"})
    return package


def export_calibre_opf(
    library_root: str | os.PathLike[str],
    output: str | os.PathLike[str] | None = None,
    *,
    overwrite: bool = True,
) -> BookExportResult:
    """Export book entries as Calibre-compatible ``metadata.opf`` files."""
    library_path = Path(library_root).expanduser()
    output_path = Path(output).expanduser() if output else library_path / ".unifile" / "calibre-opf"
    result = BookExportResult(str(library_path), str(output_path))
    library = TagLibrary(str(library_path))
    if not library.open():
        result.errors.append(f"could not open UniFile library: {library_path}")
        return result
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        for entry in _all_library_entries(library):
            if f".{entry.suffix.casefold()}" not in BOOK_EXTENSIONS:
                continue
            fields = library.get_entry_fields(entry.id)
            folder_name = _safe_output_name(fields.get("title") or Path(entry.path).stem)
            folder_name += "-" + hashlib.sha1(str(entry.path).encode("utf-8")).hexdigest()[:8]
            book_dir = output_path / folder_name
            opf_path = book_dir / "metadata.opf"
            if opf_path.exists() and not overwrite:
                result.skipped += 1
                continue
            try:
                book_dir.mkdir(parents=True, exist_ok=True)
                cover_name = None
                cover_source = Path(fields.get("cover_path", "")) if fields.get("cover_path") else None
                if cover_source and cover_source.is_file():
                    suffix = cover_source.suffix.lower() or ".jpg"
                    cover_name = f"cover{suffix}"
                    shutil.copy2(cover_source, book_dir / cover_name)
                    result.covers_copied += 1
                package = _opf_for_entry(entry, fields, cover_name)
                ET.register_namespace("", "http://www.idpf.org/2007/opf")
                ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
                ET.register_namespace("opf", "http://www.idpf.org/2007/opf")
                ET.ElementTree(package).write(opf_path, encoding="utf-8", xml_declaration=True)
                result.exported += 1
                result.files.append(str(opf_path))
            except (OSError, ValueError, TypeError) as exc:
                result.errors.append(f"{entry.path}: {exc}")
    finally:
        library.close()
    return result


__all__ = [
    "BOOK_EXTENSIONS",
    "BookExportResult",
    "BookMetadata",
    "BookMetadataClient",
    "BookMetadataError",
    "BookScanResult",
    "apply_book_metadata",
    "book_tag_names",
    "canonical_isbn",
    "export_calibre_opf",
    "extract_book_metadata",
    "iter_book_files",
    "scan_book_library",
]
