"""RAW photo family discovery and EXIF-first metadata resolution.

RAW files and their camera JPEG previews are one logical capture for scan and
move workflows.  The RAW file is always the metadata authority; the JPEG is
used only to fill fields that the RAW extractor could not provide.
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

RAW_PHOTO_EXTENSIONS = frozenset({
    ".arw",
    ".cr2",
    ".cr3",
    ".crw",
    ".dng",
    ".nef",
    ".orf",
    ".raf",
    ".raw",
    ".rw2",
    ".pef",
    ".sr2",
    ".srw",
})
JPEG_PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg"})


def _path_key(path: str | os.PathLike[str]) -> str:
    """Return a case-insensitive absolute key for a local path."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _family_key(path: Path) -> tuple[str, str]:
    return _path_key(path.parent), path.stem.casefold()


def is_raw_photo(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* has a supported camera RAW extension."""
    return Path(path).suffix.casefold() in RAW_PHOTO_EXTENSIONS


def is_jpeg_photo(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* is a JPEG candidate for a RAW pair."""
    return Path(path).suffix.casefold() in JPEG_PHOTO_EXTENSIONS


@dataclass(frozen=True)
class RawPhotoFamily:
    """One RAW capture and its optional adjacent JPEG preview."""

    raw_path: Path
    jpeg_path: Path | None = None

    @property
    def is_paired(self) -> bool:
        return self.jpeg_path is not None

    @property
    def members(self) -> tuple[Path, ...]:
        return (self.raw_path,) if self.jpeg_path is None else (self.raw_path, self.jpeg_path)

    @property
    def stem(self) -> str:
        return self.raw_path.stem

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_path": str(self.raw_path),
            "jpeg_path": str(self.jpeg_path) if self.jpeg_path else "",
            "members": [str(path) for path in self.members],
            "paired": self.is_paired,
        }


def group_raw_photo_families(paths: Iterable[str | os.PathLike[str]]) -> list[RawPhotoFamily]:
    """Group collected RAW files with same-stem JPEGs in the same directory.

    The input is intentionally limited to the paths being scanned.  A JPEG
    excluded by a file-type filter cannot be silently attached to a RAW item.
    When more than one RAW file has the same stem, no JPEG is consumed because
    the pairing would be ambiguous.
    """
    raw_by_key: dict[tuple[str, str], list[Path]] = {}
    jpeg_by_key: dict[tuple[str, str], list[Path]] = {}
    for value in paths:
        path = Path(value)
        key = _family_key(path)
        if is_raw_photo(path):
            raw_by_key.setdefault(key, []).append(path)
        elif is_jpeg_photo(path):
            jpeg_by_key.setdefault(key, []).append(path)

    families: list[RawPhotoFamily] = []
    for key in sorted(raw_by_key):
        raws = sorted(raw_by_key[key], key=lambda path: _path_key(path))
        jpegs = sorted(jpeg_by_key.get(key, []), key=lambda path: _path_key(path))
        jpeg = jpegs[0] if len(raws) == 1 and jpegs else None
        families.extend(RawPhotoFamily(raw_path=raw, jpeg_path=jpeg) for raw in raws)
    return families


def collapse_raw_photo_pairs(
    items: Iterable[tuple[Path, bool]],
) -> tuple[list[tuple[Path, bool]], dict[str, RawPhotoFamily]]:
    """Remove paired JPEG rows and return a primary-path family lookup.

    Folders and standalone JPEGs remain unchanged.  The returned mapping uses
    normalized primary RAW paths so scan workers can resolve metadata and the
    apply worker can move all family members together.
    """
    item_list = list(items)
    file_paths = [path for path, is_folder in item_list if not is_folder]
    families = group_raw_photo_families(file_paths)
    family_by_raw: dict[str, RawPhotoFamily] = {}
    paired_jpegs: set[str] = set()
    for family in families:
        family_by_raw[_path_key(family.raw_path)] = family
        if family.jpeg_path:
            paired_jpegs.add(_path_key(family.jpeg_path))

    collapsed = [
        (path, is_folder)
        for path, is_folder in item_list
        if is_folder or _path_key(path) not in paired_jpegs
    ]
    return collapsed, family_by_raw


def family_for_path(
    families: Mapping[str, RawPhotoFamily],
    path: str | os.PathLike[str],
) -> RawPhotoFamily | None:
    """Look up the RAW family whose primary path is *path*."""
    return families.get(_path_key(path))


def extract_raw_photo_metadata(
    raw_path: str | os.PathLike[str],
    jpeg_path: str | os.PathLike[str] | None = None,
    *,
    extractor=None,
    log_cb=None,
) -> dict:
    """Extract RAW metadata first and fill missing fields from its JPEG.

    ``extractor`` is injectable for scanner tests and integrations; it must
    expose ``extract(filepath, log_cb=...)`` like :class:`MetadataExtractor`.
    """
    if extractor is None:
        from unifile.metadata import MetadataExtractor

        extractor = MetadataExtractor

    def _extract(path: str | os.PathLike[str]) -> dict:
        try:
            value = extractor.extract(os.fspath(path), log_cb=log_cb)
        except Exception:
            return {}
        return dict(value) if isinstance(value, Mapping) else {}

    raw = Path(raw_path)
    metadata = _extract(raw)
    metadata.setdefault("_type", "image")
    source = "raw"
    if jpeg_path:
        jpeg_metadata = _extract(jpeg_path)
        filled = False
        for key, value in jpeg_metadata.items():
            if key == "_type":
                continue
            if key not in metadata or metadata[key] in (None, "", [], {}):
                metadata[key] = value
                filled = True
        if filled:
            source = "raw+jpeg-fallback"

    family = RawPhotoFamily(raw_path=raw, jpeg_path=Path(jpeg_path) if jpeg_path else None)
    metadata["_raw_photo"] = True
    metadata["raw_path"] = str(raw)
    metadata["paired_jpeg_path"] = str(family.jpeg_path) if family.jpeg_path else ""
    metadata["raw_family_paths"] = [str(path) for path in family.members]
    metadata["_metadata_source"] = source
    return metadata


__all__ = [
    "JPEG_PHOTO_EXTENSIONS",
    "RAW_PHOTO_EXTENSIONS",
    "RawPhotoFamily",
    "collapse_raw_photo_pairs",
    "extract_raw_photo_metadata",
    "family_for_path",
    "group_raw_photo_families",
    "is_jpeg_photo",
    "is_raw_photo",
]
