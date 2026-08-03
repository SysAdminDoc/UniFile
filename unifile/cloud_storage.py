"""Optional cloud-storage adapters for review-first library scans.

The rclone integration deliberately shells out to a user-installed rclone
binary instead of bundling credentials or a second cloud SDK.  Listing is
read-only.  Downloads are filtered and written below an explicit local
directory; sidecar upload is a separate explicit operation.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

CLOUD_CONFIG_VERSION = 1
CLOUD_REMOTES_FILE = os.path.join(_APP_DATA_DIR, "cloud_remotes.json")
SCAN_MODES = ("list-only", "download", "sync-back")
_REMOTE_NAME_RE = re.compile(r"^[^\x00:/\\]+$")
_EXTENSION_RE = re.compile(r"^[a-z0-9][a-z0-9+_-]*$")
_PLACEHOLDER_SUFFIXES = (".cloud", ".placeholder", ".online")
_FILE_ATTRIBUTE_OFFLINE = 0x00001000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000


class RcloneError(RuntimeError):
    """Raised when rclone is unavailable or returns a failed command."""


@dataclass(frozen=True)
class RemoteFile:
    """A read-only file record returned by an rclone listing."""

    path: str
    size: int = 0
    modified: datetime | None = None
    checksum: str = ""

    def __post_init__(self):
        object.__setattr__(self, "path", _safe_remote_path(self.path))
        object.__setattr__(self, "size", max(0, int(self.size)))


@dataclass(frozen=True)
class CloudRemoteConfig:
    """Persisted, credential-free configuration for one rclone remote."""

    name: str
    remote_name: str
    remote_path: str = ""
    scan_mode: str = "list-only"
    download_dir: str = ""
    max_size_mb: int = 0
    extensions: tuple[str, ...] = field(default_factory=tuple)
    sync_back: bool = False

    def __post_init__(self):
        name = self.name.strip()
        if not name:
            raise ValueError("Cloud remote name must not be empty")
        if not _REMOTE_NAME_RE.fullmatch(self.remote_name.strip()):
            raise ValueError("Invalid rclone remote name")
        if self.scan_mode not in SCAN_MODES:
            raise ValueError(f"scan_mode must be one of: {', '.join(SCAN_MODES)}")
        max_size = int(self.max_size_mb)
        if max_size < 0:
            raise ValueError("max_size_mb must be zero or greater")
        extensions = _normalize_extensions(self.extensions)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "remote_name", self.remote_name.strip())
        object.__setattr__(self, "remote_path", _normalize_remote_base(self.remote_path))
        object.__setattr__(self, "download_dir", self.download_dir.strip())
        if self.scan_mode != "list-only" and not self.download_dir.strip():
            raise ValueError("download_dir is required for download and sync-back modes")
        object.__setattr__(self, "max_size_mb", max_size)
        object.__setattr__(self, "extensions", extensions)
        object.__setattr__(self, "sync_back", bool(self.sync_back))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CloudRemoteConfig:
        return cls(
            name=str(raw.get("name", "")),
            remote_name=str(raw.get("remote_name", "")),
            remote_path=str(raw.get("remote_path", "")),
            scan_mode=str(raw.get("scan_mode", "list-only")),
            download_dir=str(raw.get("download_dir", "")),
            max_size_mb=int(raw.get("max_size_mb", 0) or 0),
            extensions=tuple(raw.get("extensions", ()) or ()),
            sync_back=bool(raw.get("sync_back", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "remote_name": self.remote_name,
            "remote_path": self.remote_path,
            "scan_mode": self.scan_mode,
            "download_dir": self.download_dir,
            "max_size_mb": self.max_size_mb,
            "extensions": list(self.extensions),
            "sync_back": self.sync_back,
        }


def _safe_remote_path(value: str) -> str:
    """Normalize a remote-relative object path and reject traversal."""
    raw = str(value or "").replace("\\", "/")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError("Remote paths must not be absolute or contain '..'")
    parts = [part for part in pure.parts if part not in ("", ".")]
    return "/".join(parts)


def _normalize_remote_base(value: str) -> str:
    return _safe_remote_path(value)


def _normalize_extensions(values: Any) -> tuple[str, ...]:
    if isinstance(values, str):
        values = values.split(",")
    normalized = []
    for value in values or ():
        extension = str(value).strip().lower().lstrip("*.")
        if extension and _EXTENSION_RE.fullmatch(extension):
            normalized.append(extension)
    return tuple(dict.fromkeys(normalized))


def load_cloud_remotes(path: str = CLOUD_REMOTES_FILE) -> list[CloudRemoteConfig]:
    """Load valid remote definitions, ignoring malformed entries safely."""
    payload = load_json_safe(path, {}, expected_type=dict)
    raw_remotes = payload.get("remotes", [])
    if not isinstance(raw_remotes, list):
        return []
    result = []
    seen_names = set()
    for raw in raw_remotes:
        if not isinstance(raw, dict):
            continue
        try:
            remote = CloudRemoteConfig.from_dict(raw)
        except (TypeError, ValueError):
            continue
        key = remote.name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        result.append(remote)
    return result


def save_cloud_remotes(remotes: list[CloudRemoteConfig], path: str = CLOUD_REMOTES_FILE) -> bool:
    """Atomically save credential-free cloud configuration."""
    unique = []
    seen_names = set()
    for remote in remotes:
        if not isinstance(remote, CloudRemoteConfig):
            continue
        key = remote.name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        unique.append(remote.to_dict())
    return save_json_safe(path, {"version": CLOUD_CONFIG_VERSION, "remotes": unique})


def _parse_modtime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _default_runner(args: list[str], timeout: float):
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )


class RcloneAdapter:
    """Small, testable wrapper around rclone's machine-readable commands."""

    def __init__(
        self,
        remote_name: str,
        remote_path: str = "",
        *,
        executable: str | None = None,
        runner: Callable[[list[str]], Any] | None = None,
        timeout: float = 60,
    ):
        if not _REMOTE_NAME_RE.fullmatch(str(remote_name).strip()):
            raise ValueError("Invalid rclone remote name")
        self.remote_name = str(remote_name).strip()
        self.remote_path = _normalize_remote_base(remote_path)
        self.executable = executable or shutil.which("rclone") or "rclone"
        self._runner = runner
        self.timeout = timeout

    def _run(self, command: str, *arguments: str):
        args = [self.executable, command, *arguments]
        try:
            result = (
                self._runner(args)
                if self._runner is not None
                else _default_runner(args, self.timeout)
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RcloneError(str(exc)) from exc
        if getattr(result, "returncode", 1) != 0:
            message = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
            raise RcloneError(message or f"rclone {command} failed")
        return result

    def remote_spec(self, relative_path: str = "") -> str:
        relative = _safe_remote_path(relative_path)
        combined = "/".join(part for part in (self.remote_path, relative) if part)
        return f"{self.remote_name}:{combined}"

    def list_files(
        self,
        *,
        extensions: tuple[str, ...] | list[str] = (),
        max_size_bytes: int = 0,
        limit: int | None = None,
    ) -> list[RemoteFile]:
        """Return filtered remote files without downloading or mutating them."""
        result = self._run(
            "lsjson",
            self.remote_spec(),
            "--recursive",
            "--files-only",
            "--no-mimetype",
        )
        try:
            payload = json.loads(getattr(result, "stdout", "") or "[]")
        except json.JSONDecodeError as exc:
            raise RcloneError("rclone returned invalid JSON") from exc
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            raise RcloneError("rclone JSON listing was not an array")

        allowed = set(_normalize_extensions(extensions))
        maximum = max(0, int(max_size_bytes or 0))
        files = []
        for item in payload:
            if not isinstance(item, dict) or item.get("IsDir"):
                continue
            try:
                remote_file = RemoteFile(
                    path=str(item.get("Path") or item.get("Name") or ""),
                    size=item.get("Size", 0) or 0,
                    modified=_parse_modtime(item.get("ModTime")),
                    checksum=_pick_checksum(item.get("Hashes")),
                )
            except (TypeError, ValueError):
                continue
            if allowed and remote_file.path.rsplit("/", 1)[-1].lower().rsplit(".", 1)[-1] not in allowed:
                continue
            if maximum and remote_file.size > maximum:
                continue
            files.append(remote_file)
        files.sort(key=lambda item: item.path.casefold())
        return files[:limit] if limit is not None and limit >= 0 else files

    def download_files(
        self,
        files: list[RemoteFile],
        destination: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Download selected files below *destination*, never outside it."""
        root = Path(destination).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        failed = 0
        errors = []
        for remote_file in files:
            try:
                local_path = _safe_local_destination(root, remote_file.path)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                args = [self.remote_spec(remote_file.path), str(local_path)]
                if not overwrite:
                    args.append("--ignore-existing")
                self._run("copyto", *args)
                downloaded += 1
            except (OSError, ValueError, RcloneError) as exc:
                failed += 1
                errors.append({"path": remote_file.path, "error": str(exc)})
        return {"downloaded": downloaded, "failed": failed, "errors": errors, "destination": str(root)}

    def sync_sidecars(
        self,
        files: list[RemoteFile],
        local_root: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Upload only existing ``<file>.xmp`` sidecars for selected files."""
        root = Path(local_root).expanduser().resolve()
        uploaded = 0
        skipped = 0
        failed = 0
        errors = []
        for remote_file in files:
            try:
                local_file = _safe_local_destination(root, remote_file.path)
                sidecar = Path(str(local_file) + ".xmp")
                if not sidecar.is_file():
                    skipped += 1
                    continue
                remote_sidecar = self.remote_spec(remote_file.path + ".xmp")
                args = [str(sidecar), remote_sidecar]
                if not overwrite:
                    args.append("--ignore-existing")
                self._run("copyto", *args)
                uploaded += 1
            except (OSError, ValueError, RcloneError) as exc:
                failed += 1
                errors.append({"path": remote_file.path, "error": str(exc)})
        return {"uploaded": uploaded, "skipped": skipped, "failed": failed, "errors": errors}


def _pick_checksum(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("SHA-256", "SHA-1", "MD5"):
        if value.get(key):
            return str(value[key])
    return next((str(item) for item in value.values() if item), "")


def _safe_local_destination(root: Path, remote_path: str) -> Path:
    pure = PurePosixPath(_safe_remote_path(remote_path))
    destination = (root / Path(*pure.parts)).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError("Remote file would escape the download directory") from exc
    return destination


def list_configured_rclone_remotes(
    *,
    executable: str | None = None,
    runner: Callable[[list[str]], Any] | None = None,
    timeout: float = 20,
) -> list[str]:
    """Return rclone remote names without reading or storing credentials."""
    exe = executable or shutil.which("rclone") or "rclone"
    try:
        result = runner([exe, "listremotes"]) if runner else _default_runner([exe, "listremotes"], timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RcloneError(str(exc)) from exc
    if getattr(result, "returncode", 1) != 0:
        message = (getattr(result, "stderr", "") or "").strip()
        raise RcloneError(message or "rclone listremotes failed")
    return [line.strip().rstrip(":") for line in (getattr(result, "stdout", "") or "").splitlines() if line.strip()]


def is_placeholder_file(path: str | os.PathLike[str]) -> bool:
    """Detect common cloud placeholders without opening or hydrating a file."""
    candidate = Path(path)
    if candidate.name.lower().endswith(_PLACEHOLDER_SUFFIXES):
        return True
    if os.name != "nt":
        return False
    try:
        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(candidate))
    except (AttributeError, OSError):
        return False
    if attributes == 0xFFFFFFFF:
        return False
    return bool(attributes & (_FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_OPEN))


def local_cloud_status(path: str | os.PathLike[str], sample_limit: int = 256) -> dict[str, Any]:
    """Return a non-hydrating status summary for a local sync folder."""
    root = Path(path)
    if not root.is_dir():
        return {
            "state": "offline",
            "online": False,
            "read_only": False,
            "placeholder_count": 0,
            "sampled_files": 0,
        }
    placeholders = 0
    sampled = 0
    pending = [root]
    visited_dirs = 0
    try:
        while pending and sampled < max(1, sample_limit) and visited_dirs < 64:
            current = pending.pop(0)
            visited_dirs += 1
            with os.scandir(current) as entries:
                for entry in entries:
                    candidate = Path(entry.path)
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not is_placeholder_file(candidate) and len(pending) < 64:
                                pending.append(candidate)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    sampled += 1
                    if is_placeholder_file(candidate):
                        placeholders += 1
                    if sampled >= max(1, sample_limit):
                        break
    except OSError:
        pass
    read_only = not os.access(root, os.W_OK)
    if placeholders:
        state = "partial"
    elif read_only:
        state = "read-only"
    else:
        state = "online"
    return {
        "state": state,
        "online": True,
        "read_only": read_only,
        "placeholder_count": placeholders,
        "sampled_files": sampled,
    }


def iter_local_cloud_files(
    path: str | os.PathLike[str],
    *,
    include_placeholders: bool = False,
):
    """Yield local files while skipping cloud placeholders by default."""
    root = Path(path)
    if not root.is_dir():
        return
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [
            name for name in dirs
            if include_placeholders or not is_placeholder_file(Path(current_root) / name)
        ]
        for name in files:
            candidate = Path(current_root) / name
            if include_placeholders or not is_placeholder_file(candidate):
                yield candidate
