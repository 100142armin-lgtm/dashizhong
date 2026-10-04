"""Unit tests for release update checker and dialog."""
import io
import json
import unittest
from unittest.mock import MagicMock, patch
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication

from update_checker import (
    UpdateInfo,
    check_update_sync,
    is_newer_version,
    parse_semver,
)
from update_dialog import UpdateDialog

_app = None


def get_app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


class UpdateCheckerTests(unittest.TestCase):
    def test_parse_semver(self):
        self.assertEqual(parse_semver("1.0.17"), (1, 0, 17))
        self.assertEqual(parse_semver("v1.0.17"), (1, 0, 17))
        self.assertEqual(parse_semver("V2.1.0"), (2, 1, 0))
        self.assertEqual(parse_semver("1.2"), (1, 2, 0))
        self.assertEqual(parse_semver("3"), (3, 0, 0))
        self.assertEqual(parse_semver("invalid"), (0, 0, 0))

    def test_is_newer_version(self):
        self.assertTrue(is_newer_version("1.0.18", "1.0.17"))
        self.assertTrue(is_newer_version("v1.0.18", "1.0.17"))
        self.assertTrue(is_newer_version("1.1.0", "1.0.17"))
        self.assertTrue(is_newer_version("2.0.0", "1.0.17"))
        self.assertFalse(is_newer_version("1.0.17", "1.0.17"))
        self.assertFalse(is_newer_version("1.0.16", "1.0.17"))
        self.assertFalse(is_newer_version("v1.0.10", "1.0.17"))

    @patch("update_checker._get_opener")
    def test_check_update_api_success(self, mock_get_opener):
        mock_opener = MagicMock()
        mock_get_opener.return_value = mock_opener

        api_payload = {
            "tag_name": "v1.0.18",
            "name": "Clock/Alarm v1.0.18 发布",
            "body": "1. 界面优化\n2. 修复已知问题",
            "html_url": "https://github.com/100142armin-lgtm/dashizhong/releases/tag/v1.0.18",
            "published_at": "2026-09-12T10:00:00Z",
            "assets": [
                {
                    "name": "Clock-Alarm-1.0.18-windows-setup.exe",
                    "browser_download_url": "https://example.com/setup.exe",
                },
                {
                    "name": "Clock-Alarm-1.0.18-windows-portable.zip",
                    "browser_download_url": "https://example.com/portable.zip",
                },
            ],
        }
        mock_response = io.BytesIO(json.dumps(api_payload).encode("utf-8"))
        mock_opener.open.return_value = mock_response

        info = check_update_sync(current_version="1.0.17")
        self.assertTrue(info.has_update)
        self.assertEqual(info.latest_version, "1.0.18")
        self.assertEqual(info.title, "Clock/Alarm v1.0.18 发布")
        self.assertIn("界面优化", info.body)
        self.assertEqual(info.download_urls.get("installer"), "https://example.com/setup.exe")
        self.assertEqual(info.download_urls.get("portable"), "https://example.com/portable.zip")

    @patch("update_checker._get_opener")
    def test_check_update_fallback_raw_version(self, mock_get_opener):
        mock_opener = MagicMock()
        mock_get_opener.return_value = mock_opener

        # First call (API) raises Exception, second call (raw VERSION) returns 1.0.18
        mock_opener.open.side_effect = [
            Exception("API Rate limit 403"),
            io.BytesIO(b"1.0.18\n"),
        ]

        info = check_update_sync(current_version="1.0.17")
        self.assertTrue(info.has_update)
        self.assertEqual(info.latest_version, "1.0.18")

    @patch("update_checker._get_opener")
    def test_check_update_total_failure(self, mock_get_opener):
        mock_opener = MagicMock()
        mock_get_opener.return_value = mock_opener
        mock_opener.open.side_effect = Exception("No internet")

        with self.assertRaises(RuntimeError):
            check_update_sync(current_version="1.0.17")

    def test_update_dialog_ui(self):
        get_app()
        info = UpdateInfo(
            has_update=True,
            latest_version="1.0.18",
            current_version="1.0.17",
            title="新版发布",
            body="全新优化体验",
            html_url="https://github.com/100142armin-lgtm/dashizhong/releases",
            published_at="2026-09-12",
            download_urls={"installer": "https://example.com/installer.exe"},
        )
        ignored = []
        dlg = UpdateDialog(info, on_ignore=lambda v: ignored.append(v))
        self.assertIn("1.0.18", dlg.windowTitle())
        self.assertIn("全新优化体验", dlg.notes_browser.toPlainText())

        dlg._skip_this_version()
        self.assertEqual(ignored, ["1.0.18"])


if __name__ == "__main__":
    unittest.main()
