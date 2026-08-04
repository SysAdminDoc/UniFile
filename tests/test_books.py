"""Book-library extraction, lookup, tagging, and OPF export coverage."""

import json
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

from unifile.books import (
    BookMetadataClient,
    canonical_isbn,
    export_calibre_opf,
    extract_book_metadata,
    scan_book_library,
)
from unifile.classifier import _SCAN_FILTERS
from unifile.profiles import get_profile_names
from unifile.tagging.library import TagLibrary


def _make_epub(path, *, title="Local Book", author="Local Author", description="A local synopsis."):
    path.parent.mkdir(parents=True, exist_ok=True)
    container = """<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
    <package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf" version="2.0">
      <metadata>
        <dc:title>{title}</dc:title>
        <dc:creator>{author}</dc:creator>
        <dc:identifier opf:scheme="ISBN">urn:isbn:978-0-452-28423-4</dc:identifier>
        <dc:language>en</dc:language>
        <dc:subject>Science Fiction</dc:subject>
        <dc:description>{description}</dc:description>
        <dc:publisher>Local Press</dc:publisher>
        <dc:date>2025-01-02</dc:date>
        <meta name="calibre:series" content="Local Series" />
        <meta name="calibre:series_index" content="2" />
      </metadata>
    </package>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
    return path


def test_canonical_isbn_and_epub_metadata(tmp_path):
    epub = _make_epub(tmp_path / "book.epub")

    metadata = extract_book_metadata(epub)

    assert canonical_isbn("ISBN 978-0-452-28423-4") == "9780452284234"
    assert metadata.title == "Local Book"
    assert metadata.authors == ["Local Author"]
    assert metadata.isbn == "9780452284234"
    assert metadata.language == "en"
    assert metadata.genres == ["Science Fiction"]
    assert metadata.series == "Local Series"
    assert metadata.series_index == "2"


def test_lookup_uses_openlibrary_and_downloads_cached_cover(tmp_path):
    epub = _make_epub(tmp_path / "book.epub", title="Book", description="")
    calls = []

    def transport(url, *_args):
        calls.append(url)
        if "covers.openlibrary.org" in url:
            return b"fake-cover"
        return {
            "docs": [
                {
                    "title": "Remote Book",
                    "author_name": ["Remote Author"],
                    "isbn13": ["9780452284234"],
                    "language": ["eng"],
                    "subject": ["Fantasy"],
                    "first_sentence": ["A remote synopsis."],
                    "publisher": ["Remote Press"],
                    "cover_i": 123,
                    "key": "/works/OL123W",
                }
            ]
        }

    metadata = extract_book_metadata(epub)
    client = BookMetadataClient(min_interval=0, transport=transport)
    enriched = client.lookup(metadata)
    cover = client.download_cover(enriched, tmp_path / "covers")

    assert enriched.title == "Remote Book"
    assert enriched.authors == ["Local Author"]
    assert enriched.description == "A remote synopsis."
    assert enriched.genres == ["Science Fiction", "Fantasy"]
    assert enriched.cover_url.endswith("123-L.jpg?default=false")
    assert cover is not None and cover.read_bytes() == b"fake-cover"
    assert any("search.json" in url for url in calls)


def test_book_scan_applies_fields_and_semantic_tags(tmp_path):
    source = tmp_path / "ebooks"
    epub = _make_epub(source / "book.epub")
    target = tmp_path / "library"

    result = scan_book_library(source, target_library=target)

    assert result.applied == 1
    assert result.books[0].path == epub
    library = TagLibrary(str(target))
    assert library.open()
    try:
        entry = library.get_entry_by_path(str(epub))
        assert entry is not None
        fields = library.get_entry_fields(entry.id)
        assert fields["title"] == "Local Book"
        assert fields["isbn"] == "9780452284234"
        assert fields["reading_status"] == "unread"
        assert {"book", "genre:science-fiction", "language:en", "series:local-series", "reading:unread"}.issubset(
            set(entry.tag_names)
        )
    finally:
        library.close()


def test_calibre_opf_export_is_deterministic_and_non_destructive(tmp_path):
    source = tmp_path / "ebooks"
    epub = _make_epub(source / "book.epub")
    target = tmp_path / "library"
    scan_book_library(source, target_library=target)
    before = epub.read_bytes()
    output = tmp_path / "calibre"

    result = export_calibre_opf(target, output)

    assert result.exported == 1
    assert epub.read_bytes() == before
    opf_path = next(output.rglob("metadata.opf"))
    root = ET.parse(opf_path).getroot()
    dc_ns = "http://purl.org/dc/elements/1.1/"
    assert root.find(f".//{{{dc_ns}}}title").text == "Local Book"
    assert root.find(f".//{{{dc_ns}}}identifier").text == "9780452284234"
    metadata_names = {node.attrib.get("name") for node in root.iter("meta")}
    assert "calibre:series" in metadata_names
    assert "unifile:reading_status" in metadata_names


def test_books_cli_and_profile_are_available(tmp_path):
    source = tmp_path / "ebooks"
    _make_epub(source / "book.epub")
    command = subprocess.run(
        [sys.executable, "-m", "unifile", "books", "scan", str(source), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert command.returncode == 0, command.stderr
    assert json.loads(command.stdout)["count"] == 1
    assert "Book Library" in get_profile_names()
    assert _SCAN_FILTERS["Books Only"] == {".epub", ".pdf", ".mobi", ".azw3"}
