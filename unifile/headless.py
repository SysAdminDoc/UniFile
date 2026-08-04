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
                return jsonify({"query": request.args.get("query", ""), "entries": service.search(
                    request.args.get("query", ""), limit=request.args.get("limit", 100)
                )})
            except (TypeError, ValueError, OSError) as exc:
                return jsonify({"error": str(exc)}), 400
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(service.tag(payload.get("path", ""), payload.get("tag", ""),
                                       action=payload.get("action", "add")))
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/search", methods=["GET", "POST"])
    def search():
        payload = request.get_json(silent=True) or {} if request.method == "POST" else {}
        query = payload.get("query", "") if request.method == "POST" else request.args.get("query", "")
        limit = payload.get("limit", 100) if request.method == "POST" else request.args.get("limit", 100)
        try:
            return jsonify({"query": query, "entries": service.search(query, limit=limit)})
        except (TypeError, ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/report", methods=["GET", "POST"])
    def report():
        try:
            return jsonify(service.report())
        except (OSError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 500

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
