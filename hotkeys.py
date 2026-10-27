"""Global hotkeys for the clock shell and region screenshot."""

from __future__ import annotations

import sys
from ctypes import wintypes
from typing import Callable

from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer
from PyQt6.QtWidgets import QApplication

WM_HOTKEY = 0x0312

# Standard Hotkey Mapping
HOTKEY_MAP = {
    "world_clock": 0xD001,
    "screenshot": 0xD002,
    "recorder": 0xD003,
    "todos": 0xD004,
    "notes": 0xD005,
    "media_player": 0xD006,
    "cleaner": 0xD007,
    "bookmarks": 0xD008,
}

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004


def _user32():
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.windll.user32


def parse_hotkey_combo(combo: str) -> tuple[int, int] | None:
    if not combo or not str(combo).strip():
        return None
    parts = [part.strip().upper() for part in str(combo).replace(" ", "").split("+") if part.strip()]
    modifiers = 0
    virtual_key: int | None = None
    for part in parts:
        if part in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        elif part in ("WIN", "META"):
            modifiers |= 0x0008
        elif len(part) == 1 and ("A" <= part <= "Z" or "0" <= part <= "9"):
            virtual_key = ord(part)
        elif part.startswith("F") and part[1:].isdigit():
            number = int(part[1:])
            if 1 <= number <= 24:
                virtual_key = 0x70 + number - 1
        elif part in ("PRINTSCREEN", "PRTSC"):
            virtual_key = 0x2C
        elif part == "SPACE":
            virtual_key = 0x20
    if virtual_key is None:
        return None
    return modifiers, virtual_key


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, handlers: dict[int, Callable[[], None]]) -> None:
        super().__init__()
        self.handlers = handlers

    def nativeEventFilter(self, event_type, message):
        if event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_HOTKEY:
            callback = self.handlers.get(int(msg.wParam))
            if callback:
                QTimer.singleShot(0, callback)
                return True, 0
        return False, 0


class ClockAlarmHotkeys:
    def __init__(
        self,
        callbacks: dict[str, Callable[[], None]],
        state: dict,
    ) -> None:
        self.callbacks = callbacks
        self.state = state
        self._ids: list[int] = []
        self._handlers: dict[int, Callable[[], None]] = {}

        # Connect internal hotkey IDs to callbacks
        for key, hotkey_id in HOTKEY_MAP.items():
            cb = callbacks.get(key)
            if cb:
                self._handlers[hotkey_id] = cb

        self._filter = _Filter(self._handlers)
        app = QApplication.instance()
        if app:
            app.installNativeEventFilter(self._filter)
        self.rebuild()

    def _unregister(self) -> None:
        user32 = _user32()
        if not user32:
            return
        for hotkey_id in list(self._ids):
            try:
                user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass
        self._ids.clear()

    @staticmethod
    def _configure_api(user32) -> None:
        import ctypes

        try:
            user32.RegisterHotKey.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            user32.RegisterHotKey.restype = wintypes.BOOL
        except Exception:
            pass

    def rebuild(self) -> None:
        user32 = _user32()
        if not user32:
            return
        self._unregister()
        self._configure_api(user32)

        cfg = self.state.setdefault("hotkeys_config", {})
        if not cfg.setdefault("enabled", True):
            return

        combos = cfg.setdefault("combos", {})
        enables = cfg.setdefault("enables", {})

        defaults = {
            "world_clock": ("Ctrl+Alt+T", (MOD_CONTROL | MOD_ALT, ord("T"))),
            "screenshot": ("Ctrl+Alt+A", (MOD_CONTROL | MOD_ALT, ord("A"))),
            "recorder": ("Ctrl+Alt+R", (MOD_CONTROL | MOD_ALT, ord("R"))),
            "todos": ("Ctrl+Alt+D", (MOD_CONTROL | MOD_ALT, ord("D"))),
            "notes": ("Ctrl+Alt+N", (MOD_CONTROL | MOD_ALT, ord("N"))),
            "media_player": ("Ctrl+Alt+V", (MOD_CONTROL | MOD_ALT, ord("V"))),
            "cleaner": ("Ctrl+Alt+C", (MOD_CONTROL | MOD_ALT, ord("C"))),
            "bookmarks": ("Ctrl+Alt+B", (MOD_CONTROL | MOD_ALT, ord("B"))),
        }

        for key, hotkey_id in HOTKEY_MAP.items():
            if not enables.setdefault(key, True):
                continue
            combo = combos.setdefault(key, defaults[key][0])
            fallback = defaults[key][1]

            modifiers, virtual_key = parse_hotkey_combo(combo) or fallback
            if user32.RegisterHotKey(None, hotkey_id, int(modifiers), int(virtual_key)):
                self._ids.append(hotkey_id)

    def pause_screenshot_hotkeys(self) -> None:
        user32 = _user32()
        if not user32:
            return
        try:
            user32.UnregisterHotKey(None, HOTKEY_MAP["screenshot"])
        except Exception:
            pass
        if HOTKEY_MAP["screenshot"] in self._ids:
            self._ids.remove(HOTKEY_MAP["screenshot"])

    def resume_screenshot_hotkeys(self) -> None:
        self.rebuild()

    def rebind(self) -> str:
        self.rebuild()
        screenshot_ok = HOTKEY_MAP["screenshot"] in self._ids
        status = "成功" if screenshot_ok else "部分失败"
        return f"快捷键应用：{status}"

    def close(self) -> None:
        self._unregister()
