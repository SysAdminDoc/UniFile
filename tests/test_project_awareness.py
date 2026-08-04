"""Video project media-reference discovery and Project Audit coverage."""

import gzip
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from unifile.project_awareness import apply_project_tags, build_project_audit, extract_project_references
from unifile.tagging.library import TagLibrary


def _make_prproj(path: Path, *references: str) -> Path:
    xml = "<Premiere><Media>" + "".join(
        f"<ActualMediaFilePath>{reference}</ActualMediaFilePath>" for reference in references
    ) + "</Media></Premiere>"
    path.write_bytes(gzip.compress(xml.encode("utf-8")))
    return path


def test_project_formats_extract_media_references(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    clip = media / "shared clip.mp4"
    still = media / "title card.jpg"
    clip.write_bytes(b"clip")
    still.write_bytes(b"still")

    premiere = _make_prproj(tmp_path / "Premiere.prproj", str(clip))
    after_effects = tmp_path / "After Effects.aep"
    after_effects.write_bytes(str(still).encode("utf-16-le") + b"\x00\x00")
    resolve = tmp_path / "Resolve.drp"
    with zipfile.ZipFile(resolve, "w") as archive:
        archive.writestr("MediaPool/MpFolder.xml", f"<Folder><FilePath>{clip}</FilePath></Folder>")
    final_cut = tmp_path / "Final Cut.fcpbundle"
    (final_cut / "Original Media").mkdir(parents=True)
    managed = final_cut / "Original Media" / "managed.mov"
    managed.write_bytes(b"managed")
    (final_cut / "Info.fcpxml").write_text(
        f'<fcpxml><asset src="{still.as_uri()}" /></fcpxml>', encoding="utf-8"
    )

    assert str(clip) in extract_project_references(premiere)
    assert any("title card.jpg" in value for value in extract_project_references(after_effects))
    assert str(clip) in extract_project_references(resolve)
    assert any("title card.jpg" in value for value in extract_project_references(final_cut))
    assert any("managed.mov" in value for value in extract_project_references(final_cut))


def test_project_audit_reports_shared_orphaned_and_missing_assets(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    shared = media / "shared.mp4"
    orphan = media / "orphan.mov"
    shared.write_bytes(b"shared")
    orphan.write_bytes(b"orphan")
    first = _make_prproj(tmp_path / "First.prproj", str(shared), str(media / "missing.mp4"))
    _make_prproj(tmp_path / "Second.prproj", str(shared))

    audit = build_project_audit(tmp_path)

    assert {project.name for project in audit.projects} == {"First", "Second"}
    assert len(audit.shared_assets) == 1
    assert next(iter(audit.shared_assets)).name == "shared.mp4"
    assert [path.name for path in audit.orphaned_assets] == ["orphan.mov"]
    assert len(audit.missing_references) == 1
    assert audit.missing_references[0].project_path == first
    assert audit.to_dict()["counts"]["shared_assets"] == 1


def test_project_tags_are_applied_without_modifying_source_projects(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    clip = media / "clip.mov"
    clip.write_bytes(b"clip")
    project = _make_prproj(tmp_path / "Promo.prproj", str(clip))
    before = project.read_bytes()
    library_root = tmp_path / "library"

    result = apply_project_tags(build_project_audit(tmp_path), library_root)

    assert result.applied == 1
    assert result.errors == []
    assert project.read_bytes() == before
    library = TagLibrary(str(library_root))
    assert library.open()
    try:
        entry = library.get_entry_by_path(str(clip))
        assert entry is not None
        fields = library.get_entry_fields(entry.id)
        assert fields["project_names"] == "Promo"
        assert fields["project_reference_count"] == "1"
        assert {"project-reference", "project:promo"}.issubset(set(entry.tag_names))
    finally:
        library.close()


def test_project_audit_cli_emits_json(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "clip.mp4").write_bytes(b"clip")
    _make_prproj(tmp_path / "Edit.prproj", str(media / "clip.mp4"))

    command = subprocess.run(
        [sys.executable, "-m", "unifile", "projects", "audit", str(tmp_path), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert command.returncode == 0, command.stderr
    payload = json.loads(command.stdout)
    assert payload["counts"]["projects"] == 1
    assert payload["counts"]["referenced_assets"] == 1
