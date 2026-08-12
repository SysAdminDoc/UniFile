from unifile.tagging.library import TagLibrary
from unifile.xmp_writer import (
    read_sidecar,
    read_sidecar_tags,
    sidecar_path,
    write_sidecar,
    write_sidecar_fields,
    write_sidecar_tags,
)


def test_xmp_tag_bridge_preserves_external_subjects(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"image")

    assert write_sidecar(str(source), "Photo")
    assert write_sidecar_fields(
        str(source), {"xmp:dc:subject": "Photo;camera-keyword"}
    )
    assert write_sidecar_tags(str(source), ["library-tag"])
    assert set(read_sidecar_tags(str(source))) == {
        "camera-keyword", "library-tag",
    }

    assert write_sidecar_tags(str(source), ["replacement-tag"])
    assert set(read_sidecar_tags(str(source))) == {
        "camera-keyword", "replacement-tag",
    }
    assert read_sidecar(str(source))["category"] == "Photo"
    assert sidecar_path(str(source)).endswith("photo.jpg.xmp")


def test_tag_library_imports_and_writes_xmp_tags_across_reopen(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"image")
    assert write_sidecar_tags(str(source), ["outside-tag"])

    first = TagLibrary(str(tmp_path))
    assert first.open()
    try:
        entry = first.add_entry(str(source))
        assert entry is not None
        assert {tag.name for tag in first.get_entry(entry.id).tags} == {"outside-tag"}
        managed = first.add_tag("managed-tag")
        assert managed is not None
        assert first.add_tags_to_entry(entry.id, [managed.id])
    finally:
        first.close()

    assert set(read_sidecar_tags(str(source))) == {"outside-tag", "managed-tag"}

    second = TagLibrary(str(tmp_path))
    assert second.open()
    try:
        reopened = second.get_entry_by_path(str(source))
        assert reopened is not None
        assert {tag.name for tag in reopened.tags} == {"outside-tag", "managed-tag"}
        managed = second.get_tag_by_name("managed-tag")
        assert managed is not None
        assert second.remove_tags_from_entry(reopened.id, [managed.id])
    finally:
        second.close()

    assert read_sidecar_tags(str(source)) == ["outside-tag"]
