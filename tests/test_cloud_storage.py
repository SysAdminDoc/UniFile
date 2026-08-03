import json
from types import SimpleNamespace

import pytest

from unifile.cloud_storage import (
    CloudRemoteConfig,
    RcloneAdapter,
    RcloneError,
    RemoteFile,
    iter_local_cloud_files,
    list_configured_rclone_remotes,
    load_cloud_remotes,
    local_cloud_status,
    save_cloud_remotes,
)


class FakeRclone:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[1] == "listremotes":
            return SimpleNamespace(returncode=0, stdout="archive:\nphotos:\n", stderr="")
        if args[1] == "lsjson":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([
                    {"Path": "nested/report.pdf", "Size": 100, "ModTime": "2026-08-01T12:00:00Z"},
                    {"Path": "large/report.pdf", "Size": 5000, "IsDir": False},
                    {"Path": "nested/photo.jpg", "Size": 50, "IsDir": False},
                    {"Path": "nested", "IsDir": True},
                ]),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_rclone_listing_is_filtered_and_machine_readable():
    runner = FakeRclone()
    adapter = RcloneAdapter("archive", "library", executable="rclone-test", runner=runner)
    files = adapter.list_files(extensions=("pdf",), max_size_bytes=1000)
    assert [file.path for file in files] == ["nested/report.pdf"]
    assert files[0].modified is not None
    assert runner.calls[0] == [
        "rclone-test", "lsjson", "archive:library", "--recursive", "--files-only", "--no-mimetype"
    ]


def test_rclone_download_and_sidecar_sync_stay_under_local_root(tmp_path):
    runner = FakeRclone()
    adapter = RcloneAdapter("archive", runner=runner, executable="rclone-test")
    files = [RemoteFile("nested/report.pdf")]
    local_file = tmp_path / "nested" / "report.pdf"
    local_file.parent.mkdir()
    local_file.with_name("report.pdf.xmp").write_text("xmp", encoding="utf-8")

    download = adapter.download_files(files, str(tmp_path))
    assert download["downloaded"] == 1
    assert download["failed"] == 0
    sync = adapter.sync_sidecars(files, str(tmp_path))
    assert sync["uploaded"] == 1
    assert any(call[1] == "copyto" and "--ignore-existing" in call for call in runner.calls)
    assert runner.calls[0][2].startswith("archive:nested/")


def test_rclone_remote_validation_and_failure_are_explicit():
    with pytest.raises(ValueError):
        RcloneAdapter("bad:remote")
    with pytest.raises(ValueError):
        RemoteFile("../outside.txt")

    def failed(_args):
        return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")

    with pytest.raises(RcloneError, match="permission denied"):
        RcloneAdapter("archive", runner=failed).list_files()


def test_cloud_remote_config_round_trips_without_credentials(tmp_path):
    path = tmp_path / "cloud.json"
    remote = CloudRemoteConfig(
        "Archive",
        "archive",
        remote_path="library",
        scan_mode="sync-back",
        download_dir=str(tmp_path / "downloads"),
        max_size_mb=25,
        extensions=(".PDF", "jpg"),
        sync_back=True,
    )
    assert save_cloud_remotes([remote], str(path))
    loaded = load_cloud_remotes(str(path))
    assert loaded == [remote]
    assert "password" not in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        CloudRemoteConfig("No folder", "archive", scan_mode="download")


def test_rclone_remote_list_and_local_cloud_placeholders():
    runner = FakeRclone()
    assert list_configured_rclone_remotes(executable="rclone-test", runner=runner) == [
        "archive", "photos"
    ]


def test_local_cloud_status_and_file_iteration_skip_placeholders(tmp_path):
    visible = tmp_path / "visible.txt"
    placeholder = tmp_path / "waiting.placeholder"
    visible.write_text("visible", encoding="utf-8")
    placeholder.write_text("not hydrated", encoding="utf-8")
    status = local_cloud_status(tmp_path)
    assert status["state"] == "partial"
    assert status["placeholder_count"] == 1
    assert list(iter_local_cloud_files(tmp_path)) == [visible]
    assert set(iter_local_cloud_files(tmp_path, include_placeholders=True)) == {visible, placeholder}
