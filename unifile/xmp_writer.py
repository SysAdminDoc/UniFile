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
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

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


def _find_desc(root: ET.Element) -> Optional[ET.Element]:
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


def write_sidecar(file_path: str,
                  category: str,
                  tags: Optional[list] = None,
                  rating: int = 0,
                  flag: str = '') -> bool:
    """Write (or update) a .xmp sidecar next to *file_path*.

    Only UniFile-managed fields are written.  Third-party fields already in
    an existing sidecar are preserved.

    Returns True on success, False on any error.
    """
    sidecar = _sidecar_path(file_path)

    # Load existing or start fresh
    root: ET.Element
    if os.path.isfile(sidecar):
        try:
            raw = _strip_xpacket(open(sidecar, 'rb').read())
            root = ET.fromstring(raw)
            desc = _find_desc(root)
            if desc is None:
                root = _build_fresh_root()
                desc = _find_desc(root)
        except Exception:
            root = _build_fresh_root()
            desc = _find_desc(root)
    else:
        root = _build_fresh_root()
        desc = _find_desc(root)

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

    try:
        _indent(root)
        payload = ET.tostring(root, encoding='unicode', xml_declaration=False)
        with open(sidecar, 'w', encoding='utf-8') as f:
            f.write("<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>\n")
            f.write(payload)
            f.write("\n<?xpacket end='w'?>")
        return True
    except Exception:
        return False


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

    return result
