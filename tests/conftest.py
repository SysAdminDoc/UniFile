"""Shared pytest fixtures for UniFile tests."""
import os
import json
import tempfile
import shutil

import pytest


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
