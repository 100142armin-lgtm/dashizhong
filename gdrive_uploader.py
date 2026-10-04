"""Google Drive Uploader for Screenshots with OAuth 2.0 Loopback Authentication.

Provides ShareX-style Google Drive authorization, folder targeting, multipart upload,
and automatic generation of public shareable links copied to the clipboard.
"""

from __future__ import annotations

import html
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import requests
import requests.adapters
from PyQt6.QtCore import QBuffer, QIODevice, QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Google OAuth 2.0 endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Google Drive API v3 endpoints
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"

# Minimal scope: only files created/opened by this app, plus user email for UI status
SCOPES = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/userinfo.email"

# ShareX official built-in Google OAuth Desktop Client Credentials (fallback)
DEFAULT_CLIENT_ID = os.environ.get(
    "GDRIVE_CLIENT_ID",
    "810697162603-ag350u1fnmf3riubv91otme0v5fkk2d6.apps.googleusercontent.com",
)
DEFAULT_CLIENT_SECRET = os.environ.get(
    "GDRIVE_CLIENT_SECRET",
    "mDft-efE0PUcwIRCLG8nkLD9",
)


def find_sharex_gdrive_config() -> dict | None:
    """Check if ShareX is installed and has Google Drive configuration."""
    from pathlib import Path
    candidates = [
        Path.home() / "Documents" / "ShareX" / "UploadersConfig.json",
        Path.home() / "AppData" / "Local" / "ShareX" / "UploadersConfig.json",
        Path.home() / "AppData" / "Roaming" / "ShareX" / "UploadersConfig.json",
    ]
    for p in candidates:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                user_info = data.get("GoogleDriveUserInfo") or {}
                folder_id = data.get("GoogleDriveFolderID") or ""
                is_public = data.get("GoogleDriveIsPublic", True)
                direct_link = data.get("GoogleDriveDirectLink", False)
                use_folder = data.get("GoogleDriveUseFolder", True)
                name = user_info.get("name") or user_info.get("given_name") or ""
                return {
                    "source_file": str(p),
                    "name": name,
                    "folder_id": folder_id,
                    "is_public": is_public,
                    "direct_link": direct_link,
                    "use_folder": use_folder,
                }
            except Exception:
                pass
    return None


def find_available_port(start_port: int = 8085, max_port: int = 8099) -> int:
    """Find an available port on 127.0.0.1 for the local OAuth redirect server."""
    for port in range(start_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    # Fallback: system-assigned port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _OAuthHandler(BaseHTTPRequestHandler):
    """Temporary local HTTP server handler to intercept the OAuth 2.0 redirect."""

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP access logs
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        state = params.get("state", [None])[0]

        server: _OAuthServer = self.server  # type: ignore

        # CSRF Protection: verify state parameter
        if server.expected_state and state != server.expected_state:
            code = None
            error = "安全校验失败：OAuth state 状态码不匹配（潜在 CSRF 攻击已被拦截）"

        server.auth_code = code
        server.auth_error = error

        if code:
            body = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Google Drive 授权成功</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
      background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center;
      height: 100vh; margin: 0;
    }
    .card {
      background: #1e293b; border: 1px solid #38bdf8; border-radius: 16px; padding: 40px 48px;
      text-align: center; max-width: 480px; box-shadow: 0 12px 30px rgba(0,0,0,0.5);
    }
    .badge {
      display: inline-block; background: rgba(16, 185, 129, 0.2); color: #34d399;
      font-weight: 700; padding: 6px 18px; border-radius: 9999px; margin-bottom: 20px; font-size: 14px;
      border: 1px solid rgba(16, 185, 129, 0.4);
    }
    h2 { color: #38bdf8; margin: 0 0 12px 0; font-size: 24px; font-weight: 700; }
    p { color: #94a3b8; font-size: 15px; line-height: 1.6; margin: 10px 0; }
    .footer { font-size: 13px; color: #64748b; margin-top: 24px; border-top: 1px solid #334155; padding-top: 16px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">✔ 授权成功</div>
    <h2>Google 账号授权已完成</h2>
    <p>桌面软件已成功连接至您的 Google Drive。</p>
    <p>现在可以安全关闭此网页，返回软件继续使用。</p>
    <div class="footer">DesktopToolkit · 截图云端上传</div>
  </div>
</body>
</html>"""
            status = 200
        else:
            raw_err = error or "未获取到有效的授权码"
            err_msg = html.escape(str(raw_err))
            body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Google Drive 授权失败</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
      background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center;
      height: 100vh; margin: 0;
    }}
    .card {{
      background: #1e293b; border: 1px solid #f87171; border-radius: 16px; padding: 40px 48px;
      text-align: center; max-width: 480px; box-shadow: 0 12px 30px rgba(0,0,0,0.5);
    }}
    .badge {{
      display: inline-block; background: rgba(239, 68, 68, 0.2); color: #f87171;
      font-weight: 700; padding: 6px 18px; border-radius: 9999px; margin-bottom: 20px; font-size: 14px;
      border: 1px solid rgba(239, 68, 68, 0.4);
    }}
    h2 {{ color: #f87171; margin: 0 0 12px 0; font-size: 24px; font-weight: 700; }}
    p {{ color: #cbd5e1; font-size: 15px; line-height: 1.6; margin: 10px 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">✖ 授权未完成</div>
    <h2>Google 账号授权失败</h2>
    <p>错误原因：{err_msg}</p>
    <p>您可以关闭此网页并在软件中重新尝试。</p>
  </div>
</body>
</html>"""
            status = 400

        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)


class _OAuthServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.auth_code: str | None = None
        self.auth_error: str | None = None
        self.expected_state: str | None = None


class GoogleDriveAuthManager(QObject):
    """Manages the OAuth 2.0 loopback flow, token refresh, and credential storage."""

    auth_success = pyqtSignal(dict)  # emits credential dict with email, tokens
    auth_failed = pyqtSignal(str)   # emits error description

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: _OAuthServer | None = None
        self._server_thread: threading.Thread | None = None

    def start_authorization(
        self, client_id: str | None = None, client_secret: str | None = None
    ) -> tuple[bool, str]:
        """Launch local loopback server and open default browser for Google OAuth."""
        cid = (client_id or "").strip() or DEFAULT_CLIENT_ID
        csec = (client_secret or "").strip() or DEFAULT_CLIENT_SECRET

        try:
            port = find_available_port()
            redirect_uri = f"http://127.0.0.1:{port}/"
            state = secrets.token_urlsafe(32)

            server = _OAuthServer(("127.0.0.1", port), _OAuthHandler)
            server.expected_state = state
            self._server = server

            def _listen_worker():
                try:
                    server.handle_request()  # handle single GET request
                    if server.auth_code:
                        self._exchange_code(server.auth_code, cid, csec, redirect_uri)
                    else:
                        err = server.auth_error or "用户取消授权或未收到授权码"
                        self.auth_failed.emit(f"授权失败：{err}")
                except Exception as exc:
                    self.auth_failed.emit(f"OAuth 回调异常：{exc}")
                finally:
                    try:
                        server.server_close()
                    except Exception:
                        pass
                    self._server = None

            self._server_thread = threading.Thread(target=_listen_worker, daemon=True)
            self._server_thread.start()

            params = {
                "client_id": cid,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": SCOPES,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
            auth_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
            webbrowser.open(auth_url)
            return True, f"已在浏览器中打开授权页面 (本地端口: {port})"

        except Exception as exc:
            return False, f"启动本地授权监听失败：{exc}"

    def _exchange_code(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> None:
        """Exchange authorization code for access_token and refresh_token."""
        try:
            resp = requests.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=15,
            )
            token_data = resp.json()
            if resp.status_code != 200 or "access_token" not in token_data:
                err_desc = token_data.get("error_description") or token_data.get("error") or str(token_data)
                self.auth_failed.emit(f"获取访问令牌失败 ({resp.status_code}): {err_desc}")
                return

            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 3600)
            expires_at = time.time() + float(expires_in)

            # Fetch user email and display name
            email = "Google 账号"
            name = ""
            try:
                userinfo_resp = requests.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                if userinfo_resp.status_code == 200:
                    uinfo = userinfo_resp.json()
                    email = uinfo.get("email") or email
                    name = uinfo.get("name") or uinfo.get("given_name") or ""
            except Exception:
                pass

            payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "email": email,
                "name": name,
                "authorized_at": time.time(),
            }
            self.auth_success.emit(payload)

        except Exception as exc:
            self.auth_failed.emit(f"交换 Token 网络错误：{exc}")

    @staticmethod
    def refresh_access_token(credentials: dict) -> tuple[bool, str, dict]:
        """Refreshes the access token using the stored refresh_token.
        
        Returns (success, error_or_token, updated_credentials).
        """
        refresh_token = credentials.get("refresh_token")
        client_id = (credentials.get("client_id") or "").strip() or DEFAULT_CLIENT_ID
        client_secret = (credentials.get("client_secret") or "").strip() or DEFAULT_CLIENT_SECRET

        if not refresh_token or not client_id or not client_secret:
            return False, "缺少 refresh_token 或客户端凭据，请重新授权", credentials

        try:
            resp = requests.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
            data = resp.json()
            if resp.status_code != 200 or "access_token" not in data:
                err = data.get("error_description") or data.get("error") or str(data)
                return False, f"刷新令牌失败 ({resp.status_code}): {err}", credentials

            new_creds = dict(credentials)
            new_creds["access_token"] = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            new_creds["expires_at"] = time.time() + float(expires_in)
            return True, data["access_token"], new_creds

        except Exception as exc:
            return False, f"刷新令牌网络异常：{exc}", credentials

    @staticmethod
    def get_valid_access_token(credentials: dict) -> tuple[str | None, str | None, dict]:
        """Ensures the credentials have an unexpired access token.
        
        Returns (access_token, error_message, updated_credentials).
        """
        if not credentials:
            return None, "未配置或未授权 Google 账号", credentials

        access_token = credentials.get("access_token")
        expires_at = credentials.get("expires_at", 0)

        # Token still valid with 60s buffer
        if access_token and time.time() < (expires_at - 60):
            return access_token, None, credentials

        # Otherwise refresh
        ok, res, updated = GoogleDriveAuthManager.refresh_access_token(credentials)
        if ok:
            return res, None, updated
        return None, res, credentials

    @staticmethod
    def revoke_authorization(credentials: dict) -> bool:
        """Revokes the refresh_token on Google's servers."""
        token = credentials.get("refresh_token") or credentials.get("access_token")
        if not token:
            return True
        try:
            requests.post(GOOGLE_REVOKE_URL, params={"token": token}, timeout=5)
            return True
        except Exception:
            return False


_DRIVE_SESSION: requests.Session | None = None


def get_drive_session() -> requests.Session:
    """Returns a pooled HTTP session to reuse TLS connections across requests."""
    global _DRIVE_SESSION
    if _DRIVE_SESSION is None:
        _DRIVE_SESSION = requests.Session()
        try:
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=5, pool_maxsize=10, max_retries=1
            )
            _DRIVE_SESSION.mount("https://", adapter)
            _DRIVE_SESSION.mount("http://", adapter)
        except Exception:
            pass
    return _DRIVE_SESSION


class GoogleDriveUploader:
    """Handles file uploading to Google Drive and setting public reader permissions."""

    @staticmethod
    def upload_png_bytes(
        png_bytes: bytes,
        access_token: str,
        folder_id: str | None = None,
        filename: str | None = None,
        is_public: bool = True,
        direct_link: bool = False,
        session: requests.Session | None = None,
    ) -> dict:
        """Uploads PNG bytes using Google Drive v3 multipart upload.
        
        Returns a dict containing id, name, web_view_link, and direct_link.
        Raises RuntimeError on API failure.
        """
        if not filename:
            filename = f"Screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"

        # 1. Metadata part
        metadata: dict[str, Any] = {
            "name": filename,
            "mimeType": "image/png",
        }
        if folder_id and folder_id.strip():
            metadata["parents"] = [folder_id.strip()]

        boundary = f"=======DesktopToolkitUploadBoundary{int(time.time() * 1000)}======="
        
        # Build multipart/related body
        meta_json = json.dumps(metadata, ensure_ascii=False)
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
        body.extend(meta_json.encode("utf-8"))
        body.extend(b"\r\n")

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b"Content-Type: image/png\r\n\r\n")
        body.extend(png_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        }

        # 2. Upload file
        http_post = session.post if session else requests.post
        upload_url = f"{DRIVE_UPLOAD_URL}&fields=id,name"
        resp = http_post(upload_url, headers=headers, data=body, timeout=30)
        if resp.status_code not in (200, 201):
            err_detail = resp.text
            try:
                err_detail = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                pass
            raise RuntimeError(f"文件上传失败 ({resp.status_code})：{err_detail}")

        file_data = resp.json()
        file_id = file_data["id"]

        # 3. Make file public (anyone: reader) if is_public is True
        if is_public:
            perm_url = f"{DRIVE_FILES_URL}/{file_id}/permissions?fields=id"
            perm_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            perm_resp = http_post(
                perm_url,
                headers=perm_headers,
                json={"role": "reader", "type": "anyone"},
                timeout=15,
            )
            if perm_resp.status_code not in (200, 201):
                logger.warning("设置公开权限返回非 200: %s", perm_resp.text)

        # 4. Construct ShareX-style links
        web_view_link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        direct_link_url = f"https://lh3.googleusercontent.com/d/{file_id}"
        share_url = direct_link_url if direct_link else web_view_link

        return {
            "id": file_id,
            "name": filename,
            "web_view_link": web_view_link,
            "direct_link": direct_link_url,
            "share_url": share_url,
        }

    @staticmethod
    def test_connection(credentials: dict, folder_id: str | None = None) -> tuple[bool, str]:
        """Tests token validity and folder existence if folder_id is specified."""
        token, err, _ = GoogleDriveAuthManager.get_valid_access_token(credentials)
        if not token:
            return False, f"授权令牌无效：{err}"

        headers = {"Authorization": f"Bearer {token}"}
        if folder_id and folder_id.strip():
            fid = folder_id.strip()
            url = f"{DRIVE_FILES_URL}/{fid}?fields=id,name,mimeType,trashed"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    info = resp.json()
                    if info.get("trashed"):
                        return False, f"指定的目标文件夹已在回收站中 ({info.get('name')})"
                    return True, f"连接正常！目标文件夹：【{info.get('name')}】"

                # Under drive.file scope, folders created outside this app return 404 on GET.
                # In this case, test actual write capability via a lightweight temporary probe.
                if resp.status_code == 404:
                    probe_headers = {
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    }
                    probe_payload = {
                        "name": f".probe_{int(time.time())}.tmp",
                        "parents": [fid],
                        "mimeType": "text/plain",
                    }
                    probe_resp = requests.post(
                        f"{DRIVE_FILES_URL}?fields=id",
                        headers=probe_headers,
                        json=probe_payload,
                        timeout=10,
                    )
                    if probe_resp.status_code in (200, 201):
                        probe_id = probe_resp.json().get("id")
                        if probe_id:
                            try:
                                requests.delete(
                                    f"{DRIVE_FILES_URL}/{probe_id}", headers=headers, timeout=5
                                )
                            except Exception:
                                pass
                        return True, f"连接正常！Google 账号授权有效，目标文件夹【{fid}】具备上传写入权限！"
                    elif probe_resp.status_code == 404:
                        return False, f"目标文件夹不存在（ID: {fid}），请检查文件夹 ID 是否填写正确"
                    elif probe_resp.status_code == 403:
                        err_msg = probe_resp.json().get("error", {}).get("message", probe_resp.text)
                        return False, f"当前 Google 账号无权写入该文件夹：{err_msg}"
                    else:
                        return False, f"验证文件夹写入权限失败 ({probe_resp.status_code})"

                return False, f"验证文件夹失败 ({resp.status_code}): {resp.text}"
            except Exception as exc:
                return False, f"网络请求异常：{exc}"
        else:
            # Check drive root / about
            try:
                about_url = "https://www.googleapis.com/drive/v3/about?fields=user"
                resp = requests.get(about_url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    user_name = resp.json().get("user", {}).get("displayName", "Google 用户")
                    return True, f"连接正常！当前用户：{user_name}（将上传至云盘根目录）"
                return False, f"验证账号失败 ({resp.status_code})"
            except Exception as exc:
                return False, f"网络请求异常：{exc}"


class GoogleDriveUploadWorker(QThread):
    """Background worker thread for non-blocking screenshot upload."""

    upload_success = pyqtSignal(dict)  # emits upload result dict
    upload_failed = pyqtSignal(str)   # emits error message

    def __init__(
        self,
        image: QImage | bytes,
        state: dict,
        filename: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._image = image
        self._state = state
        self._filename = filename

    def run(self) -> None:
        try:
            screenshot_cfg = self._state.setdefault("screenshot", {})
            gdrive_cfg = screenshot_cfg.setdefault("gdrive", {})
            creds = gdrive_cfg.get("credentials") or {}

            token, err, updated_creds = GoogleDriveAuthManager.get_valid_access_token(creds)
            if not token:
                self.upload_failed.emit(err or "未完成 Google 账号授权，请先在【设置】中绑定")
                return

            if updated_creds != creds:
                gdrive_cfg["credentials"] = updated_creds

            # Convert QImage to PNG bytes if necessary
            if isinstance(self._image, QImage):
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img = self._image
                if not img.hasAlphaChannel() and img.format() != QImage.Format.Format_RGB32:
                    img = img.convertToFormat(QImage.Format.Format_RGB32)
                img.save(buf, "PNG", 50)
                png_bytes = bytes(buf.data())
            elif isinstance(self._image, (bytes, bytearray)):
                png_bytes = bytes(self._image)
            else:
                self.upload_failed.emit("无效的图像数据格式")
                return

            use_folder = bool(gdrive_cfg.get("use_folder", True))
            folder_id = str(gdrive_cfg.get("folder_id") or "").strip() if use_folder else None
            is_public = bool(gdrive_cfg.get("is_public", True))
            direct_link = bool(gdrive_cfg.get("direct_link", False))

            session = get_drive_session()
            result = GoogleDriveUploader.upload_png_bytes(
                png_bytes=png_bytes,
                access_token=token,
                folder_id=folder_id if folder_id else None,
                filename=self._filename,
                is_public=is_public,
                direct_link=direct_link,
                session=session,
            )

            # Auto copy share link to clipboard
            share_url = result.get("share_url") or result.get("web_view_link", "")
            if share_url:
                copy_text_to_clipboard(share_url)

            self.upload_success.emit(result)

        except Exception as exc:
            self.upload_failed.emit(f"上传失败：{exc}")


def copy_text_to_clipboard(text: str) -> bool:
    """Robust text copying using Win32 API with Qt clipboard fallback."""
    if not text:
        return False

    success = False
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            GMEM_MOVEABLE = 0x0002
            CF_UNICODETEXT = 13

            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            user32.SetClipboardData.restype = wintypes.HANDLE
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL

            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalUnlock.restype = wintypes.BOOL

            if user32.OpenClipboard(None):
                try:
                    user32.EmptyClipboard()
                    encoded = (text + "\0").encode("utf-16le")
                    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
                    if h_mem:
                        ptr = kernel32.GlobalLock(h_mem)
                        if ptr:
                            ctypes.memmove(ptr, encoded, len(encoded))
                            kernel32.GlobalUnlock(h_mem)
                            if user32.SetClipboardData(CF_UNICODETEXT, h_mem):
                                success = True
                finally:
                    user32.CloseClipboard()
        except Exception:
            success = False

    if not success:
        try:
            cb = QGuiApplication.clipboard()
            if cb:
                cb.setText(text)
                success = True
        except Exception:
            pass

    return success


_ACTIVE_TOASTS: list[UploadNotificationToast] = []


class UploadNotificationToast(QDialog):
    """Floating desktop notification popup for Google Drive screenshot upload.

    - Non-modal, frameless, stays on top, without stealing keyboard focus.
    - Appears at the bottom-right corner of desktop (above taskbar).
    - In success state, automatically counts down 5 seconds and closes.
    - Hovering mouse pauses the 5-second countdown.
    - Features [🌐 打开链接], [📋 复制链接], and [✕ 关闭] actions.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(None)
        self._link: str = ""
        self._countdown: int = 5
        self._is_paused: bool = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(380)

        # Card container
        self.card = QFrame(self)
        self.card.setObjectName("toastCard")
        self.card.setStyleSheet("""
            QFrame#toastCard {
                background-color: #0f172a;
                border: 1px solid #0284c7;
                border-radius: 12px;
            }
            QLabel {
                color: #e2e8f0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 4)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)

        # Header Row
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        self.title_lbl = QLabel("☁️ 正在上传至 Google Drive...")
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #38bdf8;")
        header_row.addWidget(self.title_lbl)

        header_row.addStretch(1)

        self.timer_badge = QLabel("5s 自动关闭")
        self.timer_badge.setStyleSheet(
            "font-size: 11px; color: #94a3b8; background: rgba(148, 163, 184, 0.15); border-radius: 4px; padding: 2px 6px;"
        )
        self.timer_badge.setVisible(False)
        header_row.addWidget(self.timer_badge)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #94a3b8; border: none; font-size: 12px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(248, 113, 113, 0.2); color: #f87171; }"
        )
        self.close_btn.clicked.connect(self.close)
        header_row.addWidget(self.close_btn)

        card_layout.addLayout(header_row)

        # Subtitle message
        self.subtitle_lbl = QLabel("正在上传截图并生成公开直链，请稍候…")
        self.subtitle_lbl.setWordWrap(True)
        self.subtitle_lbl.setStyleSheet("font-size: 12px; color: #94a3b8; line-height: 1.4;")
        card_layout.addWidget(self.subtitle_lbl)

        # Link input box
        self.link_edit = QLineEdit()
        self.link_edit.setReadOnly(True)
        self.link_edit.setStyleSheet(
            "QLineEdit { background: #020617; color: #38bdf8; border: 1px solid #334155; border-radius: 6px; padding: 5px 8px; font-size: 11px; selection-background-color: #0284c7; }"
        )
        self.link_edit.setVisible(False)
        card_layout.addWidget(self.link_edit)

        # Buttons Row
        self.btn_row_widget = QWidget()
        btn_layout = QHBoxLayout(self.btn_row_widget)
        btn_layout.setContentsMargins(0, 4, 0, 0)
        btn_layout.setSpacing(8)

        self.open_btn = QPushButton("🌐 打开链接")
        self.open_btn.setFixedHeight(28)
        self.open_btn.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; border: none; border-radius: 5px; padding: 0 12px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background-color: #0369a1; }"
        )
        self.open_btn.clicked.connect(self._on_open_clicked)
        btn_layout.addWidget(self.open_btn)

        self.copy_btn = QPushButton("📋 复制链接")
        self.copy_btn.setFixedHeight(28)
        self.copy_btn.setStyleSheet(
            "QPushButton { background-color: #1e293b; color: #e2e8f0; border: 1px solid #475569; border-radius: 5px; padding: 0 12px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background-color: #334155; }"
        )
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        btn_layout.addWidget(self.copy_btn)

        btn_layout.addStretch(1)

        self.dismiss_btn = QPushButton("关闭")
        self.dismiss_btn.setFixedHeight(28)
        self.dismiss_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #94a3b8; border: none; border-radius: 5px; padding: 0 8px; font-size: 12px; }"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 0.08); color: #f1f5f9; }"
        )
        self.dismiss_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.dismiss_btn)

        self.btn_row_widget.setVisible(False)
        card_layout.addWidget(self.btn_row_widget)

        # Outer layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.addWidget(self.card)

        # Auto-close timer
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        if self not in _ACTIVE_TOASTS:
            _ACTIVE_TOASTS.append(self)

    def show_uploading(self) -> None:
        self.title_lbl.setText("☁️ 正在上传至 Google Drive...")
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #38bdf8;")
        self.subtitle_lbl.setText("正在上传截图并生成公开直链，请稍候…")
        self.timer_badge.setVisible(False)
        self.link_edit.setVisible(False)
        self.btn_row_widget.setVisible(False)
        self.card.setStyleSheet("""
            QFrame#toastCard {
                background-color: #0f172a;
                border: 1px solid #0284c7;
                border-radius: 12px;
            }
            QLabel { color: #e2e8f0; }
        """)
        self._position_bottom_right()
        self.show()

    def show_success(self, link: str) -> None:
        self._link = link
        self.title_lbl.setText("🎉 截图已成功上传！")
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #4ade80;")
        self.subtitle_lbl.setText("公开直链已复制到剪贴板，可直接粘贴分享：")
        self.link_edit.setText(link)
        self.link_edit.setCursorPosition(0)
        self.link_edit.setVisible(True)
        self.btn_row_widget.setVisible(True)
        self.open_btn.setVisible(True)
        self.copy_btn.setVisible(True)
        self.timer_badge.setVisible(True)
        self.card.setStyleSheet("""
            QFrame#toastCard {
                background-color: #0f172a;
                border: 1px solid #10b981;
                border-radius: 12px;
            }
            QLabel { color: #e2e8f0; }
        """)
        self._countdown = 5
        self._is_paused = False
        self._update_countdown_label()
        self._timer.start(1000)
        self._position_bottom_right()
        self.show()
        self.raise_()

    def show_error(self, err_msg: str) -> None:
        self.title_lbl.setText("❌ 上传失败")
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #f87171;")
        self.subtitle_lbl.setText(err_msg)
        self.link_edit.setVisible(False)
        self.btn_row_widget.setVisible(True)
        self.open_btn.setVisible(False)
        self.copy_btn.setVisible(False)
        self.timer_badge.setVisible(True)
        self.card.setStyleSheet("""
            QFrame#toastCard {
                background-color: #0f172a;
                border: 1px solid #ef4444;
                border-radius: 12px;
            }
            QLabel { color: #e2e8f0; }
        """)
        self._countdown = 6
        self._is_paused = False
        self._update_countdown_label()
        self._timer.start(1000)
        self._position_bottom_right()
        self.show()
        self.raise_()

    def _on_tick(self) -> None:
        self._countdown -= 1
        if self._countdown <= 0:
            self._timer.stop()
            self.close()
        else:
            self._update_countdown_label()

    def _update_countdown_label(self) -> None:
        if self._is_paused:
            self.timer_badge.setText("已暂停")
            self.timer_badge.setStyleSheet(
                "font-size: 11px; color: #fbbf24; background: rgba(251, 191, 36, 0.15); border-radius: 4px; padding: 2px 6px;"
            )
        else:
            self.timer_badge.setText(f"{self._countdown}s 自动关闭")
            self.timer_badge.setStyleSheet(
                "font-size: 11px; color: #94a3b8; background: rgba(148, 163, 184, 0.15); border-radius: 4px; padding: 2px 6px;"
            )

    def enterEvent(self, event) -> None:
        self._is_paused = True
        self._timer.stop()
        self._update_countdown_label()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._is_paused = False
        if self._countdown > 0:
            self._timer.start(1000)
        self._update_countdown_label()
        super().leaveEvent(event)

    def _on_open_clicked(self) -> None:
        if self._link:
            webbrowser.open(self._link)
        self.close()

    def _on_copy_clicked(self) -> None:
        if self._link:
            copy_text_to_clipboard(self._link)
            self.copy_btn.setText("已复制 ✓")
            self.copy_btn.setStyleSheet(
                "QPushButton { background-color: #059669; color: white; border: none; border-radius: 5px; padding: 0 12px; font-size: 12px; font-weight: 600; }"
            )
            QTimer.singleShot(1000, self.close)

    def _position_bottom_right(self) -> None:
        self.adjustSize()
        scr = QGuiApplication.primaryScreen()
        if scr:
            geom = scr.availableGeometry()
            x = geom.right() - self.width() - 16
            y = geom.bottom() - self.height() - 16
            self.move(x, y)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self in _ACTIVE_TOASTS:
            try:
                _ACTIVE_TOASTS.remove(self)
            except ValueError:
                pass
        super().closeEvent(event)
