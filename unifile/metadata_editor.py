"""Batch metadata editing with reviewable, sidecar-first writes.

The editor deliberately writes UniFile-managed XMP sidecars instead of
rewriting source files. This keeps RAW files and formats without a safe writer
editable while retaining the original bytes for a later application-specific
workflow. Every field change is recorded in the existing embedding log with
its previous value so a whole batch or an individual field can be restored.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe
from unifile.metadata import MetadataExtractor
from unifile.xmp_writer import (
    read_sidecar,
    read_sidecar_fields,
    sidecar_path,
    write_editable_fields,
    write_sidecar_fields,
)

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


# ── Raw metadata inspector/editor ────────────────────────────────────────────

@dataclass(frozen=True)
class MetadataField:
    """One format-level metadata field shown by the raw inspector."""

    key: str
    label: str
    source: str
    value: str
    writable: bool = False
    value_type: str = 'text'

    def as_dict(self) -> dict:
        return {
            'key': self.key,
            'label': self.label,
            'source': self.source,
            'value': self.value,
            'writable': self.writable,
            'value_type': self.value_type,
        }


_RAW_IMAGE_EXTS = {'.jpg', '.jpeg', '.tif', '.tiff'}
_PIEXIF_IFDS = ('0th', 'Exif', 'GPS', '1st')
_EXIF_POINTER_TAGS = {34665, 34853, 40965, 513, 514}
_MANAGED_XMP_FIELDS = (
    ('xmp:uf:Field_title', 'Title', 'title'),
    ('xmp:uf:Field_description', 'Description', 'description'),
    ('xmp:uf:Field_author', 'Author', 'author'),
    ('xmp:uf:Field_keywords', 'Keywords', 'keywords'),
    ('xmp:uf:Field_category', 'Category', 'category'),
    ('xmp:uf:Field_rating', 'Rating', 'rating'),
    ('xmp:uf:Field_copyright', 'Copyright', 'copyright'),
    ('xmp:uf:Field_date_taken', 'Date Taken', 'date_taken'),
    ('xmp:uf:Field_location', 'Location', 'location'),
    ('xmp:uf:Field_flag', 'Review Flag', 'flag'),
)
_XMP_PREFIXES = {'x', 'rdf', 'dc', 'xmp', 'uf'}


def _display_metadata_value(value) -> str:
    """Convert library-specific values to a compact, editable string."""
    if value is None:
        return ''
    if isinstance(value, bytes):
        if not value:
            return ''
        has_internal_nul = b'\x00' in value[:-1]
        encodings = ('utf-16le', 'utf-8', 'latin-1') if has_internal_nul else (
            'utf-8', 'utf-16le', 'latin-1'
        )
        for encoding in encodings:
            try:
                text = value.decode(encoding).rstrip('\x00').strip()
                if text and sum(char.isprintable() or char.isspace() for char in text) / len(text) > .8:
                    return text
            except (UnicodeDecodeError, ValueError):
                continue
        return f'<{len(value)} bytes>'
    if isinstance(value, (list, set)):
        return '; '.join(_display_metadata_value(item) for item in value)
    if isinstance(value, tuple):
        if value and all(isinstance(item, tuple) and len(item) == 2 for item in value):
            return '; '.join(f'{item[0]}/{item[1]}' for item in value)
        return '; '.join(_display_metadata_value(item) for item in value)
    return str(value).strip()


def _import_piexif():
    try:
        import piexif
        return piexif
    except ImportError:
        return None


def _piexif_tag_info(piexif, ifd: str, tag_id: int) -> dict:
    try:
        info = piexif.TAGS.get(ifd, {}).get(tag_id, {})
        return info if isinstance(info, dict) else {}
    except (AttributeError, TypeError):
        return {}


def _append_raw_field(fields: list[MetadataField], field: MetadataField) -> None:
    if any(existing.key == field.key for existing in fields):
        return
    fields.append(field)


def _read_exif_fields(filepath: str) -> list[MetadataField]:
    fields: list[MetadataField] = []
    piexif = _import_piexif()
    if piexif and os.path.splitext(filepath)[1].lower() in _RAW_IMAGE_EXTS:
        try:
            exif_data = piexif.load(filepath)
        except Exception:
            exif_data = {}
        for ifd in _PIEXIF_IFDS:
            values = exif_data.get(ifd, {}) if isinstance(exif_data, dict) else {}
            if not isinstance(values, dict):
                continue
            for tag_id, raw_value in values.items():
                if not isinstance(tag_id, int):
                    continue
                info = _piexif_tag_info(piexif, ifd, tag_id)
                label = str(info.get('name') or f'Tag {tag_id}')
                value_type = str(info.get('type') or 'unknown')
                writable = bool(info) and tag_id not in _EXIF_POINTER_TAGS
                _append_raw_field(fields, MetadataField(
                    f'exif:{ifd}:{tag_id}', f'EXIF / {ifd} / {label}', 'EXIF',
                    _display_metadata_value(raw_value), writable, value_type,
                ))
        if fields:
            return fields

    # Pillow can still display EXIF when piexif is not installed.  These
    # fallback rows are deliberately read-only rather than pretending a
    # partial writer can safely preserve every IFD.
    try:
        from PIL import ExifTags, Image
        with Image.open(filepath) as image:
            exif = image.getexif()
            for tag_id, raw_value in exif.items():
                label = ExifTags.TAGS.get(tag_id, f'Tag {tag_id}')
                _append_raw_field(fields, MetadataField(
                    f'exif:0th:{tag_id}', f'EXIF / 0th / {label}', 'EXIF',
                    _display_metadata_value(raw_value), False, 'fallback',
                ))
    except Exception:
        pass
    return fields


def _read_id3_fields(filepath: str) -> list[MetadataField]:
    fields: list[MetadataField] = []
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError
        try:
            audio = ID3(filepath)
        except ID3NoHeaderError:
            return fields
        for frame in audio.values():
            hash_key = str(getattr(frame, 'HashKey', '') or '')
            if not hash_key:
                continue
            frame_id = hash_key.split(':', 1)[0]
            if hasattr(frame, 'text'):
                value = _display_metadata_value(getattr(frame, 'text', []))
                writable = frame_id not in {'APIC', 'PIC', 'GEOB', 'PRIV'}
                value_type = 'text'
            elif hasattr(frame, 'url'):
                value = str(frame.url)
                writable = False
                value_type = 'url'
            else:
                payload = getattr(frame, 'data', b'')
                value = _display_metadata_value(payload)
                writable = False
                value_type = 'binary'
            _append_raw_field(fields, MetadataField(
                f'id3:{hash_key}', f'ID3 / {hash_key}', 'ID3',
                value, writable, value_type,
            ))
    except (ImportError, OSError, ValueError):
        pass
    return fields


def _read_mutagen_fields(filepath: str) -> list[MetadataField]:
    """Read non-MP3 mutagen tags (FLAC, Ogg, MP4, and similar formats)."""
    if os.path.splitext(filepath)[1].lower() == '.mp3':
        return []
    fields: list[MetadataField] = []
    try:
        import mutagen
        audio = mutagen.File(filepath, easy=False)
        tags = getattr(audio, 'tags', None) if audio is not None else None
        if not tags:
            return fields
        for raw_key, raw_value in tags.items():
            key = str(raw_key)
            value = _display_metadata_value(raw_value)
            writable = not isinstance(raw_value, (bytes, bytearray))
            _append_raw_field(fields, MetadataField(
                f'tag:{key}', f'Tag / {key}', 'Mutagen', value, writable, 'text',
            ))
    except (ImportError, OSError, ValueError):
        pass
    return fields


def _read_pdf_fields(filepath: str) -> list[MetadataField]:
    fields: list[MetadataField] = []
    try:
        from pypdf import PdfReader
        metadata = PdfReader(filepath).metadata
        if metadata:
            for raw_key, raw_value in metadata.items():
                key = str(raw_key)
                if not key.startswith('/'):
                    key = '/' + key
                _append_raw_field(fields, MetadataField(
                    f'pdf:{key}', f'PDF / {key}', 'PDF',
                    _display_metadata_value(raw_value), True, 'text',
                ))
    except (ImportError, OSError, ValueError):
        pass
    return fields


def _xmp_field_label(key: str) -> str:
    parts = key.split(':', 2)
    if len(parts) != 3:
        return key
    local = parts[2]
    if local.startswith('Field_'):
        local = local[6:].replace('_', ' ').title()
    elif local.startswith('@'):
        local = local[1:] + ' (attribute)'
    return f'XMP / {parts[1]}:{local}'


def read_metadata_fields(filepath: str) -> list[MetadataField]:
    """Enumerate embedded and sidecar metadata fields for the inspector.

    Format-specific rows are read from the original file.  XMP rows are read
    from the adjacent UniFile sidecar, and managed XMP rows are included even
    when empty so a user can create a field on a file that has no sidecar yet.
    Unsupported binary fields remain visible but are marked read-only.
    """
    filepath = os.path.abspath(str(filepath or '').strip())
    if not filepath or not os.path.isfile(filepath):
        return []
    fields: list[MetadataField] = []
    ext = os.path.splitext(filepath)[1].lower()
    if ext in _RAW_IMAGE_EXTS or ext in {
        '.png', '.webp', '.heic', '.heif', '.dng', '.nef', '.cr2', '.arw', '.tif', '.tiff',
    }:
        fields.extend(_read_exif_fields(filepath))
    if ext == '.mp3':
        fields.extend(_read_id3_fields(filepath))
    elif ext in {'.flac', '.ogg', '.oga', '.opus', '.m4a', '.mp4', '.m4v', '.aac', '.aiff', '.wav'}:
        fields.extend(_read_mutagen_fields(filepath))
    if ext == '.pdf':
        fields.extend(_read_pdf_fields(filepath))

    try:
        sidecar_fields = read_sidecar_fields(filepath)
    except Exception:
        sidecar_fields = {}
    for key, value in sidecar_fields.items():
        _append_raw_field(fields, MetadataField(
            key, _xmp_field_label(key), 'XMP', _display_metadata_value(value),
            key.split(':', 2)[1] in _XMP_PREFIXES, 'text',
        ))
    existing = {field.key for field in fields}
    editable = read_editable_metadata(filepath)
    for key, label, managed_key in _MANAGED_XMP_FIELDS:
        if key in existing:
            continue
        _append_raw_field(fields, MetadataField(
            key, f'XMP / UniFile / {label}', 'XMP', editable.get(managed_key, ''),
            True, 'text',
        ))
    return fields


def _normalise_raw_edits(edits) -> dict[str, str]:
    if isinstance(edits, dict):
        return {str(key).strip(): _text(value) for key, value in edits.items()}
    result: dict[str, str] = {}
    for item in edits or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or item.get('field') or '').strip()
        if key:
            result[key] = _text(item.get('new', item.get('value', '')))
    return result


def _dynamic_xmp_field(key: str, current: str = '') -> MetadataField | None:
    parts = key.split(':', 2)
    if len(parts) == 3 and parts[0] == 'xmp' and parts[1] in _XMP_PREFIXES and parts[2]:
        return MetadataField(key, _xmp_field_label(key), 'XMP', current, True, 'text')
    return None


def preview_metadata_changes(filepath: str, edits) -> dict:
    """Return a reviewable diff without touching the file or sidecar."""
    fields = read_metadata_fields(filepath)
    by_key = {field.key: field for field in fields}
    changes = []
    skipped = 0
    unsupported = []
    for key, new_value in _normalise_raw_edits(edits).items():
        field = by_key.get(key)
        if field is None:
            field = _dynamic_xmp_field(key)
        if field is None:
            unsupported.append({'key': key, 'reason': 'unknown metadata field'})
            continue
        if not field.writable:
            unsupported.append({'key': key, 'reason': 'read-only or unsupported field'})
            continue
        if field.value == new_value:
            skipped += 1
            continue
        changes.append({
            'key': field.key,
            'label': field.label,
            'source': field.source,
            'old': field.value,
            'new': new_value,
        })
    return {
        'filepath': os.path.abspath(str(filepath)),
        'changes': changes,
        'skipped': skipped,
        'unsupported': unsupported,
        'valid': not unsupported,
    }


def _exif_value_from_text(piexif, ifd: str, tag_id: int, value: str):
    info = _piexif_tag_info(piexif, ifd, tag_id)
    type_code = info.get('type')
    if not info:
        raise ValueError(f'unknown EXIF tag {ifd}:{tag_id}')
    if not value:
        return None
    name = str(info.get('name', ''))
    if name.startswith('XP'):
        return value.encode('utf-16le') + b'\x00\x00'
    if type_code == 2 or str(type_code).upper() == 'ASCII':
        return value.encode('ascii', errors='replace') + b'\x00'
    if type_code in {1, 7}:
        if type_code == 7:
            compact = value.replace(' ', '')
            if compact and re.fullmatch(r'[0-9a-fA-F]+', compact) and len(compact) % 2 == 0:
                return bytes.fromhex(compact)
            return value.encode('utf-8')
        parts = [part.strip() for part in re.split(r'[;,]', value) if part.strip()]
        return bytes(int(part, 0) for part in parts)
    if type_code in {3, 4, 8, 9, 11, 12}:
        parts = [part.strip() for part in re.split(r'[;,]', value) if part.strip()]
        numbers = [int(part, 0) for part in parts]
        return numbers[0] if len(numbers) == 1 else tuple(numbers)
    if type_code in {5, 10}:
        parts = [part.strip() for part in re.split(r'[;,]', value) if part.strip()]
        rationals = []
        for part in parts:
            if '/' in part:
                numerator, denominator = part.split('/', 1)
                rationals.append((int(numerator), int(denominator)))
            else:
                fraction = Fraction(float(part)).limit_denominator(1_000_000)
                rationals.append((fraction.numerator, fraction.denominator))
        return rationals[0] if len(rationals) == 1 else tuple(rationals)
    return value.encode('utf-8')


def _write_exif_fields(filepath: str, edits: dict[str, str]) -> bool:
    piexif = _import_piexif()
    if not piexif:
        return False
    try:
        exif_data = piexif.load(filepath)
        for key, value in edits.items():
            parts = key.split(':', 2)
            if len(parts) != 3 or parts[0] != 'exif' or parts[1] not in _PIEXIF_IFDS:
                return False
            ifd, raw_tag_id = parts[1], parts[2]
            tag_id = int(raw_tag_id)
            if tag_id in _EXIF_POINTER_TAGS:
                return False
            values = exif_data.setdefault(ifd, {})
            converted = _exif_value_from_text(piexif, ifd, tag_id, value)
            if converted is None:
                values.pop(tag_id, None)
            else:
                values[tag_id] = converted
        exif_bytes = piexif.dump(exif_data)
        directory = os.path.dirname(filepath) or '.'
        suffix = os.path.splitext(filepath)[1].lower()
        fd, temp_path = tempfile.mkstemp(prefix='.unifile-exif-', suffix=suffix, dir=directory)
        os.close(fd)
        try:
            shutil.copy2(filepath, temp_path)
            piexif.insert(exif_bytes, temp_path)
            os.replace(temp_path, filepath)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return True
    except Exception:
        return False


def _write_id3_fields(filepath: str, edits: dict[str, str]) -> bool:
    try:
        from mutagen.id3 import COMM, ID3, TXXX, Frames
        audio = ID3(filepath)
        for key, value in edits.items():
            hash_key = key[4:] if key.startswith('id3:') else key
            frame_id = hash_key.split(':', 1)[0]
            if not value:
                audio.delall(hash_key)
                continue
            if frame_id == 'TXXX':
                parts = hash_key.split(':', 1)
                if len(parts) != 2:
                    return False
                audio.delall(hash_key)
                audio.add(TXXX(encoding=3, desc=parts[1], text=[value]))
                continue
            if frame_id == 'COMM':
                parts = hash_key.split(':', 2)
                if len(parts) != 3:
                    return False
                audio.delall(hash_key)
                audio.add(COMM(encoding=3, lang=parts[1], desc=parts[2], text=[value]))
                continue
            frame_class = Frames.get(frame_id)
            if frame_class is None:
                return False
            frames = audio.getall(hash_key)
            if not frames or not hasattr(frames[0], 'text'):
                return False
            frame = frames[0]
            frame.encoding = 3
            frame.text = [value]
        directory = os.path.dirname(filepath) or '.'
        suffix = os.path.splitext(filepath)[1].lower()
        fd, temp_path = tempfile.mkstemp(prefix='.unifile-id3-', suffix=suffix, dir=directory)
        os.close(fd)
        try:
            shutil.copy2(filepath, temp_path)
            temp_audio = ID3(temp_path)
            # Re-run against the temporary copy so the source is only replaced
            # after mutagen has serialized every requested frame successfully.
            for key, value in edits.items():
                hash_key = key[4:] if key.startswith('id3:') else key
                frame_id = hash_key.split(':', 1)[0]
                if not value:
                    temp_audio.delall(hash_key)
                elif frame_id == 'TXXX':
                    desc = hash_key.split(':', 1)[1]
                    temp_audio.delall(hash_key)
                    temp_audio.add(TXXX(encoding=3, desc=desc, text=[value]))
                elif frame_id == 'COMM':
                    _prefix, lang, desc = hash_key.split(':', 2)
                    temp_audio.delall(hash_key)
                    temp_audio.add(COMM(encoding=3, lang=lang, desc=desc, text=[value]))
                else:
                    frames = temp_audio.getall(hash_key)
                    if not frames or not hasattr(frames[0], 'text'):
                        return False
                    frames[0].encoding = 3
                    frames[0].text = [value]
            temp_audio.save(temp_path)
            os.replace(temp_path, filepath)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return True
    except Exception:
        return False


def _write_mutagen_fields(filepath: str, edits: dict[str, str]) -> bool:
    try:
        import mutagen
        directory = os.path.dirname(filepath) or '.'
        suffix = os.path.splitext(filepath)[1].lower()
        fd, temp_path = tempfile.mkstemp(prefix='.unifile-tags-', suffix=suffix, dir=directory)
        os.close(fd)
        try:
            shutil.copy2(filepath, temp_path)
            audio = mutagen.File(temp_path, easy=False)
            if audio is None or getattr(audio, 'tags', None) is None:
                return False
            for key, value in edits.items():
                raw_key = key[4:] if key.startswith('tag:') else key
                if value:
                    audio.tags[raw_key] = [value]
                else:
                    audio.tags.pop(raw_key, None)
            audio.save()
            os.replace(temp_path, filepath)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return True
    except Exception:
        return False


def _write_pdf_fields(filepath: str, edits: dict[str, str]) -> bool:
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(filepath)
        writer = PdfWriter()
        writer.append_pages_from_reader(reader)
        metadata = {
            str(key): _display_metadata_value(value)
            for key, value in (reader.metadata or {}).items()
        }
        for key, value in edits.items():
            pdf_key = key[4:] if key.startswith('pdf:') else key
            if not pdf_key.startswith('/'):
                pdf_key = '/' + pdf_key
            if value:
                metadata[pdf_key] = value
            else:
                metadata.pop(pdf_key, None)
        writer.add_metadata(metadata)
        directory = os.path.dirname(filepath) or '.'
        fd, temp_path = tempfile.mkstemp(prefix='.unifile-pdf-', suffix='.pdf', dir=directory)
        os.close(fd)
        try:
            with open(temp_path, 'wb') as stream:
                writer.write(stream)
            os.replace(temp_path, filepath)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return True
    except Exception:
        return False


def _raw_artifact_paths(filepath: str, changes: list[dict]) -> list[str]:
    paths = []
    for change in changes:
        path = sidecar_path(filepath) if change['source'] == 'XMP' else filepath
        if path not in paths:
            paths.append(path)
    return paths


def _backup_artifacts(paths: list[str], batch_id: str, backup_dir: str) -> list[dict]:
    os.makedirs(backup_dir, exist_ok=True)
    manifest = []
    for index, path in enumerate(paths):
        existed = os.path.isfile(path)
        backup = ''
        if existed:
            backup = os.path.join(
                backup_dir, f'{batch_id}-{index}-{os.path.basename(path)}.bak')
            shutil.copy2(path, backup)
        manifest.append({'path': path, 'existed': existed, 'backup': backup})
    return manifest


def _restore_artifacts(manifest: list[dict]) -> tuple[int, int]:
    restored = 0
    failed = 0
    for item in manifest:
        path = str(item.get('path', ''))
        try:
            if item.get('existed'):
                backup = str(item.get('backup', ''))
                if not backup or not os.path.isfile(backup):
                    failed += 1
                    continue
                directory = os.path.dirname(path) or '.'
                fd, temp_path = tempfile.mkstemp(prefix='.unifile-restore-', dir=directory)
                os.close(fd)
                try:
                    shutil.copy2(backup, temp_path)
                    os.replace(temp_path, path)
                finally:
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
            elif os.path.isfile(path):
                os.remove(path)
            restored += 1
        except OSError:
            failed += 1
    return restored, failed


def _group_raw_changes(changes: list[dict]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for change in changes:
        grouped.setdefault(change['source'], {})[change['key']] = change['new']
    return grouped


def apply_metadata_field_changes(filepath: str, edits, *, log_path: str | None = None,
                                 backup_dir: str | None = None) -> dict:
    """Apply a reviewed raw metadata diff with backup and reversible logging."""
    filepath = os.path.abspath(str(filepath or '').strip())
    preview = preview_metadata_changes(filepath, edits)
    if preview['unsupported']:
        return {
            'success': 0,
            'failed': len(preview['unsupported']),
            'skipped': preview['skipped'],
            'changes': [],
            'unsupported': preview['unsupported'],
            'batch_id': '',
        }
    if not preview['changes']:
        return {
            'success': 0,
            'failed': 0,
            'skipped': preview['skipped'],
            'changes': [],
            'unsupported': [],
            'batch_id': '',
        }

    batch_id = str(uuid.uuid4())
    log_path = log_path or _EMBED_LOG
    backup_dir = backup_dir or os.path.join(_APP_DATA_DIR, 'metadata_backups')
    manifest = []
    try:
        manifest = _backup_artifacts(
            _raw_artifact_paths(filepath, preview['changes']), batch_id, backup_dir)
        grouped = _group_raw_changes(preview['changes'])
        writers = {
            'EXIF': _write_exif_fields,
            'ID3': _write_id3_fields,
            'Mutagen': _write_mutagen_fields,
            'PDF': _write_pdf_fields,
            'XMP': write_sidecar_fields,
        }
        for source, source_edits in grouped.items():
            writer = writers.get(source)
            if writer is None or not writer(filepath, source_edits):
                raise RuntimeError(f'{source} writer failed')
    except Exception as exc:
        _restore_artifacts(manifest)
        return {
            'success': 0,
            'failed': len(preview['changes']),
            'skipped': preview['skipped'],
            'changes': [],
            'unsupported': [{'key': '', 'reason': str(exc)}],
            'batch_id': '',
        }

    record = {
        'type': 'metadata_field_batch',
        'batch_id': batch_id,
        'timestamp': datetime.now().isoformat(),
        'filepath': filepath,
        'status': 'applied',
        'changes': preview['changes'],
        'artifacts': manifest,
    }
    _append_log(log_path, record)
    return {
        'success': len(preview['changes']),
        'failed': 0,
        'skipped': preview['skipped'],
        'changes': preview['changes'],
        'unsupported': [],
        'batch_id': batch_id,
        'backup_paths': [item['backup'] for item in manifest if item.get('backup')],
    }


def undo_metadata_field_batch(batch_id: str, *, log_path: str | None = None) -> dict:
    """Restore the exact source/sidecar bytes captured by a raw edit batch."""
    log_path = log_path or _EMBED_LOG
    entries = _load_log(log_path)
    record = next((item for item in reversed(entries)
                   if item.get('type') == 'metadata_field_batch'
                   and item.get('batch_id') == batch_id), None)
    if not record or record.get('status') != 'applied':
        return {'restored': 0, 'failed': 1, 'status': 'unavailable'}
    restored, failed = _restore_artifacts(record.get('artifacts', []))
    if failed == 0:
        record['status'] = 'undone'
        record['undone_at'] = datetime.now().isoformat()
        _save_log(log_path, entries)
    return {'restored': restored, 'failed': failed, 'status': record.get('status', 'applied')}


# Descriptive aliases for callers that do not use the UI's historical
# "batch" terminology.
apply_raw_metadata_changes = apply_metadata_field_changes
undo_raw_metadata_batch = undo_metadata_field_batch
