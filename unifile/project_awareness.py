"""Project-file media reference discovery and audit helpers.

The project formats supported here deliberately use read-only extraction.  Premiere
projects are normally gzipped XML; After Effects and Resolve exports are commonly
binary or ZIP-like containers, so those formats use bounded string extraction.  A
Final Cut library is a directory bundle and may contain FCPXML, SQLite, and the
media copied into its ``Original Media`` folder.  The parser never writes to a
project file or invokes the vendor application.
"""

from __future__ import annotations

import gzip
import html
import io
import os
import re
import sqlite3
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from unifile.sqlite_policy import connect_sqlite

PROJECT_APPLICATIONS = {
    ".aep": "After Effects",
    ".prproj": "Premiere Pro",
    ".drp": "DaVinci Resolve",
    ".fcpbundle": "Final Cut Pro",
}

# Common source-media formats.  Project files and sidecars are intentionally
# omitted so an audit does not mistake another project for an asset.
MEDIA_EXTENSIONS = {
    ".3g2", ".3gp", ".aac", ".aif", ".aiff", ".arw", ".avi", ".bmp",
    ".cr2", ".cr3", ".dng", ".exr", ".flac", ".gif", ".heic", ".heif",
    ".jpg", ".jpeg", ".m4a", ".m4v", ".mkv", ".mov", ".mp3", ".mp4",
    ".mpeg", ".mpg", ".mts", ".mxf", ".nef", ".ogg", ".orf", ".png",
    ".r3d", ".raw", ".rw2", ".tif", ".tiff", ".wav", ".webm", ".wmv",
}

_MAX_PROJECT_BYTES = 100 * 1024 * 1024
_MAX_GZIP_BYTES = 50 * 1024 * 1024
_MAX_BUNDLE_FILES = 2_000
_MAX_BUNDLE_BYTES = 200 * 1024 * 1024
_MEDIA_SUFFIX_PATTERN = "|".join(sorted((ext[1:] for ext in MEDIA_EXTENSIONS), key=len, reverse=True))
_MEDIA_SUFFIX_RE = re.compile(rf"\.(?:{_MEDIA_SUFFIX_PATTERN})(?:$|[?#])", re.IGNORECASE)
_BINARY_ASCII_RE = re.compile(rb"[\x20-\x7e]{4,}")
_BINARY_UTF16_RE = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")


@dataclass(frozen=True)
class ProjectFile:
    """A discovered project and the application that owns its format."""

    path: Path
    name: str
    application: str
    modified: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": str(self.path),
            "name": self.name,
            "application": self.application,
            "modified": self.modified,
        }


@dataclass(frozen=True)
class ProjectReference:
    """One source-media reference found inside a project file."""

    project_path: Path
    project_name: str
    application: str
    project_modified: str
    raw_path: str
    resolved_path: Path | None = None

    @property
    def exists(self) -> bool:
        return self.resolved_path is not None and self.resolved_path.is_file()

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "project_path": str(self.project_path),
            "project_name": self.project_name,
            "application": self.application,
            "project_modified": self.project_modified,
            "raw_path": self.raw_path,
            "resolved_path": str(self.resolved_path) if self.resolved_path else None,
            "exists": self.exists,
        }


@dataclass
class ProjectAudit:
    """Complete project/reference report for a source tree."""

    source: Path
    projects: list[ProjectFile] = field(default_factory=list)
    references: list[ProjectReference] = field(default_factory=list)
    shared_assets: dict[Path, list[ProjectReference]] = field(default_factory=dict)
    orphaned_assets: list[Path] = field(default_factory=list)
    missing_references: list[ProjectReference] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def resolved_references(self) -> list[ProjectReference]:
        return [reference for reference in self.references if reference.exists]

    @property
    def referenced_asset_count(self) -> int:
        return len({
            _path_key(reference.resolved_path)
            for reference in self.resolved_references
            if reference.resolved_path is not None
        })

    def to_dict(self) -> dict:
        shared = []
        for path, references in sorted(self.shared_assets.items(), key=lambda item: str(item[0]).casefold()):
            shared.append({
                "path": str(path),
                "projects": sorted({reference.project_name for reference in references}, key=str.casefold),
                "references": [reference.to_dict() for reference in references],
            })
        return {
            "source": str(self.source),
            "projects": [project.to_dict() for project in self.projects],
            "references": [reference.to_dict() for reference in self.references],
            "shared_assets": shared,
            "orphaned_assets": [str(path) for path in self.orphaned_assets],
            "missing_references": [reference.to_dict() for reference in self.missing_references],
            "errors": list(self.errors),
            "counts": {
                "projects": len(self.projects),
                "references": len(self.references),
                "resolved_references": len(self.resolved_references),
                "referenced_assets": self.referenced_asset_count,
                "shared_assets": len(self.shared_assets),
                "orphaned_assets": len(self.orphaned_assets),
                "missing_references": len(self.missing_references),
            },
        }


@dataclass
class ProjectApplyResult:
    """Result of applying project metadata to a UniFile tag library."""

    applied: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "applied": self.applied,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


def _path_key(path: Path | str | None) -> str:
    if path is None:
        return ""
    try:
        return os.path.normcase(os.path.normpath(str(Path(path).resolve(strict=False))))
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(str(path)))


def _project_modified(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except (OSError, ValueError, OverflowError):
        return ""


def _project_descriptor(path: Path) -> ProjectFile:
    suffix = path.suffix.lower()
    name = path.name[:-len(suffix)] if suffix else path.name
    return ProjectFile(path=path, name=name or path.name,
                       application=PROJECT_APPLICATIONS[suffix],
                       modified=_project_modified(path))


def iter_project_files(source: str | Path) -> list[Path]:
    """Return supported project files/bundles below *source* in stable order."""
    source_path = Path(source).expanduser()
    if source_path.is_file():
        return [source_path] if source_path.suffix.lower() in PROJECT_APPLICATIONS else []
    if source_path.is_dir() and source_path.suffix.lower() == ".fcpbundle":
        return [source_path]
    if not source_path.is_dir():
        return []

    found: list[Path] = []
    for root, dirs, files in os.walk(source_path, topdown=True, followlinks=False):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        kept_dirs = []
        for directory in dirs:
            directory_path = Path(root) / directory
            if directory.lower().endswith(".fcpbundle"):
                found.append(directory_path)
            else:
                kept_dirs.append(directory)
        dirs[:] = kept_dirs
        for filename in files:
            path = Path(root) / filename
            if path.suffix.lower() in PROJECT_APPLICATIONS:
                found.append(path)
    return sorted(found, key=lambda path: str(path).casefold())


def iter_media_files(source: str | Path) -> list[Path]:
    """Enumerate local source assets used to calculate project orphans."""
    source_path = Path(source).expanduser()
    if source_path.is_file():
        return [source_path] if source_path.suffix.lower() in MEDIA_EXTENSIONS else []
    if not source_path.is_dir():
        return []
    found: list[Path] = []
    for root, dirs, files in os.walk(source_path, topdown=True, followlinks=False):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for filename in files:
            path = Path(root) / filename
            if path.suffix.lower() in MEDIA_EXTENSIONS:
                found.append(path)
    return found


def _read_bytes(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"project exceeds safe read limit ({limit:,} bytes): {path}")
    return data


def _xml_values(data: bytes) -> list[str]:
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError):
        return []
    values: list[str] = []
    for node in root.iter():
        if node.text and node.text.strip():
            values.append(node.text.strip())
        values.extend(str(value).strip() for value in node.attrib.values() if str(value).strip())
    return values


def _binary_values(data: bytes) -> list[str]:
    values: list[str] = []
    for match in _BINARY_ASCII_RE.finditer(data):
        values.append(match.group().decode("utf-8", errors="replace"))
    for match in _BINARY_UTF16_RE.finditer(data):
        values.append(match.group().decode("utf-16-le", errors="replace"))
    return values


def _clean_raw_path(value: str) -> str:
    cleaned = html.unescape(str(value)).replace("\x00", "").strip()
    cleaned = cleaned.strip('"\'[](){}<>')
    if cleaned.lower().startswith("file://"):
        parsed = urlparse(cleaned)
        decoded = unquote(parsed.path)
        if parsed.netloc and parsed.netloc.lower() not in {"", "localhost"}:
            decoded = f"//{parsed.netloc}{decoded}"
        # file:///C:/... is a URI spelling of a Windows absolute path.
        if re.match(r"^/[A-Za-z]:[\\/]", decoded):
            decoded = decoded[1:]
        cleaned = decoded
    return cleaned.rstrip(" .,;|\t")


def _media_candidates(value: str) -> list[str]:
    """Extract media-looking path tokens from XML or binary strings."""
    if not value:
        return []
    candidates: list[str] = []
    parts = re.split(r"[\x00\r\n\"'<>|;]+", value)
    for part in parts:
        cleaned = _clean_raw_path(part)
        if _MEDIA_SUFFIX_RE.search(cleaned) and not cleaned.lower().startswith(("http://", "https://")):
            candidates.append(cleaned)
    # Some binary formats concatenate a label and a path without separators.
    embedded = re.compile(
        rf"(?:(?:file://|[A-Za-z]:[\\/]|/)[^\"'<>\r\n|;]*?\.(?:{_MEDIA_SUFFIX_PATTERN})(?:$|[?#]))",
        re.IGNORECASE,
    )
    for match in embedded.finditer(value):
        cleaned = _clean_raw_path(match.group())
        if cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def _values_from_zip(path: Path) -> list[str]:
    values: list[str] = []
    total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename.casefold()):
                if info.is_dir():
                    continue
                total += info.file_size
                if total > _MAX_PROJECT_BYTES:
                    break
                data = archive.read(info)
                values.extend(_xml_values(data))
                values.extend(_binary_values(data))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        return []
    return values


def _values_from_sqlite(path: Path) -> list[str]:
    """Read text columns from a SQLite library without modifying it."""
    values: list[str] = []
    try:
        connection = connect_sqlite(
            f"file:{path.as_posix()}?mode=ro",
            uri=True,
            check_same_thread=True,
            read_only=True,
            query_only=True,
        )
        try:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for (table,) in tables:
                columns = connection.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")').fetchall()
                text_columns = [column[1] for column in columns if str(column[2]).upper() in {"", "TEXT", "VARCHAR", "CHAR"}]
                for column in text_columns:
                    quoted_table = table.replace('"', '""')
                    quoted_column = column.replace('"', '""')
                    rows = connection.execute(
                        f'SELECT "{quoted_column}" FROM "{quoted_table}" WHERE "{quoted_column}" IS NOT NULL'
                    ).fetchmany(20_000)
                    values.extend(str(row[0]) for row in rows if row and row[0] is not None)
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return []
    return values


def _fcpbundle_values(path: Path) -> list[str]:
    values: list[str] = []
    if path.is_file():
        return _values_from_zip(path) or _binary_values(_read_bytes(path, _MAX_PROJECT_BYTES))
    processed = 0
    total = 0
    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for filename in files:
            if processed >= _MAX_BUNDLE_FILES or total >= _MAX_BUNDLE_BYTES:
                return values
            file_path = Path(root) / filename
            try:
                size = file_path.stat().st_size
                if size > _MAX_PROJECT_BYTES:
                    continue
                data = _read_bytes(file_path, min(_MAX_PROJECT_BYTES, _MAX_BUNDLE_BYTES - total))
            except (OSError, ValueError):
                continue
            processed += 1
            total += len(data)
            lower_name = filename.casefold()
            if lower_name.endswith((".fcpxml", ".xml")):
                values.extend(_xml_values(data))
            if lower_name.endswith((".flexolibrary", ".sqlite", ".db")) or data.startswith(b"SQLite format 3"):
                values.extend(_values_from_sqlite(file_path))
            values.extend(_binary_values(data))
            # FCP bundles often copy managed assets into Original Media.  They
            # are references even when the database stores an opaque asset ID.
            if file_path.suffix.lower() in MEDIA_EXTENSIONS:
                values.append(str(file_path))
    return values


def extract_project_references(project_path: str | Path) -> list[str]:
    """Extract raw local-media path candidates from one supported project."""
    path = Path(project_path).expanduser()
    suffix = path.suffix.lower()
    if suffix not in PROJECT_APPLICATIONS:
        return []
    try:
        if suffix == ".fcpbundle":
            values = _fcpbundle_values(path)
        elif suffix == ".prproj":
            data = _read_bytes(path, _MAX_PROJECT_BYTES)
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                    data = stream.read(_MAX_GZIP_BYTES + 1)
                if len(data) > _MAX_GZIP_BYTES:
                    raise ValueError("decompressed Premiere project exceeds safe read limit")
            except (OSError, EOFError, gzip.BadGzipFile):
                pass
            values = _xml_values(data) or _binary_values(data)
        elif zipfile.is_zipfile(path):
            values = _values_from_zip(path)
        else:
            values = _binary_values(_read_bytes(path, _MAX_PROJECT_BYTES))
    except (OSError, ValueError):
        return []

    references: list[str] = []
    seen: set[str] = set()
    for value in values:
        for candidate in _media_candidates(value):
            key = os.path.normcase(candidate)
            if key not in seen:
                seen.add(key)
                references.append(candidate)
    return references


def _resolve_reference(raw_path: str, project_path: Path, source_root: Path,
                       inventory: list[Path], by_basename: dict[str, list[Path]]) -> Path | None:
    cleaned = _clean_raw_path(raw_path)
    if not cleaned or cleaned.lower().startswith(("http://", "https://")):
        return None
    path_value = cleaned.replace("/", os.sep) if os.sep == "\\" else cleaned.replace("\\", os.sep)
    candidate = Path(path_value).expanduser()
    candidates = [candidate] if candidate.is_absolute() else [project_path.parent / candidate, source_root / candidate]
    for item in candidates:
        try:
            if item.is_file():
                return item.resolve(strict=False)
        except OSError:
            continue
    basename = Path(path_value).name.casefold()
    matches = by_basename.get(basename, [])
    if len(matches) == 1:
        return matches[0].resolve(strict=False)
    # Handle a path that differs only by case or slash style on a filesystem
    # where the original absolute path cannot be opened from this host.
    wanted = os.path.normcase(os.path.normpath(path_value))
    for item in inventory:
        if os.path.normcase(os.path.normpath(str(item))) == wanted:
            return item.resolve(strict=False)
    return None


def build_project_audit(source: str | Path) -> ProjectAudit:
    """Parse projects below *source* and classify shared, orphaned, and missing assets."""
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    source_root = source_path if source_path.is_dir() and source_path.suffix.lower() != ".fcpbundle" else source_path.parent
    project_paths = iter_project_files(source_path)
    inventory = iter_media_files(source_root)
    by_basename: dict[str, list[Path]] = defaultdict(list)
    for path in inventory:
        by_basename[path.name.casefold()].append(path)

    audit = ProjectAudit(source=source_path)
    referenced_by_path: dict[str, list[ProjectReference]] = defaultdict(list)
    for project_path in project_paths:
        descriptor = _project_descriptor(project_path)
        audit.projects.append(descriptor)
        try:
            raw_references = extract_project_references(project_path)
        except (OSError, ValueError) as exc:
            audit.errors.append(f"{project_path}: {exc}")
            raw_references = []
        seen_for_project: set[str] = set()
        for raw_path in raw_references:
            resolved = _resolve_reference(raw_path, project_path, source_root, inventory, by_basename)
            identity = _path_key(resolved) or os.path.normcase(raw_path)
            if identity in seen_for_project:
                continue
            seen_for_project.add(identity)
            reference = ProjectReference(
                project_path=project_path,
                project_name=descriptor.name,
                application=descriptor.application,
                project_modified=descriptor.modified,
                raw_path=raw_path,
                resolved_path=resolved,
            )
            audit.references.append(reference)
            if reference.exists and resolved is not None:
                referenced_by_path[_path_key(resolved)].append(reference)

    inventory_by_key = {_path_key(path): path for path in inventory}
    for key, references in sorted(referenced_by_path.items()):
        if len({reference.project_path for reference in references}) > 1:
            path = inventory_by_key.get(key) or references[0].resolved_path
            if path is not None:
                audit.shared_assets[path] = references
    referenced_keys = set(referenced_by_path)
    audit.orphaned_assets = sorted(
        (path for key, path in inventory_by_key.items() if key not in referenced_keys),
        key=lambda path: str(path).casefold(),
    )
    audit.missing_references = [reference for reference in audit.references if not reference.exists]
    audit.projects.sort(key=lambda project: str(project.path).casefold())
    audit.references.sort(key=lambda reference: (str(reference.project_path).casefold(), reference.raw_path.casefold()))
    audit.missing_references.sort(key=lambda reference: (reference.project_name.casefold(), reference.raw_path.casefold()))
    return audit


def _project_tag_slug(name: str) -> str:
    slug = re.sub(r"[^\w]+", "-", name.casefold(), flags=re.UNICODE).strip("-")
    return slug or "unnamed"


def apply_project_tags(audit: ProjectAudit, target_library) -> ProjectApplyResult:
    """Apply non-destructive project tags and fields to resolved library assets."""
    from unifile.tagging.library import TagLibrary

    result = ProjectApplyResult()
    library = target_library if isinstance(target_library, TagLibrary) else TagLibrary(str(target_library))
    owns_library = library is not target_library
    if owns_library and not library.open():
        result.errors.append(f"could not open UniFile library: {target_library}")
        return result
    try:
        grouped: dict[str, list[ProjectReference]] = defaultdict(list)
        paths: dict[str, Path] = {}
        for reference in audit.resolved_references:
            if reference.resolved_path is None:
                continue
            key = _path_key(reference.resolved_path)
            grouped[key].append(reference)
            paths[key] = reference.resolved_path
        for key, references in sorted(grouped.items()):
            path = paths[key]
            try:
                entry = library.add_entry(str(path))
                if entry is None:
                    result.skipped += 1
                    continue
                tag_names = {"project-reference"}
                tag_names.update(f"project:{_project_tag_slug(reference.project_name)}" for reference in references)
                tag_ids = []
                for tag_name in sorted(tag_names):
                    tag = library.add_tag(tag_name, color_slug="sky" if tag_name == "project-reference" else "violet")
                    if tag is not None:
                        tag_ids.append(tag.id)
                library.add_tags_to_entry(entry.id, tag_ids)
                names = sorted({reference.project_name for reference in references}, key=str.casefold)
                modified = sorted(
                    {f"{reference.project_name}={reference.project_modified}" for reference in references},
                    key=str.casefold,
                )
                library.set_entry_field(entry.id, "project_names", "; ".join(names))
                library.set_entry_field(entry.id, "project_modified", "; ".join(modified))
                library.set_entry_field(entry.id, "project_reference_count", str(len(references)))
                result.applied += 1
            except (OSError, ValueError, RuntimeError) as exc:
                result.errors.append(f"{path}: {exc}")
    finally:
        if owns_library:
            library.close()
    return result
