"""Multi-Profile Browser Detection & Smart URL Delivery Bridge (Blink Architecture).

Detects active top-level browser windows in Windows Z-order (Chrome, Edge, Brave,
Firefox, etc.), resolves Chromium User Data profiles from Local State & window
titles, and delivers bookmark URLs directly into the active browser window/profile
or a user-selected browser profile.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

from bookmarks_vault import normalize_bookmark_url

KNOWN_BROWSERS: dict[str, dict[str, str]] = {
    "msedge.exe": {
        "id": "edge",
        "name": "Microsoft Edge",
        "short": "Edge",
        "user_data_rel": r"Microsoft\Edge\User Data",
    },
    "chrome.exe": {
        "id": "chrome",
        "name": "Google Chrome",
        "short": "Chrome",
        "user_data_rel": r"Google\Chrome\User Data",
    },
    "brave.exe": {
        "id": "brave",
        "name": "Brave Browser",
        "short": "Brave",
        "user_data_rel": r"BraveSoftware\Brave-Browser\User Data",
    },
    "vivaldi.exe": {
        "id": "vivaldi",
        "name": "Vivaldi",
        "short": "Vivaldi",
        "user_data_rel": r"Vivaldi\User Data",
    },
    "firefox.exe": {
        "id": "firefox",
        "name": "Mozilla Firefox",
        "short": "Firefox",
        "user_data_rel": "",
    },
}


def _get_process_image_path(pid: int) -> str:
    """Return full executable path for a Win32 process ID using QueryFullProcessImageNameW."""
    if sys.platform != "win32" or pid <= 0:
        return ""
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h_proc:
        return ""
    try:
        buf_len = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(buf_len)):
            return buf.value
        return ""
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(h_proc)


def _safe_is_file(p: Path) -> bool:
    try:
        return p.is_file()
    except OSError:
        return False


def _safe_is_dir(p: Path) -> bool:
    try:
        return p.is_dir()
    except OSError:
        return False


def _read_chromium_profiles(user_data_dir: Path) -> tuple[list[dict[str, Any]], str]:
    """Read profile list and last_active_profile from Chromium's Local State file."""
    try:
        local_state_path = user_data_dir / "Local State"
        if not _safe_is_file(local_state_path):
            return [], "Default"
        raw = json.loads(local_state_path.read_text(encoding="utf-8", errors="replace"))
        prof_section = raw.get("profile") or {}
        info_cache = prof_section.get("info_cache") or {}
        last_active_list = prof_section.get("last_active_profiles") or []
        last_active = str(last_active_list[0]) if last_active_list else "Default"

        profiles: list[dict[str, Any]] = []
        for dir_name, meta in info_cache.items():
            if not isinstance(meta, dict):
                continue
            display_name = (
                str(meta.get("name") or "").strip()
                or str(meta.get("shortcut_name") or "").strip()
                or str(meta.get("user_name") or "").strip()
                or dir_name
            )
            profiles.append(
                {
                    "profile_dir": str(dir_name),
                    "profile_name": display_name,
                    "user_name": str(meta.get("user_name") or ""),
                    "active_time": float(meta.get("active_time") or 0.0),
                }
            )
        profiles.sort(key=lambda p: (0 if p["profile_dir"] == last_active else 1, -p["active_time"]))
        return profiles, last_active
    except Exception:
        return [], "Default"


def _match_profile_from_window_title(
    window_title: str,
    profiles: list[dict[str, Any]],
    default_profile_dir: str,
) -> tuple[str, str]:
    """Match a Chromium window title to its profile directory and friendly name."""
    if not profiles:
        return default_profile_dir, "默认配置"
    if len(profiles) == 1:
        return profiles[0]["profile_dir"], profiles[0]["profile_name"]

    # Clean zero-width chars that Edge inserts in 'Microsoft\u200b Edge'
    clean_title = window_title.replace("\u200b", "").strip()
    for p in profiles:
        pname = p["profile_name"]
        if pname and (f" - {pname} - " in clean_title or f" - {pname}" in clean_title):
            return p["profile_dir"], pname

    # Fallback to last active profile
    for p in profiles:
        if p["profile_dir"] == default_profile_dir:
            return p["profile_dir"], p["profile_name"]
    return profiles[0]["profile_dir"], profiles[0]["profile_name"]


def detect_active_browser_windows() -> list[dict[str, Any]]:
    """Enumerate visible top-level browser windows in Windows Z-order (front to back)."""
    if sys.platform != "win32":
        return []

    user32 = ctypes.windll.user32
    local_appdata = Path(os.environ.get("LOCALAPPDATA") or "")
    results: list[dict[str, Any]] = []
    profile_cache: dict[str, tuple[list[dict[str, Any]], str]] = {}

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum_cb(hwnd: int, _lparam: int) -> bool:
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)
            title = title_buf.value.strip()
            if not title:
                return True

            class_buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, class_buf, 128)
            class_name = class_buf.value

            # Chromium browsers use Chrome_WidgetWin_1; Firefox uses MozillaWindowClass
            if not (class_name.startswith("Chrome_WidgetWin_") or class_name == "MozillaWindowClass"):
                return True

            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            exe_path = _get_process_image_path(pid.value)
            if not exe_path:
                return True
            exe_name = os.path.basename(exe_path).lower()
            browser_info = KNOWN_BROWSERS.get(exe_name)
            if not browser_info:
                return True

            profile_dir = ""
            profile_name = "默认"
            rel = browser_info.get("user_data_rel") or ""
            if rel and _safe_is_dir(local_appdata):
                if exe_name not in profile_cache:
                    profile_cache[exe_name] = _read_chromium_profiles(local_appdata / rel)
                profs, last_active = profile_cache[exe_name]
                profile_dir, profile_name = _match_profile_from_window_title(title, profs, last_active)

            results.append(
                {
                    "hwnd": int(hwnd),
                    "pid": int(pid.value),
                    "exe_path": exe_path,
                    "exe_name": exe_name,
                    "browser_id": browser_info["id"],
                    "browser_name": browser_info["name"],
                    "browser_short": browser_info["short"],
                    "profile_dir": profile_dir,
                    "profile_name": profile_name,
                    "window_title": title,
                    "display_badge": (
                        f"{browser_info['short']} ({profile_name})"
                        if profile_dir
                        else browser_info["short"]
                    ),
                }
            )
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
    except Exception:
        pass
    return results


def discover_all_browser_profiles() -> list[dict[str, Any]]:
    """Discover all installed Chromium browser profiles on the machine for the selector menu."""
    local_appdata = Path(os.environ.get("LOCALAPPDATA") or "")
    active_wins = detect_active_browser_windows()
    exe_by_name: dict[str, str] = {}
    for w in active_wins:
        exe_by_name.setdefault(w["exe_name"], w["exe_path"])

    # Standard installation paths fallback
    program_files = [
        os.environ.get("ProgramFiles") or r"C:\Program Files",
        os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)",
        str(local_appdata / "Programs"),
    ]
    standard_bins = {
        "msedge.exe": r"Microsoft\Edge\Application\msedge.exe",
        "chrome.exe": r"Google\Chrome\Application\chrome.exe",
        "brave.exe": r"BraveSoftware\Brave-Browser\Application\brave.exe",
    }
    for exe_name, rel_bin in standard_bins.items():
        if exe_name not in exe_by_name:
            for pf in program_files:
                cand = Path(pf) / rel_bin
                if _safe_is_file(cand):
                    exe_by_name[exe_name] = str(cand)
                    break

    choices: list[dict[str, Any]] = []
    for exe_name, info in KNOWN_BROWSERS.items():
        exe_path = exe_by_name.get(exe_name, "")
        rel = info.get("user_data_rel") or ""
        if not exe_path or not rel:
            continue
        user_data_dir = local_appdata / rel
        profs, _ = _read_chromium_profiles(user_data_dir)
        if not profs:
            choices.append(
                {
                    "key": f"{info['id']}:Default",
                    "exe_path": exe_path,
                    "browser_short": info["short"],
                    "profile_dir": "Default",
                    "profile_name": "默认配置",
                    "label": f"{info['short']} · 默认配置",
                }
            )
        else:
            for p in profs:
                pdir = p["profile_dir"]
                pname = p["profile_name"]
                choices.append(
                    {
                        "key": f"{info['id']}:{pdir}",
                        "exe_path": exe_path,
                        "browser_short": info["short"],
                        "profile_dir": pdir,
                        "profile_name": pname,
                        "label": f"{info['short']} · {pname} ({pdir})",
                    }
                )
    return choices


def open_url_in_browser(
    raw_url: str,
    target_mode: str = "auto",
    custom_target: dict[str, Any] | None = None,
    cached_last_active: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Open URL in the target browser and profile.

    target_mode:
      - 'auto': Deliver to the most recently active browser window & profile
      - 'custom': Deliver to custom_target {'exe_path': ..., 'profile_dir': ...}
      - 'system': Open with system default browser
    """
    norm_url = normalize_bookmark_url(raw_url)

    if target_mode == "custom" and isinstance(custom_target, dict):
        exe_path = str(custom_target.get("exe_path") or "")
        profile_dir = str(custom_target.get("profile_dir") or "")
        if exe_path and _safe_is_file(Path(exe_path)):
            args = [exe_path]
            if profile_dir:
                args.append(f"--profile-directory={profile_dir}")
            args.append(norm_url)
            try:
                subprocess.Popen(args, close_fds=True)
                return True, f"已在 {custom_target.get('label') or '指定浏览器'} 中打开"
            except Exception:
                pass

    if target_mode == "auto":
        target_win = cached_last_active
        if not target_win:
            wins = detect_active_browser_windows()
            target_win = wins[0] if wins else None

        if target_win and target_win.get("exe_path") and _safe_is_file(Path(target_win["exe_path"])):
            exe_path = target_win["exe_path"]
            profile_dir = target_win.get("profile_dir") or ""
            hwnd = target_win.get("hwnd")
            if sys.platform == "win32" and hwnd:
                try:
                    ctypes.windll.user32.SetForegroundWindow(int(hwnd))
                except Exception:
                    pass
            args = [exe_path]
            if profile_dir:
                args.append(f"--profile-directory={profile_dir}")
            args.append(norm_url)
            try:
                subprocess.Popen(args, close_fds=True)
                return True, f"已投递至 {target_win.get('display_badge') or '当前浏览器'}"
            except Exception:
                pass

    # Fallback: system default browser
    webbrowser.open(norm_url)
    return True, "已在系统默认浏览器中打开"
