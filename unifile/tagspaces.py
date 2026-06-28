"""TagSpaces .ts sidecar import/export.

TagSpaces stores per-file metadata in `.ts/<filename>.json` sidecar files.
Schema: {"tags": [{"title": "...", "type": "sidecar", "color": "#hex",
         "textcolor": "#hex"}], "description": "..."}

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
