"""UniFile — Media metadata providers (TMDb, TVMaze, OMDb).

Adapted from mnamer's provider system. Queries public APIs to fetch
movie/episode metadata from filenames.
"""
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

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


class ProviderNotFound(ProviderError):
    pass


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
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("API request failed: %s — %s", url, e)
        raise ProviderError(str(e)) from e


# ---------------------------------------------------------------------------
# TMDb provider (movies)
# ---------------------------------------------------------------------------

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w300"
TMDB_KEY = os.environ.get("API_KEY_TMDB", "db972a607f2760bb19ff8bb34074b4c7")


def tmdb_search_movies(query: str, year: str | None = None,
                       limit: int = 10) -> list[MovieResult]:
    """Search TMDb for movies by title."""
    params: dict[str, Any] = {"api_key": TMDB_KEY, "query": query}
    if year:
        params["year"] = year
    try:
        data = _get_json(f"{TMDB_BASE}/search/movie", params=params)
    except ProviderError:
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
    try:
        data = _get_json(f"{TMDB_BASE}/movie/{tmdb_id}",
                         params={"api_key": TMDB_KEY})
    except ProviderError:
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
OMDB_KEY = os.environ.get("API_KEY_OMDB", "477a7ebc")


def omdb_search(query: str, year: str | None = None,
                limit: int = 10) -> list[MovieResult]:
    """Search OMDb for movies."""
    params: dict[str, Any] = {"apikey": OMDB_KEY, "s": query, "type": "movie"}
    if year:
        params["y"] = year
    try:
        data = _get_json(OMDB_BASE, params=params)
    except ProviderError:
        return []
    if data.get("Response") != "True":
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
    try:
        data = _get_json(OMDB_BASE, params={"apikey": OMDB_KEY, "i": imdb_id})
    except ProviderError:
        return None
    if data.get("Response") != "True":
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
