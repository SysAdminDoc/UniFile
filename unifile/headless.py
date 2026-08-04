"""Flask API and service layer for local, headless UniFile deployments."""
from __future__ import annotations

import hashlib
import hmac
import mimetypes
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

API_SCHEMA_VERSION = "1"
DEFAULT_LIBRARY_ROOT = os.path.join(os.path.expanduser("~"), "UniFileLibrary")
MAX_SCAN_ITEMS = 10_000
MAX_QUERY_RESULTS = 500
MOBILE_MAX_ENTRIES = 500
MOBILE_IMAGE_EXTENSIONS = {
    ".avif", ".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp",
}


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _inside(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    try:
        candidate = os.path.realpath(os.path.abspath(os.fspath(path)))
        base = os.path.realpath(os.path.abspath(os.fspath(root)))
        return os.path.commonpath([candidate, base]) == base
    except (OSError, ValueError):
        return False


class HeadlessService:
    """Thread-safe, Qt-free operations used by the Flask routes and scheduler."""

    def __init__(
        self,
        library_root: str | os.PathLike[str],
        *,
        scan_roots: list[str] | None = None,
        ollama_url: str = "",
        scan_interval: float = 0,
    ):
        self.library_root = Path(library_root).expanduser().resolve()
        self.library_root.mkdir(parents=True, exist_ok=True)
        roots = scan_roots or [str(self.library_root)]
        self.scan_roots = [Path(root).expanduser().resolve() for root in roots]
        self.ollama_url = str(ollama_url or "").strip()
        self.scan_interval = max(0.0, float(scan_interval or 0))
        self._lock = threading.RLock()
        self._scan_signatures: dict[str, str] = {}
        self._collaboration_store = None

    def _allowed_directory(self, value: str | None) -> Path:
        path = Path(value or self.library_root).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"scan path is not a directory: {path}")
        if not any(_inside(path, root) for root in self.scan_roots):
            raise PermissionError("path is outside configured scan roots")
        return path

    def _allowed_file(self, value: str) -> Path:
        path = Path(value).expanduser().resolve()
        if not _inside(path, self.library_root):
            raise PermissionError("file is outside the configured library root")
        if not path.is_file():
            raise ValueError(f"file does not exist: {path}")
        return path

    @contextmanager
    def _tag_library(self):
        from unifile.tagging.library import TagLibrary

        with self._lock:
            library = TagLibrary(str(self.library_root))
            if not library.open():
                raise RuntimeError("could not open tag library")
            try:
                yield library
            finally:
                library.close()

    def collaboration_store(self):
        """Return the library-scoped collaboration state store."""
        if self._collaboration_store is None:
            from unifile.collaboration import CollaborationStore

            with self._lock:
                if self._collaboration_store is None:
                    self._collaboration_store = CollaborationStore(self.library_root)
        return self._collaboration_store

    def scan(self, path: str | None = None, *, limit: int = MAX_SCAN_ITEMS) -> dict[str, Any]:
        """Return a reviewable rule-based scan plan without changing files."""
        from unifile.files import _build_ext_map, _classify_pc_item, _load_pc_categories

        source = self._allowed_directory(path)
        bounded_limit = max(1, min(MAX_SCAN_ITEMS, int(limit)))
        categories = _load_pc_categories()
        ext_map = _build_ext_map(categories)
        items = []
        with self._lock:
            for root, dirs, files in os.walk(source, followlinks=False):
                dirs[:] = [
                    name for name in dirs
                    if not name.startswith((".", "$"))
                    and not os.path.islink(os.path.join(root, name))
                ]
                for name in sorted(files, key=str.casefold):
                    if name.startswith((".", "$")):
                        continue
                    filepath = Path(root) / name
                    try:
                        if filepath.is_symlink() or not filepath.is_file():
                            continue
                        stat = filepath.stat()
                        category, confidence, method = _classify_pc_item(
                            str(filepath), ext_map, is_folder=False, categories=categories
                        )
                    except OSError:
                        continue
                    items.append({
                        "name": name,
                        "src": str(filepath),
                        "dst": "",
                        "category": category,
                        "confidence": confidence,
                        "method": method,
                        "size": stat.st_size,
                        "selected": False,
                        "status": "Pending",
                    })
                    if len(items) >= bounded_limit:
                        break
                if len(items) >= bounded_limit:
                    break
        signature = hashlib.sha256(
            "\n".join(
                f"{item['src']}|{item['size']}|{item['category']}|{item['confidence']}"
                for item in items
            ).encode("utf-8")
        ).hexdigest()
        key = str(source)
        changed = self._scan_signatures.get(key) != signature
        self._scan_signatures[key] = signature
        return {
            "version": API_SCHEMA_VERSION,
            "timestamp": datetime.now().isoformat(),
            "source": str(source),
            "mode": "headless-rule-based",
            "items": items,
            "count": len(items),
            "changed": changed,
        }

    @staticmethod
    def _entry_payload(entry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "path": str(entry.path),
            "name": entry.filename,
            "extension": entry.suffix,
            "tags": sorted(tag.name for tag in getattr(entry, "tags", set())),
        }

    def tag(self, path: str, tag_name: str, *, action: str = "add") -> dict[str, Any]:
        filepath = self._allowed_file(path)
        tag_name = str(tag_name).strip()
        action = str(action).strip().lower()
        if not tag_name or len(tag_name) > 120 or "\x00" in tag_name:
            raise ValueError("tag must be between 1 and 120 characters")
        if action not in {"add", "remove"}:
            raise ValueError("tag action must be add or remove")
        with self._tag_library() as library:
            entry = library.add_entry(str(filepath))
            tag = library.get_tag_by_name(tag_name)
            if tag is None and action == "add":
                tag = library.add_tag(tag_name)
            if entry is None or tag is None:
                raise RuntimeError("entry or tag could not be created")
            ok = (
                library.add_tags_to_entry(entry.id, [tag.id])
                if action == "add"
                else library.remove_tags_from_entry(entry.id, [tag.id])
            )
            if not ok:
                raise RuntimeError("tag operation failed")
            refreshed = library.get_entry(entry.id)
            return {"ok": True, "action": action, "tag": tag_name, "entry": self._entry_payload(refreshed)}

    def search(self, query: str, *, limit: int = 100) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if len(query) > 500:
            raise ValueError("search query is too long")
        bounded_limit = max(1, min(MAX_QUERY_RESULTS, int(limit)))
        with self._tag_library() as library:
            return [
                self._entry_payload(entry)
                for entry in library.search_entries(query, limit=bounded_limit)
            ]

    @staticmethod
    def _collab_tag_payload(tag, *, acl: list[str] | None = None, count: int | None = None) -> dict[str, Any]:
        payload = {
            "id": tag.id,
            "name": tag.name,
            "namespace": tag.namespace or "",
            "description": tag.description or "",
            "color_slug": tag.color_slug or "",
            "is_category": bool(tag.is_category),
        }
        if acl is not None:
            payload["allowed_roles"] = list(acl)
        if count is not None:
            payload["entry_count"] = int(count)
        return payload

    def _collab_entry_payload(self, entry, principal, store, library=None) -> dict[str, Any] | None:
        tags = sorted(getattr(entry, "tags", set()), key=lambda tag: tag.name.casefold())
        if any(not store.visible_tag(tag.name, principal) for tag in tags):
            return None
        path = Path(entry.path).expanduser().resolve(strict=False)
        try:
            relative = os.path.relpath(path, self.library_root)
        except ValueError:
            relative = entry.filename
        fields = library.get_entry_fields(entry.id) if library is not None else {}
        return {
            "id": entry.id,
            "path": relative,
            "name": entry.filename,
            "extension": entry.suffix,
            "tags": [tag.name for tag in tags],
            "fields": fields,
        }

    def collab_search(self, query: str, principal, *, limit: int = 100) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if len(query) > 500:
            raise ValueError("search query is too long")
        bounded_limit = max(1, min(MAX_QUERY_RESULTS, int(limit)))
        with self._tag_library() as library:
            results = []
            for entry in library.search_entries(query, limit=bounded_limit):
                payload = self._collab_entry_payload(entry, principal, self.collaboration_store(), library)
                if payload is not None:
                    results.append(payload)
            return results

    def collab_tags(self, principal) -> list[dict[str, Any]]:
        store = self.collaboration_store()
        acl = store.tag_acl()
        with self._tag_library() as library:
            counts = library.get_tag_entry_counts()
            tags = []
            for tag in library.get_all_tags():
                if not store.visible_tag(tag.name, principal):
                    continue
                tags.append(self._collab_tag_payload(
                    tag, acl=acl.get(tag.name), count=counts.get(tag.id, 0)
                ))
            return tags

    def collab_apply_tag(self, principal, *, entry_id: int | None = None,
                         path: str | None = None, tag_name: str,
                         action: str = "add", field_timestamp: str | None = None) -> dict[str, Any]:
        from unifile.collaboration import CollaborationError

        store = self.collaboration_store()
        if not store.can(principal, "editor"):
            raise PermissionError("editor role is required to apply tags")
        tag_name = str(tag_name or "").strip()
        action = str(action or "add").strip().lower()
        if not tag_name or len(tag_name) > 120 or "\x00" in tag_name:
            raise ValueError("tag must be between 1 and 120 characters")
        if action not in {"add", "remove"}:
            raise ValueError("tag action must be add or remove")
        if entry_id is None and not path:
            raise ValueError("entry_id or path is required")
        if entry_id is not None and path:
            raise ValueError("provide entry_id or path, not both")

        with self._lock:
            with self._tag_library() as library:
                entry = library.get_entry(int(entry_id)) if entry_id is not None else None
                if entry is None and path:
                    candidate = Path(path)
                    if not candidate.is_absolute():
                        candidate = self.library_root / candidate
                    filepath = self._allowed_file(str(candidate))
                    entry = library.add_entry(str(filepath))
                if entry is None:
                    raise LookupError("entry not found")
                tag = library.get_tag_by_name(tag_name)
                if tag is None:
                    raise LookupError("tag not found; an admin must create it first")
                if any(not store.visible_tag(existing.name, principal) for existing in entry.tags):
                    raise PermissionError("entry contains a restricted tag")
                implied = library.get_implied_tag_ids(tag.id) if action == "add" else {tag.id}
                implied_tags = [library.get_tag(candidate_id) for candidate_id in implied]
                if any(candidate is not None and not store.visible_tag(candidate.name, principal)
                       for candidate in implied_tags):
                    raise PermissionError("tag is restricted to the admin role")
                if not store.visible_tag(tag.name, principal):
                    raise PermissionError("tag is restricted to the admin role")
                field = f"entry:{entry.id}:tag:{tag.id}"
                version = store.accept_field(field, principal, field_timestamp)
                ok = (
                    library.add_tags_to_entry(entry.id, [tag.id])
                    if action == "add"
                    else library.remove_tags_from_entry(entry.id, [tag.id])
                )
                if not ok:
                    raise CollaborationError("tag operation failed")
                refreshed = library.get_entry(entry.id)
                payload = self._collab_entry_payload(refreshed, principal, store, library)
                if payload is None:
                    raise PermissionError("updated entry contains a restricted tag")
                store.record_audit(
                    principal,
                    f"tag.{action}",
                    f"entry:{entry.id}",
                    {"tag": tag.name},
                    field=field,
                    version=version,
                )
                return {
                    "ok": True,
                    "action": action,
                    "tag": tag.name,
                    "entry": payload,
                    "field_version": version,
                }

    def collab_admin_tags(self, principal, payload: dict[str, Any]) -> dict[str, Any]:
        from unifile.collaboration import CollaborationError

        store = self.collaboration_store()
        if not store.can(principal, "admin"):
            raise PermissionError("admin role is required to edit tags")
        payload = dict(payload or {})
        action = str(payload.get("action", "add")).strip().lower()
        timestamp = payload.get("field_timestamp")
        with self._lock:
            with self._tag_library() as library:
                if action == "add":
                    name = str(payload.get("name", "")).strip()
                    if not name:
                        raise ValueError("tag name is required")
                    if library.get_tag_by_name(name) is not None:
                        raise ValueError("tag already exists")
                    field = f"tag:name:{name.casefold()}:metadata"
                    version = store.accept_field(field, principal, timestamp)
                    tag = library.add_tag(
                        name,
                        shorthand=payload.get("shorthand"),
                        color_slug=payload.get("color_slug"),
                        is_category=bool(payload.get("is_category", False)),
                        parent_id=payload.get("parent_id"),
                        namespace=payload.get("namespace"),
                        description=payload.get("description"),
                    )
                    if tag is None:
                        raise CollaborationError("tag could not be created")
                    changes = {key: payload[key] for key in (
                        "name", "namespace", "description", "color_slug", "is_category"
                    ) if key in payload}
                    store.record_audit(principal, "tag.create", f"tag:{tag.id}", changes,
                                       field=field, version=version)
                    return {"ok": True, "action": action,
                            "tag": self._collab_tag_payload(tag, acl=store.tag_acl().get(tag.name, [])),
                            "field_version": version}

                tag = self._resolve_tag(library, payload)
                if tag is None:
                    raise LookupError("tag not found")
                if action == "acl":
                    roles = payload.get("roles", payload.get("allowed_roles", []))
                    if not isinstance(roles, (list, tuple, set)):
                        raise ValueError("roles must be a list")
                    field = f"tag:{tag.id}:acl"
                    version = store.accept_field(field, principal, timestamp)
                    acl = store.set_tag_acl(tag.name, list(roles))
                    store.record_audit(principal, "tag.acl", f"tag:{tag.id}", acl,
                                       field=field, version=version)
                    return {"ok": True, "action": action, "tag": tag.name,
                            "allowed_roles": next(iter(acl.values())), "field_version": version}
                if action == "delete":
                    field = f"tag:{tag.id}:delete"
                    version = store.accept_field(field, principal, timestamp)
                    deleted_name = tag.name
                    if not library.delete_tag(tag.id):
                        raise CollaborationError("tag could not be deleted")
                    store.record_audit(principal, "tag.delete", f"tag:{tag.id}",
                                       {"name": deleted_name}, field=field, version=version)
                    return {"ok": True, "action": action, "tag": deleted_name,
                            "field_version": version}
                if action != "update":
                    raise ValueError("tag action must be add, update, delete, or acl")
                changes = {}
                update_kwargs = {}
                for key in ("name", "color_slug", "is_category", "namespace", "is_hidden", "description", "icon"):
                    if key not in payload:
                        continue
                    value = payload[key]
                    if key in {"is_category", "is_hidden"}:
                        if not isinstance(value, bool):
                            raise ValueError(f"{key} must be boolean")
                    update_kwargs[key] = value
                    changes[key] = value
                if not update_kwargs:
                    raise ValueError("at least one tag field is required")
                versions = {}
                for key in update_kwargs:
                    field = f"tag:{tag.id}:{key}"
                    versions[key] = store.accept_field(field, principal, timestamp)
                if not library.update_tag(tag.id, **update_kwargs):
                    raise CollaborationError("tag could not be updated")
                refreshed = library.get_tag(tag.id)
                store.record_audit(principal, "tag.update", f"tag:{tag.id}", changes,
                                   field=f"tag:{tag.id}:metadata", version=versions.get("name") or next(iter(versions.values())))
                return {"ok": True, "action": action,
                        "tag": self._collab_tag_payload(refreshed, acl=store.tag_acl().get(refreshed.name, [])),
                        "field_versions": versions}

    @staticmethod
    def _resolve_tag(library, payload: dict[str, Any]):
        if payload.get("id") is not None:
            try:
                return library.get_tag(int(payload["id"]))
            except (TypeError, ValueError):
                raise ValueError("tag id must be an integer")
        name = str(payload.get("name", "")).strip()
        return library.get_tag_by_name(name) if name else None

    def collab_rules(self, principal, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        store = self.collaboration_store()
        if not store.can(principal, "admin"):
            raise PermissionError("admin role is required to edit rules")
        if payload is None:
            return {"rules": store.get_rules()}
        rules = payload.get("rules")
        if not isinstance(rules, list):
            raise ValueError("rules must be a list")
        with self._lock:
            version = store.accept_field("rules", principal, payload.get("field_timestamp"))
            saved = store.set_rules(rules)
            store.record_audit(principal, "rules.update", "rules",
                               {"count": len(saved)}, field="rules", version=version)
        return {"ok": True, "rules": saved, "field_version": version}

    def collab_users(self, principal) -> list[dict[str, str]]:
        store = self.collaboration_store()
        if not store.can(principal, "admin"):
            raise PermissionError("admin role is required to manage users")
        return store.list_users()

    def collab_audit(self, principal, *, limit: int = 200) -> list[dict[str, Any]]:
        store = self.collaboration_store()
        if not store.can(principal, "admin"):
            raise PermissionError("admin role is required to view the audit log")
        return store.audit_events(limit)

    def _mobile_entry_payload(self, entry, fields: dict[str, str] | None = None) -> dict[str, Any]:
        """Build a read-only payload without leaking an absolute filesystem path."""
        path = Path(entry.path).expanduser().resolve(strict=False)
        relative = os.path.relpath(path, self.library_root)
        try:
            stat = path.stat()
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            is_file = path.is_file()
        except OSError:
            size = None
            modified = ""
            is_file = False
        payload = {
            "id": entry.id,
            "path": relative,
            "name": entry.filename,
            "extension": entry.suffix,
            "size": size,
            "modified": modified,
            "tags": sorted(tag.name for tag in getattr(entry, "tags", set())),
            "fields": fields or {},
            "preview_url": None,
            "mime_type": mimetypes.guess_type(str(path))[0] or "application/octet-stream",
            "absolute_path": str(path),
        }
        if is_file and path.suffix.lower() in MOBILE_IMAGE_EXTENSIONS and _inside(path, self.library_root):
            payload["preview_url"] = f"/mobile/api/entries/{entry.id}/preview"
        return payload

    def mobile_library(self) -> dict[str, Any]:
        """Return the minimal catalog summary needed by the PWA shell."""
        with self._tag_library() as library:
            tags = library.get_all_tags()
            counts = library.get_tag_entry_counts()
            return {
                "version": API_SCHEMA_VERSION,
                "library_root": str(self.library_root),
                "entry_count": library.get_entry_count(),
                "tag_count": len(tags),
                "tags": [
                    {"name": tag.name, "entry_count": counts.get(tag.id, 0)}
                    for tag in tags
                    if counts.get(tag.id, 0) > 0
                ],
            }

    def mobile_entries(self, *, query: str = "", tag: str = "", limit: int = 80,
                       offset: int = 0) -> list[dict[str, Any]]:
        """Return paginated entries for the read-only companion."""
        query = str(query or "").strip()
        tag = str(tag or "").strip()
        if len(query) > 500 or len(tag) > 120:
            raise ValueError("mobile search query is too long")
        bounded_limit = max(1, min(MOBILE_MAX_ENTRIES, int(limit)))
        bounded_offset = max(0, int(offset))
        with self._tag_library() as library:
            if tag:
                tag_obj = library.get_tag_by_name(tag)
                entries = library.get_entries_by_tag(tag_obj.id) if tag_obj else []
                entries = entries[bounded_offset:bounded_offset + bounded_limit]
            elif query:
                entries = library.search_entries(query, limit=MOBILE_MAX_ENTRIES)
                entries = entries[bounded_offset:bounded_offset + bounded_limit]
            else:
                entries = library.get_all_entries(limit=bounded_limit, offset=bounded_offset)
            payloads = [
                self._mobile_entry_payload(entry, library.get_entry_fields(entry.id))
                for entry in entries
            ]
            for payload in payloads:
                payload.pop("absolute_path", None)
            return payloads

    def mobile_entry(self, entry_id: int, *, include_private: bool = False) -> dict[str, Any] | None:
        """Return one entry and its fields for the mobile detail/preview route."""
        with self._tag_library() as library:
            entry = library.get_entry(entry_id)
            if entry is None:
                return None
            payload = self._mobile_entry_payload(entry, library.get_entry_fields(entry.id))
        if not include_private:
            payload.pop("absolute_path", None)
        return payload

    def report(self) -> dict[str, Any]:
        with self._tag_library() as library:
            tags = library.get_all_tags()
            counts = library.get_tag_entry_counts()
            return {
                "version": API_SCHEMA_VERSION,
                "timestamp": datetime.now().isoformat(),
                "library_root": str(self.library_root),
                "entry_count": library.get_entry_count(),
                "tag_count": len(tags),
                "tags": [
                    {"name": tag.name, "entry_count": counts.get(tag.id, 0)}
                    for tag in tags
                ],
            }

    def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        action = job.get("action", "scan")
        if action == "scan":
            plan = self.scan(job.get("path"))
            return {
                "changed": bool(plan.get("changed")),
                "count": plan.get("count", 0),
                "source": plan.get("source", ""),
            }
        result = self.tag(job.get("path", ""), job.get("tag", ""), action="add")
        return {"changed": bool(result.get("ok")), "entry": result.get("entry", {})}


def create_app(config: dict[str, Any] | None = None, *, service: HeadlessService | None = None):
    """Create the Qt-free Flask application used by Docker and local tests."""
    try:
        from flask import Flask, jsonify, render_template_string, request
    except ImportError as exc:
        raise RuntimeError("Flask is required for the headless API; install the full extra") from exc

    supplied = dict(config or {})
    library_root = supplied.get("LIBRARY_ROOT") or os.environ.get(
        "UNIFILE_LIBRARY_DIR", DEFAULT_LIBRARY_ROOT
    )
    scan_roots = supplied.get("SCAN_ROOTS")
    if scan_roots is None:
        raw_roots = os.environ.get("UNIFILE_SCAN_ROOTS", "").strip()
        scan_roots = [root for root in raw_roots.split(os.pathsep) if root] or None
    ollama_url = supplied.get("OLLAMA_URL") or os.environ.get("OLLAMA_URL", "http://localhost:11434")
    scan_interval = supplied.get("SCAN_INTERVAL", os.environ.get("SCAN_INTERVAL", 0))
    api_key = str(supplied.get("API_KEY", os.environ.get("UNIFILE_API_KEY", "")))
    collaborative_mode = supplied.get(
        "COLLABORATIVE_MODE",
        _truthy(os.environ.get("UNIFILE_COLLABORATIVE_MODE", "")),
    )
    allow_unauthenticated = supplied.get(
        "ALLOW_UNAUTHENTICATED",
        _truthy(os.environ.get("UNIFILE_ALLOW_UNAUTHENTICATED", "")),
    )
    service = service or HeadlessService(
        library_root,
        scan_roots=scan_roots,
        ollama_url=ollama_url,
        scan_interval=float(scan_interval or 0),
    )
    app = Flask(__name__)
    app.config.update(
        API_KEY=api_key,
        ALLOW_UNAUTHENTICATED=bool(allow_unauthenticated),
        LIBRARY_ROOT=str(service.library_root),
        OLLAMA_URL=service.ollama_url,
        SCAN_INTERVAL=service.scan_interval,
        MOBILE_ONLY=bool(supplied.get("MOBILE_ONLY", False)),
        MOBILE_TOKEN=str(supplied.get("MOBILE_TOKEN", "")),
        COLLABORATIVE_MODE=bool(collaborative_mode),
        SCHEDULER_FILE=str(supplied.get("SCHEDULER_FILE", os.path.join(
            os.path.expanduser("~"), "UniFile", "headless_jobs.json"
        ))),
    )
    app.extensions["unifile_service"] = service

    def _auth_error():
        if request.path == "/health":
            return None
        if app.config.get("MOBILE_ONLY") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            return jsonify({"error": "mobile companion is read-only"}), 405
        if request.path.startswith("/mobile"):
            expected = str(app.config.get("MOBILE_TOKEN", ""))
            provided = request.headers.get("X-API-Key", "") or request.args.get("token", "")
            if not expected:
                return jsonify({"error": "mobile token is not configured"}), 503
            if not hmac.compare_digest(provided, expected):
                return jsonify({"error": "invalid mobile token"}), 401
            return None
        if app.config.get("COLLABORATIVE_MODE"):
            from unifile.collaboration import ROLE_RANK

            user_id = request.headers.get("X-UniFile-User", "") or request.headers.get("X-User", "")
            token = request.headers.get("X-UniFile-Token", "")
            if not token:
                authorization = request.headers.get("Authorization", "")
                if authorization.lower().startswith("bearer "):
                    token = authorization[7:].strip()
            principal = service.collaboration_store().authenticate(user_id, token)
            if principal is None:
                return jsonify({"error": "valid collaboration user and token are required"}), 401
            request.environ["unifile_principal"] = principal
            path = request.path
            required_role = "admin"
            if path in {"/search", "/tag"} and request.method == "GET":
                required_role = "viewer"
            elif path == "/collab/search" or path == "/collab/me":
                required_role = "viewer"
            elif path in {"/tag", "/collab/tag"} and request.method == "POST":
                required_role = "editor"
            elif path == "/collab/tags" and request.method == "GET":
                required_role = "editor"
            if ROLE_RANK.get(principal.role, -1) < ROLE_RANK[required_role]:
                return jsonify({"error": f"{required_role} role is required"}), 403
            return None
        expected = app.config.get("API_KEY", "")
        if not expected:
            if app.config.get("ALLOW_UNAUTHENTICATED"):
                return None
            return jsonify({"error": "API key is not configured"}), 503
        provided = request.headers.get("X-API-Key", "")
        if not provided:
            authorization = request.headers.get("Authorization", "")
            if authorization.lower().startswith("bearer "):
                provided = authorization[7:].strip()
        if not hmac.compare_digest(provided, expected):
            return jsonify({"error": "invalid API key"}), 401
        return None

    @app.before_request
    def _authenticate():
        return _auth_error()

    @app.get("/health")
    def health():
        scheduler = app.extensions.get("unifile_scheduler")
        return jsonify({
            "status": "ok",
            "version": API_SCHEMA_VERSION,
            "library_root": str(service.library_root),
            "ollama_url": service.ollama_url,
            "scan_interval": service.scan_interval,
            "scheduler_running": bool(scheduler and scheduler._thread and scheduler._thread.is_alive()),
            "collaborative_mode": bool(app.config.get("COLLABORATIVE_MODE")),
        })

    @app.get("/admin")
    def admin():
        return render_template_string(
            """<!doctype html><title>UniFile headless admin</title>
            <h1>UniFile headless admin</h1>
            <p>Library: <code>{{ library_root }}</code></p>
            <p>Ollama: <code>{{ ollama_url }}</code></p>
            <ul><li><a href='/health'>Health JSON</a></li><li><a href='/jobs'>Scheduled jobs JSON</a></li></ul>
            <p>Use the authenticated API for scans, tags, search, reports, and job changes.</p>""",
            library_root=str(service.library_root),
            ollama_url=service.ollama_url,
        )

    @app.post("/scan")
    def scan():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(service.scan(payload.get("path"), limit=payload.get("limit", MAX_SCAN_ITEMS)))
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except (OSError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/tag", methods=["GET", "POST"])
    def tag():
        if request.method == "GET":
            try:
                query = request.args.get("query", "")
                if app.config.get("COLLABORATIVE_MODE"):
                    entries = service.collab_search(
                        query, request.environ["unifile_principal"], limit=request.args.get("limit", 100)
                    )
                else:
                    entries = service.search(query, limit=request.args.get("limit", 100))
                return jsonify({"query": query, "entries": entries})
            except (TypeError, ValueError, OSError) as exc:
                return jsonify({"error": str(exc)}), 400
        payload = request.get_json(silent=True) or {}
        try:
            if app.config.get("COLLABORATIVE_MODE"):
                result = service.collab_apply_tag(
                    request.environ["unifile_principal"],
                    entry_id=payload.get("entry_id"),
                    path=payload.get("path"),
                    tag_name=payload.get("tag", ""),
                    action=payload.get("action", "add"),
                    field_timestamp=payload.get("field_timestamp"),
                )
                return jsonify(result)
            return jsonify(service.tag(payload.get("path", ""), payload.get("tag", ""),
                                       action=payload.get("action", "add")))
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            from unifile.collaboration import CollaborationConflict, CollaborationError

            if isinstance(exc, CollaborationConflict):
                return jsonify({"error": str(exc), "conflict": True,
                                "field": exc.field, "current": exc.current}), 409
            if isinstance(exc, CollaborationError) and app.config.get("COLLABORATIVE_MODE"):
                return jsonify({"error": str(exc)}), 400
            if not app.config.get("COLLABORATIVE_MODE") and isinstance(exc, (OSError, TypeError, ValueError, RuntimeError)):
                return jsonify({"error": str(exc)}), 400
            raise

    @app.route("/search", methods=["GET", "POST"])
    def search():
        payload = request.get_json(silent=True) or {} if request.method == "POST" else {}
        query = payload.get("query", "") if request.method == "POST" else request.args.get("query", "")
        limit = payload.get("limit", 100) if request.method == "POST" else request.args.get("limit", 100)
        try:
            entries = (
                service.collab_search(query, request.environ["unifile_principal"], limit=limit)
                if app.config.get("COLLABORATIVE_MODE")
                else service.search(query, limit=limit)
            )
            return jsonify({"query": query, "entries": entries})
        except (TypeError, ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/report", methods=["GET", "POST"])
    def report():
        try:
            return jsonify(service.report())
        except (OSError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 500

    if app.config.get("COLLABORATIVE_MODE"):
        def _principal():
            return request.environ["unifile_principal"]

        @app.get("/collab/me")
        def collab_me():
            return jsonify(_principal().to_dict())

        @app.get("/collab/search")
        def collab_search():
            try:
                query = request.args.get("query", "")
                entries = service.collab_search(query, _principal(), limit=request.args.get("limit", 100))
                return jsonify({"query": query, "entries": entries})
            except (TypeError, ValueError, OSError) as exc:
                return jsonify({"error": str(exc)}), 400

        @app.post("/collab/tag")
        def collab_tag():
            payload = request.get_json(silent=True) or {}
            try:
                return jsonify(service.collab_apply_tag(
                    _principal(),
                    entry_id=payload.get("entry_id"),
                    path=payload.get("path"),
                    tag_name=payload.get("tag", ""),
                    action=payload.get("action", "add"),
                    field_timestamp=payload.get("field_timestamp"),
                ))
            except PermissionError as exc:
                return jsonify({"error": str(exc)}), 403
            except LookupError as exc:
                return jsonify({"error": str(exc)}), 404
            except Exception as exc:
                from unifile.collaboration import CollaborationConflict, CollaborationError

                if isinstance(exc, CollaborationConflict):
                    return jsonify({"error": str(exc), "conflict": True,
                                    "field": exc.field, "current": exc.current}), 409
                if isinstance(exc, CollaborationError):
                    return jsonify({"error": str(exc)}), 400
                if isinstance(exc, (OSError, TypeError, ValueError, RuntimeError)):
                    return jsonify({"error": str(exc)}), 400
                raise

        @app.route("/collab/tags", methods=["GET", "POST"])
        def collab_tags():
            if request.method == "GET":
                return jsonify({"tags": service.collab_tags(_principal())})
            try:
                return jsonify(service.collab_admin_tags(_principal(), request.get_json(silent=True) or {}))
            except PermissionError as exc:
                return jsonify({"error": str(exc)}), 403
            except LookupError as exc:
                return jsonify({"error": str(exc)}), 404
            except Exception as exc:
                from unifile.collaboration import CollaborationConflict, CollaborationError

                if isinstance(exc, CollaborationConflict):
                    return jsonify({"error": str(exc), "conflict": True,
                                    "field": exc.field, "current": exc.current}), 409
                if isinstance(exc, (CollaborationError, OSError, TypeError, ValueError, RuntimeError)):
                    return jsonify({"error": str(exc)}), 400
                raise

        @app.route("/collab/rules", methods=["GET", "POST"])
        def collab_rules():
            try:
                if request.method == "GET":
                    return jsonify(service.collab_rules(_principal()))
                return jsonify(service.collab_rules(_principal(), request.get_json(silent=True) or {}))
            except PermissionError as exc:
                return jsonify({"error": str(exc)}), 403
            except Exception as exc:
                from unifile.collaboration import CollaborationConflict, CollaborationError

                if isinstance(exc, CollaborationConflict):
                    return jsonify({"error": str(exc), "conflict": True,
                                    "field": exc.field, "current": exc.current}), 409
                if isinstance(exc, (CollaborationError, OSError, TypeError, ValueError, RuntimeError)):
                    return jsonify({"error": str(exc)}), 400
                raise

        @app.route("/collab/users", methods=["GET", "POST"])
        def collab_users():
            store = service.collaboration_store()
            principal = _principal()
            if request.method == "GET":
                return jsonify({"users": service.collab_users(principal)})
            try:
                payload = request.get_json(silent=True) or {}
                created = store.create_user(
                    payload.get("user_id", ""),
                    payload.get("display_name"),
                    payload.get("role", "viewer"),
                    token=payload.get("token"),
                )
                store.record_audit(principal, "user.create", f"user:{created['user_id']}",
                                   {"role": created["role"]})
                return jsonify(created), 201
            except PermissionError as exc:
                return jsonify({"error": str(exc)}), 403
            except Exception as exc:
                from unifile.collaboration import CollaborationError

                if isinstance(exc, (CollaborationError, OSError, TypeError, ValueError)):
                    return jsonify({"error": str(exc)}), 400
                raise

        @app.get("/collab/audit")
        def collab_audit():
            try:
                return jsonify({"events": service.collab_audit(
                    _principal(), limit=request.args.get("limit", 200)
                )})
            except (PermissionError, TypeError, ValueError, OSError) as exc:
                return jsonify({"error": str(exc)}), 403 if isinstance(exc, PermissionError) else 400

    if app.config.get("MOBILE_ONLY") or app.config.get("MOBILE_TOKEN"):
        from unifile.mobile import register_mobile_routes

        register_mobile_routes(app, service)

    from unifile.scheduler import JobScheduler, load_jobs, save_jobs, validate_job

    scheduler_file = app.config["SCHEDULER_FILE"]

    @app.get("/jobs")
    def jobs_get():
        return jsonify({"jobs": load_jobs(scheduler_file)})

    @app.post("/jobs")
    def jobs_post():
        payload = request.get_json(silent=True) or {}
        try:
            job = validate_job(payload)
            jobs = load_jobs(scheduler_file)
            if any(existing["id"] == job["id"] for existing in jobs):
                return jsonify({"error": "job id already exists"}), 409
            jobs.append(job)
            if not save_jobs(jobs, scheduler_file):
                raise OSError("could not save scheduled jobs")
            return jsonify(job), 201
        except (OSError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.delete("/jobs/<job_id>")
    def jobs_delete(job_id: str):
        jobs = load_jobs(scheduler_file)
        remaining = [job for job in jobs if job["id"] != job_id]
        if len(remaining) == len(jobs):
            return jsonify({"error": "job not found"}), 404
        if not save_jobs(remaining, scheduler_file):
            return jsonify({"error": "could not save scheduled jobs"}), 500
        return jsonify({"deleted": job_id})

    scheduler = JobScheduler(service.run_job, path=scheduler_file)
    app.extensions["unifile_scheduler"] = scheduler
    if _truthy(supplied.get("START_SCHEDULER", os.environ.get("UNIFILE_START_SCHEDULER", ""))):
        scheduler.start()

    return app


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Qt-free UniFile Flask API")
    parser.add_argument("--host", default=os.environ.get("UNIFILE_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("UNIFILE_API_PORT", "8787")))
    args = parser.parse_args(argv)
    app = create_app({"START_SCHEDULER": True})
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
