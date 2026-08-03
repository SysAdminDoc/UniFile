from unifile.tagging.library import TagLibrary


def _open_library(path):
    library = TagLibrary(str(path))
    assert library.open()
    return library


def test_implication_chain_propagates_and_expands_search(tmp_path):
    library = _open_library(tmp_path)
    try:
        kitten = library.add_tag("kitten")
        cat = library.add_tag("cat")
        animal = library.add_tag("animal")
        entry = library.add_entry(str(tmp_path / "photo.jpg"))
        legacy_entry = library.add_entry(str(tmp_path / "older-photo.jpg"))
        assert kitten and cat and animal and entry and legacy_entry

        # Existing entries are covered by query-time reverse expansion too.
        assert library.add_tags_to_entry(legacy_entry.id, [kitten.id])

        assert library.add_tag_implication(kitten.id, cat.id)
        assert library.add_tag_implication(cat.id, animal.id)
        assert not library.add_tag_implication(animal.id, kitten.id)
        assert library.get_tag_implication_ids(kitten.id) == {cat.id, animal.id}

        assert library.add_tags_to_entry(entry.id, [kitten.id])
        refreshed = library.get_entry(entry.id)
        assert refreshed
        assert {tag.id for tag in refreshed.tags} == {kitten.id, cat.id, animal.id}
        assert {match.id for match in library.search_entries("tag:animal")} == {
            entry.id,
            legacy_entry.id,
        }
    finally:
        library.close()


def test_siblings_apply_both_tags_and_can_be_removed(tmp_path):
    library = _open_library(tmp_path)
    try:
        jpeg = library.add_tag("jpeg")
        jpg = library.add_tag("jpg")
        entry = library.add_entry(str(tmp_path / "image.jpg"))
        assert jpeg and jpg and entry

        assert library.add_tag_sibling(jpeg.id, jpg.id)
        assert library.get_tag_sibling_ids(jpeg.id) == {jpg.id}
        assert library.get_tag_sibling_ids(jpg.id) == {jpeg.id}
        assert library.add_tags_to_entry(entry.id, [jpeg.id])
        refreshed = library.get_entry(entry.id)
        assert refreshed
        assert {tag.id for tag in refreshed.tags} == {jpeg.id, jpg.id}

        assert library.remove_tag_sibling(jpeg.id, jpg.id)
        assert library.get_tag_sibling_ids(jpeg.id) == set()
        assert not library.remove_tag_sibling(jpeg.id, jpg.id)
    finally:
        library.close()


def test_tag_pack_round_trips_relationships(tmp_path):
    source = _open_library(tmp_path / "source")
    try:
        kitten = source.add_tag("kitten")
        cat = source.add_tag("cat")
        feline = source.add_tag("feline")
        assert kitten and cat and feline
        assert source.add_tag_implication(kitten.id, cat.id)
        assert source.add_tag_sibling(cat.id, feline.id)
        pack_path = tmp_path / "relationships.json"
        assert source.export_tag_pack(str(pack_path))
    finally:
        source.close()

    restored = _open_library(tmp_path / "restored")
    try:
        assert restored.import_tag_pack(str(pack_path)) == {
            "imported": 3,
            "skipped": 0,
            "errors": 0,
        }
        kitten = restored.get_tag_by_name("kitten")
        cat = restored.get_tag_by_name("cat")
        feline = restored.get_tag_by_name("feline")
        assert kitten and cat and feline
        assert restored.get_tag_implication_ids(kitten.id) == {cat.id}
        assert restored.get_tag_sibling_ids(cat.id) == {feline.id}
    finally:
        restored.close()
