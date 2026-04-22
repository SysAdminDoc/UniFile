"""UniFile — Plugins, profiles, category presets, cloud path resolution."""
import os, re, json, importlib.util, subprocess, sys
from pathlib import Path

from unifile.config import _APP_DATA_DIR, _PROFILES_DIR, _PRESETS_DIR

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
        path = os.path.join(_PROFILES_DIR, f"{name}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

    @staticmethod
    def load(name: str) -> dict:
        """Load a profile from disk."""
        path = os.path.join(_PROFILES_DIR, f"{name}.json")
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def delete(name: str):
        """Delete a profile."""
        path = os.path.join(_PROFILES_DIR, f"{name}.json")
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
        path = os.path.join(_PRESETS_DIR, f"{name}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(categories, f, indent=2)

    @staticmethod
    def load(name) -> list:
        path = os.path.join(_PRESETS_DIR, f"{name}.json")
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def list_presets() -> list:
        try:
            return sorted(os.path.splitext(f)[0] for f in os.listdir(_PRESETS_DIR) if f.endswith('.json'))
        except OSError:
            return []

    @staticmethod
    def delete(name):
        path = os.path.join(_PRESETS_DIR, f"{name}.json")
        if os.path.exists(path):
            os.remove(path)

    @staticmethod
    def builtin_presets() -> dict:
        return dict(CategoryPresetManager._BUILTINS)



# ── Plugin System ────────────────────────────────────────────────────────────
_PLUGINS_DIR = os.path.join(_APP_DATA_DIR, 'plugins')
os.makedirs(_PLUGINS_DIR, exist_ok=True)


class PluginManager:
    """Safe loader for UniFile plugins."""

    HOOKS = ('classify', 'rename_token', 'post_move', 'post_scan')
    _plugins = []  # list of (module, metadata_dict)

    @classmethod
    def discover(cls) -> list:
        """Scan _PLUGINS_DIR for .py files, extract metadata from docstring."""
        results = []
        if not os.path.isdir(_PLUGINS_DIR):
            return results
        for fname in sorted(os.listdir(_PLUGINS_DIR)):
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(_PLUGINS_DIR, fname)
            meta = {'file': fname, 'path': fpath, 'name': fname[:-3],
                    'hooks': [], 'description': '', 'enabled': True}
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
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
            except Exception:
                meta['description'] = f"Error parsing {fname}"
            results.append(meta)
        return results

    @classmethod
    def load_all(cls):
        """Load all discovered plugins."""
        cls._plugins.clear()
        for meta in cls.discover():
            if not meta.get('enabled', True):
                continue
            try:
                spec = importlib.util.spec_from_file_location(meta['name'], meta['path'])
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    cls._plugins.append((mod, meta))
            except Exception:
                pass

    @classmethod
    def run_classifiers(cls, filepath, metadata) -> tuple:
        """Run all enabled 'classify' hooks. First match wins. Returns (cat, conf) or None."""
        for mod, meta in cls._plugins:
            if 'classify' not in meta.get('hooks', []):
                continue
            fn = getattr(mod, 'classify', None)
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
            fn = getattr(mod, 'rename_tokens', None)
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
            fn = getattr(mod, 'post_move', None)
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
            fn = getattr(mod, 'post_scan', None)
            if fn:
                try:
                    fn(items)
                except Exception:
                    pass



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
                with open(db_info, 'r') as f:
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
        if not os.path.isdir(path):
            return False
        # Check for common placeholder patterns (OneDrive on-demand)
        try:
            for entry in os.scandir(path):
                if entry.name.endswith('.cloud') or entry.name.endswith('.placeholder'):
                    return False
                break  # Just check first few
        except OSError:
            pass
        return True


# Note: append_csv_log() used to live here as duplicate code. The canonical
# implementation is in unifile.cache — import it from there instead.

