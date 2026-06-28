from unifile.media import providers


def _isolate_key_store(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_MEDIA_KEYS_FILE", str(tmp_path / "media_api_keys.json"))
    monkeypatch.delenv("API_KEY_TMDB", raising=False)
    monkeypatch.delenv("API_KEY_OMDB", raising=False)
    providers.clear_media_provider_errors()


def test_media_api_key_env_overrides_saved_config(monkeypatch, tmp_path):
    _isolate_key_store(monkeypatch, tmp_path)
    assert providers.save_media_api_keys({"tmdb": "saved-tmdb", "omdb": "saved-omdb"})

    monkeypatch.setenv("API_KEY_TMDB", "env-tmdb")

    assert providers.get_media_api_key("tmdb") == "env-tmdb"
    assert providers.get_media_api_key("omdb") == "saved-omdb"
    statuses = providers.media_provider_statuses()
    assert statuses["tmdb"]["source"] == "environment"
    assert statuses["omdb"]["source"] == "settings"


def test_media_api_key_config_saves_only_supported_nonempty_keys(monkeypatch, tmp_path):
    _isolate_key_store(monkeypatch, tmp_path)

    assert providers.save_media_api_keys({"tmdb": "  cfg-tmdb  ", "omdb": "", "other": "ignored"})

    assert providers.load_media_api_keys() == {"tmdb": "cfg-tmdb"}
    statuses = providers.media_provider_statuses()
    assert statuses["tmdb"]["configured"] is True
    assert statuses["omdb"]["configured"] is False
    assert statuses["tvmaze"]["configured"] is True
    assert statuses["tvmaze"]["requires_key"] is False


def test_tmdb_missing_key_short_circuits_without_http(monkeypatch, tmp_path):
    _isolate_key_store(monkeypatch, tmp_path)
    calls = []

    def fake_get_json(*args, **kwargs):
        calls.append((args, kwargs))
        return {}

    monkeypatch.setattr(providers, "_get_json", fake_get_json)

    assert providers.tmdb_search_movies("Arrival") == []
    assert calls == []
    assert providers.media_provider_statuses()["tmdb"]["last_error"] == "Missing TMDb API key."


def test_omdb_invalid_key_error_is_visible(monkeypatch, tmp_path):
    _isolate_key_store(monkeypatch, tmp_path)
    monkeypatch.setenv("API_KEY_OMDB", "bad-key")

    def fake_get_json(url, params=None, headers=None):
        assert url == providers.OMDB_BASE
        assert params["apikey"] == "bad-key"
        return {"Response": "False", "Error": "Invalid API key!"}

    monkeypatch.setattr(providers, "_get_json", fake_get_json)

    assert providers.omdb_search("Arrival") == []
    assert providers.media_provider_statuses()["omdb"]["last_error"] == "Invalid API key!"


def test_tvmaze_search_needs_no_api_key(monkeypatch, tmp_path):
    _isolate_key_store(monkeypatch, tmp_path)

    def fake_get_json(url, params=None, headers=None):
        assert url == f"{providers.TVMAZE_BASE}/search/shows"
        assert params == {"q": "Fringe"}
        return [{"show": {"id": 1, "name": "Fringe"}}]

    monkeypatch.setattr(providers, "_get_json", fake_get_json)

    assert providers.tvmaze_search_shows("Fringe") == [{"id": 1, "name": "Fringe"}]
    statuses = providers.media_provider_statuses()
    assert statuses["tvmaze"]["configured"] is True
    assert statuses["tvmaze"]["source"] == "not required"
