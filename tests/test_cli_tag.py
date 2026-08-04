"""Coverage for the Qt-free Tag Library query command."""

import argparse
import json
import os
import subprocess
import sys


def _seed_library(root):
    from unifile.tagging.library import TagLibrary

    root.mkdir()
    first = root / "outdoor-cat.jpg"
    second = root / "indoor-cat.jpg"
    third = root / "outdoor-dog.jpg"
    for path in (first, second, third):
        path.write_bytes(b"not-an-image")
    library = TagLibrary(str(root))
    assert library.open()
    cat = library.add_tag("cat")
    outdoor = library.add_tag("outdoor")
    dog = library.add_tag("dog")
    first_entry = library.add_entry(str(first))
    second_entry = library.add_entry(str(second))
    third_entry = library.add_entry(str(third))
    assert library.add_tags_to_entry(first_entry.id, [cat.id, outdoor.id])
    assert library.add_tags_to_entry(second_entry.id, [cat.id])
    assert library.add_tags_to_entry(third_entry.id, [dog.id, outdoor.id])
    library.close()


def test_normalize_tag_query_supports_bare_terms_and_selectors():
    from unifile.__main__ import _normalize_tag_query

    assert _normalize_tag_query("cat AND outdoor") == "tag:cat AND tag:outdoor"
    assert _normalize_tag_query("TAG:cat OR -tag:dog") == "tag:cat OR -tag:dog"
    assert _normalize_tag_query("cat AND ext:jpg") == "tag:cat AND ext:jpg"


def test_tag_subcommand_returns_boolean_tag_matches(tmp_path, capsys):
    from unifile.__main__ import _cmd_tag

    library = tmp_path / "library"
    _seed_library(library)
    args = argparse.Namespace(
        library=str(library), query="cat AND outdoor", limit=100, json=True
    )

    assert _cmd_tag(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "cat AND outdoor"
    assert payload["normalized_query"] == "tag:cat AND tag:outdoor"
    assert payload["count"] == 1
    assert payload["entries"][0]["name"] == "outdoor-cat.jpg"


def test_tag_subcommand_runs_from_shell(tmp_path):
    library = tmp_path / "library"
    _seed_library(library)
    env = os.environ.copy()
    env["APPDATA"] = str(tmp_path / "appdata")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unifile",
            "tag",
            "--library",
            str(library),
            "--query",
            "cat AND outdoor",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["count"] == 1
    assert payload["entries"][0]["name"] == "outdoor-cat.jpg"
