"""Local JSON state for Clock/Alarm (no pet data required)."""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_STATE: dict[str, Any] = {
    "app_name": "ClockAlarm",
    "prefs": {
        "theme": "dark",
        "autostart": False,
        "autostart_consent": False,
        "check_updates": True,
        "ignored_update_version": "",
        "last_update_check": 0.0,
    },
    "todo_board": {"color": "#fef08a"},
    "screenshot": {
        "save_dir": "",
        "hotkey_region": "Ctrl+Alt+A",
        "hide_windows": False,
        "gdrive": {
            "is_public": True,
            "direct_link": False,
            "use_folder": True,
            "folder_id": "",
            "credentials": {},
        },
    },
    "recorder": {},
    "cleaner": {
        "scopes": ["temp", "thumbs"],
        "scope_selection_version": 1,
    },
    "media": {
        "allow_online": True,
        "playlist_limit": 1000,
        "playlist": [],
        "favorites": [],
        "right_click_association": False,
        "subscriptions": [],
        "subscription_check_mins": 30,
        "auto_add_to_playlist": True,
        "notify_on_new_video": True,
        "seen_video_ids": [],
        "cookies_text": "",
    },
    "todos": [],
    "notes": [],
    "alarms": [],
    "timer": {},
    "bookmarks": {
        "auto_lock_on_close": False,
    },
}

_WRITE_LOCK = threading.RLock()


class JsonStore:
    def __init__(self, app_name: str = "ClockAlarm") -> None:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        configured = os.environ.get("CLOCK_ALARM_DATA_DIR", "")
        preferred = Path(configured) if configured else Path(base) / app_name
        self.directory = self._select_writable(preferred, app_name)
        self.state_path = self.directory / "state.json"
        self.log_path = self.directory / "log.json"
        self.state = self._load_state()

    @staticmethod
    def _select_writable(preferred: Path, app_name: str) -> Path:
        candidates = [preferred]
        local = os.environ.get("LOCALAPPDATA") or ""
        if local:
            candidates.append(Path(local) / app_name)
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / f"{app_name}Data")
        else:
            candidates.append(Path(__file__).resolve().parent / f"{app_name}Data")
        tmp = os.environ.get("TEMP") or str(Path.home())
        candidates.append(Path(tmp) / app_name)
        seen: set[str] = set()
        for c in candidates:
            k = str(c).lower()
            if k in seen:
                continue
            seen.add(k)
            try:
                c.mkdir(parents=True, exist_ok=True)
                probe = c / f".w{os.getpid()}"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                return c
            except OSError:
                continue
        import tempfile

        return Path(tempfile.mkdtemp(prefix=f"{app_name}-"))

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return copy.deepcopy(DEFAULT_STATE)
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return copy.deepcopy(DEFAULT_STATE)
        return self._drop_legacy_state(self._merge(saved, DEFAULT_STATE))

    @staticmethod
    def _drop_legacy_state(state: dict[str, Any]) -> dict[str, Any]:
        """Remove retired feature settings from existing user state files."""
        for key in ("p2p", "lan", "music", "pomodoro"):
            state.pop(key, None)

        prefs = state.get("prefs")
        if isinstance(prefs, dict):
            for key in (
                "float_assistant",
                "tips_enabled",
                "voice_enabled",
                "auto_check_update",
            ):
                prefs.pop(key, None)

        screenshot = state.get("screenshot")
        if isinstance(screenshot, dict):
            for key in ("auto_upload", "hotkey_full"):
                screenshot.pop(key, None)

        cleaner = state.get("cleaner")
        if isinstance(cleaner, dict):
            for key in ("speak", "bubble", "keep_log"):
                cleaner.pop(key, None)
        return state

    @staticmethod
    def _merge(value: dict, defaults: dict) -> dict:
        merged = copy.deepcopy(defaults)
        for k, item in value.items():
            if isinstance(item, dict) and isinstance(merged.get(k), dict):
                merged[k] = JsonStore._merge(item, merged[k])
            else:
                merged[k] = item
        return merged

    def save_state(self) -> None:
        with _WRITE_LOCK:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)

    def append_log(self, event_type: str, message: str, **details: Any) -> None:
        records: list = []
        if self.log_path.exists():
            try:
                records = json.loads(self.log_path.read_text(encoding="utf-8"))
            except Exception:
                records = []
        if not isinstance(records, list):
            records = []
        records.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "type": event_type,
                "message": message,
                "details": details,
            }
        )
        records = records[-500:]
        try:
            self.log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def read_log(self) -> list:
        if not self.log_path.exists():
            return []
        try:
            data = json.loads(self.log_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []
