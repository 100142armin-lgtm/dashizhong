"""GitHub release update checker for Clock/Alarm."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

DEFAULT_REPO = "100142armin-lgtm/dashizhong"
GITHUB_API_URL = f"https://api.github.com/repos/{DEFAULT_REPO}/releases/latest"
GITHUB_RAW_VERSION_URL = f"https://raw.githubusercontent.com/{DEFAULT_REPO}/main/VERSION"


def parse_semver(version_str: str) -> tuple[int, ...]:
    """Parse a version string like 'v1.0.17' or '1.0.17-rc1' into a numeric tuple."""
    cleaned = re.sub(r"^[vV]", "", version_str.strip())
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", cleaned)
    if not match:
        return (0, 0, 0)
    parts = [int(p) if p is not None else 0 for p in match.groups()]
    return tuple(parts)


def is_newer_version(latest: str, current: str) -> bool:
    """Return True if latest version is strictly newer than current version."""
    t_latest = parse_semver(latest)
    t_current = parse_semver(current)
    return t_latest > t_current


@dataclass
class UpdateInfo:
    has_update: bool
    latest_version: str
    current_version: str
    title: str = ""
    body: str = ""
    html_url: str = ""
    published_at: str = ""
    download_urls: dict[str, str] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def _create_request(url: str, current_version: str, timeout: float = 6.0) -> urllib.request.Request:
    headers = {
        "User-Agent": f"ClockAlarm/{current_version}",
        "Accept": "application/vnd.github.v3+json",
    }
    return urllib.request.Request(url, headers=headers)


def _get_opener() -> urllib.request.OpenerDirector:
    """Create an opener that uses local proxy if available."""
    try:
        from yt_feed_monitor import detect_local_proxy
        proxy_url = detect_local_proxy()
        if proxy_url:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            return urllib.request.build_opener(proxy_handler)
    except Exception as exc:
        logger.debug("Failed to detect local proxy for update check: %s", exc)
    return urllib.request.build_opener()


def check_update_sync(
    current_version: str,
    repo: str = DEFAULT_REPO,
    timeout: float = 6.0,
) -> UpdateInfo:
    """Synchronously check for new release from GitHub API with fallback to raw VERSION."""
    opener = _get_opener()
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    raw_version_url = f"https://raw.githubusercontent.com/{repo}/main/VERSION"

    # 1. Try GitHub Releases API
    try:
        req = _create_request(api_url, current_version, timeout)
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        tag_name = data.get("tag_name", "").strip()
        latest_clean = re.sub(r"^[vV]", "", tag_name)
        has_update = is_newer_version(latest_clean, current_version)

        downloads: dict[str, str] = {}
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            dl_url = asset.get("browser_download_url", "")
            if not dl_url:
                continue
            if "setup" in name.lower() and name.endswith(".exe"):
                downloads["installer"] = dl_url
            elif "portable" in name.lower() and name.endswith(".zip"):
                downloads["portable"] = dl_url

        return UpdateInfo(
            has_update=has_update,
            latest_version=latest_clean,
            current_version=current_version,
            title=data.get("name") or f"Clock/Alarm v{latest_clean}",
            body=data.get("body", "").strip(),
            html_url=data.get("html_url") or f"https://github.com/{repo}/releases/tag/{tag_name}",
            published_at=data.get("published_at", ""),
            download_urls=downloads,
        )
    except Exception as api_err:
        logger.warning("GitHub Releases API check failed: %s, trying raw VERSION", api_err)

    # 2. Fallback to raw VERSION file
    try:
        req = _create_request(raw_version_url, current_version, timeout)
        with opener.open(req, timeout=timeout) as resp:
            raw_ver = resp.read().decode("utf-8", errors="replace").strip()

        latest_clean = re.sub(r"^[vV]", "", raw_ver)
        has_update = is_newer_version(latest_clean, current_version)

        return UpdateInfo(
            has_update=has_update,
            latest_version=latest_clean,
            current_version=current_version,
            title=f"Clock/Alarm v{latest_clean}",
            body="检测到新版本发布，请前往 GitHub Releases 页面查看完整更新日志并下载安装。",
            html_url=f"https://github.com/{repo}/releases",
            published_at="",
            download_urls={},
        )
    except Exception as raw_err:
        logger.error("Raw VERSION update check failed: %s", raw_err)
        raise RuntimeError(f"无法连接更新服务器，请检查网络或稍后重试: {raw_err}") from raw_err


class UpdateCheckWorker(QThread):
    check_finished = pyqtSignal(object)  # UpdateInfo
    check_failed = pyqtSignal(str)       # Error message

    def __init__(
        self,
        current_version: str,
        repo: str = DEFAULT_REPO,
        timeout: float = 6.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.current_version = current_version
        self.repo = repo
        self.timeout = timeout

    def run(self) -> None:
        try:
            info = check_update_sync(
                current_version=self.current_version,
                repo=self.repo,
                timeout=self.timeout,
            )
            self.check_finished.emit(info)
        except Exception as exc:
            self.check_failed.emit(str(exc))
