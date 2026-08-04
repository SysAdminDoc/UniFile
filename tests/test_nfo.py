"""Coverage for Kodi/Plex NFO sidecar generation and the headless command."""

import json
from argparse import Namespace
from xml.etree import ElementTree as ET

from unifile.__main__ import _cmd_nfo_generate
from unifile.media.nfo import (
    build_nfo_xml,
    preview_nfo_sidecar,
    write_nfo_sidecar,
)


def test_movie_nfo_maps_provider_fields_and_unique_ids():
    root = ET.fromstring(build_nfo_xml({
        "title": "The Example",
        "year": "2026",
        "synopsis": "A useful test movie.",
        "genres": ["Drama", "Sci-Fi"],
        "poster_url": "https://image.example.test/poster.jpg",
        "id_tmdb": "123",
        "id_imdb": "tt0000123",
        "media_type": "movie",
    }))

    assert root.tag == "movie"
    assert root.findtext("title") == "The Example"
    assert [node.text for node in root.findall("genre")] == ["Drama", "Sci-Fi"]
    assert root.findtext("thumb") == "https://image.example.test/poster.jpg"
    ids = {node.attrib["type"]: node.text for node in root.findall("uniqueid")}
    assert ids == {"tmdb": "123", "imdb": "tt0000123"}
    assert root.find("uniqueid").attrib["default"] == "true"


def test_episode_nfo_uses_show_and_episode_fields():
    root = ET.fromstring(build_nfo_xml({
        "series": "Example Show",
        "title": "Pilot",
        "season": 2,
        "episode": 4,
        "date": "2026-08-03",
        "media_type": "episode",
    }))

    assert root.tag == "episodedetails"
    assert root.findtext("showtitle") == "Example Show"
    assert root.findtext("title") == "Pilot"
    assert root.findtext("season") == "2"
    assert root.findtext("episode") == "4"
    assert root.findtext("aired") == "2026-08-03"


def test_book_nfo_merges_tag_library_fields():
    root = ET.fromstring(build_nfo_xml({
        "fields": {
            "title": "Dune",
            "author": "Frank Herbert; Brian Herbert",
            "genre": "Science Fiction; Classic",
            "description": "A desert planet story.",
            "publisher": "Ace",
            "published": "1965",
            "isbn": "0441172717",
            "language": "eng",
            "series": "Dune",
            "source": "https://example.test/dune",
            "media_type": "book",
        }
    }))

    assert root.tag == "book"
    assert [node.text for node in root.findall("author")] == ["Frank Herbert", "Brian Herbert"]
    assert [node.text for node in root.findall("genre")] == ["Science Fiction", "Classic"]
    assert root.findtext("plot") == "A desert planet story."
    assert root.findtext("website") == "https://example.test/dune"
    assert root.findtext("isbn") == "0441172717"


def test_nfo_write_is_atomic_and_respects_no_overwrite(tmp_path):
    source = tmp_path / "Example Movie.mkv"
    source.write_bytes(b"media")
    metadata = {"title": "Example Movie", "media_type": "movie"}

    preview = preview_nfo_sidecar(source, metadata)
    assert preview.exists is False
    assert preview.changed is True
    assert "<title>Example Movie</title>" in preview.xml

    first = write_nfo_sidecar(source, metadata)
    assert first.written is True
    assert first.overwritten is False
    assert (tmp_path / "Example Movie.nfo").exists()

    skipped = write_nfo_sidecar(source, {"title": "Changed"}, overwrite=False)
    assert skipped.skipped is True
    assert skipped.written is False

    updated = write_nfo_sidecar(source, {"title": "Changed"})
    assert updated.overwritten is True
    assert "Changed" in (tmp_path / "Example Movie.nfo").read_text(encoding="utf-8")
    assert preview_nfo_sidecar(source, {"title": "Changed"}).changed is False


def test_nfo_cli_writes_json_metadata(tmp_path, capsys):
    source = tmp_path / "book.epub"
    source.write_bytes(b"ebook")
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({
        "fields": {"title": "Dune", "author": "Frank Herbert", "media_type": "book"}
    }), encoding="utf-8")

    result = _cmd_nfo_generate(Namespace(
        path=str(source),
        metadata_json=str(metadata_path),
        kind="auto",
        output=None,
        no_overwrite=False,
        json=True,
    ))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["written"] is True
    assert ET.parse(tmp_path / "book.nfo").getroot().tag == "book"
