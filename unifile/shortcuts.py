"""User-configurable keyboard shortcut definitions and validation."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QKeySequence


@dataclass(frozen=True)
class ShortcutDefinition:
    """One user-facing shortcut binding."""

    key: str
    label: str
    description: str
    default: str
    scope: str = "window"


SHORTCUT_DEFINITIONS = (
    ShortcutDefinition(
        "command_palette", "Command palette", "Open the Ctrl+K command palette.", "Ctrl+K"
    ),
    ShortcutDefinition(
        "start_scan", "Start scan", "Start the current scan when the Scan button is enabled.", "Ctrl+S"
    ),
    ShortcutDefinition(
        "focus_search", "Focus result search", "Focus and select all text in the result filter.", "Ctrl+T"
    ),
    ShortcutDefinition(
        "voice_control", "Voice control", "Open the offline-first voice control dialog.", "Ctrl+Shift+V"
    ),
    ShortcutDefinition(
        "clear_selection", "Clear result selection", "Clear selected result rows.", "Escape", "results"
    ),
    ShortcutDefinition(
        "toggle_selected", "Toggle selected results", "Toggle the review checkbox on selected rows.", "Return", "results"
    ),
    ShortcutDefinition(
        "open_selected_location", "Open selected location", "Open the selected result's containing folder.", "Space", "results"
    ),
    ShortcutDefinition(
        "uncheck_selected", "Uncheck selected results", "Uncheck selected result rows without changing the scan.", "Delete", "results"
    ),
    *tuple(
        ShortcutDefinition(
            f"profile_{index}",
            f"Switch to profile {index}",
            f"Select profile {index} from the profile list.",
            f"Alt+{index}",
        )
        for index in range(1, 10)
    ),
)

SHORTCUTS_BY_KEY = {definition.key: definition for definition in SHORTCUT_DEFINITIONS}

# These are Windows shell/session bindings. Application defaults intentionally
# stay outside this set, while custom bindings are rejected when they collide.
_OS_RESERVED_TEXT = (
    "Alt+Tab",
    "Alt+F4",
    "Alt+Space",
    "Ctrl+Alt+Delete",
    "Ctrl+Esc",
    "Win+D",
    "Win+E",
    "Win+L",
    "Win+R",
    "Win+Tab",
    "Win+Shift+S",
)


def normalize_sequence(value) -> str:
    """Return a portable, displayable representation of a key sequence."""

    if isinstance(value, QKeySequence):
        sequence = value
    else:
        sequence = QKeySequence(str(value or "").strip())
    return sequence.toString(QKeySequence.SequenceFormat.PortableText).strip()


def _reserved_forms() -> set[str]:
    forms = set()
    for value in _OS_RESERVED_TEXT:
        normalized = normalize_sequence(value)
        if normalized:
            forms.add(normalized.casefold().replace(" ", ""))
    # Qt uses Meta for the Windows key on some platforms; keep both spellings.
    forms.update({
        "win+d", "win+e", "win+l", "win+r", "win+tab", "win+shift+s",
        "meta+d", "meta+e", "meta+l", "meta+r", "meta+tab", "meta+shift+s",
    })
    return forms


OS_RESERVED_SHORTCUTS = frozenset(_reserved_forms())


def is_os_reserved(sequence: str) -> bool:
    """Return whether a sequence is reserved by Windows shell/session UI."""

    normalized = normalize_sequence(sequence)
    if not normalized:
        return False
    return normalized.casefold().replace(" ", "") in OS_RESERVED_SHORTCUTS


class ShortcutManager:
    """Load, validate, and persist the application's shortcut bindings."""

    PREFIX = "shortcuts/"

    def __init__(self, settings: QSettings | None = None):
        self.settings = settings or QSettings("UniFile", "UniFile")

    @staticmethod
    def definitions() -> tuple[ShortcutDefinition, ...]:
        return SHORTCUT_DEFINITIONS

    def sequence(self, key: str) -> str:
        definition = SHORTCUTS_BY_KEY[key]
        stored = self.settings.value(f"{self.PREFIX}{key}", None)
        # Preserve the pre-dialog voice setting used by existing installs.
        if stored is None and key == "voice_control":
            stored = self.settings.value("voice/shortcut", None)
        if stored is None:
            return definition.default
        return normalize_sequence(stored)

    def values(self) -> dict[str, str]:
        return {definition.key: self.sequence(definition.key)
                for definition in SHORTCUT_DEFINITIONS}

    def validate_values(self, values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """Return ``(normalized_values, errors)`` for a complete binding set."""
        normalized = {}
        errors = {}
        owners: dict[str, str] = {}
        for definition in SHORTCUT_DEFINITIONS:
            raw = values.get(definition.key, self.sequence(definition.key))
            text = str(raw or "").strip()
            candidate = normalize_sequence(text)
            if text and not candidate:
                errors[definition.key] = "Enter a valid key sequence or clear the field."
                continue
            normalized[definition.key] = candidate
            compact = candidate.casefold().replace(" ", "")
            if compact and is_os_reserved(candidate):
                errors[definition.key] = "Reserved by Windows. Choose another shortcut."
            if compact and compact in owners:
                errors[definition.key] = f"Conflicts with {owners[compact]}."
            elif compact:
                owners[compact] = definition.label
        return normalized, errors

    def save_values(self, values: dict[str, str]) -> tuple[bool, dict[str, str]]:
        normalized, errors = self.validate_values(values)
        if errors:
            return False, errors
        for definition in SHORTCUT_DEFINITIONS:
            value = normalized[definition.key]
            self.settings.setValue(f"{self.PREFIX}{definition.key}", value)
            if definition.key == "voice_control":
                self.settings.setValue("voice/shortcut", value)
        self.settings.sync()
        return True, {}

    def set_sequence(self, key: str, value: str) -> tuple[bool, str]:
        """Update one binding while retaining all other current values."""
        if key not in SHORTCUTS_BY_KEY:
            return False, "Unknown shortcut."
        values = self.values()
        values[key] = value
        ok, errors = self.save_values(values)
        return ok, errors.get(key, "")

