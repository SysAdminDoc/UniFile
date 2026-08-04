"""Qt-free HTML, PDF, and JSON reports for a UniFile Tag Library."""
from __future__ import annotations

import html
import json
import os
import tempfile
import textwrap
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "1"
DEFAULT_REPORT_ENTRIES = 10_000
MAX_REPORT_ENTRIES = 50_000


def _entry_payload(entry) -> dict[str, Any]:
    path = Path(entry.path).expanduser().resolve(strict=False)
    try:
        stat = path.stat()
        size = stat.st_size
        modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    except OSError:
        size = None
        modified = ""
    tags = sorted(
        (tag for tag in getattr(entry, "tags", set())),
        key=lambda tag: str(tag.name).casefold(),
    )
    categories = sorted(
        (str(tag.name) for tag in tags if bool(getattr(tag, "is_category", False))),
        key=str.casefold,
    )
    return {
        "id": entry.id,
        "path": str(path),
        "name": entry.filename,
        "extension": entry.suffix,
        "size": size,
        "modified": modified,
        "categories": categories,
        "tags": [str(tag.name) for tag in tags],
    }


def build_library_report(
    library_root: str | os.PathLike[str],
    *,
    limit: int = DEFAULT_REPORT_ENTRIES,
) -> dict[str, Any]:
    """Read a bounded file inventory and category distribution from a library."""
    root = Path(library_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a library directory: {root}")
    bounded_limit = max(1, min(MAX_REPORT_ENTRIES, int(limit)))

    from unifile.tagging.library import TagLibrary

    library = TagLibrary(str(root))
    if not library.open():
        raise RuntimeError(f"could not open Tag Library: {root}")
    try:
        total_entries = library.get_entry_count()
        files: list[dict[str, Any]] = []
        category_counts: Counter[str] = Counter()
        tag_counts: Counter[str] = Counter()
        offset = 0
        page_size = 500
        while offset < total_entries and len(files) < bounded_limit:
            entries = library.get_all_entries(
                limit=min(page_size, bounded_limit - len(files)), offset=offset
            )
            if not entries:
                break
            for entry in entries:
                payload = _entry_payload(entry)
                files.append(payload)
                for category in payload["categories"] or ["Uncategorized"]:
                    category_counts[category] += 1
                for tag in payload["tags"]:
                    tag_counts[tag] += 1
            offset += len(entries)

        categories = [
            {"name": name, "count": count}
            for name, count in sorted(
                category_counts.items(), key=lambda pair: (-pair[1], pair[0].casefold())
            )
        ]
        tags = [
            {"name": name, "entry_count": count}
            for name, count in sorted(
                tag_counts.items(), key=lambda pair: (-pair[1], pair[0].casefold())
            )
        ]
        return {
            "version": REPORT_SCHEMA_VERSION,
            "timestamp": datetime.now().isoformat(),
            "library_root": str(root),
            "entry_count": total_entries,
            "reported_entries": len(files),
            "truncated": total_entries > len(files),
            "category_distribution": categories,
            "tag_distribution": tags,
            "files": files,
        }
    finally:
        library.close()


def _format_size(size: int | None) -> str:
    if size is None:
        return "missing"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{int(size)} B"


def render_html(report: dict[str, Any]) -> str:
    """Render a self-contained, escaped HTML report."""
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    category_rows = "".join(
        f"<tr><td>{esc(item['name'])}</td><td>{item['count']}</td></tr>"
        for item in report["category_distribution"]
    ) or '<tr><td colspan="2">No category tags</td></tr>'
    file_rows = "".join(
        "<tr>"
        f"<td>{esc(item['name'])}</td>"
        f"<td>{esc(', '.join(item['categories']) or 'Uncategorized')}</td>"
        f"<td>{esc(item['extension'] or '')}</td>"
        f"<td>{esc(_format_size(item['size']))}</td>"
        f"<td>{esc(', '.join(item['tags']))}</td>"
        f"<td>{esc(item['path'])}</td>"
        "</tr>"
        for item in report["files"]
    ) or '<tr><td colspan="6">No files in the report</td></tr>'
    truncated = (
        f"<p class=\"notice\">Showing {report['reported_entries']} of "
        f"{report['entry_count']} entries.</p>"
        if report["truncated"]
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UniFile Report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#0a1520;color:#d7e0ea;margin:2rem}}
h1{{color:#70d7ff;border-bottom:2px solid #21415c;padding-bottom:.6rem}}
h2{{color:#9be7ff;margin-top:2rem}}
.meta,.notice{{color:#9bb1c4}}
table{{border-collapse:collapse;width:100%;margin-top:.75rem}}
th{{background:#10263a;color:#70d7ff;text-align:left}}
th,td{{border-bottom:1px solid #1e3448;padding:.5rem .65rem;vertical-align:top}}
tr:nth-child(even){{background:#0d1e2d}}
.path{{word-break:break-all}}
</style></head><body>
<h1>UniFile Report</h1>
<p class="meta">Library: {esc(report['library_root'])}<br>
Generated: {esc(report['timestamp'])}<br>
Entries: {report['entry_count']}</p>
{truncated}
<h2>Category distribution</h2>
<table><thead><tr><th>Category</th><th>Files</th></tr></thead>
<tbody>{category_rows}</tbody></table>
<h2>File list</h2>
<table><thead><tr><th>Name</th><th>Category</th><th>Extension</th>
<th>Size</th><th>Tags</th><th>Path</th></tr></thead>
<tbody>{file_rows}</tbody></table>
</body></html>
"""


def _pdf_escape(value: str) -> str:
    clean = "".join(char if ord(char) >= 32 else " " for char in str(value))
    return clean.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_lines(report: dict[str, Any]) -> list[str]:
    lines = [
        "UniFile Report",
        f"Library: {report['library_root']}",
        f"Generated: {report['timestamp']}",
        f"Entries: {report['entry_count']} (reported {report['reported_entries']})",
        "",
        "Category distribution",
    ]
    lines.extend(
        f"  {item['name']}: {item['count']}"
        for item in report["category_distribution"]
    )
    if not report["category_distribution"]:
        lines.append("  (no category tags)")
    lines.extend(("", "File list"))
    for item in report["files"]:
        lines.append(
            f"  {item['name']} | {', '.join(item['categories']) or 'Uncategorized'} | "
            f"{_format_size(item['size'])} | {item['path']}"
        )
    return [
        wrapped
        for line in lines
        for wrapped in (textwrap.wrap(line, width=105) or [""])
    ]


def render_pdf(report: dict[str, Any]) -> bytes:
    """Render a dependency-free, text-oriented PDF report."""
    lines = _pdf_lines(report)
    page_lines = 48
    pages = [lines[index:index + page_lines] for index in range(0, len(lines), page_lines)] or [[]]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    page_refs: list[int] = []
    next_object = 4
    for page in pages:
        content_object = next_object
        page_object = next_object + 1
        next_object += 2
        page_refs.append(page_object)
        commands = ["BT", "/F1 10 Tf", "50 760 Td"]
        for line in page:
            commands.append(f"({_pdf_escape(line)}) Tj")
            commands.append("0 -14 Td")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", "replace")
        objects[content_object] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream + b"\nendstream"
        )
        objects[page_object] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_object} 0 R >>"
        ).encode("ascii")
    kids = " ".join(f"{number} 0 R" for number in page_refs)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>".encode("ascii")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max(objects) + 1)
    for number in range(1, max(objects) + 1):
        offsets[number] = len(output)
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(objects[number])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _atomic_write(path: Path, payload: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".unifile-report-", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass


def write_report(report: dict[str, Any], output: str | os.PathLike[str], fmt: str) -> str:
    """Atomically write a report in ``html``, ``pdf``, or ``json`` format."""
    path = Path(output).expanduser()
    kind = str(fmt or path.suffix.lstrip(".")).casefold()
    if kind == "html":
        payload: str | bytes = render_html(report)
    elif kind == "pdf":
        payload = render_pdf(report)
    elif kind == "json":
        payload = json.dumps(report, indent=2, ensure_ascii=False)
    else:
        raise ValueError("format must be html, pdf, or json")
    _atomic_write(path, payload)
    return str(path.resolve())
