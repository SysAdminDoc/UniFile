"""OpenSubtitles downloads and TMDb chapter sidecars.

Network calls are deliberately kept behind small, deterministic functions so
the media panel can run them in a worker and tests can replace the HTTP
session without contacting a provider.  OpenSubtitles credentials are never
written to logs and the session token is held in memory only.
"""
from __future__ import annotations

import gzip
import io
import os
import re
import struct
import time
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from unifile import __version__
from unifile.config import save_json_safe
from unifile.media.providers import (
    ProviderAuthError,
    ProviderError,
    _get_json,
    _get_session,
    _post_json,
    _set_provider_error,
    get_media_api_key,
)

OPEN_SUBTITLES_BASE = "https://api.opensubtitles.com/api/v1"
OPEN_SUBTITLES_USER_AGENT = f"UniFile v{__version__}"
SUBTITLE_SCHEMA_VERSION = 1
CHAPTER_SCHEMA_VERSION = 1
SUPPORTED_SUBTITLE_FORMATS = ("srt", "ass")

_request_lock = Lock()
_last_request_at = 0.0
_token = ""
_token_key = ""
_base_url = OPEN_SUBTITLES_BASE


@dataclass
class SubtitleResult:
    """A reviewable subtitle file returned by OpenSubtitles."""

    file_id: str = ""
    language: str = ""
    language_name: str = ""
    format: str = "srt"
    release: str = ""
    uploader: str = ""
    upload_date: str = ""
    download_count: int = 0
    rating: float = 0.0
    hearing_impaired: bool = False
    foreign_parts_only: bool = False
    trusted: bool = False
    moviehash_match: bool = False
    ai_translated: bool = False
    machine_translated: bool = False
    fps: float | None = None
    feature_title: str = ""
    feature_year: str = ""
    feature_id: str = ""
    provider_id: str = ""

    @property
    def label(self) -> str:
        flags = []
        if self.moviehash_match:
            flags.append("exact match")
        if self.hearing_impaired:
            flags.append("HI")
        if self.trusted:
            flags.append("trusted")
        suffix = f" · {', '.join(flags)}" if flags else ""
        release = f" — {self.release}" if self.release else ""
        return f"{self.language_name or self.language} · {self.format.upper()}{release}{suffix}"


@dataclass
class Chapter:
    """TMDb-derived chapter metadata stored in a sidecar."""

    number: int
    title: str
    season: int = 0
    episode: int = 0
    air_date: str = ""
    synopsis: str = ""
    tmdb_id: str = ""
    start_seconds: float | None = None
    end_seconds: float | None = None


def _pace_requests() -> None:
    """Keep login/search/download calls at least one second apart."""
    global _last_request_at
    with _request_lock:
        wait_for = 1.0 - (time.monotonic() - _last_request_at)
        if wait_for > 0:
            time.sleep(wait_for)
        _last_request_at = time.monotonic()


def _api_headers(token: str = "") -> dict[str, str]:
    key = get_media_api_key("opensubtitles")
    if not key:
        raise ProviderAuthError("Missing OpenSubtitles API key.")
    headers = {
        "Accept": "application/json",
        "Api-Key": key,
        "User-Agent": OPEN_SUBTITLES_USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _normalise_base_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    if not value:
        return OPEN_SUBTITLES_BASE
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value if value.endswith("/api/v1") else f"{value}/api/v1"


def opensubtitles_hash(filepath: str | os.PathLike[str]) -> str:
    """Return the OpenSubtitles 64-bit hash for a local media file."""
    path = Path(filepath)
    size = path.stat().st_size
    chunk_size = 64 * 1024

    with path.open("rb") as handle:
        first = handle.read(chunk_size)
        if size > chunk_size:
            handle.seek(max(0, size - chunk_size))
        last = handle.read(chunk_size)

    def _sum_chunks(data: bytes) -> int:
        total = 0
        for offset in range(0, len(data), 8):
            chunk = data[offset:offset + 8]
            if chunk:
                total += struct.unpack("<Q", chunk.ljust(8, b"\0"))[0]
        return total

    value = (size + _sum_chunks(first) + _sum_chunks(last)) & ((1 << 64) - 1)
    return f"{value:016x}"


def _subtitle_format(attributes: dict[str, Any], files: list[dict[str, Any]]) -> str:
    value = str(attributes.get("format") or "").strip().lower().lstrip(".")
    if value:
        return value
    for item in files:
        suffix = Path(str(item.get("file_name") or "")).suffix.lower().lstrip(".")
        if suffix:
            return suffix
    return "srt"


def _subtitle_result(item: dict[str, Any]) -> SubtitleResult | None:
    attributes = item.get("attributes") if isinstance(item, dict) else {}
    if not isinstance(attributes, dict):
        attributes = {}
    files = attributes.get("files") or []
    if not isinstance(files, list):
        files = []
    file_item = next((entry for entry in files if isinstance(entry, dict)), {})
    file_id = str(file_item.get("file_id") or attributes.get("file_id") or "")
    if not file_id:
        return None
    uploader = attributes.get("uploader") or {}
    if isinstance(uploader, dict):
        uploader = uploader.get("name") or uploader.get("username") or ""
    feature = attributes.get("feature_details") or {}
    if not isinstance(feature, dict):
        feature = {}
    fps = attributes.get("fps")
    try:
        fps = float(fps) if fps not in (None, "") else None
    except (TypeError, ValueError):
        fps = None
    return SubtitleResult(
        file_id=file_id,
        language=str(attributes.get("language") or ""),
        language_name=str(attributes.get("language_name") or ""),
        format=_subtitle_format(attributes, files),
        release=str(attributes.get("release") or ""),
        uploader=str(uploader),
        upload_date=str(attributes.get("upload_date") or ""),
        download_count=int(attributes.get("download_count") or 0),
        rating=float(attributes.get("ratings") or attributes.get("rating") or 0),
        hearing_impaired=bool(attributes.get("hearing_impaired")),
        foreign_parts_only=bool(attributes.get("foreign_parts_only")),
        trusted=bool(attributes.get("from_trusted")),
        moviehash_match=bool(attributes.get("moviehash_match")),
        ai_translated=bool(attributes.get("ai_translated")),
        machine_translated=bool(attributes.get("machine_translated")),
        fps=fps,
        feature_title=str(feature.get("title") or ""),
        feature_year=str(feature.get("year") or ""),
        feature_id=str(feature.get("tmdb_id") or feature.get("imdb_id") or ""),
        provider_id=str(item.get("id") or ""),
    )


def search_opensubtitles(
    *,
    query: str = "",
    media_path: str | os.PathLike[str] | None = None,
    imdb_id: str = "",
    tmdb_id: str = "",
    season: int | None = None,
    episode: int | None = None,
    languages: str | Iterable[str] = "en",
    formats: Iterable[str] = SUPPORTED_SUBTITLE_FORMATS,
    limit: int = 20,
) -> list[SubtitleResult]:
    """Search OpenSubtitles by title, IDs, episode, or exact movie hash."""
    try:
        headers = _api_headers()
        params: dict[str, Any] = {}
        if isinstance(languages, str):
            languages = [languages]
        language_values = [str(value).strip() for value in languages if str(value).strip()]
        if language_values:
            params["languages"] = ",".join(language_values)
        if query.strip():
            params["query"] = query.strip()
        if imdb_id.strip():
            normalized_imdb = imdb_id.strip()
            if normalized_imdb.lower().startswith("tt"):
                normalized_imdb = normalized_imdb[2:]
            params["imdb_id"] = normalized_imdb
        if tmdb_id.strip():
            params["tmdb_id"] = tmdb_id.strip()
        if season is not None:
            params["season_number"] = int(season)
        if episode is not None:
            params["episode_number"] = int(episode)
        if media_path:
            path = Path(media_path)
            params["moviehash"] = opensubtitles_hash(path)
            params["moviebytesize"] = path.stat().st_size
        params["order_by"] = "download_count"
        params["order_direction"] = "desc"
        _pace_requests()
        payload = _get_json(f"{OPEN_SUBTITLES_BASE}/subtitles", params=params, headers=headers)
    except ProviderAuthError as exc:
        _set_provider_error("opensubtitles", str(exc))
        return []
    except (ProviderError, OSError, ValueError):
        _set_provider_error("opensubtitles", "OpenSubtitles search failed.")
        return []

    allowed_formats = {
        str(value).lower().lstrip(".") for value in formats
        if str(value).lower().lstrip(".") in SUPPORTED_SUBTITLE_FORMATS
    }
    results: list[SubtitleResult] = []
    seen: set[str] = set()
    for item in (payload or {}).get("data", []) if isinstance(payload, dict) else []:
        result = _subtitle_result(item)
        if not result or result.file_id in seen:
            continue
        if allowed_formats and result.format not in allowed_formats:
            continue
        seen.add(result.file_id)
        results.append(result)
        if len(results) >= max(1, limit):
            break
    _set_provider_error("opensubtitles", "")
    return results


def _get_opensubtitles_token() -> str:
    global _token, _token_key, _base_url
    key = get_media_api_key("opensubtitles")
    username = get_media_api_key("opensubtitles_username")
    password = get_media_api_key("opensubtitles_password")
    if not key:
        raise ProviderAuthError("Missing OpenSubtitles API key.")
    if not username or not password:
        raise ProviderAuthError(
            "OpenSubtitles username and password are required to download subtitles.")
    cache_key = "\0".join((key, username))
    if _token and _token_key == cache_key:
        return _token
    _pace_requests()
    payload = _post_json(
        f"{OPEN_SUBTITLES_BASE}/login",
        {"username": username, "password": password},
        headers=_api_headers(),
    )
    _token = str((payload or {}).get("token") or "")
    _token_key = cache_key
    _base_url = _normalise_base_url(str((payload or {}).get("base_url") or ""))
    if not _token:
        raise ProviderAuthError("OpenSubtitles login did not return a session token.")
    return _token


def _extract_subtitle_bytes(payload: bytes, expected_format: str) -> bytes:
    if payload.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [name for name in archive.namelist()
                     if Path(name).suffix.lower().lstrip(".") == expected_format]
            if not names:
                names = [name for name in archive.namelist()
                         if Path(name).suffix.lower().lstrip(".") in SUPPORTED_SUBTITLE_FORMATS]
            if not names:
                raise ProviderError("OpenSubtitles returned an archive without a subtitle file.")
            return archive.read(names[0])
    if payload.startswith(b"\x1f\x8b"):
        return gzip.decompress(payload)
    return payload


def _write_subtitle_text(payload: bytes, destination: Path, overwrite: bool) -> str:
    if not payload:
        raise ProviderError("OpenSubtitles returned an empty subtitle file.")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("cp1252")
    if not text.strip() or re.search(r"<\s*(html|!doctype)\b", text[:500], re.IGNORECASE):
        raise ProviderError("OpenSubtitles returned an invalid subtitle payload.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(str(destination))
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return str(destination)


def subtitle_output_path(media_path: str | os.PathLike[str], result: SubtitleResult) -> Path:
    """Return the deterministic side-by-side filename for a subtitle."""
    path = Path(media_path)
    language = re.sub(r"[^A-Za-z0-9-]+", "", result.language or "und") or "und"
    extension = result.format if result.format in SUPPORTED_SUBTITLE_FORMATS else "srt"
    return path.with_name(f"{path.stem}.{language}.{extension}")


def download_opensubtitle(
    result: SubtitleResult,
    media_path: str | os.PathLike[str],
    *,
    destination: str | os.PathLike[str] | None = None,
    overwrite: bool = False,
) -> str:
    """Download one reviewed subtitle beside its media file."""
    if not result.file_id:
        raise ValueError("Subtitle result has no downloadable file ID.")
    try:
        token = _get_opensubtitles_token()
        _pace_requests()
        payload = _post_json(
            f"{_base_url}/download",
            {"file_id": str(result.file_id)},
            headers=_api_headers(token),
        )
        link = str((payload or {}).get("link") or (payload or {}).get("url") or "")
        if not link:
            raise ProviderError("OpenSubtitles did not return a download link.")
        _pace_requests()
        response = _get_session().get(link, headers=_api_headers(token), timeout=20)
        response.raise_for_status()
        raw = _extract_subtitle_bytes(response.content, result.format)
        output = Path(destination) if destination else subtitle_output_path(media_path, result)
        saved = _write_subtitle_text(raw, output, overwrite)
        _set_provider_error("opensubtitles", "")
        return saved
    except ProviderAuthError as exc:
        _set_provider_error("opensubtitles", str(exc))
        raise
    except (ProviderError, OSError, ValueError) as exc:
        _set_provider_error("opensubtitles", "OpenSubtitles download failed.")
        if isinstance(exc, (FileExistsError, ValueError)):
            raise
        raise ProviderError(str(exc)) from exc


def chapters_from_episodes(episodes: Iterable[Any]) -> list[Chapter]:
    """Normalize TMDb/EpisodeResult records into sidecar chapter records."""
    chapters = []
    for number, episode in enumerate(episodes, start=1):
        title = str(getattr(episode, "title", "") or getattr(episode, "series", "") or "Untitled")
        chapters.append(Chapter(
            number=number,
            title=title,
            season=int(getattr(episode, "season", 0) or 0),
            episode=int(getattr(episode, "episode", 0) or 0),
            air_date=str(getattr(episode, "date", "") or ""),
            synopsis=str(getattr(episode, "synopsis", "") or ""),
            tmdb_id=str(getattr(episode, "id_tmdb", "") or ""),
        ))
    return chapters


def write_chapter_sidecar(
    media_path: str | os.PathLike[str],
    chapters: Iterable[Chapter],
    *,
    source: str = "tmdb",
    overwrite: bool = True,
) -> str:
    """Write a reviewable, atomic ``.chapters.json`` sidecar beside media."""
    path = Path(media_path)
    sidecar = path.with_name(f"{path.stem}.chapters.json")
    if sidecar.exists() and not overwrite:
        raise FileExistsError(str(sidecar))
    chapter_list = [asdict(chapter) for chapter in chapters]
    payload = {
        "schema_version": CHAPTER_SCHEMA_VERSION,
        "source": source,
        "media_file": path.name,
        "chapters": chapter_list,
    }
    if not save_json_safe(str(sidecar), payload):
        raise OSError(f"Could not write chapter sidecar: {sidecar}")
    return str(sidecar)


__all__ = [
    "CHAPTER_SCHEMA_VERSION", "OPEN_SUBTITLES_BASE", "SubtitleResult", "Chapter",
    "SUPPORTED_SUBTITLE_FORMATS", "chapters_from_episodes", "download_opensubtitle",
    "opensubtitles_hash", "search_opensubtitles", "subtitle_output_path",
    "write_chapter_sidecar",
]
