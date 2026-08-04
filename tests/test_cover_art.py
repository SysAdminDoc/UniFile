import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from unifile.media.cover_art import (
    CoverArtAsset,
    cover_art_status,
    download_cover_art,
    embed_cover_art,
    undo_cover_art_write,
)


def _jpeg_bytes():
    image = pytest.importorskip("PIL.Image")
    output = BytesIO()
    image.new("RGB", (8, 8), "#3478c8").save(output, format="JPEG")
    return output.getvalue()


def _write_tagged_mp3(path: Path):
    id3 = pytest.importorskip("mutagen.id3")
    tags = id3.ID3()
    tags.add(id3.TIT2(encoding=3, text=["Demo track"]))
    tags.save(path)


def test_download_cover_art_validates_and_reuses_cache(tmp_path):
    payload = _jpeg_bytes()

    class Response:
        status_code = 200
        headers = {"Content-Type": "image/jpeg", "Content-Length": str(len(payload))}
        content = payload

        def iter_content(self, chunk_size):
            assert chunk_size == 64 * 1024
            return [payload[:10], payload[10:]]

        def close(self):
            pass

    class Session:
        def __init__(self):
            self.calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            assert url == "https://covers.example.test/front.jpg"
            assert kwargs["stream"] is True
            return Response()

    session = Session()
    first = download_cover_art(
        "https://covers.example.test/front.jpg",
        cache_dir=tmp_path / "cache",
        session=session,
    )
    assert isinstance(first, CoverArtAsset)
    assert first.mime_type == "image/jpeg"
    assert Path(first.cache_path).is_file()

    class NoNetwork:
        def get(self, *_args, **_kwargs):
            raise AssertionError("cache should avoid a second request")

    second = download_cover_art(
        first.source_url, cache_dir=tmp_path / "cache", session=NoNetwork()
    )
    assert second.data == first.data
    assert session.calls == 1


def test_mp3_cover_art_is_embedded_atomically_and_restored(tmp_path):
    filepath = tmp_path / "track.mp3"
    _write_tagged_mp3(filepath)
    original = filepath.read_bytes()
    assert not cover_art_status(str(filepath)).has_artwork

    result = embed_cover_art(
        str(filepath), _jpeg_bytes(), "image/jpeg",
        source_url="https://covers.example.test/front.jpg",
        backup_dir=tmp_path / "backups",
    )
    assert result.success, result.message
    assert Path(result.backup_path).is_file()
    assert cover_art_status(str(filepath)).has_artwork

    skipped = embed_cover_art(str(filepath), _jpeg_bytes(), "image/jpeg")
    assert skipped.skipped
    assert undo_cover_art_write(str(filepath), result.backup_path)
    assert filepath.read_bytes() == original
    assert not cover_art_status(str(filepath)).has_artwork


def test_epub_cover_art_updates_manifest_and_undoes(tmp_path):
    filepath = tmp_path / "book.epub"
    container = b'''<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    opf = b'''<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Demo</dc:title></metadata><manifest/><spine/></package>'''
    with zipfile.ZipFile(filepath, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
    original = filepath.read_bytes()
    assert not cover_art_status(str(filepath)).has_artwork

    result = embed_cover_art(
        str(filepath), _jpeg_bytes(), "image/jpeg", backup_dir=tmp_path / "backups"
    )
    assert result.success, result.message
    assert cover_art_status(str(filepath)).has_artwork
    with zipfile.ZipFile(filepath) as archive:
        names = set(archive.namelist())
        assert "OEBPS/images/unifile-cover.jpg" in names
        assert b"unifile-cover-art" in archive.read("OEBPS/content.opf")

    assert undo_cover_art_write(str(filepath), result.backup_path)
    assert filepath.read_bytes() == original
