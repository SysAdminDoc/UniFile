"""Redacted support diagnostics export."""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from unifile import __version__
from unifile.config import (
    _APP_DATA_DIR,
    _CSV_LOG_FILE,
    _UNDO_STACK_FILE,
    _WATCH_HISTORY_FILE,
)

REDACTED_EMAIL = "[REDACTED_EMAIL]"
REDACTED_PATH = "[REDACTED_PATH]"
REDACTED_SECRET = "[REDACTED_SECRET]"

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|token|secret|password)\b(\s*[:=]\s*)(['\"]?)[^\s,'\"]+"
)
_PATH_STOP = r"(?=\s+(?:api[_-]?key|authorization|token|secret|password)\b|[\r\n\t,;\"<>|]|$)"
_WINDOWS_PATH_RE = re.compile(
    rf"(?<![\w])(?:[A-Za-z]:\\|\\\\)[^\r\n\t,;\"<>|]+?{_PATH_STOP}",
    re.IGNORECASE,
)
_UNIX_PATH_RE = re.compile(
    rf"(?<![\w])/(?:Users|home|mnt|Volumes)/[^\r\n\t,;\"<>|]+?{_PATH_STOP}",
    re.IGNORECASE,
)
_SECRET_KEY_PARTS = ("api_key", "apikey", "authorization", "token", "secret", "password", "key")


def redact_text(text: str) -> str:
    """Redact common secrets, emails, and local filesystem paths from text."""
    if not text:
        return ""
    redacted = _BEARER_RE.sub(f"Bearer {REDACTED_SECRET}", str(text))
    redacted = _SECRET_ASSIGN_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED_SECRET}",
        redacted,
    )
    redacted = _EMAIL_RE.sub(REDACTED_EMAIL, redacted)
    redacted = _WINDOWS_PATH_RE.sub(REDACTED_PATH, redacted)
    redacted = _UNIX_PATH_RE.sub(REDACTED_PATH, redacted)
    return redacted


def _looks_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _looks_like_path(value: str) -> bool:
    return bool(_WINDOWS_PATH_RE.fullmatch(value) or _UNIX_PATH_RE.fullmatch(value))


def redact_json(value: Any, *, key: str = "") -> Any:
    """Recursively redact secret-looking values and path/email-bearing strings."""
    if isinstance(value, dict):
        return {str(k): redact_json(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_json(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [redact_json(item, key=key) for item in value]
    if isinstance(value, str):
        if _looks_sensitive_key(key):
            return REDACTED_SECRET if value else ""
        if _looks_like_path(value):
            return REDACTED_PATH
        return redact_text(value)
    return value


def _provider_snapshot() -> dict[str, Any]:
    from unifile.ai_providers import load_providers
    from unifile.media.providers import media_provider_statuses

    providers = load_providers()
    ai = {}
    for key, cfg in providers.items():
        ai[key] = {
            "name": cfg.get("name", key),
            "type": cfg.get("type", ""),
            "enabled": bool(cfg.get("enabled", False)),
            "priority": cfg.get("priority"),
            "url": redact_text(cfg.get("url", "")),
            "model": cfg.get("model", ""),
            "vision_model": cfg.get("vision_model", ""),
            "timeout": cfg.get("timeout"),
            "api_key_configured": bool(cfg.get("api_key", "")),
        }
    return {
        "ai_providers": ai,
        "media_providers": redact_json(media_provider_statuses()),
    }


def _system_summary() -> dict[str, Any]:
    return {
        "version": __version__,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "app_data_dir": REDACTED_PATH if _APP_DATA_DIR else "",
    }


def _read_recent_text(path: str, max_bytes: int) -> str:
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as handle:
            size = os.path.getsize(path)
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read(max_bytes)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def default_diagnostics_path() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(_APP_DATA_DIR, f"unifile-diagnostics-{timestamp}.zip")


def export_diagnostics_zip(output_path: str | None = None, *, max_log_bytes: int = 128 * 1024) -> str:
    """Create a redacted support diagnostics ZIP and return its path."""
    output = Path(output_path or default_diagnostics_path())
    output.parent.mkdir(parents=True, exist_ok=True)

    logs = {
        "crash.log": os.path.join(_APP_DATA_DIR, "crash.log"),
        "crash.log.1": os.path.join(_APP_DATA_DIR, "crash.log.1"),
        "move_log.csv": _CSV_LOG_FILE,
        "undo_stack.json": _UNDO_STACK_FILE,
        "watch_history.json": _WATCH_HISTORY_FILE,
    }

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "summary.json",
            json.dumps(redact_json(_system_summary()), indent=2, sort_keys=True),
        )
        zf.writestr(
            "providers.json",
            json.dumps(redact_json(_provider_snapshot()), indent=2, sort_keys=True),
        )
        for name, path in logs.items():
            text = _read_recent_text(path, max_log_bytes)
            if text:
                zf.writestr(f"logs/{name}", redact_text(text))
    return str(output)
