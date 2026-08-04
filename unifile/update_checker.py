"""Asynchronous GitHub release checks and the unobtrusive update banner."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

GITHUB_RELEASES_URL = "https://api.github.com/repos/SysAdminDoc/UniFile/releases/latest"
DISABLE_UPDATE_CHECK_KEY = "disable_update_check"
UPDATE_CHECK_TIMEOUT_SECONDS = 4.0
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_RELEASE_URL_PREFIX = "https://github.com/SysAdminDoc/UniFile/releases/"


@dataclass(frozen=True)
class UpdateInfo:
    """A stable release that is newer than the running application."""

    version: str
    url: str
    name: str = ""


def version_tuple(value: str) -> tuple[int, int, int] | None:
    """Parse a semantic three-part version, accepting a leading ``v``."""
    match = _VERSION_PATTERN.fullmatch(str(value).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def is_newer_version(current: str, candidate: str) -> bool:
    """Return whether ``candidate`` is a valid version newer than ``current``."""
    current_parts = version_tuple(current)
    candidate_parts = version_tuple(candidate)
    return bool(current_parts and candidate_parts and candidate_parts > current_parts)


def _trusted_release_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url).strip())
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "github.com"
        and parsed.path.startswith("/SysAdminDoc/UniFile/releases/")
    )


def parse_release_payload(payload: Any, current_version: str) -> UpdateInfo | None:
    """Convert GitHub's latest-release JSON into an actionable update, if any."""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    tag = str(payload.get("tag_name", "")).strip()
    url = str(payload.get("html_url", "")).strip()
    if not is_newer_version(current_version, tag) or not _trusted_release_url(url):
        return None
    version = tag.lstrip("vV")
    return UpdateInfo(version=version, url=url, name=str(payload.get("name", "")).strip())


def fetch_latest_release(
    current_version: str,
    *,
    api_url: str = GITHUB_RELEASES_URL,
    timeout: float = UPDATE_CHECK_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> UpdateInfo | None:
    """Fetch and parse the latest stable GitHub release without installing it."""
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"UniFile/{current_version}",
        },
    )
    with opener(request, timeout=timeout) as response:
        raw = response.read(512 * 1024)
    return parse_release_payload(json.loads(raw.decode("utf-8")), current_version)


def update_check_disabled(settings: Any) -> bool:
    """Read the persisted ``disable_update_check`` setting from QSettings-like data."""
    return bool(settings.value(DISABLE_UPDATE_CHECK_KEY, False, type=bool))


class UpdateCheckWorker(QThread):
    """Run the release request away from the GUI thread."""

    result_ready = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, current_version: str, *, api_url: str = GITHUB_RELEASES_URL, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.api_url = api_url

    def run(self) -> None:
        try:
            result = fetch_latest_release(self.current_version, api_url=self.api_url)
        except Exception as exc:  # network and malformed-response failures are non-fatal
            self.error.emit(str(exc))
            return
        self.result_ready.emit(result)


class UpdateBanner(QFrame):
    """Compact, dismissible banner offering a release download link only."""

    dismissed = pyqtSignal()
    download_requested = pyqtSignal(str)

    def __init__(self, info: UpdateInfo, theme: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self.setObjectName("update_banner")
        self.setAccessibleName("Software update available")
        self.setAccessibleDescription(
            f"UniFile {info.version} is available. Download it from GitHub or dismiss this notice."
        )
        self.setMaximumHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 10, 6)
        layout.setSpacing(10)

        message = QLabel(f"UniFile {info.version} is available.")
        message.setObjectName("update_banner_message")
        message.setAccessibleName("Update available message")
        if info.name:
            message.setToolTip(info.name)
        layout.addWidget(message, 1)

        self.download_button = QPushButton("Download")
        self.download_button.setObjectName("update_banner_download")
        self.download_button.setAccessibleName("Download UniFile update")
        self.download_button.setAccessibleDescription(
            "Open the GitHub release page. The update is not installed automatically."
        )
        self.download_button.setToolTip("Open the GitHub release page; no automatic install")
        self.download_button.clicked.connect(lambda: self.download_requested.emit(self.info.url))
        layout.addWidget(self.download_button)

        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.setObjectName("update_banner_dismiss")
        self.dismiss_button.setAccessibleName("Dismiss update notice")
        self.dismiss_button.clicked.connect(self.dismissed)
        layout.addWidget(self.dismiss_button)
        self.apply_theme(theme)

    def apply_theme(self, theme: dict) -> None:
        """Apply current theme tokens to the banner and its two actions."""
        self.setStyleSheet(
            f"QFrame#update_banner {{ background: {theme['selection']}; "
            f"border: 1px solid {theme['accent']}; border-radius: 8px; }}"
            f"QLabel#update_banner_message {{ color: {theme['fg_bright']}; font-weight: 600; }}"
            f"QPushButton#update_banner_download {{ background: {theme['accent']}; "
            f"color: {theme['btn_on_accent']}; border: 1px solid {theme['accent']}; "
            "border-radius: 8px; padding: 5px 12px; font-weight: 700; }"
            f"QPushButton#update_banner_download:hover {{ background: {theme['accent_hover']}; }}"
            f"QPushButton#update_banner_dismiss {{ background: transparent; color: {theme['fg']}; "
            f"border: 1px solid {theme['border']}; border-radius: 8px; padding: 5px 10px; }}"
            f"QPushButton#update_banner_dismiss:hover {{ background: {theme['btn_hover']}; }}"
        )


__all__ = [
    "DISABLE_UPDATE_CHECK_KEY",
    "GITHUB_RELEASES_URL",
    "UpdateBanner",
    "UpdateCheckWorker",
    "UpdateInfo",
    "fetch_latest_release",
    "is_newer_version",
    "parse_release_payload",
    "update_check_disabled",
    "version_tuple",
]
