"""Coverage for the unified movie, TV, book, audiobook, and audio lookup flow."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unifile.media import providers


def test_parse_media_filename_preserves_book_audiobook_and_audio_types():
    assert providers.parse_media_filename("Dune.epub")["type"] is providers.MediaType.BOOK
    assert providers.parse_media_filename("Dune.m4b")["type"] is providers.MediaType.AUDIOBOOK
    assert providers.parse_media_filename("Dune audiobook.mp3")["type"] is providers.MediaType.AUDIO


def test_search_media_uses_deterministic_tv_and_book_fallbacks(monkeypatch):
    monkeypatch.setattr(providers, "tvdb_search_shows", lambda *args, **kwargs: [])
    monkeypatch.setattr(providers, "tmdb_search_shows", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        providers,
        "tvmaze_search_shows",
        lambda *args, **kwargs: [{"id": 42, "name": "Fallback Show", "genres": ["Drama"]}],
    )
    tv_results = providers.search_media("Fallback Show", media_type=providers.MediaType.EPISODE)
    assert len(tv_results) == 1
    assert tv_results[0].provider == "tvmaze"
    assert tv_results[0].id_tvmaze == "42"

    monkeypatch.setattr(providers, "openlibrary_search_books", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        providers,
        "googlebooks_search_books",
        lambda *args, **kwargs: [providers.BookResult(title="Fallback Book", provider="googlebooks")],
    )
    book_results = providers.search_media("Fallback Book", media_type=providers.MediaType.BOOK)
    assert [result.title for result in book_results] == ["Fallback Book"]
    assert book_results[0].provider == "googlebooks"


def test_tvdb_login_and_search_use_bearer_contract(monkeypatch):
    providers._TVDB_TOKEN = ""
    providers._TVDB_TOKEN_KEY = ""
    monkeypatch.setattr(
        providers,
        "get_media_api_key",
        lambda name: {"tvdb": "tvdb-key", "tvdb_pin": "1234"}.get(name, ""),
    )
    post_calls = []

    def fake_post(url, payload, headers=None):
        post_calls.append((url, payload, headers))
        return {"data": {"token": "access-token"}}

    def fake_get(url, params=None, headers=None):
        assert url == f"{providers.TVDB_BASE}/search"
        assert params["query"] == "The Expanse"
        assert headers == {"Authorization": "Bearer access-token"}
        return {"data": [{"id": "123", "name": "The Expanse", "year": 2015}]}

    monkeypatch.setattr(providers, "_post_json", fake_post)
    monkeypatch.setattr(providers, "_get_json", fake_get)

    results = providers.tvdb_search_shows("The Expanse", year="2015")
    assert post_calls == [
        (f"{providers.TVDB_BASE}/login", {"apikey": "tvdb-key", "pin": "1234"}, None)
    ]
    assert results[0].series == "The Expanse"
    assert results[0].id_tvdb == "123"
    assert results[0].year == "2015"

    providers._TVDB_TOKEN = ""
    providers._TVDB_TOKEN_KEY = ""


def test_musicbrainz_search_sets_json_and_identifying_user_agent(monkeypatch):
    providers._MUSICBRAINZ_LAST_REQUEST = 0.0
    captured = {}

    def fake_get(url, params=None, headers=None):
        captured.update(url=url, params=params, headers=headers)
        return {
            "recordings": [
                {
                    "id": "recording-1",
                    "title": "Come Together",
                    "artist-credit": [{"name": "The Beatles"}],
                    "first-release-date": "1969-09-26",
                    "releases": [{"id": "release-1", "title": "Abbey Road"}],
                }
            ]
        }

    monkeypatch.setattr(providers, "_get_json", fake_get)
    results = providers.musicbrainz_search_recordings("Come Together", year="1969")

    assert captured["url"] == f"{providers.MUSICBRAINZ_BASE}/recording"
    assert captured["params"]["fmt"] == "json"
    assert captured["params"]["inc"] == "artists+releases"
    assert captured["headers"]["User-Agent"].startswith("UniFile/")
    assert results[0].artist == "The Beatles"
    assert results[0].album == "Abbey Road"
    assert results[0].id_musicbrainz == "recording-1"


def test_openlibrary_search_normalizes_book_metadata(monkeypatch):
    def fake_get(url, params=None, headers=None):
        assert url == providers.OPENLIBRARY_SEARCH
        return {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Dune",
                    "author_name": ["Frank Herbert"],
                    "first_publish_year": 1965,
                    "isbn": ["0441172717"],
                    "language": ["eng"],
                    "subject": ["Science Fiction"],
                    "cover_i": 123,
                }
            ]
        }

    monkeypatch.setattr(providers, "_get_json", fake_get)
    result = providers.openlibrary_search_books("Dune")[0]
    assert result.title == "Dune"
    assert result.authors == ["Frank Herbert"]
    assert result.year == "1965"
    assert result.isbn == "0441172717"
    assert result.cover_url.endswith("123-L.jpg?default=false")


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([sys.argv[0], "-platform", "offscreen"])
    return app


def test_media_lookup_panel_exposes_all_catalogs_and_builds_payload(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_MEDIA_KEYS_FILE", str(tmp_path / "media_api_keys.json"))
    panel_module = __import__("unifile.dialogs.media_lookup", fromlist=["MediaLookupPanel"])
    panel = panel_module.MediaLookupPanel()

    assert [panel.cmb_type.itemText(index) for index in range(panel.cmb_type.count())] == [
        "Movie", "TV Show", "Book", "Audiobook", "Audio"
    ]
    assert panel.txt_tvdb_key.accessibleName() == "TVDB API key"
    assert panel.txt_tvdb_pin.accessibleName() == "TVDB subscriber PIN"
    assert panel.txt_opensubtitles_key.accessibleName() == "OpenSubtitles API key"
    assert panel.btn_save_chapters.accessibleName() == "Save TMDb chapter sidecar"
    assert panel.btn_embed_cover.accessibleName() == "Fetch and embed cover artwork"
    assert panel.btn_save_nfo.accessibleName() == "Save Kodi and Plex NFO sidecar"

    panel._set_media_type(providers.MediaType.AUDIOBOOK)
    book = providers.BookResult(
        title="Dune",
        authors=["Frank Herbert"],
        isbn="0441172717",
        provider="openlibrary",
    )
    panel._on_search_results([book])
    assert panel.tbl_results.item(0, 2).text() == "Audiobook"
    panel._on_detail_ready(book)
    assert panel._build_metadata_dict()["media_type"] == "audiobook"
    assert panel._build_metadata_dict()["author"] == "Frank Herbert"

    panel._set_media_type(providers.MediaType.AUDIO)
    audio = providers.AudioResult(
        title="Come Together", artist="The Beatles", id_musicbrainz="recording-1",
        cover_url="https://covers.example.test/front.jpg",
    )
    panel._on_detail_ready(audio)
    payload = panel._build_metadata_dict()
    assert payload["media_type"] == "audio"
    assert payload["artist"] == "The Beatles"
    audio_path = tmp_path / "track.mp3"
    from mutagen.id3 import ID3
    ID3().save(audio_path)
    panel.txt_media_file.setText(str(audio_path))
    panel._update_cover_art_action()
    panel._update_nfo_action()
    assert panel.btn_embed_cover.isEnabled()
    assert panel.btn_save_nfo.isEnabled()
    panel._on_save_nfo()
    assert (tmp_path / "track.nfo").exists()
    panel.deleteLater()
    qapp.processEvents()


def test_media_lookup_saves_tmdb_chapter_sidecar(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_MEDIA_KEYS_FILE", str(tmp_path / "media_api_keys.json"))
    panel_module = __import__("unifile.dialogs.media_lookup", fromlist=["MediaLookupPanel"])
    panel = panel_module.MediaLookupPanel()
    source = tmp_path / "Show.S01E02.mkv"
    source.write_bytes(b"media")
    panel.txt_media_file.setText(str(source))
    panel._current_detail = providers.EpisodeResult(
        series="Show", season=1, episode=2, title="Pilot", id_tmdb="77"
    )

    panel._on_save_chapters()

    sidecar = tmp_path / "Show.S01E02.chapters.json"
    assert sidecar.exists()
    assert "Pilot" in sidecar.read_text(encoding="utf-8")
    panel.deleteLater()
    qapp.processEvents()
