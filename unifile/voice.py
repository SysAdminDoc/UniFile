"""Offline-first voice command parsing for UniFile.

The parser deliberately handles the small set of safe, high-value commands
locally.  A caller may provide an optional LLM callback for otherwise unknown
phrasing, but no network/provider is contacted by default.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VOICE_SCHEMA_VERSION = 1
DEFAULT_LARGE_FILE_MB = 1024
VIDEO_EXTENSIONS = (
    "mp4", "mkv", "avi", "mov", "webm", "wmv", "m4v", "flv", "mpeg",
    "mpg", "3gp", "ogv",
)
IMAGE_EXTENSIONS = (
    "jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic",
    "raw", "cr2", "nef", "arw", "orf", "dng",
)
_GENERIC_SELECTOR_WORDS = {
    "all", "the", "these", "those", "files", "file", "items", "item",
    "photos", "photo", "pictures", "picture", "videos", "video",
    "documents", "document", "images", "image",
}
_ACTION_NAMES = {"tag", "scan", "search", "unknown"}


@dataclass(frozen=True)
class VoiceIntent:
    """A normalized command ready for preview or explicit execution."""

    action: str
    text: str
    query: str = ""
    path: str = ""
    tag: str = ""
    selector: str = ""
    selector_terms: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    provider: str = "grammar"
    requires_confirmation: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""
        return {
            "schema_version": VOICE_SCHEMA_VERSION,
            "action": self.action,
            "text": self.text,
            "query": self.query,
            "path": self.path,
            "tag": self.tag,
            "selector": self.selector,
            "selector_terms": list(self.selector_terms),
            "confidence": self.confidence,
            "provider": self.provider,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VoiceIntent:
        """Build an intent from a persisted or provider-produced mapping."""
        action = str(payload.get("action", "unknown")).strip().lower()
        if action not in _ACTION_NAMES:
            action = "unknown"
        terms = payload.get("selector_terms", ())
        if isinstance(terms, str):
            terms = _selector_terms(terms)
        elif not isinstance(terms, (list, tuple)):
            terms = ()
        return cls(
            action=action,
            text=str(payload.get("text", "")).strip(),
            query=str(payload.get("query", "")).strip(),
            path=str(payload.get("path", "")).strip(),
            tag=str(payload.get("tag", "")).strip(),
            selector=str(payload.get("selector", "")).strip(),
            selector_terms=tuple(str(term).lower() for term in terms if str(term).strip()),
            confidence=max(0.0, min(1.0, float(payload.get("confidence", 0.0) or 0.0))),
            provider=str(payload.get("provider", "provider")).strip() or "provider",
            requires_confirmation=bool(payload.get("requires_confirmation", True)),
            reason=str(payload.get("reason", "")).strip(),
        )


def _clean_text(text: str) -> str:
    return " ".join(
        str(text or "")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .strip()
        .split()
    )


def _selector_terms(selector: str) -> tuple[str, ...]:
    words = re.findall(r"[\w-]+", selector.lower(), flags=re.UNICODE)
    useful = [word for word in words if word not in _GENERIC_SELECTOR_WORDS]
    return tuple(useful or words)


def _resolve_folder(raw_path: str, home: Path | None = None) -> str:
    """Resolve friendly folder names without requiring the folder to exist."""
    home = Path(home or Path.home())
    value = raw_path.strip().strip('"').strip("'").strip()
    value = re.sub(r"\s+(?:folder|directory)$", "", value, flags=re.IGNORECASE).strip()
    value = os.path.expandvars(os.path.expanduser(value))
    aliases = {
        "downloads": "Downloads",
        "desktop": "Desktop",
        "documents": "Documents",
        "pictures": "Pictures",
        "music": "Music",
        "videos": "Videos",
    }
    alias = aliases.get(value.lower())
    if alias:
        return str(home / alias)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = home / candidate
    return str(candidate)


def _search_query(subject: str, large_file_mb: int) -> str:
    """Translate common media wording into UniFile's existing query grammar."""
    lowered = subject.lower()
    is_large = bool(re.search(r"\b(?:large|big|huge)\b", lowered))
    is_video = bool(re.search(r"\bvideos?\b|\bmovies?\b", lowered))
    is_image = bool(re.search(r"\b(?:photos?|pictures?|images?)\b", lowered))
    parts: list[str] = []
    if is_video:
        parts.append(f"ext:{','.join(VIDEO_EXTENSIONS)}")
    elif is_image:
        parts.append(f"ext:{','.join(IMAGE_EXTENSIONS)}")
    if is_large:
        parts.append(f"size:>{max(1, int(large_file_mb))}mb")
    if not parts:
        return subject.strip()
    remainder = re.sub(
        r"\b(?:show|me|find|search|list|all|the|large|big|huge|video|videos|movie|movies|"
        r"file|files|photo|photos|picture|pictures|image|images|document|documents)\b",
        " ", subject, flags=re.IGNORECASE,
    )
    remainder = " ".join(remainder.split()).strip()
    if remainder:
        parts.append(remainder)
    return " ".join(parts)


def parse_voice_command(
    text: str,
    *,
    home: Path | None = None,
    large_file_mb: int = DEFAULT_LARGE_FILE_MB,
) -> VoiceIntent:
    """Parse a supported command using only local regular-expression rules."""
    command = _clean_text(text)
    if not command:
        return VoiceIntent("unknown", "", reason="Enter a voice command first.")

    scan_match = re.match(
        r"^(?:please\s+)?(?:scan|index|rescan)\s+(?:the\s+)?(.+?)\s*$",
        command, flags=re.IGNORECASE,
    )
    if scan_match:
        path = _resolve_folder(scan_match.group(1), home)
        return VoiceIntent(
            action="scan", text=command, path=path, confidence=0.97,
            reason="Scan the selected source folder.",
        )

    tag_match = re.match(
        r"^(?:please\s+)?(?:tag|label|mark)\s+(?:all\s+|these\s+|the\s+)?"
        r"(.+?)\s+(?:as|with(?:\s+the)?\s+tag|using(?:\s+the)?\s+tag)\s+"
        r"([\w][\w ._-]*)$",
        command, flags=re.IGNORECASE,
    )
    if tag_match:
        selector = tag_match.group(1).strip()
        tag = " ".join(tag_match.group(2).strip().split())
        return VoiceIntent(
            action="tag", text=command, selector=selector, tag=tag,
            selector_terms=_selector_terms(selector), confidence=0.95,
            reason="Preview matching entries before applying the tag.",
        )

    search_match = re.match(
        r"^(?:please\s+)?(?:show|find|search|list)(?:\s+me)?\s+(.+?)\s*$",
        command, flags=re.IGNORECASE,
    )
    if search_match:
        subject = search_match.group(1).strip()
        query = _search_query(subject, large_file_mb)
        return VoiceIntent(
            action="search", text=command, query=query,
            selector=subject, selector_terms=_selector_terms(subject),
            confidence=0.94, reason="Filter the current results using the search grammar.",
        )

    return VoiceIntent(
        action="unknown", text=command, confidence=0.0,
        reason="No supported voice action matched. Try scan, tag, show, find, or search.",
    )


def _provider_mapping(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    try:
        payload = json.loads(candidate)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            return None


class VoiceIntentParser:
    """Local parser with an explicitly opt-in LLM fallback."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        large_file_mb: int = DEFAULT_LARGE_FILE_MB,
        llm_classifier: Callable[[str], Any] | None = None,
    ):
        self.home = Path(home or Path.home())
        self.large_file_mb = large_file_mb
        self.llm_classifier = llm_classifier

    def parse(self, text: str, *, use_llm: bool = False) -> VoiceIntent:
        intent = parse_voice_command(
            text, home=self.home, large_file_mb=self.large_file_mb,
        )
        if intent.action != "unknown" or not use_llm or self.llm_classifier is None:
            return intent
        try:
            response = self.llm_classifier(text)
            if isinstance(response, tuple):
                raw, provider = response[0], response[1] if len(response) > 1 else "provider"
            else:
                raw, provider = response, "provider"
            mapping = _provider_mapping(raw)
            if mapping:
                payload = dict(mapping)
                payload.setdefault("text", _clean_text(text))
                payload.setdefault("provider", provider)
                payload.setdefault("selector_terms", _selector_terms(str(payload.get("selector", ""))))
                parsed = VoiceIntent.from_dict(payload)
                if parsed.action != "unknown":
                    return parsed
        except Exception:
            pass
        return intent


def matches_voice_selector(value: str, selector_terms: tuple[str, ...] | list[str]) -> bool:
    """Match every meaningful selector term against an entry path/name."""
    haystack = str(value or "").lower()
    return bool(selector_terms) and all(term.lower() in haystack for term in selector_terms)


def provider_voice_classifier(text: str) -> tuple[str, str]:
    """Use the configured provider chain for an opt-in intent fallback."""
    from unifile.ai_providers import ProviderChain

    system = (
        "You are UniFile's voice command parser. Return only JSON matching the schema. "
        "Choose tag for applying a tag to matching files, scan for a folder scan, "
        "search for a read-only filter, and unknown when the request is unsafe or unclear."
    )
    prompt = f"Parse this command: {text}"
    raw, provider = ProviderChain().classify(prompt, system=system)
    if not raw:
        return "", ""
    # ProviderChain keeps compatibility with the existing provider adapters;
    # the system prompt carries the small voice-action grammar.
    return raw, provider
