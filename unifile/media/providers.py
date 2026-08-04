"""UniFile — normalized metadata providers for video, books, and audio.

Adapted from mnamer's provider system. Queries public APIs to fetch
movie/episode metadata from filenames.
"""
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

logger = logging.getLogger(__name__)

_MEDIA_KEYS_FILE = os.path.join(_APP_DATA_DIR, "media_api_keys.json")
_KEY_ENV_VARS = {
    "tmdb": "API_KEY_TMDB",
    "omdb": "API_KEY_OMDB",
    "tvdb": "API_KEY_TVDB",
    "opensubtitles": "API_KEY_OPENSUBTITLES",
}
_OPTIONAL_KEY_ENV_VARS = {
    "tvdb_pin": "API_KEY_TVDB_PIN",
    "opensubtitles_username": "OPENSUBTITLES_USERNAME",
    "opensubtitles_password": "OPENSUBTITLES_PASSWORD",
}
_ALL_KEY_ENV_VARS = {**_KEY_ENV_VARS, **_OPTIONAL_KEY_ENV_VARS}
_PROVIDER_LABELS = {
    "tmdb": "TMDb",
    "omdb": "OMDb",
    "tvdb": "TVDB",
    "tvmaze": "TVMaze",
    "openlibrary": "OpenLibrary",
    "googlebooks": "Google Books",
    "musicbrainz": "MusicBrainz",
    "opensubtitles": "OpenSubtitles",
}
_PROVIDER_ERRORS: dict[str, str] = {key: "" for key in _PROVIDER_LABELS}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class MediaType(Enum):
    MOVIE = "movie"
    EPISODE = "episode"
    BOOK = "book"
    AUDIOBOOK = "audiobook"
    AUDIO = "audio"
    UNKNOWN = "unknown"


@dataclass
class MovieResult:
    title: str = ""
    year: str = ""
    synopsis: str = ""
    id_imdb: str = ""
    id_tmdb: str = ""
    poster_url: str = ""
    genres: list[str] = field(default_factory=list)
    provider: str = ""

    @property
    def display(self) -> str:
        y = f" ({self.year})" if self.year else ""
        return f"{self.title}{y}"


@dataclass
class EpisodeResult:
    series: str = ""
    season: int = 0
    episode: int = 0
    title: str = ""
    date: str = ""
    synopsis: str = ""
    id_tvdb: str = ""
    id_tvmaze: str = ""
    id_imdb: str = ""
    poster_url: str = ""
    genres: list[str] = field(default_factory=list)
    id_tmdb: str = ""
    year: str = ""
    provider: str = ""

    @property
    def display(self) -> str:
        ep = f"S{self.season:02d}E{self.episode:02d}" if self.season and self.episode else ""
        t = f" - {self.title}" if self.title else ""
        return f"{self.series} {ep}{t}".strip()


@dataclass
class BookResult:
    """A normalized book or audiobook search result."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    synopsis: str = ""
    isbn: str = ""
    language: str = ""
    genres: list[str] = field(default_factory=list)
    series: str = ""
    publisher: str = ""
    cover_url: str = ""
    source_url: str = ""
    id_openlibrary: str = ""
    id_googlebooks: str = ""
    provider: str = ""

    @property
    def display(self) -> str:
        year = f" ({self.year})" if self.year else ""
        authors = f" — {', '.join(self.authors)}" if self.authors else ""
        return f"{self.title}{year}{authors}"


@dataclass
class AudioResult:
    """A normalized MusicBrainz recording result."""

    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    synopsis: str = ""
    genre: str = ""
    id_musicbrainz: str = ""
    release_id: str = ""
    cover_url: str = ""
    source_url: str = ""
    provider: str = ""

    @property
    def display(self) -> str:
        prefix = f"{self.artist} — " if self.artist else ""
        suffix = f" ({self.year})" if self.year else ""
        return f"{prefix}{self.title}{suffix}"


# ---------------------------------------------------------------------------
# Provider base
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderNotFound(ProviderError):
    pass


def load_media_api_keys() -> dict[str, str]:
    """Load user-owned media API keys from UniFile app data."""
    raw = load_json_safe(_MEDIA_KEYS_FILE, {}, expected_type=dict)
    keys: dict[str, str] = {}
    for provider in _ALL_KEY_ENV_VARS:
        value = raw.get(provider, "")
        if isinstance(value, str) and value.strip():
            keys[provider] = value.strip()
    return keys


def save_media_api_keys(keys: dict[str, str]) -> bool:
    """Persist user-owned media API keys. Empty values remove saved keys."""
    payload: dict[str, str] = {}
    for provider in _ALL_KEY_ENV_VARS:
        value = str(keys.get(provider, "") or "").strip()
        if value:
            payload[provider] = value
    return save_json_safe(_MEDIA_KEYS_FILE, payload)


def _api_key_source(provider: str) -> str:
    env_var = _ALL_KEY_ENV_VARS.get(provider)
    if env_var and os.environ.get(env_var, "").strip():
        return "environment"
    if load_media_api_keys().get(provider, ""):
        return "settings"
    return "missing"


def get_media_api_key(provider: str) -> str:
    """Return the configured API key for a provider, preferring env vars."""
    provider = provider.lower()
    env_var = _ALL_KEY_ENV_VARS.get(provider)
    if env_var:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return load_media_api_keys().get(provider, "")


def clear_media_provider_errors() -> None:
    for provider in _PROVIDER_ERRORS:
        _PROVIDER_ERRORS[provider] = ""


def _set_provider_error(provider: str, message: str) -> None:
    if provider in _PROVIDER_ERRORS:
        _PROVIDER_ERRORS[provider] = message.strip()


def media_provider_statuses() -> dict[str, dict[str, Any]]:
    """Return provider credential/readiness state for UI and tests."""
    statuses: dict[str, dict[str, Any]] = {}
    for provider, label in _PROVIDER_LABELS.items():
        requires_key = provider in _KEY_ENV_VARS
        source = _api_key_source(provider) if requires_key else "not required"
        statuses[provider] = {
            "label": label,
            "requires_key": requires_key,
            "configured": not requires_key or source != "missing",
            "source": source,
            "env_var": _KEY_ENV_VARS.get(provider, ""),
            "pin_configured": bool(get_media_api_key("tvdb_pin")) if provider == "tvdb" else False,
            "pin_source": _api_key_source("tvdb_pin") if provider == "tvdb" else "",
            "pin_env_var": _OPTIONAL_KEY_ENV_VARS.get("tvdb_pin", "") if provider == "tvdb" else "",
            "last_error": _PROVIDER_ERRORS.get(provider, ""),
        }
    return statuses


def _get_session():
    """Create a cached requests session (falls back to plain if requests-cache unavailable)."""
    import requests
    try:
        import requests_cache
        from platformdirs import user_cache_dir
        cache_dir = user_cache_dir("unifile", ensure_exists=True)
        session = requests_cache.CachedSession(
            cache_name=os.path.join(cache_dir, "media_cache"),
            expire_after=518_400,  # 6 days
        )
    except ImportError:
        session = requests.Session()
    from requests.adapters import HTTPAdapter
    adapter = HTTPAdapter(max_retries=3)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_session = None

def _get_json(url: str, params: dict | None = None,
              headers: dict | None = None) -> Any:
    global _session
    if _session is None:
        _session = _get_session()
    try:
        resp = _session.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code in (401, 403):
            raise ProviderAuthError(f"provider rejected credentials ({resp.status_code})")
        resp.raise_for_status()
        return resp.json()
    except ProviderAuthError:
        raise
    except Exception as e:
        logger.warning("API request failed: %s - %s", url, e)
        raise ProviderError(str(e)) from e


def _post_json(url: str, payload: dict[str, Any],
               headers: dict | None = None) -> Any:
    """POST JSON through the same cached session and normalized error path."""
    global _session
    if _session is None:
        _session = _get_session()
    try:
        resp = _session.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code in (401, 403):
            raise ProviderAuthError(f"provider rejected credentials ({resp.status_code})")
        resp.raise_for_status()
        return resp.json()
    except ProviderAuthError:
        raise
    except Exception as e:
        logger.warning("API request failed: %s - %s", url, e)
        raise ProviderError(str(e)) from e


# ---------------------------------------------------------------------------
# TMDb provider (movies)
# ---------------------------------------------------------------------------

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w300"


def tmdb_search_movies(query: str, year: str | None = None,
                       limit: int = 10) -> list[MovieResult]:
    """Search TMDb for movies by title."""
    key = get_media_api_key("tmdb")
    if not key:
        _set_provider_error("tmdb", "Missing TMDb API key.")
        return []

    params: dict[str, Any] = {"api_key": key, "query": query}
    if year:
        params["year"] = year
    try:
        data = _get_json(f"{TMDB_BASE}/search/movie", params=params)
        _set_provider_error("tmdb", "")
    except ProviderAuthError:
        _set_provider_error("tmdb", "TMDb rejected the API key.")
        return []
    except ProviderError:
        _set_provider_error("tmdb", "TMDb request failed.")
        return []
    results = []
    for item in data.get("results", [])[:limit]:
        poster = f"{TMDB_IMG}{item['poster_path']}" if item.get("poster_path") else ""
        rd = item.get("release_date", "")
        results.append(MovieResult(
            title=item.get("title", ""),
            year=rd[:4] if rd else "",
            synopsis=item.get("overview", ""),
            id_tmdb=str(item.get("id", "")),
            poster_url=poster,
            genres=[],
            provider="tmdb",
        ))
    return results


def tmdb_movie_details(tmdb_id: str) -> MovieResult | None:
    """Get detailed movie info by TMDb ID."""
    key = get_media_api_key("tmdb")
    if not key:
        _set_provider_error("tmdb", "Missing TMDb API key.")
        return None

    try:
        data = _get_json(f"{TMDB_BASE}/movie/{tmdb_id}",
                         params={"api_key": key})
        _set_provider_error("tmdb", "")
    except ProviderAuthError:
        _set_provider_error("tmdb", "TMDb rejected the API key.")
        return None
    except ProviderError:
        _set_provider_error("tmdb", "TMDb request failed.")
        return None
    poster = f"{TMDB_IMG}{data['poster_path']}" if data.get("poster_path") else ""
    rd = data.get("release_date", "")
    return MovieResult(
        title=data.get("title", ""),
        year=rd[:4] if rd else "",
        synopsis=data.get("overview", ""),
        id_tmdb=str(data.get("id", "")),
        id_imdb=data.get("imdb_id", ""),
        poster_url=poster,
        genres=[g["name"] for g in data.get("genres", [])],
        provider="tmdb",
    )


# ---------------------------------------------------------------------------
# TV providers (TMDb / TVDB / TVMaze)
# ---------------------------------------------------------------------------

def _strip_html(value: Any) -> str:
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


def tmdb_search_shows(query: str, year: str | None = None,
                      limit: int = 10) -> list[EpisodeResult]:
    """Search TMDb TV series using the same key as movie lookup."""
    key = get_media_api_key("tmdb")
    if not key:
        _set_provider_error("tmdb", "Missing TMDb API key.")
        return []
    params: dict[str, Any] = {"api_key": key, "query": query}
    if year:
        params["first_air_date_year"] = year
    try:
        data = _get_json(f"{TMDB_BASE}/search/tv", params=params)
        _set_provider_error("tmdb", "")
    except ProviderAuthError:
        _set_provider_error("tmdb", "TMDb rejected the API key.")
        return []
    except ProviderError:
        _set_provider_error("tmdb", "TMDb request failed.")
        return []
    results: list[EpisodeResult] = []
    for item in (data or {}).get("results", [])[:limit]:
        first_air = str(item.get("first_air_date", "") or "")
        poster_path = item.get("poster_path")
        results.append(EpisodeResult(
            series=item.get("name", ""),
            synopsis=item.get("overview", ""),
            id_tmdb=str(item.get("id", "")),
            poster_url=f"{TMDB_IMG}{poster_path}" if poster_path else "",
            year=first_air[:4],
            provider="tmdb",
        ))
    return results


def tmdb_show_details(tmdb_id: str) -> EpisodeResult | None:
    """Load a detailed TMDb TV series record."""
    key = get_media_api_key("tmdb")
    if not key:
        _set_provider_error("tmdb", "Missing TMDb API key.")
        return None
    try:
        data = _get_json(f"{TMDB_BASE}/tv/{tmdb_id}", params={"api_key": key})
        _set_provider_error("tmdb", "")
    except ProviderAuthError:
        _set_provider_error("tmdb", "TMDb rejected the API key.")
        return None
    except ProviderError:
        _set_provider_error("tmdb", "TMDb request failed.")
        return None
    first_air = str(data.get("first_air_date", "") or "")
    poster_path = data.get("poster_path")
    return EpisodeResult(
        series=data.get("name", ""),
        synopsis=data.get("overview", ""),
        id_tmdb=str(data.get("id", tmdb_id)),
        poster_url=f"{TMDB_IMG}{poster_path}" if poster_path else "",
        genres=[item.get("name", "") for item in data.get("genres", []) if item.get("name")],
        year=first_air[:4],
        provider="tmdb",
    )


def tmdb_show_episodes(tmdb_id: str) -> list[EpisodeResult]:
    """Fetch all available TMDb seasons and normalize their episodes."""
    key = get_media_api_key("tmdb")
    if not key:
        _set_provider_error("tmdb", "Missing TMDb API key.")
        return []
    try:
        show = _get_json(f"{TMDB_BASE}/tv/{tmdb_id}", params={"api_key": key})
        series = show.get("name", "")
        episodes: list[EpisodeResult] = []
        for season in show.get("seasons", []):
            season_number = season.get("season_number")
            if season_number is None:
                continue
            payload = _get_json(
                f"{TMDB_BASE}/tv/{tmdb_id}/season/{season_number}",
                params={"api_key": key},
            )
            for item in payload.get("episodes", []):
                episodes.append(EpisodeResult(
                    series=series,
                    season=int(item.get("season_number", season_number) or 0),
                    episode=int(item.get("episode_number", 0) or 0),
                    title=item.get("name", ""),
                    date=item.get("air_date", "") or "",
                    synopsis=item.get("overview", "") or "",
                    id_tmdb=str(item.get("id", "")),
                    provider="tmdb",
                ))
        _set_provider_error("tmdb", "")
        return episodes
    except (ProviderAuthError, ProviderError, ValueError, TypeError):
        _set_provider_error("tmdb", "TMDb request failed.")
        return []


TVDB_BASE = "https://api4.thetvdb.com/v4"
_TVDB_TOKEN = ""
_TVDB_TOKEN_KEY = ""


def _tvdb_headers() -> dict[str, str] | None:
    """Authenticate once per configured TVDB key and return bearer headers."""
    global _TVDB_TOKEN, _TVDB_TOKEN_KEY
    key = get_media_api_key("tvdb")
    if not key:
        _set_provider_error("tvdb", "Missing TVDB API key.")
        return None
    pin = get_media_api_key("tvdb_pin")
    cache_key = f"{key}\x00{pin}"
    if key.startswith("eyJ"):
        _TVDB_TOKEN = key
        _TVDB_TOKEN_KEY = cache_key
    if not _TVDB_TOKEN or _TVDB_TOKEN_KEY != cache_key:
        payload: dict[str, Any] = {"apikey": key}
        if pin:
            payload["pin"] = pin
        try:
            response = _post_json(f"{TVDB_BASE}/login", payload)
            _TVDB_TOKEN = str((response or {}).get("data", {}).get("token", ""))
            _TVDB_TOKEN_KEY = cache_key
        except ProviderAuthError:
            _set_provider_error("tvdb", "TVDB rejected the API key or subscriber PIN.")
            return None
        except ProviderError:
            _set_provider_error("tvdb", "TVDB authentication failed.")
            return None
    if not _TVDB_TOKEN:
        _set_provider_error("tvdb", "TVDB did not return an access token.")
        return None
    return {"Authorization": f"Bearer {_TVDB_TOKEN}"}


def _tvdb_result(item: dict[str, Any], *, provider: str = "tvdb") -> EpisodeResult:
    image = item.get("image_url") or item.get("image") or ""
    first_air = str(item.get("firstAired") or item.get("year") or "")
    genres = []
    for value in item.get("genres") or []:
        if isinstance(value, dict):
            value = value.get("name") or value.get("genre") or ""
        if value:
            genres.append(str(value))
    return EpisodeResult(
        series=item.get("name") or item.get("seriesName") or "",
        synopsis=_strip_html(item.get("overview") or item.get("overviewTranslations", "")),
        id_tvdb=str(item.get("id") or item.get("tvdb_id") or ""),
        poster_url=image,
        year=first_air[:4],
        genres=genres,
        provider=provider,
    )


def tvdb_search_shows(query: str, year: str | None = None,
                      limit: int = 10) -> list[EpisodeResult]:
    """Search TVDB v4 series with user-provided API credentials."""
    headers = _tvdb_headers()
    if not headers:
        return []
    params: dict[str, Any] = {"query": query, "type": "series", "limit": limit}
    if year:
        params["year"] = year
    try:
        data = _get_json(f"{TVDB_BASE}/search", params=params, headers=headers)
        _set_provider_error("tvdb", "")
    except ProviderAuthError:
        _set_provider_error("tvdb", "TVDB rejected the access token.")
        return []
    except ProviderError:
        _set_provider_error("tvdb", "TVDB request failed.")
        return []
    return [_tvdb_result(item) for item in (data or {}).get("data", [])[:limit]]


def tvdb_show_details(tvdb_id: str) -> EpisodeResult | None:
    """Load a detailed TVDB series record."""
    headers = _tvdb_headers()
    if not headers:
        return None
    try:
        data = _get_json(f"{TVDB_BASE}/series/{tvdb_id}/extended", headers=headers)
        _set_provider_error("tvdb", "")
        return _tvdb_result((data or {}).get("data", {}))
    except ProviderAuthError:
        _set_provider_error("tvdb", "TVDB rejected the access token.")
    except ProviderError:
        _set_provider_error("tvdb", "TVDB request failed.")
    return None


def tvdb_show_episodes(tvdb_id: str, season: int | None = None) -> list[EpisodeResult]:
    """Load normalized TVDB episodes, optionally for one season."""
    headers = _tvdb_headers()
    if not headers:
        return []
    params: dict[str, Any] = {"page": 0}
    if season is not None:
        params["season"] = season
    try:
        data = _get_json(
            f"{TVDB_BASE}/series/{tvdb_id}/episodes/default",
            params=params,
            headers=headers,
        )
        series = tvdb_show_details(tvdb_id)
        name = series.series if series else ""
        result: list[EpisodeResult] = []
        for item in (data or {}).get("data", []):
            episode = EpisodeResult(
                series=name,
                season=int(item.get("seasonNumber", 0) or 0),
                episode=int(item.get("number", 0) or 0),
                title=item.get("name", ""),
                date=item.get("aired", "") or "",
                synopsis=_strip_html(item.get("overview", "")),
                id_tvdb=str(item.get("id", "")),
                provider="tvdb",
            )
            result.append(episode)
        _set_provider_error("tvdb", "")
        return result
    except (ProviderAuthError, ProviderError, ValueError, TypeError):
        _set_provider_error("tvdb", "TVDB request failed.")
        return []


# ---------------------------------------------------------------------------
# TVMaze provider (episodes / no-key fallback)
# ---------------------------------------------------------------------------

TVMAZE_BASE = "https://api.tvmaze.com"


def tvmaze_search_shows(query: str, limit: int = 10) -> list[dict]:
    """Search TVMaze for shows by name. Returns raw show dicts."""
    try:
        data = _get_json(f"{TVMAZE_BASE}/search/shows", params={"q": query})
    except ProviderError:
        return []
    results = []
    for item in data[:limit]:
        show = item.get("show", {})
        results.append(show)
    return results


def tvmaze_show_details(show_id: int) -> dict | None:
    """Get show info by TVMaze ID."""
    try:
        return _get_json(f"{TVMAZE_BASE}/shows/{show_id}")
    except ProviderError:
        return None


def tvmaze_show_episodes(show_id: int) -> list[EpisodeResult]:
    """Get all episodes for a show."""
    try:
        data = _get_json(f"{TVMAZE_BASE}/shows/{show_id}/episodes")
    except ProviderError:
        return []
    results = []
    for ep in data:
        img = ep.get("image", {}) or {}
        synopsis = ep.get("summary", "") or ""
        # Strip HTML tags from synopsis
        synopsis = re.sub(r"<[^>]+>", "", synopsis).strip()
        results.append(EpisodeResult(
            series="",  # Caller fills in
            season=ep.get("season", 0),
            episode=ep.get("number", 0),
            title=ep.get("name", ""),
            date=ep.get("airdate", ""),
            synopsis=synopsis,
            id_tvmaze=str(ep.get("id", "")),
            poster_url=img.get("medium", ""),
            provider="tvmaze",
        ))
    return results


def tvmaze_episode_lookup(show_id: int, season: int,
                          episode: int) -> EpisodeResult | None:
    """Get a specific episode by season/episode number."""
    try:
        data = _get_json(
            f"{TVMAZE_BASE}/shows/{show_id}/episodebynumber",
            params={"season": season, "number": episode},
        )
    except ProviderError:
        return None
    img = data.get("image", {}) or {}
    synopsis = data.get("summary", "") or ""
    synopsis = re.sub(r"<[^>]+>", "", synopsis).strip()
    return EpisodeResult(
        season=data.get("season", 0),
        episode=data.get("number", 0),
        title=data.get("name", ""),
        date=data.get("airdate", ""),
        synopsis=synopsis,
        id_tvmaze=str(data.get("id", "")),
        poster_url=img.get("medium", ""),
        provider="tvmaze",
    )


# ---------------------------------------------------------------------------
# OMDb provider (movies — fallback)
# ---------------------------------------------------------------------------

OMDB_BASE = "https://www.omdbapi.com"


def omdb_search(query: str, year: str | None = None,
                limit: int = 10) -> list[MovieResult]:
    """Search OMDb for movies."""
    key = get_media_api_key("omdb")
    if not key:
        _set_provider_error("omdb", "Missing OMDb API key.")
        return []

    params: dict[str, Any] = {"apikey": key, "s": query, "type": "movie"}
    if year:
        params["y"] = year
    try:
        data = _get_json(OMDB_BASE, params=params)
        _set_provider_error("omdb", "")
    except ProviderAuthError:
        _set_provider_error("omdb", "OMDb rejected the API key.")
        return []
    except ProviderError:
        _set_provider_error("omdb", "OMDb request failed.")
        return []
    if data.get("Response") != "True":
        err = data.get("Error", "")
        if isinstance(err, str) and "api key" in err.lower():
            _set_provider_error("omdb", err)
        return []
    results = []
    for item in data.get("Search", [])[:limit]:
        poster = item.get("Poster", "")
        if poster == "N/A":
            poster = ""
        results.append(MovieResult(
            title=item.get("Title", ""),
            year=item.get("Year", ""),
            id_imdb=item.get("imdbID", ""),
            poster_url=poster,
            provider="omdb",
        ))
    return results


def omdb_details(imdb_id: str) -> MovieResult | None:
    """Get movie details by IMDb ID from OMDb."""
    key = get_media_api_key("omdb")
    if not key:
        _set_provider_error("omdb", "Missing OMDb API key.")
        return None

    try:
        data = _get_json(OMDB_BASE, params={"apikey": key, "i": imdb_id})
        _set_provider_error("omdb", "")
    except ProviderAuthError:
        _set_provider_error("omdb", "OMDb rejected the API key.")
        return None
    except ProviderError:
        _set_provider_error("omdb", "OMDb request failed.")
        return None
    if data.get("Response") != "True":
        err = data.get("Error", "")
        if isinstance(err, str) and "api key" in err.lower():
            _set_provider_error("omdb", err)
        return None
    poster = data.get("Poster", "")
    if poster == "N/A":
        poster = ""
    genres = [g.strip() for g in data.get("Genre", "").split(",") if g.strip()]
    return MovieResult(
        title=data.get("Title", ""),
        year=data.get("Year", ""),
        synopsis=data.get("Plot", ""),
        id_imdb=data.get("imdbID", ""),
        poster_url=poster,
        genres=genres,
        provider="omdb",
    )


# ---------------------------------------------------------------------------
# Book / audiobook providers (OpenLibrary / Google Books)
# ---------------------------------------------------------------------------

OPENLIBRARY_BASE = "https://openlibrary.org"
OPENLIBRARY_SEARCH = f"{OPENLIBRARY_BASE}/search.json"
GOOGLE_BOOKS_BASE = "https://www.googleapis.com/books/v1/volumes"


def _text(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    if isinstance(value, dict):
        return str(value.get("value", ""))
    return str(value or "").strip()


def _book_from_openlibrary(item: dict[str, Any]) -> BookResult:
    key = _text(item.get("key"))
    isbns = item.get("isbn") or item.get("isbn13") or item.get("isbn10") or []
    if isinstance(isbns, str):
        isbns = [isbns]
    cover_id = _text(item.get("cover_i"))
    subjects = item.get("subject") or item.get("subject_key") or []
    if isinstance(subjects, str):
        subjects = [subjects]
    source_url = f"{OPENLIBRARY_BASE}{key}" if key.startswith("/") else ""
    authors = item.get("author_name") or item.get("authors") or []
    if isinstance(authors, (str, dict)):
        authors = [authors]
    author_names = []
    for value in authors:
        if isinstance(value, dict):
            value = value.get("name") or value.get("author", {}).get("name", "")
        if _text(value):
            author_names.append(_text(value))
    description = item.get("first_sentence") or item.get("description")
    if isinstance(description, dict):
        description = description.get("value", "")
    languages = item.get("language") or item.get("languages") or []
    if isinstance(languages, (str, dict)):
        languages = [languages]
    language = _text(languages[0]) if languages else ""
    publishers = item.get("publisher") or item.get("publishers") or []
    if isinstance(publishers, (str, dict)):
        publishers = [publishers]
    publisher = _text(publishers[0]) if publishers else ""
    return BookResult(
        title=_text(item.get("title")),
        authors=list(dict.fromkeys(author_names)),
        year=_text(item.get("first_publish_year")) or _text(item.get("publish_date"))[:4],
        synopsis=_text(description),
        isbn=_text(isbns[0]) if isbns else "",
        language=language,
        genres=list(dict.fromkeys(_text(value) for value in subjects if _text(value)))[:20],
        publisher=publisher,
        cover_url=f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg?default=false" if cover_id else "",
        source_url=source_url,
        id_openlibrary=key,
        provider="openlibrary",
    )


def openlibrary_search_books(query: str, year: str | None = None,
                             limit: int = 10) -> list[BookResult]:
    """Search OpenLibrary without requiring an API key."""
    params: dict[str, Any] = {"q": query, "limit": min(100, max(1, limit))}
    if year:
        params["first_publish_year"] = year
    try:
        data = _get_json(OPENLIBRARY_SEARCH, params=params)
    except ProviderError:
        _set_provider_error("openlibrary", "OpenLibrary request failed.")
        return []
    _set_provider_error("openlibrary", "")
    return [_book_from_openlibrary(item) for item in (data or {}).get("docs", [])[:limit]]


def openlibrary_book_details(key: str) -> BookResult | None:
    """Load one OpenLibrary work or edition record."""
    if not key:
        return None
    path = key if key.startswith("/") else f"/works/{key}.json"
    if not path.endswith(".json"):
        path += ".json"
    try:
        data = _get_json(f"{OPENLIBRARY_BASE}{path}")
    except ProviderError:
        _set_provider_error("openlibrary", "OpenLibrary request failed.")
        return None
    result = _book_from_openlibrary({**(data or {}), "key": path.removesuffix(".json")})
    result.provider = "openlibrary"
    return result


def _book_from_google(item: dict[str, Any]) -> BookResult:
    info = item.get("volumeInfo") or {}
    identifiers = info.get("industryIdentifiers") or []
    isbn = next(
        (_text(value.get("identifier")) for value in identifiers
         if isinstance(value, dict) and _text(value.get("identifier"))),
        "",
    )
    image_links = info.get("imageLinks") or {}
    return BookResult(
        title=_text(info.get("title")),
        authors=[_text(value) for value in (info.get("authors") or []) if _text(value)],
        year=_text(info.get("publishedDate"))[:4],
        synopsis=_text(info.get("description")),
        isbn=isbn,
        language=_text(info.get("language")),
        genres=[_text(value) for value in (info.get("categories") or []) if _text(value)],
        publisher=_text(info.get("publisher")),
        cover_url=_text(image_links.get("thumbnail")),
        source_url=_text(info.get("canonicalVolumeLink")) or _text(info.get("infoLink")),
        id_googlebooks=_text(item.get("id")),
        provider="googlebooks",
    )


def googlebooks_search_books(query: str, year: str | None = None,
                             limit: int = 10) -> list[BookResult]:
    """Search Google Books as a fallback for book and audiobook metadata."""
    try:
        data = _get_json(
            GOOGLE_BOOKS_BASE,
            params={"q": query, "maxResults": min(40, max(1, limit))},
        )
    except ProviderError:
        _set_provider_error("googlebooks", "Google Books request failed.")
        return []
    _set_provider_error("googlebooks", "")
    results = [_book_from_google(item) for item in (data or {}).get("items", [])]
    if year:
        filtered = [item for item in results if item.year == str(year)]
        if filtered:
            results = filtered
    return results[:limit]


def googlebooks_book_details(volume_id: str) -> BookResult | None:
    if not volume_id:
        return None
    try:
        data = _get_json(f"{GOOGLE_BOOKS_BASE}/{volume_id}")
    except ProviderError:
        _set_provider_error("googlebooks", "Google Books request failed.")
        return None
    return _book_from_google(data)


# ---------------------------------------------------------------------------
# MusicBrainz provider (audio)
# ---------------------------------------------------------------------------

MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_USER_AGENT = "UniFile/9.3.32 (https://github.com/SysAdminDoc/UniFile)"
COVER_ART_BASE = "https://coverartarchive.org/release"
_MUSICBRAINZ_LOCK = threading.Lock()
_MUSICBRAINZ_LAST_REQUEST = 0.0


def _musicbrainz_json(path: str, params: dict[str, Any]) -> Any:
    """Call MusicBrainz with its required identifying user-agent and pacing."""
    global _MUSICBRAINZ_LAST_REQUEST
    with _MUSICBRAINZ_LOCK:
        wait = 1.0 - (time.monotonic() - _MUSICBRAINZ_LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        payload = _get_json(
            f"{MUSICBRAINZ_BASE}/{path.lstrip('/')}",
            params={**params, "fmt": "json"},
            headers={
                "Accept": "application/json",
                "User-Agent": MUSICBRAINZ_USER_AGENT,
            },
        )
        _MUSICBRAINZ_LAST_REQUEST = time.monotonic()
        return payload


def _artist_credit(recording: dict[str, Any]) -> str:
    values: list[str] = []
    for credit in recording.get("artist-credit", []) or []:
        if isinstance(credit, dict):
            artist = credit.get("artist", {}) or {}
            values.append(_text(artist.get("name")) or _text(credit.get("name")))
        elif isinstance(credit, str):
            values.append(credit)
    return "".join(value for value in values if value).strip()


def _audio_from_recording(item: dict[str, Any]) -> AudioResult:
    releases = item.get("releases") or []
    release = releases[0] if releases and isinstance(releases[0], dict) else {}
    release_id = _text(release.get("id"))
    date = _text(item.get("first-release-date")) or _text(release.get("date"))
    genres = item.get("genres") or []
    genre = _text(genres[0].get("name") if genres and isinstance(genres[0], dict) else (genres[0] if genres else ""))
    return AudioResult(
        title=_text(item.get("title")),
        artist=_artist_credit(item),
        album=_text((release.get("release-group") or {}).get("title")) or _text(release.get("title")),
        year=date[:4],
        genre=genre,
        id_musicbrainz=_text(item.get("id")),
        release_id=release_id,
        cover_url=f"{COVER_ART_BASE}/{release_id}/front-250" if release_id else "",
        source_url=f"https://musicbrainz.org/recording/{_text(item.get('id'))}" if item.get("id") else "",
        provider="musicbrainz",
    )


def musicbrainz_search_recordings(query: str, year: str | None = None,
                                  limit: int = 10) -> list[AudioResult]:
    """Search public MusicBrainz recording metadata without an API key."""
    try:
        data = _musicbrainz_json(
            "recording",
            {"query": query, "limit": min(100, max(1, limit)), "inc": "artists+releases"},
        )
    except ProviderError:
        _set_provider_error("musicbrainz", "MusicBrainz request failed.")
        return []
    _set_provider_error("musicbrainz", "")
    results = [_audio_from_recording(item) for item in (data or {}).get("recordings", [])]
    if year:
        filtered = [item for item in results if item.year == str(year)]
        if filtered:
            results = filtered
    return results[:limit]


def musicbrainz_recording_details(recording_id: str) -> AudioResult | None:
    if not recording_id:
        return None
    try:
        data = _musicbrainz_json(
            f"recording/{recording_id}",
            {"inc": "artists+releases+release-groups+genres"},
        )
    except ProviderError:
        _set_provider_error("musicbrainz", "MusicBrainz request failed.")
        return None
    return _audio_from_recording(data or {})


# ---------------------------------------------------------------------------
# Filename → metadata parser (uses guessit)
# ---------------------------------------------------------------------------

def parse_media_filename(filename: str) -> dict:
    """Parse a media filename into structured metadata using guessit.

    Returns dict with keys: type (MediaType), title, year, season, episode, etc.
    Falls back to basic parsing if guessit is unavailable.
    """
    suffix = os.path.splitext(filename)[1].casefold()
    extension_type = {
        ".epub": MediaType.BOOK,
        ".pdf": MediaType.BOOK,
        ".mobi": MediaType.BOOK,
        ".azw3": MediaType.BOOK,
        ".m4b": MediaType.AUDIOBOOK,
        ".aax": MediaType.AUDIOBOOK,
        ".aa": MediaType.AUDIOBOOK,
        ".mp3": MediaType.AUDIO,
        ".flac": MediaType.AUDIO,
        ".m4a": MediaType.AUDIO,
        ".wav": MediaType.AUDIO,
        ".ogg": MediaType.AUDIO,
        ".opus": MediaType.AUDIO,
    }
    result: dict[str, Any] = {
        "type": extension_type.get(suffix, MediaType.UNKNOWN), "title": "", "year": ""
    }
    if suffix in extension_type:
        result["title"] = re.sub(r"[._-]+", " ", os.path.splitext(os.path.basename(filename))[0]).strip()
    try:
        from guessit import guessit
        parsed = dict(guessit(filename))
        media_type = parsed.get("type", "")
        if media_type == "episode":
            result["type"] = MediaType.EPISODE
            result["title"] = str(parsed.get("title", ""))
            result["season"] = parsed.get("season", 0)
            result["episode"] = parsed.get("episode", 0)
            result["year"] = str(parsed.get("year", ""))
        elif result["type"] not in {MediaType.BOOK, MediaType.AUDIOBOOK, MediaType.AUDIO}:
            result["type"] = MediaType.MOVIE
            result["title"] = str(parsed.get("title", ""))
            result["year"] = str(parsed.get("year", ""))

        result["quality"] = parsed.get("screen_size", "")
        result["source"] = parsed.get("source", "")
        result["group"] = parsed.get("release_group", "")
    except ImportError:
        # Basic fallback: just use the filename stem
        from pathlib import Path
        stem = Path(filename).stem
        # Strip common junk patterns
        clean = re.sub(r"[\.\-_]", " ", stem)
        clean = re.sub(r"\s+", " ", clean).strip()
        result["title"] = clean
    return result


# ---------------------------------------------------------------------------
# Unified search
# ---------------------------------------------------------------------------

def search_media(query: str, year: str | None = None,
                 media_type: MediaType = MediaType.MOVIE,
                 limit: int = 10) -> list[MovieResult | EpisodeResult | BookResult | AudioResult]:
    """Unified search with deterministic provider fallback chains."""
    if media_type == MediaType.MOVIE:
        results = tmdb_search_movies(query, year=year, limit=limit)
        if not results:
            results = omdb_search(query, year=year, limit=limit)
        return results
    elif media_type == MediaType.EPISODE:
        results = tvdb_search_shows(query, year=year, limit=limit)
        if results:
            return results
        results = tmdb_search_shows(query, year=year, limit=limit)
        if results:
            return results
        shows = tvmaze_search_shows(query, limit=limit)
        return [EpisodeResult(
            series=show.get("name", ""),
            synopsis=_strip_html(show.get("summary", "")),
            id_tvmaze=str(show.get("id", "")),
            poster_url=(show.get("image", {}) or {}).get("medium", ""),
            genres=show.get("genres", []) or [],
            year=str(show.get("premiered", "") or "")[:4],
            provider="tvmaze",
        ) for show in shows]
    elif media_type in {MediaType.BOOK, MediaType.AUDIOBOOK}:
        results = openlibrary_search_books(query, year=year, limit=limit)
        if not results:
            results = googlebooks_search_books(query, year=year, limit=limit)
        return results
    elif media_type == MediaType.AUDIO:
        return musicbrainz_search_recordings(query, year=year, limit=limit)
    return []
