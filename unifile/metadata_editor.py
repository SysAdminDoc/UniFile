"""Batch metadata editing with reviewable, sidecar-first writes.

The editor deliberately writes UniFile-managed XMP sidecars instead of
rewriting source files. This keeps RAW files and formats without a safe writer
editable while retaining the original bytes for a later application-specific
workflow. Every field change is recorded in the existing embedding log with
its previous value so a whole batch or an individual field can be restored.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe
from unifile.metadata import MetadataExtractor
from unifile.xmp_writer import read_sidecar, write_editable_fields

_EMBED_LOG = os.path.join(_APP_DATA_DIR, 'embed_log.json')

EDITABLE_FIELDS = (
    ('title', 'Title'),
    ('description', 'Description'),
    ('author', 'Author'),
    ('keywords', 'Keywords'),
    ('category', 'Category'),
    ('rating', 'Rating'),
    ('copyright', 'Copyright'),
    ('date_taken', 'Date Taken'),
    ('location', 'Location'),
    ('flag', 'Review Flag'),
)
EDITABLE_FIELD_KEYS = frozenset(key for key, _label in EDITABLE_FIELDS)


def _text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, list | tuple | set):
        return '; '.join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def read_editable_metadata(filepath: str) -> dict[str, str]:
    """Return the current values shown by the batch editor for one file."""
    values = {key: '' for key in EDITABLE_FIELD_KEYS}
    try:
        extracted = MetadataExtractor.extract(filepath)
    except Exception:
        extracted = {}
    try:
        sidecar = read_sidecar(filepath)
    except Exception:
        sidecar = {}

    aliases = {
        'title': ('title', 'name'),
        'description': ('description', 'subject'),
        'author': ('author', 'creator', 'artist'),
        'copyright': ('copyright',),
        'date_taken': ('date_taken', 'creation_date', 'created'),
        'location': ('location', 'gps_location'),
    }
    for field, candidates in aliases.items():
        for candidate in candidates:
            if extracted.get(candidate) not in (None, ''):
                values[field] = _text(extracted[candidate])
                break

    values['keywords'] = _text(extracted.get('keywords'))
    values['category'] = _text(extracted.get('category'))
    values['rating'] = _text(extracted.get('rating') or extracted.get('_rating'))
    values['flag'] = _text(extracted.get('flag') or extracted.get('_flag'))

    custom = sidecar.get('fields', {})
    if isinstance(custom, dict):
        for field in EDITABLE_FIELD_KEYS:
            if field in custom:
                values[field] = _text(custom[field])
    if sidecar.get('tags') is not None:
        values['keywords'] = _text(sidecar.get('tags'))
    for field in ('category', 'rating', 'flag'):
        if sidecar.get(field) not in (None, ''):
            values[field] = _text(sidecar[field])
    return values


def _load_log(log_path: str) -> list:
    return load_json_safe(log_path, [], expected_type=list)


def _save_log(log_path: str, entries: list) -> bool:
    return save_json_safe(log_path, entries[-500:])


def _append_log(log_path: str, record: dict) -> bool:
    entries = _load_log(log_path)
    entries.append(record)
    return _save_log(log_path, entries)


def apply_metadata_changes(changes: list[dict], *, log_path: str | None = None) -> dict:
    """Apply proposed field changes and append one reversible batch record.

    Each input change contains ``filepath``, ``field`` and ``new``. ``old`` is
    refreshed from disk immediately before writing so a stale grid cannot
    silently overwrite a newer sidecar value.
    """
    log_path = log_path or _EMBED_LOG
    pending: dict[tuple[str, str], str] = {}
    invalid = 0
    for change in changes or []:
        filepath = os.path.abspath(str(change.get('filepath', '')).strip())
        field = str(change.get('field', '')).strip().lower()
        if not filepath or field not in EDITABLE_FIELD_KEYS:
            invalid += 1
            continue
        pending[(filepath, field)] = _text(change.get('new'))

    grouped: dict[str, dict[str, str]] = {}
    records_by_path: dict[str, list[dict]] = {}
    skipped = invalid
    for (filepath, field), new_value in pending.items():
        current = read_editable_metadata(filepath).get(field, '')
        if current == new_value:
            skipped += 1
            continue
        grouped.setdefault(filepath, {})[field] = new_value
        records_by_path.setdefault(filepath, []).append({
            'filepath': filepath,
            'field': field,
            'old': current,
            'new': new_value,
        })

    applied: list[dict] = []
    failed: list[dict] = []
    for filepath, fields in grouped.items():
        if write_editable_fields(filepath, fields):
            applied.extend(records_by_path[filepath])
        else:
            failed.extend(records_by_path[filepath])

    batch_id = str(uuid.uuid4()) if applied else ''
    if applied or failed:
        _append_log(log_path, {
            'type': 'metadata_batch',
            'batch_id': batch_id,
            'timestamp': datetime.now().isoformat(),
            'status': 'applied' if applied else 'failed',
            'changes': applied,
            'failed_changes': failed,
        })
    return {
        'batch_id': batch_id,
        'success': len(applied),
        'failed': len(failed),
        'skipped': skipped,
        'changes': applied,
    }


def undo_metadata_changes(changes: list[dict]) -> dict:
    """Restore the ``old`` value for each field record, independently."""
    grouped: dict[str, dict[str, str]] = {}
    invalid = 0
    for change in changes or []:
        filepath = os.path.abspath(str(change.get('filepath', '')).strip())
        field = str(change.get('field', '')).strip().lower()
        if not filepath or field not in EDITABLE_FIELD_KEYS:
            invalid += 1
            continue
        grouped.setdefault(filepath, {})[field] = _text(change.get('old'))

    restored = 0
    failed = invalid
    for filepath, fields in grouped.items():
        if write_editable_fields(filepath, fields):
            restored += len(fields)
        else:
            failed += len(fields)
    return {'restored': restored, 'failed': failed}


def undo_metadata_batch(batch_id: str, *, fields: set[tuple[str, str]] | None = None,
                        log_path: str | None = None) -> dict:
    """Undo all or selected fields in a batch and update its log record."""
    log_path = log_path or _EMBED_LOG
    entries = _load_log(log_path)
    record = next((item for item in reversed(entries)
                   if item.get('type') == 'metadata_batch'
                   and item.get('batch_id') == batch_id), None)
    if not record or record.get('status') not in {'applied', 'partially-undone'}:
        return {'restored': 0, 'failed': 1, 'status': 'unavailable'}
    changes = record.get('changes', [])
    if fields is not None:
        changes = [
            change for change in changes
            if (os.path.abspath(str(change.get('filepath', ''))),
                str(change.get('field', '')).lower()) in fields
        ]
    if not changes:
        return {'restored': 0, 'failed': 0, 'status': record.get('status', 'applied')}
    result = undo_metadata_changes(changes)
    if result['failed'] == 0:
        remaining = [change for change in record.get('changes', []) if change not in changes]
        record['changes'] = remaining
        record['status'] = 'undone' if not remaining else 'partially-undone'
        record.setdefault('undone_fields', []).extend(changes)
        record['undone_at'] = datetime.now().isoformat()
        _save_log(log_path, entries)
    return {**result, 'status': record.get('status', 'applied')}
