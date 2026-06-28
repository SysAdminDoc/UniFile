"""UniFile — Media metadata providers (TMDb, TVMaze, OMDb).

Adapted from mnamer's provider system. Queries public APIs to fetch
movie/episode metadata from filenames.
"""
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

logger = logging.getLogger(__name__)

_MEDIA_KEYS_FILE = os.path.join(_APP_DATA_DIR, "media_api_keys.json")
_KEY_ENV_VARS = {
    "tmdb": "API_KEY_TMDB",
    "omdb": "API_KEY_OMDB",
}
_PROVIDER_LABELS = {
    "tmdb": "TMDb",
    "omdb": "OMDb",
    "tvmaze": "TVMaze",
}
_PROVIDER_ERRORS: dict[str, str] = {key: "" for key in _PROVIDER_LABELS}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class MediaType(Enum):
    MOVIE = "movie"
    EPISODE = "episode"
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

    @property
    def display(self) -> str:
        ep = f"S{self.season:02d}E{self.episode:02d}" if self.season and self.episode else ""
        t = f" - {self.title}" if self.title else ""
        return f"{self.series} {ep}{t}".strip()


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
    for provider in _KEY_ENV_VARS:
        value = raw.get(provider, "")
        if isinstance(value, str) and value.strip():
            keys[provider] = value.strip()
    return keys


def save_media_api_keys(keys: dict[str, str]) -> bool:
    """Persist user-owned media API keys. Empty values remove saved keys."""
    payload: dict[str, str] = {}
    for provider in _KEY_ENV_VARS:
        value = str(keys.get(provider, "") or "").strip()
        if value:
            payload[provider] = value
    return save_json_safe(_MEDIA_KEYS_FILE, payload)


def _api_key_source(provider: str) -> str:
    env_var = _KEY_ENV_VARS.get(provider)
    if env_var and os.environ.get(env_var, "").strip():
        return "environment"
    if load_media_api_keys().get(provider, ""):
        return "settings"
    return "missing"


def get_media_api_key(provider: str) -> str:
    """Return the configured API key for a provider, preferring env vars."""
    provider = provider.lower()
    env_var = _KEY_ENV_VARS.get(provider)
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
              headers: dict | None = None) -> dict:
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
    )


# ---------------------------------------------------------------------------
# TVMaze provider (episodes)
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
        import re
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
    import re
    synopsis = re.sub(r"<[^>]+>", "", synopsis).strip()
    return EpisodeResult(
        season=data.get("season", 0),
        episode=data.get("number", 0),
        title=data.get("name", ""),
        date=data.get("airdate", ""),
        synopsis=synopsis,
        id_tvmaze=str(data.get("id", "")),
        poster_url=img.get("medium", ""),
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
    )


# ---------------------------------------------------------------------------
# Filename → metadata parser (uses guessit)
# ---------------------------------------------------------------------------

def parse_media_filename(filename: str) -> dict:
    """Parse a media filename into structured metadata using guessit.

    Returns dict with keys: type (MediaType), title, year, season, episode, etc.
    Falls back to basic parsing if guessit is unavailable.
    """
    result: dict[str, Any] = {"type": MediaType.UNKNOWN, "title": "", "year": ""}
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
        else:
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
        import re
        clean = re.sub(r"[\.\-_]", " ", stem)
        clean = re.sub(r"\s+", " ", clean).strip()
        result["title"] = clean
    return result


# ---------------------------------------------------------------------------
# Unified search
# ---------------------------------------------------------------------------

def search_media(query: str, year: str | None = None,
                 media_type: MediaType = MediaType.MOVIE,
                 limit: int = 10) -> list[MovieResult | EpisodeResult]:
    """Unified search across providers based on media type."""
    if media_type == MediaType.MOVIE:
        results = tmdb_search_movies(query, year=year, limit=limit)
        if not results:
            results = omdb_search(query, year=year, limit=limit)
        return results
    elif media_type == MediaType.EPISODE:
        shows = tvmaze_search_shows(query, limit=limit)
        results = []
        for show in shows:
            img = show.get("image", {}) or {}
            genres = show.get("genres", []) or []
            results.append(EpisodeResult(
                series=show.get("name", ""),
                synopsis=(show.get("summary") or "").replace("<p>", "").replace("</p>", ""),
                id_tvmaze=str(show.get("id", "")),
                poster_url=img.get("medium", ""),
                genres=genres,
            ))
        return results
    return []
