"""YAML plugin manifests, local scaffolding, and community index discovery.

Manifest files describe a small Python plugin package without importing it.
The existing fingerprint/trust gate remains the authority for executing the
entrypoint; this module only parses metadata, resolves a safe entrypoint, and
reads a bounded read-only community index.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from unifile.network import request_bytes

MANIFEST_FILENAME = "plugin.yaml"
MANIFEST_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 128 * 1024
MAX_INDEX_BYTES = 512 * 1024
DEFAULT_COMMUNITY_INDEX_URL = (
    "https://raw.githubusercontent.com/SysAdminDoc/UniFile/master/plugin-index.json"
)

SUPPORTED_HOOKS = (
    "classify",
    "rename_token",
    "post_move",
    "post_scan",
    "on_scan_item",
    "on_apply",
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+){1,79}$")


class ManifestError(ValueError):
    """Raised when a plugin manifest is missing or outside the supported schema."""


def _bounded_text(value: Any, field: str, *, maximum: int, required: bool = False) -> str:
    if value is None:
        text = ""
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
    else:
        raise ManifestError(f"{field} must be text")
    if required and not text:
        raise ManifestError(f"{field} is required")
    if len(text) > maximum:
        raise ManifestError(f"{field} exceeds {maximum} characters")
    return text


def _normalize_hooks(raw: Any) -> dict[str, str]:
    """Normalize both the documented list-of-maps and a compact mapping form."""
    if isinstance(raw, dict):
        entries = list(raw.items())
    elif isinstance(raw, list):
        entries = []
        for item in raw:
            if not isinstance(item, dict) or len(item) != 1:
                raise ManifestError("hooks list entries must contain one hook mapping")
            entries.extend(item.items())
    else:
        raise ManifestError("hooks must be a mapping or list of one-item mappings")

    hooks: dict[str, str] = {}
    for hook_value, function_value in entries:
        hook = _bounded_text(hook_value, "hook", maximum=40, required=True)
        function = _bounded_text(function_value, f"function for {hook}", maximum=64, required=True)
        if hook not in SUPPORTED_HOOKS:
            raise ManifestError(
                f"unsupported hook '{hook}'; choose from {', '.join(SUPPORTED_HOOKS)}"
            )
        if not _IDENTIFIER_RE.fullmatch(function) or function.startswith("__"):
            raise ManifestError(f"function for {hook} must be a public Python identifier")
        if hook in hooks:
            raise ManifestError(f"hook '{hook}' is declared more than once")
        hooks[hook] = function
    if not hooks:
        raise ManifestError("at least one hook is required")
    return hooks


def _normalize_entrypoint(value: Any) -> str:
    entrypoint = _bounded_text(value, "entrypoint", maximum=160, required=True) or "plugin.py"
    normalized = entrypoint.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ManifestError("entrypoint must be a relative path")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or ".." in parts or not parts[-1].lower().endswith(".py"):
        raise ManifestError("entrypoint must stay inside the plugin folder and be a Python file")
    return "/".join(parts)


def parse_manifest(source: str, *, source_path: str | None = None) -> dict[str, Any]:
    """Parse and validate a plugin manifest without importing its code."""
    if not isinstance(source, str) or not source.strip():
        raise ManifestError("manifest is empty")
    if len(source.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ManifestError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    try:
        import yaml
    except ImportError as exc:
        raise ManifestError("PyYAML is required to read plugin.yaml") from exc
    try:
        document = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ManifestError("manifest root must be a mapping")

    schema = document.get("manifest_version", MANIFEST_SCHEMA_VERSION)
    if isinstance(schema, bool) or not isinstance(schema, int) or schema != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"unsupported manifest_version: {schema!r}")
    plugin_id = _bounded_text(document.get("id"), "id", maximum=80, required=True).lower()
    if not _PLUGIN_ID_RE.fullmatch(plugin_id):
        raise ManifestError("id must be a lowercase dotted, dashed, or underscored plugin identifier")
    name = _bounded_text(document.get("name"), "name", maximum=120, required=True)
    version = _bounded_text(document.get("version"), "version", maximum=50, required=True)
    description = _bounded_text(document.get("description"), "description", maximum=500)
    author = _bounded_text(document.get("author"), "author", maximum=120)
    license_name = _bounded_text(document.get("license"), "license", maximum=80)
    entrypoint = _normalize_entrypoint(document.get("entrypoint", "plugin.py"))
    hooks = _normalize_hooks(document.get("hooks"))

    return {
        "manifest_version": schema,
        "id": plugin_id,
        "name": name,
        "version": version,
        "description": description,
        "author": author,
        "license": license_name,
        "entrypoint": entrypoint,
        "hooks": hooks,
        "manifest_path": os.path.abspath(source_path) if source_path else "",
    }


def read_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read one bounded UTF-8 manifest and return normalized metadata."""
    manifest_path = os.path.abspath(os.fspath(path))
    try:
        if os.path.getsize(manifest_path) > MAX_MANIFEST_BYTES:
            raise ManifestError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
        with open(manifest_path, encoding="utf-8") as stream:
            source = stream.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise ManifestError(f"could not read manifest: {exc}") from exc
    return parse_manifest(source, source_path=manifest_path)


def resolve_entrypoint(manifest: dict[str, Any]) -> str:
    """Resolve a manifest entrypoint and prove it remains inside its folder."""
    manifest_path = manifest.get("manifest_path")
    if not manifest_path:
        raise ManifestError("manifest_path is required to resolve an entrypoint")
    folder = os.path.realpath(os.path.dirname(manifest_path))
    candidate = os.path.realpath(os.path.join(folder, manifest["entrypoint"]))
    try:
        inside = os.path.commonpath([folder, candidate]) == folder
    except ValueError:
        inside = False
    if not inside or not os.path.isfile(candidate):
        raise ManifestError("manifest entrypoint is missing or outside the plugin folder")
    return candidate


def find_manifests(plugin_root: str | os.PathLike[str]) -> list[str]:
    """Find one-level plugin-folder manifests deterministically."""
    root = os.path.abspath(os.fspath(plugin_root))
    if not os.path.isdir(root):
        return []
    paths = []
    try:
        entries = sorted(os.scandir(root), key=lambda entry: entry.name.lower())
    except OSError:
        return paths
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            manifest_path = os.path.join(entry.path, MANIFEST_FILENAME)
            if os.path.isfile(manifest_path):
                paths.append(manifest_path)
    return paths


def _plugin_slug(name: str) -> str:
    text = _bounded_text(name, "name", maximum=100, required=True).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not slug:
        raise ManifestError("name must contain at least one letter or number")
    return slug[:48].rstrip("-")


def _atomic_text_write(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def create_plugin_scaffold(name: str, output_dir: str | os.PathLike[str], *, force: bool = False) -> dict[str, str]:
    """Create a safe two-file plugin package and return its generated paths."""
    slug = _plugin_slug(name)
    root = Path(output_dir).expanduser().resolve()
    plugin_dir = (root / slug).resolve()
    try:
        if os.path.commonpath([str(root), str(plugin_dir)]) != str(root):
            raise ManifestError("plugin output must remain inside the selected directory")
    except ValueError as exc:
        raise ManifestError("plugin output is on an incompatible filesystem path") from exc
    if plugin_dir.exists():
        if not plugin_dir.is_dir():
            raise ManifestError(f"plugin target is not a directory: {plugin_dir}")
        existing = {path.name for path in plugin_dir.iterdir()}
        if existing and not force:
            raise ManifestError(f"plugin directory is not empty: {plugin_dir}")
    else:
        plugin_dir.mkdir(parents=True, exist_ok=False)

    plugin_id = f"plugin.{slug.replace('-', '_')}"
    manifest = (
        "manifest_version: 1\n"
        f"id: {plugin_id}\n"
        f"name: {name.strip()}\n"
        "version: 1.0.0\n"
        "description: Generated UniFile plugin scaffold.\n"
        "entrypoint: plugin.py\n"
        "hooks:\n"
        "  - classify: classify_custom\n"
    )
    source = '''"""Generated UniFile plugin scaffold.

The manifest keeps metadata separate from this entrypoint. Review and trust
the plugin from Settings -> Plugins before enabling it.
"""


def classify_custom(filepath, metadata):
    """Return (category, confidence) or None to defer to built-in rules."""
    return None
'''
    manifest_path = plugin_dir / MANIFEST_FILENAME
    entrypoint = plugin_dir / "plugin.py"
    _atomic_text_write(manifest_path, manifest)
    _atomic_text_write(entrypoint, source)
    return {
        "directory": str(plugin_dir),
        "manifest": str(manifest_path),
        "entrypoint": str(entrypoint),
        "id": plugin_id,
    }


def _normalize_index_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ManifestError("community index entries must be objects")
    plugin_id = _bounded_text(entry.get("id"), "plugin id", maximum=80, required=True).lower()
    if not _PLUGIN_ID_RE.fullmatch(plugin_id):
        raise ManifestError(f"invalid community plugin id: {plugin_id}")
    name = _bounded_text(entry.get("name"), "plugin name", maximum=120, required=True)
    version = _bounded_text(entry.get("version"), "plugin version", maximum=50, required=True)
    url = _bounded_text(entry.get("url"), "plugin url", maximum=2048, required=True)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ManifestError(f"community plugin URL must use HTTPS: {url}")
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list) or any(not isinstance(hook, str) for hook in hooks):
        raise ManifestError(f"hooks for {plugin_id} must be a string list")
    return {
        "id": plugin_id,
        "name": name,
        "version": version,
        "description": _bounded_text(entry.get("description"), "plugin description", maximum=500),
        "url": url,
        "hooks": [hook[:40] for hook in hooks[:12]],
    }


def parse_community_index(source: str) -> list[dict[str, Any]]:
    """Parse a plain JSON community index with a strict, display-only schema."""
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_INDEX_BYTES:
        raise ManifestError(f"community index exceeds {MAX_INDEX_BYTES} bytes")
    try:
        document = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid community index JSON: {exc}") from exc
    if isinstance(document, dict):
        schema = document.get("schema_version", 1)
        entries = document.get("plugins")
    else:
        schema = 1
        entries = document
    if schema != 1 or not isinstance(entries, list):
        raise ManifestError("community index must contain schema_version 1 and a plugins list")
    normalized = [_normalize_index_entry(entry) for entry in entries]
    ids = [entry["id"] for entry in normalized]
    if len(ids) != len(set(ids)):
        raise ManifestError("community index contains duplicate plugin ids")
    return normalized


def fetch_community_index(
    url: str = DEFAULT_COMMUNITY_INDEX_URL,
    *,
    timeout: float = 5.0,
    opener: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch a bounded HTTPS JSON index; never downloads or executes plugins."""
    parsed = urllib.parse.urlparse(str(url).strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ManifestError("community index URL must use HTTPS")
    if len(url) > 2048:
        raise ManifestError("community index URL is too long")
    try:
        bounded_timeout = max(0.5, min(30.0, float(timeout)))
        headers = {"User-Agent": "UniFile Plugin Index/1", "Accept": "application/json"}
        if opener is not None:
            request = urllib.request.Request(url, headers=headers)
            with opener(request, timeout=bounded_timeout) as response:
                payload = response.read(MAX_INDEX_BYTES + 1)
        else:
            payload = request_bytes(
                url,
                headers=headers,
                timeout=bounded_timeout,
                max_bytes=MAX_INDEX_BYTES,
                provider="plugin-index",
            ).content
    except Exception as exc:
        raise ManifestError(f"could not fetch community index: {exc}") from exc
    if len(payload) > MAX_INDEX_BYTES:
        raise ManifestError(f"community index exceeds {MAX_INDEX_BYTES} bytes")
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError("community index is not UTF-8") from exc
    return parse_community_index(source)
