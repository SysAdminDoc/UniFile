"""Persistent SHA-256 file-integrity monitoring for UniFile libraries."""

from __future__ import annotations

import csv
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from unifile.config import load_json_safe, save_json_safe

FILE_HEALTH_SCHEMA_VERSION = 1
FILE_HEALTH_FILENAME = "file_health.json"
MAX_RUN_LOGS = 200
MAX_DIFF_ITEMS = 2_000
HASH_CHUNK_SIZE = 1024 * 1024


class FileHealthError(RuntimeError):
    """Raised when an integrity ledger cannot be read or written."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_file(path: str | os.PathLike[str], *, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Hash a file in bounded chunks so large media never loads into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(max(4_096, int(chunk_size)))
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _default_state() -> dict[str, Any]:
    return {
        "version": FILE_HEALTH_SCHEMA_VERSION,
        "files": {},
        "expected_changes": {},
        "runs": [],
    }


def _scope_prefix(root: Path, scope: Path) -> str:
    if scope == root:
        return ""
    return f"{scope.relative_to(root).as_posix().rstrip('/')}/"


class FileHealthMonitor:
    """Maintain and verify a SHA-256 ledger beneath a library root.

    The ledger records relative paths, never depends on absolute paths for
    identity, and excludes UniFile's own metadata directory from hashing.
    ``expect_change`` lets an intentional edit be acknowledged before the
    next verification; all other digest changes remain visible as alerts.
    """

    def __init__(self, library_root: str | os.PathLike[str]):
        root = Path(library_root).expanduser().resolve()
        if root.is_file():
            root = root.parent
        if not root.exists() or not root.is_dir():
            raise FileHealthError(f"health root is not a directory: {root}")
        self.library_root = root
        self.state_path = root / ".unifile" / FILE_HEALTH_FILENAME

    def _load(self) -> dict[str, Any]:
        state = load_json_safe(str(self.state_path), _default_state(), expected_type=dict)
        if not isinstance(state, dict):
            state = _default_state()
        if not isinstance(state.get("files"), dict):
            state["files"] = {}
        if not isinstance(state.get("expected_changes"), dict):
            state["expected_changes"] = {}
        if not isinstance(state.get("runs"), list):
            state["runs"] = []
        state.setdefault("version", FILE_HEALTH_SCHEMA_VERSION)
        return state

    def _save(self, state: dict[str, Any]) -> None:
        if not save_json_safe(str(self.state_path), state):
            raise FileHealthError(f"could not save health ledger: {self.state_path}")

    def _relative(self, path: str | os.PathLike[str]) -> str:
        candidate = Path(path).expanduser().resolve(strict=False)
        try:
            relative = candidate.relative_to(self.library_root)
        except ValueError as exc:
            raise FileHealthError("path is outside the health root") from exc
        return relative.as_posix() or "."

    def _scope(self, path: str | os.PathLike[str] | None) -> Path:
        if path is None or str(path).strip() == "":
            return self.library_root
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.library_root / candidate
        candidate = candidate.resolve(strict=False)
        try:
            candidate.relative_to(self.library_root)
        except ValueError as exc:
            raise FileHealthError("verification path is outside the health root") from exc
        if not candidate.exists():
            raise FileHealthError(f"verification path does not exist: {candidate}")
        if not candidate.is_dir() and not candidate.is_file():
            raise FileHealthError(f"verification path is not a file or directory: {candidate}")
        return candidate

    def _iter_files(self, scope: Path):
        if scope.is_file():
            if not scope.is_symlink() and scope.name not in {FILE_HEALTH_FILENAME}:
                yield scope
            return
        for root, dirs, files in os.walk(scope, topdown=True, followlinks=False):
            dirs[:] = [
                name for name in dirs
                if name != ".unifile"
                and not name.startswith((".", "$"))
                and not (Path(root) / name).is_symlink()
            ]
            for name in sorted(files, key=str.casefold):
                if name.startswith((".", "$")):
                    continue
                candidate = Path(root) / name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                yield candidate

    @staticmethod
    def _diff(path: str, change: str, old: dict | None, new: dict | None) -> dict[str, Any]:
        return {
            "path": path,
            "change": change,
            "expected_sha256": str((old or {}).get("sha256", "")),
            "actual_sha256": str((new or {}).get("sha256", "")),
            "expected_size": (old or {}).get("size"),
            "actual_size": (new or {}).get("size"),
            "expected_mtime_ns": (old or {}).get("mtime_ns"),
            "actual_mtime_ns": (new or {}).get("mtime_ns"),
        }

    def expect_change(self, path: str | os.PathLike[str], reason: str = "") -> dict[str, Any]:
        """Mark the next digest change as intentional and consume it on verify."""
        relative = self._relative(path)
        if relative == ".":
            raise FileHealthError("expected changes must target a file")
        state = self._load()
        expected = {
            "requested_at": utc_now(),
            "reason": str(reason or "")[:500],
        }
        state["expected_changes"][relative] = expected
        self._save(state)
        return {"path": relative, **expected}

    def latest_report(self) -> dict[str, Any]:
        state = self._load()
        runs = [run for run in state.get("runs", []) if isinstance(run, dict)]
        if not runs:
            return {
                "status": "not-verified",
                "library_root": str(self.library_root),
                "files_verified": 0,
                "unchanged": 0,
                "baselined": 0,
                "changed_unexpectedly": 0,
                "expected_changes": 0,
                "missing": 0,
                "errors": 0,
                "diff": [],
            }
        return dict(runs[-1])

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(MAX_RUN_LOGS, int(limit)))
        state = self._load()
        runs = [run for run in state.get("runs", []) if isinstance(run, dict)]
        return list(reversed(runs[-bounded:]))

    def verify(self, path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
        """Hash a scope and compare it to the previous ledger snapshot."""
        scope = self._scope(path)
        state = self._load()
        previous = {
            str(key): dict(value)
            for key, value in state["files"].items()
            if isinstance(value, dict)
        }
        expected_changes = dict(state.get("expected_changes", {}))
        now = utc_now()
        run: dict[str, Any] = {
            "timestamp": now,
            "library_root": str(self.library_root),
            "scope": str(scope),
            "files_verified": 0,
            "unchanged": 0,
            "baselined": 0,
            "changed_unexpectedly": 0,
            "expected_changes": 0,
            "missing": 0,
            "errors": 0,
            "diff": [],
            "error_details": [],
        }
        seen: set[str] = set()
        for candidate in self._iter_files(scope):
            try:
                relative = self._relative(candidate)
                before = candidate.stat()
                digest = sha256_file(candidate)
                after = candidate.stat()
                if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                    status = "unstable"
                    run["errors"] += 1
                    run["error_details"].append({"path": relative, "error": "file changed while hashing"})
                else:
                    status = "verified"
                old = previous.get(relative)
                record = {
                    "path": relative,
                    "sha256": digest,
                    "size": after.st_size,
                    "mtime_ns": after.st_mtime_ns,
                    "first_seen": str((old or {}).get("first_seen") or now),
                    "last_verified": now,
                    "status": status,
                    "change_count": int((old or {}).get("change_count", 0) or 0),
                }
                if old and old.get("sha256") != digest:
                    record["previous_sha256"] = str(old.get("sha256", ""))
                    if relative in expected_changes:
                        status = "expected_change"
                        run["expected_changes"] += 1
                        expected_changes.pop(relative, None)
                    else:
                        status = "changed"
                        run["changed_unexpectedly"] += 1
                    record["status"] = status
                    record["change_count"] += 1
                    if len(run["diff"]) < MAX_DIFF_ITEMS:
                        run["diff"].append(self._diff(relative, status, old, record))
                elif old:
                    run["unchanged"] += 1
                else:
                    run["baselined"] += 1
                state["files"][relative] = record
                seen.add(relative)
                run["files_verified"] += 1
            except (OSError, ValueError, FileHealthError) as exc:
                run["errors"] += 1
                run["error_details"].append({"path": str(candidate), "error": str(exc)[:500]})

        file_scope = self._relative(scope) if scope.is_file() else ""
        prefix = _scope_prefix(self.library_root, scope) if scope.is_dir() else ""
        for relative, old in previous.items():
            in_scope = relative == file_scope if file_scope else relative.startswith(prefix)
            if not in_scope or relative in seen:
                continue
            record = dict(old)
            record["status"] = "missing"
            record["last_verified"] = now
            state["files"][relative] = record
            run["missing"] += 1
            if len(run["diff"]) < MAX_DIFF_ITEMS:
                run["diff"].append(self._diff(relative, "missing", old, None))

        state["expected_changes"] = expected_changes
        run["status"] = "alert" if (
            run["changed_unexpectedly"] or run["missing"] or run["errors"]
        ) else "ok"
        state["runs"] = [
            run for run in state.get("runs", []) if isinstance(run, dict)
        ][-MAX_RUN_LOGS + 1:]
        state["runs"].append(run)
        self._save(state)
        return dict(run)


def export_health_log(report: dict[str, Any], output: str | os.PathLike[str], *, fmt: str = "") -> str:
    """Export a verification report as JSON, CSV, or plain text."""
    target = Path(output).expanduser()
    selected = str(fmt or target.suffix.lstrip(".") or "json").lower()
    if selected not in {"json", "csv", "txt", "text"}:
        raise FileHealthError("health log format must be json, csv, or text")
    if selected == "json":
        if not save_json_safe(str(target), report):
            raise FileHealthError(f"could not export health log: {target}")
    elif selected == "csv":
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", newline="", encoding="utf-8") as stream:
                fields = [
                    "path", "change", "expected_sha256", "actual_sha256",
                    "expected_size", "actual_size", "expected_mtime_ns", "actual_mtime_ns",
                ]
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(report.get("diff", []))
        except OSError as exc:
            raise FileHealthError(f"could not export health log: {target}") from exc
    else:
        lines = [
            f"UniFile file health verification — {report.get('timestamp', '')}",
            f"Scope: {report.get('scope', report.get('library_root', ''))}",
            f"Files verified: {report.get('files_verified', 0)}",
            f"Unchanged: {report.get('unchanged', 0)}",
            f"Baselined: {report.get('baselined', 0)}",
            f"Changed unexpectedly: {report.get('changed_unexpectedly', 0)}",
            f"Expected changes: {report.get('expected_changes', 0)}",
            f"Missing: {report.get('missing', 0)}",
            f"Errors: {report.get('errors', 0)}",
            "",
            "Diff:",
        ]
        lines.extend(
            f"{item.get('change', '')}\t{item.get('path', '')}\t"
            f"{item.get('expected_sha256', '')}\t{item.get('actual_sha256', '')}"
            for item in report.get("diff", [])
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            raise FileHealthError(f"could not export health log: {target}") from exc
    return str(target)


__all__ = [
    "FILE_HEALTH_FILENAME",
    "FILE_HEALTH_SCHEMA_VERSION",
    "FileHealthError",
    "FileHealthMonitor",
    "export_health_log",
    "sha256_file",
]
