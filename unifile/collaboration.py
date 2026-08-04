"""Identity, role, ACL, conflict, and audit primitives for LAN collaboration."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unifile.config import load_json_safe, save_json_safe

COLLAB_SCHEMA_VERSION = 1
COLLAB_FILENAME = "collaboration.json"
MAX_AUDIT_EVENTS = 2_000
ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}
DEFAULT_TAG_ACL = {"tag:confidential": ["admin"]}
_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class CollaborationError(RuntimeError):
    """Invalid collaboration configuration or operation."""


class CollaborationConflict(CollaborationError):
    """A stale per-field write lost a last-write-wins comparison."""

    def __init__(self, field: str, current: dict | None):
        super().__init__(f"stale collaboration write for {field}")
        self.field = field
        self.current = current or {}


@dataclass(frozen=True)
class UserPrincipal:
    user_id: str
    display_name: str
    role: str

    def to_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "role": self.role,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized not in ROLE_RANK:
        raise CollaborationError(f"unknown role: {role}")
    return normalized


class CollaborationStore:
    """Atomic JSON-backed collaboration state scoped to a tag-library root."""

    def __init__(self, library_root: str | Path):
        self.library_root = Path(library_root).expanduser().resolve()
        self.state_path = self.library_root / ".unifile" / COLLAB_FILENAME
        self._lock = threading.RLock()

    @staticmethod
    def _default_state() -> dict:
        return {
            "version": COLLAB_SCHEMA_VERSION,
            "users": [],
            "tag_acl": dict(DEFAULT_TAG_ACL),
            "field_versions": {},
            "audit": [],
            "rules": [],
        }

    def _load(self) -> dict:
        state = load_json_safe(str(self.state_path), self._default_state(), expected_type=dict)
        if not isinstance(state, dict):
            state = self._default_state()
        state.setdefault("version", COLLAB_SCHEMA_VERSION)
        if not isinstance(state.get("users"), list):
            state["users"] = []
        if not isinstance(state.get("tag_acl"), dict):
            state["tag_acl"] = dict(DEFAULT_TAG_ACL)
        if not isinstance(state.get("field_versions"), dict):
            state["field_versions"] = {}
        if not isinstance(state.get("audit"), list):
            state["audit"] = []
        if not isinstance(state.get("rules"), list):
            state["rules"] = []
        return state

    def _save(self, state: dict) -> None:
        if not save_json_safe(str(self.state_path), state):
            raise CollaborationError(f"could not save collaboration state: {self.state_path}")

    @property
    def has_users(self) -> bool:
        with self._lock:
            return bool(self._load().get("users"))

    def create_user(self, user_id: str, display_name: str | None = None,
                    role: str = "viewer", *, token: str | None = None) -> dict[str, str]:
        user_id = str(user_id or "").strip()
        if not _USER_ID_RE.fullmatch(user_id):
            raise CollaborationError("user id must be 1-64 letters, digits, dot, dash, or underscore")
        role = _normalize_role(role)
        display_name = str(display_name or user_id).strip()[:120] or user_id
        token = str(token or secrets.token_urlsafe(32))
        if len(token) < 16:
            raise CollaborationError("user token must be at least 16 characters")
        with self._lock:
            state = self._load()
            if any(str(item.get("user_id", "")).casefold() == user_id.casefold()
                   for item in state["users"] if isinstance(item, dict)):
                raise CollaborationError(f"user already exists: {user_id}")
            state["users"].append({
                "user_id": user_id,
                "display_name": display_name,
                "role": role,
                "token_hash": _token_hash(token),
                "created_at": utc_now(),
            })
            self._save(state)
        return {"user_id": user_id, "display_name": display_name, "role": role, "token": token}

    def authenticate(self, user_id: str, token: str) -> UserPrincipal | None:
        user_id = str(user_id or "").strip()
        token = str(token or "")
        if not user_id or not token:
            return None
        with self._lock:
            state = self._load()
            for item in state.get("users", []):
                if not isinstance(item, dict) or str(item.get("user_id", "")).casefold() != user_id.casefold():
                    continue
                if not hmac.compare_digest(str(item.get("token_hash", "")), _token_hash(token)):
                    return None
                role = str(item.get("role", "viewer")).lower()
                if role not in ROLE_RANK:
                    return None
                return UserPrincipal(
                    user_id=str(item.get("user_id", user_id)),
                    display_name=str(item.get("display_name", user_id)),
                    role=role,
                )
        return None

    def list_users(self) -> list[dict[str, str]]:
        with self._lock:
            result = []
            for item in self._load().get("users", []):
                if not isinstance(item, dict):
                    continue
                result.append({
                    "user_id": str(item.get("user_id", "")),
                    "display_name": str(item.get("display_name", "")),
                    "role": str(item.get("role", "viewer")),
                    "created_at": str(item.get("created_at", "")),
                })
            return sorted(result, key=lambda user: user["user_id"].casefold())

    def can(self, principal: UserPrincipal, required_role: str) -> bool:
        return ROLE_RANK.get(principal.role, -1) >= ROLE_RANK.get(required_role, 99)

    def visible_tag(self, tag_name: str, principal: UserPrincipal) -> bool:
        normalized = str(tag_name or "").casefold()
        with self._lock:
            acl = self._load().get("tag_acl", {})
        allowed = None
        for restricted_name, roles in acl.items():
            if str(restricted_name).casefold() == normalized:
                allowed = {str(role).lower() for role in roles if str(role).lower() in ROLE_RANK}
                break
        return allowed is None or principal.role in allowed

    def filter_visible_tags(self, tag_names: list[str], principal: UserPrincipal) -> list[str]:
        return sorted(
            {name for name in tag_names if self.visible_tag(name, principal)},
            key=str.casefold,
        )

    def tag_acl(self) -> dict[str, list[str]]:
        with self._lock:
            state = self._load()
            acl = state.get("tag_acl", {})
            return {
                str(name): sorted({str(role).lower() for role in roles if str(role).lower() in ROLE_RANK})
                for name, roles in acl.items()
                if isinstance(roles, (list, tuple, set))
            }

    def set_tag_acl(self, tag_name: str, roles: list[str] | tuple[str, ...] | set[str]) -> dict[str, list[str]]:
        tag_name = str(tag_name or "").strip()
        if not tag_name or len(tag_name) > 120 or "\x00" in tag_name:
            raise CollaborationError("tag name must be between 1 and 120 characters")
        if not isinstance(roles, (list, tuple, set)):
            raise CollaborationError("tag ACL roles must be a list")
        normalized_roles = sorted({_normalize_role(role) for role in roles})
        if not normalized_roles:
            raise CollaborationError("tag ACL must allow at least one role")
        with self._lock:
            state = self._load()
            acl = dict(state.get("tag_acl", {}))
            existing_name = next(
                (str(name) for name in acl if str(name).casefold() == tag_name.casefold()),
                tag_name,
            )
            acl[existing_name] = normalized_roles
            state["tag_acl"] = acl
            self._save(state)
        return {existing_name: normalized_roles}

    def get_rules(self) -> list[dict]:
        with self._lock:
            state = self._load()
            rules = state.get("rules", [])
            return [dict(rule) for rule in rules if isinstance(rule, dict)]

    def set_rules(self, rules: list[dict]) -> list[dict]:
        if not isinstance(rules, list) or len(rules) > 1_000:
            raise CollaborationError("rules must be a list of at most 1000 objects")
        normalized = []
        for rule in rules:
            if not isinstance(rule, dict):
                raise CollaborationError("each rule must be a JSON object")
            try:
                json.dumps(rule)
            except (TypeError, ValueError) as exc:
                raise CollaborationError("rules must contain JSON-compatible values") from exc
            normalized.append(dict(rule))
        with self._lock:
            state = self._load()
            state["rules"] = normalized
            self._save(state)
        return [dict(rule) for rule in normalized]

    def field_version(self, field: str) -> dict | None:
        with self._lock:
            version = self._load().get("field_versions", {}).get(str(field))
            return dict(version) if isinstance(version, dict) else None

    def accept_field(self, field: str, principal: UserPrincipal,
                     client_timestamp: str | None = None) -> dict:
        """Accept a write when its timestamp wins, returning the server version."""
        field = str(field)
        incoming = _parse_timestamp(client_timestamp)
        with self._lock:
            state = self._load()
            current = state.get("field_versions", {}).get(field)
            current_timestamp = _parse_timestamp(current.get("timestamp")) if isinstance(current, dict) else None
            if incoming is not None and current_timestamp is not None and incoming < current_timestamp:
                raise CollaborationConflict(field, current)
            now = datetime.now(timezone.utc)
            effective = incoming or now
            if current_timestamp is not None and effective <= current_timestamp:
                effective = current_timestamp + timedelta(microseconds=1)
            version = {
                "timestamp": effective.isoformat(timespec="microseconds"),
                "user_id": principal.user_id,
            }
            state["field_versions"][field] = version
            self._save(state)
            return version

    def record_audit(self, principal: UserPrincipal, action: str, resource: str,
                     changes: dict | None = None, *, field: str = "", version: dict | None = None) -> dict:
        event = {
            "timestamp": utc_now(),
            "user_id": principal.user_id,
            "display_name": principal.display_name,
            "role": principal.role,
            "action": str(action),
            "resource": str(resource),
            "changes": dict(changes or {}),
        }
        if field:
            event["field"] = str(field)
        if version:
            event["field_version"] = dict(version)
        with self._lock:
            state = self._load()
            audit = [item for item in state.get("audit", []) if isinstance(item, dict)]
            audit.append(event)
            state["audit"] = audit[-MAX_AUDIT_EVENTS:]
            self._save(state)
        return event

    def audit_events(self, limit: int = 200) -> list[dict]:
        bounded = max(1, min(MAX_AUDIT_EVENTS, int(limit)))
        with self._lock:
            audit = [item for item in self._load().get("audit", []) if isinstance(item, dict)]
        return list(reversed(audit[-bounded:]))


def collaboration_state_path(library_root: str | Path) -> Path:
    return Path(library_root).expanduser().resolve() / ".unifile" / COLLAB_FILENAME


class CollaborationClient:
    """Small dependency-free client for the collaborative headless API."""

    def __init__(self, base_url: str, user_id: str, token: str, *, timeout: float = 15.0):
        self.base_url = str(base_url).rstrip("/")
        self.user_id = str(user_id).strip()
        self.token = str(token)
        self.timeout = max(1.0, float(timeout))
        if not self.base_url or not self.user_id or not self.token:
            raise CollaborationError("URL, user id, and token are required")

    def request(self, method: str, path: str, *, query: dict | None = None,
                payload: dict | None = None) -> dict:
        url = f"{self.base_url}/{str(path).lstrip('/')}"
        if query:
            encoded = urllib.parse.urlencode({key: value for key, value in query.items() if value is not None})
            if encoded:
                url = f"{url}?{encoded}"
        body = None
        headers = {
            "Accept": "application/json",
            "X-UniFile-User": self.user_id,
            "X-UniFile-Token": self.token,
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                result = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except (TypeError, ValueError):
                detail = {"error": raw or exc.reason}
            raise CollaborationError(f"HTTP {exc.code}: {detail.get('error', detail)}") from exc
        except (OSError, ValueError) as exc:
            raise CollaborationError(f"collaboration request failed: {exc}") from exc
        if not isinstance(result, dict):
            raise CollaborationError("collaboration server returned invalid JSON")
        return result

    def search(self, query: str = "", *, limit: int = 100) -> dict:
        return self.request("GET", "/collab/search", query={"query": query, "limit": limit})

    def apply_tag(self, *, entry_id: int | None = None, path: str | None = None,
                  tag: str, action: str = "add", field_timestamp: str | None = None) -> dict:
        payload = {"tag": tag, "action": action}
        if entry_id is not None:
            payload["entry_id"] = entry_id
        if path is not None:
            payload["path"] = path
        if field_timestamp is not None:
            payload["field_timestamp"] = field_timestamp
        return self.request("POST", "/collab/tag", payload=payload)


__all__ = [
    "COLLAB_FILENAME",
    "CollaborationConflict",
    "CollaborationError",
    "CollaborationStore",
    "CollaborationClient",
    "ROLE_RANK",
    "UserPrincipal",
    "collaboration_state_path",
]
