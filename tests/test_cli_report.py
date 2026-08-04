"""Coverage for Qt-free library report exports."""

import argparse
import json
import os
import subprocess
import sys


def _seed_report_library(root):
    from unifile.tagging.library import TagLibrary

    root.mkdir()
    document = root / "invoice.pdf"
    image = root / "photo.jpg"
    document.write_bytes(b"pdf")
    image.write_bytes(b"jpg")
    library = TagLibrary(str(root))
    assert library.open()
    documents = library.add_tag("Documents", is_category=True)
    important = library.add_tag("important")
    entry = library.add_entry(str(document))
    library.add_entry(str(image))
    assert library.add_tags_to_entry(entry.id, [documents.id, important.id])
    library.close()


def test_build_and_write_report_supports_html_pdf_and_json(tmp_path):
    from unifile.reports import build_library_report, write_report

    library = tmp_path / "library"
    _seed_report_library(library)
    report = build_library_report(library)
    assert report["entry_count"] == 2
    assert report["reported_entries"] == 2
    assert report["category_distribution"] == [
        {"name": "Documents", "count": 1},
        {"name": "Uncategorized", "count": 1},
    ]
    assert {item["name"] for item in report["files"]} == {"invoice.pdf", "photo.jpg"}

    html_path = tmp_path / "report.html"
    pdf_path = tmp_path / "report.pdf"
    json_path = tmp_path / "report.json"
    write_report(report, html_path, "html")
    write_report(report, pdf_path, "pdf")
    write_report(report, json_path, "json")
    html_text = html_path.read_text(encoding="utf-8")
    assert "Category distribution" in html_text
    assert "invoice.pdf" in html_text
    assert pdf_path.read_bytes().startswith(b"%PDF-1.4")
    assert pdf_path.read_bytes().rstrip().endswith(b"%%EOF")
    assert json.loads(json_path.read_text(encoding="utf-8"))["entry_count"] == 2


def test_report_subcommand_exports_html(tmp_path, capsys):
    from unifile.__main__ import _cmd_report

    library = tmp_path / "library"
    _seed_report_library(library)
    output = tmp_path / "report.html"
    args = argparse.Namespace(
        library=str(library), format="html", output=str(output), limit=10_000
    )

    assert _cmd_report(args) == 0
    assert output.is_file()
    assert "Report written" in capsys.readouterr().out


def test_report_subcommand_runs_from_shell(tmp_path):
    library = tmp_path / "library"
    _seed_report_library(library)
    output = tmp_path / "report.pdf"
    env = os.environ.copy()
    env["APPDATA"] = str(tmp_path / "appdata")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unifile",
            "report",
            "--library",
            str(library),
            "--format",
            "pdf",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes().startswith(b"%PDF-1.4")
