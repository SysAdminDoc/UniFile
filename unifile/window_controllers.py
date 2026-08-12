"""Stable controller facades for the main-window operation boundary.

The Qt window remains the public coordinator, but worker construction and
ownership live here so scan/apply flows can be tested without importing the
4,900-line widget.  The lifecycle controller deliberately owns cancellation
and bounded waits; callers do not terminate threads or leave orphaned worker
references themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QThread

from unifile.workers import (
    ApplyAepWorker,
    ApplyCatWorker,
    ApplyFilesWorker,
    ScanAepWorker,
    ScanCategoryWorker,
    ScanFilesLLMWorker,
    ScanFilesWorker,
    ScanLLMWorker,
)


class WorkerLifecycleError(RuntimeError):
    """Raised when a worker cannot be registered or started safely."""


class WorkerLifecycleController:
    """Own the lifecycle of GUI workers under stable string keys.

    ``QThread`` subclasses in the application expose different signal
    signatures, so the finished connection intentionally accepts ``*args``.
    A worker's optional ``cancel``/``stop`` method is called before Qt's
    interruption request, and ``close`` never force-terminates a live thread.
    The boolean result lets the window decide how to report an unresolved
    shutdown without pretending it was clean.
    """

    DEFAULT_WAIT_MS = 5_000

    def __init__(self, owner: Any = None):
        self.owner = owner
        self._workers: dict[str, QThread] = {}
        self._connections: dict[str, Any] = {}
        self._errors: dict[str, str] = {}

    def active_names(self) -> tuple[str, ...]:
        """Return active registrations in deterministic order."""
        return tuple(sorted(self._workers))

    def worker(self, name: str) -> QThread | None:
        """Return the registered worker, if any."""
        return self._workers.get(str(name))

    def last_error(self, name: str) -> str:
        """Return the most recent optional worker error owned by this controller."""
        return self._errors.get(str(name), "")

    def start(self, name: str, worker: QThread) -> QThread:
        """Register and start one worker, replacing a completed old worker."""
        key = str(name).strip()
        if not key:
            raise WorkerLifecycleError("worker name must not be empty")
        if worker is None or not hasattr(worker, "start"):
            raise WorkerLifecycleError(f"worker {key!r} is not startable")
        previous = self._workers.get(key)
        if previous is not None and previous is not worker:
            if not self.close(key):
                raise WorkerLifecycleError(f"worker {key!r} is still running")
        if hasattr(worker, "isRunning") and worker.isRunning():
            raise WorkerLifecycleError(f"worker {key!r} is already running")
        self._workers[key] = worker
        self._errors.pop(key, None)

        def on_finished(*_args, _key=key, _worker=worker):
            if self._workers.get(_key) is _worker:
                self._workers.pop(_key, None)
                self._connections.pop(_key, None)

        finished = getattr(worker, "finished", None)
        if finished is not None and hasattr(finished, "connect"):
            finished.connect(on_finished)
            self._connections[key] = on_finished

        def on_error(*args, _key=key):
            detail = next((arg for arg in reversed(args) if arg), "worker failed")
            self._errors[_key] = str(detail)
            callback = getattr(self.owner, "_on_worker_error", None)
            if callable(callback):
                callback(_key, self._errors[_key])

        for signal_name in ("error", "failed"):
            signal = getattr(worker, signal_name, None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(on_error)
        worker.start()
        return worker

    def cancel(self, name: str) -> bool:
        """Request cooperative cancellation for one registered worker."""
        worker = self._workers.get(str(name))
        if worker is None:
            return False
        for method_name in ("cancel", "stop"):
            method = getattr(worker, method_name, None)
            if callable(method):
                method()
                break
        request_interruption = getattr(worker, "requestInterruption", None)
        if callable(request_interruption):
            request_interruption()
        return True

    def close(self, name: str, *, timeout_ms: int | None = None) -> bool:
        """Cancel and wait for one worker; return false if it remains live."""
        key = str(name)
        worker = self._workers.get(key)
        if worker is None:
            return True
        self.cancel(key)
        running = getattr(worker, "isRunning", None)
        if callable(running) and running():
            wait = getattr(worker, "wait", None)
            if not callable(wait) or not wait(
                self._bounded_wait(timeout_ms)
            ):
                return False
        close_method = getattr(worker, "close", None)
        if callable(close_method):
            close_method()
        self._workers.pop(key, None)
        self._connections.pop(key, None)
        return True

    def close_all(self, *, timeout_ms: int | None = None) -> bool:
        """Close every owned worker and report whether all shutdowns completed."""
        results = [self.close(name, timeout_ms=timeout_ms) for name in self.active_names()]
        return all(results)

    def release(self, name: str, worker: QThread | None = None) -> bool:
        """Release a completed registration without touching a live thread."""
        key = str(name)
        current = self._workers.get(key)
        if current is None:
            return True
        if worker is not None and current is not worker:
            return False
        running = getattr(current, "isRunning", None)
        if callable(running) and running():
            return False
        self._workers.pop(key, None)
        self._connections.pop(key, None)
        return True

    @classmethod
    def _bounded_wait(cls, timeout_ms: int | None) -> int:
        try:
            value = int(timeout_ms if timeout_ms is not None else cls.DEFAULT_WAIT_MS)
        except (TypeError, ValueError):
            value = cls.DEFAULT_WAIT_MS
        return max(100, min(60_000, value))


class ScanController:
    """Factory facade for the four scan worker variants used by the window."""

    @staticmethod
    def aep(root_dir: str, *, scan_depth: int = 0) -> ScanAepWorker:
        return ScanAepWorker(root_dir, scan_depth=scan_depth)

    @staticmethod
    def category(root_dir: str, destination: str, *, scan_depth: int = 0,
                 use_llm: bool = False):
        worker_type = ScanLLMWorker if use_llm else ScanCategoryWorker
        return worker_type(root_dir, destination, scan_depth=scan_depth)

    @staticmethod
    def files(source: str, categories: list[dict], *, scan_depth: int = 0,
              check_hashes: bool = False, include_folders: bool = True,
              include_files: bool = True, ext_filter: set[str] | None = None,
              force_rescan: bool = False, use_llm: bool = False):
        worker_type = ScanFilesLLMWorker if use_llm else ScanFilesWorker
        kwargs = {
            "ext_filter": ext_filter,
            "force_rescan": force_rescan,
        }
        if use_llm:
            return worker_type(
                source, "", categories, scan_depth, check_hashes,
                include_folders, include_files, **kwargs,
            )
        return worker_type(
            source, "", categories, scan_depth, check_hashes,
            include_folders, include_files, **kwargs,
        )


class ApplyController:
    """Factory facade for the three apply worker variants."""

    @staticmethod
    def aep(work: list, *, check_hashes: bool = False, dry_run: bool = False) -> ApplyAepWorker:
        return ApplyAepWorker(work, check_hashes=check_hashes, dry_run=dry_run)

    @staticmethod
    def category(work: list, *, check_hashes: bool = False, dry_run: bool = False) -> ApplyCatWorker:
        return ApplyCatWorker(work, check_hashes=check_hashes, dry_run=dry_run)

    @staticmethod
    def files(work: list, *, check_hashes: bool = False, dry_run: bool = False) -> ApplyFilesWorker:
        return ApplyFilesWorker(work, check_hashes=check_hashes, dry_run=dry_run)


class LibraryController:
    """Own construction and lifecycle entry points for the Tag Library panel."""

    @staticmethod
    def create_panel(parent: Any = None):
        from unifile.dialogs.tag_library import TagLibraryPanel

        return TagLibraryPanel(parent)

    @staticmethod
    def close_panel(panel: Any) -> None:
        close_library = getattr(panel, "close_library", None)
        if callable(close_library):
            close_library()


@dataclass(frozen=True)
class MediaApplyResult:
    """Result of applying reviewed media metadata to selected entries."""

    title: str
    saved_entries: int


class MediaController:
    """Pure metadata-to-library boundary used by the media panel callback."""

    _FIELDS = {
        "title": "title",
        "author": "author",
        "artist": "artist",
        "synopsis": "ai_summary",
        "source_url": "url",
        "publisher": "publisher",
        "isbn": "isbn",
        "language": "language",
        "published": "published",
        "cover_url": "cover_url",
        "genres": "genre",
        "id_imdb": "imdb_id",
        "id_tmdb": "tmdb_id",
    }

    @staticmethod
    def create_panel(parent: Any = None):
        from unifile.dialogs.media_lookup import MediaLookupPanel

        return MediaLookupPanel(parent)

    @classmethod
    def apply_metadata(
        cls,
        metadata: dict[str, Any],
        library: Any,
        selected_entry_ids: list[Any],
    ) -> MediaApplyResult:
        """Apply one reviewed result without depending on Qt table widgets."""
        media_type = str(metadata.get("media_type", ""))
        title = str(metadata.get("title", "") or metadata.get("series", ""))
        fields = dict(cls._FIELDS)
        if media_type == "episode":
            fields.update({"series": "series", "season": "season", "episode": "episode", "date": "date"})
        elif media_type in {"book", "audiobook"}:
            fields["series"] = "series"

        raw_genres = metadata.get("genres", [])
        genres = [raw_genres] if isinstance(raw_genres, str) else list(raw_genres or [])
        genre_tags = []
        for genre in genres:
            name = str(genre).strip()
            if not name:
                continue
            tag = library.get_tag_by_name(name)
            if not tag:
                tag = library.add_tag(name, is_category=True, color_slug="purple")
            if tag:
                genre_tags.append(tag)

        saved = 0
        for entry_id in selected_entry_ids:
            for source_key, field_key in fields.items():
                value = metadata.get(source_key, "")
                if value:
                    if isinstance(value, list):
                        value = "; ".join(str(item) for item in value)
                    library.set_entry_field(entry_id, field_key, str(value))
            if genre_tags:
                library.add_tags_to_entry(entry_id, [tag.id for tag in genre_tags])
            saved += 1
        return MediaApplyResult(title=title, saved_entries=saved)


class CleanupController:
    """Own construction and tab selection for the inline cleanup surface."""

    @staticmethod
    def create_panel(parent: Any = None):
        from unifile.dialogs.cleanup import CleanupPanel

        return CleanupPanel(parent)

    @staticmethod
    def select_tab(panel: Any, index: int) -> None:
        tabs = getattr(panel, "tabs", None)
        if tabs is not None and hasattr(tabs, "setCurrentIndex"):
            tabs.setCurrentIndex(max(0, int(index)))


class WindowControllers:
    """Composition root for bounded window domain and worker facades."""

    def __init__(self, owner: Any = None):
        self.lifecycle = WorkerLifecycleController(owner)
        self.scan = ScanController()
        self.apply = ApplyController()
        self.library = LibraryController()
        self.media = MediaController()
        self.cleanup = CleanupController()

    def close(self) -> bool:
        return self.lifecycle.close_all()
