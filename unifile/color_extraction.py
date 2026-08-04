"""Deterministic image palette extraction and color-search query parsing."""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

IMAGE_EXTENSIONS = frozenset({
    ".avif", ".bmp", ".gif", ".heic", ".heif", ".ico", ".jfif",
    ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp",
})

COLOR_NAMES = frozenset({
    "black", "blue", "brown", "cyan", "gray", "green", "magenta",
    "orange", "pink", "purple", "red", "teal", "white", "yellow",
})

# Stable display colors for the Tag Library's dominant-color picker. These
# are separate from palette values, which come from each image.
COLOR_SWATCHES = {
    "red": "#ef4444",
    "orange": "#f97316",
    "yellow": "#eab308",
    "green": "#22c55e",
    "teal": "#14b8a6",
    "cyan": "#06b6d4",
    "blue": "#3b82f6",
    "purple": "#8b5cf6",
    "magenta": "#d946ef",
    "pink": "#ec4899",
    "brown": "#a16207",
    "gray": "#6b7280",
    "black": "#111827",
    "white": "#f8fafc",
}

_COLOR_ALIASES = {
    "grey": "gray",
    "violet": "purple",
    "lime": "green",
    "navy": "blue",
    "aqua": "cyan",
    "turquoise": "teal",
}
_BIN_SIZE = 32
_DEFAULT_SAMPLE_SIZE = 128


def canonical_color_name(value: str) -> str | None:
    """Normalize a user-facing color name to the indexed vocabulary."""
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    text = text.strip("\"'")
    text = re.sub(r"\b(?:tones?|colou?rs?)\b", "", text).strip()
    text = _COLOR_ALIASES.get(text, text)
    return text if text in COLOR_NAMES else None


def color_name_for_rgb(red: int, green: int, blue: int) -> str:
    """Return a stable coarse color name for an RGB sample."""
    r, g, b = (max(0, min(255, int(value))) / 255 for value in (red, green, blue))
    hue, saturation, value = colorsys.rgb_to_hsv(r, g, b)
    if value <= 0.14:
        return "black"
    if value >= 0.9 and saturation <= 0.1:
        return "white"
    if saturation <= 0.14:
        return "gray"
    degrees = hue * 360
    if value < 0.48 and degrees < 45:
        return "brown"
    if degrees < 15 or degrees >= 345:
        return "red"
    if degrees < 45:
        return "orange"
    if degrees < 70:
        return "yellow"
    if degrees < 160:
        return "green"
    if degrees < 195:
        return "teal"
    if degrees < 220:
        return "cyan"
    if degrees < 255:
        return "blue"
    if degrees < 290:
        return "purple"
    if degrees < 330:
        return "magenta"
    return "pink"


def extract_color_palette(
    filepath: str | Path,
    *,
    max_colors: int = 5,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
) -> list[dict]:
    """Extract weighted representative colors from an image.

    Qt is already a required UniFile dependency, so this avoids making Pillow
    mandatory for the Tag Library's color index. Transparent pixels are
    ignored, and nearby RGB values are grouped into deterministic 32-value
    bins before the palette is reduced to one row per coarse color name.
    """
    path = Path(filepath)
    if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
        return []
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QImage

        image = QImage(str(path))
        if image.isNull():
            return []
        longest = max(image.width(), image.height())
        if longest > sample_size:
            image = image.scaled(
                sample_size,
                sample_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        histogram: dict[tuple[int, int, int], int] = {}
        total = 0
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() < 32:
                    continue
                rgb = tuple(
                    min(255, (channel // _BIN_SIZE) * _BIN_SIZE + _BIN_SIZE // 2)
                    for channel in (pixel.red(), pixel.green(), pixel.blue())
                )
                histogram[rgb] = histogram.get(rgb, 0) + 1
                total += 1
        if not total:
            return []

        grouped: dict[str, dict] = {}
        candidates = sorted(
            histogram.items(), key=lambda item: (-item[1], item[0])
        )[: max(1, int(max_colors)) * 3]
        for (red, green, blue), count in candidates:
            name = color_name_for_rgb(red, green, blue)
            current = grouped.setdefault(
                name,
                {"name": name, "count": 0, "rgb": (red, green, blue)},
            )
            current["count"] += count
            if count > current.get("best_count", 0):
                current["rgb"] = (red, green, blue)
                current["best_count"] = count

        palette = []
        for rank, item in enumerate(
            sorted(grouped.values(), key=lambda value: (-value["count"], value["name"]))[
                : max(1, int(max_colors))
            ]
        ):
            red, green, blue = item["rgb"]
            palette.append({
                "name": item["name"],
                "hex": f"#{red:02x}{green:02x}{blue:02x}",
                "weight": round(item["count"] / total, 6),
                "rank": rank,
            })
        return palette
    except Exception:
        return []


def parse_color_query(query: str) -> tuple[str, bool] | None:
    """Parse explicit and natural-language color searches.

    Returns ``(canonical_name, dominant_only)`` for queries such as
    ``color:blue`` and ``show me files with predominant blue tones``.
    Plain words such as ``blue`` remain filename searches.
    """
    text = re.sub(r"\s+", " ", str(query or "").strip().lower())
    if text.startswith("color:"):
        name = canonical_color_name(text[6:])
        return (name, False) if name else None
    if not any(marker in text for marker in ("tone", "colour", "color", "predominant", "dominant")):
        return None
    for candidate in sorted(COLOR_NAMES | set(_COLOR_ALIASES), key=len, reverse=True):
        if re.search(rf"\b{re.escape(candidate)}\b", text):
            name = canonical_color_name(candidate)
            if name:
                return name, bool(re.search(r"\b(?:predominant|dominant|main)\b", text))
    return None


__all__ = [
    "COLOR_NAMES",
    "COLOR_SWATCHES",
    "IMAGE_EXTENSIONS",
    "canonical_color_name",
    "color_name_for_rgb",
    "extract_color_palette",
    "parse_color_query",
]
