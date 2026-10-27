"""Asset root helper (tools build — no pet skins)."""

from __future__ import annotations

import sys
from pathlib import Path


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


_APP_VERSION: str | None = None


def get_app_version() -> str:
    """Read the authoritative application version string from VERSION file."""
    global _APP_VERSION
    if _APP_VERSION is not None:
        return _APP_VERSION

    root = bundle_root()
    candidates = [
        root / "VERSION",
        root / "app" / "VERSION",
        Path(__file__).resolve().parent / "VERSION",
        Path(__file__).resolve().parent.parent / "VERSION",
        Path.cwd() / "VERSION",
    ]
    for c in candidates:
        if c.is_file():
            try:
                v = c.read_text(encoding="utf-8").strip()
                if v:
                    _APP_VERSION = v
                    return _APP_VERSION
            except Exception:
                pass

    _APP_VERSION = "1.0.21"
    return _APP_VERSION


def make_version_badge(parent=None, text: str | None = None):
    """Create a sleek, high-tech version badge widget for window top edges."""
    from PyQt6.QtWidgets import QLabel

    ver = text or f"v{get_app_version()}"
    lbl = QLabel(ver, parent)
    lbl.setObjectName("versionBadge")
    lbl.setToolTip(f"Clock/Alarm 版本: {ver}")
    lbl.setStyleSheet(
        "color: #94a3b8; font-family: 'Consolas', 'Segoe UI', monospace; "
        "font-size: 11px; font-weight: 700; padding: 2px 7px; "
        "background: rgba(255, 255, 255, 0.07); "
        "border: 1px solid rgba(148, 163, 184, 0.22); "
        "border-radius: 5px;"
    )
    return lbl

