"""Kodi/Plex-compatible NFO sidecar generation from normalized metadata."""
from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class NfoError(RuntimeError):
    """Raised when an NFO sidecar cannot be generated safely."""


@dataclass(frozen=True)
class NfoPreview:
    path: str
    exists: bool
    changed: bool
    xml: str


@dataclass(frozen=True)
class NfoWriteResult:
    path: str
    written: bool
    skipped: bool = False
    overwritten: bool = False
    message: str = ''

    def as_dict(self) -> dict:
        return {
            'path': self.path,
            'written': self.written,
            'skipped': self.skipped,
            'overwritten': self.overwritten,
            'message': self.message,
        }


def _mapping(metadata) -> dict:
    if isinstance(metadata, Mapping):
        data = dict(metadata)
    elif hasattr(metadata, 'to_dict') and callable(metadata.to_dict):
        data = dict(metadata.to_dict())
    elif hasattr(metadata, '__dict__'):
        data = dict(vars(metadata))
    else:
        raise NfoError('metadata must be a mapping or a normalized provider result')
    nested = data.get('fields')
    if isinstance(nested, Mapping):
        for key, value in nested.items():
            data.setdefault(key, value)
    return data


def _value(data: dict, *keys: str, default=''):
    for key in keys:
        value = data.get(key)
        if value not in (None, ''):
            return value
    return default


def _text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, Mapping):
        return _text(value.get('value') or value.get('name') or '')
    return str(value).strip()


def _values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        value = value.get('name') or value.get('value') or ''
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = str(value).replace(';', ',').split(',')
    return list(dict.fromkeys(_text(item) for item in values if _text(item)))


def _kind(data: dict, requested: str | None = None) -> str:
    if requested and requested != 'auto':
        return requested.casefold()
    media_type = _text(_value(data, 'media_type', 'type')).casefold()
    if media_type in {'episode', 'tv episode'}:
        return 'episode'
    if media_type in {'tvshow', 'tv show', 'series'}:
        return 'tvshow'
    if media_type in {'audio', 'music', 'musicvideo'}:
        return 'musicvideo'
    if media_type in {'book', 'audiobook', 'ebook'}:
        return 'book'
    if _value(data, 'season', 'season_number') not in (None, ''):
        return 'episode'
    return 'movie'


def _add(parent: ET.Element, tag: str, value) -> ET.Element | None:
    text = _text(value)
    if not text:
        return None
    element = ET.SubElement(parent, tag)
    element.text = text
    return element


def _add_values(parent: ET.Element, tag: str, values) -> None:
    for value in _values(values):
        _add(parent, tag, value)


def _add_unique_ids(root: ET.Element, data: dict) -> None:
    identifiers = (
        ('tmdb', ('id_tmdb', 'tmdb_id', 'id_tmdb_movie', 'id_tmdb_show')),
        ('imdb', ('id_imdb', 'imdb_id')),
        ('tvdb', ('id_tvdb', 'tvdb_id')),
        ('tvmaze', ('id_tvmaze', 'tvmaze_id')),
        ('musicbrainz', ('id_musicbrainz', 'musicbrainz_id')),
        ('openlibrary', ('id_openlibrary', 'openlibrary_id')),
        ('googlebooks', ('id_googlebooks', 'googlebooks_id')),
    )
    first = True
    for provider, keys in identifiers:
        value = _value(data, *keys)
        if value in (None, ''):
            continue
        attributes = {'type': provider}
        if first:
            attributes['default'] = 'true'
            first = False
        element = _add(root, 'uniqueid', value)
        if element is not None:
            element.attrib.update(attributes)


def build_nfo_xml(metadata, *, kind: str | None = None) -> str:
    """Build UTF-8 NFO XML for movie, TV, music-video, or book metadata."""
    data = _mapping(metadata)
    media_kind = _kind(data, kind)
    root_name = {
        'movie': 'movie',
        'tvshow': 'tvshow',
        'episode': 'episodedetails',
        'musicvideo': 'musicvideo',
        'book': 'book',
    }.get(media_kind)
    if not root_name:
        raise NfoError(f'unsupported NFO kind: {media_kind}')
    root = ET.Element(root_name)

    title = _value(data, 'title', 'name', 'episode_title')
    _add(root, 'title', title)
    _add(root, 'originaltitle', _value(data, 'original_title', 'originaltitle'))
    _add(root, 'year', _value(data, 'year', 'published', 'publication_year'))
    _add(root, 'plot', _value(data, 'plot', 'synopsis', 'description', 'summary'))
    _add(root, 'outline', _value(data, 'outline', 'tagline'))
    _add_values(root, 'genre', _value(data, 'genres', 'genre'))
    _add(root, 'thumb', _value(data, 'cover_url', 'poster_url', 'thumb'))
    _add(root, 'runtime', _value(data, 'runtime', 'duration'))
    _add(root, 'studio', _value(data, 'studio', 'publisher'))
    _add(root, 'premiered', _value(data, 'premiered', 'date', 'aired', 'published'))
    _add_unique_ids(root, data)

    if media_kind in {'tvshow', 'episode'}:
        _add(root, 'showtitle', _value(data, 'series', 'showtitle', 'show_title'))
    if media_kind == 'episode':
        _add(root, 'season', _value(data, 'season', 'season_number'))
        _add(root, 'episode', _value(data, 'episode', 'episode_number'))
        _add(root, 'aired', _value(data, 'aired', 'date', 'air_date'))
    if media_kind == 'book':
        _add_values(root, 'author', _value(data, 'authors', 'author', 'creator'))
        _add(root, 'isbn', _value(data, 'isbn', 'isbn13', 'isbn10'))
        _add(root, 'language', _value(data, 'language', 'lang'))
        _add(root, 'series', _value(data, 'series'))
    if media_kind == 'musicvideo':
        _add(root, 'artist', _value(data, 'artist', 'artists'))
        _add(root, 'album', _value(data, 'album'))
        _add(root, 'track', _value(data, 'track', 'track_number'))
        _add(root, 'releasedate', _value(data, 'date', 'released', 'published'))

    _add(root, 'website', _value(data, 'source_url', 'source', 'url', 'website'))
    ET.indent(root, space='  ')
    return ET.tostring(root, encoding='unicode', xml_declaration=True)


def nfo_sidecar_path(media_path: str | os.PathLike[str], output_path: str | os.PathLike[str] | None = None) -> Path:
    source = Path(media_path).expanduser().resolve()
    if output_path:
        return Path(output_path).expanduser().resolve()
    return source.with_suffix('.nfo')


def preview_nfo_sidecar(media_path: str | os.PathLike[str], metadata, *,
                        kind: str | None = None,
                        output_path: str | os.PathLike[str] | None = None) -> NfoPreview:
    """Build an NFO proposal and compare it with an existing sidecar."""
    target = nfo_sidecar_path(media_path, output_path)
    xml = build_nfo_xml(metadata, kind=kind)
    try:
        existing = target.read_text(encoding='utf-8') if target.is_file() else ''
    except OSError as exc:
        raise NfoError(f'could not read existing NFO sidecar: {exc}') from exc
    return NfoPreview(str(target), target.is_file(), existing != xml, xml)


def write_nfo_sidecar(media_path: str | os.PathLike[str], metadata, *,
                      kind: str | None = None,
                      output_path: str | os.PathLike[str] | None = None,
                      overwrite: bool = True) -> NfoWriteResult:
    """Atomically write a `.nfo` beside a media file or to an explicit path."""
    source = Path(media_path).expanduser().resolve()
    if not source.is_file():
        raise NfoError(f'media file does not exist: {source}')
    target = nfo_sidecar_path(source, output_path)
    had_existing = target.is_file()
    if target.exists() and not overwrite:
        return NfoWriteResult(str(target), False, skipped=True, message='NFO sidecar already exists')
    xml = build_nfo_xml(metadata, kind=kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.unifile-nfo-', suffix='.tmp', dir=str(target.parent))
    os.close(fd)
    try:
        with open(temp_path, 'w', encoding='utf-8', newline='') as stream:
            stream.write(xml)
        os.replace(temp_path, target)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass
    return NfoWriteResult(
        str(target), True, overwritten=had_existing, message='NFO sidecar written',
    )


def metadata_from_json(path: str | os.PathLike[str]) -> dict:
    """Load a JSON object for the headless NFO command."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise NfoError(f'could not read metadata JSON: {exc}') from exc
    if not isinstance(data, dict):
        raise NfoError('metadata JSON must contain an object')
    return data


# Short aliases for integrations and scripts.
build_nfo = build_nfo_xml
write_nfo = write_nfo_sidecar
