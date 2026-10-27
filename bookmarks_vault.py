"""AES-256-GCM Encrypted Bookmark Vault with Dual-Key Recovery (Blink Architecture).

Implements:
- Hardware-accelerated AES-256-GCM via Windows CNG (bcrypt.dll) with pure-stdlib
  authenticated stream cipher fallback (BLAKE2b-CTR + HMAC-SHA256).
- Dual-Key Wrapping (Strategy 2):
  A random 256-bit Vault Master Key encrypts the bookmark database.
  The Vault Master Key is wrapped twice:
    1) By the user's Master Password (derived via scrypt)
    2) By a 16-char Emergency Recovery Key (BK-XXXX-XXXX-XXXX)
  This guarantees 100% lossless bookmark preservation when resetting a forgotten
  master password via the Recovery Key.
- Additive Netscape HTML bookmark import & Dual-Track export (HTML + encrypted .blinkbak).
"""

from __future__ import annotations

import base64
import copy
import ctypes
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

VAULT_VERSION = 2
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 30.0

CATEGORY_COLORS: dict[str, dict[str, str]] = {
    "indigo": {"name": "靛蓝", "hex": "#6366f1", "bg": "rgba(99, 102, 241, 0.16)", "border": "rgba(99, 102, 241, 0.45)"},
    "emerald": {"name": "翠绿", "hex": "#10b981", "bg": "rgba(16, 185, 129, 0.16)", "border": "rgba(16, 185, 129, 0.45)"},
    "amber": {"name": "琥珀", "hex": "#f59e0b", "bg": "rgba(245, 158, 11, 0.16)", "border": "rgba(245, 158, 11, 0.45)"},
    "rose": {"name": "玫红", "hex": "#f43f5e", "bg": "rgba(244, 63, 94, 0.16)", "border": "rgba(244, 63, 94, 0.45)"},
    "violet": {"name": "紫罗兰", "hex": "#8b5cf6", "bg": "rgba(139, 92, 246, 0.16)", "border": "rgba(139, 92, 246, 0.45)"},
    "cyan": {"name": "青碧", "hex": "#06b6d4", "bg": "rgba(6, 182, 212, 0.16)", "border": "rgba(6, 182, 212, 0.45)"},
    "pink": {"name": "粉霞", "hex": "#ec4899", "bg": "rgba(236, 72, 153, 0.16)", "border": "rgba(236, 72, 153, 0.45)"},
    "teal": {"name": "松石", "hex": "#14b8a6", "bg": "rgba(20, 184, 166, 0.16)", "border": "rgba(20, 184, 166, 0.45)"},
}

COLOR_KEYS = list(CATEGORY_COLORS.keys())
RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _escape_html(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _unescape_html(text: str) -> str:
    s = str(text or "")
    s = (
        s.replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )
    return re.sub(
        r"&#(\d+);",
        lambda m: chr(int(m.group(1))) if 0 <= int(m.group(1)) <= 0x10FFFF else m.group(0),
        s,
    )


def normalize_bookmark_url(raw_url: str) -> str:
    """Validate and normalize bookmark URLs. Only http:// and https:// are permitted."""
    url = str(raw_url or "").strip()
    if not url:
        raise ValueError("网址不能为空")
    lower = url.lower()
    if lower.startswith(("javascript:", "data:", "vbscript:", "file:", "about:", "blob:")):
        raise ValueError("出于安全保护，仅支持 http:// 或 https:// 网页链接")
    if "://" not in url:
        url = "https://" + url
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("仅支持 http:// 或 https:// 协议的网址")
    if not parsed.netloc or ("." not in parsed.netloc and parsed.hostname != "localhost"):
        raise ValueError("请输入有效的域名或网址")
    return url


def generate_recovery_key() -> str:
    """Generate a human-friendly 16-char recovery key: BK-XXXX-XXXX-XXXX-XXXX."""
    groups = [
        "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(4))
        for _ in range(4)
    ]
    return "BK-" + "-".join(groups)


def normalize_recovery_key(raw_key: str) -> str:
    """Normalize user-entered recovery key by stripping spaces/dashes and upper-casing."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(raw_key or "")).upper()
    if cleaned.startswith("BK"):
        cleaned = cleaned[2:]
    return cleaned


def _derive_key(secret_text: str, salt: bytes) -> bytes:
    """Derive a 256-bit key using scrypt (N=16384, r=8, p=1) with PBKDF2-SHA256 fallback."""
    raw = str(secret_text).encode("utf-8")
    if hasattr(hashlib, "scrypt"):
        try:
            return hashlib.scrypt(raw, salt=salt, n=16384, r=8, p=1, dklen=32)
        except Exception:
            pass
    return hashlib.pbkdf2_hmac("sha256", raw, salt, 200_000, dklen=32)


class _BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("dwInfoVersion", ctypes.c_ulong),
        ("pbNonce", ctypes.c_void_p),
        ("cbNonce", ctypes.c_ulong),
        ("pbAuthData", ctypes.c_void_p),
        ("cbAuthData", ctypes.c_ulong),
        ("pbTag", ctypes.c_void_p),
        ("cbTag", ctypes.c_ulong),
        ("pbMacContext", ctypes.c_void_p),
        ("cbMacContext", ctypes.c_ulong),
        ("cbAAD", ctypes.c_ulong),
        ("cbData", ctypes.c_ulonglong),
        ("dwFlags", ctypes.c_ulong),
    ]


def _cng_aes256_gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> tuple[bytes, bytes] | None:
    """Encrypt with Windows CNG (bcrypt.dll) AES-256-GCM."""
    if sys.platform != "win32":
        return None
    try:
        bcrypt = ctypes.windll.bcrypt
    except Exception:
        return None

    h_alg = ctypes.c_void_p()
    h_key = ctypes.c_void_p()
    try:
        if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(h_alg), ctypes.c_wchar_p("AES"), None, 0) != 0:
            return None
        mode = "ChainingModeGCM\x00".encode("utf-16-le")
        if bcrypt.BCryptSetProperty(h_alg, ctypes.c_wchar_p("ChainingMode"), mode, len(mode), 0) != 0:
            return None
        if bcrypt.BCryptGenerateSymmetricKey(h_alg, ctypes.byref(h_key), None, 0, key, len(key), 0) != 0:
            return None

        nonce_buf = ctypes.create_string_buffer(nonce, len(nonce))
        tag_buf = ctypes.create_string_buffer(16)
        pt_len = len(plaintext)
        ct_buf = ctypes.create_string_buffer(max(1, pt_len))

        info = _BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
        info.cbSize = ctypes.sizeof(info)
        info.dwInfoVersion = 1
        info.pbNonce = ctypes.cast(nonce_buf, ctypes.c_void_p)
        info.cbNonce = len(nonce)
        info.pbTag = ctypes.cast(tag_buf, ctypes.c_void_p)
        info.cbTag = 16

        cb_result = ctypes.c_ulong()
        status = bcrypt.BCryptEncrypt(
            h_key, plaintext, pt_len, ctypes.byref(info),
            None, 0, ct_buf, pt_len, ctypes.byref(cb_result), 0
        )
        if status != 0:
            return None
        return ct_buf.raw[:pt_len], tag_buf.raw[:16]
    except Exception:
        return None
    finally:
        if h_key.value:
            try:
                bcrypt.BCryptDestroyKey(h_key)
            except Exception:
                pass
        if h_alg.value:
            try:
                bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)
            except Exception:
                pass


def _cng_aes256_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes | None:
    """Decrypt and verify tag with Windows CNG (bcrypt.dll) AES-256-GCM."""
    if sys.platform != "win32":
        return None
    try:
        bcrypt = ctypes.windll.bcrypt
    except Exception:
        return None

    h_alg = ctypes.c_void_p()
    h_key = ctypes.c_void_p()
    try:
        if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(h_alg), ctypes.c_wchar_p("AES"), None, 0) != 0:
            return None
        mode = "ChainingModeGCM\x00".encode("utf-16-le")
        if bcrypt.BCryptSetProperty(h_alg, ctypes.c_wchar_p("ChainingMode"), mode, len(mode), 0) != 0:
            return None
        if bcrypt.BCryptGenerateSymmetricKey(h_alg, ctypes.byref(h_key), None, 0, key, len(key), 0) != 0:
            return None

        nonce_buf = ctypes.create_string_buffer(nonce, len(nonce))
        tag_buf = ctypes.create_string_buffer(tag, len(tag))
        ct_len = len(ciphertext)
        pt_buf = ctypes.create_string_buffer(max(1, ct_len))

        info = _BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
        info.cbSize = ctypes.sizeof(info)
        info.dwInfoVersion = 1
        info.pbNonce = ctypes.cast(nonce_buf, ctypes.c_void_p)
        info.cbNonce = len(nonce)
        info.pbTag = ctypes.cast(tag_buf, ctypes.c_void_p)
        info.cbTag = len(tag)

        cb_result = ctypes.c_ulong()
        status = bcrypt.BCryptDecrypt(
            h_key, ciphertext, ct_len, ctypes.byref(info),
            None, 0, pt_buf, ct_len, ctypes.byref(cb_result), 0
        )
        if status != 0:
            raise ValueError("AES-256-GCM 认证标签校验失败或密码错误")
        return pt_buf.raw[:ct_len]
    finally:
        if h_key.value:
            try:
                bcrypt.BCryptDestroyKey(h_key)
            except Exception:
                pass
        if h_alg.value:
            try:
                bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)
            except Exception:
                pass


def _stdlib_stream_xor(enc_key: bytes, nonce: bytes, data: bytes) -> bytes:
    """Pure-stdlib BLAKE2b counter-mode stream cipher fallback."""
    out = bytearray(len(data))
    offset = 0
    counter = 0
    while offset < len(data):
        block = hashlib.blake2b(
            counter.to_bytes(8, "little"),
            key=enc_key,
            salt=nonce[:16].ljust(16, b"\x00"),
            digest_size=64,
        ).digest()
        chunk_len = min(64, len(data) - offset)
        for i in range(chunk_len):
            out[offset + i] = data[offset + i] ^ block[i]
        offset += chunk_len
        counter += 1
    return bytes(out)


def aead_encrypt(key: bytes, plaintext: bytes) -> dict[str, str]:
    """Encrypt plaintext with 256-bit key using AES-256-GCM (or stdlib AEAD fallback)."""
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes")
    nonce = os.urandom(12)
    cng_res = _cng_aes256_gcm_encrypt(key, nonce, plaintext)
    if cng_res is not None:
        ciphertext, tag = cng_res
        return {
            "alg": "aes-256-gcm",
            "iv": base64.b64encode(nonce).decode("ascii"),
            "tag": base64.b64encode(tag).decode("ascii"),
            "data": base64.b64encode(ciphertext).decode("ascii"),
        }
    enc_key = hmac.new(key, b"blink-enc", hashlib.sha256).digest()
    mac_key = hmac.new(key, b"blink-mac", hashlib.sha256).digest()
    ciphertext = _stdlib_stream_xor(enc_key, nonce, plaintext)
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()[:16]
    return {
        "alg": "blake2b-hmac-sha256",
        "iv": base64.b64encode(nonce).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
        "data": base64.b64encode(ciphertext).decode("ascii"),
    }


def aead_decrypt(key: bytes, box: dict[str, Any]) -> bytes:
    """Decrypt an AEAD box created by aead_encrypt. Raises ValueError on wrong key or tampering."""
    if len(key) != 32 or not isinstance(box, dict):
        raise ValueError("无效的加密数据块")
    alg = str(box.get("alg") or "aes-256-gcm")
    nonce = base64.b64decode(str(box.get("iv") or ""))
    tag = base64.b64decode(str(box.get("tag") or ""))
    ciphertext = base64.b64decode(str(box.get("data") or ""))

    if alg == "aes-256-gcm":
        res = _cng_aes256_gcm_decrypt(key, nonce, ciphertext, tag)
        if res is None:
            raise ValueError("当前系统环境不支持 AES-256-GCM 解密")
        return res
    elif alg == "blake2b-hmac-sha256":
        enc_key = hmac.new(key, b"blink-enc", hashlib.sha256).digest()
        mac_key = hmac.new(key, b"blink-mac", hashlib.sha256).digest()
        expected_tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected_tag):
            raise ValueError("认证标签校验失败或密码错误")
        return _stdlib_stream_xor(enc_key, nonce, ciphertext)
    else:
        raise ValueError(f"未知的加密算法: {alg}")


def default_vault_payload() -> dict[str, Any]:
    """Default categories and starter bookmarks matching Blink's aesthetic."""
    now_ms = int(time.time() * 1000)
    cat_freq = "cat_frequent"
    cat_work = "cat_workspace"
    cat_web = "cat_services"
    cat_ai = "cat_ai_tools"
    cat_fun = "cat_media"
    return {
        "categories": [
            {"id": cat_freq, "name": "高频常用", "color": "indigo"},
            {"id": cat_work, "name": "工作台", "color": "emerald"},
            {"id": cat_web, "name": "网站与服务", "color": "amber"},
            {"id": cat_ai, "name": "AI 工具箱", "color": "violet"},
            {"id": cat_fun, "name": "视频与娱乐", "color": "rose"},
        ],
        "bookmarks": [
            {
                "id": "bm_github",
                "title": "GitHub 工作台",
                "url": "https://github.com",
                "note": "代码托管与团队协作仓库",
                "categoryId": cat_freq,
                "pinned": True,
                "order": 0,
                "createdAt": now_ms - 3000,
                "updatedAt": now_ms - 3000,
            },
            {
                "id": "bm_google",
                "title": "Google 搜索",
                "url": "https://www.google.com",
                "note": "全球检索入口",
                "categoryId": cat_freq,
                "pinned": False,
                "order": 1,
                "createdAt": now_ms - 2000,
                "updatedAt": now_ms - 2000,
            },
            {
                "id": "bm_chatgpt",
                "title": "ChatGPT",
                "url": "https://chatgpt.com",
                "note": "OpenAI 智能对话助手",
                "categoryId": cat_ai,
                "pinned": True,
                "order": 2,
                "createdAt": now_ms - 1000,
                "updatedAt": now_ms - 1000,
            },
        ],
    }


def _default_vault_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    configured = os.environ.get("CLOCK_ALARM_DATA_DIR", "")
    root = Path(configured) if configured else Path(base) / "ClockAlarm"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        root = Path(tempfile.gettempdir()) / "ClockAlarm"
        root.mkdir(parents=True, exist_ok=True)
    return root / "blink-vault.json"


_VAULT_LOCK = threading.RLock()


class BookmarksVault:
    """AES-256-GCM Encrypted Bookmark Vault with Dual-Key Recovery."""

    def __init__(self, vault_path: Path | str | None = None) -> None:
        self.vault_path = Path(vault_path) if vault_path else _default_vault_path()
        self.backup_path = self.vault_path.with_suffix(".backup.json")
        self._master_key: bytes | None = None
        self._data: dict[str, Any] | None = None
        self._failed_attempts: int = 0
        self._lockout_until: float = 0.0

    # ── Status & Rate-Limiting ──────────────────────────────────────────────
    def is_initialized(self) -> bool:
        """Return True if a vault file exists and has valid structure."""
        meta = self._read_envelope()
        return bool(meta and isinstance(meta.get("vault_box"), dict))

    def is_unlocked(self) -> bool:
        return self._master_key is not None and self._data is not None

    def remaining_lockout_seconds(self) -> int:
        rem = self._lockout_until - time.monotonic()
        return max(0, int(rem + 0.999)) if rem > 0 else 0

    def _check_rate_limit(self) -> tuple[bool, str]:
        rem = self.remaining_lockout_seconds()
        if rem > 0:
            return False, f"密码尝试次数过多，请等待 {rem} 秒后再试"
        return True, ""

    def _record_failure(self) -> str:
        self._failed_attempts += 1
        if self._failed_attempts >= MAX_FAILED_ATTEMPTS:
            self._lockout_until = time.monotonic() + LOCKOUT_SECONDS
            self._failed_attempts = 0
            return f"连续输错 {MAX_FAILED_ATTEMPTS} 次，已触发安全锁定 {int(LOCKOUT_SECONDS)} 秒"
        left = MAX_FAILED_ATTEMPTS - self._failed_attempts
        return f"密码或急救码不正确（还可尝试 {left} 次）"

    def _reset_failures(self) -> None:
        self._failed_attempts = 0
        self._lockout_until = 0.0

    # ── Envelope I/O ────────────────────────────────────────────────────────
    def _read_envelope(self) -> dict[str, Any] | None:
        for candidate in (self.vault_path, self.backup_path):
            if not candidate.is_file():
                continue
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and "vault_box" in raw:
                    return raw
            except Exception:
                continue
        return None

    def _write_envelope(self, envelope: dict[str, Any]) -> None:
        with _VAULT_LOCK:
            self.vault_path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(envelope, ensure_ascii=False, indent=2)
            tmp_path = self.vault_path.with_suffix(".tmp")
            tmp_path.write_text(serialized, encoding="utf-8")
            if self.vault_path.is_file():
                try:
                    shutil.copy2(self.vault_path, self.backup_path)
                except OSError:
                    pass
            tmp_path.replace(self.vault_path)

    def _save_unlocked_data(self) -> None:
        if not self.is_unlocked():
            raise RuntimeError("书签保险库处于锁定状态，无法保存")
        envelope = self._read_envelope()
        if not envelope:
            raise RuntimeError("未找到保险库元数据")
        payload_bytes = json.dumps(self._data, ensure_ascii=False).encode("utf-8")
        envelope["vault_box"] = aead_encrypt(self._master_key, payload_bytes)
        envelope["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._write_envelope(envelope)

    # ── Vault Lifecycle: Init / Unlock / Lock / Recovery / Password Change ──
    def initialize_vault(self, master_password: str, initial_data: dict[str, Any] | None = None) -> str:
        """Initialize a new encrypted vault with Dual-Key protection.

        Returns the 16-char Emergency Recovery Key (BK-XXXX-XXXX-XXXX-XXXX).
        """
        pwd = str(master_password or "").strip()
        if len(pwd) < 4:
            raise ValueError("主密码长度至少需要 4 个字符")

        master_key = os.urandom(32)
        recovery_key = generate_recovery_key()
        norm_recovery = normalize_recovery_key(recovery_key)

        pwd_salt = os.urandom(16)
        rec_salt = os.urandom(16)
        pwd_kek = _derive_key(pwd, pwd_salt)
        rec_kek = _derive_key(norm_recovery, rec_salt)

        payload = copy.deepcopy(initial_data) if isinstance(initial_data, dict) else default_vault_payload()
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        envelope = {
            "version": VAULT_VERSION,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "password_wrap": {
                "salt": base64.b64encode(pwd_salt).decode("ascii"),
                "box": aead_encrypt(pwd_kek, master_key),
            },
            "recovery_wrap": {
                "salt": base64.b64encode(rec_salt).decode("ascii"),
                "box": aead_encrypt(rec_kek, master_key),
            },
            "vault_box": aead_encrypt(master_key, payload_bytes),
        }
        self._write_envelope(envelope)
        self._master_key = master_key
        self._data = payload
        self._reset_failures()
        return recovery_key

    def unlock(self, master_password: str) -> tuple[bool, str]:
        """Unlock the vault using the user's master password."""
        allowed, msg = self._check_rate_limit()
        if not allowed:
            return False, msg

        envelope = self._read_envelope()
        if not envelope:
            return False, "保险库尚未初始化"

        pwd = str(master_password or "").strip()
        if not pwd:
            return False, "请输入主密码"

        try:
            pwd_wrap = envelope.get("password_wrap") or {}
            pwd_salt = base64.b64decode(str(pwd_wrap.get("salt") or ""))
            pwd_kek = _derive_key(pwd, pwd_salt)
            master_key = aead_decrypt(pwd_kek, pwd_wrap.get("box") or {})
            raw_payload = aead_decrypt(master_key, envelope.get("vault_box") or {})
            data = json.loads(raw_payload.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("保险库数据格式异常")
            data.setdefault("categories", [])
            data.setdefault("bookmarks", [])
            self._master_key = master_key
            self._data = data
            self._reset_failures()
            return True, "已解锁"
        except Exception:
            return False, self._record_failure()

    def lock(self) -> None:
        """Lock the vault and wipe keys and plaintext bookmarks from memory."""
        self._master_key = None
        self._data = None

    def reset_password_with_recovery_key(
        self, recovery_key: str, new_password: str
    ) -> tuple[bool, str]:
        """Lossless password reset using the Emergency Recovery Key (Strategy 2).

        Unwraps the Vault Master Key with the Recovery Key, re-wraps it with
        new_password, and unlocks the vault with 100% of existing bookmarks intact!
        """
        allowed, msg = self._check_rate_limit()
        if not allowed:
            return False, msg

        envelope = self._read_envelope()
        if not envelope:
            return False, "保险库尚未初始化"

        norm_rec = normalize_recovery_key(recovery_key)
        if len(norm_rec) < 8:
            return False, "请输入完整的 16 位安全急救码（形如 BK-XXXX-XXXX-XXXX-XXXX）"

        new_pwd = str(new_password or "").strip()
        if len(new_pwd) < 4:
            return False, "新主密码长度至少需要 4 个字符"

        try:
            rec_wrap = envelope.get("recovery_wrap") or {}
            rec_salt = base64.b64decode(str(rec_wrap.get("salt") or ""))
            rec_kek = _derive_key(norm_rec, rec_salt)
            master_key = aead_decrypt(rec_kek, rec_wrap.get("box") or {})
            raw_payload = aead_decrypt(master_key, envelope.get("vault_box") or {})
            data = json.loads(raw_payload.decode("utf-8"))
        except Exception:
            return False, self._record_failure()

        # Re-wrap the SAME master_key with the new password -> zero data loss!
        new_pwd_salt = os.urandom(16)
        new_pwd_kek = _derive_key(new_pwd, new_pwd_salt)
        envelope["password_wrap"] = {
            "salt": base64.b64encode(new_pwd_salt).decode("ascii"),
            "box": aead_encrypt(new_pwd_kek, master_key),
        }
        envelope["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._write_envelope(envelope)

        self._master_key = master_key
        self._data = data
        self._reset_failures()
        return True, "密码重置成功！您的所有历史书签均已完整无损保留。"

    def change_password(self, old_password: str, new_password: str) -> tuple[bool, str]:
        """Change the master password after verifying old_password."""
        envelope = self._read_envelope()
        if not envelope:
            return False, "保险库尚未初始化"

        new_pwd = str(new_password or "").strip()
        if len(new_pwd) < 4:
            return False, "新主密码长度至少需要 4 个字符"

        try:
            pwd_wrap = envelope.get("password_wrap") or {}
            pwd_salt = base64.b64decode(str(pwd_wrap.get("salt") or ""))
            pwd_kek = _derive_key(str(old_password or "").strip(), pwd_salt)
            master_key = aead_decrypt(pwd_kek, pwd_wrap.get("box") or {})
        except Exception:
            return False, "原主密码验证失败"

        new_pwd_salt = os.urandom(16)
        new_pwd_kek = _derive_key(new_pwd, new_pwd_salt)
        envelope["password_wrap"] = {
            "salt": base64.b64encode(new_pwd_salt).decode("ascii"),
            "box": aead_encrypt(new_pwd_kek, master_key),
        }
        envelope["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._write_envelope(envelope)
        return True, "主密码已更新，所有书签数据均保持加密无损状态"

    def regenerate_recovery_key(self, master_password: str) -> tuple[bool, str]:
        """Verify master_password and issue a brand-new Emergency Recovery Key."""
        envelope = self._read_envelope()
        if not envelope:
            return False, "保险库尚未初始化"

        try:
            pwd_wrap = envelope.get("password_wrap") or {}
            pwd_salt = base64.b64decode(str(pwd_wrap.get("salt") or ""))
            pwd_kek = _derive_key(str(master_password or "").strip(), pwd_salt)
            master_key = aead_decrypt(pwd_kek, pwd_wrap.get("box") or {})
        except Exception:
            return False, "主密码验证失败，无法生成新急救码"

        new_recovery_key = generate_recovery_key()
        norm_rec = normalize_recovery_key(new_recovery_key)
        rec_salt = os.urandom(16)
        rec_kek = _derive_key(norm_rec, rec_salt)
        envelope["recovery_wrap"] = {
            "salt": base64.b64encode(rec_salt).decode("ascii"),
            "box": aead_encrypt(rec_kek, master_key),
        }
        envelope["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._write_envelope(envelope)
        return True, new_recovery_key


    # ── Category & Bookmark CRUD ────────────────────────────────────────────
    def _require_unlocked(self) -> dict[str, Any]:
        if not self.is_unlocked() or self._data is None:
            raise RuntimeError("请先解锁灵动书签保险库")
        return self._data

    @staticmethod
    def _ensure_bookmark_orders(data: dict[str, Any]) -> bool:
        """Ensure every bookmark in data['bookmarks'] has a deterministic integer 'order'."""
        bms = data.get("bookmarks")
        if not isinstance(bms, list) or not bms:
            return False
        missing = [b for b in bms if "order" not in b or b.get("order") is None]
        if not missing:
            return False
        if len(missing) == len(bms):
            # Legacy vault without 'order': preserve exact legacy display order
            indexed = list(enumerate(bms))
            indexed.sort(
                key=lambda pair: (
                    0 if pair[1].get("pinned") else 1,
                    -int(pair[1].get("updatedAt") or pair[1].get("createdAt") or 0),
                    pair[0],
                )
            )
            for new_order, (_, bm) in enumerate(indexed):
                bm["order"] = new_order
            data["bookmarks"] = [bm for _, bm in indexed]
        else:
            max_order = max(
                (int(b["order"]) for b in bms if "order" in b and b.get("order") is not None),
                default=-1,
            )
            for offset, bm in enumerate(missing, start=1):
                bm["order"] = max_order + offset
        return True

    def get_categories(self) -> list[dict[str, Any]]:
        data = self._require_unlocked()
        return copy.deepcopy(data.get("categories") or [])

    def get_bookmarks(
        self,
        category_id: str | None = None,
        search_query: str = "",
    ) -> list[dict[str, Any]]:
        data = self._require_unlocked()
        self._ensure_bookmark_orders(data)
        items = list(data.get("bookmarks") or [])
        if category_id and category_id != "all":
            items = [b for b in items if b.get("categoryId") == category_id]
        q = str(search_query or "").strip().lower()
        if q:
            items = [
                b for b in items
                if q in str(b.get("title") or "").lower()
                or q in str(b.get("url") or "").lower()
                or q in str(b.get("note") or "").lower()
            ]
        # Sort pinned first, then by custom drag order ascending (Blink storage.js style)
        items.sort(
            key=lambda b: (
                0 if b.get("pinned") else 1,
                int(b.get("order", 0)),
            )
        )
        return copy.deepcopy(items)

    def add_category(self, name: str, color: str = "indigo") -> dict[str, Any]:
        data = self._require_unlocked()
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("分类名称不能为空")
        color_key = color if color in CATEGORY_COLORS else "indigo"
        cat = {
            "id": f"cat_{uuid.uuid4().hex[:8]}",
            "name": clean_name[:32],
            "color": color_key,
        }
        data.setdefault("categories", []).append(cat)
        self._save_unlocked_data()
        return copy.deepcopy(cat)

    def update_category(self, category_id: str, name: str, color: str) -> bool:
        data = self._require_unlocked()
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("分类名称不能为空")
        color_key = color if color in CATEGORY_COLORS else "indigo"
        for cat in data.get("categories") or []:
            if cat.get("id") == category_id:
                cat["name"] = clean_name[:32]
                cat["color"] = color_key
                self._save_unlocked_data()
                return True
        return False

    def delete_category(self, category_id: str, delete_bookmarks: bool = False) -> bool:
        data = self._require_unlocked()
        cats = data.get("categories") or []
        if len(cats) <= 1:
            raise ValueError("至少需要保留一个书签分类")
        remaining = [c for c in cats if c.get("id") != category_id]
        if len(remaining) == len(cats):
            return False
        data["categories"] = remaining
        fallback_cat_id = remaining[0]["id"]
        if delete_bookmarks:
            data["bookmarks"] = [
                b for b in (data.get("bookmarks") or [])
                if b.get("categoryId") != category_id
            ]
        else:
            for b in data.get("bookmarks") or []:
                if b.get("categoryId") == category_id:
                    b["categoryId"] = fallback_cat_id
        self._save_unlocked_data()
        return True

    def reorder_categories(self, ordered_category_ids: list[str]) -> bool:
        """Reorder categories to match ordered_category_ids while preserving all categories."""
        data = self._require_unlocked()
        cats = list(data.get("categories") or [])
        if len(cats) <= 1:
            return False
        by_id = {str(c.get("id")): c for c in cats}
        new_cats: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cid in ordered_category_ids:
            scid = str(cid)
            if scid in by_id and scid not in seen:
                new_cats.append(by_id[scid])
                seen.add(scid)
        for c in cats:
            scid = str(c.get("id"))
            if scid not in seen:
                new_cats.append(c)
                seen.add(scid)
        data["categories"] = new_cats
        self._save_unlocked_data()
        return True

    def move_category_to_index(self, category_id: str, target_index: int) -> bool:
        """Move a single category to target_index (0-based) in the categories list."""
        data = self._require_unlocked()
        cats = list(data.get("categories") or [])
        cur_idx = next((i for i, c in enumerate(cats) if c.get("id") == category_id), -1)
        if cur_idx < 0:
            return False
        clamped = max(0, min(len(cats) - 1, int(target_index)))
        if cur_idx == clamped:
            return False
        item = cats.pop(cur_idx)
        cats.insert(clamped, item)
        data["categories"] = cats
        self._save_unlocked_data()
        return True

    def move_bookmark_to_category(
        self, bookmark_id: str, target_category_id: str
    ) -> dict[str, Any] | None:
        """Move a bookmark into target_category_id and return the updated bookmark dict."""
        data = self._require_unlocked()
        valid_ids = {str(c.get("id")) for c in (data.get("categories") or [])}
        if target_category_id not in valid_ids:
            return None
        for bm in data.get("bookmarks") or []:
            if bm.get("id") == bookmark_id:
                bm["categoryId"] = target_category_id
                bm["updatedAt"] = int(time.time() * 1000)
                self._save_unlocked_data()
                return dict(bm)
        return None

    def add_bookmark(
        self,
        title: str,
        url: str,
        category_id: str = "",
        note: str = "",
        pinned: bool = False,
    ) -> dict[str, Any]:
        data = self._require_unlocked()
        self._ensure_bookmark_orders(data)
        norm_url = normalize_bookmark_url(url)
        clean_title = str(title or "").strip()
        if not clean_title:
            parsed = urllib.parse.urlsplit(norm_url)
            clean_title = parsed.hostname or norm_url
        cats = data.get("categories") or []
        if not cats:
            default_cat = self.add_category("高频常用", "indigo")
            cats = [default_cat]
        valid_cat_ids = {c.get("id") for c in cats}
        target_cat = category_id if category_id in valid_cat_ids else cats[0]["id"]
        now_ms = int(time.time() * 1000)
        bms = data.setdefault("bookmarks", [])
        min_order = min((int(b.get("order", 0)) for b in bms), default=0)
        bm = {
            "id": f"bm_{uuid.uuid4().hex[:10]}",
            "title": clean_title[:120],
            "url": norm_url,
            "note": str(note or "").strip()[:300],
            "categoryId": target_cat,
            "pinned": bool(pinned),
            "order": min_order - 1,
            "createdAt": now_ms,
            "updatedAt": now_ms,
        }
        bms.insert(0, bm)
        bms.sort(key=lambda b: (0 if b.get("pinned") else 1, int(b.get("order", 0))))
        for idx, item in enumerate(bms):
            item["order"] = idx
        self._save_unlocked_data()
        return copy.deepcopy(bm)

    def update_bookmark(
        self,
        bookmark_id: str,
        title: str,
        url: str,
        category_id: str,
        note: str = "",
        pinned: bool | None = None,
    ) -> bool:
        data = self._require_unlocked()
        self._ensure_bookmark_orders(data)
        norm_url = normalize_bookmark_url(url)
        clean_title = str(title or "").strip() or norm_url
        for bm in data.get("bookmarks") or []:
            if bm.get("id") == bookmark_id:
                bm["title"] = clean_title[:120]
                bm["url"] = norm_url
                if category_id:
                    bm["categoryId"] = category_id
                bm["note"] = str(note or "").strip()[:300]
                if pinned is not None:
                    bm["pinned"] = bool(pinned)
                bm["updatedAt"] = int(time.time() * 1000)
                self._save_unlocked_data()
                return True
        return False

    def delete_bookmark(self, bookmark_id: str) -> bool:
        data = self._require_unlocked()
        old_list = data.get("bookmarks") or []
        new_list = [b for b in old_list if b.get("id") != bookmark_id]
        if len(new_list) == len(old_list):
            return False
        data["bookmarks"] = new_list
        self._save_unlocked_data()
        return True

    def toggle_pin_bookmark(self, bookmark_id: str) -> bool:
        data = self._require_unlocked()
        self._ensure_bookmark_orders(data)
        for bm in data.get("bookmarks") or []:
            if bm.get("id") == bookmark_id:
                bm["pinned"] = not bool(bm.get("pinned"))
                bm["updatedAt"] = int(time.time() * 1000)
                self._save_unlocked_data()
                return True
        return False

    def move_bookmark_to_top(self, bookmark_id: str) -> bool:
        data = self._require_unlocked()
        self._ensure_bookmark_orders(data)
        bms = data.get("bookmarks") or []
        for idx, bm in enumerate(bms):
            if bm.get("id") == bookmark_id:
                min_order = min((int(b.get("order", 0)) for b in bms), default=0)
                bm["order"] = min_order - 1
                bm["updatedAt"] = int(time.time() * 1000) + 1
                bms.sort(key=lambda b: (0 if b.get("pinned") else 1, int(b.get("order", 0))))
                for i, item in enumerate(bms):
                    item["order"] = i
                self._save_unlocked_data()
                return True
        return False

    def reorder_bookmarks(
        self,
        ordered_bookmark_ids: list[str],
        moved_bookmark_id: str | None = None,
        target_category_id: str | None = None,
    ) -> bool:
        """Reorder bookmarks (full list or category subset) and sync pinned boundary.

        Mirrors dedeyuyu/Blink's reorderBookmarks + moveBookmarkOrderAndCategory in storage.js.
        """
        data = self._require_unlocked()
        self._ensure_bookmark_orders(data)
        bms = list(data.get("bookmarks") or [])
        if not bms or not ordered_bookmark_ids:
            return False
        bm_map = {str(b.get("id")): b for b in bms}
        str_ordered = [str(bid) for bid in ordered_bookmark_ids if str(bid) in bm_map]
        if not str_ordered:
            return False

        if target_category_id and moved_bookmark_id and str(moved_bookmark_id) in bm_map:
            valid_cats = {str(c.get("id")) for c in (data.get("categories") or [])}
            if str(target_category_id) in valid_cats:
                bm_map[str(moved_bookmark_id)]["categoryId"] = str(target_category_id)
                bm_map[str(moved_bookmark_id)]["updatedAt"] = int(time.time() * 1000)

        # Auto-sync pinned status if moved_bookmark_id crossed the pinned/unpinned boundary
        if moved_bookmark_id and str(moved_bookmark_id) in bm_map:
            mid = str(moved_bookmark_id)
            target = bm_map[mid]
            if mid in str_ordered:
                new_idx = str_ordered.index(mid)
                after_ids = str_ordered[new_idx + 1 :]
                before_ids = str_ordered[:new_idx]
                has_pinned_after = any(
                    bool(bm_map[bid].get("pinned")) for bid in after_ids if bid in bm_map
                )
                has_unpinned_before = any(
                    not bool(bm_map[bid].get("pinned")) for bid in before_ids if bid in bm_map
                )
                if has_pinned_after and not target.get("pinned"):
                    target["pinned"] = True
                    target["updatedAt"] = int(time.time() * 1000)
                elif has_unpinned_before and target.get("pinned"):
                    target["pinned"] = False
                    target["updatedAt"] = int(time.time() * 1000)

        # Full sorted list: replace subset positions in-place with str_ordered
        full_sorted = sorted(
            bms,
            key=lambda b: (0 if b.get("pinned") else 1, int(b.get("order", 0))),
        )
        subset_set = set(str_ordered)
        subset_iter = iter(str_ordered)
        merged: list[dict[str, Any]] = []
        for item in full_sorted:
            iid = str(item.get("id"))
            if iid in subset_set:
                next_id = next(subset_iter, iid)
                merged.append(bm_map[next_id])
            else:
                merged.append(item)

        for idx, item in enumerate(merged):
            item["order"] = idx
        data["bookmarks"] = merged
        self._save_unlocked_data()
        return True

    # ── Additive HTML Import & Dual-Track Export ────────────────────────────
    def import_html_additive(self, html_text: str) -> tuple[int, int]:
        """Additively import bookmarks from Chrome/Edge/Firefox Netscape Bookmark HTML.

        Never overwrites existing categories or bookmarks; skips exact duplicate
        (categoryId, url) pairs.
        Returns (added_bookmarks_count, added_categories_count).
        """
        data = self._require_unlocked()
        cats = data.setdefault("categories", [])
        bms = data.setdefault("bookmarks", [])

        cat_by_name: dict[str, str] = {
            str(c.get("name") or "").strip().lower(): str(c.get("id"))
            for c in cats
            if c.get("id")
        }
        existing_pairs: set[tuple[str, str]] = {
            (str(b.get("categoryId") or ""), str(b.get("url") or "").rstrip("/").lower())
            for b in bms
        }

        added_cats = 0
        added_bms = 0
        current_folder = "导入的书签"

        def _ensure_category(folder_name: str) -> str:
            nonlocal added_cats
            clean = str(folder_name or "导入的书签").strip()[:32] or "导入的书签"
            key = clean.lower()
            if key in cat_by_name:
                return cat_by_name[key]
            color = COLOR_KEYS[len(cats) % len(COLOR_KEYS)]
            new_cat = {
                "id": f"cat_{uuid.uuid4().hex[:8]}",
                "name": clean,
                "color": color,
            }
            cats.append(new_cat)
            cat_by_name[key] = new_cat["id"]
            added_cats += 1
            return new_cat["id"]

        token_pattern = re.compile(
            r"<H3[^>]*>(.*?)</H3>|<A\s+([^>]*?)>(.*?)</A>",
            re.IGNORECASE | re.DOTALL,
        )
        href_pattern = re.compile(r'HREF\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
        note_pattern = re.compile(r'DATA-BLINK-NOTE\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
        pin_pattern = re.compile(r'DATA-BLINK-PINNED\s*=\s*["\']1["\']', re.IGNORECASE)

        now_ms = int(time.time() * 1000)
        for match in token_pattern.finditer(str(html_text or "")):
            h3_inner, a_attrs, a_inner = match.groups()
            if h3_inner is not None:
                folder_title = _unescape_html(re.sub(r"<[^>]+>", "", h3_inner)).strip()
                if folder_title and folder_title.lower() not in (
                    "bookmarks", "书签栏", "收藏夹栏", "bookmarks bar", "other bookmarks", "其他书签"
                ):
                    current_folder = folder_title
                continue

            if a_attrs is not None:
                href_m = href_pattern.search(a_attrs)
                if not href_m:
                    continue
                raw_href = _unescape_html(href_m.group(1)).strip()
                try:
                    norm_url = normalize_bookmark_url(raw_href)
                except ValueError:
                    continue
                title_text = _unescape_html(re.sub(r"<[^>]+>", "", a_inner or "")).strip()
                if not title_text:
                    title_text = urllib.parse.urlsplit(norm_url).hostname or norm_url

                note_m = note_pattern.search(a_attrs)
                note_text = _unescape_html(note_m.group(1)).strip() if note_m else ""
                is_pinned = bool(pin_pattern.search(a_attrs))

                cat_id = _ensure_category(current_folder)
                dedup_key = (cat_id, norm_url.rstrip("/").lower())
                if dedup_key in existing_pairs:
                    continue
                existing_pairs.add(dedup_key)
                bms.append(
                    {
                        "id": f"bm_{uuid.uuid4().hex[:10]}",
                        "title": title_text[:120],
                        "url": norm_url,
                        "note": note_text[:300],
                        "categoryId": cat_id,
                        "pinned": is_pinned,
                        "createdAt": now_ms + added_bms,
                        "updatedAt": now_ms + added_bms,
                    }
                )
                added_bms += 1

        if added_bms > 0 or added_cats > 0:
            self._ensure_bookmark_orders(data)
            self._save_unlocked_data()
        return added_bms, added_cats

    def import_clipboard_batches(
        self,
        batches: list[dict[str, Any]],
        skip_duplicates: bool = True,
    ) -> tuple[int, int, str]:
        """Batch-import bookmarks parsed from Google Sheets / Excel / Clipboard.

        batches: list of {"category_id": str | None, "category_name": str | None, "items": [{"title": str, "url": str, "note": str}]}
        Returns (added_bookmarks_count, added_categories_count, first_target_category_id).
        """
        data = self._require_unlocked()
        self._ensure_bookmark_orders(data)
        cats = data.setdefault("categories", [])
        bms = data.setdefault("bookmarks", [])

        cat_by_id: dict[str, dict[str, Any]] = {
            str(c.get("id")): c for c in cats if c.get("id")
        }
        cat_by_name: dict[str, str] = {
            str(c.get("name") or "").strip().lower(): str(c.get("id"))
            for c in cats
            if c.get("id")
        }
        existing_pairs: set[tuple[str, str]] = {
            (str(b.get("categoryId") or ""), str(b.get("url") or "").rstrip("/").lower())
            for b in bms
        }

        max_order = max((int(b.get("order", 0)) for b in bms), default=-1)
        added_cats = 0
        added_bms = 0
        first_cat_id = ""
        now_ms = int(time.time() * 1000)

        def _resolve_cat_id(cid: str | None, cname: str | None) -> str:
            nonlocal added_cats
            if cid and str(cid) in cat_by_id:
                return str(cid)
            clean = str(cname or "导入的书签").strip()[:32] or "导入的书签"
            key = clean.lower()
            if key in cat_by_name:
                return cat_by_name[key]
            color = COLOR_KEYS[len(cats) % len(COLOR_KEYS)]
            new_cat = {
                "id": f"cat_{uuid.uuid4().hex[:8]}",
                "name": clean,
                "color": color,
            }
            cats.append(new_cat)
            cat_by_id[new_cat["id"]] = new_cat
            cat_by_name[key] = new_cat["id"]
            added_cats += 1
            return new_cat["id"]

        for batch in batches or []:
            items = batch.get("items") or []
            if not items:
                continue
            target_cid = _resolve_cat_id(batch.get("category_id"), batch.get("category_name"))
            if not first_cat_id:
                first_cat_id = target_cid
            for raw_item in items:
                raw_url = str(raw_item.get("url") or "").strip()
                if not raw_url:
                    continue
                try:
                    norm_url = normalize_bookmark_url(raw_url)
                except ValueError:
                    continue
                dedup_key = (target_cid, norm_url.rstrip("/").lower())
                if skip_duplicates and dedup_key in existing_pairs:
                    continue
                existing_pairs.add(dedup_key)
                title_text = str(raw_item.get("title") or "").strip()
                if not title_text:
                    title_text = urllib.parse.urlsplit(norm_url).hostname or norm_url
                note_text = str(raw_item.get("note") or "").strip()
                max_order += 1
                bms.append(
                    {
                        "id": f"bm_{uuid.uuid4().hex[:10]}",
                        "title": title_text[:120],
                        "url": norm_url,
                        "note": note_text[:300],
                        "categoryId": target_cid,
                        "pinned": False,
                        "order": max_order,
                        "createdAt": now_ms + added_bms,
                        "updatedAt": now_ms + added_bms,
                    }
                )
                added_bms += 1

        if added_bms > 0 or added_cats > 0:
            self._ensure_bookmark_orders(data)
            self._save_unlocked_data()
        return added_bms, added_cats, first_cat_id

    def export_html(self) -> str:
        """Export all categories and bookmarks to standard Netscape Bookmark HTML format."""
        data = self._require_unlocked()
        self._ensure_bookmark_orders(data)
        cats = data.get("categories") or []
        bms = sorted(
            list(data.get("bookmarks") or []),
            key=lambda b: (0 if b.get("pinned") else 1, int(b.get("order", 0))),
        )
        now_ts = int(time.time())

        lines = [
            "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
            "<!-- This is an automatically generated file.",
            "     It will be read and overwritten.",
            "     DO NOT EDIT! -->",
            '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
            "<TITLE>Clock/Alarm · 灵动书签导出备份</TITLE>",
            "<H1>灵动书签 (Blink Bookmarks)</H1>",
            "<DL><p>",
        ]

        by_cat: dict[str, list[dict[str, Any]]] = {}
        for bm in bms:
            cid = str(bm.get("categoryId") or "")
            by_cat.setdefault(cid, []).append(bm)

        for cat in cats:
            cid = str(cat.get("id") or "")
            cname = _escape_html(str(cat.get("name") or "未命名分类"))
            ccolor = _escape_html(str(cat.get("color") or "indigo"))
            lines.append(
                f'    <DT><H3 ADD_DATE="{now_ts}" LAST_MODIFIED="{now_ts}" DATA-BLINK-COLOR="{ccolor}">{cname}</H3>'
            )
            lines.append("    <DL><p>")
            for bm in by_cat.pop(cid, []):
                url = _escape_html(str(bm.get("url") or ""))
                title = _escape_html(str(bm.get("title") or url))
                note = _escape_html(str(bm.get("note") or ""))
                pinned = "1" if bm.get("pinned") else "0"
                add_date = int((bm.get("createdAt") or (now_ts * 1000)) // 1000)
                extra = f' DATA-BLINK-PINNED="{pinned}"'
                if note:
                    extra += f' DATA-BLINK-NOTE="{note}"'
                lines.append(
                    f'        <DT><A HREF="{url}" ADD_DATE="{add_date}"{extra}>{title}</A>'
                )
            lines.append("    </DL><p>")

        # Any orphan bookmarks whose categoryId wasn't in cats
        if by_cat:
            lines.append(f'    <DT><H3 ADD_DATE="{now_ts}">未分类书签</H3>')
            lines.append("    <DL><p>")
            for orphan_list in by_cat.values():
                for bm in orphan_list:
                    url = _escape_html(str(bm.get("url") or ""))
                    title = _escape_html(str(bm.get("title") or url))
                    lines.append(f'        <DT><A HREF="{url}" ADD_DATE="{now_ts}">{title}</A>')
            lines.append("    </DL><p>")

        lines.append("</DL><p>")
        return "\n".join(lines) + "\n"

    def export_encrypted_backup(self, dest_path: Path | str) -> Path:
        """Export the full encrypted vault envelope (.blinkbak) for lossless migration."""
        envelope = self._read_envelope()
        if not envelope:
            raise RuntimeError("保险库尚未初始化，无法导出加密备份")
        target = Path(dest_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_doc = copy.deepcopy(envelope)
        backup_doc["exported_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        backup_doc["app"] = "ClockAlarm.BlinkVault"
        target.write_text(json.dumps(backup_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def import_encrypted_backup(
        self, src_path: Path | str, secret_password_or_recovery: str
    ) -> tuple[int, int]:
        """Decrypt an external .blinkbak encrypted backup using its password or recovery key,
        and merge its categories and bookmarks additively into the current vault (or initialize if empty).
        Returns (added_bookmarks_count, added_categories_count).
        """
        source = Path(src_path)
        if not source.is_file():
            raise FileNotFoundError(f"找不到备份文件: {source}")
        ext_env = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(ext_env, dict) or "vault_box" not in ext_env:
            raise ValueError("不是有效的灵动书签加密备份包 (.blinkbak)")

        secret = str(secret_password_or_recovery or "").strip()
        if not secret:
            raise ValueError("请输入备份包的解密密码或安全急救码")

        ext_master_key: bytes | None = None
        # Try password unwrap first
        try:
            pw_wrap = ext_env.get("password_wrap") or {}
            pw_salt = base64.b64decode(str(pw_wrap.get("salt") or ""))
            pw_kek = _derive_key(secret, pw_salt)
            ext_master_key = aead_decrypt(pw_kek, pw_wrap.get("box") or {})
        except Exception:
            ext_master_key = None

        # Try recovery key unwrap if password didn't match
        if ext_master_key is None:
            try:
                rec_wrap = ext_env.get("recovery_wrap") or {}
                rec_salt = base64.b64decode(str(rec_wrap.get("salt") or ""))
                rec_kek = _derive_key(normalize_recovery_key(secret), rec_salt)
                ext_master_key = aead_decrypt(rec_kek, rec_wrap.get("box") or {})
            except Exception as exc:
                raise ValueError("备份包密码或安全急救码不正确，无法解密") from exc

        raw_payload = aead_decrypt(ext_master_key, ext_env.get("vault_box") or {})
        ext_data = json.loads(raw_payload.decode("utf-8"))
        if not isinstance(ext_data, dict):
            raise ValueError("备份包内容损坏")

        data = self._require_unlocked()
        cats = data.setdefault("categories", [])
        bms = data.setdefault("bookmarks", [])

        cat_by_name = {
            str(c.get("name") or "").strip().lower(): str(c.get("id"))
            for c in cats
            if c.get("id")
        }
        ext_cat_id_map: dict[str, str] = {}
        added_cats = 0
        for ext_cat in ext_data.get("categories") or []:
            cname = str(ext_cat.get("name") or "导入分类").strip()
            ckey = cname.lower()
            if ckey in cat_by_name:
                ext_cat_id_map[str(ext_cat.get("id"))] = cat_by_name[ckey]
            else:
                new_id = f"cat_{uuid.uuid4().hex[:8]}"
                color = str(ext_cat.get("color") or "indigo")
                if color not in CATEGORY_COLORS:
                    color = "indigo"
                cats.append({"id": new_id, "name": cname[:32], "color": color})
                cat_by_name[ckey] = new_id
                ext_cat_id_map[str(ext_cat.get("id"))] = new_id
                added_cats += 1

        existing_pairs = {
            (str(b.get("categoryId") or ""), str(b.get("url") or "").rstrip("/").lower())
            for b in bms
        }
        added_bms = 0
        fallback_cid = cats[0]["id"] if cats else "cat_frequent"
        for ext_bm in ext_data.get("bookmarks") or []:
            try:
                norm_url = normalize_bookmark_url(str(ext_bm.get("url") or ""))
            except ValueError:
                continue
            target_cid = ext_cat_id_map.get(str(ext_bm.get("categoryId")), fallback_cid)
            dedup_key = (target_cid, norm_url.rstrip("/").lower())
            if dedup_key in existing_pairs:
                continue
            existing_pairs.add(dedup_key)
            bms.append(
                {
                    "id": f"bm_{uuid.uuid4().hex[:10]}",
                    "title": str(ext_bm.get("title") or norm_url)[:120],
                    "url": norm_url,
                    "note": str(ext_bm.get("note") or "")[:300],
                    "categoryId": target_cid,
                    "pinned": bool(ext_bm.get("pinned")),
                    "createdAt": int(ext_bm.get("createdAt") or time.time() * 1000),
                    "updatedAt": int(ext_bm.get("updatedAt") or time.time() * 1000),
                }
            )
            added_bms += 1

        if added_bms > 0 or added_cats > 0:
            self._save_unlocked_data()
        return added_bms, added_cats

def _unwrap_google_redirect_url(raw_url: str) -> str:
    """Unwrap Google Sheets / Docs redirect URLs (https://www.google.com/url?q=...)."""
    s = str(raw_url or "").strip()
    if not s:
        return s
    try:
        parsed = urllib.parse.urlsplit(s)
        host = (parsed.hostname or "").lower()
        if host in ("www.google.com", "google.com") and parsed.path == "/url":
            qs = urllib.parse.parse_qs(parsed.query)
            for key in ("q", "url"):
                if key in qs and qs[key]:
                    cand = str(qs[key][0] or "").strip()
                    if cand.startswith(("http://", "https://")):
                        return cand
    except Exception:
        pass
    return s


def _clean_html_fragment_text(fragment: str) -> str:
    """Strip style/script/tags from an HTML fragment and return collapsed plain text."""
    s = str(fragment or "")
    s = re.sub(r"<style[^>]*>.*?</style>", "", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<script[^>]*>.*?</script>", "", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = _unescape_html(s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_links_from_plain_cell(cell_text: str) -> list[dict[str, str]]:
    """Extract (title, url) from a plain-text cell (supports =HYPERLINK formula, 'Title https://...', or bare URLs)."""
    text = str(cell_text or "").strip()
    if not text:
        return []

    # 1. Check Excel/Sheets =HYPERLINK("url", "label") formula
    m_hyp = re.match(
        r'^=\s*HYPERLINK\s*\(\s*["\']([^"\']+)["\']\s*[,;]\s*["\']([^"\']*)["\']\s*\)$',
        text,
        flags=re.IGNORECASE,
    )
    if m_hyp:
        raw_u, raw_lbl = m_hyp.group(1), m_hyp.group(2)
        try:
            norm_u = normalize_bookmark_url(_unwrap_google_redirect_url(raw_u))
            lbl = raw_lbl.strip() or extract_domain_label(norm_u)
            return [{"title": lbl, "url": norm_u, "note": ""}]
        except ValueError:
            pass

    # 2. Check explicit http:// or https:// URLs embedded in text
    url_matches = list(re.finditer(r"https?://[^\s<>\"']+", text, flags=re.IGNORECASE))
    if url_matches:
        if len(url_matches) == 1:
            m = url_matches[0]
            raw_u = m.group(0).rstrip("),.;]}>")
            try:
                norm_u = normalize_bookmark_url(_unwrap_google_redirect_url(raw_u))
                leftover = (text[: m.start()] + " " + text[m.end() :]).strip(" -|·:：()\t")
                title = leftover if leftover else extract_domain_label(norm_u)
                return [{"title": title, "url": norm_u, "note": ""}]
            except ValueError:
                pass
        else:
            out: list[dict[str, str]] = []
            for m in url_matches:
                raw_u = m.group(0).rstrip("),.;]}>")
                try:
                    norm_u = normalize_bookmark_url(_unwrap_google_redirect_url(raw_u))
                    out.append({"title": extract_domain_label(norm_u), "url": norm_u, "note": ""})
                except ValueError:
                    continue
            if out:
                return out

    # 3. Check bare domain URL (e.g. "www.google.com" or "github.com/openai" with no spaces)
    if " " not in text and re.match(
        r"^(?:www\.[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+|[a-zA-Z0-9-]+\.(?:com|cn|net|org|io|ai|dev|app|co|me|tv|cc|xyz|info|edu|gov|hk|tw|jp|uk|de|fr))(?:[/:?#][^\s]*)?$",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            norm_u = normalize_bookmark_url(text)
            return [{"title": extract_domain_label(norm_u), "url": norm_u, "note": ""}]
        except ValueError:
            pass

    return []


def parse_clipboard_spreadsheet(html_text: str = "", plain_text: str = "") -> dict[str, Any]:
    """Parse Google Sheets / Excel / HTML / TSV clipboard content into bookmark batches.

    Supports both:
    - Scenario 1 ('single_category'): Copy 1 or more cells (e.g. 100 hyperlinks) and paste into a chosen folder.
    - Scenario 2 ('matrix_headers'): Copy multi-column table A-Z where Row 1 has Category Folder names
      and Row 2..N has hyperlinks under each column.
    """
    html_s = str(html_text or "").strip()
    plain_s = str(plain_text or "").strip()
    max_input_len = 10_000_000  # Cap clipboard payload to 10MB to mitigate ReDoS / memory spikes
    if len(html_s) > max_input_len:
        html_s = html_s[:max_input_len]
    if len(plain_s) > max_input_len:
        plain_s = plain_s[:max_input_len]

    grid: list[list[dict[str, Any]]] = []

    # ── Path A: HTML Table (Google Sheets / Excel / Browser Table) ──────────
    tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    td_pattern = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
    a_pattern = re.compile(r"<a\s+([^>]*?)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
    href_pattern = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
    sheets_link_pattern = re.compile(
        r'data-sheets-hyperlink\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE
    )
    colspan_pattern = re.compile(r'colspan\s*=\s*["\']?(\d+)', re.IGNORECASE)

    if html_s and "<tr" in html_s.lower():
        for tr_m in tr_pattern.finditer(html_s):
            tr_inner = tr_m.group(1)
            row_cells: list[dict[str, Any]] = []
            for td_m in td_pattern.finditer(tr_inner):
                td_attrs, td_inner = td_m.groups()
                colspan = 1
                cs_m = colspan_pattern.search(td_attrs or "")
                if cs_m:
                    try:
                        colspan = max(1, min(50, int(cs_m.group(1))))
                    except Exception:
                        colspan = 1

                cell_text = _clean_html_fragment_text(td_inner)
                cell_links: list[dict[str, str]] = []

                # 1) Standard <a href="..."> tags inside cell
                a_matches = list(a_pattern.finditer(td_inner))
                if a_matches:
                    for a_idx, am in enumerate(a_matches):
                        a_attrs, a_inner = am.groups()
                        hm = href_pattern.search(a_attrs or "")
                        if not hm:
                            hm = sheets_link_pattern.search(a_attrs or "")
                        if not hm:
                            continue
                        raw_href = _unwrap_google_redirect_url(_unescape_html(hm.group(1)).strip())
                        try:
                            norm_u = normalize_bookmark_url(raw_href)
                        except ValueError:
                            continue
                        a_lbl = _clean_html_fragment_text(a_inner)
                        if len(a_matches) == 1 and cell_text:
                            lbl = cell_text
                        else:
                            lbl = a_lbl or cell_text or extract_domain_label(norm_u)
                        if lbl.rstrip("/").lower() in (
                            norm_u.rstrip("/").lower(),
                            raw_href.rstrip("/").lower(),
                        ):
                            lbl = a_lbl or extract_domain_label(norm_u)
                        cell_links.append({"title": lbl[:120], "url": norm_u, "note": ""})

                # 2) Google Sheets data-sheets-hyperlink on <td> or inner <span> without <a>
                if not cell_links:
                    sm = sheets_link_pattern.search(td_attrs or "") or sheets_link_pattern.search(
                        td_inner or ""
                    )
                    if sm:
                        raw_href = _unwrap_google_redirect_url(_unescape_html(sm.group(1)).strip())
                        try:
                            norm_u = normalize_bookmark_url(raw_href)
                            lbl = cell_text or extract_domain_label(norm_u)
                            cell_links.append({"title": lbl[:120], "url": norm_u, "note": ""})
                        except ValueError:
                            pass

                # 3) Plain URL text inside <td>
                if not cell_links and cell_text:
                    cell_links = _extract_links_from_plain_cell(cell_text)

                row_cells.append({"text": cell_text, "links": cell_links})
                for _ in range(colspan - 1):
                    row_cells.append({"text": "", "links": []})
            if row_cells:
                grid.append(row_cells)

    # ── Path B: Non-table HTML with <a href="..."> links ────────────────────
    if not grid and html_s and "<a" in html_s.lower():
        for am in a_pattern.finditer(html_s):
            a_attrs, a_inner = am.groups()
            hm = href_pattern.search(a_attrs or "")
            if not hm:
                continue
            raw_href = _unwrap_google_redirect_url(_unescape_html(hm.group(1)).strip())
            try:
                norm_u = normalize_bookmark_url(raw_href)
            except ValueError:
                continue
            lbl = _clean_html_fragment_text(a_inner) or extract_domain_label(norm_u)
            item = {"title": lbl[:120], "url": norm_u, "note": ""}
            grid.append([{"text": lbl, "links": [item]}])

    # ── Path C: Plain Text / TSV / CSV fallback ─────────────────────────────
    if not grid and plain_s:
        for raw_line in plain_s.splitlines():
            if not raw_line.strip():
                continue
            if "\t" in raw_line:
                parts = raw_line.split("\t")
            else:
                parts = [raw_line]
            row_cells = []
            for part in parts:
                c_txt = part.strip()
                c_links = _extract_links_from_plain_cell(c_txt)
                row_cells.append({"text": c_txt, "links": c_links})

            # Support 2-column [Title, URL] or 3-column [Title, URL, Note] row format
            if (
                len(row_cells) >= 2
                and row_cells[0]["text"]
                and not row_cells[0]["links"]
                and len(row_cells[1]["links"]) == 1
            ):
                paired_link = dict(row_cells[1]["links"][0])
                paired_link["title"] = row_cells[0]["text"][:120]
                if len(row_cells) >= 3 and row_cells[2]["text"] and not row_cells[2]["links"]:
                    paired_link["note"] = row_cells[2]["text"][:300]
                row_cells[1]["links"] = [paired_link]

            grid.append(row_cells)

    if not grid:
        return {
            "has_data": False,
            "total_links": 0,
            "recommended_mode": "single_category",
            "flat_items": [],
            "header_columns": [],
        }

    num_cols = max((len(r) for r in grid), default=0)

    # 1. Build flat_items (preserving natural reading/column order)
    flat_items: list[dict[str, str]] = []
    if num_cols == 1:
        for r in grid:
            for lk in r[0]["links"]:
                flat_items.append(dict(lk))
    else:
        # Column-by-column top-to-bottom so multi-column lists stay grouped logically
        for c_idx in range(num_cols):
            for r_idx in range(len(grid)):
                if c_idx < len(grid[r_idx]):
                    for lk in grid[r_idx][c_idx]["links"]:
                        flat_items.append(dict(lk))

    # 2. Build header_columns (Row 0 = Category Name for each column A-Z, Rows 1..N = Bookmarks)
    header_columns: list[dict[str, Any]] = []
    plain_header_count = 0
    row0_link_count = 0

    if len(grid) >= 2 and num_cols >= 1:
        for c_idx in range(num_cols):
            hdr_cell = grid[0][c_idx] if c_idx < len(grid[0]) else {"text": "", "links": []}
            hdr_text = str(hdr_cell.get("text") or "").strip()
            hdr_links = hdr_cell.get("links") or []
            if hdr_links:
                row0_link_count += 1
            elif hdr_text:
                plain_header_count += 1

            col_items: list[dict[str, str]] = []
            for r_idx in range(1, len(grid)):
                if c_idx < len(grid[r_idx]):
                    for lk in grid[r_idx][c_idx]["links"]:
                        col_items.append(dict(lk))

            if col_items:
                cat_name = hdr_text[:32] if hdr_text else f"导入分组 {c_idx + 1}"
                header_columns.append(
                    {
                        "col_index": c_idx,
                        "category_name": cat_name,
                        "has_explicit_header": bool(hdr_text and not hdr_links),
                        "items": col_items,
                    }
                )

    # Recommend 'matrix_headers' when Row 0 has plain-text category headers and Row 1+ has links
    if header_columns and plain_header_count >= 1 and row0_link_count == 0:
        recommended_mode = "matrix_headers"
    else:
        recommended_mode = "single_category"

    has_data = bool(flat_items or any(col["items"] for col in header_columns))
    return {
        "has_data": has_data,
        "total_links": len(flat_items),
        "recommended_mode": recommended_mode,
        "flat_items": flat_items,
        "header_columns": header_columns,
    }


def extract_domain_label(url: str) -> str:
    """Return a clean hostname label for display (e.g. 'github.com')."""
    try:
        host = urllib.parse.urlsplit(str(url or "")).hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host or str(url or "")
    except Exception:
        return str(url or "")


_GLOBAL_VAULT_INSTANCE: BookmarksVault | None = None


def get_bookmarks_vault(vault_path: Path | str | None = None) -> BookmarksVault:
    """Return the shared singleton BookmarksVault instance."""
    global _GLOBAL_VAULT_INSTANCE
    if vault_path is not None:
        return BookmarksVault(vault_path)
    if _GLOBAL_VAULT_INSTANCE is None:
        _GLOBAL_VAULT_INSTANCE = BookmarksVault()
    return _GLOBAL_VAULT_INSTANCE
