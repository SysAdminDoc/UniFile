"""Qt-free polling watch daemon for settled file arrivals."""
from __future__ import annotations

import os
import shutil
import signal
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from unifile.cli_scan import (
    DEFAULT_MIN_CONFIDENCE,
    _build_ext_map,
    _collision_safe_path,
    _destination_for_category,
    _effective_categories,
    _effective_rules,
    _inside,
    _walk_files,
    plan_file_action,
)
from unifile.config import is_protected

WATCH_SCHEMA_VERSION = "1"
DEFAULT_SETTLE_SECONDS = 0.5
DEFAULT_POLL_SECONDS = 0.25


def _signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


class WatchDaemon:
    """Poll a directory, settle arrivals, and classify each file once.

    Existing files are treated as the initial baseline unless
    ``include_existing`` is enabled. A file must keep the same size and mtime
    for ``settle_seconds`` before it is classified, which prevents a partially
    copied download from being moved. The daemon owns no GUI state and can be
    stopped safely with ``SIGINT`` or ``SIGTERM``.
    """

    def __init__(
        self,
        source: str | os.PathLike[str],
        *,
        destination: str | os.PathLike[str] | None = None,
        apply_rules: bool = False,
        settle_seconds: float = DEFAULT_SETTLE_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        min_confidence: int = DEFAULT_MIN_CONFIDENCE,
        include_existing: bool = False,
    ):
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_dir():
            raise ValueError(f"not a directory: {source_path}")
        destination_path = (
            Path(destination).expanduser().resolve() if destination is not None else None
        )
        if destination_path is not None and _inside(destination_path, source_path):
            raise ValueError("destination must be outside the source directory")

        self.source_path = source_path
        self.destination_path = destination_path
        self.apply_rules = bool(apply_rules)
        self.settle_seconds = max(0.0, float(settle_seconds))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.min_confidence = max(0, min(100, int(min_confidence)))
        self.categories = _effective_categories(source_path)
        self.ext_map = _build_ext_map(self.categories)
        self.rules = _effective_rules(source_path)
        self.destination_roots = [
            _destination_for_category(
                str(category.get("name", "Other")),
                self.categories,
                source_path,
                destination_path,
            )
            for category in self.categories
        ]
        initial = self._snapshot()
        self._seen: dict[str, tuple[int, int]] = {} if include_existing else initial
        self._pending: dict[str, dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._stop_requested = False

    def _snapshot(self) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for path in _walk_files(self.source_path, self.destination_roots):
            try:
                snapshot[str(path)] = _signature(path)
            except OSError:
                continue
        return snapshot

    def request_stop(self, *_signal_args) -> None:
        """Request a graceful stop; the run loop flushes settled work."""
        self._stop_requested = True
        self._stop_event.set()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def poll_once(self, now: float | None = None) -> list[dict[str, Any]]:
        """Detect arrivals and process files that have settled."""
        current_time = time.monotonic() if now is None else float(now)
        current = self._snapshot()

        for path in set(self._seen) - set(current) - set(self._pending):
            self._seen.pop(path, None)

        for path, file_signature in current.items():
            previous = self._seen.get(path)
            pending = self._pending.get(path)
            if previous != file_signature:
                self._seen[path] = file_signature
                if pending is None or tuple(pending["signature"]) != file_signature:
                    self._pending[path] = {
                        "signature": file_signature,
                        "stable_since": current_time,
                    }
            elif pending is not None and tuple(pending["signature"]) != file_signature:
                pending["signature"] = file_signature
                pending["stable_since"] = current_time

        ready = [
            path for path, pending in self._pending.items()
            if current_time - float(pending["stable_since"]) >= self.settle_seconds
        ]
        events: list[dict[str, Any]] = []
        for path in sorted(ready, key=str.casefold):
            pending = self._pending.pop(path, None)
            if pending is None:
                continue
            events.append(self._process(Path(path), tuple(pending["signature"])))
        return events

    def _process(self, path: Path, file_signature: tuple[int, int]) -> dict[str, Any]:
        event: dict[str, Any] = {
            "version": WATCH_SCHEMA_VERSION,
            "timestamp": datetime.now().isoformat(),
            "path": str(path),
            "status": "error",
            "action": "error",
        }
        try:
            if not path.is_file() or path.is_symlink():
                event.update(status="skipped", action="skipped", reason="file disappeared")
                return event
            if _signature(path) != file_signature:
                self._pending[str(path)] = {
                    "signature": _signature(path),
                    "stable_since": time.monotonic(),
                }
                event.update(status="deferred", action="deferred", reason="file changed while settling")
                return event
            item = plan_file_action(
                path,
                source_path=self.source_path,
                destination_path=self.destination_path,
                categories=self.categories,
                ext_map=self.ext_map,
                rules=self.rules,
                min_confidence=self.min_confidence,
                reserved=set(),
            )
            event["item"] = item
            if not item["selected"]:
                event.update(status=str(item["status"]).lower(), action="classified")
                return event
            if not self.apply_rules:
                event.update(status="pending", action="classified")
                return event
            self._move(item)
            event.update(status="done", action="moved")
            return event
        except (OSError, shutil.Error, TypeError, ValueError) as exc:
            event["reason"] = str(exc)
            return event

    @staticmethod
    def _move(item: dict[str, Any]) -> None:
        source = Path(item["src"])
        if is_protected(str(source)):
            raise OSError("source is protected")
        target = Path(item["dst"])
        if target.exists():
            target = _collision_safe_path(target, set())
            item["dst"] = str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        item["status"] = "Done"
        item["selected"] = False

    def run_once(self) -> list[dict[str, Any]]:
        """Run discovery and wait just long enough to flush settled arrivals."""
        events = self.poll_once()
        if not self._pending:
            return events
        deadline = time.monotonic() + self.settle_seconds + self.poll_seconds * 2 + 0.1
        while self._pending and time.monotonic() < deadline:
            time.sleep(min(self.poll_seconds, max(0.01, deadline - time.monotonic())))
            events.extend(self.poll_once())
        events.extend(self._defer_unsettled())
        return events

    def _defer_unsettled(self) -> list[dict[str, Any]]:
        events = []
        for path in sorted(self._pending, key=str.casefold):
            events.append({
                "version": WATCH_SCHEMA_VERSION,
                "timestamp": datetime.now().isoformat(),
                "path": path,
                "status": "deferred",
                "action": "deferred",
                "reason": "file did not settle before one-shot timeout",
            })
        self._pending.clear()
        return events

    def flush_pending(self) -> list[dict[str, Any]]:
        """Finish settled work after a termination request, bounded by a grace window."""
        events: list[dict[str, Any]] = []
        deadline = time.monotonic() + max(
            1.0, self.settle_seconds + self.poll_seconds * 2
        )
        while self._pending and time.monotonic() < deadline:
            events.extend(self.poll_once())
            if self._pending:
                time.sleep(min(self.poll_seconds, max(0.01, deadline - time.monotonic())))
        events.extend(self._defer_unsettled())
        return events

    def run(self, on_events: Callable[[list[dict[str, Any]]], None] | None = None) -> list[dict[str, Any]]:
        """Run until interrupted, then flush settled files before returning."""
        handlers: dict[int, Any] = {}
        if threading.current_thread() is threading.main_thread():
            for signal_name in ("SIGINT", "SIGTERM"):
                signal_number = getattr(signal, signal_name, None)
                if signal_number is None:
                    continue
                handlers[signal_number] = signal.getsignal(signal_number)
                signal.signal(signal_number, self.request_stop)
        events: list[dict[str, Any]] = []
        try:
            while not self._stop_event.is_set():
                batch = self.poll_once()
                if batch:
                    events.extend(batch)
                    if on_events:
                        on_events(batch)
                self._stop_event.wait(self.poll_seconds)
            batch = self.flush_pending()
            events.extend(batch)
            if batch and on_events:
                on_events(batch)
        finally:
            for signal_number, handler in handlers.items():
                signal.signal(signal_number, handler)
        return events

    def result(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Return a stable summary suitable for JSON or log consumers."""
        return {
            "version": WATCH_SCHEMA_VERSION,
            "source": str(self.source_path),
            "destination": str(self.destination_path) if self.destination_path else "",
            "apply_rules": self.apply_rules,
            "settle_seconds": self.settle_seconds,
            "poll_seconds": self.poll_seconds,
            "stopped": self._stop_requested,
            "events": events,
            "detected": len(events),
            "moved": sum(1 for event in events if event.get("action") == "moved"),
            "errors": sum(1 for event in events if event.get("status") == "error"),
            "deferred": sum(1 for event in events if event.get("status") == "deferred"),
        }
