"""Tests for apply-time disk-space protection."""
from types import SimpleNamespace


def test_min_free_threshold_normalizes_invalid_and_out_of_range_values():
    from unifile.disk_space import normalize_min_free_mb

    assert normalize_min_free_mb("500") == 500
    assert normalize_min_free_mb("not-a-number") == 500
    assert normalize_min_free_mb(-1) == 0
    assert normalize_min_free_mb(2_000_000) == 1_000_000


def test_check_work_blocks_same_volume_apply_below_floor(tmp_path, monkeypatch):
    from unifile import disk_space

    destination = tmp_path / "destination"
    destination.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    item = SimpleNamespace(full_src=str(source), full_dst=str(destination / "source.txt"), size=6)

    monkeypatch.setattr(disk_space, "_volume_identity", lambda _path: "volume-a")
    monkeypatch.setattr(
        disk_space.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=499 * 1024 * 1024, total=0, used=0),
    )

    issues = disk_space.check_work([(0, item)], min_free_mb=500)

    assert len(issues) == 1
    assert issues[0].free_mb == 499
    assert issues[0].required_mb == 500


def test_check_work_reserves_bytes_for_cross_volume_copy(tmp_path, monkeypatch):
    from unifile import disk_space

    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    destination = tmp_path / "destination"
    destination.mkdir()
    item = SimpleNamespace(
        full_source_path=str(source),
        full_dest_path=str(destination / "source.bin"),
        size=200 * 1024 * 1024,
    )

    monkeypatch.setattr(
        disk_space,
        "_volume_identity",
        lambda path: "source-volume" if path == str(tmp_path) else "destination-volume",
    )
    monkeypatch.setattr(
        disk_space.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=600 * 1024 * 1024, total=0, used=0),
    )

    issues = disk_space.check_work([(0, item)], min_free_mb=500)

    assert len(issues) == 1
    assert issues[0].required_mb == 700


def test_check_work_supports_aep_rename_paths_without_cross_volume_bytes(tmp_path, monkeypatch):
    from unifile import disk_space

    source = tmp_path / "old-name"
    destination = tmp_path / "new-name"
    source.mkdir()
    item = SimpleNamespace(
        full_current_path=str(source),
        full_new_path=str(destination),
    )

    monkeypatch.setattr(disk_space, "_volume_identity", lambda _path: "volume-a")
    monkeypatch.setattr(
        disk_space.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=501 * 1024 * 1024, total=0, used=0),
    )

    assert disk_space.check_work([(0, item)], min_free_mb=500) == []
