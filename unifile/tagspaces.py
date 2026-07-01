"""TagSpaces .ts sidecar import/export.

TagSpaces stores per-file metadata in `.ts/<filename>.json` sidecar files.
Schema: {"tags": [{"title": "...", "type": "sidecar", "color": "#hex",
         "textcolor": "#hex"}], "description": "..."}

Folder-level metadata lives in `.ts/tsm.json` with the same tag/description
schema applied to the containing directory.

Saved searches are stored as JSON objects with ``textQuery``, ``fileTypes``,
``tagTimePeriod``, etc. fields.  UniFile maps the subset it understands and
reports unsupported fields so the caller can surface warnings.

This module provides bidirectional conversion between TagSpaces sidecars
and UniFile's tag library without moving original files.
"""
import json
import os
from pathlib import Path

_TS_DIR = '.ts'


def _sidecar_path(file_path: str) -> Path:
    """Return the expected .ts sidecar path for a file."""
    p = Path(file_path)
    return p.parent / _TS_DIR / f"{p.name}.json"


def read_sidecar(file_path: str) -> dict | None:
    """Read a TagSpaces sidecar for the given file. Returns None if absent."""
    sc = _sidecar_path(file_path)
    if not sc.is_file():
        return None
    try:
        data = json.loads(sc.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def write_sidecar(file_path: str, tags: list[str], description: str = '',
                  tag_colors: dict[str, str] | None = None) -> Path:
    """Write a TagSpaces sidecar alongside the original file.

    Args:
        file_path: Path to the original file.
        tags: List of tag name strings.
        description: Optional description text.
        tag_colors: Optional {tag_name: "#hex_color"} mapping.

    Returns the path to the written sidecar file.
    """
    sc = _sidecar_path(file_path)
    sc.parent.mkdir(parents=True, exist_ok=True)

    existing = read_sidecar(file_path) or {}
    colors = tag_colors or {}

    tag_objects = []
    for t in tags:
        obj = {'title': t, 'type': 'sidecar'}
        if t in colors:
            obj['color'] = colors[t]
            obj['textcolor'] = '#ffffff'
        tag_objects.append(obj)

    existing['tags'] = tag_objects
    if description:
        existing['description'] = description
    elif 'description' not in existing:
        existing['description'] = ''

    sc.write_text(json.dumps(existing, indent=2, ensure_ascii=False),
                  encoding='utf-8')
    return sc


def extract_tags(sidecar_data: dict) -> list[str]:
    """Extract tag names from a parsed sidecar dict."""
    tags = sidecar_data.get('tags', [])
    return [t['title'] for t in tags if isinstance(t, dict) and 'title' in t]


def extract_description(sidecar_data: dict) -> str:
    """Extract description from a parsed sidecar dict."""
    return sidecar_data.get('description', '')


def extract_tag_colors(sidecar_data: dict) -> dict[str, str]:
    """Extract {tag_name: color_hex} from a parsed sidecar dict."""
    result = {}
    for t in sidecar_data.get('tags', []):
        if isinstance(t, dict) and 'title' in t and 'color' in t:
            result[t['title']] = t['color']
    return result


def scan_directory_sidecars(directory: str) -> list[tuple[str, dict]]:
    """Find all TagSpaces sidecars under a directory.

    Returns [(original_file_path, sidecar_data), ...] for files where
    the original file exists alongside the sidecar.
    """
    results = []
    for dirpath, dirnames, filenames in os.walk(directory):
        ts_dir = os.path.join(dirpath, _TS_DIR)
        if not os.path.isdir(ts_dir):
            continue
        try:
            sidecar_files = os.listdir(ts_dir)
        except OSError:
            continue
        for sc_name in sidecar_files:
            if not sc_name.endswith('.json') or sc_name in ('tsm.json', 'tsl.json'):
                continue
            original_name = sc_name[:-5]  # strip .json
            original_path = os.path.join(dirpath, original_name)
            if not os.path.exists(original_path):
                continue
            sc_path = os.path.join(ts_dir, sc_name)
            try:
                data = json.loads(Path(sc_path).read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    results.append((original_path, data))
            except (json.JSONDecodeError, OSError):
                continue
    return results


def dry_run_import(directory: str) -> list[dict]:
    """Preview what a TagSpaces import would produce without touching the DB.

    Returns a list of dicts: [{file_path, tags, description, colors}, ...]
    """
    sidecars = scan_directory_sidecars(directory)
    preview = []
    for file_path, data in sidecars:
        tags = extract_tags(data)
        desc = extract_description(data)
        colors = extract_tag_colors(data)
        if tags or desc:
            preview.append({
                'file_path': file_path,
                'tags': tags,
                'description': desc,
                'colors': colors,
            })
    return preview


def import_to_library(library, directory: str) -> int:
    """Import TagSpaces sidecars into a UniFile tag library.

    For each file with a sidecar:
    - Creates or finds a tag library entry for the file
    - Creates tags from the sidecar (if they don't exist)
    - Applies the tags to the entry
    - Sets the description as the 'notes' field

    Returns the number of entries imported.
    """
    sidecars = scan_directory_sidecars(directory)
    imported = 0
    for file_path, data in sidecars:
        tags = extract_tags(data)
        desc = extract_description(data)
        if not tags and not desc:
            continue
        entry = library.get_entry_by_path(file_path)
        if not entry:
            entry = library.add_entry(file_path)
        if not entry:
            continue
        if tags:
            tag_ids = []
            for tag_name in tags:
                tag = library.get_tag_by_name(tag_name)
                if not tag:
                    tag = library.add_tag(tag_name)
                if tag:
                    tag_ids.append(tag.id)
            if tag_ids:
                library.add_tags_to_entry(entry.id, tag_ids)
        if desc:
            library.set_entry_field(entry.id, 'notes', desc)
        imported += 1
    return imported


def export_from_library(library, directory: str,
                        entry_ids: list[int] | None = None) -> int:
    """Export UniFile tag library entries as TagSpaces sidecars.

    For each entry (optionally filtered by entry_ids), writes a `.ts/<name>.json`
    sidecar alongside the original file if it has tags.

    Returns the number of sidecars written.
    """
    if entry_ids:
        entries = [library.get_entry(eid) for eid in entry_ids]
        entries = [e for e in entries if e is not None]
    else:
        entries = library.get_all_entries(limit=100000)

    exported = 0
    for entry in entries:
        file_path = str(entry.path)
        if directory and not file_path.startswith(directory):
            continue
        tag_names = [t.name for t in entry.tags]
        if not tag_names:
            continue
        fields = library.get_entry_fields(entry.id)
        desc = fields.get('notes', '') or fields.get('description', '')
        write_sidecar(file_path, tag_names, description=desc)
        exported += 1
    return exported


# ── Folder-level metadata (.ts/tsm.json) ────────────────────────────────────

_TSM_FILE = 'tsm.json'


def read_folder_metadata(folder_path: str) -> dict | None:
    """Read TagSpaces folder metadata from `<folder>/.ts/tsm.json`.

    Returns the parsed dict or None if the file is absent/invalid.
    """
    tsm = Path(folder_path) / _TS_DIR / _TSM_FILE
    if not tsm.is_file():
        return None
    try:
        data = json.loads(tsm.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def write_folder_metadata(folder_path: str, tags: list[str],
                          description: str = '',
                          tag_colors: dict[str, str] | None = None) -> Path:
    """Write TagSpaces folder metadata to `<folder>/.ts/tsm.json`.

    Returns the path to the written tsm.json file.
    """
    tsm = Path(folder_path) / _TS_DIR / _TSM_FILE
    tsm.parent.mkdir(parents=True, exist_ok=True)

    existing = read_folder_metadata(folder_path) or {}
    colors = tag_colors or {}

    tag_objects = []
    for t in tags:
        obj = {'title': t, 'type': 'sidecar'}
        if t in colors:
            obj['color'] = colors[t]
            obj['textcolor'] = '#ffffff'
        tag_objects.append(obj)

    existing['tags'] = tag_objects
    if description:
        existing['description'] = description
    elif 'description' not in existing:
        existing['description'] = ''

    tsm.write_text(json.dumps(existing, indent=2, ensure_ascii=False),
                   encoding='utf-8')
    return tsm


def scan_folder_metadata(directory: str) -> list[tuple[str, dict]]:
    """Find all TagSpaces folder metadata (tsm.json) under a directory tree.

    Returns [(folder_path, metadata_dict), ...] for each folder that has
    a `.ts/tsm.json` file.
    """
    results = []
    for dirpath, dirnames, _filenames in os.walk(directory):
        tsm_path = os.path.join(dirpath, _TS_DIR, _TSM_FILE)
        if not os.path.isfile(tsm_path):
            continue
        try:
            data = json.loads(Path(tsm_path).read_text(encoding='utf-8'))
            if isinstance(data, dict):
                results.append((dirpath, data))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def dry_run_import_folders(directory: str) -> list[dict]:
    """Preview folder-level metadata import without touching the DB.

    Returns [{folder_path, tags, description, colors, unsupported_fields}, ...]
    """
    folder_meta = scan_folder_metadata(directory)
    preview = []
    for folder_path, data in folder_meta:
        tags = extract_tags(data)
        desc = extract_description(data)
        colors = extract_tag_colors(data)
        unsupported = [k for k in data if k not in ('tags', 'description', 'id',
                                                     'perspective', 'color')]
        if tags or desc:
            preview.append({
                'folder_path': folder_path,
                'tags': tags,
                'description': desc,
                'colors': colors,
                'unsupported_fields': unsupported,
            })
    return preview


def import_folders_to_library(library, directory: str) -> int:
    """Import TagSpaces folder metadata into a UniFile tag library.

    Creates entries for folders that have tsm.json metadata and applies
    their tags. Returns the number of folder entries imported.
    """
    folder_meta = scan_folder_metadata(directory)
    imported = 0
    for folder_path, data in folder_meta:
        tags = extract_tags(data)
        desc = extract_description(data)
        if not tags and not desc:
            continue
        entry = library.get_entry_by_path(folder_path)
        if not entry:
            entry = library.add_entry(folder_path)
        if not entry:
            continue
        if tags:
            tag_ids = []
            for tag_name in tags:
                tag = library.get_tag_by_name(tag_name)
                if not tag:
                    tag = library.add_tag(tag_name)
                if tag:
                    tag_ids.append(tag.id)
            if tag_ids:
                library.add_tags_to_entry(entry.id, tag_ids)
        if desc:
            library.set_entry_field(entry.id, 'notes', desc)
        imported += 1
    return imported


def export_folder_metadata_from_library(library, directory: str) -> int:
    """Export UniFile folder entries as TagSpaces tsm.json files.

    For each entry that points to a directory inside *directory*, writes
    a `.ts/tsm.json` sidecar with the entry's tags and description.

    Returns the number of tsm.json files written.
    """
    entries = library.get_all_entries(limit=100000)
    exported = 0
    for entry in entries:
        folder_path = str(entry.path)
        if not os.path.isdir(folder_path):
            continue
        if directory and not folder_path.startswith(directory):
            continue
        tag_names = [t.name for t in entry.tags]
        if not tag_names:
            continue
        fields = library.get_entry_fields(entry.id)
        desc = fields.get('notes', '') or fields.get('description', '')
        write_folder_metadata(folder_path, tag_names, description=desc)
        exported += 1
    return exported


# ── Saved Searches ───────────────────────────────────────────────────────────

_SUPPORTED_SEARCH_FIELDS = frozenset({
    'textQuery', 'fileTypes', 'tagsAND', 'tagsOR', 'tagsNOT',
    'searchBoxing',
})


def parse_saved_search(search_data: dict) -> dict:
    """Convert a TagSpaces saved search into a UniFile query dict.

    Returns:
        {
            'name': str,
            'query': str,           # UniFile search_entries() compatible
            'original': dict,       # raw TagSpaces data for round-trip
            'unsupported_fields': [str],
        }
    """
    name = search_data.get('title', search_data.get('uuid', 'Untitled'))

    parts = []
    text_q = search_data.get('textQuery', '').strip()
    if text_q:
        parts.append(text_q)

    for tag_obj in search_data.get('tagsAND', []):
        t = tag_obj.get('title', '') if isinstance(tag_obj, dict) else str(tag_obj)
        if t:
            parts.append(f'tag:{t}')

    for tag_obj in search_data.get('tagsOR', []):
        t = tag_obj.get('title', '') if isinstance(tag_obj, dict) else str(tag_obj)
        if t:
            parts.append(f'tag:{t}')

    file_types = search_data.get('fileTypes', [])
    if isinstance(file_types, list):
        for ft in file_types:
            parts.append(f'ext:{ft}')

    query = ' AND '.join(parts) if parts else ''

    all_keys = set(search_data.keys()) - {'title', 'uuid'}
    unsupported = sorted(all_keys - _SUPPORTED_SEARCH_FIELDS)

    return {
        'name': name,
        'query': query,
        'original': search_data,
        'unsupported_fields': unsupported,
    }


def import_saved_searches(search_list: list[dict]) -> list[dict]:
    """Parse a list of TagSpaces saved search objects.

    Args:
        search_list: List of TagSpaces search definition dicts.

    Returns list of parsed search dicts from ``parse_saved_search()``.
    """
    return [parse_saved_search(s) for s in search_list if isinstance(s, dict)]


def export_saved_searches(queries: list[dict]) -> list[dict]:
    """Convert UniFile saved searches to TagSpaces format.

    Args:
        queries: List of dicts with 'name' and 'query' keys.

    Returns a list of TagSpaces-format search dicts.
    """
    results = []
    for q in queries:
        name = q.get('name', 'Untitled')
        query_str = q.get('query', '')

        ts_search = {'title': name, 'textQuery': '', 'tagsAND': [],
                     'tagsOR': [], 'fileTypes': []}

        remaining_parts = []
        for part in query_str.split(' AND '):
            part = part.strip()
            if part.startswith('tag:'):
                ts_search['tagsAND'].append({'title': part[4:], 'type': 'sidecar'})
            elif part.startswith('ext:'):
                ts_search['fileTypes'].append(part[4:])
            else:
                remaining_parts.append(part)

        ts_search['textQuery'] = ' '.join(remaining_parts)
        results.append(ts_search)

    return results


def read_saved_searches_file(filepath: str) -> list[dict]:
    """Read a TagSpaces saved searches JSON export file.

    The file may be a JSON array of search objects or a dict with a
    ``searches`` key containing the array.
    """
    try:
        data = json.loads(Path(filepath).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get('searches', data.get('searchQueries', []))
    return []


def write_saved_searches_file(filepath: str, searches: list[dict]) -> Path:
    """Write TagSpaces saved searches to a JSON file."""
    p = Path(filepath)
    p.write_text(json.dumps(searches, indent=2, ensure_ascii=False),
                 encoding='utf-8')
    return p
