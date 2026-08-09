"""Reproducible Tag Library search benchmark.

The benchmark creates a disposable deterministic library, measures bounded
search pages with ``tracemalloc``, and exercises the SQLite cancellation hook.
It never touches a user's library or writes outside its temporary fixture.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from unifile.tagging.library import SearchCancelled, TagLibrary  # noqa: E402, I001
from unifile.tagging.models import Entry, TagEntry  # noqa: E402, I001


DEFAULT_ENTRIES = 10_000
DEFAULT_SEED = 20260808


def _build_fixture(library: TagLibrary, count: int, seed: int) -> None:
    paths = []
    for index in range(count):
        suffix = "pdf" if index % 4 == 0 else "txt"
        paths.append(str(Path(library.library_dir) / f"document-{seed + index:08d}.{suffix}"))
    library.add_entries_bulk(paths, batch_size=500)

    benchmark_tag = library.add_tag("benchmark")
    if not benchmark_tag:
        raise RuntimeError("Unable to create benchmark tag")
    entries = library._session.query(Entry).order_by(Entry.id).all()
    library._session.add_all([
        TagEntry(tag_id=benchmark_tag.id, entry_id=entry.id)
        for entry in entries[::2]
    ])
    library._session.commit()


def _measure(library: TagLibrary, query: str) -> dict[str, object]:
    tracemalloc.start()
    started = time.perf_counter()
    try:
        page = library.search_entries_page(query, limit=100, offset=0)
        result: dict[str, object] = {
            "query": query,
            "status": "completed",
            "total": page.total,
            "returned": len(page.entries),
            "index_mode": page.index_mode,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
    except Exception as exc:
        result = {
            "query": query,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result["peak_python_bytes"] = peak
    return result


def _measure_cancellation(library: TagLibrary, cancel_after_ms: float) -> dict[str, object]:
    started = time.perf_counter()

    def cancelled() -> bool:
        return (time.perf_counter() - started) * 1000.0 >= cancel_after_ms

    try:
        page = library.search_entries_page(
            "document AND ext:pdf",
            limit=100,
            cancel=cancelled,
        )
        return {
            "status": "completed-before-cancel",
            "returned": len(page.entries),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "cancel_after_ms": cancel_after_ms,
        }
    except SearchCancelled as exc:
        return {
            "status": "cancelled",
            "error": str(exc),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "cancel_after_ms": cancel_after_ms,
        }


def run_benchmark(entries: int = DEFAULT_ENTRIES, seed: int = DEFAULT_SEED,
                  cancel_after_ms: float = 2.0) -> dict[str, object]:
    """Run the benchmark and return a JSON-serializable report."""
    if entries < 1:
        raise ValueError("entries must be positive")
    with TemporaryDirectory(prefix="unifile-search-benchmark-") as temp_dir:
        library = TagLibrary(temp_dir)
        if not library.open():
            raise RuntimeError("Unable to open benchmark library")
        try:
            _build_fixture(library, entries, seed)
            queries = [
                _measure(library, "document"),
                _measure(library, "tag:benchmark AND ext:pdf"),
                _measure(library, "document OR ext:txt"),
            ]
            cancellation = _measure_cancellation(library, cancel_after_ms)
            return {
                "fixture": {"entries": entries, "seed": seed},
                "queries": queries,
                "cancellation": cancellation,
            }
        finally:
            library.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=int, default=DEFAULT_ENTRIES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--cancel-after-ms", type=float, default=2.0)
    args = parser.parse_args(argv)
    print(json.dumps(run_benchmark(
        entries=args.entries,
        seed=args.seed,
        cancel_after_ms=args.cancel_after_ms,
    ), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
