"""UniFile — Chainable search query parser.

Supported token syntax (all case-insensitive, order does not matter):

  name:<substr>            filename contains substr
  ext:<ext[,ext,...]>      extension in list (leading dot optional)
  cat:<substr>             category label contains substr
  dir:<substr>             source directory path contains substr
  folder:<substr>          alias for dir:
  path:<substr>            alias for dir:
  method:<name>            classification method contains name
  tag:<substr>             metadata tag contains substr
  size:>N[b|kb|mb|gb]      file size greater-than N
  size:<N[b|kb|mb|gb]      file size less-than N

Any text NOT matched as a token is treated as a plain substring filter
checked against the filename, directory path, and category.

Example query::

    ext:pdf,docx cat:invoices name:2024 dir:Downloads size:>10kb
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# Matches tokens like  key:value  or  key:"quoted value"
_TOKEN_RE = re.compile(r'\b(\w+):(\"(?:[^\"]+)\"|\S+)')


@dataclass
class SearchSpec:
    text: str = ""
    names: List[str] = field(default_factory=list)
    exts: List[str] = field(default_factory=list)
    cats: List[str] = field(default_factory=list)
    dirs: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    size_op: Optional[str] = None       # '>' or '<'
    size_bytes: Optional[int] = None
    is_chainable: bool = False          # True when at least one token was parsed


def _parse_size(value: str):
    """Return (op, bytes) or (None, None) on parse failure."""
    m = re.match(r'^([<>])(\d+(?:\.\d+)?)(b|kb|mb|gb)?$', value.strip().lower())
    if not m:
        return None, None
    op, num, unit = m.group(1), float(m.group(2)), (m.group(3) or 'b')
    mult = {'b': 1, 'kb': 1024, 'mb': 1024 ** 2, 'gb': 1024 ** 3}
    return op, int(num * mult[unit])


def parse_query(raw: str) -> SearchSpec:
    """Parse a search string into a :class:`SearchSpec`."""
    spec = SearchSpec()
    remaining = raw
    for m in _TOKEN_RE.finditer(raw):
        key = m.group(1).lower()
        val = m.group(2).strip('"').lower()
        remaining = remaining.replace(m.group(0), '', 1)
        spec.is_chainable = True

        if key in ('name', 'n'):
            spec.names.append(val)
        elif key in ('ext', 'e'):
            spec.exts.extend(
                v.lstrip('.').strip() for v in val.split(',') if v.strip()
            )
        elif key in ('cat', 'category', 'c'):
            spec.cats.append(val)
        elif key in ('dir', 'd', 'folder', 'path'):
            spec.dirs.append(val)
        elif key in ('method', 'm'):
            spec.methods.append(val)
        elif key in ('tag', 't'):
            spec.tags.append(val)
        elif key == 'size':
            op, sz = _parse_size(val)
            if op is not None:
                spec.size_op, spec.size_bytes = op, sz

    spec.text = remaining.strip().lower()
    return spec


def item_matches(spec: SearchSpec, it) -> bool:
    """Return True if *it* (FileItem or CategorizeItem) satisfies *spec*."""
    name = (
        getattr(it, 'name', None)
        or getattr(it, 'folder_name', '')
        or ''
    ).lower()
    ext = name.rsplit('.', 1)[-1] if '.' in name else ''
    cat = getattr(it, 'category', '').lower()
    src = (
        getattr(it, 'full_src', '')
        or getattr(it, 'full_current_path', '')
        or ''
    ).lower()
    method = getattr(it, 'method', '').lower()
    meta = getattr(it, 'metadata', {}) or {}
    meta_tags = [t.lower() for t in meta.get('_tags', [])]
    size = getattr(it, 'size', 0) or 0

    # Plain text: must appear in name, src, or cat
    if spec.text and spec.text not in name and spec.text not in src and spec.text not in cat:
        return False

    for n in spec.names:
        if n not in name:
            return False

    if spec.exts and ext not in spec.exts:
        return False

    for c in spec.cats:
        if c not in cat:
            return False

    for d in spec.dirs:
        if d not in src:
            return False

    for m_tok in spec.methods:
        if m_tok not in method:
            return False

    for t in spec.tags:
        if not any(t in mt for mt in meta_tags):
            return False

    if spec.size_op == '>' and spec.size_bytes is not None and size <= spec.size_bytes:
        return False
    if spec.size_op == '<' and spec.size_bytes is not None and size >= spec.size_bytes:
        return False

    return True
