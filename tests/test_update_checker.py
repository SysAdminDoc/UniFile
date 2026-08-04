"""Contract tests for the opt-out background release checker."""
import json

import pytest

from unifile.update_checker import (
    DISABLE_UPDATE_CHECK_KEY,
    UpdateBanner,
    UpdateInfo,
    fetch_latest_release,
    is_newer_version,
    parse_release_payload,
    update_check_disabled,
    version_tuple,
)


class _Settings:
    def __init__(self, **values):
        self.values = values

    def value(self, key, default=False, type=bool):
        del type
        return self.values.get(key, default)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        del exc_type, exc_value, traceback
        return False

    def read(self, limit):
        assert limit == 512 * 1024
        return json.dumps(self.payload).encode("utf-8")


def test_versions_accept_v_prefix_and_reject_malformed_values():
    assert version_tuple("v9.3.32") == (9, 3, 32)
    assert version_tuple("9.3.33-beta.1") == (9, 3, 33)
    assert version_tuple("9.3") is None
    assert is_newer_version("9.3.32", "v9.3.33")
    assert not is_newer_version("9.3.33", "9.3.32")


def test_release_payload_requires_new_stable_trusted_release():
    url = "https://github.com/SysAdminDoc/UniFile/releases/tag/v9.3.33"
    payload = {
        "tag_name": "v9.3.33",
        "html_url": url,
        "name": "UniFile 9.3.33",
        "draft": False,
        "prerelease": False,
    }
    assert parse_release_payload(payload, "9.3.32") == UpdateInfo(
        version="9.3.33", url=url, name="UniFile 9.3.33"
    )
    assert parse_release_payload({**payload, "prerelease": True}, "9.3.32") is None
    assert parse_release_payload({**payload, "html_url": "https://example.com/release"}, "9.3.32") is None
    assert parse_release_payload({**payload, "tag_name": "v9.3.31"}, "9.3.32") is None


def test_fetch_latest_release_uses_bounded_request_and_user_agent():
    payload = {
        "tag_name": "9.3.33",
        "html_url": "https://github.com/SysAdminDoc/UniFile/releases/tag/9.3.33",
        "draft": False,
        "prerelease": False,
    }
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["user_agent"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        return _Response(payload)

    result = fetch_latest_release("9.3.32", opener=opener)
    assert result is not None
    assert result.version == "9.3.33"
    assert seen == {
        "url": "https://api.github.com/repos/SysAdminDoc/UniFile/releases/latest",
        "user_agent": "UniFile/9.3.32",
        "timeout": 4.0,
    }


def test_update_check_setting_defaults_enabled_and_honors_disable_flag():
    assert not update_check_disabled(_Settings())
    assert update_check_disabled(_Settings(**{DISABLE_UPDATE_CHECK_KEY: True}))


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["unifile-update-test", "-platform", "offscreen"])
    return app


def test_update_banner_exposes_download_and_dismiss_actions(qapp):
    from unifile.config import get_active_theme

    info = UpdateInfo(
        version="9.3.33",
        url="https://github.com/SysAdminDoc/UniFile/releases/tag/9.3.33",
    )
    banner = UpdateBanner(info, get_active_theme())
    assert banner.download_button.text() == "Download"
    assert banner.dismiss_button.text() == "Dismiss"
    assert "not installed automatically" in banner.download_button.accessibleDescription()
    banner.deleteLater()
    qapp.processEvents()
