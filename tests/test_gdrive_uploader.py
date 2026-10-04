"""Tests for Google Drive uploader, OAuth flow helpers, and screenshot integration."""

import time
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication

import gdrive_uploader
from gdrive_uploader import (
    GoogleDriveAuthManager,
    GoogleDriveUploader,
    GoogleDriveUploadWorker,
    copy_text_to_clipboard,
    find_available_port,
)
import screenshot_app
from screenshot_app import DOCK_ACTION_ROW, ScreenshotEditor

app = QApplication.instance() or QApplication([])


class GoogleDriveUploaderTests(unittest.TestCase):
    def test_find_available_port(self):
        port = find_available_port(8085, 8095)
        self.assertIsInstance(port, int)
        self.assertGreater(port, 1024)

    def test_token_validity_with_unexpired_token(self):
        future_time = time.time() + 3600
        creds = {
            "access_token": "valid_token_123",
            "expires_at": future_time,
            "refresh_token": "refresh_123",
        }
        token, err, updated = GoogleDriveAuthManager.get_valid_access_token(creds)
        self.assertEqual(token, "valid_token_123")
        self.assertIsNone(err)

    @patch("requests.post")
    def test_token_refresh_when_expired(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new_refreshed_token",
            "expires_in": 3600,
        }
        mock_post.return_value = mock_resp

        past_time = time.time() - 100
        creds = {
            "access_token": "old_token",
            "expires_at": past_time,
            "refresh_token": "refresh_xyz",
            "client_id": "cid_test",
            "client_secret": "csec_test",
        }
        token, err, updated = GoogleDriveAuthManager.get_valid_access_token(creds)
        self.assertEqual(token, "new_refreshed_token")
        self.assertIsNone(err)
        self.assertEqual(updated["access_token"], "new_refreshed_token")
        self.assertGreater(updated["expires_at"], time.time() + 3000)

    @patch("requests.post")
    def test_upload_png_bytes_success_and_public_link(self, mock_post):
        # First call is upload, second call is permissions
        upload_resp = MagicMock()
        upload_resp.status_code = 200
        upload_resp.json.return_value = {"id": "test_file_id_999", "name": "Screenshot_1.png"}

        perm_resp = MagicMock()
        perm_resp.status_code = 200
        perm_resp.json.return_value = {"id": "anyoneWithLink"}

        mock_post.side_effect = [upload_resp, perm_resp]

        fake_png = b"\x89PNG\r\n\x1a\nfake_image_bytes"
        result = GoogleDriveUploader.upload_png_bytes(
            png_bytes=fake_png,
            access_token="fake_token",
            folder_id="my_target_folder_id",
            filename="Test_Shot.png",
        )

        self.assertEqual(result["id"], "test_file_id_999")
        self.assertEqual(result["name"], "Test_Shot.png")
        self.assertEqual(
            result["web_view_link"],
            "https://drive.google.com/file/d/test_file_id_999/view?usp=sharing",
        )
        self.assertEqual(
            result["direct_link"],
            "https://lh3.googleusercontent.com/d/test_file_id_999",
        )
        self.assertEqual(mock_post.call_count, 2)

    @patch("requests.get")
    def test_test_connection_folder_valid(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "folder_123", "name": "我的截图文件夹", "trashed": False}
        mock_get.return_value = mock_resp

        creds = {
            "access_token": "tok_123",
            "expires_at": time.time() + 3600,
        }
        ok, msg = GoogleDriveUploader.test_connection(creds, "folder_123")
        self.assertTrue(ok)
        self.assertIn("我的截图文件夹", msg)

    @patch("requests.post")
    @patch("requests.get")
    def test_test_connection_folder_probe_success_on_404_get(self, mock_get, mock_post):
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 404
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {"id": "probe_id_999"}
        mock_post.return_value = mock_post_resp

        creds = {
            "access_token": "tok_123",
            "expires_at": time.time() + 3600,
        }
        with patch("requests.delete") as mock_del:
            ok, msg = GoogleDriveUploader.test_connection(creds, "folder_123")
            self.assertTrue(ok)
            self.assertIn("具备上传写入权限", msg)
            mock_del.assert_called_once()

    @patch("requests.post")
    @patch("requests.get")
    def test_test_connection_folder_not_found(self, mock_get, mock_post):
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 404
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 404
        mock_post.return_value = mock_post_resp

        creds = {
            "access_token": "tok_123",
            "expires_at": time.time() + 3600,
        }
        ok, msg = GoogleDriveUploader.test_connection(creds, "nonexistent_folder")
        self.assertFalse(ok)
        self.assertIn("不存在", msg)

    def test_copy_text_to_clipboard(self):
        test_url = "https://drive.google.com/file/d/12345/view?usp=sharing"
        res = copy_text_to_clipboard(test_url)
        self.assertTrue(res)

    def test_upload_direct_link_selection(self):
        with patch("requests.post") as mock_post:
            upload_resp = MagicMock()
            upload_resp.status_code = 200
            upload_resp.json.return_value = {"id": "direct_id_888", "name": "Direct.png"}
            perm_resp = MagicMock()
            perm_resp.status_code = 200
            perm_resp.json.return_value = {"id": "anyoneWithLink"}
            mock_post.side_effect = [upload_resp, perm_resp]

            result = GoogleDriveUploader.upload_png_bytes(
                png_bytes=b"fake",
                access_token="fake_token",
                direct_link=True,
            )
            self.assertEqual(result["share_url"], "https://lh3.googleusercontent.com/d/direct_id_888")

    def test_default_sharex_credentials_present(self):
        from gdrive_uploader import DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET
        self.assertTrue(DEFAULT_CLIENT_ID.endswith(".apps.googleusercontent.com"))
        self.assertGreater(len(DEFAULT_CLIENT_SECRET), 10)

    def test_find_sharex_gdrive_config(self):
        from gdrive_uploader import find_sharex_gdrive_config
        cfg = find_sharex_gdrive_config()
        # On this user's machine, ShareX is installed and configured
        if cfg:
            self.assertIn("folder_id", cfg)
            self.assertIn("is_public", cfg)

    def test_dock_action_row_contains_upload(self):
        keys = [item[0] for item in DOCK_ACTION_ROW]
        self.assertIn("upload", keys)
        self.assertIn("copy", keys)
        # Verify upload is placed adjacent to copy
        copy_idx = keys.index("copy")
        upload_idx = keys.index("upload")
        self.assertEqual(upload_idx, copy_idx + 1)

    def test_screenshot_prewarm_method_exists_on_app(self):
        from main import ClockAlarmApp
        self.assertTrue(hasattr(ClockAlarmApp, "_prewarm_screenshot"))

    def test_get_drive_session(self):
        from gdrive_uploader import get_drive_session
        sess = get_drive_session()
        self.assertIsNotNone(sess)
        self.assertTrue(hasattr(sess, "post"))

    def test_upload_notification_toast_lifecycle(self):
        from gdrive_uploader import UploadNotificationToast
        toast = UploadNotificationToast()
        toast.show_uploading()
        self.assertIn("正在上传", toast.title_lbl.text())
        self.assertFalse(toast.link_edit.isVisible())

        toast.show_success("https://drive.google.com/test_123")
        self.assertIn("成功", toast.title_lbl.text())
        self.assertTrue(toast.link_edit.isVisible())
        self.assertEqual(toast.link_edit.text(), "https://drive.google.com/test_123")
        self.assertEqual(toast._countdown, 5)

        # Tick 4 times
        for _ in range(4):
            toast._on_tick()
        self.assertEqual(toast._countdown, 1)
        self.assertIn("1s", toast.timer_badge.text())

        # 5th tick triggers close
        toast._on_tick()
        self.assertEqual(toast._countdown, 0)
        self.assertFalse(toast._timer.isActive())
        toast.close()

    def test_gdrive_credentials_persistence_across_restarts(self):
        from storage import JsonStore, DEFAULT_STATE
        saved_state = {
            "screenshot": {
                "gdrive": {
                    "is_public": True,
                    "folder_id": "test_folder_id_123",
                    "credentials": {
                        "access_token": "token_abc",
                        "refresh_token": "refresh_def",
                        "email": "user@gmail.com",
                    },
                },
                "auto_upload": True,  # should be dropped as legacy
            }
        }
        cleaned = JsonStore._drop_legacy_state(saved_state)
        # Verify legacy auto_upload was dropped, but gdrive was KEPT!
        self.assertNotIn("auto_upload", cleaned["screenshot"])
        self.assertIn("gdrive", cleaned["screenshot"])
        self.assertEqual(
            cleaned["screenshot"]["gdrive"]["credentials"]["email"],
            "user@gmail.com",
        )
        self.assertEqual(
            cleaned["screenshot"]["gdrive"]["folder_id"],
            "test_folder_id_123",
        )

    def test_screenshot_editor_modality_and_no_tool_flag(self):
        from PyQt6.QtCore import Qt, QRect
        from PyQt6.QtGui import QPixmap
        pm = QPixmap(100, 100)
        editor = ScreenshotEditor(pm, QRect(0, 0, 100, 100))
        # Ensure it has ApplicationModal so modal dialogs don't block screenshotting
        self.assertEqual(editor.windowModality(), Qt.WindowModality.ApplicationModal)
        # Ensure it is not a Tool window (Tool windows lose z-order to normal topmost windows)
        self.assertNotEqual(
            editor.windowFlags() & Qt.WindowType.WindowType_Mask,
            Qt.WindowType.Tool,
        )
        editor.close()

    def test_settings_dialog_modeless_in_main(self):
        from pathlib import Path
        source = Path(__file__).resolve().parents[1] / "main.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("dialog.setModal(False)", text)
        self.assertIn("dialog.show()", text)
        show_settings_code = text.split("def show_settings")[1].split("def start_deep_clean")[0]
        self.assertNotIn(".exec()", show_settings_code)

    def test_oauth_state_csrf_and_xss_protection(self):
        import io
        from unittest.mock import MagicMock
        from gdrive_uploader import _OAuthHandler, _OAuthServer

        server = MagicMock(spec=_OAuthServer)
        server.expected_state = "correct_secret_state"
        server.auth_code = None
        server.auth_error = None

        # 1. State mismatch -> CSRF blocked
        handler = _OAuthHandler.__new__(_OAuthHandler)
        handler.server = server
        handler.path = "/?code=malicious_code&state=wrong_state"
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.do_GET()

        self.assertIsNone(server.auth_code)
        self.assertIn("CSRF", server.auth_error)
        handler.send_response.assert_called_with(400)

        # 2. XSS in error message -> escaped
        handler = _OAuthHandler.__new__(_OAuthHandler)
        handler.server = server
        handler.path = "/?error=%3Cscript%3Ealert(1)%3C%2Fscript%3E&state=correct_secret_state"
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.do_GET()

        rendered = handler.wfile.getvalue().decode("utf-8")
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

        # 3. Valid state & code -> success
        handler = _OAuthHandler.__new__(_OAuthHandler)
        handler.server = server
        handler.path = "/?code=valid_code_xyz&state=correct_secret_state"
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.do_GET()

        self.assertEqual(server.auth_code, "valid_code_xyz")
        handler.send_response.assert_called_with(200)


if __name__ == "__main__":
    unittest.main()
