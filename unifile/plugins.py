"""UniFile — Plugins, profiles, category presets, cloud path resolution."""
import hashlib
import importlib.util
import json
import os
import re
import shutil

from unifile.cloud_storage import iter_local_cloud_files, local_cloud_status
from unifile.config import _APP_DATA_DIR, _PRESETS_DIR, _PROFILES_DIR, load_json_safe, save_json_safe
from unifile.plugin_manifest import (
    DEFAULT_COMMUNITY_INDEX_URL,
    ManifestError,
    fetch_community_index,
    find_manifests,
    read_manifest,
    resolve_entrypoint,
)


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
    def _fingerprint(path: str, related_paths: list[str] | None = None) -> dict:
        """Fingerprint one plugin, optionally including its manifest sidecar."""
        related = [os.path.abspath(value) for value in (related_paths or [])]
        if not related:
            # Preserve the original trust record shape/hash for legacy plugins.
            st = os.stat(path)
            h = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    h.update(chunk)
            return {
                'path': PluginManager._trust_key(path),
                'size': st.st_size,
                'mtime_ns': getattr(st, 'st_mtime_ns', int(st.st_mtime * 1_000_000_000)),
                'sha256': h.hexdigest(),
            }
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
        return {
            'path': PluginManager._trust_key(path),
            'size': total_size,
            'mtime_ns': newest_mtime,
            'sha256': h.hexdigest(),
        }

    @classmethod
    def _trust_store(cls) -> dict:
        return load_json_safe(_PLUGIN_TRUST_PATH, {}, expected_type=dict)

    @classmethod
    def is_trusted(cls, path: str, related_paths: list[str] | None = None) -> bool:
        key = cls._trust_key(path)
        entry = cls._trust_store().get(key)
        if not isinstance(entry, dict):
            return False
        try:
            return entry == cls._fingerprint(path, related_paths)
        except OSError:
            return False

    @classmethod
    def trust(cls, path: str, related_paths: list[str] | None = None) -> bool:
        try:
            fp = cls._fingerprint(path, related_paths)
        except OSError:
            return False
        store = cls._trust_store()
        store[fp['path']] = fp
        return save_json_safe(_PLUGIN_TRUST_PATH, store)

    @classmethod
    def untrust(cls, path: str) -> bool:
        store = cls._trust_store()
        store.pop(cls._trust_key(path), None)
        return save_json_safe(_PLUGIN_TRUST_PATH, store)

    @classmethod
    def trust_status(cls, path: str, related_paths: list[str] | None = None) -> str:
        key = cls._trust_key(path)
        store = cls._trust_store()
        if key not in store:
            return 'untrusted'
        try:
            return 'trusted' if store.get(key) == cls._fingerprint(path, related_paths) else 'changed'
        except OSError:
            return 'missing'

    @classmethod
    def trust_metadata(cls, meta: dict) -> bool:
        """Trust a discovered plugin and bind its manifest to the fingerprint."""
        related = [meta['manifest_path']] if meta.get('manifest_path') else None
        return cls.trust(meta.get('path', ''), related)

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
                    'hook_functions': {}, 'manifest_path': ''}
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
                })
                for hook in manifest['hooks']:
                    if hook in cls.WORKFLOW_HOOKS:
                        meta['workflow_hooks'].append(hook)
                    else:
                        meta['hooks'].append(hook)
                status = cls.trust_status(entrypoint, [manifest_path])
                meta['trust_status'] = status
                meta['trusted'] = status == 'trusted'
                meta['enabled'] = meta['trusted']
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
    def run_classifiers(cls, filepath, metadata) -> tuple:
        """Run all enabled 'classify' hooks. First match wins. Returns (cat, conf) or None."""
        for mod, meta in cls._plugins:
            if 'classify' not in meta.get('hooks', []):
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
            if meta.get('trust_status') != 'trusted' or hook not in meta.get('workflow_hooks', []):
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
                result = execute_script(
                    job['source'],
                    hook,
                    item,
                    function_name=job.get('function', hook),
                    classifier_values=classifier_values,
                    tag_values=tag_values,
                    timeout=timeout,
                )
                for message in result.logs:
                    if log_cb:
                        log_cb(f"  [SCRIPT:{job['name']}] {message}")
                applied, skipped = apply_workflow_commands(
                    result.commands,
                    tag_library=tag_library,
                    allow_file_ops=allow_file_ops,
                    allowed_roots=allowed_roots,
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
                            allowed_roots: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Apply child-process workflow commands with explicit host-side guards."""
    applied = []
    skipped = []
    for command in commands[:500]:
        if not isinstance(command, dict):
            skipped.append({'command': command, 'reason': 'invalid command'})
            continue
        operation = command.get('op')
        if operation in {'tag_add', 'tag_remove'}:
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
