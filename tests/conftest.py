"""Shared pytest fixtures for UniFile tests."""
import gc
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest

# Keep every pytest entrypoint pointer-free and windowless, including direct
# ``python -m pytest`` invocations that do not go through tools/run_tests.py.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# UniFile declares PyQt6, while some developer machines also have PySide6;
# pytest-qt otherwise selects the first importable binding and mismatches the app.
os.environ["PYTEST_QT_API"] = "pyqt6"


def _cleanup_tree(path: str | os.PathLike[str], *, attempts: int = 5) -> str | None:
    """Remove a test-owned tree, returning a diagnostic instead of masking tests."""
    last_error = ""
    for attempt in range(max(1, attempts)):
        try:
            shutil.rmtree(path)
            return None
        except FileNotFoundError:
            return None
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < attempts:
                time.sleep(0.05 * (attempt + 1))
    return last_error


def pytest_configure(config):
    """Give direct pytest invocations an isolated Windows temp root."""
    if config.option.basetemp is not None:
        config._unifile_owned_basetemp = False
        return
    root = Path(tempfile.gettempdir()) / "unifile-pytest"
    root.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = tempfile.mkdtemp(
        prefix=f"run-{os.getpid()}-",
        dir=str(root),
    )
    config._unifile_owned_basetemp = True


def pytest_sessionfinish(session, exitstatus):
    """Close registered resources and report cleanup separately from assertions."""
    diagnostics: list[str] = []
    try:
        from unifile.config import _close_all_sqlite_connections

        _close_all_sqlite_connections()
    except Exception as exc:
        diagnostics.append(f"SQLite cleanup: {type(exc).__name__}: {exc}")
    gc.collect()

    alive_threads = [
        thread.name for thread in threading.enumerate()
        if thread.is_alive() and thread is not threading.current_thread()
    ]
    if alive_threads:
        diagnostics.append("background threads still alive: " + ", ".join(alive_threads))

    if getattr(session.config, "_unifile_owned_basetemp", False):
        cleanup_error = _cleanup_tree(session.config.option.basetemp)
        if cleanup_error:
            diagnostics.append(
                "temporary-directory cleanup (environment/resource lock): "
                f"{session.config.option.basetemp}: {cleanup_error}"
            )

    if diagnostics:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            for diagnostic in diagnostics:
                reporter.write_line(f"UNIFILE TEST CLEANUP WARNING: {diagnostic}")
        if session.exitstatus == 0:
            session.exitstatus = 1


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory with some sample files."""
    # Create sample file structure
    (tmp_path / "photo_2024.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4" + b"\x00" * 100)
    (tmp_path / "script.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "video_tutorial.mp4").write_bytes(b"\x00" * 5000)
    (tmp_path / "invoice_march.xlsx").write_bytes(b"\x00" * 200)
    (tmp_path / "design_mockup.psd").write_bytes(b"\x00" * 300)
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "output.o").write_bytes(b"\x00" * 50)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("module.exports={}", encoding="utf-8")
    return tmp_path


@pytest.fixture
def ignore_file(tmp_dir):
    """Create a .unifile_ignore file in the temp directory."""
    ignore_path = tmp_dir / ".unifile_ignore"
    ignore_path.write_text(
        "# Build artifacts\n"
        "build/\n"
        "*.o\n"
        "node_modules/\n"
        "\n"
        "# Negate important build output\n"
        "!build/important.bin\n",
        encoding="utf-8"
    )
    return ignore_path


@pytest.fixture
def learning_db(tmp_path):
    """Create a temporary learning patterns database."""
    db_path = tmp_path / "learning_patterns.json"
    data = {
        'ext': {
            '.psd': {'Design Assets': 5, 'Graphics': 2},
            '.xlsx': {'Finance': 4},
        },
        'tokens': {
            'invoice': {'Finance': 6},
            'design': {'Design Assets': 3},
        },
        'folders': {},
        'sizes': {},
        'total': 20,
    }
    db_path.write_text(json.dumps(data), encoding="utf-8")
    return db_path


@pytest.fixture
def sample_file_items():
    """Create sample FileItem objects for testing."""
    from unifile.models import FileItem
    items = []
    for name, cat, conf in [
        ("photo1.jpg", "Photos", 90),
        ("photo2.png", "Photos", 85),
        ("report.pdf", "Documents", 80),
        ("budget.xlsx", "Finance", 75),
        ("readme.md", "Documents", 60),
        ("logo.psd", "Design Assets", 70),
        ("video.mp4", "Video", 95),
        ("song.mp3", "Audio", 88),
        ("data.csv", "Data", 65),
        ("script.py", "Code", 92),
        ("backup.zip", "Archives", 77),
        ("notes.txt", "Documents", 55),
    ]:
        it = FileItem()
        it.name = name
        it.full_src = f"/tmp/test/{name}"
        it.category = cat
        it.confidence = conf
        it.method = "test"
        items.append(it)
    return items
