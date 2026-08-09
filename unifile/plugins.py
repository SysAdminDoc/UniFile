"""UniFile — Plugins, profiles, category presets, cloud path resolution."""
import hashlib
import importlib.util
import json
import multiprocessing
import os
import re
import shutil
from typing import Any

from unifile.cloud_storage import iter_local_cloud_files, local_cloud_status
from unifile.config import _APP_DATA_DIR, _PRESETS_DIR, _PROFILES_DIR, load_json_safe, save_json_safe
from unifile.plugin_manifest import (
    DEFAULT_COMMUNITY_INDEX_URL,
    DEFAULT_RESOURCES,
    SUPPORTED_CAPABILITIES,
    ManifestError,
    fetch_community_index,
    find_manifests,
    read_manifest,
    resolve_entrypoint,
)

_MANIFEST_HIGH_RISK_HOOKS = frozenset(("post_move", "post_scan"))
_MANIFEST_HOOK_CAPABILITIES = {
    "classify": frozenset(("read_metadata",)),
    "rename_token": frozenset(("read_metadata",)),
    "post_move": frozenset(("file_ops",)),
    "post_scan": frozenset(("read_library",)),
    "on_scan_item": frozenset(("read_metadata",)),
    "on_apply": frozenset(("read_metadata",)),
}
_MANIFEST_SAFE_IN_PROCESS_CAPABILITIES = frozenset(("read_metadata", "read_library"))
_MANIFEST_MAX_ARGS_BYTES = 2 * 1024 * 1024


def _safe_plugin_payload(value: Any, depth: int = 0) -> Any:
    """Convert plugin arguments/results to bounded, JSON-safe process payloads."""
    if depth > 5:
        return str(value)[:1_000]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key)[:160]: _safe_plugin_payload(item, depth + 1)
            for key, item in list(value.items())[:2_000]
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_plugin_payload(item, depth + 1) for item in list(value)[:2_000]]
    fields = {}
    for name in ("name", "full_src", "category", "confidence", "size", "method", "metadata"):
        if hasattr(value, name):
            fields[name] = _safe_plugin_payload(getattr(value, name), depth + 1)
    return fields or str(value)[:1_000]


def _run_manifest_hook_process(connection, path: str, function_name: str, args: list[Any],
                               max_output_bytes: int) -> None:
    """Import and invoke one manifest hook outside the UI process."""
    try:
        spec = importlib.util.spec_from_file_location("_unifile_manifest_plugin", path)
        if not spec or not spec.loader:
            raise ImportError("could not create a plugin import specification")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, function_name, None)
        if not callable(function):
            raise AttributeError(f"plugin function {function_name!r} is not callable")
        result = _safe_plugin_payload(function(*args))
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > max_output_bytes:
            raise ValueError(f"plugin output exceeds {max_output_bytes} bytes")
        connection.send({"success": True, "result": result})
    except BaseException as exc:
        try:
            connection.send({
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _reap_manifest_process(process: multiprocessing.Process) -> None:
    """Terminate and join one manifest hook child without leaving an orphan."""
    try:
        if process.is_alive():
            process.terminate()
        process.join(2)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(2)
    except (OSError, RuntimeError):
        pass


def _execute_manifest_hook(path: str, function_name: str, args: list[Any],
                           resources: dict[str, int]) -> dict[str, Any]:
    """Run a manifest hook with a spawn boundary and a bounded response."""
    safe_args = _safe_plugin_payload(args)
    max_items = max(1, min(10_000, resources.get("max_items", DEFAULT_RESOURCES["max_items"])))
    if safe_args and isinstance(safe_args[0], list):
        safe_args[0] = safe_args[0][:max_items]
    encoded_args = json.dumps(safe_args, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded_args) > _MANIFEST_MAX_ARGS_BYTES:
        return {"success": False, "error": "plugin input exceeds the process payload limit"}
    timeout = max(0.1, min(60.0, resources.get("timeout_ms", DEFAULT_RESOURCES["timeout_ms"]) / 1000))
    max_output_bytes = max(
        1_024,
        min(4 * 1024 * 1024, resources.get("max_output_bytes", DEFAULT_RESOURCES["max_output_bytes"])),
    )
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_manifest_hook_process,
        args=(child, path, function_name, safe_args, max_output_bytes),
    )
    process.daemon = True
    try:
        process.start()
        child.close()
        if not parent.poll(timeout):
            _reap_manifest_process(process)
            return {
                "success": False,
                "timed_out": True,
                "error": f"plugin timed out after {timeout:.1f}s",
            }
        try:
            response = parent.recv()
        except (EOFError, OSError) as exc:
            return {"success": False, "error": f"plugin process failed: {exc}"}
        _reap_manifest_process(process)
        return response if isinstance(response, dict) else {
            "success": False,
            "error": "plugin process returned an invalid response",
        }
    except (OSError, RuntimeError) as exc:
        _reap_manifest_process(process)
        return {"success": False, "error": f"plugin process failed: {exc}"}
    finally:
        parent.close()
        _reap_manifest_process(process)


def _legacy_manifest_capabilities(meta: dict[str, Any]) -> list[str]:
    """Infer the narrowest useful approval set for a v1 manifest migration."""
    capabilities = set()
    raw_hooks = meta.get("hooks", [])
    hooks = set(raw_hooks.keys()) if isinstance(raw_hooks, dict) else set(raw_hooks)
    hooks |= set(meta.get("workflow_hooks", []))
    if hooks & {"classify", "rename_token", "post_scan", "on_scan_item", "on_apply"}:
        capabilities.add("read_metadata")
    if "post_scan" in hooks:
        capabilities.add("read_library")
    if "post_move" in hooks or "on_apply" in hooks:
        capabilities.add("file_ops")
    if hooks & {"on_scan_item", "on_apply"}:
        capabilities.update({"write_tags", "file_ops"})
    return sorted(capabilities)


def _manifest_contract(meta: dict[str, Any], *, effective: bool = False) -> dict[str, Any]:
    capabilities = list(meta.get("capabilities") or [])
    if effective and not capabilities and meta.get("legacy_manifest"):
        capabilities = _legacy_manifest_capabilities(meta)
    resources = dict(DEFAULT_RESOURCES)
    resources.update({
        key: int(value)
        for key, value in (meta.get("resources") or {}).items()
        if key in DEFAULT_RESOURCES and isinstance(value, int) and not isinstance(value, bool)
    })
    return {
        "capabilities": sorted(set(capabilities)),
        "resources": resources,
        "isolation": str(meta.get("isolation") or "process"),
    }


def _safe_name(name: str) -> str:
    """Sanitize a profile/preset name to prevent path traversal."""
    name = os.path.basename(name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    if not name:
        raise ValueError("Name must not be empty after sanitization")
    return name


class ProfileManager:
    """Manages saved scan configuration profiles."""

    @staticmethod
    def list_profiles() -> list:
        """Return list of profile names (without .json extension)."""
        try:
            return sorted(
                os.path.splitext(f)[0] for f in os.listdir(_PROFILES_DIR)
                if f.endswith('.json'))
        except OSError:
            return []

    @staticmethod
    def save(name: str, config: dict):
        """Save a profile to disk."""
        path = os.path.join(_PROFILES_DIR, f"{_safe_name(name)}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

    @staticmethod
    def load(name: str) -> dict:
        """Load a profile from disk."""
        path = os.path.join(_PROFILES_DIR, f"{_safe_name(name)}.json")
        with open(path, encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def delete(name: str):
        """Delete a profile."""
        path = os.path.join(_PROFILES_DIR, f"{_safe_name(name)}.json")
        if os.path.exists(path):
            os.remove(path)





class CategoryPresetManager:
    """Import/export category preset packs."""

    _BUILTINS = {
        "Developer": [
            {"name": "Code", "color": "#38bdf8", "rename_template": "", "extensions": ["py","js","ts","jsx","tsx","html","css","java","c","cpp","go","rs","rb","php"]},
            {"name": "Docs", "color": "#60a5fa", "rename_template": "", "extensions": ["md","txt","pdf","docx","rst","adoc"]},
            {"name": "Config", "color": "#fbbf24", "rename_template": "", "extensions": ["json","yaml","yml","toml","ini","cfg","env","xml"]},
            {"name": "Data", "color": "#2dd4bf", "rename_template": "", "extensions": ["csv","tsv","sql","db","sqlite","parquet","json"]},
            {"name": "Logs", "color": "#94a3b8", "rename_template": "", "extensions": ["log","out","err"]},
            {"name": "Build Artifacts", "color": "#ef4444", "rename_template": "", "extensions": ["exe","dll","so","o","class","pyc","wasm"]},
            {"name": "Dependencies", "color": "#a78bfa", "rename_template": "", "extensions": ["whl","tar.gz","gem","jar","nupkg"]},
        ],
        "Photographer": [
            {"name": "RAW", "color": "#34d399", "rename_template": "{year}-{month}-{day}_{name}", "extensions": ["cr2","cr3","nef","arw","dng","orf","rw2","raw"]},
            {"name": "JPEG", "color": "#60a5fa", "rename_template": "{year}-{month}-{day}_{name}", "extensions": ["jpg","jpeg"]},
            {"name": "Edited", "color": "#f472b6", "rename_template": "", "extensions": ["psd","psb","tiff","tif","png"]},
            {"name": "Panoramas", "color": "#fbbf24", "rename_template": "", "extensions": ["jpg","jpeg","tiff"]},
            {"name": "Timelapse", "color": "#a78bfa", "rename_template": "", "extensions": ["mp4","mov","avi"]},
            {"name": "Catalogs", "color": "#94a3b8", "rename_template": "", "extensions": ["lrcat","lrdata","catalog"]},
        ],
        "Music Producer": [
            {"name": "Stems", "color": "#34d399", "rename_template": "", "extensions": ["wav","aiff","flac"]},
            {"name": "Mixes", "color": "#60a5fa", "rename_template": "", "extensions": ["wav","mp3","flac"]},
            {"name": "Masters", "color": "#f472b6", "rename_template": "", "extensions": ["wav","flac","dsd"]},
            {"name": "Samples", "color": "#fbbf24", "rename_template": "", "extensions": ["wav","mp3","ogg","aiff"]},
            {"name": "MIDI", "color": "#a78bfa", "rename_template": "", "extensions": ["mid","midi"]},
            {"name": "DAW Projects", "color": "#ef4444", "rename_template": "", "extensions": ["als","flp","logic","ptx","rpp","cpr"]},
        ],
        "Designer": [
            {"name": "PSDs", "color": "#c084fc", "rename_template": "", "extensions": ["psd","psb"]},
            {"name": "Vectors", "color": "#34d399", "rename_template": "", "extensions": ["ai","eps","svg"]},
            {"name": "Mockups", "color": "#60a5fa", "rename_template": "", "extensions": ["xd","fig","sketch"]},
            {"name": "Fonts", "color": "#fb923c", "rename_template": "", "extensions": ["ttf","otf","woff","woff2"]},
            {"name": "Icons", "color": "#fbbf24", "rename_template": "", "extensions": ["ico","icns","svg","png"]},
            {"name": "Color Palettes", "color": "#f472b6", "rename_template": "", "extensions": ["ase","aco","gpl","clr"]},
        ],
    }

    @staticmethod
    def save(name, categories):
        path = os.path.join(_PRESETS_DIR, f"{_safe_name(name)}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(categories, f, indent=2)

    @staticmethod
    def load(name) -> list:
        path = os.path.join(_PRESETS_DIR, f"{_safe_name(name)}.json")
        with open(path, encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def list_presets() -> list:
        try:
            return sorted(os.path.splitext(f)[0] for f in os.listdir(_PRESETS_DIR) if f.endswith('.json'))
        except OSError:
            return []

    @staticmethod
    def delete(name):
        path = os.path.join(_PRESETS_DIR, f"{_safe_name(name)}.json")
        if os.path.exists(path):
            os.remove(path)

    @staticmethod
    def builtin_presets() -> dict:
        return dict(CategoryPresetManager._BUILTINS)



# ── Plugin System ────────────────────────────────────────────────────────────
_PLUGINS_DIR = os.path.join(_APP_DATA_DIR, 'plugins')
_PLUGIN_TRUST_PATH = os.path.join(_APP_DATA_DIR, 'trusted_plugins.json')
os.makedirs(_PLUGINS_DIR, exist_ok=True)


class PluginManager:
    """Safe loader for UniFile plugins."""

    HOOKS = ('classify', 'rename_token', 'post_move', 'post_scan')
    WORKFLOW_HOOKS = ('on_scan_item', 'on_apply')
    COMMUNITY_INDEX_URL = DEFAULT_COMMUNITY_INDEX_URL
    _plugins = []  # list of (module, metadata_dict)
    _load_errors = []

    @staticmethod
    def _trust_key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    @staticmethod
    def _fingerprint(path: str, related_paths: list[str] | None = None,
                     capability_data: dict[str, Any] | None = None) -> dict:
        """Fingerprint one plugin, optionally including its manifest sidecar."""
        related = [os.path.abspath(value) for value in (related_paths or [])]
        if not related:
            # Preserve the original trust record shape/hash for legacy plugins.
            st = os.stat(path)
            h = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    h.update(chunk)
            fingerprint = {
                'path': PluginManager._trust_key(path),
                'size': st.st_size,
                'mtime_ns': getattr(st, 'st_mtime_ns', int(st.st_mtime * 1_000_000_000)),
                'sha256': h.hexdigest(),
            }
            if capability_data is not None:
                PluginManager._add_capability_fingerprint(fingerprint, capability_data)
            return fingerprint
        paths = [os.path.abspath(path), *related]
        h = hashlib.sha256()
        total_size = 0
        newest_mtime = 0
        for candidate in paths:
            st = os.stat(candidate)
            total_size += st.st_size
            newest_mtime = max(
                newest_mtime,
                getattr(st, 'st_mtime_ns', int(st.st_mtime * 1_000_000_000)),
            )
            h.update(PluginManager._trust_key(candidate).encode('utf-8'))
            h.update(b'\0')
            with open(candidate, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    h.update(chunk)
            h.update(b'\0')
        fingerprint = {
            'path': PluginManager._trust_key(path),
            'size': total_size,
            'mtime_ns': newest_mtime,
            'sha256': h.hexdigest(),
        }
        if capability_data is not None:
            PluginManager._add_capability_fingerprint(fingerprint, capability_data)
        return fingerprint

    @staticmethod
    def _add_capability_fingerprint(fingerprint: dict[str, Any], capability_data: dict[str, Any]) -> None:
        contract = _manifest_contract(capability_data)
        encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fingerprint["capability_sha256"] = hashlib.sha256(encoded).hexdigest()
        fingerprint["capability_contract"] = contract

    @classmethod
    def _trust_store(cls) -> dict:
        return load_json_safe(_PLUGIN_TRUST_PATH, {}, expected_type=dict)

    @classmethod
    def is_trusted(cls, path: str, related_paths: list[str] | None = None) -> bool:
        return cls.trust_status(path, related_paths) == 'trusted'

    @classmethod
    def trust(cls, path: str, related_paths: list[str] | None = None,
              *, capability_data: dict[str, Any] | None = None) -> bool:
        """Trust a root plugin or explicitly approve a manifest package."""
        manifest_data = capability_data
        if related_paths and manifest_data is None:
            try:
                manifest_data = read_manifest(related_paths[0])
            except (ManifestError, OSError, ValueError):
                return False
        try:
            fp = cls._fingerprint(path, related_paths, manifest_data)
        except OSError:
            return False
        store = cls._trust_store()
        if manifest_data is None:
            store[fp['path']] = fp
        else:
            store[fp['path']] = {
                "fingerprint": fp,
                "approval": cls._approval_for_metadata(manifest_data),
            }
        return save_json_safe(_PLUGIN_TRUST_PATH, store)

    @classmethod
    def untrust(cls, path: str) -> bool:
        store = cls._trust_store()
        store.pop(cls._trust_key(path), None)
        return save_json_safe(_PLUGIN_TRUST_PATH, store)

    @classmethod
    def trust_status(cls, path: str, related_paths: list[str] | None = None,
                     *, capability_data: dict[str, Any] | None = None) -> str:
        key = cls._trust_key(path)
        store = cls._trust_store()
        if key not in store:
            return 'untrusted'
        manifest_data = capability_data
        if related_paths and manifest_data is None:
            try:
                manifest_data = read_manifest(related_paths[0])
            except (ManifestError, OSError, ValueError):
                return 'changed'
        try:
            expected = cls._fingerprint(path, related_paths, manifest_data)
            record = store.get(key)
            if isinstance(record, dict) and isinstance(record.get("fingerprint"), dict):
                if record["fingerprint"] != expected:
                    return 'changed'
                approval = record.get("approval") or {}
                if manifest_data and manifest_data.get("legacy_manifest") and not approval.get(
                    "migration_approved", False
                ):
                    return 'migration_required'
                return 'trusted'
            if record == expected:
                return 'trusted'
            # Old v1 manifest trust records predate capability approval. Keep
            # them visible, but require a deliberate migration approval.
            if manifest_data and manifest_data.get("legacy_manifest"):
                legacy_expected = cls._fingerprint(path, related_paths)
                if record == legacy_expected:
                    return 'migration_required'
            return 'changed'
        except OSError:
            return 'missing'

    @classmethod
    def trust_metadata(cls, meta: dict) -> bool:
        """Approve a discovered manifest and bind its declared contract."""
        path = meta.get('path', '')
        related = [meta['manifest_path']] if meta.get('manifest_path') else None
        if not path or not related:
            return cls.trust(path, related)
        try:
            fingerprint = cls._fingerprint(path, related, meta)
            approval = cls._approval_for_metadata(meta)
        except (OSError, ValueError):
            return False
        store = cls._trust_store()
        store[fingerprint['path']] = {
            "fingerprint": fingerprint,
            "approval": approval,
        }
        return save_json_safe(_PLUGIN_TRUST_PATH, store)

    @staticmethod
    def _approval_for_metadata(meta: dict[str, Any], *, approved_capabilities: list[str] | None = None,
                               approved_isolation: str | None = None) -> dict[str, Any]:
        declared = set(meta.get("capabilities") or [])
        if meta.get("legacy_manifest") and not declared:
            capabilities = _legacy_manifest_capabilities(meta)
        else:
            capabilities = sorted(declared)
        if approved_capabilities is not None:
            requested = {str(value).strip().lower() for value in approved_capabilities}
            if not requested.issubset(set(SUPPORTED_CAPABILITIES) | set(capabilities)):
                raise ValueError("approved capabilities contain an unsupported value")
            if not meta.get("legacy_manifest") and not requested.issubset(declared):
                raise ValueError("approved capabilities must be declared by the manifest")
            capabilities = sorted(requested)
        resources = _manifest_contract(meta)["resources"]
        isolation = approved_isolation or meta.get("isolation") or "process"
        if isolation not in ("in_process", "process"):
            raise ValueError("unsupported approved isolation mode")
        return {
            "capabilities": capabilities,
            "resources": resources,
            "isolation": isolation,
            "migration_approved": bool(meta.get("legacy_manifest")),
        }

    @classmethod
    def approval_summary(cls, meta: dict[str, Any]) -> dict[str, Any]:
        """Return the current/approved capability contract and a stable diff."""
        key = cls._trust_key(meta.get("path", ""))
        record = cls._trust_store().get(key)
        approval = record.get("approval", {}) if isinstance(record, dict) else {}
        current = _manifest_contract(meta, effective=True)
        approved = {
            "capabilities": sorted(set(approval.get("capabilities") or [])),
            "resources": dict(approval.get("resources") or {}),
            "isolation": approval.get("isolation", ""),
        }
        current_capabilities = set(current["capabilities"])
        approved_capabilities = set(approved["capabilities"])
        resource_diff = {
            key: {"approved": approved["resources"].get(key), "current": value}
            for key, value in current["resources"].items()
            if approved["resources"].get(key) != value
        }
        return {
            "current": current,
            "approved": approved,
            "capability_diff": {
                "added": sorted(current_capabilities - approved_capabilities),
                "removed": sorted(approved_capabilities - current_capabilities),
            },
            "resource_diff": resource_diff,
            "isolation_changed": bool(
                approved["isolation"] and approved["isolation"] != current["isolation"]
            ),
            "requires_migration": bool(
                meta.get("legacy_manifest") and not approval.get("migration_approved", False)
            ),
            "high_risk_hooks": sorted(set(meta.get("hooks", [])) & _MANIFEST_HIGH_RISK_HOOKS),
        }

    @classmethod
    def format_approval_summary(cls, summary: dict[str, Any]) -> str:
        """Render an approval diff suitable for the Qt confirmation dialog."""
        current = summary.get("current", {})
        lines = ["Review the plugin contract before enabling it:"]
        capabilities = ", ".join(current.get("capabilities", [])) or "none"
        lines.append(f"Capabilities: {capabilities}")
        resources = current.get("resources", {})
        lines.append(
            "Resources: "
            f"timeout {resources.get('timeout_ms')} ms, "
            f"output {resources.get('max_output_bytes')} bytes, "
            f"items {resources.get('max_items')}"
        )
        lines.append(f"Isolation: {current.get('isolation', 'unknown')}")
        diff = summary.get("capability_diff", {})
        if diff.get("added"):
            lines.append(f"New capabilities: {', '.join(diff['added'])}")
        if diff.get("removed"):
            lines.append(f"Removed capabilities: {', '.join(diff['removed'])}")
        if summary.get("resource_diff"):
            lines.append("Resource limits changed since the last approval.")
        if summary.get("isolation_changed"):
            lines.append("Isolation mode changed since the last approval.")
        if summary.get("requires_migration"):
            lines.append("This is a legacy v1 manifest and requires explicit migration approval.")
        if summary.get("high_risk_hooks"):
            lines.append(
                "High-risk hooks require process isolation: "
                + ", ".join(summary["high_risk_hooks"])
            )
        return "\n".join(lines)

    @classmethod
    def _hook_allowed(cls, meta: dict[str, Any], hook: str) -> bool:
        """Apply capability and isolation gates before invoking a manifest hook."""
        if meta.get("kind") != "manifest":
            return True
        required = _MANIFEST_HOOK_CAPABILITIES.get(hook, frozenset())
        approved = set(meta.get("approved_capabilities") or [])
        if not required.issubset(approved):
            return False
        if hook in _MANIFEST_HIGH_RISK_HOOKS and meta.get("isolation") != "process":
            return False
        if (
            meta.get("kind") == "manifest"
            and meta.get("isolation") == "in_process"
            and hook not in {"on_scan_item", "on_apply"}
            and not approved.issubset(_MANIFEST_SAFE_IN_PROCESS_CAPABILITIES)
        ):
            return False
        return True

    @classmethod
    def _disabled_hooks(cls, meta: dict[str, Any]) -> list[str]:
        hooks = list(meta.get("hooks", [])) + list(meta.get("workflow_hooks", []))
        return [hook for hook in hooks if not cls._hook_allowed(meta, hook)]

    @classmethod
    def _load_approval(cls, meta: dict[str, Any]) -> None:
        record = cls._trust_store().get(cls._trust_key(meta.get("path", "")))
        approval = record.get("approval", {}) if isinstance(record, dict) else {}
        meta["approved_capabilities"] = sorted(set(approval.get("capabilities") or []))
        meta["approved_resources"] = dict(approval.get("resources") or {})
        meta["approved_isolation"] = approval.get("isolation", "")
        summary = cls.approval_summary(meta)
        meta["capability_diff"] = summary["capability_diff"]
        meta["resource_diff"] = summary["resource_diff"]
        meta["isolation_changed"] = summary["isolation_changed"]

    @classmethod
    def last_load_errors(cls) -> list:
        return list(cls._load_errors)

    @classmethod
    def community_plugins(cls, url: str | None = None) -> list[dict]:
        """Fetch the display-only community catalog over HTTPS."""
        return fetch_community_index(url or cls.COMMUNITY_INDEX_URL)

    @classmethod
    def discover(cls) -> list:
        """Discover legacy root scripts and validated YAML plugin packages."""
        results = []
        if not os.path.isdir(_PLUGINS_DIR):
            return results
        for fname in sorted(os.listdir(_PLUGINS_DIR)):
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(_PLUGINS_DIR, fname)
            meta = {'file': fname, 'path': fpath, 'name': fname[:-3],
                    'hooks': [], 'description': '', 'enabled': False,
                    'trusted': False, 'trust_status': 'untrusted',
                    'load_error': '', 'workflow_hooks': [], 'kind': 'legacy',
                    'hook_functions': {}, 'manifest_path': '',
                    'capabilities': [], 'resources': dict(DEFAULT_RESOURCES),
                    'isolation': 'in_process', 'legacy_manifest': False,
                    'migration_required': False}
            try:
                with open(fpath, encoding='utf-8') as f:
                    src = f.read()
                # Parse docstring for Hook: lines
                import ast
                tree = ast.parse(src)
                docstr = ast.get_docstring(tree) or ''
                meta['description'] = docstr.split('\n')[0] if docstr else fname
                for line in docstr.split('\n'):
                    if line.strip().lower().startswith('hook:'):
                        hook = line.split(':', 1)[1].strip().lower()
                        if hook in cls.HOOKS:
                            meta['hooks'].append(hook)
                            meta['hook_functions'][hook] = (
                                'rename_tokens' if hook == 'rename_token' else hook
                            )
                    if line.strip().lower().startswith('workflow-hook:'):
                        hook = line.split(':', 1)[1].strip().lower()
                        if hook in cls.WORKFLOW_HOOKS:
                            meta['workflow_hooks'].append(hook)
                            meta['hook_functions'][hook] = hook
                if meta['workflow_hooks']:
                    meta['kind'] = 'workflow'
                status = cls.trust_status(fpath)
                meta['trust_status'] = status
                meta['trusted'] = status == 'trusted'
                meta['enabled'] = meta['trusted']
            except Exception as exc:
                meta['description'] = f"Error parsing {fname}"
                meta['trust_status'] = 'parse_error'
                meta['load_error'] = f"{type(exc).__name__}: {exc}"
            results.append(meta)

        for manifest_path in find_manifests(_PLUGINS_DIR):
            manifest_name = os.path.basename(os.path.dirname(manifest_path)) or 'plugin'
            meta = {
                'file': manifest_name,
                'path': '',
                'name': manifest_name,
                'id': '',
                'version': '',
                'hooks': [],
                'workflow_hooks': [],
                'hook_functions': {},
                'description': '',
                'enabled': False,
                'trusted': False,
                'trust_status': 'untrusted',
                'load_error': '',
                'kind': 'manifest',
                'manifest_path': os.path.abspath(manifest_path),
                'capabilities': [],
                'resources': dict(DEFAULT_RESOURCES),
                'isolation': 'process',
                'legacy_manifest': False,
                'migration_required': False,
            }
            try:
                manifest = read_manifest(manifest_path)
                entrypoint = resolve_entrypoint(manifest)
                meta.update({
                    'path': entrypoint,
                    'name': manifest['name'],
                    'id': manifest['id'],
                    'version': manifest['version'],
                    'description': manifest['description'] or manifest['name'],
                    'hook_functions': dict(manifest['hooks']),
                    'manifest_version': manifest['manifest_version'],
                    'capabilities': list(manifest['capabilities']),
                    'resources': dict(manifest['resources']),
                    'isolation': manifest['isolation'],
                    'legacy_manifest': manifest['legacy_manifest'],
                    'capability_source': manifest['capability_source'],
                })
                for hook in manifest['hooks']:
                    if hook in cls.WORKFLOW_HOOKS:
                        meta['workflow_hooks'].append(hook)
                    else:
                        meta['hooks'].append(hook)
                status = cls.trust_status(entrypoint, [manifest_path], capability_data=meta)
                meta['trust_status'] = status
                meta['trusted'] = status == 'trusted'
                meta['enabled'] = meta['trusted']
                meta['migration_required'] = bool(
                    meta.get('legacy_manifest') and status != 'trusted'
                )
                cls._load_approval(meta)
                meta['disabled_hooks'] = cls._disabled_hooks(meta)
            except (ManifestError, OSError, ValueError) as exc:
                meta['description'] = f"Error parsing {manifest_name}"
                meta['trust_status'] = 'parse_error'
                meta['load_error'] = f"{type(exc).__name__}: {exc}"
            results.append(meta)
        return results

    @classmethod
    def load_all(cls):
        """Load all discovered plugins."""
        cls._plugins.clear()
        cls._load_errors.clear()
        for meta in cls.discover():
            if not meta.get('trusted', False):
                continue
            # Workflow scripts execute in the restricted child-process runner;
            # never import them into the host just because they are trusted.
            if not meta.get('hooks'):
                continue
            if not any(cls._hook_allowed(meta, hook) for hook in meta.get('hooks', [])):
                continue
            if meta.get('kind') == 'manifest' and meta.get('isolation') == 'process':
                # Keep the entrypoint out of the host process. Each invocation
                # gets a fresh child and a timeout/reap watchdog.
                cls._plugins.append((None, meta))
                continue
            try:
                spec = importlib.util.spec_from_file_location(meta['name'], meta['path'])
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    cls._plugins.append((mod, meta))
            except Exception as exc:
                failed = dict(meta)
                failed['load_error'] = f"{type(exc).__name__}: {exc}"
                cls._load_errors.append(failed)

    @classmethod
    def _run_manifest_hook(cls, meta: dict[str, Any], hook: str, *args):
        if not cls._hook_allowed(meta, hook):
            return None
        function_name = meta.get('hook_functions', {}).get(hook, hook)
        resources = dict(meta.get('resources') or DEFAULT_RESOURCES)
        result = _execute_manifest_hook(meta['path'], function_name, list(args), resources)
        if not result.get('success'):
            return None
        return result.get('result')

    @classmethod
    def run_classifiers(cls, filepath, metadata) -> tuple:
        """Run all enabled 'classify' hooks. First match wins. Returns (cat, conf) or None."""
        for mod, meta in cls._plugins:
            if 'classify' not in meta.get('hooks', []):
                continue
            if meta.get('kind') == 'manifest' and meta.get('isolation') == 'process':
                result = cls._run_manifest_hook(meta, 'classify', filepath, metadata)
                if isinstance(result, list) and len(result) == 2:
                    return tuple(result)
                continue
            if not cls._hook_allowed(meta, 'classify'):
                continue
            fn = getattr(mod, meta.get('hook_functions', {}).get('classify', 'classify'), None)
            if fn:
                try:
                    result = fn(filepath, metadata)
                    if result and isinstance(result, tuple) and len(result) == 2:
                        return result
                except Exception:
                    pass
        return None

    @classmethod
    def get_rename_tokens(cls) -> dict:
        """Collect custom rename tokens from all plugins."""
        tokens = {}
        for mod, meta in cls._plugins:
            if 'rename_token' not in meta.get('hooks', []):
                continue
            if meta.get('kind') == 'manifest' and meta.get('isolation') == 'process':
                result = cls._run_manifest_hook(meta, 'rename_token')
                if isinstance(result, dict):
                    tokens.update(result)
                continue
            if not cls._hook_allowed(meta, 'rename_token'):
                continue
            fn = getattr(mod, meta.get('hook_functions', {}).get('rename_token', 'rename_tokens'), None)
            if fn:
                try:
                    t = fn()
                    if isinstance(t, dict):
                        tokens.update(t)
                except Exception:
                    pass
        return tokens

    @classmethod
    def run_post_move(cls, src, dst, category):
        """Run all 'post_move' hooks after a file is moved."""
        for mod, meta in cls._plugins:
            if 'post_move' not in meta.get('hooks', []):
                continue
            if meta.get('kind') == 'manifest' and meta.get('isolation') == 'process':
                cls._run_manifest_hook(meta, 'post_move', src, dst, category)
                continue
            if not cls._hook_allowed(meta, 'post_move'):
                continue
            fn = getattr(mod, meta.get('hook_functions', {}).get('post_move', 'post_move'), None)
            if fn:
                try:
                    fn(src, dst, category)
                except Exception:
                    pass

    @classmethod
    def run_post_scan(cls, items):
        """Run all 'post_scan' hooks after scan completes."""
        for mod, meta in cls._plugins:
            if 'post_scan' not in meta.get('hooks', []):
                continue
            if meta.get('kind') == 'manifest' and meta.get('isolation') == 'process':
                cls._run_manifest_hook(meta, 'post_scan', items)
                continue
            if not cls._hook_allowed(meta, 'post_scan'):
                continue
            fn = getattr(mod, meta.get('hook_functions', {}).get('post_scan', 'post_scan'), None)
            if fn:
                try:
                    fn(items)
                except Exception:
                    pass

    @classmethod
    def workflow_scripts(cls) -> list[dict]:
        """Return explicitly marked workflow scripts and trust status."""
        return [meta for meta in cls.discover() if meta.get('workflow_hooks')]

    @classmethod
    def workflow_jobs(cls, hook: str) -> list[dict]:
        """Load trusted workflow sources for a hook without importing them."""
        jobs = []
        for meta in cls.workflow_scripts():
            if (
                meta.get('trust_status') != 'trusted'
                or hook not in meta.get('workflow_hooks', [])
                or not cls._hook_allowed(meta, hook)
            ):
                continue
            try:
                with open(meta['path'], encoding='utf-8') as stream:
                    source = stream.read()
            except OSError:
                continue
            jobs.append({
                'name': meta['name'],
                'path': meta['path'],
                'source': source,
                'function': meta.get('hook_functions', {}).get(hook, hook),
                'resources': dict(meta.get('resources') or DEFAULT_RESOURCES),
                'capabilities': (
                    set(meta.get('approved_capabilities') or [])
                    if meta.get('kind') == 'manifest' else None
                ),
            })
        return jobs

    @classmethod
    def run_workflow_hook(cls, hook: str, item, *, tag_library=None,
                          classifier_values: dict | None = None,
                          tag_values: dict | None = None,
                          allow_file_ops: bool = False,
                          allowed_roots: list[str] | None = None,
                          timeout: float = 3.0,
                          log_cb=None) -> list[dict]:
        """Run trusted workflow scripts and apply their returned commands.

        The script itself never receives a host ``TagLibrary`` or filesystem
        object.  Only validated, serializable commands cross the process
        boundary; file operations stay disabled unless the caller explicitly
        opts in and supplies the allowed roots.
        """
        if hook not in cls.WORKFLOW_HOOKS:
            return []
        from unifile.script import execute_script, item_to_payload

        outcomes = []
        item_payload = (
            [item_to_payload(value) for value in item]
            if isinstance(item, list) else item_to_payload(item)
        )
        for job in cls.workflow_jobs(hook):
            try:
                declared_timeout = max(
                    0.1,
                    min(60.0, job.get('resources', {}).get('timeout_ms', timeout * 1000) / 1000),
                )
                result = execute_script(
                    job['source'],
                    hook,
                    item,
                    function_name=job.get('function', hook),
                    classifier_values=classifier_values,
                    tag_values=tag_values,
                    timeout=min(float(timeout), declared_timeout),
                )
                for message in result.logs:
                    if log_cb:
                        log_cb(f"  [SCRIPT:{job['name']}] {message}")
                applied, skipped = apply_workflow_commands(
                    result.commands,
                    tag_library=tag_library,
                    allow_file_ops=allow_file_ops,
                    allowed_roots=allowed_roots,
                    allowed_capabilities=job.get('capabilities'),
                ) if result.success else ([], [])
                outcomes.append({
                    'script': job['name'],
                    'path': job['path'],
                    'success': result.success,
                    'timed_out': result.timed_out,
                    'error': result.error,
                    'commands': result.commands,
                    'applied': applied,
                    'skipped': skipped,
                    'item': item_payload,
                })
                if log_cb and result.error:
                    log_cb(f"  [SCRIPT:{job['name']}] {result.error}")
            except (OSError, ValueError, TypeError) as exc:
                outcomes.append({
                    'script': job['name'], 'path': job['path'],
                    'success': False, 'timed_out': False,
                    'error': f"{type(exc).__name__}: {exc}",
                    'commands': [], 'applied': [], 'skipped': [],
                    'item': item_payload,
                })
                if log_cb:
                    log_cb(f"  [SCRIPT:{job['name']}] {type(exc).__name__}: {exc}")
        return outcomes


def _workflow_path_allowed(path: str, allowed_roots: list[str] | None) -> bool:
    if not allowed_roots:
        return False
    try:
        candidate = os.path.realpath(path)
        return any(
            os.path.commonpath([candidate, os.path.realpath(root)])
            == os.path.realpath(root)
            for root in allowed_roots
        )
    except (OSError, ValueError):
        return False


def apply_workflow_commands(commands: list[dict], *, tag_library=None,
                            allow_file_ops: bool = False,
                            allowed_roots: list[str] | None = None,
                            allowed_capabilities: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Apply child-process workflow commands with explicit host-side guards."""
    applied = []
    skipped = []
    for command in commands[:500]:
        if not isinstance(command, dict):
            skipped.append({'command': command, 'reason': 'invalid command'})
            continue
        operation = command.get('op')
        if operation in {'tag_add', 'tag_remove'}:
            if allowed_capabilities is not None and 'write_tags' not in allowed_capabilities:
                skipped.append({'command': command, 'reason': 'write_tags capability is not approved'})
                continue
            if tag_library is None or not getattr(tag_library, 'is_open', False):
                skipped.append({'command': command, 'reason': 'tag library is not open'})
                continue
            path = str(command.get('path', ''))
            tag_name = str(command.get('tag', '')).strip()
            if not path or not tag_name or '\x00' in path or '\x00' in tag_name:
                skipped.append({'command': command, 'reason': 'invalid tag command'})
                continue
            try:
                entry = tag_library.add_entry(path)
                tag = tag_library.get_tag_by_name(tag_name)
                if tag is None:
                    tag = tag_library.add_tag(tag_name)
                if entry is None or tag is None:
                    raise ValueError('entry or tag could not be created')
                if operation == 'tag_add':
                    ok = tag_library.add_tags_to_entry(entry.id, [tag.id])
                else:
                    ok = tag_library.remove_tags_from_entry(entry.id, [tag.id])
                if ok:
                    applied.append(command)
                else:
                    skipped.append({'command': command, 'reason': 'tag operation failed'})
            except Exception as exc:
                skipped.append({'command': command, 'reason': f'{type(exc).__name__}: {exc}'})
            continue

        if not operation or not operation.startswith('file_'):
            skipped.append({'command': command, 'reason': 'unsupported command'})
            continue
        if allowed_capabilities is not None and 'file_ops' not in allowed_capabilities:
            skipped.append({'command': command, 'reason': 'file_ops capability is not approved'})
            continue
        if not allow_file_ops:
            skipped.append({'command': command, 'reason': 'file operations are disabled'})
            continue
        source = os.path.abspath(str(command.get('source', '')))
        destination = os.path.abspath(str(command.get('destination', '')))
        if not _workflow_path_allowed(source, allowed_roots):
            skipped.append({'command': command, 'reason': 'source is outside allowed roots'})
            continue
        if operation == 'file_rename':
            new_name = str(command.get('destination', ''))
            if os.path.basename(new_name) != new_name:
                skipped.append({'command': command, 'reason': 'rename must use a file name'})
                continue
            destination = os.path.join(os.path.dirname(source), new_name)
        if not _workflow_path_allowed(destination, allowed_roots):
            skipped.append({'command': command, 'reason': 'destination is outside allowed roots'})
            continue
        if not os.path.isfile(source) or os.path.exists(destination):
            skipped.append({'command': command, 'reason': 'source missing or destination exists'})
            continue
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            if operation == 'file_move' or operation == 'file_rename':
                shutil.move(source, destination)
            elif operation == 'file_copy':
                shutil.copy2(source, destination)
            else:
                skipped.append({'command': command, 'reason': 'unsupported file operation'})
                continue
            applied.append(command)
        except (OSError, shutil.Error) as exc:
            skipped.append({'command': command, 'reason': f'{type(exc).__name__}: {exc}'})
    return applied, skipped



# ── Cloud Path Resolver ──────────────────────────────────────────────────────

class CloudPathResolver:
    """Detects cloud storage folders and handles UNC paths."""

    @staticmethod
    def detect_cloud_folders() -> list:
        """Scan common locations for cloud sync folders."""
        folders = []
        # OneDrive
        od = os.environ.get('OneDrive') or os.environ.get('OneDriveConsumer')
        if od and os.path.isdir(od):
            folders.append({'name': 'OneDrive', 'path': od, 'icon': 'cloud'})
        # Google Drive
        for gd_path in [os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'DriveFS'),
                        os.path.expanduser('~/Google Drive'),
                        os.path.expanduser('~/My Drive')]:
            if os.path.isdir(gd_path):
                folders.append({'name': 'Google Drive', 'path': gd_path, 'icon': 'cloud'})
                break
        # Dropbox
        db_info = os.path.join(os.environ.get('APPDATA', ''), 'Dropbox', 'info.json')
        if os.path.isfile(db_info):
            try:
                with open(db_info) as f:
                    info = json.load(f)
                db_path = info.get('personal', {}).get('path', '')
                if db_path and os.path.isdir(db_path):
                    folders.append({'name': 'Dropbox', 'path': db_path, 'icon': 'cloud'})
            except Exception:
                pass
        # iCloud
        ic = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'iCloudDrive')
        if os.path.isdir(ic):
            folders.append({'name': 'iCloud', 'path': ic, 'icon': 'cloud'})
        for folder in folders:
            folder['sync_status'] = local_cloud_status(folder['path'])
        return folders

    @staticmethod
    def is_unc(path: str) -> bool:
        return path.startswith('\\\\') or path.startswith('//')

    @staticmethod
    def normalize_path(path: str) -> str:
        return os.path.normpath(path)

    @staticmethod
    def is_sync_safe(path: str) -> bool:
        """Check if a cloud folder is fully synced (heuristic)."""
        return local_cloud_status(path)['state'] in {'online', 'read-only'}

    @staticmethod
    def sync_status(path: str) -> dict:
        """Return non-hydrating local sync status and placeholder coverage."""
        return local_cloud_status(path)

    @staticmethod
    def iter_files(path: str, *, include_placeholders: bool = False):
        """Yield local cloud files, skipping on-demand placeholders by default."""
        return iter_local_cloud_files(path, include_placeholders=include_placeholders)


# Note: append_csv_log() used to live here as duplicate code. The canonical
# implementation is in unifile.cache — import it from there instead.
