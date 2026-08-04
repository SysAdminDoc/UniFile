"""Offline coverage for subtitle provider and TMDb chapter sidecars."""

import json

from unifile.media import subtitles
from unifile.media.providers import EpisodeResult


def _media_keys(monkeypatch, **overrides):
    values = {
        "opensubtitles": "api-key",
        "opensubtitles_username": "user",
        "opensubtitles_password": "password",
    }
    values.update(overrides)
    monkeypatch.setattr(subtitles, "get_media_api_key", lambda name: values.get(name, ""))


def test_opensubtitles_hash_is_stable_for_small_file(tmp_path):
    source = tmp_path / "sample.mkv"
    source.write_bytes(bytes(range(256)) * 3)

    first = subtitles.opensubtitles_hash(source)
    second = subtitles.opensubtitles_hash(source)

    assert first == second
    assert len(first) == 16
    assert all(char in "0123456789abcdef" for char in first)


def test_search_normalizes_and_filters_provider_results(tmp_path, monkeypatch):
    source = tmp_path / "Show.S01E02.mkv"
    source.write_bytes(b"media")
    _media_keys(monkeypatch)
    monkeypatch.setattr(subtitles, "_pace_requests", lambda: None)
    captured = {}

    def fake_get_json(url, params=None, headers=None):
        captured.update(params or {})
        return {
            "data": [
                {"id": "provider-1", "attributes": {
                    "language": "en", "language_name": "English", "format": "srt",
                    "files": [{"file_id": 41, "file_name": "subtitle.srt"}],
                    "moviehash_match": True, "download_count": 99,
                    "feature_details": {"title": "Show", "year": 2024},
                }},
                {"id": "provider-2", "attributes": {
                    "language": "en", "format": "vtt",
                    "files": [{"file_id": 42, "file_name": "subtitle.vtt"}],
                }},
            ]
        }

    monkeypatch.setattr(subtitles, "_get_json", fake_get_json)
    results = subtitles.search_opensubtitles(
        query="Show", media_path=source, season=1, episode=2,
        languages=["en"], formats=["srt"], limit=10,
    )

    assert len(results) == 1
    assert results[0].file_id == "41"
    assert results[0].moviehash_match is True
    assert captured["query"] == "Show"
    assert captured["season_number"] == 1
    assert captured["episode_number"] == 2
    assert captured["moviebytesize"] == source.stat().st_size


def test_download_writes_utf8_sidecar_and_uses_session_token(tmp_path, monkeypatch):
    _media_keys(monkeypatch)
    monkeypatch.setattr(subtitles, "_pace_requests", lambda: None)
    subtitles._token = ""
    subtitles._token_key = ""
    subtitles._base_url = subtitles.OPEN_SUBTITLES_BASE
    posted = []

    def fake_post_json(url, payload, headers=None):
        posted.append((url, payload, headers))
        if url.endswith("/login"):
            return {"token": "session-token", "base_url": "api.opensubtitles.com"}
        return {"link": "https://download.example/subtitle.srt"}

    class Response:
        content = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"

        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, headers=None, timeout=None):
            assert url == "https://download.example/subtitle.srt"
            assert headers["Authorization"] == "Bearer session-token"
            return Response()

    monkeypatch.setattr(subtitles, "_post_json", fake_post_json)
    monkeypatch.setattr(subtitles, "_get_session", lambda: Session())

    source = tmp_path / "Show.mkv"
    source.write_bytes(b"media")
    result = subtitles.SubtitleResult(file_id="41", language="en", format="srt")
    saved = subtitles.download_opensubtitle(result, source)

    assert saved.endswith("Show.en.srt")
    assert (tmp_path / "Show.en.srt").read_text(encoding="utf-8").startswith("1\n")
    assert posted[0][0].endswith("/login")
    assert posted[1][0].endswith("/download")
    assert posted[1][2]["Authorization"] == "Bearer session-token"


def test_tmdb_episode_chapters_write_reviewable_sidecar(tmp_path):
    source = tmp_path / "Show.S01E02.mkv"
    source.write_bytes(b"media")
    episodes = [EpisodeResult(
        series="Show", season=1, episode=2, title="Pilot",
        date="2024-01-02", synopsis="Opening episode", id_tmdb="77",
    )]

    chapters = subtitles.chapters_from_episodes(episodes)
    sidecar = subtitles.write_chapter_sidecar(source, chapters)
    payload = json.loads((tmp_path / "Show.S01E02.chapters.json").read_text(encoding="utf-8"))

    assert sidecar.endswith("Show.S01E02.chapters.json")
    assert payload["schema_version"] == subtitles.CHAPTER_SCHEMA_VERSION
    assert payload["source"] == "tmdb"
    assert payload["chapters"][0]["title"] == "Pilot"
    assert payload["chapters"][0]["season"] == 1
