"""XMP sidecar writer for UniFile.

Writes category, tags, and rating to a .xmp file alongside the original.
If a sidecar already exists, only UniFile-managed fields are updated so that
Lightroom / Adobe / other app metadata is preserved.

Wraps the XMP document with standard <?xpacket ...?> processing instructions
that Adobe and other tools expect, but strips them before parsing so stdlib
ElementTree can read the file without the xml.parsers.expat error.
"""
from __future__ import annotations

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ── Namespace registry ────────────────────────────────────────────────────────
_NS = {
    'x':       'adobe:ns:meta/',
    'rdf':     'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dc':      'http://purl.org/dc/elements/1.1/',
    'xmp':     'http://ns.adobe.com/xap/1.0/',
    'uf':      'http://ns.unifile.io/1.0/',
}
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)

_RDF     = f'{{{_NS["rdf"]}}}'
_DC      = f'{{{_NS["dc"]}}}'
_XMP     = f'{{{_NS["xmp"]}}}'
_UF      = f'{{{_NS["uf"]}}}'
_X       = f'{{{_NS["x"]}}}'

_XPACKET_START_RE = re.compile(rb'<\?xpacket\s+begin[^?]*\?>', re.DOTALL)
_XPACKET_END_RE   = re.compile(rb'<\?xpacket\s+end[^?]*\?>', re.DOTALL)


def _sidecar_path(file_path: str) -> str:
    return file_path + '.xmp'


def sidecar_path(file_path: str) -> str:
    """Return the UniFile XMP sidecar path for *file_path*."""
    return _sidecar_path(file_path)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def _strip_xpacket(raw: bytes) -> bytes:
    raw = _XPACKET_START_RE.sub(b'', raw)
    raw = _XPACKET_END_RE.sub(b'', raw)
    return raw.strip()


def _indent(elem: ET.Element, level: int = 0) -> None:
    """Pretty-print indentation (in-place)."""
    pad = '\n' + '  ' * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + '  '
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad


def _build_fresh_root() -> ET.Element:
    """Build a minimal XMP document root."""
    root = ET.Element(f'{_X}xmpmeta')
    rdf  = ET.SubElement(root, f'{_RDF}RDF')
    desc = ET.SubElement(rdf, f'{_RDF}Description')
    desc.set(f'{_RDF}about', '')
    return root


def _find_desc(root: ET.Element) -> ET.Element | None:
    """Find the first rdf:Description element anywhere in the tree."""
    tag = f'{_RDF}Description'
    if root.tag == tag:
        return root
    for child in root.iter(tag):
        return child
    return None


def _set_text(desc: ET.Element, ns_prefix: str, local: str, value: str) -> None:
    key = f'{ns_prefix}{local}'
    el = desc.find(key)
    if el is None:
        el = ET.SubElement(desc, key)
    el.text = value


def _set_bag(desc: ET.Element, ns_prefix: str, local: str, values: list) -> None:
    key = f'{ns_prefix}{local}'
    old = desc.find(key)
    if old is not None:
        desc.remove(old)
    el  = ET.SubElement(desc, key)
    bag = ET.SubElement(el, f'{_RDF}Bag')
    for v in values:
        li = ET.SubElement(bag, f'{_RDF}li')
        li.text = str(v)


def _remove_value(desc: ET.Element, ns_prefix: str, local: str) -> None:
    element = desc.find(f'{ns_prefix}{local}')
    if element is not None:
        desc.remove(element)


def _load_sidecar_root(sidecar: str) -> tuple[ET.Element, ET.Element]:
    """Load an XMP root and description, falling back to a fresh document."""
    if os.path.isfile(sidecar):
        try:
            raw = _strip_xpacket(open(sidecar, 'rb').read())
            root = ET.fromstring(raw)
            desc = _find_desc(root)
            if desc is not None:
                return root, desc
        except Exception:
            pass
    root = _build_fresh_root()
    return root, _find_desc(root)


def _write_sidecar_root(sidecar: str, root: ET.Element) -> bool:
    """Atomically write an XMP root, retaining the original on failure."""
    try:
        _indent(root)
        payload = ET.tostring(root, encoding='unicode', xml_declaration=False)
        directory = os.path.dirname(sidecar) or '.'
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix='.unifile-', suffix='.xmp.tmp', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write("<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>\n")
                f.write(payload)
                f.write("\n<?xpacket end='w'?>")
            os.replace(temp_path, sidecar)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return True
    except Exception:
        return False


def write_sidecar(file_path: str,
                  category: str,
                  tags: list | None = None,
                  rating: int = 0,
                  flag: str = '') -> bool:
    """Write (or update) a .xmp sidecar next to *file_path*.

    Only UniFile-managed fields are written.  Third-party fields already in
    an existing sidecar are preserved.

    Returns True on success, False on any error.
    """
    sidecar = _sidecar_path(file_path)

    root, desc = _load_sidecar_root(sidecar)

    now = _iso_now()

    # dc:subject — Bag
    subjects = [category] if category else []
    if tags:
        subjects.extend(t for t in tags if t and t not in subjects)
    if subjects:
        _set_bag(desc, _DC, 'subject', subjects)

    # xmp:Label
    if category:
        _set_text(desc, _XMP, 'Label', category)

    # xmp:Rating (skip 0 — "no rating" in XMP standard)
    if 0 < rating <= 5:
        _set_text(desc, _XMP, 'Rating', str(rating))

    # xmp:CreateDate — only if not already present
    if desc.find(f'{_XMP}CreateDate') is None:
        _set_text(desc, _XMP, 'CreateDate', now)

    # xmp:ModifyDate — always update
    _set_text(desc, _XMP, 'ModifyDate', now)

    # uf:Category / uf:Flag (UniFile proprietary)
    _set_text(desc, _UF, 'Category', category or '')
    if flag:
        _set_text(desc, _UF, 'Flag', flag)

    return _write_sidecar_root(sidecar, root)


def read_sidecar(file_path: str) -> dict:
    """Read UniFile-managed fields from a .xmp sidecar.

    Returns a dict with keys: category, rating, create_date, modify_date,
    tags (list), flag.  Missing fields are omitted.  Returns {} on error.
    """
    sidecar = _sidecar_path(file_path)
    if not os.path.isfile(sidecar):
        return {}
    try:
        raw  = _strip_xpacket(open(sidecar, 'rb').read())
        root = ET.fromstring(raw)
        desc = _find_desc(root)
        if desc is None:
            return {}
    except Exception:
        return {}

    result: dict = {}

    # dc:subject → tags list
    subj_el = desc.find(f'{_DC}subject')
    if subj_el is not None:
        bag = subj_el.find(f'{_RDF}Bag')
        if bag is not None:
            result['tags'] = [li.text for li in bag if li.text]

    # xmp fields
    for local, key in [('Label', 'category'), ('Rating', 'rating'),
                       ('CreateDate', 'create_date'), ('ModifyDate', 'modify_date')]:
        el = desc.find(f'{_XMP}{local}')
        if el is not None and el.text:
            result[key] = el.text

    # UniFile proprietary fields
    for local, key in [('Category', 'category'), ('Flag', 'flag')]:
        el = desc.find(f'{_UF}{local}')
        if el is not None and el.text:
            result[key] = el.text

    custom_fields = {}
    for element in desc:
        if not element.tag.startswith(_UF):
            continue
        local = element.tag[len(_UF):]
        if local.startswith('Field_'):
            # An empty element is an intentional clear marker. It prevents a
            # stale embedded EXIF value from reappearing after a sidecar edit.
            custom_fields[local[6:].lower()] = element.text or ''
    if custom_fields:
        result['fields'] = custom_fields

    return result


def _xmp_element_value(element: ET.Element) -> str:
    """Flatten a simple XMP text or RDF collection for editor display."""
    for collection_name in ('Bag', 'Seq', 'Alt'):
        collection = element.find(f'{_RDF}{collection_name}')
        if collection is not None:
            return '; '.join(
                (child.text or '').strip() for child in collection
                if child.text and child.text.strip()
            )
    return (element.text or '').strip()


def read_sidecar_fields(file_path: str) -> dict[str, str]:
    """Read all scalar and RDF collection fields from a UniFile sidecar.

    Keys are stable ``xmp:<namespace-prefix>:<local-name>`` values.  Unknown
    namespaces are represented by their URI, which keeps the viewer useful
    even when a sidecar was authored by another application.  ``Field_*``
    values use a canonical lower-case suffix so an edit updates the existing
    UniFile field instead of creating a case-variant duplicate.
    """
    sidecar = _sidecar_path(file_path)
    if not os.path.isfile(sidecar):
        return {}
    try:
        raw = _strip_xpacket(open(sidecar, 'rb').read())
        root = ET.fromstring(raw)
        desc = _find_desc(root)
        if desc is None:
            return {}
    except Exception:
        return {}

    prefix_by_uri = {uri: prefix for prefix, uri in _NS.items()}
    result: dict[str, str] = {}
    for element in desc:
        if not element.tag.startswith('{'):
            continue
        uri, local = element.tag[1:].split('}', 1)
        prefix = prefix_by_uri.get(uri, uri)
        if local.startswith('Field_'):
            local = 'Field_' + local[6:].lower()
        result[f'xmp:{prefix}:{local}'] = _xmp_element_value(element)

    for attribute, value in desc.attrib.items():
        if not attribute.startswith('{') or attribute.endswith('}about'):
            continue
        uri, local = attribute[1:].split('}', 1)
        prefix = prefix_by_uri.get(uri, uri)
        result[f'xmp:{prefix}:@{local}'] = str(value).strip()
    return result


def write_sidecar_fields(file_path: str, fields: dict[str, object]) -> bool:
    """Update arbitrary existing XMP fields while preserving other metadata.

    The editor uses the stable keys returned by :func:`read_sidecar_fields`.
    Empty values remove an element or attribute.  New fields are limited to
    namespaces known by UniFile so an accidental typo cannot create arbitrary
    XML namespaces or mutate the source file.
    """
    if not isinstance(fields, dict):
        return False
    sidecar = _sidecar_path(file_path)
    root, desc = _load_sidecar_root(sidecar)
    uri_by_prefix = {prefix: uri for prefix, uri in _NS.items()}
    try:
        for raw_key, raw_value in fields.items():
            key = str(raw_key).strip()
            if not key.startswith('xmp:'):
                return False
            parts = key.split(':', 2)
            if len(parts) != 3 or parts[1] not in uri_by_prefix:
                return False
            prefix, local = parts[1], parts[2]
            value = '' if raw_value is None else str(raw_value).strip()
            if local.startswith('@'):
                attribute = f'{{{uri_by_prefix[prefix]}}}{local[1:]}'
                if value:
                    desc.set(attribute, value)
                else:
                    desc.attrib.pop(attribute, None)
                continue

            tag = f'{{{uri_by_prefix[prefix]}}}{local}'
            element = desc.find(tag)
            if not value:
                if element is not None:
                    desc.remove(element)
                continue
            had_collection = element is not None and any(
                element.find(f'{_RDF}{name}') is not None
                for name in ('Bag', 'Seq', 'Alt')
            )
            if prefix == 'dc' and local == 'subject':
                had_collection = True
            if had_collection:
                namespace = f'{{{uri_by_prefix[prefix]}}}'
                _set_bag(desc, namespace, local,
                         [part.strip() for part in re.split(r'[;,]', value)
                          if part.strip()])
            else:
                namespace = f'{{{uri_by_prefix[prefix]}}}'
                _set_text(desc, namespace, local, value)
        _set_text(desc, _XMP, 'ModifyDate', _iso_now())
        return _write_sidecar_root(sidecar, root)
    except Exception:
        return False


def write_editable_fields(file_path: str, fields: dict[str, object]) -> bool:
    """Update UniFile-managed batch-editor fields in the XMP sidecar.

    The original file is never modified. Empty values remove the managed
    field, which makes an undo operation able to restore a previously absent
    value. Unknown fields are stored under the UniFile namespace so they can
    safely accompany RAW and other formats without damaging embedded metadata.
    """
    sidecar = _sidecar_path(file_path)
    root, desc = _load_sidecar_root(sidecar)

    for field, raw_value in fields.items():
        key = str(field).strip().lower()
        if isinstance(raw_value, list | tuple | set):
            value = '; '.join(str(item).strip() for item in raw_value if str(item).strip())
        else:
            value = '' if raw_value is None else str(raw_value).strip()

        custom_local = 'Field_' + re.sub(
            r'[^A-Za-z0-9_]+', '_', key).strip('_')
        _set_text(desc, _UF, custom_local, value)

        if key == 'keywords':
            values = [part.strip() for part in re.split(r'[;,]', value) if part.strip()]
            if values:
                _set_bag(desc, _DC, 'subject', values)
            else:
                _remove_value(desc, _DC, 'subject')
            continue
        if key == 'category':
            if value:
                _set_text(desc, _UF, 'Category', value)
                _set_text(desc, _XMP, 'Label', value)
            else:
                _remove_value(desc, _UF, 'Category')
                _remove_value(desc, _XMP, 'Label')
            continue
        if key == 'rating':
            if value:
                _set_text(desc, _XMP, 'Rating', value)
            else:
                _remove_value(desc, _XMP, 'Rating')
            continue
        if key == 'flag':
            if value:
                _set_text(desc, _UF, 'Flag', value)
            else:
                _remove_value(desc, _UF, 'Flag')
            continue

    _set_text(desc, _XMP, 'ModifyDate', _iso_now())
    return _write_sidecar_root(sidecar, root)
