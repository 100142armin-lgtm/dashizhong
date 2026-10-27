"""Blink Encrypted Bookmarks UI — Embedded Clock Orb, Floating Vault Panel & Security Dialogs.

Provides:
- BookmarkOrbWidget: Proportional scaling floating orb embedded in the bottom-left of FloatingWorldClock.
- BookmarksFloatingPanel: Popup dark-cyber bookmark manager with AES-256-GCM lock screen,
  first-time setup wizard, Recovery Key lossless password reset, multi-profile browser delivery,
  category color pills, instant search, additive HTML import, and dual-track export.
- VaultSecurityDialog: Reusable dialog for Settings & Panel to manage passwords, recovery keys, and backups.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bookmarks_browser_bridge import (
    detect_active_browser_windows,
    discover_all_browser_profiles,
    open_url_in_browser,
)
from bookmarks_vault import (
    CATEGORY_COLORS,
    COLOR_KEYS,
    BookmarksVault,
    extract_domain_label,
    get_bookmarks_vault,
    normalize_bookmark_url,
    parse_clipboard_spreadsheet,
)

PANEL_STYLE = """
QWidget#BlinkPanelRoot {
    background-color: rgba(13, 18, 30, 246);
    border: 1px solid rgba(99, 102, 241, 0.42);
    border-radius: 16px;
}
QLabel {
    color: #e2e8f0;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}
QLineEdit, QComboBox {
    background-color: rgba(30, 41, 59, 210);
    color: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 0.28);
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 13px;
    selection-background-color: #6366f1;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #818cf8;
    background-color: rgba(30, 41, 59, 245);
}
QPushButton {
    background-color: rgba(51, 65, 85, 190);
    color: #f1f5f9;
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: rgba(71, 85, 105, 230);
    border-color: rgba(165, 180, 252, 0.55);
}
QPushButton#PrimaryBtn {
    background-color: #4f46e5;
    color: #ffffff;
    border: 1px solid #6366f1;
}
QPushButton#PrimaryBtn:hover {
    background-color: #6366f1;
    border-color: #818cf8;
}
QPushButton#EmeraldBtn {
    background-color: rgba(16, 185, 129, 0.22);
    color: #6ee7b7;
    border: 1px solid rgba(16, 185, 129, 0.48);
}
QPushButton#EmeraldBtn:hover {
    background-color: rgba(16, 185, 129, 0.36);
}
QPushButton#GhostBtn {
    background-color: transparent;
    color: #94a3b8;
    border: none;
    padding: 4px 8px;
}
QPushButton#GhostBtn:hover {
    color: #e2e8f0;
    background-color: rgba(51, 65, 85, 120);
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: rgba(15, 23, 42, 0.4);
    width: 6px;
    margin: 2px 0;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(148, 163, 184, 0.35);
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(129, 140, 248, 0.7);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: rgba(15, 23, 42, 0.35);
    height: 6px;
    border-radius: 3px;
}
QScrollBar::handle:horizontal {
    background: rgba(129, 140, 248, 0.45);
    min-width: 24px;
    border-radius: 3px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(129, 140, 248, 0.8);
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
"""


def _build_scaled_panel_style(scale: float = 1.0) -> str:
    """Build proportionally scaled stylesheet for BookmarksFloatingPanel when resized."""
    s = max(0.78, min(1.85, float(scale)))
    f_inp = max(10, round(13 * s))
    f_btn = max(10, round(12 * s))
    f_title = max(11, round(13 * s))
    f_url = max(9, round(11 * s))
    f_note = max(9, round(11 * s))
    f_act = max(9, round(11 * s))
    pad_v = max(4, round(6 * s))
    pad_h = max(8, round(12 * s))
    inp_v = max(5, round(7 * s))
    inp_h = max(7, round(10 * s))
    rad_root = max(12, round(16 * s))
    rad_ctrl = max(6, round(8 * s))
    act_pv = max(1, round(2 * s))
    act_ph = max(4, round(6 * s))
    return f"""
QWidget#BlinkPanelRoot {{
    background-color: rgba(13, 18, 30, 246);
    border: 1px solid rgba(99, 102, 241, 0.42);
    border-radius: {rad_root}px;
}}
QLabel {{
    color: #e2e8f0;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}}
QLineEdit, QComboBox {{
    background-color: rgba(30, 41, 59, 210);
    color: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 0.28);
    border-radius: {rad_ctrl}px;
    padding: {inp_v}px {inp_h}px;
    font-size: {f_inp}px;
    selection-background-color: #6366f1;
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid #818cf8;
    background-color: rgba(30, 41, 59, 245);
}}
QPushButton {{
    background-color: rgba(51, 65, 85, 190);
    color: #f1f5f9;
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-radius: {rad_ctrl}px;
    padding: {pad_v}px {pad_h}px;
    font-size: {f_btn}px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: rgba(71, 85, 105, 230);
    border-color: rgba(165, 180, 252, 0.55);
}}
QPushButton#PrimaryBtn {{
    background-color: #4f46e5;
    color: #ffffff;
    border: 1px solid #6366f1;
}}
QPushButton#PrimaryBtn:hover {{
    background-color: #6366f1;
    border-color: #818cf8;
}}
QPushButton#EmeraldBtn {{
    background-color: rgba(16, 185, 129, 0.22);
    color: #6ee7b7;
    border: 1px solid rgba(16, 185, 129, 0.48);
}}
QPushButton#EmeraldBtn:hover {{
    background-color: rgba(16, 185, 129, 0.36);
}}
QPushButton#GhostBtn {{
    background-color: transparent;
    color: #94a3b8;
    border: none;
    padding: 4px 8px;
}}
QPushButton#GhostBtn:hover {{
    color: #e2e8f0;
    background-color: rgba(51, 65, 85, 120);
}}
QLabel#BmCardTitle {{
    font-size: {f_title}px;
    font-weight: 700;
    color: #f8fafc;
    background: transparent;
    border: none;
}}
QLabel#BmCardUrl {{
    font-size: {f_url}px;
    color: #94a3b8;
    background: transparent;
    border: none;
}}
QLabel#BmCardNote {{
    font-size: {f_note}px;
    color: #a5b4fc;
    background: transparent;
    border: none;
}}
QPushButton#BmCardActBtn {{
    background: rgba(15, 23, 42, 0.45);
    color: #cbd5e1;
    border: none;
    border-radius: 5px;
    padding: {act_pv}px {act_ph}px;
    font-size: {f_act}px;
}}
QPushButton#BmCardActBtn:hover {{
    background: #4f46e5;
    color: #ffffff;
}}
QPushButton#BmCardDelBtn {{
    background: rgba(15, 23, 42, 0.45);
    color: #fda4af;
    border: none;
    border-radius: 5px;
    padding: {act_pv}px {act_ph}px;
    font-size: {f_act}px;
}}
QPushButton#BmCardDelBtn:hover {{
    background: #e11d48;
    color: #ffffff;
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: rgba(15, 23, 42, 0.4);
    width: 6px;
    margin: 2px 0;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: rgba(148, 163, 184, 0.35);
    min-height: 24px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(129, 140, 248, 0.7);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: rgba(15, 23, 42, 0.35);
    height: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(129, 140, 248, 0.48);
    min-width: 24px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(129, 140, 248, 0.85);
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""


class BookmarkOrbWidget(QWidget):
    """Embedded Floating Ball (Orb) inside FloatingWorldClock's bottom-left area.

    Scales proportionally when the clock panel is resized and reflects lock/open state.
    """

    clicked = pyqtSignal()
    context_action_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._orb_size = 36
        self._hovered = False
        self._panel_open = False
        self._unlocked = False
        self._accent_hex = "#6366f1"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setToolTip("✨ 灵动书签 (Blink)\n左键：展开/收起加密书签库\n右键：快捷菜单与导出备份")
        self.setFixedSize(self._orb_size, self._orb_size)

    def set_orb_size(self, size_px: int) -> None:
        clamped = max(24, min(76, int(size_px)))
        if clamped != self._orb_size or self.width() != clamped:
            self._orb_size = clamped
            self.setFixedSize(clamped, clamped)
            self.update()

    def set_visual_state(
        self,
        *,
        unlocked: bool | None = None,
        panel_open: bool | None = None,
        accent_hex: str | None = None,
    ) -> None:
        if unlocked is not None:
            self._unlocked = bool(unlocked)
        if panel_open is not None:
            self._panel_open = bool(panel_open)
        if accent_hex:
            self._accent_hex = str(accent_hex)
        self.update()

    def enterEvent(self, event: Any) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.clicked.emit()
            return
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self._show_orb_context_menu(event.globalPosition().toPoint())
            return
        super().mousePressEvent(event)

    def _show_orb_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #0f172a; color: #f1f5f9; border: 1px solid #334155; "
            "border-radius: 8px; padding: 4px; font-size: 12px; }"
            "QMenu::item { padding: 6px 14px; border-radius: 5px; }"
            "QMenu::item:selected { background-color: #4f46e5; color: #ffffff; }"
        )
        act_toggle = menu.addAction("✨ 展开 / 收起灵动书签")
        act_lock = menu.addAction("🔒 立即锁定书签保险库")
        menu.addSeparator()
        act_export = menu.addAction("📤 一键导出全部书签 (HTML)")
        act_security = menu.addAction("🔐 密码与安全急救码设置...")
        chosen = menu.exec(global_pos)
        if chosen == act_toggle:
            self.clicked.emit()
        elif chosen == act_lock:
            self.context_action_requested.emit("lock")
        elif chosen == act_export:
            self.context_action_requested.emit("export_html")
        elif chosen == act_security:
            self.context_action_requested.emit("security")

    def paintEvent(self, event: Any) -> None:
        del event
        w = float(self.width())
        h = float(self.height())
        side = min(w, h)
        if side <= 4:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        margin = max(2.0, side * 0.08)
        if self._hovered:
            margin = max(1.2, side * 0.04)
        rect = QRectF(margin, margin, side - 2 * margin, side - 2 * margin)
        center = rect.center()
        radius = rect.width() / 2.0

        primary_color = QColor(self._accent_hex if self._unlocked else "#6366f1")
        if not primary_color.isValid():
            primary_color = QColor("#6366f1")

        # Outer glow on hover or panel_open
        if self._hovered or self._panel_open:
            glow = QRadialGradient(center, radius * 1.15)
            glow_c = QColor(primary_color)
            glow_c.setAlpha(115 if self._panel_open else 85)
            glow.setColorAt(0.0, glow_c)
            glow_c_zero = QColor(primary_color)
            glow_c_zero.setAlpha(0)
            glow.setColorAt(1.0, glow_c_zero)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(0.5, 0.5, side - 1.0, side - 1.0))

        # Sphere body gradient
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if self._unlocked:
            c_top = primary_color.lighter(125)
            c_top.setAlpha(235)
            c_bot = QColor("#0f172a")
            c_bot.setAlpha(245)
        else:
            c_top = QColor("#312e81")
            c_top.setAlpha(235)
            c_bot = QColor("#090d16")
            c_bot.setAlpha(245)
        grad.setColorAt(0.0, c_top)
        grad.setColorAt(1.0, c_bot)

        border_color = QColor("#a5b4fc" if (self._hovered or self._panel_open) else primary_color)
        border_color.setAlpha(230 if (self._hovered or self._panel_open) else 165)
        pen_w = max(1.3, side * 0.045)
        painter.setPen(QPen(border_color, pen_w))
        painter.setBrush(grad)
        painter.drawEllipse(rect)

        # Draw crisp Bookmark Ribbon icon inside the sphere
        bw = rect.width() * 0.36
        bh = rect.height() * 0.44
        bx = center.x() - bw / 2.0
        by = center.y() - bh / 2.0

        bm_path = QPainterPath()
        bm_path.moveTo(bx, by + bh * 0.12)
        bm_path.quadTo(bx, by, bx + bw * 0.18, by)
        bm_path.lineTo(bx + bw * 0.82, by)
        bm_path.quadTo(bx + bw, by, bx + bw, by + bh * 0.12)
        bm_path.lineTo(bx + bw, by + bh)
        bm_path.lineTo(bx + bw * 0.5, by + bh * 0.74)
        bm_path.lineTo(bx, by + bh)
        bm_path.closeSubpath()

        icon_pen = QPen(QColor("#f8fafc"), max(1.4, side * 0.05))
        icon_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(icon_pen)
        fill_c = QColor("#e0e7ff" if self._unlocked else "#818cf8")
        fill_c.setAlpha(185 if self._unlocked else 95)
        painter.setBrush(fill_c)
        painter.drawPath(bm_path)

        # Small status indicator dot at bottom-right of orb (amber=locked, emerald=unlocked)
        dot_r = max(2.8, side * 0.10)
        dot_center_x = rect.right() - dot_r * 0.75
        dot_center_y = rect.bottom() - dot_r * 0.75
        dot_rect = QRectF(
            dot_center_x - dot_r,
            dot_center_y - dot_r,
            dot_r * 2.0,
            dot_r * 2.0,
        )
        painter.setPen(QPen(QColor("#090d16"), max(1.0, side * 0.035)))
        painter.setBrush(QColor("#10b981" if self._unlocked else "#f59e0b"))
        painter.drawEllipse(dot_rect)
        painter.end()



def copy_text_to_clipboard(text: str) -> bool:
    """Robustly copy text to the Windows system clipboard (CF_UNICODETEXT) with clip.exe & Qt fallbacks.

    Avoids QApplication.clipboard() overwriting Win32 global memory with transient OLE objects
    that disappear when a Qt.WindowType.Tool window deactivates.
    """
    val = str(text or "")
    if not val:
        return False

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

            for _ in range(12):
                if user32.OpenClipboard(None):
                    try:
                        user32.EmptyClipboard()
                        encoded = (val + "\0").encode("utf-16le")
                        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
                        if h_mem:
                            ptr = kernel32.GlobalLock(h_mem)
                            if ptr:
                                ctypes.memmove(ptr, encoded, len(encoded))
                                kernel32.GlobalUnlock(h_mem)
                                if user32.SetClipboardData(CF_UNICODETEXT, h_mem):
                                    return True
                    finally:
                        user32.CloseClipboard()
                time.sleep(0.01)
        except Exception:
            pass

        try:
            subprocess.run(
                ["clip"],
                input=val.encode("utf-16le"),
                creationflags=0x08000000,
                timeout=2,
                check=False,
            )
            return True
        except Exception:
            pass

    try:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(val)
            return True
    except Exception:
        pass
    return False


def _get_windows_desktop_dir() -> Path:
    """Resolve the user's actual Windows Desktop directory (including OneDrive/redirected Desktop)."""
    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY = 0x0010
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0 and buf.value:
                p = Path(buf.value)
                if p.is_dir():
                    return p
        except Exception:
            pass
    d = Path.home() / "Desktop"
    return d if d.is_dir() else Path.home()


def format_recovery_key_txt(recovery_key: str) -> str:
    """Format the human-readable TXT credential file content for a 16-char Recovery Key."""
    return (
        "====================================================\n"
        "  Clock/Alarm · 灵动书签 (Blink) 安全急救码凭证\n"
        "====================================================\n\n"
        f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"安全急救码: {recovery_key}\n\n"
        "使用说明:\n"
        "当您忘记灵动书签主密码时，请在解锁界面点击“忘记密码？使用急救码重置”，\n"
        "输入上方 16 位急救码并设置新密码，即可 100% 无损恢复所有历史书签。\n"
    )


def save_recovery_key_to_desktop(recovery_key: str) -> tuple[bool, Path | None, str]:
    """Write the recovery key TXT to the resolved Windows Desktop directory."""
    content = format_recovery_key_txt(recovery_key)
    target_dir = _get_windows_desktop_dir()
    filename = f"灵动书签-安全急救码-{datetime.date.today().isoformat()}.txt"
    target_path = target_dir / filename
    try:
        target_path.write_text(content, encoding="utf-8")
        return True, target_path, f"✅ 已保存至: {target_path}"
    except Exception as exc:
        return False, None, f"⚠️ 保存失败: {exc}"


def _safe_save_file_dialog(
    parent: QWidget | None,
    title: str,
    default_path: str,
    name_filter: str,
) -> str:
    """Open a non-native, topmost QFileDialog for saving files without Windows COM deadlock."""
    dlg = QFileDialog(parent, title, default_path, name_filter)
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dlg.setFileMode(QFileDialog.FileMode.AnyFile)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.setStyleSheet(
        PANEL_STYLE
        + "QFileDialog { background-color: #0f172a; color: #f1f5f9; }"
        + "QWidget { color: #e2e8f0; background-color: #0f172a; }"
        + "QTreeView, QListView { background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; }"
    )
    p = Path(default_path)
    if p.parent.is_dir():
        dlg.setDirectory(str(p.parent))
    if p.name:
        dlg.selectFile(p.name)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        files = dlg.selectedFiles()
        return str(files[0]) if files else ""
    return ""


def _safe_open_file_dialog(
    parent: QWidget | None,
    title: str,
    default_dir: str,
    name_filter: str,
) -> str:
    """Open a non-native, topmost QFileDialog for opening files without Windows COM deadlock."""
    dlg = QFileDialog(parent, title, default_dir, name_filter)
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.setStyleSheet(
        PANEL_STYLE
        + "QFileDialog { background-color: #0f172a; color: #f1f5f9; }"
        + "QWidget { color: #e2e8f0; background-color: #0f172a; }"
        + "QTreeView, QListView { background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; }"
    )
    if dlg.exec() == QDialog.DialogCode.Accepted:
        files = dlg.selectedFiles()
        return str(files[0]) if files else ""
    return ""


def _show_topmost_message(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    is_warning: bool = False,
) -> None:
    """Show a topmost QMessageBox that never hides behind BookmarksFloatingPanel."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if is_warning else QMessageBox.Icon.Information)
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    box.setStyleSheet(
        PANEL_STYLE
        + "QMessageBox { background-color: #0f172a; color: #f8fafc; }"
        + "QLabel { color: #f8fafc; }"
    )
    box.exec()


class RecoveryKeyDisplayDialog(QDialog):
    """Modal dialog showing the newly generated 16-char Emergency Recovery Key."""

    def __init__(
        self,
        recovery_key: str,
        parent: QWidget | None = None,
        title: str = "🛡️ 请妥善保存您的 16 位安全急救码",
    ) -> None:
        super().__init__(parent)
        self.recovery_key = str(recovery_key or "").strip()
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFixedWidth(465)
        self.setStyleSheet(
            PANEL_STYLE
            + "QDialog { background-color: #0f172a; border: 1px solid #4f46e5; border-radius: 14px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        hdr = QLabel("🛡️ 灵动书签 · 双密钥无损恢复机制")
        hdr.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        root.addWidget(hdr)

        desc = QLabel(
            "您的书签库已启用 <b>AES-256-GCM 硬件级加密</b>。<br>"
            "如果您日后忘记了主密码，凭下方的 <b>16 位安全急救码</b> 即可直接重置密码，"
            "<span style='color:#6ee7b7;font-weight:700;'>且之前保存的所有书签将 100% 完整无损保留！</span>"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px; color: #cbd5e1; line-height: 1.45;")
        root.addWidget(desc)

        key_box = QFrame()
        key_box.setStyleSheet(
            "QFrame { background-color: rgba(30, 41, 59, 235); border: 1px dashed #818cf8; border-radius: 10px; }"
        )
        kb_layout = QVBoxLayout(key_box)
        kb_layout.setContentsMargins(14, 12, 14, 12)
        self.key_label = QLabel(self.recovery_key)
        self.key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.key_label.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 18px; "
            "font-weight: 700; color: #fde047; letter-spacing: 1.5px; border: none;"
        )
        kb_layout.addWidget(self.key_label)
        root.addWidget(key_box)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("font-size: 12px; color: #6ee7b7;")
        root.addWidget(self.status_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.copy_btn = QPushButton("📋 复制急救码")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy_key)

        self.save_btn = QPushButton("💾 保存为 TXT 文件...")
        self.save_btn.setObjectName("EmeraldBtn")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(lambda: self._save_txt())

        self.ok_btn = QPushButton("✅ 我已妥善保存")
        self.ok_btn.setObjectName("PrimaryBtn")
        self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_btn.clicked.connect(self.accept)

        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.ok_btn)
        root.addLayout(btn_row)

    def _copy_key(self) -> None:
        ok = copy_text_to_clipboard(self.recovery_key)
        self.status_lbl.setStyleSheet(
            f"font-size: 12px; color: {'#6ee7b7' if ok else '#fda4af'}; font-weight: 600;"
        )
        self.status_lbl.setText(
            "✅ 已复制急救码到系统剪贴板（可直接 Ctrl+V 粘贴）！"
            if ok
            else "⚠️ 复制到剪贴板失败，请直接选中上方黄色急救码复制"
        )

    def _save_txt(self, dest_path: str | None = None) -> None:
        default_name = f"灵动书签-安全急救码-{datetime.date.today().isoformat()}.txt"
        path_str = dest_path or _safe_save_file_dialog(
            self,
            "保存灵动书签安全急救码",
            str(_get_windows_desktop_dir() / default_name),
            "文本文件 (*.txt);;所有文件 (*.*)",
        )
        if not path_str:
            return
        try:
            out_p = Path(path_str)
            out_p.write_text(format_recovery_key_txt(self.recovery_key), encoding="utf-8")
            self.status_lbl.setStyleSheet("font-size: 12px; color: #6ee7b7; font-weight: 600;")
            self.status_lbl.setText(f"✅ 已保存至: {out_p}")
        except Exception as exc:
            self.status_lbl.setStyleSheet("font-size: 12px; color: #fda4af; font-weight: 600;")
            self.status_lbl.setText(f"⚠️ 保存失败: {exc}")


class CategoryEditDialog(QDialog):
    """Dialog to add or edit a bookmark category name and theme color."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_name: str = "",
        initial_color: str = "indigo",
        is_edit: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("✏️ 编辑书签分类" if is_edit else "➕ 新建书签分类")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFixedWidth(360)
        self.setStyleSheet(
            PANEL_STYLE + "QDialog { background-color: #0f172a; border: 1px solid #334155; }"
        )
        self.selected_color = initial_color if initial_color in CATEGORY_COLORS else "indigo"
        self._color_btns: dict[str, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        lbl_name = QLabel("分类名称：")
        lbl_name.setStyleSheet("font-size: 12px; color: #94a3b8;")
        root.addWidget(lbl_name)

        self.name_edit = QLineEdit(initial_name)
        self.name_edit.setPlaceholderText("例如：高频常用 / 工作台 / AI 工具箱...")
        root.addWidget(self.name_edit)

        lbl_color = QLabel("分类主题色：")
        lbl_color.setStyleSheet("font-size: 12px; color: #94a3b8;")
        root.addWidget(lbl_color)

        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        for ckey in COLOR_KEYS:
            cinfo = CATEGORY_COLORS[ckey]
            btn = QPushButton("")
            btn.setFixedSize(28, 28)
            btn.setToolTip(cinfo["name"])
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=ckey: self._select_color(k))
            self._color_btns[ckey] = btn
            color_row.addWidget(btn)
        color_row.addStretch(1)
        root.addLayout(color_row)
        self._refresh_color_buttons()

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("保存")
        ok_btn.setObjectName("PrimaryBtn")
        ok_btn.clicked.connect(self._on_submit)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    def _select_color(self, color_key: str) -> None:
        self.selected_color = color_key
        self._refresh_color_buttons()

    def _refresh_color_buttons(self) -> None:
        for ckey, btn in self._color_btns.items():
            hex_c = CATEGORY_COLORS[ckey]["hex"]
            if ckey == self.selected_color:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {hex_c}; border: 2px solid #ffffff; border-radius: 14px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {hex_c}; border: 1px solid rgba(255,255,255,0.2); border-radius: 14px; }}"
                )

    def _on_submit(self) -> None:
        if not self.name_edit.text().strip():
            _show_topmost_message(self, "提示", "请输入分类名称", is_warning=True)
            return
        self.accept()

    def get_values(self) -> tuple[str, str]:
        return self.name_edit.text().strip(), self.selected_color


class BookmarkEditDialog(QDialog):
    """Dialog to add or edit a bookmark item."""

    def __init__(
        self,
        categories: list[dict[str, Any]],
        parent: QWidget | None = None,
        *,
        initial_item: dict[str, Any] | None = None,
        default_category_id: str = "",
    ) -> None:
        super().__init__(parent)
        is_edit = bool(initial_item)
        self.setWindowTitle("✏️ 编辑书签" if is_edit else "➕ 新增灵动书签")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFixedWidth(420)
        self.setStyleSheet(
            PANEL_STYLE + "QDialog { background-color: #0f172a; border: 1px solid #334155; }"
        )
        item = initial_item or {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        root.addWidget(QLabel("网页标题（留空将自动提取域名）："))
        self.title_edit = QLineEdit(str(item.get("title") or ""))
        self.title_edit.setPlaceholderText("例如：GitHub 代码仓库")
        root.addWidget(self.title_edit)

        root.addWidget(QLabel("网址链接 (URL)："))
        self.url_edit = QLineEdit(str(item.get("url") or ""))
        self.url_edit.setPlaceholderText("https://...")
        root.addWidget(self.url_edit)

        root.addWidget(QLabel("所属分类："))
        self.cat_combo = QComboBox()
        target_cid = str(item.get("categoryId") or default_category_id or "")
        selected_idx = 0
        for idx, cat in enumerate(categories):
            cid = str(cat.get("id") or "")
            cname = str(cat.get("name") or "未命名")
            self.cat_combo.addItem(cname, cid)
            if cid == target_cid:
                selected_idx = idx
        if self.cat_combo.count() > 0:
            self.cat_combo.setCurrentIndex(selected_idx)
        root.addWidget(self.cat_combo)

        root.addWidget(QLabel("备注说明（可选）："))
        self.note_edit = QLineEdit(str(item.get("note") or ""))
        self.note_edit.setPlaceholderText("记录账号用途、快捷说明或标签...")
        root.addWidget(self.note_edit)

        self.pin_check = QCheckBox("📌 置顶此书签（在列表中优先靠前展示）")
        self.pin_check.setChecked(bool(item.get("pinned", False)))
        self.pin_check.setStyleSheet("color: #e2e8f0; font-size: 12px;")
        root.addWidget(self.pin_check)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #fda4af; font-size: 12px;")
        self.err_lbl.hide()
        root.addWidget(self.err_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存书签")
        save_btn.setObjectName("PrimaryBtn")
        save_btn.clicked.connect(self._on_submit)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _on_submit(self) -> None:
        raw_url = self.url_edit.text().strip()
        try:
            norm_url = normalize_bookmark_url(raw_url)
            self.url_edit.setText(norm_url)
        except ValueError as exc:
            self.err_lbl.setText(f"⚠️ {exc}")
            self.err_lbl.show()
            return
        self.accept()

    def get_values(self) -> dict[str, Any]:
        return {
            "title": self.title_edit.text().strip(),
            "url": normalize_bookmark_url(self.url_edit.text().strip()),
            "category_id": str(self.cat_combo.currentData() or ""),
            "note": self.note_edit.text().strip(),
            "pinned": bool(self.pin_check.isChecked()),
        }



class VaultSecurityDialog(QDialog):
    """Comprehensive Security & Backup Center for Blink Bookmarks Vault.

    Accessible from both BookmarksFloatingPanel and SettingsDialog ('设置 -> 灵动书签与安全密码').
    Supports:
    - Changing Master Password (lossless)
    - Resetting Forgotten Password via 16-char Recovery Key (lossless Strategy 2)
    - Regenerating Emergency Recovery Key
    - One-Click Export (HTML & Encrypted .blinkbak) and Additive Import
    """

    vault_changed = pyqtSignal()

    def __init__(
        self,
        vault: BookmarksVault | None = None,
        parent: QWidget | None = None,
        initial_tab: str = "password",
    ) -> None:
        super().__init__(parent)
        self.vault = vault or get_bookmarks_vault()
        self.setWindowTitle("🔐 灵动书签 · 安全密码与急救码管理中心")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFixedWidth(480)
        self.setStyleSheet(
            PANEL_STYLE + "QDialog { background-color: #0f172a; border: 1px solid #4f46e5; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title_lbl = QLabel("🔐 灵动书签 · 安全密码与数据备份中心")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        root.addWidget(title_lbl)

        # Mode switcher pills
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self.tab_pwd_btn = QPushButton("🔑 修改主密码")
        self.tab_rec_btn = QPushButton("🛡️ 急救码无损重置")
        self.tab_gen_btn = QPushButton("♻️ 重新生成急救码")
        self.tab_bak_btn = QPushButton("📤 导出 / 导入备份")
        for b in (self.tab_pwd_btn, self.tab_rec_btn, self.tab_gen_btn, self.tab_bak_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            nav_row.addWidget(b)
        root.addLayout(nav_row)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # Page 0: Change Master Password (with old password)
        p_pwd = QWidget()
        l_pwd = QVBoxLayout(p_pwd)
        l_pwd.setContentsMargins(4, 8, 4, 8)
        l_pwd.setSpacing(8)
        l_pwd.addWidget(QLabel("当前主密码："))
        self.old_pwd_edit = QLineEdit()
        self.old_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.old_pwd_edit.setPlaceholderText("输入当前正在使用的主密码")
        l_pwd.addWidget(self.old_pwd_edit)
        l_pwd.addWidget(QLabel("新主密码（至少 4 位）："))
        self.new_pwd_edit = QLineEdit()
        self.new_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pwd_edit.setPlaceholderText("输入新主密码")
        l_pwd.addWidget(self.new_pwd_edit)
        l_pwd.addWidget(QLabel("确认新主密码："))
        self.confirm_pwd_edit = QLineEdit()
        self.confirm_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_pwd_edit.setPlaceholderText("再次输入新主密码")
        l_pwd.addWidget(self.confirm_pwd_edit)
        btn_do_change = QPushButton("🔑 确认修改主密码（书签 100% 无损保留）")
        btn_do_change.setObjectName("PrimaryBtn")
        btn_do_change.clicked.connect(self._handle_change_password)
        l_pwd.addWidget(btn_do_change)
        l_pwd.addStretch(1)
        self.stack.addWidget(p_pwd)

        # Page 1: Reset Password via Recovery Key (Strategy 2)
        p_rec = QWidget()
        l_rec = QVBoxLayout(p_rec)
        l_rec.setContentsMargins(4, 8, 4, 8)
        l_rec.setSpacing(8)
        info_rec = QLabel(
            "💡 忘记了主密码？请输入您保存的 <b>16 位安全急救码 (BK-XXXX-...)</b>。<br>"
            "系统将直接用急救码解封主密钥并绑定新密码，<span style='color:#6ee7b7;'>所有书签数据 100% 完好无损！</span>"
        )
        info_rec.setWordWrap(True)
        info_rec.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        l_rec.addWidget(info_rec)
        l_rec.addWidget(QLabel("16 位安全急救码："))
        self.rec_key_edit = QLineEdit()
        self.rec_key_edit.setPlaceholderText("BK-XXXX-XXXX-XXXX-XXXX")
        l_rec.addWidget(self.rec_key_edit)
        l_rec.addWidget(QLabel("设置新的主密码（至少 4 位）："))
        self.rec_new_pwd_edit = QLineEdit()
        self.rec_new_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.rec_new_pwd_edit.setPlaceholderText("输入新主密码")
        l_rec.addWidget(self.rec_new_pwd_edit)
        btn_do_recover = QPushButton("🛡️ 验证急救码并无损重置密码")
        btn_do_recover.setObjectName("EmeraldBtn")
        btn_do_recover.clicked.connect(self._handle_recovery_reset)
        l_rec.addWidget(btn_do_recover)
        l_rec.addStretch(1)
        self.stack.addWidget(p_rec)

        # Page 2: Regenerate Recovery Key
        p_gen = QWidget()
        l_gen = QVBoxLayout(p_gen)
        l_gen.setContentsMargins(4, 8, 4, 8)
        l_gen.setSpacing(8)
        info_gen = QLabel(
            "如果您担心旧急救码遗失或泄露，可验证当前主密码后重新生成一组全新的 16 位安全急救码（旧急救码将立即失效）。"
        )
        info_gen.setWordWrap(True)
        info_gen.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        l_gen.addWidget(info_gen)
        l_gen.addWidget(QLabel("验证当前主密码："))
        self.gen_pwd_edit = QLineEdit()
        self.gen_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gen_pwd_edit.setPlaceholderText("输入当前主密码以生成新急救码")
        l_gen.addWidget(self.gen_pwd_edit)
        btn_do_gen = QPushButton("♻️ 生成全新 16 位安全急救码")
        btn_do_gen.setObjectName("PrimaryBtn")
        btn_do_gen.clicked.connect(self._handle_regenerate_key)
        l_gen.addWidget(btn_do_gen)
        l_gen.addStretch(1)
        self.stack.addWidget(p_gen)

        # Page 3: Dual-Track Export & Additive Import
        p_bak = QWidget()
        l_bak = QVBoxLayout(p_bak)
        l_bak.setContentsMargins(4, 8, 4, 8)
        l_bak.setSpacing(10)
        info_bak = QLabel(
            "支持双轨本地备份：既可导出为所有浏览器通用的 <b>HTML 书签文件</b>，"
            "也可导出为 <b>AES-256 加密全量备份包 (.blinkbak)</b>，换机或重装系统永不丢失。"
        )
        info_bak.setWordWrap(True)
        info_bak.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        l_bak.addWidget(info_bak)

        btn_exp_html = QPushButton("📤 一键导出全部书签为通用 HTML 文件 (.html)")
        btn_exp_html.setObjectName("EmeraldBtn")
        btn_exp_html.clicked.connect(lambda: export_bookmarks_html_interactive(self, self.vault))
        l_bak.addWidget(btn_exp_html)

        btn_exp_enc = QPushButton("🔐 导出加密全量备份包 (.blinkbak · 无需解锁也可备份)")
        btn_exp_enc.setObjectName("PrimaryBtn")
        btn_exp_enc.clicked.connect(lambda: export_bookmarks_encrypted_interactive(self, self.vault))
        l_bak.addWidget(btn_exp_enc)

        btn_imp_html = QPushButton("📥 增量导入浏览器 HTML 书签（不覆盖现有书签）")
        btn_imp_html.clicked.connect(self._handle_import_html)
        l_bak.addWidget(btn_imp_html)

        btn_imp_enc = QPushButton("📦 从加密备份包 (.blinkbak) 增量恢复书签")
        btn_imp_enc.clicked.connect(self._handle_import_encrypted)
        l_bak.addWidget(btn_imp_enc)
        l_bak.addStretch(1)
        self.stack.addWidget(p_bak)

        self.feedback_lbl = QLabel("")
        self.feedback_lbl.setWordWrap(True)
        self.feedback_lbl.setStyleSheet("font-size: 12px; color: #6ee7b7;")
        root.addWidget(self.feedback_lbl)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)
        root.addLayout(bottom_row)

        self.tab_pwd_btn.clicked.connect(lambda: self._switch_tab(0))
        self.tab_rec_btn.clicked.connect(lambda: self._switch_tab(1))
        self.tab_gen_btn.clicked.connect(lambda: self._switch_tab(2))
        self.tab_bak_btn.clicked.connect(lambda: self._switch_tab(3))

        tab_map = {"password": 0, "recovery": 1, "regenerate": 2, "backup": 3}
        self._switch_tab(tab_map.get(initial_tab, 0))

    def _switch_tab(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        self.feedback_lbl.setText("")
        btns = [self.tab_pwd_btn, self.tab_rec_btn, self.tab_gen_btn, self.tab_bak_btn]
        for i, b in enumerate(btns):
            if i == idx:
                b.setStyleSheet("background-color: #4f46e5; color: #ffffff; border: 1px solid #818cf8;")
            else:
                b.setStyleSheet("")

    def _set_feedback(self, msg: str, ok: bool = True) -> None:
        color = "#6ee7b7" if ok else "#fda4af"
        self.feedback_lbl.setStyleSheet(f"font-size: 12px; color: {color}; font-weight: 600;")
        self.feedback_lbl.setText(msg)

    def _handle_change_password(self) -> None:
        if not self.vault.is_initialized():
            self._set_feedback("⚠️ 书签保险库尚未创建，请先点击时钟左下角悬浮球完成首次设置。", False)
            return
        old_p = self.old_pwd_edit.text().strip()
        new_p = self.new_pwd_edit.text().strip()
        conf_p = self.confirm_pwd_edit.text().strip()
        if new_p != conf_p:
            self._set_feedback("⚠️ 两次输入的新密码不一致", False)
            return
        ok, msg = self.vault.change_password(old_p, new_p)
        self._set_feedback(("✅ " if ok else "⚠️ ") + msg, ok)
        if ok:
            self.old_pwd_edit.clear()
            self.new_pwd_edit.clear()
            self.confirm_pwd_edit.clear()
            self.vault_changed.emit()

    def _handle_recovery_reset(self) -> None:
        if not self.vault.is_initialized():
            self._set_feedback("⚠️ 书签保险库尚未初始化", False)
            return
        rec_k = self.rec_key_edit.text().strip()
        new_p = self.rec_new_pwd_edit.text().strip()
        ok, msg = self.vault.reset_password_with_recovery_key(rec_k, new_p)
        self._set_feedback(("✅ " if ok else "⚠️ ") + msg, ok)
        if ok:
            self.rec_key_edit.clear()
            self.rec_new_pwd_edit.clear()
            self.vault_changed.emit()

    def _handle_regenerate_key(self) -> None:
        if not self.vault.is_initialized():
            self._set_feedback("⚠️ 书签保险库尚未初始化", False)
            return
        pwd = self.gen_pwd_edit.text().strip()
        ok, res = self.vault.regenerate_recovery_key(pwd)
        if not ok:
            self._set_feedback(f"⚠️ {res}", False)
            return
        self.gen_pwd_edit.clear()
        self._set_feedback("✅ 已生成全新的 16 位安全急救码！", True)
        dlg = RecoveryKeyDisplayDialog(res, self, title="♻️ 您的全新 16 位安全急救码")
        dlg.exec()

    def _handle_import_html(self) -> None:
        ok, msg = import_bookmarks_html_interactive(self, self.vault)
        self._set_feedback(msg, ok)
        if ok:
            self.vault_changed.emit()

    def _handle_import_encrypted(self) -> None:
        ok, msg = import_bookmarks_encrypted_interactive(self, self.vault)
        self._set_feedback(msg, ok)
        if ok:
            self.vault_changed.emit()



def _prompt_password_modal(
    parent: QWidget | None,
    title: str,
    prompt_text: str,
    placeholder: str = "请输入主密码或 16 位安全急救码",
) -> str | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.setFixedWidth(380)
    dlg.setStyleSheet(
        PANEL_STYLE + "QDialog { background-color: #0f172a; border: 1px solid #334155; }"
    )
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    lbl = QLabel(prompt_text)
    lbl.setWordWrap(True)
    lay.addWidget(lbl)
    inp = QLineEdit()
    inp.setEchoMode(QLineEdit.EchoMode.Password)
    inp.setPlaceholderText(placeholder)
    inp.returnPressed.connect(dlg.accept)
    lay.addWidget(inp)
    row = QHBoxLayout()
    row.addStretch(1)
    b_cancel = QPushButton("取消")
    b_cancel.clicked.connect(dlg.reject)
    b_ok = QPushButton("确定")
    b_ok.setObjectName("PrimaryBtn")
    b_ok.clicked.connect(dlg.accept)
    row.addWidget(b_cancel)
    row.addWidget(b_ok)
    lay.addLayout(row)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return inp.text().strip()
    return None


def _ensure_vault_unlocked_interactive(parent: QWidget | None, vault: BookmarksVault) -> bool:
    if not vault.is_initialized():
        _show_topmost_message(
            parent,
            "灵动书签尚未初始化",
            "请先点击时钟左下角的【灵动书签悬浮球】设置初始主密码。",
        )
        return False
    if vault.is_unlocked():
        return True
    pwd = _prompt_password_modal(
        parent,
        "🔓 解锁灵动书签保险库",
        "当前书签库处于加密锁定状态，请输入主密码以继续操作：",
        "请输入主密码",
    )
    if not pwd:
        return False
    ok, msg = vault.unlock(pwd)
    if not ok:
        _show_topmost_message(parent, "解锁失败", msg, is_warning=True)
        return False
    return True


def export_bookmarks_html_interactive(
    parent: QWidget | None = None,
    vault: BookmarksVault | None = None,
) -> tuple[bool, str]:
    """One-click export all bookmarks to a standard Netscape HTML file."""
    v = vault or get_bookmarks_vault()
    if not _ensure_vault_unlocked_interactive(parent, v):
        return False, "已取消导出"
    default_name = f"Blink-灵动书签全量备份-{datetime.date.today().isoformat()}.html"
    dest_str = _safe_save_file_dialog(
        parent,
        "📤 一键导出全部书签 (通用浏览器 HTML 格式)",
        str(Path.home() / "Desktop" / default_name),
        "HTML 书签文件 (*.html);;所有文件 (*.*)",
    )
    if not dest_str:
        return False, "已取消导出"
    try:
        html_doc = v.export_html()
        Path(dest_str).write_text(html_doc, encoding="utf-8")
        count = len(v.get_bookmarks())
        msg = f"✅ 已成功导出 {count} 条书签至: {Path(dest_str).name}"
        _show_topmost_message(parent, "导出成功", msg)
        return True, msg
    except Exception as exc:
        err = f"⚠️ 导出 HTML 失败: {exc}"
        _show_topmost_message(parent, "导出失败", err, is_warning=True)
        return False, err


def export_bookmarks_encrypted_interactive(
    parent: QWidget | None = None,
    vault: BookmarksVault | None = None,
) -> tuple[bool, str]:
    """One-click export the AES-256-GCM encrypted .blinkbak archive."""
    v = vault or get_bookmarks_vault()
    if not v.is_initialized():
        _show_topmost_message(parent, "提示", "书签保险库尚未初始化，暂无可导出的数据。")
        return False, "保险库未初始化"
    default_name = f"Blink-灵动书签加密备份-{datetime.date.today().isoformat()}.blinkbak"
    dest_str = _safe_save_file_dialog(
        parent,
        "🔐 导出 AES-256 加密全量备份包 (.blinkbak)",
        str(Path.home() / "Desktop" / default_name),
        "灵动书签加密备份 (*.blinkbak *.json);;所有文件 (*.*)",
    )
    if not dest_str:
        return False, "已取消导出"
    try:
        v.export_encrypted_backup(dest_str)
        msg = f"✅ 加密备份包已保存至: {Path(dest_str).name}"
        _show_topmost_message(parent, "加密备份成功", msg)
        return True, msg
    except Exception as exc:
        err = f"⚠️ 导出加密备份失败: {exc}"
        _show_topmost_message(parent, "导出失败", err, is_warning=True)
        return False, err


def import_bookmarks_html_interactive(
    parent: QWidget | None = None,
    vault: BookmarksVault | None = None,
) -> tuple[bool, str]:
    """Additively import bookmarks from a browser HTML file without overwriting."""
    v = vault or get_bookmarks_vault()
    if not _ensure_vault_unlocked_interactive(parent, v):
        return False, "已取消导入"
    src_str = _safe_open_file_dialog(
        parent,
        "📥 选择要增量导入的浏览器书签 HTML 文件",
        str(Path.home() / "Desktop"),
        "HTML 书签文件 (*.html *.htm);;所有文件 (*.*)",
    )
    if not src_str:
        return False, "已取消导入"
    try:
        raw_html = Path(src_str).read_text(encoding="utf-8", errors="replace")
        added_bms, added_cats = v.import_html_additive(raw_html)
        msg = f"✅ 增量导入完成：新增 {added_bms} 条书签、{added_cats} 个分类（原有书签完整保留）"
        _show_topmost_message(parent, "导入成功", msg)
        return True, msg
    except Exception as exc:
        err = f"⚠️ 导入 HTML 书签失败: {exc}"
        _show_topmost_message(parent, "导入失败", err, is_warning=True)
        return False, err


def import_bookmarks_encrypted_interactive(
    parent: QWidget | None = None,
    vault: BookmarksVault | None = None,
) -> tuple[bool, str]:
    """Additively restore bookmarks from an encrypted .blinkbak file."""
    v = vault or get_bookmarks_vault()
    if not _ensure_vault_unlocked_interactive(parent, v):
        return False, "已取消导入"
    src_str = _safe_open_file_dialog(
        parent,
        "📦 选择要恢复的灵动书签加密备份包 (.blinkbak)",
        str(Path.home() / "Desktop"),
        "灵动书签加密备份 (*.blinkbak *.json);;所有文件 (*.*)",
    )
    if not src_str:
        return False, "已取消导入"
    secret = _prompt_password_modal(
        parent,
        "🔐 输入备份包解密凭证",
        "请输入该加密备份包的主密码或 16 位安全急救码：",
        "主密码 或 BK-XXXX-XXXX-XXXX-XXXX",
    )
    if not secret:
        return False, "已取消导入"
    try:
        added_bms, added_cats = v.import_encrypted_backup(src_str, secret)
        msg = f"✅ 加密备份恢复成功：新增 {added_bms} 条书签、{added_cats} 个分类"
        _show_topmost_message(parent, "恢复成功", msg)
        return True, msg
    except Exception as exc:
        err = f"⚠️ 解密或导入备份包失败: {exc}"
        _show_topmost_message(parent, "恢复失败", err, is_warning=True)
        return False, err


def get_clipboard_html_and_text() -> tuple[str, str]:
    """Read both HTML ('text/html' / Win32 CF_HTML) and plain text from the system clipboard."""
    html_s = ""
    text_s = ""
    try:
        cb = QApplication.clipboard()
        if cb is not None:
            mime = cb.mimeData()
            if mime is not None:
                if mime.hasHtml():
                    html_s = str(mime.html() or "")
                if mime.hasText():
                    text_s = str(mime.text() or "")
            if not text_s:
                text_s = str(cb.text() or "")
    except Exception:
        pass

    if sys.platform == "win32" and (not html_s or not text_s):
        try:
            import ctypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_int
            user32.GetClipboardData.argtypes = [ctypes.c_uint]
            user32.GetClipboardData.restype = ctypes.c_void_p
            user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
            user32.RegisterClipboardFormatW.restype = ctypes.c_uint
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
            kernel32.GlobalSize.restype = ctypes.c_size_t

            if user32.OpenClipboard(None):
                try:
                    if not html_s:
                        cf_html = user32.RegisterClipboardFormatW("HTML Format")
                        if cf_html:
                            h_mem = user32.GetClipboardData(cf_html)
                            if h_mem:
                                ptr = kernel32.GlobalLock(h_mem)
                                if ptr:
                                    try:
                                        sz = int(kernel32.GlobalSize(h_mem))
                                        if 0 < sz < 32_000_000:
                                            raw_bytes = ctypes.string_at(ptr, sz).rstrip(b"\x00")
                                            decoded = raw_bytes.decode("utf-8", errors="replace")
                                            idx = decoded.lower().find("<html")
                                            if idx < 0:
                                                idx = decoded.find("<")
                                            html_s = decoded[idx:] if idx >= 0 else decoded
                                    finally:
                                        kernel32.GlobalUnlock(h_mem)
                    if not text_s:
                        h_u = user32.GetClipboardData(13)  # CF_UNICODETEXT
                        if h_u:
                            ptr_u = kernel32.GlobalLock(h_u)
                            if ptr_u:
                                try:
                                    text_s = ctypes.wstring_at(ptr_u)
                                finally:
                                    kernel32.GlobalUnlock(h_u)
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass

    return html_s, text_s


class ClipboardBatchImportDialog(QDialog):
    """Smart preview & confirmation dialog for Google Sheets / Excel / Clipboard batch bookmark paste."""

    def __init__(
        self,
        parsed_data: dict[str, Any],
        vault: BookmarksVault,
        default_category_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.parsed_data = parsed_data
        self.vault = vault
        self.default_category_id = str(default_category_id or "")
        self.flat_items: list[dict[str, str]] = list(parsed_data.get("flat_items") or [])
        self.header_columns: list[dict[str, Any]] = list(parsed_data.get("header_columns") or [])
        self._mode: str = str(parsed_data.get("recommended_mode") or "single_category")
        if self._mode == "matrix_headers" and not self.header_columns:
            self._mode = "single_category"

        self.setWindowTitle("📋 从谷歌表格 / 剪贴板批量粘贴书签")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumSize(500, 440)
        self.resize(540, 480)
        self.setStyleSheet(
            PANEL_STYLE + "QDialog { background-color: #0f172a; border: 1px solid #4f46e5; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        hdr = QLabel("📋 识别到谷歌表格 / 剪贴板超链接数据")
        hdr.setStyleSheet("font-size: 15px; font-weight: 800; color: #f8fafc;")
        root.addWidget(hdr)

        sub = QLabel(
            "请选择导入方式（支持<b>单列 100+ 超链接一键贴入指定文件夹</b>，或<b>A-Z 多列按第一行标题自动建文件夹</b>）："
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        root.addWidget(sub)

        # Mode switch buttons
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.btn_mode_single = QPushButton(
            f"📥 模式一：全部贴入指定分组 ({len(self.flat_items)} 条)"
        )
        self.btn_mode_single.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_single.setMinimumHeight(34)
        self.btn_mode_single.clicked.connect(lambda: self._set_mode("single_category"))

        col_bm_total = sum(len(c.get("items") or []) for c in self.header_columns)
        self.btn_mode_matrix = QPushButton(
            f"📂 模式二：按第 1 行自动建分组 ({len(self.header_columns)} 列 / {col_bm_total} 条)"
        )
        self.btn_mode_matrix.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_matrix.setMinimumHeight(34)
        self.btn_mode_matrix.setEnabled(bool(self.header_columns))
        self.btn_mode_matrix.clicked.connect(lambda: self._set_mode("matrix_headers"))

        mode_row.addWidget(self.btn_mode_single, 1)
        mode_row.addWidget(self.btn_mode_matrix, 1)
        root.addLayout(mode_row)

        # Target category selector row (visible in 'single_category' mode)
        self.single_cat_frame = QFrame()
        self.single_cat_frame.setStyleSheet(
            "QFrame { background-color: rgba(30, 41, 59, 180); border: 1px solid rgba(99, 102, 241, 0.35); border-radius: 9px; }"
        )
        sc_lay = QHBoxLayout(self.single_cat_frame)
        sc_lay.setContentsMargins(10, 8, 10, 8)
        sc_lay.setSpacing(8)
        sc_lbl = QLabel("目标分组文件夹：")
        sc_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #e2e8f0; border: none;")
        sc_lay.addWidget(sc_lbl)

        self.cat_combo = QComboBox()
        self.cats = self.vault.get_categories() if self.vault.is_unlocked() else []
        sel_idx = 0
        for idx, c in enumerate(self.cats):
            cid = str(c.get("id") or "")
            cname = str(c.get("name") or "未命名分类")
            self.cat_combo.addItem(f"📂 {cname}", cid)
            if cid == self.default_category_id:
                sel_idx = idx
        self.cat_combo.addItem("➕ 新建分组文件夹...", "__new__")
        self.cat_combo.setCurrentIndex(sel_idx)
        self.cat_combo.currentIndexChanged.connect(self._on_cat_combo_changed)
        sc_lay.addWidget(self.cat_combo, 1)

        self.new_cat_edit = QLineEdit()
        self.new_cat_edit.setPlaceholderText("输入新分组名称...")
        self.new_cat_edit.hide()
        self.new_cat_edit.textChanged.connect(lambda _t: self._refresh_preview())
        sc_lay.addWidget(self.new_cat_edit, 1)
        root.addWidget(self.single_cat_frame)

        # Preview area
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setStyleSheet(
            "QScrollArea { background-color: rgba(15, 23, 42, 220); border: 1px solid rgba(148, 163, 184, 0.22); border-radius: 10px; }"
        )
        self.preview_container = QWidget()
        self.preview_container.setStyleSheet("background: transparent;")
        self.preview_lay = QVBoxLayout(self.preview_container)
        self.preview_lay.setContentsMargins(12, 10, 12, 10)
        self.preview_lay.setSpacing(6)
        self.preview_scroll.setWidget(self.preview_container)
        root.addWidget(self.preview_scroll, 1)

        self.dedup_cb = QCheckBox("自动跳过同一分组下已存在的重复网址（推荐）")
        self.dedup_cb.setChecked(True)
        root.addWidget(self.dedup_cb)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = QPushButton("🚀 确认一键导入")
        self.confirm_btn.setObjectName("EmeraldBtn")
        self.confirm_btn.setMinimumHeight(36)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._on_confirm_clicked)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.confirm_btn)
        root.addLayout(btn_row)

        self._set_mode(self._mode)

    def _on_cat_combo_changed(self, _idx: int) -> None:
        if self.cat_combo.currentData() == "__new__":
            self.new_cat_edit.show()
            self.new_cat_edit.setFocus()
        else:
            self.new_cat_edit.hide()
        self._refresh_preview()

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        active_qss = (
            "QPushButton { background-color: #4f46e5; color: #ffffff; "
            "border: 1.5px solid #a5b4fc; border-radius: 8px; font-weight: 800; padding: 6px 10px; }"
        )
        idle_qss = (
            "QPushButton { background-color: rgba(30, 41, 59, 190); color: #94a3b8; "
            "border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 8px; padding: 6px 10px; }"
            "QPushButton:hover { color: #f8fafc; border-color: #6366f1; }"
        )
        if mode == "matrix_headers":
            self.btn_mode_matrix.setStyleSheet(active_qss)
            self.btn_mode_single.setStyleSheet(idle_qss)
            self.single_cat_frame.hide()
        else:
            self.btn_mode_single.setStyleSheet(active_qss)
            self.btn_mode_matrix.setStyleSheet(idle_qss)
            self.single_cat_frame.show()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        while self.preview_lay.count():
            it = self.preview_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        existing_names = {
            str(c.get("name") or "").strip().lower() for c in self.cats
        }

        if self._mode == "matrix_headers":
            total_bms = sum(len(c.get("items") or []) for c in self.header_columns)
            summary = QLabel(
                f"✨ 将按表格<b>第 1 行</b>自动识别 <b>{len(self.header_columns)} 个分组</b>，"
                f"并从<b>第 2 行起</b>按列导入共 <b>{total_bms} 条超链接书签</b>："
            )
            summary.setWordWrap(True)
            summary.setStyleSheet("font-size: 12px; color: #a5b4fc;")
            self.preview_lay.addWidget(summary)

            for col in self.header_columns:
                cname = str(col.get("category_name") or "未命名分组")
                c_items = col.get("items") or []
                is_existing = cname.strip().lower() in existing_names
                badge = "🔗 归入已有同名分组" if is_existing else "✨ 自动新建分组文件夹"
                badge_color = "#6ee7b7" if not is_existing else "#93c5fd"

                box = QFrame()
                box.setStyleSheet(
                    "QFrame { background-color: rgba(30, 41, 59, 175); border: 1px solid rgba(148, 163, 184, 0.18); border-radius: 8px; }"
                )
                b_lay = QVBoxLayout(box)
                b_lay.setContentsMargins(10, 7, 10, 7)
                b_lay.setSpacing(3)

                title_lbl = QLabel(
                    f"<b>📂 {cname}</b> &nbsp; <span style='color:{badge_color};font-size:11px;'>[{badge} · {len(c_items)} 条超链接]</span>"
                )
                title_lbl.setStyleSheet("font-size: 12px; color: #f8fafc; border: none;")
                b_lay.addWidget(title_lbl)

                samples = []
                for idx, bm in enumerate(c_items[:4], 1):
                    samples.append(f"{idx}. {bm['title']}  ({bm['url'][:48]})")
                if len(c_items) > 4:
                    samples.append(f"... 以及其余 {len(c_items) - 4} 条超链接")
                samp_lbl = QLabel("\n".join(samples))
                samp_lbl.setStyleSheet("font-size: 11px; color: #94a3b8; border: none;")
                b_lay.addWidget(samp_lbl)
                self.preview_lay.addWidget(box)

            self.confirm_btn.setText(
                f"🚀 确认按列建组并导入 ({len(self.header_columns)} 个分组 / {total_bms} 条)"
            )
        else:
            cid = str(self.cat_combo.currentData() or "")
            if cid == "__new__":
                target_name = self.new_cat_edit.text().strip() or "新建粘贴分组"
            else:
                target_name = self.cat_combo.currentText().replace("📂 ", "").strip()

            summary = QLabel(
                f"✨ 将把剪贴板中的 <b>{len(self.flat_items)} 条超链接</b> 批量导入到分组 <b>【{target_name}】</b>："
            )
            summary.setWordWrap(True)
            summary.setStyleSheet("font-size: 12px; color: #6ee7b7;")
            self.preview_lay.addWidget(summary)

            for idx, bm in enumerate(self.flat_items[:60], 1):
                u_disp = bm["url"] if len(bm["url"]) <= 56 else (bm["url"][:53] + "...")
                row_lbl = QLabel(
                    f"<b>{idx}. {bm['title']}</b> &nbsp;<span style='color:#64748b;'>— {u_disp}</span>"
                )
                row_lbl.setStyleSheet("font-size: 11px; color: #e2e8f0; padding: 1px 0;")
                self.preview_lay.addWidget(row_lbl)

            if len(self.flat_items) > 60:
                more_lbl = QLabel(f"... 以及其余 {len(self.flat_items) - 60} 条超链接（将一次性全部导入）")
                more_lbl.setStyleSheet("font-size: 11px; color: #94a3b8; padding-top: 4px;")
                self.preview_lay.addWidget(more_lbl)

            self.confirm_btn.setText(f"🚀 确认一键导入到【{target_name}】 ({len(self.flat_items)} 条)")

        self.preview_lay.addStretch(1)

    def get_batches_and_options(self) -> tuple[list[dict[str, Any]], bool]:
        skip_dup = bool(self.dedup_cb.isChecked())
        if self._mode == "matrix_headers":
            batches = [
                {
                    "category_id": None,
                    "category_name": str(col.get("category_name") or "导入分组"),
                    "items": list(col.get("items") or []),
                }
                for col in self.header_columns
            ]
            return batches, skip_dup

        cid = str(self.cat_combo.currentData() or "")
        if cid == "__new__":
            cname = self.new_cat_edit.text().strip() or "新建粘贴分组"
            return [{"category_id": None, "category_name": cname, "items": self.flat_items}], skip_dup
        return [{"category_id": cid, "category_name": None, "items": self.flat_items}], skip_dup

    def _on_confirm_clicked(self) -> None:
        if self._mode == "single_category" and self.cat_combo.currentData() == "__new__":
            if not self.new_cat_edit.text().strip():
                self.new_cat_edit.setText("谷歌表格导入")
        self.accept()


def import_bookmarks_from_clipboard_interactive(
    parent: QWidget | None = None,
    vault: BookmarksVault | None = None,
    default_category_id: str = "",
    html_override: str | None = None,
    text_override: str | None = None,
    auto_confirm_mode: str | None = None,
) -> tuple[bool, str, str]:
    """Parse Google Sheets / Excel / Clipboard hyperlinks and batch-import them.

    Returns (success, status_message, first_imported_category_id).
    """
    v = vault or get_bookmarks_vault()
    if not _ensure_vault_unlocked_interactive(parent, v):
        return False, "已取消粘贴导入", ""

    if html_override is not None or text_override is not None:
        html_s = str(html_override or "")
        text_s = str(text_override or "")
    else:
        html_s, text_s = get_clipboard_html_and_text()

    parsed = parse_clipboard_spreadsheet(html_s, text_s)
    if not parsed.get("has_data"):
        msg = (
            "⚠️ 剪贴板中未检测到有效的超链接或网址。\n\n"
            "💡 使用提示：\n"
            "1. 在谷歌表格 / Excel 中框选带超链接的单元格（支持单列 100+ 个或 A-Z 多列全选）按 Ctrl+C 复制；\n"
            "2. 回到灵动书签面板按 Ctrl+V 或点击【📋 粘贴表格】即可一键批量导入！"
        )
        if auto_confirm_mode is None:
            _show_topmost_message(parent, "未检测到超链接", msg, is_warning=True)
        return False, "剪贴板中未检测到超链接", ""

    cats = v.get_categories()
    valid_cat_ids = {str(c.get("id")) for c in cats}
    resolved_default_cid = (
        default_category_id
        if default_category_id in valid_cat_ids
        else (str(cats[0]["id"]) if cats else "")
    )

    if auto_confirm_mode is not None:
        mode = auto_confirm_mode
        if mode == "matrix_headers" and parsed.get("header_columns"):
            batches = [
                {
                    "category_id": None,
                    "category_name": str(col.get("category_name") or "导入分组"),
                    "items": list(col.get("items") or []),
                }
                for col in parsed["header_columns"]
            ]
        else:
            batches = [
                {
                    "category_id": resolved_default_cid,
                    "category_name": None,
                    "items": list(parsed.get("flat_items") or []),
                }
            ]
        added_bms, added_cats, first_cid = v.import_clipboard_batches(batches, skip_duplicates=True)
        return (
            True,
            f"✅ 批量粘贴成功：新增 {added_bms} 条书签、{added_cats} 个分组",
            first_cid,
        )

    dlg = ClipboardBatchImportDialog(
        parsed_data=parsed,
        vault=v,
        default_category_id=resolved_default_cid,
        parent=parent,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False, "已取消粘贴导入", ""

    batches, skip_dup = dlg.get_batches_and_options()
    added_bms, added_cats, first_cid = v.import_clipboard_batches(
        batches, skip_duplicates=skip_dup
    )
    if added_cats > 0:
        msg = f"✅ 表格批量导入完成：自动新建 {added_cats} 个分组，导入 {added_bms} 条超链接书签！"
    else:
        msg = f"✅ 批量粘贴完成：成功导入 {added_bms} 条超链接书签！"
    return True, msg, first_cid


class _DragFloatingAvatar(QWidget):
    """Blink-style magnified floating drag avatar with velocity micro-tilt and indigo glow."""

    def __init__(
        self,
        parent: QWidget,
        pixmap: QPixmap,
        scale_factor: float = 1.08,
        border_radius: int = 12,
    ) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self._scale = scale_factor
        self._radius = border_radius
        self._tilt_deg: float = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        dpr = pixmap.devicePixelRatio() or 1.0
        logical_w = max(24, int(round(pixmap.width() / dpr)))
        logical_h = max(18, int(round(pixmap.height() / dpr)))
        self._base_w = logical_w
        self._base_h = logical_h
        self._pad = 14
        self.resize(
            int(round(logical_w * scale_factor)) + self._pad * 2,
            int(round(logical_h * scale_factor)) + self._pad * 2,
        )

    def set_tilt(self, tilt_deg: float) -> None:
        clamped = max(-3.8, min(3.8, float(tilt_deg)))
        if abs(clamped - self._tilt_deg) > 0.08:
            self._tilt_deg = clamped
            self.update()

    def move_avatar(self, root_x: int, root_y: int) -> None:
        self.move(root_x - self._pad, root_y - self._pad)

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        painter.translate(cx, cy)
        if abs(self._tilt_deg) > 0.05:
            painter.rotate(self._tilt_deg)
        painter.scale(self._scale, self._scale)

        rect = QRectF(-self._base_w / 2.0, -self._base_h / 2.0, float(self._base_w), float(self._base_h))

        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(rect.adjusted(-2, 3, 2, 5), self._radius + 2, self._radius + 2)
        painter.fillPath(shadow_path, QColor(2, 6, 23, 155))

        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, self._radius, self._radius)
        painter.save()
        painter.setClipPath(clip_path)
        painter.setOpacity(0.96)
        painter.drawPixmap(rect.toRect(), self._pixmap)
        painter.restore()

        pen = QPen(QColor("#818cf8"), 1.8)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, self._radius, self._radius)
        painter.end()


class BookmarkCardWidget(QFrame):
    """Single bookmark item card with left color accent strip, vertical drag reordering, and drag-to-category support."""

    open_requested = pyqtSignal(dict)
    pin_requested = pyqtSignal(str)
    top_requested = pyqtSignal(str)
    edit_requested = pyqtSignal(dict)
    delete_requested = pyqtSignal(str)
    copy_url_requested = pyqtSignal(str)

    def __init__(
        self,
        item: dict[str, Any],
        category_info: dict[str, Any] | None = None,
        parent: QWidget | None = None,
        panel: Any = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self._panel = panel
        self.bm_id = str(item.get("id") or "")
        self.cat_color_key = str((category_info or {}).get("color") or "indigo")
        self.cat_name = str((category_info or {}).get("name") or "")
        self.c_palette = CATEGORY_COLORS.get(self.cat_color_key, CATEGORY_COLORS["indigo"])
        self.accent_hex = self.c_palette["hex"]
        self._press_global: QPoint | None = None
        self._press_local: QPoint = QPoint(24, 18)
        self._dragging_card = False
        self._is_placeholder = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "左键点击打开书签 · 按住左键上下拖动可自由调整书签顺序 · 拖到上方【分组标签】可快速归类 · 右键更多操作"
        )
        self.setObjectName("BmCard")
        self.setStyleSheet(self._normal_card_stylesheet())

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(11, 8, 10, 8)
        self._lay.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        pinned = bool(item.get("pinned"))
        title_str = ("📌 " if pinned else "") + str(item.get("title") or "未命名书签")
        self.title_lbl = QLabel(title_str)
        self.title_lbl.setObjectName("BmCardTitle")
        top_row.addWidget(self.title_lbl, 1)

        self.cat_badge: QLabel | None = None
        if self.cat_name:
            self.cat_badge = QLabel(self.cat_name)
            self.cat_badge.setStyleSheet(
                f"font-size: 10px; color: {self.accent_hex}; background-color: {self.c_palette['bg']}; "
                f"border: 1px solid {self.c_palette['border']}; border-radius: 5px; padding: 1px 6px;"
            )
            top_row.addWidget(self.cat_badge)

        pin_btn = QPushButton("📌")
        pin_btn.setObjectName("BmCardActBtn")
        pin_btn.setToolTip("置顶 / 取消置顶")
        pin_btn.clicked.connect(lambda: self.pin_requested.emit(self.bm_id))
        top_row.addWidget(pin_btn)

        edit_btn = QPushButton("✏️")
        edit_btn.setObjectName("BmCardActBtn")
        edit_btn.setToolTip("编辑书签")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.item))
        top_row.addWidget(edit_btn)

        del_btn = QPushButton("🗑️")
        del_btn.setObjectName("BmCardDelBtn")
        del_btn.setToolTip("删除书签")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.bm_id))
        top_row.addWidget(del_btn)

        self._lay.addLayout(top_row)

        self.url_str = str(item.get("url") or "")
        self.domain = extract_domain_label(self.url_str)
        display_url = self.url_str if len(self.url_str) <= 58 else (self.url_str[:55] + "...")
        self.url_lbl = QLabel(f"🌐 {self.domain}  ·  {display_url}")
        self.url_lbl.setObjectName("BmCardUrl")
        self._lay.addWidget(self.url_lbl)

        note_str = str(item.get("note") or "").strip()
        self.note_lbl: QLabel | None = None
        if note_str:
            self.note_lbl = QLabel(f"💬 {note_str}")
            self.note_lbl.setObjectName("BmCardNote")
            self.note_lbl.setWordWrap(True)
            self._lay.addWidget(self.note_lbl)

    def _normal_card_stylesheet(self) -> str:
        return f"""
            QFrame#BmCard {{
                background-color: rgba(30, 41, 59, 175);
                border: 1px solid rgba(148, 163, 184, 0.16);
                border-left: 4px solid {self.accent_hex};
                border-radius: 10px;
            }}
            QFrame#BmCard:hover {{
                background-color: rgba(51, 65, 85, 220);
                border: 1px solid rgba(165, 180, 252, 0.45);
                border-left: 4px solid {self.accent_hex};
            }}
        """

    def set_placeholder_mode(self, is_placeholder: bool) -> None:
        self._is_placeholder = is_placeholder
        if is_placeholder:
            self.setStyleSheet(
                """
                QFrame#BmCard {
                    background-color: rgba(99, 102, 241, 0.08);
                    border: 1.5px dashed rgba(129, 140, 248, 0.82);
                    border-left: 4px solid rgba(129, 140, 248, 0.90);
                    border-radius: 10px;
                }
                QLabel {
                    color: rgba(148, 163, 184, 0.28);
                }
                """
            )
        else:
            self.setStyleSheet(self._normal_card_stylesheet())

    def sync_item_data(self, updated_bm: dict[str, Any]) -> None:
        self.item = updated_bm
        pinned = bool(updated_bm.get("pinned"))
        title_str = ("📌 " if pinned else "") + str(updated_bm.get("title") or "未命名书签")
        self.title_lbl.setText(title_str)

    def update_url_for_width(self, panel_width: int, scale: float = 1.0) -> None:
        """Adjust URL truncation length and card badge sizing proportionally with panel width/scale."""
        char_px = max(5.5, 6.6 * scale)
        max_chars = max(36, int((panel_width - 110 * scale) / char_px))
        display_url = (
            self.url_str
            if len(self.url_str) <= max_chars
            else (self.url_str[: max(12, max_chars - 3)] + "...")
        )
        self.url_lbl.setText(f"🌐 {self.domain}  ·  {display_url}")
        if self.cat_badge is not None:
            f_badge = max(9, min(16, round(10 * scale)))
            pad_v = max(1, round(1 * scale))
            pad_h = max(4, round(6 * scale))
            self.cat_badge.setStyleSheet(
                f"font-size: {f_badge}px; color: {self.accent_hex}; background-color: {self.c_palette['bg']}; "
                f"border: 1px solid {self.c_palette['border']}; border-radius: 5px; padding: {pad_v}px {pad_h}px;"
            )

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_local = event.position().toPoint()
            self._dragging_card = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self._press_global is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            gpos = event.globalPosition().toPoint()
            if not self._dragging_card and (gpos - self._press_global).manhattanLength() >= 5:
                self._dragging_card = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                if self._panel is not None:
                    self._panel._on_bookmark_card_drag_start(self, gpos, self._press_local)
            if self._dragging_card and self._panel is not None:
                self._panel._on_bookmark_card_drag_move(self, gpos)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            was_dragging = self._dragging_card
            self._dragging_card = False
            self._press_global = None
            if was_dragging and self._panel is not None:
                self._panel._on_bookmark_card_drag_drop(self, event.globalPosition().toPoint())
                event.accept()
                return
            event.accept()
            self.open_requested.emit(self.item)
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: Any) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #0f172a; color: #f1f5f9; border: 1px solid #334155; "
            "border-radius: 8px; padding: 4px; font-size: 12px; }"
            "QMenu::item { padding: 6px 14px; border-radius: 5px; }"
            "QMenu::item:selected { background-color: #4f46e5; color: #ffffff; }"
        )
        act_open = menu.addAction("🚀 在目标浏览器中打开")
        act_copy = menu.addAction("📋 复制网址链接")
        menu.addSeparator()
        act_pin = menu.addAction("📌 取消置顶" if self.item.get("pinned") else "📌 置顶书签")
        act_top = menu.addAction("⬆️ 移至列表最顶部")
        act_edit = menu.addAction("✏️ 编辑书签...")
        if self._panel is not None and self._panel.vault.is_unlocked():
            cats = self._panel.vault.get_categories()
            if len(cats) > 1:
                sub_move = menu.addMenu("📂 移动书签到分组...")
                sub_move.setStyleSheet(menu.styleSheet())
                move_actions: dict[Any, str] = {}
                cur_cid = str(self.item.get("categoryId") or "")
                for c in cats:
                    cid = str(c.get("id") or "")
                    cname = str(c.get("name") or "分类")
                    prefix = "✓ " if cid == cur_cid else "   "
                    a = sub_move.addAction(f"{prefix}● {cname}")
                    move_actions[a] = cid
            else:
                move_actions = {}
        else:
            move_actions = {}
        menu.addSeparator()
        act_del = menu.addAction("🗑️ 删除书签")
        chosen = menu.exec(event.globalPos())
        if chosen == act_open:
            self.open_requested.emit(self.item)
        elif chosen == act_copy:
            self.copy_url_requested.emit(str(self.item.get("url") or ""))
        elif chosen == act_pin:
            self.pin_requested.emit(self.bm_id)
        elif chosen == act_top:
            self.top_requested.emit(self.bm_id)
        elif chosen == act_edit:
            self.edit_requested.emit(self.item)
        elif chosen == act_del:
            self.delete_requested.emit(self.bm_id)
        elif chosen in move_actions and self._panel is not None:
            self._panel._move_bookmark_to_category_by_id(self.bm_id, move_actions[chosen])


class _PanelResizeHandle(QWidget):
    """8-direction edge/corner resize handle for frameless BookmarksFloatingPanel."""

    _CURSORS = {
        "Left": Qt.CursorShape.SizeHorCursor,
        "Right": Qt.CursorShape.SizeHorCursor,
        "Top": Qt.CursorShape.SizeVerCursor,
        "Bottom": Qt.CursorShape.SizeVerCursor,
        "TopLeft": Qt.CursorShape.SizeFDiagCursor,
        "BottomRight": Qt.CursorShape.SizeFDiagCursor,
        "TopRight": Qt.CursorShape.SizeBDiagCursor,
        "BottomLeft": Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, panel: "BookmarksFloatingPanel", direction: str) -> None:
        super().__init__(panel)
        self.panel = panel
        self.direction = direction
        self._start_global: QPoint | None = None
        self._start_geo: QRect | None = None
        self.setMouseTracking(True)
        self.setCursor(self._CURSORS.get(direction, Qt.CursorShape.ArrowCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(15, 23, 42, 4);")

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(15, 23, 42, 4))
        painter.end()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_global = event.globalPosition().toPoint()
            self._start_geo = QRect(self.panel.geometry())
            if self.panel.isVisible():
                try:
                    self.grabMouse()
                except Exception:
                    pass
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if (
            self._start_global is not None
            and self._start_geo is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            self.panel._resize_from_handle(
                self.direction,
                self._start_geo,
                self._start_global,
                event.globalPosition().toPoint(),
                event.modifiers(),
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if QWidget.mouseGrabber() is self:
                try:
                    self.releaseMouse()
                except Exception:
                    pass
            self._start_global = None
            self._start_geo = None
            self.panel._save_panel_size_to_config()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CategoryPillButton(QPushButton):
    """Draggable, scrollable, and reorderable category pill button with Blink-style placeholder & highlights."""

    def __init__(
        self,
        text: str,
        cat_id: str,
        cat_name: str,
        cat_obj: dict[str, Any] | None,
        panel: "BookmarksFloatingPanel",
        is_movable: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.cat_id = cat_id
        self.cat_name = cat_name
        self.cat_obj = cat_obj
        self.panel = panel
        self.is_movable = is_movable
        self._normal_qss = ""
        self._is_placeholder = False
        self._press_global: QPoint | None = None
        self._press_local: QPoint = QPoint(18, 12)
        self._press_scroll_val: int = 0
        self._drag_mode: str | None = None  # None | 'reorder' | 'pan'
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_pill_style(self, qss: str) -> None:
        self._normal_qss = qss
        if not self._is_placeholder:
            self.setStyleSheet(qss)

    def set_placeholder_mode(self, is_placeholder: bool) -> None:
        self._is_placeholder = is_placeholder
        if is_placeholder:
            scale = getattr(self.panel, "_ui_scale", 1.0)
            f_sz = max(10, min(18, round(11 * scale)))
            pad_v = max(2, round(3 * scale))
            pad_h = max(7, round(10 * scale))
            rad = max(9, round(12 * scale))
            self.setStyleSheet(
                f"QPushButton {{ background-color: rgba(99, 102, 241, 0.08); "
                f"color: rgba(148, 163, 184, 0.22); "
                f"border: 1.5px dashed rgba(129, 140, 248, 0.85); border-radius: {rad}px; "
                f"padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; }}"
            )
        else:
            self.setStyleSheet(self._normal_qss)

    def set_neighbor_highlight(self, highlighted: bool) -> None:
        if self._is_placeholder:
            return
        if highlighted:
            scale = getattr(self.panel, "_ui_scale", 1.0)
            f_sz = max(10, min(18, round(11 * scale)))
            pad_v = max(2, round(3 * scale))
            pad_h = max(7, round(10 * scale))
            rad = max(9, round(12 * scale))
            self.setStyleSheet(
                f"QPushButton {{ background-color: rgba(99, 102, 241, 0.22); color: #e0e7ff; "
                f"border: 1.5px solid rgba(129, 140, 248, 0.78); border-radius: {rad}px; "
                f"padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; font-weight: 700; }}"
            )
        else:
            self.setStyleSheet(self._normal_qss)

    def set_drop_target_highlight(self, highlighted: bool) -> None:
        if highlighted:
            scale = getattr(self.panel, "_ui_scale", 1.0)
            f_sz = max(10, min(18, round(11 * scale)))
            pad_v = max(2, round(3 * scale))
            pad_h = max(7, round(10 * scale))
            rad = max(9, round(12 * scale))
            self.setStyleSheet(
                f"QPushButton {{ background-color: rgba(16, 185, 129, 0.26); color: #6ee7b7; "
                f"border: 1.5px solid #10b981; border-radius: {rad}px; "
                f"padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; font-weight: 800; }}"
            )
        else:
            self.setStyleSheet(self._normal_qss)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_local = event.position().toPoint()
            hbar = self.panel.cat_scroll.horizontalScrollBar()
            self._press_scroll_val = hbar.value() if hbar is not None else 0
            self._drag_mode = None
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self._press_global is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            gpos = event.globalPosition().toPoint()
            delta = gpos - self._press_global
            if self._drag_mode is None and delta.manhattanLength() >= 4:
                if self.is_movable:
                    self._drag_mode = "reorder"
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    self.panel._on_category_pill_drag_start(self, gpos, self._press_local)
                else:
                    self._drag_mode = "pan"
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)

            if self._drag_mode == "reorder":
                self.panel._on_category_pill_drag_move(self, gpos)
                event.accept()
                return
            if self._drag_mode == "pan":
                hbar = self.panel.cat_scroll.horizontalScrollBar()
                if hbar is not None:
                    hbar.setValue(self._press_scroll_val - delta.x())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            mode = self._drag_mode
            self._drag_mode = None
            self._press_global = None
            if mode == "reorder":
                self.panel._on_category_pill_drag_finish(self)
                event.accept()
                return
            if mode == "pan":
                event.accept()
                return
            event.accept()
            self.panel._select_category(self.cat_id)
            return
        super().mouseReleaseEvent(event)


class CategoryBarScrollArea(QScrollArea):
    """Horizontal/Multi-row category bar supporting mouse-wheel horizontal scroll and grab-panning."""

    def __init__(self, panel: "BookmarksFloatingPanel", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panel = panel
        self._pan_start_global: QPoint | None = None
        self._pan_start_val: int = 0

    def wheelEvent(self, event: Any) -> None:
        if getattr(self.panel, "_cat_wrap_mode", False):
            super().wheelEvent(event)
            return
        hbar = self.horizontalScrollBar()
        if hbar is not None and hbar.maximum() > 0:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta != 0:
                step = -int(delta * 0.65)
                hbar.setValue(hbar.value() + step)
                event.accept()
                return
        super().wheelEvent(event)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._pan_start_global = event.globalPosition().toPoint()
            hbar = self.horizontalScrollBar()
            self._pan_start_val = hbar.value() if hbar is not None else 0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self._pan_start_global is not None and (
            event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.MiddleButton)
        ):
            dx = event.globalPosition().toPoint().x() - self._pan_start_global.x()
            hbar = self.horizontalScrollBar()
            if hbar is not None:
                hbar.setValue(self._pan_start_val - dx)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if self._pan_start_global is not None:
            self._pan_start_global = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)




class BookmarksFloatingPanel(QWidget):
    """Popup dark-cyber Encrypted Bookmark Manager (Method B popup from Clock Orb)."""

    state_changed = pyqtSignal(bool, bool, str)  # (unlocked, is_visible, accent_hex)

    _BASE_W = 420
    _BASE_H = 540
    _MIN_W = 320
    _MIN_H = 380
    _HANDLE_MARGIN = 10

    def __init__(
        self,
        vault: BookmarksVault | None = None,
        parent: QWidget | None = None,
        config_getter: Callable[[], dict[str, Any]] | None = None,
        config_saver: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.vault = vault or get_bookmarks_vault()
        self._config_getter = config_getter
        self._config_saver = config_saver
        self._pinned_panel = False
        self._modal_open = False
        self._in_setup_key_step = False
        self._pending_setup_recovery_key = ""
        self._selected_category_id = "all"
        self._target_mode = "auto"  # 'auto' | 'custom' | 'system'
        self._custom_target: dict[str, Any] | None = None
        self._cached_last_browser: dict[str, Any] | None = None
        self._drag_offset: QPoint | None = None
        self._edge_resize_dir: str | None = None
        self._edge_resize_start_global: QPoint | None = None
        self._edge_resize_start_geo: QRect | None = None
        self._ui_scale: float = 1.0
        self._cat_wrap_mode: bool = False
        self._last_wrap_reflow_w: int = 0
        self._category_pill_widgets: list[CategoryPillButton] = []
        self._cat_btn_all: CategoryPillButton | None = None
        self._cat_btn_add: QPushButton | None = None
        self._cat_single_row_layout: QHBoxLayout | None = None
        self._card_widgets: list[BookmarkCardWidget] = []
        self._bm_render_limit: int = 120
        self._current_filtered_items: list[dict[str, Any]] = []
        self._load_more_btn: QPushButton | None = None
        self._drag_avatar: _DragFloatingAvatar | None = None
        self._drag_avatar_offset: QPoint = QPoint(18, 12)
        self._last_drag_global: QPoint = QPoint(0, 0)
        self._drag_tilt: float = 0.0
        self._last_cat_swap_time: float = 0.0
        self._last_bm_swap_time: float = 0.0

        init_w, init_h = self._BASE_W, self._BASE_H
        if self._config_getter is not None:
            try:
                cfg = self._config_getter() or {}
                b_cfg = cfg.get("bookmarks") if isinstance(cfg.get("bookmarks"), dict) else {}
                init_w = max(self._MIN_W, min(1400, int(b_cfg.get("panel_width", self._BASE_W))))
                init_h = max(self._MIN_H, min(1200, int(b_cfg.get("panel_height", self._BASE_H))))
                self._cat_wrap_mode = bool(b_cfg.get("cat_wrap_mode", False))
            except Exception:
                init_w, init_h = self._BASE_W, self._BASE_H

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(self._MIN_W, self._MIN_H)
        self.resize(init_w, init_h)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.root_frame = QFrame(self)
        self.root_frame.setObjectName("BlinkPanelRoot")
        self.root_frame.setStyleSheet(PANEL_STYLE)
        outer.addWidget(self.root_frame)

        self.main_lay = QVBoxLayout(self.root_frame)
        self.main_lay.setContentsMargins(14, 12, 14, 10)
        self.main_lay.setSpacing(10)

        # ── Top Header Bar (Draggable) ──
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(6)
        self.brand_lbl = QLabel("✨ 灵动书签")
        self.brand_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #f8fafc;")
        hdr_row.addWidget(self.brand_lbl)

        self.count_badge = QLabel("AES-256")
        self.count_badge.setStyleSheet(
            "font-size: 10px; color: #a5b4fc; background-color: rgba(99, 102, 241, 0.2); "
            "border: 1px solid rgba(99, 102, 241, 0.45); border-radius: 6px; padding: 2px 6px;"
        )
        hdr_row.addWidget(self.count_badge)
        hdr_row.addStretch(1)

        hdr_btn_style = (
            "QPushButton { background-color: rgba(30, 41, 59, 190); color: #cbd5e1; "
            "border: 1px solid rgba(148, 163, 184, 0.22); border-radius: 7px; padding: 4px 7px; font-size: 12px; }"
            "QPushButton:hover { background-color: #4f46e5; color: #ffffff; border-color: #818cf8; }"
        )
        self.pin_panel_btn = QPushButton("📌")
        self.pin_panel_btn.setToolTip("固定面板（点击外部区域时不自动收起）")
        self.pin_panel_btn.setStyleSheet(hdr_btn_style)
        self.pin_panel_btn.clicked.connect(self._toggle_pin_panel)
        hdr_row.addWidget(self.pin_panel_btn)

        self.lock_now_btn = QPushButton("🔒")
        self.lock_now_btn.setToolTip("立即加密锁定书签保险库")
        self.lock_now_btn.setStyleSheet(hdr_btn_style)
        self.lock_now_btn.clicked.connect(self.lock_vault)
        hdr_row.addWidget(self.lock_now_btn)

        self.export_quick_btn = QPushButton("📤")
        self.export_quick_btn.setToolTip("一键导出全部书签备份 (HTML / 加密包)")
        self.export_quick_btn.setStyleSheet(hdr_btn_style)
        self.export_quick_btn.clicked.connect(self._show_export_menu)
        hdr_row.addWidget(self.export_quick_btn)

        self.more_menu_btn = QPushButton("⚙️")
        self.more_menu_btn.setToolTip("更多管理：导入书签、修改密码、生成急救码")
        self.more_menu_btn.setStyleSheet(hdr_btn_style)
        self.more_menu_btn.clicked.connect(self._show_more_menu)
        hdr_row.addWidget(self.more_menu_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setToolTip("收起面板")
        self.close_btn.setStyleSheet(hdr_btn_style)
        self.close_btn.clicked.connect(self.hide_panel)
        hdr_row.addWidget(self.close_btn)

        self.main_lay.addLayout(hdr_row)

        # ── Stacked Views: 0=FirstSetup, 1=Lock&Recovery, 2=UnlockedMain ──
        self.stack = QStackedWidget()
        self.main_lay.addWidget(self.stack, 1)

        self._build_page0_setup()
        self._build_page1_lock_and_recovery()
        self._build_page2_unlocked_main()

        # ── Footer Status Bar + Resize Hint ──
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        self.footer_lbl = QLabel("🛡️ AES-256-GCM 本地加密 · 四周边缘可拖拽缩放")
        self.footer_lbl.setStyleSheet("font-size: 11px; color: #64748b;")
        footer_row.addWidget(self.footer_lbl, 1)

        self.size_grip = QSizeGrip(self.root_frame)
        self.size_grip.setFixedSize(14, 14)
        self.size_grip.setToolTip("拖拽面板任意边缘或四角可自由缩放面板并等比例放大缩小字体")
        self.size_grip.setStyleSheet("background: transparent;")
        footer_row.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self.main_lay.addLayout(footer_row)

        # ── 8-Direction Frameless Edge/Corner Resize Handles ──
        self._resize_handles: dict[str, _PanelResizeHandle] = {}
        for direction in (
            "Left",
            "Right",
            "Top",
            "Bottom",
            "TopLeft",
            "TopRight",
            "BottomLeft",
            "BottomRight",
        ):
            h_widget = _PanelResizeHandle(self, direction)
            h_widget.raise_()
            self._resize_handles[direction] = h_widget
        self._place_resize_handles()

        self._load_cached_recovery_key_if_present()
        self._refresh_view_state()
        self._apply_proportional_scale()

    def _load_cached_recovery_key_if_present(self) -> None:
        """Load the most recently saved recovery key from Desktop if present so user can re-copy/save easily."""
        import re

        if getattr(self.vault, "vault_path", Path()).name != "blink-vault.json":
            return
        if not self.vault.is_initialized():
            return
        candidates = [
            _get_windows_desktop_dir() / "灵动书签-安全急救码.txt",
            Path.home() / "Desktop" / "灵动书签-安全急救码.txt",
        ]
        for p in candidates:
            if p.is_file():
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                    m = re.search(r"(BK-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})", txt)
                    if m:
                        self._pending_setup_recovery_key = m.group(1)
                        if hasattr(self, "setup_key_label"):
                            self.setup_key_label.setText(self._pending_setup_recovery_key)
                        return
                except Exception:
                    pass

    # ── Page 0: First-Time Master Password Setup & In-Panel Recovery Key Step ──
    def _build_page0_setup(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(0)

        self.setup_sub_stack = QStackedWidget()
        lay.addWidget(self.setup_sub_stack)

        # Sub-page 0: Password Input Form
        sp_form = QWidget()
        f_lay = QVBoxLayout(sp_form)
        f_lay.setContentsMargins(4, 8, 4, 8)
        f_lay.setSpacing(11)

        hero = QLabel("🔐 欢迎启用灵动书签保险库")
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.setStyleSheet("font-size: 16px; font-weight: 800; color: #f8fafc;")
        f_lay.addWidget(hero)

        sub = QLabel(
            "首次使用请设置您的 <b>主密码</b>。<br>"
            "系统将同时为您生成一组 <b>16 位安全急救码</b>：未来若忘记密码，"
            "凭急救码即可直接重置密码，<span style='color:#6ee7b7;'>所有书签 100% 完整无损保留！</span>"
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(
            "font-size: 12px; color: #cbd5e1; background-color: rgba(30, 41, 59, 160); "
            "border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 10px; padding: 10px;"
        )
        f_lay.addWidget(sub)

        f_lay.addWidget(QLabel("设置主密码（至少 4 个字符）："))
        self.setup_pwd1 = QLineEdit()
        self.setup_pwd1.setEchoMode(QLineEdit.EchoMode.Password)
        self.setup_pwd1.setPlaceholderText("输入您的主密码...")
        self.setup_pwd1.returnPressed.connect(lambda: self.setup_pwd2.setFocus())
        f_lay.addWidget(self.setup_pwd1)

        f_lay.addWidget(QLabel("确认主密码："))
        self.setup_pwd2 = QLineEdit()
        self.setup_pwd2.setEchoMode(QLineEdit.EchoMode.Password)
        self.setup_pwd2.setPlaceholderText("再次输入主密码...")
        self.setup_pwd2.returnPressed.connect(self._handle_first_time_setup)
        f_lay.addWidget(self.setup_pwd2)

        self.setup_err_lbl = QLabel("")
        self.setup_err_lbl.setWordWrap(True)
        self.setup_err_lbl.setStyleSheet("font-size: 12px; color: #fda4af;")
        f_lay.addWidget(self.setup_err_lbl)

        self.btn_init_vault = QPushButton("🛡️ 启用加密书签库并生成急救码")
        self.btn_init_vault.setObjectName("PrimaryBtn")
        self.btn_init_vault.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_init_vault.setMinimumHeight(38)
        self.btn_init_vault.clicked.connect(self._handle_first_time_setup)
        f_lay.addWidget(self.btn_init_vault)
        f_lay.addStretch(1)
        self.setup_sub_stack.addWidget(sp_form)

        # Sub-page 1: In-Panel 16-Char Emergency Recovery Key Card (Zero Modal Deadlock)
        sp_key = QWidget()
        k_lay = QVBoxLayout(sp_key)
        k_lay.setContentsMargins(4, 8, 4, 8)
        k_lay.setSpacing(11)

        k_hdr = QLabel("🛡️ 请妥善保存您的 16 位安全急救码")
        k_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        k_hdr.setStyleSheet("font-size: 15px; font-weight: 800; color: #f8fafc;")
        k_lay.addWidget(k_hdr)

        k_desc = QLabel(
            "您的书签库已启用 <b>AES-256-GCM 硬件级加密</b>。<br>"
            "若日后忘记主密码，凭下方 <b>16 位安全急救码</b> 即可直接重置密码，"
            "<span style='color:#6ee7b7;font-weight:700;'>且之前保存的所有书签将 100% 完整无损保留！</span>"
        )
        k_desc.setWordWrap(True)
        k_desc.setStyleSheet(
            "font-size: 12px; color: #cbd5e1; background-color: rgba(30, 41, 59, 160); "
            "border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 10px; padding: 10px;"
        )
        k_lay.addWidget(k_desc)

        key_box = QFrame()
        key_box.setStyleSheet(
            "QFrame { background-color: rgba(30, 41, 59, 235); border: 1px dashed #818cf8; border-radius: 10px; }"
        )
        kb_layout = QVBoxLayout(key_box)
        kb_layout.setContentsMargins(12, 12, 12, 12)
        self.setup_key_label = QLabel("")
        self.setup_key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setup_key_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setup_key_label.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 17px; "
            "font-weight: 700; color: #fde047; letter-spacing: 1.4px; border: none;"
        )
        kb_layout.addWidget(self.setup_key_label)
        k_lay.addWidget(key_box)

        self.setup_key_status_lbl = QLabel("")
        self.setup_key_status_lbl.setWordWrap(True)
        self.setup_key_status_lbl.setStyleSheet("font-size: 12px; color: #6ee7b7; font-weight: 600;")
        k_lay.addWidget(self.setup_key_status_lbl)

        act_row = QHBoxLayout()
        act_row.setSpacing(8)
        self.setup_copy_key_btn = QPushButton("📋 复制急救码")
        self.setup_copy_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setup_copy_key_btn.setMinimumHeight(34)
        self.setup_copy_key_btn.clicked.connect(self._on_setup_copy_key)

        self.setup_save_txt_btn = QPushButton("💾 保存为 TXT 文件...")
        self.setup_save_txt_btn.setObjectName("EmeraldBtn")
        self.setup_save_txt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setup_save_txt_btn.setMinimumHeight(34)
        self.setup_save_txt_btn.clicked.connect(lambda: self._on_setup_save_txt())

        act_row.addWidget(self.setup_copy_key_btn, 1)
        act_row.addWidget(self.setup_save_txt_btn, 1)
        k_lay.addLayout(act_row)

        self.setup_finish_btn = QPushButton("✅ 我已妥善保存，进入灵动书签")
        self.setup_finish_btn.setObjectName("PrimaryBtn")
        self.setup_finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setup_finish_btn.setMinimumHeight(40)
        self.setup_finish_btn.clicked.connect(self._finish_first_time_setup)
        k_lay.addWidget(self.setup_finish_btn)
        k_lay.addStretch(1)
        self.setup_sub_stack.addWidget(sp_key)

        self.stack.addWidget(page)

    # ── Page 1: Lock Screen & Lossless Recovery View ──
    def _build_page1_lock_and_recovery(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 12, 10, 12)

        self.lock_sub_stack = QStackedWidget()
        lay.addWidget(self.lock_sub_stack)

        # Sub-page 0: Standard Password Unlock
        sp_unlock = QWidget()
        ul_lay = QVBoxLayout(sp_unlock)
        ul_lay.setContentsMargins(4, 16, 4, 10)
        ul_lay.setSpacing(12)

        lock_icon = QLabel("🔒")
        lock_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lock_icon.setStyleSheet("font-size: 36px;")
        ul_lay.addWidget(lock_icon)

        lock_title = QLabel("灵动书签保险库已加密锁定")
        lock_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lock_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        ul_lay.addWidget(lock_title)

        lock_hint = QLabel("请输入主密码解锁您的私密书签与分类")
        lock_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lock_hint.setStyleSheet("font-size: 12px; color: #94a3b8;")
        ul_lay.addWidget(lock_hint)

        self.unlock_pwd_edit = QLineEdit()
        self.unlock_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.unlock_pwd_edit.setPlaceholderText("输入主密码（按 Enter 键快速解锁）")
        self.unlock_pwd_edit.setMinimumHeight(36)
        self.unlock_pwd_edit.returnPressed.connect(self._handle_unlock)
        ul_lay.addWidget(self.unlock_pwd_edit)

        self.unlock_err_lbl = QLabel("")
        self.unlock_err_lbl.setWordWrap(True)
        self.unlock_err_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.unlock_err_lbl.setStyleSheet("font-size: 12px; color: #fda4af;")
        ul_lay.addWidget(self.unlock_err_lbl)

        btn_unlock = QPushButton("🔓 解锁书签保险库")
        btn_unlock.setObjectName("PrimaryBtn")
        btn_unlock.setMinimumHeight(38)
        btn_unlock.clicked.connect(self._handle_unlock)
        ul_lay.addWidget(btn_unlock)

        btn_forgot = QPushButton("忘记密码？使用 16 位安全急救码无损重置 →")
        btn_forgot.setObjectName("GhostBtn")
        btn_forgot.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_forgot.clicked.connect(lambda: self.lock_sub_stack.setCurrentIndex(1))
        ul_lay.addWidget(btn_forgot, 0, Qt.AlignmentFlag.AlignCenter)
        ul_lay.addStretch(1)
        self.lock_sub_stack.addWidget(sp_unlock)

        # Sub-page 1: Lossless Password Reset via Recovery Key (Strategy 2)
        sp_recover = QWidget()
        rc_lay = QVBoxLayout(sp_recover)
        rc_lay.setContentsMargins(4, 8, 4, 8)
        rc_lay.setSpacing(10)

        rc_title = QLabel("🛡️ 急救码无损找回书签与重置密码")
        rc_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #fde047;")
        rc_lay.addWidget(rc_title)

        rc_desc = QLabel(
            "输入您保存的 <b>16 位安全急救码 (BK-XXXX-...)</b> 并设置新主密码。<br>"
            "<span style='color:#6ee7b7;'>系统将无损解封主密钥，您之前保存的所有书签 100% 完整保留！</span>"
        )
        rc_desc.setWordWrap(True)
        rc_desc.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        rc_lay.addWidget(rc_desc)

        rc_lay.addWidget(QLabel("16 位安全急救码："))
        self.recover_key_input = QLineEdit()
        self.recover_key_input.setPlaceholderText("BK-XXXX-XXXX-XXXX-XXXX")
        rc_lay.addWidget(self.recover_key_input)

        rc_lay.addWidget(QLabel("设置新的主密码（至少 4 位）："))
        self.recover_new_pwd = QLineEdit()
        self.recover_new_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.recover_new_pwd.setPlaceholderText("输入新主密码")
        self.recover_new_pwd.returnPressed.connect(self._handle_inline_recovery)
        rc_lay.addWidget(self.recover_new_pwd)

        self.recover_err_lbl = QLabel("")
        self.recover_err_lbl.setWordWrap(True)
        self.recover_err_lbl.setStyleSheet("font-size: 12px; color: #fda4af;")
        rc_lay.addWidget(self.recover_err_lbl)

        btn_do_rec = QPushButton("🛡️ 验证急救码并无损恢复全部书签")
        btn_do_rec.setObjectName("EmeraldBtn")
        btn_do_rec.setMinimumHeight(36)
        btn_do_rec.clicked.connect(self._handle_inline_recovery)
        rc_lay.addWidget(btn_do_rec)

        btn_back_unlock = QPushButton("← 返回主密码解锁")
        btn_back_unlock.setObjectName("GhostBtn")
        btn_back_unlock.clicked.connect(lambda: self.lock_sub_stack.setCurrentIndex(0))
        rc_lay.addWidget(btn_back_unlock, 0, Qt.AlignmentFlag.AlignCenter)
        rc_lay.addStretch(1)
        self.lock_sub_stack.addWidget(sp_recover)

        self.stack.addWidget(page)


    # ── Page 2: Unlocked Main Bookmark Manager View ──
    def _build_page2_unlocked_main(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # Row 1: Browser Delivery Target Selector Bar
        target_row = QHBoxLayout()
        target_row.setSpacing(6)
        self.browser_target_btn = QPushButton("🎯 智能投递：自动跟随当前活动浏览器窗口 ▾")
        self.browser_target_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browser_target_btn.setToolTip(
            "点击切换书签打开方式：\n"
            "• 智能跟随当前活动浏览器及分身配置 (Edge / Chrome / Brave 等)\n"
            "• 固定投递到指定浏览器分身 Profile\n"
            "• 使用系统默认浏览器打开"
        )
        self.browser_target_btn.setStyleSheet(
            "QPushButton { background-color: rgba(30, 41, 59, 200); color: #93c5fd; "
            "border: 1px solid rgba(59, 130, 246, 0.35); border-radius: 8px; "
            "padding: 5px 10px; font-size: 11px; text-align: left; }"
            "QPushButton:hover { background-color: rgba(37, 99, 235, 0.28); border-color: #60a5fa; color: #eff6ff; }"
        )
        self.browser_target_btn.clicked.connect(self._show_browser_target_menu)
        target_row.addWidget(self.browser_target_btn, 1)
        lay.addLayout(target_row)

        # Row 2: Search Box + Quick Add Bookmark + Batch Paste Spreadsheet Buttons
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索书签（按 Ctrl+V 可直接粘贴谷歌表格超链接）...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.installEventFilter(self)
        self.search_edit.textChanged.connect(lambda _t: self._rebuild_bookmark_cards(reset_limit=True))
        search_row.addWidget(self.search_edit, 1)

        self.paste_bm_btn = QPushButton("📋 粘贴表格")
        self.paste_bm_btn.setObjectName("EmeraldBtn")
        self.paste_bm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paste_bm_btn.setToolTip(
            "从谷歌表格 / Excel / 剪贴板一键批量粘贴超链接 (快捷键 Ctrl+V)\n"
            "• 模式一：复制 100+ 个超链接一键粘贴到当前选中的分组文件夹\n"
            "• 模式二：复制 A-Z 多列表格（第 1 行为分组标题，第 2 行起为超链接）自动建组并归类"
        )
        self.paste_bm_btn.clicked.connect(lambda: self._on_paste_clipboard_clicked())
        search_row.addWidget(self.paste_bm_btn)

        self.add_bm_btn = QPushButton("＋ 新增")
        self.add_bm_btn.setObjectName("PrimaryBtn")
        self.add_bm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_bm_btn.setToolTip("手动新增单条书签")
        self.add_bm_btn.clicked.connect(self._on_add_bookmark_clicked)
        search_row.addWidget(self.add_bm_btn)
        lay.addLayout(search_row)

        # Row 3: Scrollable & Draggable Category Pills Bar + ‹ › Scroll & ☷ Multi-Row Wrap Controls
        cat_row = QHBoxLayout()
        cat_row.setContentsMargins(0, 0, 0, 0)
        cat_row.setSpacing(4)

        nav_btn_qss = (
            "QPushButton { background-color: rgba(30, 41, 59, 210); color: #cbd5e1; "
            "border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 7px; "
            "padding: 2px 6px; font-size: 13px; font-weight: 700; min-width: 22px; }"
            "QPushButton:hover { background-color: #4f46e5; color: #ffffff; border-color: #818cf8; }"
        )
        self.cat_prev_btn = QPushButton("‹")
        self.cat_prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cat_prev_btn.setToolTip("向左滚动分组栏（也可直接在分组栏上滚动鼠标滚轮）")
        self.cat_prev_btn.setStyleSheet(nav_btn_qss)
        self.cat_prev_btn.clicked.connect(lambda: self._scroll_category_bar(-175))
        self.cat_prev_btn.hide()

        self.cat_scroll = CategoryBarScrollArea(self)
        self.cat_scroll.setFixedHeight(34)
        self.cat_scroll.setWidgetResizable(True)
        self.cat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cat_bar_container = QWidget()
        self.cat_bar_container.setStyleSheet("background: transparent;")
        self.cat_bar_layout = QVBoxLayout(self.cat_bar_container)
        self.cat_bar_layout.setContentsMargins(0, 2, 0, 2)
        self.cat_bar_layout.setSpacing(5)
        self.cat_scroll.setWidget(self.cat_bar_container)
        cat_row.addWidget(self.cat_scroll, 1)

        self.cat_next_btn = QPushButton("›")
        self.cat_next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cat_next_btn.setToolTip("向右滚动分组栏（也可直接在分组栏上滚动鼠标滚轮）")
        self.cat_next_btn.setStyleSheet(nav_btn_qss)
        self.cat_next_btn.clicked.connect(lambda: self._scroll_category_bar(175))
        self.cat_next_btn.hide()

        self.cat_wrap_btn = QPushButton("☷")
        self.cat_wrap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cat_wrap_btn.setToolTip(
            "展开 / 收起全部分组多行视图\n"
            "• 按住任意分组标签左右拖拽可直接调整分组排列顺序\n"
            "• 按住下方书签卡片拖到分组标签上可快速归类"
        )
        self.cat_wrap_btn.setStyleSheet(nav_btn_qss)
        self.cat_wrap_btn.clicked.connect(self._toggle_category_wrap_mode)
        cat_row.addWidget(self.cat_wrap_btn)

        lay.addLayout(cat_row)

        # Row 4: Bookmark Cards Scroll Area
        self.bm_scroll = QScrollArea()
        self.bm_scroll.setWidgetResizable(True)
        self.bm_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bm_list_container = QWidget()
        self.bm_list_container.setStyleSheet("background: transparent;")
        self.bm_list_layout = QVBoxLayout(self.bm_list_container)
        self.bm_list_layout.setContentsMargins(0, 2, 4, 4)
        self.bm_list_layout.setSpacing(7)
        self.bm_scroll.setWidget(self.bm_list_container)
        vbar = self.bm_scroll.verticalScrollBar()
        if vbar is not None:
            vbar.valueChanged.connect(self._on_bm_scroll_value_changed)
        lay.addWidget(self.bm_scroll, 1)

        self.stack.addWidget(page)

    # ── State & Refresh Logic ───────────────────────────────────────────────
    def capture_foreground_browser_snapshot(self) -> None:
        """Capture the currently active top-level browser window before panel takes focus."""
        try:
            wins = detect_active_browser_windows()
            if wins:
                self._cached_last_browser = wins[0]
        except Exception:
            pass
        self._update_browser_target_badge()

    def _update_browser_target_badge(self) -> None:
        if not hasattr(self, "browser_target_btn"):
            return
        if self._target_mode == "system":
            self.browser_target_btn.setText("🌐 投递目标：系统默认浏览器 ▾")
        elif self._target_mode == "custom" and self._custom_target:
            lbl = self._custom_target.get("label") or "指定浏览器配置"
            self.browser_target_btn.setText(f"🎯 固定投递：{lbl} ▾")
        else:
            if self._cached_last_browser:
                badge = self._cached_last_browser.get("display_badge") or "当前浏览器"
                self.browser_target_btn.setText(f"⚡ 智能跟随：{badge} ▾")
            else:
                self.browser_target_btn.setText("⚡ 智能投递：自动跟随当前活动浏览器窗口 ▾")

    def _get_active_accent_hex(self) -> str:
        if not self.vault.is_unlocked():
            return "#6366f1"
        try:
            for c in self.vault.get_categories():
                if c.get("id") == self._selected_category_id:
                    ckey = str(c.get("color") or "indigo")
                    return CATEGORY_COLORS.get(ckey, CATEGORY_COLORS["indigo"])["hex"]
        except Exception:
            pass
        return "#10b981"

    def _emit_state(self) -> None:
        self.state_changed.emit(
            self.vault.is_unlocked(),
            self.isVisible(),
            self._get_active_accent_hex(),
        )

    def _refresh_view_state(self) -> None:
        if not self.vault.is_initialized():
            self._in_setup_key_step = False
            self.stack.setCurrentIndex(0)
            if hasattr(self, "setup_sub_stack"):
                self.setup_sub_stack.setCurrentIndex(0)
            self.lock_now_btn.hide()
            self.count_badge.setText("待初始化")
            self.footer_lbl.setText("🛡️ 首次使用请设置主密码并妥善保存 16 位急救码")
        elif self._in_setup_key_step:
            self.stack.setCurrentIndex(0)
            if hasattr(self, "setup_sub_stack"):
                self.setup_sub_stack.setCurrentIndex(1)
            self.lock_now_btn.hide()
            self.count_badge.setText("急救码备份")
            self.footer_lbl.setText("🛡️ 请复制或保存您的 16 位安全急救码，随后点击进入书签库")
        elif not self.vault.is_unlocked():
            self.stack.setCurrentIndex(1)
            self.lock_sub_stack.setCurrentIndex(0)
            self.lock_now_btn.hide()
            self.count_badge.setText("🔒 已锁定")
            self.footer_lbl.setText("🛡️ AES-256-GCM 硬件级加密保护中")
        else:
            self.stack.setCurrentIndex(2)
            self.lock_now_btn.show()
            self._update_browser_target_badge()
            self._rebuild_category_bar()
            self._rebuild_bookmark_cards()
        self._emit_state()

    def _clear_layout_recursively(self, layout: Any, delete_widgets: bool = True) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                if delete_widgets:
                    w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout_recursively(item.layout(), delete_widgets=delete_widgets)

    def _compute_pill_style(
        self,
        is_all: bool = False,
        is_sel: bool = False,
        pal: dict[str, str] | None = None,
    ) -> str:
        scale = self._ui_scale
        f_sz = max(10, min(18, round(11 * scale)))
        pad_v = max(2, round(3 * scale))
        pad_h = max(7, round(10 * scale))
        rad = max(9, round(12 * scale))
        if is_all:
            if is_sel:
                return (
                    f"QPushButton {{ background-color: #4f46e5; color: #ffffff; border: 1px solid #818cf8; "
                    f"border-radius: {rad}px; padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; font-weight: 700; }}"
                )
            return (
                f"QPushButton {{ background-color: rgba(30,41,59,180); color: #94a3b8; "
                f"border: 1px solid rgba(148,163,184,0.2); border-radius: {rad}px; padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; }}"
                f"QPushButton:hover {{ color: #f8fafc; border-color: #6366f1; }}"
            )
        p = pal or CATEGORY_COLORS["indigo"]
        if is_sel:
            return (
                f"QPushButton {{ background-color: {p['hex']}; color: #ffffff; "
                f"border: 1px solid #ffffff; border-radius: {rad}px; padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; font-weight: 700; }}"
            )
        return (
            f"QPushButton {{ background-color: {p['bg']}; color: {p['hex']}; "
            f"border: 1px solid {p['border']}; border-radius: {rad}px; padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; }}"
            f"QPushButton:hover {{ background-color: {p['hex']}; color: #ffffff; }}"
        )

    def _rebuild_category_bar(self) -> None:
        self._clear_layout_recursively(self.cat_bar_layout, delete_widgets=True)
        self._category_pill_widgets.clear()
        self._cat_btn_all = None
        self._cat_btn_add = None
        self._cat_single_row_layout = None

        if not self.vault.is_unlocked():
            return

        cats = self.vault.get_categories()
        all_bms = self.vault.get_bookmarks()
        counts: dict[str, int] = {}
        for b in all_bms:
            cid = str(b.get("categoryId") or "")
            counts[cid] = counts.get(cid, 0) + 1

        valid_ids = {str(c.get("id")) for c in cats}
        if self._selected_category_id != "all" and self._selected_category_id not in valid_ids:
            self._selected_category_id = "all"

        all_active = self._selected_category_id == "all"
        btn_all = CategoryPillButton(
            f"全部 ({len(all_bms)})",
            cat_id="all",
            cat_name="全部",
            cat_obj=None,
            panel=self,
            is_movable=False,
            parent=self.cat_bar_container,
        )
        btn_all.setToolTip("显示全部书签（按住可左右滑动分组栏）")
        btn_all.set_pill_style(self._compute_pill_style(is_all=True, is_sel=all_active))
        self._cat_btn_all = btn_all

        for cat in cats:
            cid = str(cat.get("id") or "")
            cname = str(cat.get("name") or "分类")
            ccolor = str(cat.get("color") or "indigo")
            pal = CATEGORY_COLORS.get(ccolor, CATEGORY_COLORS["indigo"])
            c_count = counts.get(cid, 0)
            is_sel = self._selected_category_id == cid

            pill = CategoryPillButton(
                f"● {cname} ({c_count})",
                cat_id=cid,
                cat_name=cname,
                cat_obj=cat,
                panel=self,
                is_movable=True,
                parent=self.cat_bar_container,
            )
            pill.setToolTip(
                f"分组：{cname} ({c_count} 条)\n"
                "• 左键点击：筛选该分组书签\n"
                "• 按住左键左右拖拽：直接调整分组先后顺序\n"
                "• 右键点击：编辑、移动顺序或删除分组"
            )
            pill.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            pill.customContextMenuRequested.connect(
                lambda pos, c_obj=cat, btn_ref=pill: self._show_category_context_menu(
                    c_obj, btn_ref.mapToGlobal(pos)
                )
            )
            pill.set_pill_style(self._compute_pill_style(is_all=False, is_sel=is_sel, pal=pal))
            self._category_pill_widgets.append(pill)

        scale = self._ui_scale
        f_sz = max(10, min(18, round(11 * scale)))
        pad_v = max(2, round(3 * scale))
        pad_h = max(7, round(9 * scale))
        rad = max(9, round(12 * scale))
        btn_add_cat = QPushButton("＋分类", self.cat_bar_container)
        btn_add_cat.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_cat.setToolTip("新建书签分类（右键已有分类可编辑、排序或删除）")
        btn_add_cat.setStyleSheet(
            f"QPushButton {{ background-color: transparent; color: #94a3b8; "
            f"border: 1px dashed rgba(148,163,184,0.35); border-radius: {rad}px; padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; }}"
            f"QPushButton:hover {{ color: #e2e8f0; border-color: #818cf8; background-color: rgba(99,102,241,0.15); }}"
        )
        btn_add_cat.clicked.connect(self._on_add_category_clicked)
        self._cat_btn_add = btn_add_cat

        self._relayout_category_pills_preserve_widgets()

    def _relayout_category_pills_preserve_widgets(self) -> None:
        """Arrange existing category pill widgets into single-row or multi-row wrap layout without deleting them."""
        self._clear_layout_recursively(self.cat_bar_layout, delete_widgets=False)
        self._cat_single_row_layout = None
        if self._cat_btn_all is None or self._cat_btn_add is None:
            return

        scale = self._ui_scale
        all_widgets: list[QWidget] = [self._cat_btn_all, *self._category_pill_widgets, self._cat_btn_add]

        if not self._cat_wrap_mode:
            row_lay = QHBoxLayout()
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(max(5, round(6 * scale)))
            for w in all_widgets:
                row_lay.addWidget(w)
            row_lay.addStretch(1)
            self._cat_single_row_layout = row_lay
            self.cat_bar_layout.addLayout(row_lay)
            self.cat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.cat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.cat_scroll.setFixedHeight(max(32, round(34 * scale)))
            if hasattr(self, "cat_prev_btn"):
                self.cat_prev_btn.hide()
                self.cat_next_btn.hide()
        else:
            avail_w = max(240, self.width() - round(62 * scale))
            self._last_wrap_reflow_w = self.width()
            spacing = max(5, round(6 * scale))
            cur_row = QHBoxLayout()
            cur_row.setContentsMargins(0, 0, 0, 0)
            cur_row.setSpacing(spacing)
            cur_w = 0
            row_count = 1
            for w in all_widgets:
                hint_w = max(58, w.sizeHint().width())
                if cur_w > 0 and (cur_w + spacing + hint_w) > avail_w:
                    cur_row.addStretch(1)
                    self.cat_bar_layout.addLayout(cur_row)
                    cur_row = QHBoxLayout()
                    cur_row.setContentsMargins(0, 0, 0, 0)
                    cur_row.setSpacing(spacing)
                    cur_w = 0
                    row_count += 1
                cur_row.addWidget(w)
                cur_w += (spacing if cur_w > 0 else 0) + hint_w
            cur_row.addStretch(1)
            self.cat_bar_layout.addLayout(cur_row)
            self.cat_bar_layout.addStretch(1)
            self.cat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.cat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            row_h = max(28, round(31 * scale))
            target_h = min(max(76, round(138 * scale)), row_count * row_h + round(10 * scale))
            self.cat_scroll.setFixedHeight(target_h)
            if hasattr(self, "cat_prev_btn"):
                self.cat_prev_btn.hide()
                self.cat_next_btn.hide()

    def _scroll_category_bar(self, delta_px: int) -> None:
        hbar = self.cat_scroll.horizontalScrollBar()
        if hbar is not None:
            hbar.setValue(hbar.value() + int(delta_px * self._ui_scale))

    def _toggle_category_wrap_mode(self) -> None:
        self._cat_wrap_mode = not self._cat_wrap_mode
        self._update_wrap_btn_style()
        self._relayout_category_pills_preserve_widgets()
        self._save_panel_size_to_config()
        if self._cat_wrap_mode:
            self.footer_lbl.setText("☷ 已展开全部分组多行视图 · 可直接按住任意分组拖拽调整顺序")
        else:
            self.footer_lbl.setText("↔️ 已切换为单行分组栏 · 支持滚轮滑动、‹ › 翻页及拖拽分组排序")

    def _select_category(self, cat_id: str) -> None:
        self._selected_category_id = str(cat_id or "all")
        self._rebuild_category_bar()
        self._rebuild_bookmark_cards(reset_limit=True)
        self._emit_state()

    def _create_card_widget(
        self, bm: dict[str, Any], cats_map: dict[str, dict[str, Any]]
    ) -> BookmarkCardWidget:
        cat_info = cats_map.get(str(bm.get("categoryId") or ""))
        card = BookmarkCardWidget(bm, cat_info, self.bm_list_container, panel=self)
        card.update_url_for_width(self.width(), self._ui_scale)
        card.open_requested.connect(self._on_open_bookmark)
        card.pin_requested.connect(self._on_toggle_pin_bookmark)
        card.top_requested.connect(self._on_move_top_bookmark)
        card.edit_requested.connect(self._on_edit_bookmark)
        card.delete_requested.connect(self._on_delete_bookmark)
        card.copy_url_requested.connect(self._on_copy_bookmark_url)
        return card

    def _rebuild_bookmark_cards(self, reset_limit: bool = False) -> None:
        if reset_limit:
            self._bm_render_limit = 120
        self._card_widgets.clear()
        self._load_more_btn = None
        while self.bm_list_layout.count():
            item = self.bm_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self.vault.is_unlocked():
            return

        cats_map = {str(c.get("id")): c for c in self.vault.get_categories()}
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        items = self.vault.get_bookmarks(
            category_id=self._selected_category_id,
            search_query=query,
        )
        self._current_filtered_items = items
        total_all = len(self.vault.get_bookmarks())
        self.count_badge.setText(f"{total_all} 条书签")

        if not items:
            empty_lbl = QLabel(
                "🔍 未找到匹配的书签\n可尝试更换搜索词或切换分类"
                if query
                else "✨ 当前分类暂无书签\n点击上方【📋 粘贴表格 (Ctrl+V)】批量导入谷歌表格超链接，或点【＋ 新增】"
            )
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            f_empty = max(11, round(12 * self._ui_scale))
            empty_lbl.setStyleSheet(f"color: #64748b; font-size: {f_empty}px; padding: 42px 10px;")
            self.bm_list_layout.addWidget(empty_lbl)
            self.bm_list_layout.addStretch(1)
            return

        visible_slice = items[: self._bm_render_limit]
        for bm in visible_slice:
            card = self._create_card_widget(bm, cats_map)
            self._card_widgets.append(card)
            self.bm_list_layout.addWidget(card)

        remaining = len(items) - len(visible_slice)
        if remaining > 0:
            more_btn = QPushButton(
                f"👇 继续加载更多书签（已显示 {len(visible_slice)} / {len(items)} 条，向下滚动自动加载）"
            )
            more_btn.setObjectName("GhostBtn")
            more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            more_btn.clicked.connect(self._load_more_bookmark_cards)
            self._load_more_btn = more_btn
            self.bm_list_layout.addWidget(more_btn)

        self.bm_list_layout.addStretch(1)

    def _load_more_bookmark_cards(self) -> None:
        if not self.vault.is_unlocked():
            return
        already = len(self._card_widgets)
        total = len(self._current_filtered_items)
        if already >= total:
            return
        next_limit = min(total, already + 120)
        self._bm_render_limit = next_limit
        cats_map = {str(c.get("id")): c for c in self.vault.get_categories()}

        # Remove trailing stretch and load_more_btn temporarily
        if self._load_more_btn is not None:
            self.bm_list_layout.removeWidget(self._load_more_btn)
            self._load_more_btn.deleteLater()
            self._load_more_btn = None
        if self.bm_list_layout.count() > 0:
            last_item = self.bm_list_layout.itemAt(self.bm_list_layout.count() - 1)
            if last_item is not None and last_item.spacerItem() is not None:
                self.bm_list_layout.takeAt(self.bm_list_layout.count() - 1)

        for bm in self._current_filtered_items[already:next_limit]:
            card = self._create_card_widget(bm, cats_map)
            self._card_widgets.append(card)
            self.bm_list_layout.addWidget(card)

        remaining = total - len(self._card_widgets)
        if remaining > 0:
            more_btn = QPushButton(
                f"👇 继续加载更多书签（已显示 {len(self._card_widgets)} / {total} 条，向下滚动自动加载）"
            )
            more_btn.setObjectName("GhostBtn")
            more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            more_btn.clicked.connect(self._load_more_bookmark_cards)
            self._load_more_btn = more_btn
            self.bm_list_layout.addWidget(more_btn)

        self.bm_list_layout.addStretch(1)

    def _on_bm_scroll_value_changed(self, val: int) -> None:
        vbar = self.bm_scroll.verticalScrollBar()
        if vbar is None or vbar.maximum() <= 0:
            return
        if val >= vbar.maximum() - 90 and len(self._card_widgets) < len(self._current_filtered_items):
            self._load_more_bookmark_cards()


    # ── Vault Auth & Recovery Handlers ──────────────────────────────────────
    def _handle_first_time_setup(self) -> None:
        p1 = self.setup_pwd1.text().strip()
        p2 = self.setup_pwd2.text().strip()
        if len(p1) < 4:
            self.setup_err_lbl.setText("⚠️ 主密码长度至少需要 4 个字符")
            return
        if p1 != p2:
            self.setup_err_lbl.setText("⚠️ 两次输入的密码不一致，请重新核对")
            return
        try:
            recovery_key = self.vault.initialize_vault(p1)
        except Exception as exc:
            self.setup_err_lbl.setText(f"⚠️ 初始化失败: {exc}")
            return

        self.setup_pwd1.clear()
        self.setup_pwd2.clear()
        self.setup_err_lbl.setText("")

        self._pending_setup_recovery_key = recovery_key
        self._in_setup_key_step = True
        self.setup_key_label.setText(recovery_key)

        ok_copy = copy_text_to_clipboard(recovery_key)
        self.setup_key_status_lbl.setStyleSheet("font-size: 12px; color: #6ee7b7; font-weight: 600;")
        if ok_copy:
            self.setup_key_status_lbl.setText(
                "✅ 已将急救码复制到系统剪贴板（可直接 Ctrl+V 粘贴），也可点击下方保存为 TXT 文件"
            )
        else:
            self.setup_key_status_lbl.setText("💡 请点击下方【📋 复制急救码】或【💾 保存为 TXT 文件...】进行备份")

        self._refresh_view_state()

    def _on_setup_copy_key(self) -> None:
        key = self._pending_setup_recovery_key or self.setup_key_label.text().strip()
        ok = copy_text_to_clipboard(key)
        self.setup_key_status_lbl.setStyleSheet(
            f"font-size: 12px; color: {'#6ee7b7' if ok else '#fda4af'}; font-weight: 600;"
        )
        self.setup_key_status_lbl.setText(
            "✅ 已复制急救码到系统剪贴板（可直接 Ctrl+V 粘贴）！"
            if ok
            else "⚠️ 复制失败，请直接鼠标选中上方黄色急救码按 Ctrl+C"
        )

    def _on_setup_save_txt(self, dest_path: str | None = None) -> None:
        key = self._pending_setup_recovery_key or self.setup_key_label.text().strip()
        default_name = f"灵动书签-安全急救码-{datetime.date.today().isoformat()}.txt"
        if dest_path:
            path_str = dest_path
        else:
            self._modal_open = True
            try:
                path_str = _safe_save_file_dialog(
                    self,
                    "保存灵动书签安全急救码",
                    str(_get_windows_desktop_dir() / default_name),
                    "文本文件 (*.txt);;所有文件 (*.*)",
                )
            finally:
                self._modal_open = False
        if not path_str:
            return
        try:
            out_p = Path(path_str)
            out_p.write_text(format_recovery_key_txt(key), encoding="utf-8")
            self.setup_key_status_lbl.setStyleSheet("font-size: 12px; color: #6ee7b7; font-weight: 600;")
            self.setup_key_status_lbl.setText(f"✅ 已保存至: {out_p}")
        except Exception as exc:
            self.setup_key_status_lbl.setStyleSheet("font-size: 12px; color: #fda4af; font-weight: 600;")
            self.setup_key_status_lbl.setText(f"⚠️ 保存失败: {exc}")

    def _finish_first_time_setup(self) -> None:
        self._in_setup_key_step = False
        if hasattr(self, "setup_sub_stack"):
            self.setup_sub_stack.setCurrentIndex(0)
        self._refresh_view_state()
        if self.vault.is_unlocked():
            self.footer_lbl.setText("✅ 灵动书签加密库已就绪")
        else:
            self.footer_lbl.setText("🔒 请输入主密码解锁灵动书签")

    def show_recovery_key_step(self) -> None:
        """Display the in-panel 16-char Recovery Key card for copying or saving as TXT."""
        self._load_cached_recovery_key_if_present()
        if not self._pending_setup_recovery_key:
            self.open_security_dialog("regenerate")
            return
        self._in_setup_key_step = True
        self.setup_key_label.setText(self._pending_setup_recovery_key)
        self.setup_key_status_lbl.setStyleSheet("font-size: 12px; color: #6ee7b7; font-weight: 600;")
        self.setup_key_status_lbl.setText("💡 点击下方按钮可复制急救码到剪贴板，或选择位置保存为 TXT 文件")
        self._refresh_view_state()

    def _handle_unlock(self) -> None:
        pwd = self.unlock_pwd_edit.text().strip()
        ok, msg = self.vault.unlock(pwd)
        if not ok:
            self.unlock_err_lbl.setText(f"⚠️ {msg}")
            self.unlock_pwd_edit.selectAll()
            return
        self.unlock_pwd_edit.clear()
        self.unlock_err_lbl.setText("")
        self._refresh_view_state()
        self.footer_lbl.setText("🔓 保险库已解锁 · 点击书签即可投递至浏览器")

    def _handle_inline_recovery(self) -> None:
        rec_key = self.recover_key_input.text().strip()
        new_pwd = self.recover_new_pwd.text().strip()
        ok, msg = self.vault.reset_password_with_recovery_key(rec_key, new_pwd)
        if not ok:
            self.recover_err_lbl.setText(f"⚠️ {msg}")
            return
        self.recover_key_input.clear()
        self.recover_new_pwd.clear()
        self.recover_err_lbl.setText("")
        self._refresh_view_state()
        self.footer_lbl.setText(f"✅ {msg}")

    def lock_vault(self) -> None:
        self.vault.lock()
        self._refresh_view_state()
        self.footer_lbl.setText("🔒 灵动书签保险库已安全锁定")

    # ── Menus & Dialogs ─────────────────────────────────────────────────────
    def _menu_style(self) -> str:
        return (
            "QMenu { background-color: #0f172a; color: #f1f5f9; border: 1px solid #334155; "
            "border-radius: 9px; padding: 5px; font-size: 12px; }"
            "QMenu::item { padding: 6px 14px; border-radius: 5px; }"
            "QMenu::item:selected { background-color: #4f46e5; color: #ffffff; }"
        )

    def _show_browser_target_menu(self) -> None:
        self._modal_open = True
        try:
            menu = QMenu(self)
            menu.setStyleSheet(self._menu_style())

            active_badge = ""
            if self._cached_last_browser:
                active_badge = f" ({self._cached_last_browser.get('display_badge')})"
            act_auto = menu.addAction(f"⚡ 智能跟随当前活动浏览器窗口{active_badge}")
            if self._target_mode == "auto":
                act_auto.setText("✓ " + act_auto.text())

            act_sys = menu.addAction("🌐 使用系统默认浏览器打开")
            if self._target_mode == "system":
                act_sys.setText("✓ " + act_sys.text())

            profiles = discover_all_browser_profiles()
            prof_actions: dict[Any, dict[str, Any]] = {}
            if profiles:
                menu.addSeparator()
                hdr = menu.addAction("── 固定投递到指定浏览器配置 (Profile) ──")
                hdr.setEnabled(False)
                for prof in profiles[:16]:
                    lbl = prof["label"]
                    is_cur = (
                        self._target_mode == "custom"
                        and self._custom_target
                        and self._custom_target.get("key") == prof["key"]
                    )
                    act = menu.addAction(("✓ 🎯 " if is_cur else "   🎯 ") + lbl)
                    prof_actions[act] = prof

            chosen = menu.exec(
                self.browser_target_btn.mapToGlobal(QPoint(0, self.browser_target_btn.height() + 2))
            )
            if chosen == act_auto:
                self._target_mode = "auto"
                self._custom_target = None
            elif chosen == act_sys:
                self._target_mode = "system"
                self._custom_target = None
            elif chosen in prof_actions:
                self._target_mode = "custom"
                self._custom_target = prof_actions[chosen]
            self._update_browser_target_badge()
        finally:
            self._modal_open = False

    def _show_export_menu(self) -> None:
        self._modal_open = True
        try:
            menu = QMenu(self)
            menu.setStyleSheet(self._menu_style())
            act_html = menu.addAction("📤 一键导出全部书签为通用 HTML (.html)")
            act_enc = menu.addAction("🔐 导出 AES-256 加密全量备份包 (.blinkbak)")
            chosen = menu.exec(
                self.export_quick_btn.mapToGlobal(QPoint(0, self.export_quick_btn.height() + 2))
            )
            if chosen == act_html:
                ok, msg = export_bookmarks_html_interactive(self, self.vault)
                if ok:
                    self.footer_lbl.setText(msg)
            elif chosen == act_enc:
                ok, msg = export_bookmarks_encrypted_interactive(self, self.vault)
                if ok:
                    self.footer_lbl.setText(msg)
        finally:
            self._modal_open = False

    def _show_more_menu(self) -> None:
        self._modal_open = True
        try:
            menu = QMenu(self)
            menu.setStyleSheet(self._menu_style())
            act_add_cat = menu.addAction("➕ 新建书签分类...")
            menu.addSeparator()
            act_paste_sheet = menu.addAction("📋 从谷歌表格 / 剪贴板批量粘贴超链接 (Ctrl+V)...")
            act_imp_html = menu.addAction("📥 增量导入浏览器 HTML 书签...")
            act_exp_html = menu.addAction("📤 一键导出全部书签 (HTML)...")
            act_exp_enc = menu.addAction("🔐 导出加密全量备份包 (.blinkbak)...")
            act_imp_enc = menu.addAction("📦 从加密备份包 (.blinkbak) 恢复...")
            menu.addSeparator()
            act_view_key = menu.addAction("🛡️ 查看 / 备份 16 位安全急救码...")
            act_sec = menu.addAction("🔑 修改主密码 / 重新生成急救码...")
            chosen = menu.exec(
                self.more_menu_btn.mapToGlobal(QPoint(0, self.more_menu_btn.height() + 2))
            )
            if chosen == act_add_cat:
                self._on_add_category_clicked()
            elif chosen == act_paste_sheet:
                self._on_paste_clipboard_clicked()
            elif chosen == act_imp_html:
                ok, msg = import_bookmarks_html_interactive(self, self.vault)
                if ok:
                    self._refresh_view_state()
                    self.footer_lbl.setText(msg)
            elif chosen == act_exp_html:
                ok, msg = export_bookmarks_html_interactive(self, self.vault)
                if ok:
                    self.footer_lbl.setText(msg)
            elif chosen == act_exp_enc:
                ok, msg = export_bookmarks_encrypted_interactive(self, self.vault)
                if ok:
                    self.footer_lbl.setText(msg)
            elif chosen == act_imp_enc:
                ok, msg = import_bookmarks_encrypted_interactive(self, self.vault)
                if ok:
                    self._refresh_view_state()
                    self.footer_lbl.setText(msg)
            elif chosen == act_view_key:
                self.show_recovery_key_step()
            elif chosen == act_sec:
                self.open_security_dialog()
        finally:
            self._modal_open = False

    def open_security_dialog(self, initial_tab: str = "password") -> None:
        self._modal_open = True
        try:
            dlg = VaultSecurityDialog(self.vault, self, initial_tab=initial_tab)
            dlg.vault_changed.connect(self._refresh_view_state)
            dlg.exec()
            self._refresh_view_state()
        finally:
            self._modal_open = False

    # ── Category & Bookmark Actions ─────────────────────────────────────────
    def _on_paste_clipboard_clicked(
        self,
        target_category_id: str = "",
        html_override: str | None = None,
        text_override: str | None = None,
        auto_confirm_mode: str | None = None,
    ) -> bool:
        if not self.vault.is_unlocked():
            return False
        self._modal_open = True
        try:
            default_cid = (
                target_category_id
                if target_category_id and target_category_id != "all"
                else (
                    self._selected_category_id
                    if self._selected_category_id != "all"
                    else ""
                )
            )
            ok, msg, first_cid = import_bookmarks_from_clipboard_interactive(
                parent=self,
                vault=self.vault,
                default_category_id=default_cid,
                html_override=html_override,
                text_override=text_override,
                auto_confirm_mode=auto_confirm_mode,
            )
            if ok:
                if first_cid:
                    self._selected_category_id = first_cid
                self._rebuild_category_bar()
                self._rebuild_bookmark_cards(reset_limit=True)
                self.footer_lbl.setText(msg)
            return ok
        finally:
            self._modal_open = False

    def _on_add_category_clicked(self) -> None:
        if not self.vault.is_unlocked():
            return
        self._modal_open = True
        try:
            dlg = CategoryEditDialog(self, is_edit=False)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                name, color = dlg.get_values()
                cat = self.vault.add_category(name, color)
                self._selected_category_id = str(cat.get("id") or "all")
                self._rebuild_category_bar()
                self._rebuild_bookmark_cards()
                self.footer_lbl.setText(f"✅ 已新建分类「{name}」")
        finally:
            self._modal_open = False

    def _show_category_context_menu(self, cat: dict[str, Any], global_pos: QPoint) -> None:
        self._modal_open = True
        try:
            cats = self.vault.get_categories()
            cid = str(cat.get("id") or "")
            cname = str(cat.get("name") or "分类")
            cur_idx = next((i for i, c in enumerate(cats) if str(c.get("id")) == cid), -1)

            menu = QMenu(self)
            menu.setStyleSheet(self._menu_style())
            act_paste_here = menu.addAction(f"📋 粘贴剪贴板超链接到「{cname}」...")
            menu.addSeparator()
            act_edit = menu.addAction("✏️ 编辑分类名称与颜色...")
            menu.addSeparator()
            act_left = menu.addAction("⬅️ 向左前移该分组")
            act_left.setEnabled(cur_idx > 0)
            act_right = menu.addAction("➡️ 向右后移该分组")
            act_right.setEnabled(0 <= cur_idx < len(cats) - 1)
            act_first = menu.addAction("⏫ 移至第一位（紧随“全部”之后）")
            act_first.setEnabled(cur_idx > 0)
            menu.addSeparator()
            act_clean_empty = menu.addAction("🧹 清理所有空分组 (0 条书签)")
            menu.addSeparator()
            act_del = menu.addAction("🗑️ 删除该分类（书签将自动移入默认分类）")

            chosen = menu.exec(global_pos)
            if chosen == act_paste_here:
                self._selected_category_id = cid
                self._rebuild_category_bar()
                self._rebuild_bookmark_cards(reset_limit=True)
                self._on_paste_clipboard_clicked(target_category_id=cid)
            elif chosen == act_edit:
                dlg = CategoryEditDialog(
                    self,
                    initial_name=cname,
                    initial_color=str(cat.get("color") or "indigo"),
                    is_edit=True,
                )
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    name, color = dlg.get_values()
                    self.vault.update_category(cid, name, color)
                    self._rebuild_category_bar()
                    self._rebuild_bookmark_cards()
            elif chosen == act_left and cur_idx > 0:
                self.vault.move_category_to_index(cid, cur_idx - 1)
                self._rebuild_category_bar()
                self.footer_lbl.setText(f"⬅️ 已前移分组「{cname}」")
            elif chosen == act_right and 0 <= cur_idx < len(cats) - 1:
                self.vault.move_category_to_index(cid, cur_idx + 1)
                self._rebuild_category_bar()
                self.footer_lbl.setText(f"➡️ 已后移分组「{cname}」")
            elif chosen == act_first and cur_idx > 0:
                self.vault.move_category_to_index(cid, 0)
                self._rebuild_category_bar()
                hbar = self.cat_scroll.horizontalScrollBar()
                if hbar is not None:
                    hbar.setValue(0)
                self.footer_lbl.setText(f"⏫ 已将分组「{cname}」移至第一位")
            elif chosen == act_clean_empty:
                self._clean_empty_categories()
            elif chosen == act_del:
                try:
                    self.vault.delete_category(cid, delete_bookmarks=False)
                    if self._selected_category_id == cid:
                        self._selected_category_id = "all"
                    self._rebuild_category_bar()
                    self._rebuild_bookmark_cards(reset_limit=True)
                    self.footer_lbl.setText("✅ 已删除分类（原分类下的书签已安全移入默认分类）")
                except ValueError as exc:
                    _show_topmost_message(self, "提示", str(exc), is_warning=True)
        finally:
            self._modal_open = False

    def _clean_empty_categories(self) -> None:
        if not self.vault.is_unlocked():
            return
        cats = self.vault.get_categories()
        bms = self.vault.get_bookmarks()
        used_cids = {str(b.get("categoryId") or "") for b in bms}
        removed = 0
        for c in list(cats):
            cid = str(c.get("id") or "")
            if cid not in used_cids and len(self.vault.get_categories()) > 1:
                try:
                    self.vault.delete_category(cid, delete_bookmarks=False)
                    removed += 1
                except Exception:
                    pass
        self._rebuild_category_bar()
        self._rebuild_bookmark_cards()
        if removed > 0:
            self.footer_lbl.setText(f"🧹 已清理 {removed} 个空分组")
        else:
            self.footer_lbl.setText("✨ 当前没有可清理的空分组")

    def _clear_drag_avatar(self) -> None:
        if self._drag_avatar is not None:
            self._drag_avatar.hide()
            self._drag_avatar.deleteLater()
            self._drag_avatar = None
        self._drag_tilt = 0.0

    def _on_category_pill_drag_start(
        self, pill: CategoryPillButton, global_pos: QPoint, press_local: QPoint
    ) -> None:
        self._clear_drag_avatar()
        try:
            pixmap = pill.grab()
        except Exception:
            pixmap = QPixmap(max(48, pill.width()), max(24, pill.height()))
            pixmap.fill(QColor("#4f46e5"))
        pill.set_placeholder_mode(True)
        rad = max(9, round(12 * self._ui_scale))
        self._drag_avatar = _DragFloatingAvatar(
            self.root_frame, pixmap, scale_factor=1.08, border_radius=rad
        )
        self._drag_avatar_offset = QPoint(
            max(8, min(pill.width() - 8, press_local.x())),
            max(6, min(pill.height() - 6, press_local.y())),
        )
        self._last_drag_global = global_pos
        self._drag_tilt = 0.0
        self._last_cat_swap_time = 0.0
        root_pt = self.root_frame.mapFromGlobal(global_pos)
        self._drag_avatar.move_avatar(
            root_pt.x() - self._drag_avatar_offset.x(),
            root_pt.y() - self._drag_avatar_offset.y(),
        )
        self._drag_avatar.show()
        self._drag_avatar.raise_()
        self.footer_lbl.setText(
            f"✨ 正在拖拽调整分组「{pill.cat_name}」顺序（左右平滑换位，靠边自动滚屏）..."
        )

    def _on_category_pill_drag_move(self, pill: CategoryPillButton, global_pos: QPoint) -> None:
        """Blink-style floating avatar + midpoint slot swapping with 55ms cooldown."""
        if pill not in self._category_pill_widgets:
            return
        if self._drag_avatar is None:
            self._on_category_pill_drag_start(pill, global_pos, pill._press_local)

        # 1. Update floating avatar position & velocity micro-tilt
        if self._drag_avatar is not None:
            vx = global_pos.x() - self._last_drag_global.x()
            self._last_drag_global = global_pos
            target_tilt = max(-3.5, min(3.5, vx * 0.22))
            self._drag_tilt = self._drag_tilt * 0.65 + target_tilt * 0.35
            self._drag_avatar.set_tilt(self._drag_tilt)
            root_pt = self.root_frame.mapFromGlobal(global_pos)
            self._drag_avatar.move_avatar(
                root_pt.x() - self._drag_avatar_offset.x(),
                root_pt.y() - self._drag_avatar_offset.y(),
            )
            self._drag_avatar.raise_()

        # 2. Auto-scroll horizontal category bar if near left/right edge
        if not self._cat_wrap_mode:
            vp = self.cat_scroll.viewport()
            if vp is not None:
                vp_pos = vp.mapFromGlobal(global_pos)
                hbar = self.cat_scroll.horizontalScrollBar()
                if hbar is not None and hbar.maximum() > 0:
                    if vp_pos.x() < 38:
                        hbar.setValue(hbar.value() - max(6, int((38 - vp_pos.x()) * 0.42)))
                    elif vp_pos.x() > vp.width() - 38:
                        hbar.setValue(hbar.value() + max(6, int((vp_pos.x() - (vp.height() if vp.width() <= 0 else vp.width() - 38)) * 0.42)))

        # 3. Neighbor proximity highlight & midpoint crossing check
        local_pos = self.cat_bar_container.mapFromGlobal(global_pos)
        cur_idx = self._category_pill_widgets.index(pill)

        nearest_pill: CategoryPillButton | None = None
        nearest_dist = 999999.0
        for other in self._category_pill_widgets:
            if other is pill:
                continue
            dist = abs(local_pos.x() - other.geometry().center().x()) + abs(
                local_pos.y() - other.geometry().center().y()
            )
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_pill = other
        for other in self._category_pill_widgets:
            if other is not pill:
                other.set_neighbor_highlight(other is nearest_pill and nearest_dist < 60)

        now = time.monotonic()
        if self._last_cat_swap_time > 0.0 and (now - self._last_cat_swap_time) < 0.055:
            return

        if not self._cat_wrap_mode and self._cat_single_row_layout is not None:
            target_idx = cur_idx
            if cur_idx > 0:
                for i in range(cur_idx - 1, -1, -1):
                    if local_pos.x() < self._category_pill_widgets[i].geometry().center().x():
                        target_idx = i
                    else:
                        break
            if target_idx == cur_idx and cur_idx < len(self._category_pill_widgets) - 1:
                for i in range(cur_idx + 1, len(self._category_pill_widgets)):
                    if local_pos.x() > self._category_pill_widgets[i].geometry().center().x():
                        target_idx = i
                    else:
                        break
            if target_idx != cur_idx:
                self._category_pill_widgets.pop(cur_idx)
                self._category_pill_widgets.insert(target_idx, pill)
                self._cat_single_row_layout.removeWidget(pill)
                # +1 offset because _cat_btn_all is at index 0
                self._cat_single_row_layout.insertWidget(target_idx + 1, pill)
                self._last_cat_swap_time = now
        else:
            for idx, other in enumerate(self._category_pill_widgets):
                if other is pill:
                    continue
                if other.geometry().contains(local_pos):
                    self._category_pill_widgets.pop(cur_idx)
                    self._category_pill_widgets.insert(idx, pill)
                    self._relayout_category_pills_preserve_widgets()
                    self._last_cat_swap_time = now
                    break

    def _on_category_pill_drag_finish(self, pill: CategoryPillButton) -> None:
        self._clear_drag_avatar()
        for p in self._category_pill_widgets:
            p.set_placeholder_mode(False)
            p.set_neighbor_highlight(False)
        ordered_ids = [p.cat_id for p in self._category_pill_widgets if p.cat_id and p.cat_id != "all"]
        if ordered_ids and self.vault.is_unlocked():
            try:
                self.vault.reorder_categories(ordered_ids)
                self.footer_lbl.setText(f"✅ 已保存分组「{pill.cat_name}」的新排列顺序")
            except Exception as exc:
                self.footer_lbl.setText(f"⚠️ 保存分组顺序失败: {exc}")

    def _find_category_pill_at_global(self, global_pos: QPoint) -> CategoryPillButton | None:
        for pill in self._category_pill_widgets:
            if not pill.isVisible():
                continue
            local_pt = pill.mapFromGlobal(global_pos)
            if pill.rect().contains(local_pt):
                return pill
        return None

    def _on_bookmark_card_drag_start(
        self, card: BookmarkCardWidget, global_pos: QPoint, press_local: QPoint
    ) -> None:
        self._clear_drag_avatar()
        try:
            pixmap = card.grab()
        except Exception:
            pixmap = QPixmap(max(180, card.width()), max(44, card.height()))
            pixmap.fill(QColor("#1e293b"))
        card.set_placeholder_mode(True)
        self._drag_avatar = _DragFloatingAvatar(
            self.root_frame, pixmap, scale_factor=1.03, border_radius=10
        )
        self._drag_avatar_offset = QPoint(
            max(14, min(max(24, card.width() - 14), press_local.x())),
            max(10, min(max(18, card.height() - 10), press_local.y())),
        )
        self._last_drag_global = global_pos
        self._drag_tilt = 0.0
        self._last_bm_swap_time = 0.0
        root_pt = self.root_frame.mapFromGlobal(global_pos)
        self._drag_avatar.move_avatar(
            root_pt.x() - self._drag_avatar_offset.x(),
            root_pt.y() - self._drag_avatar_offset.y(),
        )
        self._drag_avatar.show()
        self._drag_avatar.raise_()

    def _on_bookmark_card_drag_move(self, card: BookmarkCardWidget, global_pos: QPoint) -> None:
        """Vertical drag-and-drop reordering of bookmark cards + cross-category drop onto category pills."""
        if self._drag_avatar is None:
            self._on_bookmark_card_drag_start(card, global_pos, card._press_local)

        # 1. Update floating avatar position & subtle velocity tilt
        if self._drag_avatar is not None:
            vx = global_pos.x() - self._last_drag_global.x()
            vy = global_pos.y() - self._last_drag_global.y()
            self._last_drag_global = global_pos
            target_tilt = max(-2.6, min(2.6, (vx + vy * 0.35) * 0.16))
            self._drag_tilt = self._drag_tilt * 0.68 + target_tilt * 0.32
            self._drag_avatar.set_tilt(self._drag_tilt)
            root_pt = self.root_frame.mapFromGlobal(global_pos)
            self._drag_avatar.move_avatar(
                root_pt.x() - self._drag_avatar_offset.x(),
                root_pt.y() - self._drag_avatar_offset.y(),
            )
            self._drag_avatar.raise_()

        # 2. Auto-scroll category bar if dragging near left/right edge of cat_scroll
        if not self._cat_wrap_mode:
            vp = self.cat_scroll.viewport()
            if vp is not None:
                vp_pt = vp.mapFromGlobal(global_pos)
                if -24 <= vp_pt.y() <= vp.height() + 36:
                    hbar = self.cat_scroll.horizontalScrollBar()
                    if hbar is not None and hbar.maximum() > 0:
                        if vp_pt.x() < 40:
                            hbar.setValue(hbar.value() - 12)
                        elif vp_pt.x() > vp.width() - 40:
                            hbar.setValue(hbar.value() + 12)

        target_pill = self._find_category_pill_at_global(global_pos)
        for pill in self._category_pill_widgets:
            pill.set_drop_target_highlight(pill is target_pill)

        bm_title = str(card.item.get("title") or "书签")[:18]
        if target_pill is not None:
            self.footer_lbl.setText(
                f"📂 松开鼠标即可将「{bm_title}」归入分组【{target_pill.cat_name}】"
            )
            return

        # 3. Vertical auto-scroll inside bm_scroll when near top/bottom edges
        bm_vp = self.bm_scroll.viewport()
        if bm_vp is not None:
            bvp_pt = bm_vp.mapFromGlobal(global_pos)
            vbar = self.bm_scroll.verticalScrollBar()
            if vbar is not None and vbar.maximum() > 0:
                if 0 <= bvp_pt.y() < 44:
                    vbar.setValue(vbar.value() - max(6, int((44 - bvp_pt.y()) * 0.42)))
                elif bm_vp.height() - 44 < bvp_pt.y() <= bm_vp.height() + 20:
                    vbar.setValue(vbar.value() + max(6, int((bvp_pt.y() - (bm_vp.height() - 44)) * 0.42)))

        # 4. Vertical midpoint crossing slot swap in bm_list_layout
        if card in self._card_widgets and len(self._card_widgets) > 1:
            now = time.monotonic()
            if self._last_bm_swap_time == 0.0 or (now - self._last_bm_swap_time) >= 0.055:
                local_pos = self.bm_list_container.mapFromGlobal(global_pos)
                cur_idx = self._card_widgets.index(card)
                target_idx = cur_idx
                if cur_idx > 0:
                    for i in range(cur_idx - 1, -1, -1):
                        if local_pos.y() < self._card_widgets[i].geometry().center().y():
                            target_idx = i
                        else:
                            break
                if target_idx == cur_idx and cur_idx < len(self._card_widgets) - 1:
                    for i in range(cur_idx + 1, len(self._card_widgets)):
                        if local_pos.y() > self._card_widgets[i].geometry().center().y():
                            target_idx = i
                        else:
                            break
                if target_idx != cur_idx:
                    self._card_widgets.pop(cur_idx)
                    self._card_widgets.insert(target_idx, card)
                    self.bm_list_layout.removeWidget(card)
                    self.bm_list_layout.insertWidget(target_idx, card)
                    self._last_bm_swap_time = now

        self.footer_lbl.setText(
            f"↕️ 正在上下拖动调整「{bm_title}」顺序（也可拖到上方分组标签归类）..."
        )

    def _on_bookmark_card_drag_drop(self, card: BookmarkCardWidget, global_pos: QPoint) -> None:
        self._clear_drag_avatar()
        card.set_placeholder_mode(False)
        target_pill = self._find_category_pill_at_global(global_pos)
        for pill in self._category_pill_widgets:
            pill.set_drop_target_highlight(False)
        if target_pill is not None:
            self._move_bookmark_to_category_by_id(card.bm_id, target_pill.cat_id)
            return

        if self.vault.is_unlocked() and self._card_widgets:
            ordered_ids = [c.bm_id for c in self._card_widgets if c.bm_id]
            seen = set(ordered_ids)
            for tail_item in self._current_filtered_items:
                tid = str(tail_item.get("id") or "")
                if tid and tid not in seen:
                    ordered_ids.append(tid)
                    seen.add(tid)
            try:
                self.vault.reorder_bookmarks(ordered_ids, moved_bookmark_id=card.bm_id)
                query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
                refreshed = self.vault.get_bookmarks(
                    category_id=self._selected_category_id,
                    search_query=query,
                )
                self._current_filtered_items = refreshed
                by_id = {str(b.get("id")): b for b in refreshed}
                for cw in self._card_widgets:
                    if cw.bm_id in by_id:
                        cw.sync_item_data(by_id[cw.bm_id])
                bm_title = str(card.item.get("title") or "书签")[:18]
                self.footer_lbl.setText(f"✅ 已保存书签「{bm_title}」的新排列顺序")
                return
            except Exception as exc:
                self.footer_lbl.setText(f"⚠️ 保存书签顺序失败: {exc}")
                return

        self.footer_lbl.setText("🛡️ AES-256-GCM 本地加密 · 四周边缘可拖拽缩放")

    def _move_bookmark_to_category_by_id(self, bm_id: str, target_cid: str) -> None:
        if not self.vault.is_unlocked() or not bm_id or not target_cid:
            return
        try:
            updated = self.vault.move_bookmark_to_category(bm_id, target_cid)
            cats_map = {str(c.get("id")): str(c.get("name") or "分类") for c in self.vault.get_categories()}
            cname = cats_map.get(target_cid, "目标分组")
            self._rebuild_category_bar()
            self._rebuild_bookmark_cards()
            if updated:
                self.footer_lbl.setText(f"✅ 已将「{str(updated.get('title') or '')[:18]}」移入分组【{cname}】")
        except Exception as exc:
            self.footer_lbl.setText(f"⚠️ 移动分组失败: {exc}")

    def _on_add_bookmark_clicked(self) -> None:
        if not self.vault.is_unlocked():
            return
        self._modal_open = True
        try:
            cats = self.vault.get_categories()
            default_cid = (
                self._selected_category_id
                if self._selected_category_id != "all"
                else (str(cats[0]["id"]) if cats else "")
            )
            dlg = BookmarkEditDialog(cats, self, default_category_id=default_cid)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                vals = dlg.get_values()
                bm = self.vault.add_bookmark(
                    title=vals["title"],
                    url=vals["url"],
                    category_id=vals["category_id"],
                    note=vals["note"],
                    pinned=vals["pinned"],
                )
                self._rebuild_category_bar()
                self._rebuild_bookmark_cards()
                self.footer_lbl.setText(f"✅ 已保存书签「{bm.get('title')}」")
        finally:
            self._modal_open = False

    def _on_edit_bookmark(self, item: dict[str, Any]) -> None:
        if not self.vault.is_unlocked():
            return
        self._modal_open = True
        try:
            cats = self.vault.get_categories()
            dlg = BookmarkEditDialog(cats, self, initial_item=item)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                vals = dlg.get_values()
                self.vault.update_bookmark(
                    bookmark_id=str(item.get("id") or ""),
                    title=vals["title"],
                    url=vals["url"],
                    category_id=vals["category_id"],
                    note=vals["note"],
                    pinned=vals["pinned"],
                )
                self._rebuild_category_bar()
                self._rebuild_bookmark_cards()
                self.footer_lbl.setText(f"✅ 已更新书签「{vals['title']}」")
        finally:
            self._modal_open = False

    def _on_delete_bookmark(self, bm_id: str) -> None:
        if not self.vault.is_unlocked():
            return
        self.vault.delete_bookmark(bm_id)
        self._rebuild_category_bar()
        self._rebuild_bookmark_cards()
        self.footer_lbl.setText("🗑️ 已删除书签")

    def _on_toggle_pin_bookmark(self, bm_id: str) -> None:
        if not self.vault.is_unlocked():
            return
        self.vault.toggle_pin_bookmark(bm_id)
        self._rebuild_bookmark_cards()

    def _on_move_top_bookmark(self, bm_id: str) -> None:
        if not self.vault.is_unlocked():
            return
        self.vault.move_bookmark_to_top(bm_id)
        self._rebuild_bookmark_cards()

    def _on_copy_bookmark_url(self, url: str) -> None:
        copy_text_to_clipboard(str(url or ""))
        self.footer_lbl.setText("📋 已复制链接地址到剪贴板")

    def _on_open_bookmark(self, item: dict[str, Any]) -> None:
        url = str(item.get("url") or "")
        if not url:
            return
        try:
            _ok, status_msg = open_url_in_browser(
                url,
                target_mode=self._target_mode,
                custom_target=self._custom_target,
                cached_last_active=self._cached_last_browser,
            )
            self.footer_lbl.setText(f"🚀 {status_msg}")
            if not self._pinned_panel:
                QTimer.singleShot(160, self.hide_panel)
        except Exception as exc:
            self.footer_lbl.setText(f"⚠️ 打开链接失败: {exc}")

    # ── Positioning, Pinning, Auto-Collapse, Edge Resizing & Proportional Scaling ──
    def _update_pin_btn_style(self) -> None:
        scale = self._ui_scale
        f_sz = max(11, min(18, round(12 * scale)))
        pad_v = max(3, round(4 * scale))
        pad_h = max(5, round(7 * scale))
        rad = max(6, round(7 * scale))
        if self._pinned_panel:
            self.pin_panel_btn.setStyleSheet(
                f"QPushButton {{ background-color: #4f46e5; color: #ffffff; "
                f"border: 1px solid #818cf8; border-radius: {rad}px; padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; }}"
            )
        else:
            self.pin_panel_btn.setStyleSheet(
                f"QPushButton {{ background-color: rgba(30, 41, 59, 190); color: #cbd5e1; "
                f"border: 1px solid rgba(148, 163, 184, 0.22); border-radius: {rad}px; padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; }}"
                f"QPushButton:hover {{ background-color: #4f46e5; color: #ffffff; border-color: #818cf8; }}"
            )

    def _update_wrap_btn_style(self) -> None:
        if not hasattr(self, "cat_wrap_btn"):
            return
        scale = self._ui_scale
        f_sz = max(11, min(19, round(13 * scale)))
        pad_v = max(2, round(2 * scale))
        pad_h = max(5, round(6 * scale))
        rad = max(6, round(7 * scale))
        min_w = max(20, round(22 * scale))
        if self._cat_wrap_mode:
            self.cat_wrap_btn.setStyleSheet(
                f"QPushButton {{ background-color: #4f46e5; color: #ffffff; "
                f"border: 1px solid #818cf8; border-radius: {rad}px; "
                f"padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; font-weight: 700; min-width: {min_w}px; }}"
            )
        else:
            self.cat_wrap_btn.setStyleSheet(
                f"QPushButton {{ background-color: rgba(30, 41, 59, 210); color: #cbd5e1; "
                f"border: 1px solid rgba(148, 163, 184, 0.25); border-radius: {rad}px; "
                f"padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; font-weight: 700; min-width: {min_w}px; }}"
                f"QPushButton:hover {{ background-color: #4f46e5; color: #ffffff; border-color: #818cf8; }}"
            )

    def _toggle_pin_panel(self) -> None:
        self._pinned_panel = not self._pinned_panel
        self._update_pin_btn_style()
        if self._pinned_panel:
            self.footer_lbl.setText("📌 面板已固定常驻（点击外部不会自动收起）")
        else:
            self.footer_lbl.setText("📌 已取消固定（点击外部区域将自动收起）")

    def _place_resize_handles(self) -> None:
        if not hasattr(self, "_resize_handles") or not self._resize_handles:
            return
        w, h = self.width(), self.height()
        m = self._HANDLE_MARGIN
        c = m * 2 + 2  # Corner hit-box size (22px)
        self._resize_handles["TopLeft"].setGeometry(0, 0, c, c)
        self._resize_handles["TopRight"].setGeometry(w - c, 0, c, c)
        self._resize_handles["BottomLeft"].setGeometry(0, h - c, c, c)
        self._resize_handles["BottomRight"].setGeometry(w - c, h - c, c, c)
        self._resize_handles["Top"].setGeometry(c, 0, max(10, w - 2 * c), m)
        self._resize_handles["Bottom"].setGeometry(c, h - m, max(10, w - 2 * c), m)
        self._resize_handles["Left"].setGeometry(0, c, m, max(10, h - 2 * c))
        self._resize_handles["Right"].setGeometry(w - m, c, m, max(10, h - 2 * c))
        for hw in self._resize_handles.values():
            hw.show()
            hw.raise_()

    def _detect_edge_direction(self, pos: QPoint) -> str | None:
        w, h = self.width(), self.height()
        m = self._HANDLE_MARGIN
        c = m * 2 + 2
        x, y = pos.x(), pos.y()
        if x <= c and y <= c:
            return "TopLeft"
        if x >= w - c and y <= c:
            return "TopRight"
        if x <= c and y >= h - c:
            return "BottomLeft"
        if x >= w - c and y >= h - c:
            return "BottomRight"
        if x <= m:
            return "Left"
        if x >= w - m:
            return "Right"
        if y <= m:
            return "Top"
        if y >= h - m:
            return "Bottom"
        return None

    def _resize_from_handle(
        self,
        direction: str,
        start_geo: QRect,
        start_global: QPoint,
        cur_global: QPoint,
        modifiers: Any = None,
    ) -> None:
        dx = cur_global.x() - start_global.x()
        dy = cur_global.y() - start_global.y()

        left = start_geo.left()
        top = start_geo.top()
        width = start_geo.width()
        height = start_geo.height()

        if "Right" in direction:
            width = max(self._MIN_W, min(1400, start_geo.width() + dx))
        elif "Left" in direction:
            new_w = max(self._MIN_W, min(1400, start_geo.width() - dx))
            left = start_geo.left() + (start_geo.width() - new_w)
            width = new_w

        if "Bottom" in direction:
            height = max(self._MIN_H, min(1200, start_geo.height() + dy))
        elif "Top" in direction:
            new_h = max(self._MIN_H, min(1200, start_geo.height() - dy))
            top = start_geo.top() + (start_geo.height() - new_h)
            height = new_h

        # Hold Shift on single-edge drag to lock exact aspect ratio if desired
        if modifiers is not None and (modifiers & Qt.KeyboardModifier.ShiftModifier):
            aspect = self._BASE_H / float(self._BASE_W)
            if direction in ("Left", "Right"):
                height = max(self._MIN_H, min(1200, round(width * aspect)))
            elif direction in ("Top", "Bottom"):
                width = max(self._MIN_W, min(1400, round(height / aspect)))

        self.setGeometry(left, top, width, height)

    def _apply_proportional_scale(self) -> None:
        w = max(self._MIN_W, self.width())
        h = max(self._MIN_H, self.height())
        scale = max(0.82, min(1.80, (w / float(self._BASE_W)) * 0.62 + (h / float(self._BASE_H)) * 0.38))
        self._ui_scale = scale

        self.root_frame.setStyleSheet(_build_scaled_panel_style(scale))

        mx = max(10, round(14 * scale))
        my_top = max(9, round(12 * scale))
        my_bot = max(8, round(10 * scale))
        self.main_lay.setContentsMargins(mx, my_top, mx, my_bot)
        self.main_lay.setSpacing(max(7, round(10 * scale)))

        f_brand = max(13, min(25, round(15 * scale)))
        self.brand_lbl.setStyleSheet(f"font-size: {f_brand}px; font-weight: 800; color: #f8fafc;")

        f_badge = max(9, min(16, round(10 * scale)))
        pad_bv = max(1, round(2 * scale))
        pad_bh = max(4, round(6 * scale))
        self.count_badge.setStyleSheet(
            f"font-size: {f_badge}px; color: #a5b4fc; background-color: rgba(99, 102, 241, 0.2); "
            f"border: 1px solid rgba(99, 102, 241, 0.45); border-radius: 6px; padding: {pad_bv}px {pad_bh}px;"
        )

        f_hdr = max(11, min(18, round(12 * scale)))
        pad_hv = max(3, round(4 * scale))
        pad_hh = max(5, round(7 * scale))
        rad_h = max(6, round(7 * scale))
        hdr_btn_style = (
            f"QPushButton {{ background-color: rgba(30, 41, 59, 190); color: #cbd5e1; "
            f"border: 1px solid rgba(148, 163, 184, 0.22); border-radius: {rad_h}px; "
            f"padding: {pad_hv}px {pad_hh}px; font-size: {f_hdr}px; }}"
            f"QPushButton:hover {{ background-color: #4f46e5; color: #ffffff; border-color: #818cf8; }}"
        )
        for btn in (self.lock_now_btn, self.export_quick_btn, self.more_menu_btn, self.close_btn):
            btn.setStyleSheet(hdr_btn_style)
        self._update_pin_btn_style()

        if hasattr(self, "browser_target_btn"):
            f_bt = max(10, min(17, round(11 * scale)))
            pad_btv = max(4, round(5 * scale))
            pad_bth = max(8, round(10 * scale))
            self.browser_target_btn.setStyleSheet(
                f"QPushButton {{ background-color: rgba(30, 41, 59, 200); color: #93c5fd; "
                f"border: 1px solid rgba(59, 130, 246, 0.35); border-radius: 8px; "
                f"padding: {pad_btv}px {pad_bth}px; font-size: {f_bt}px; text-align: left; }}"
                f"QPushButton:hover {{ background-color: rgba(37, 99, 235, 0.28); border-color: #60a5fa; color: #eff6ff; }}"
            )

        if hasattr(self, "cat_prev_btn"):
            f_nav = max(11, min(19, round(13 * scale)))
            pad_nv = max(2, round(2 * scale))
            pad_nh = max(5, round(6 * scale))
            min_nw = max(20, round(22 * scale))
            nav_qss = (
                f"QPushButton {{ background-color: rgba(30, 41, 59, 210); color: #cbd5e1; "
                f"border: 1px solid rgba(148, 163, 184, 0.25); border-radius: {rad_h}px; "
                f"padding: {pad_nv}px {pad_nh}px; font-size: {f_nav}px; font-weight: 700; min-width: {min_nw}px; }}"
                f"QPushButton:hover {{ background-color: #4f46e5; color: #ffffff; border-color: #818cf8; }}"
            )
            self.cat_prev_btn.setStyleSheet(nav_qss)
            self.cat_next_btn.setStyleSheet(nav_qss)
            self._update_wrap_btn_style()

        # Scale category pills & scroll area height
        if self._cat_btn_all is not None:
            self._cat_btn_all.set_pill_style(
                self._compute_pill_style(is_all=True, is_sel=(self._selected_category_id == "all"))
            )
        for pill in self._category_pill_widgets:
            c_obj = pill.cat_obj or {}
            ccolor = str(c_obj.get("color") or "indigo")
            pal = CATEGORY_COLORS.get(ccolor, CATEGORY_COLORS["indigo"])
            is_sel = self._selected_category_id == pill.cat_id
            pill.set_pill_style(self._compute_pill_style(is_all=False, is_sel=is_sel, pal=pal))
        if self._cat_btn_add is not None:
            f_sz = max(10, min(18, round(11 * scale)))
            pad_v = max(2, round(3 * scale))
            pad_h = max(7, round(9 * scale))
            rad = max(9, round(12 * scale))
            self._cat_btn_add.setStyleSheet(
                f"QPushButton {{ background-color: transparent; color: #94a3b8; "
                f"border: 1px dashed rgba(148,163,184,0.35); border-radius: {rad}px; padding: {pad_v}px {pad_h}px; font-size: {f_sz}px; }}"
                f"QPushButton:hover {{ color: #e2e8f0; border-color: #818cf8; background-color: rgba(99,102,241,0.15); }}"
            )

        if not self._cat_wrap_mode and hasattr(self, "cat_scroll"):
            self.cat_scroll.setFixedHeight(max(32, round(34 * scale)))
        elif self._cat_wrap_mode and abs(w - self._last_wrap_reflow_w) >= 22:
            self._relayout_category_pills_preserve_widgets()

        # Scale bookmark cards URL truncation & category badge
        for card in self._card_widgets:
            card.update_url_for_width(w, scale)

        f_foot = max(10, min(16, round(11 * scale)))
        self.footer_lbl.setStyleSheet(f"font-size: {f_foot}px; color: #64748b;")
        self._place_resize_handles()

    def _save_panel_size_to_config(self) -> None:
        if self._config_getter is None:
            return
        try:
            cfg = self._config_getter()
            if isinstance(cfg, dict):
                b_cfg = cfg.setdefault("bookmarks", {})
                if isinstance(b_cfg, dict):
                    b_cfg["panel_width"] = self.width()
                    b_cfg["panel_height"] = self.height()
                    b_cfg["cat_wrap_mode"] = self._cat_wrap_mode
                if self._config_saver is not None:
                    self._config_saver()
        except Exception:
            pass

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._place_resize_handles()
        self._apply_proportional_scale()

    def show_near_orb(self, orb_widget: QWidget | None = None, anchor_window: QWidget | None = None) -> None:
        """Capture active browser, position panel centered on the screen, and show."""
        self.capture_foreground_browser_snapshot()
        self._refresh_view_state()
        self._apply_proportional_scale()

        pw, ph = self.width(), self.height()
        ref_point = QCursor.pos()
        if orb_widget is not None and orb_widget.isVisible():
            ref_point = orb_widget.mapToGlobal(orb_widget.rect().center())
        elif anchor_window is not None and anchor_window.isVisible():
            ref_point = anchor_window.frameGeometry().center()

        screen = QApplication.screenAt(ref_point) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            target_x = avail.left() + (avail.width() - pw) // 2
            target_y = avail.top() + (avail.height() - ph) // 2
            target_x = max(avail.left() + 8, min(target_x, avail.right() - pw - 8))
            target_y = max(avail.top() + 8, min(target_y, avail.bottom() - ph - 8))
        else:
            target_x = max(40, ref_point.x() - pw // 2)
            target_y = max(40, ref_point.y() - ph // 2)

        self.move(target_x, target_y)
        self.show()
        self.raise_()
        self._place_resize_handles()
        self.activateWindow()
        if self.stack.currentIndex() == 1 and hasattr(self, "unlock_pwd_edit"):
            self.unlock_pwd_edit.setFocus()
        elif self.stack.currentIndex() == 2 and hasattr(self, "search_edit"):
            self.search_edit.setFocus()
        self._emit_state()

    def hide_panel(self) -> None:
        if not self.isVisible():
            return
        self._clear_drag_avatar()
        self.hide()
        # Check config if auto-lock on close is enabled
        if self._config_getter is not None:
            try:
                cfg = self._config_getter() or {}
                b_cfg = cfg.get("bookmarks") if isinstance(cfg.get("bookmarks"), dict) else {}
                if bool(b_cfg.get("auto_lock_on_close", False)) and self.vault.is_unlocked():
                    self.vault.lock()
            except Exception:
                pass
        self._emit_state()

    def toggle_near_orb(self, orb_widget: QWidget | None = None, anchor_window: QWidget | None = None) -> None:
        if self.isVisible():
            self.hide_panel()
        else:
            self.show_near_orb(orb_widget=orb_widget, anchor_window=anchor_window)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate:
            if (
                self.isVisible()
                and not self._pinned_panel
                and not self._modal_open
                and not self._in_setup_key_step
                and self.vault.is_initialized()
            ):
                QTimer.singleShot(110, self._check_auto_hide_on_deactivate)
        return super().event(event)

    def _check_auto_hide_on_deactivate(self) -> None:
        if (
            not self.isVisible()
            or self._pinned_panel
            or self._modal_open
            or self._in_setup_key_step
            or not self.vault.is_initialized()
        ):
            return
        active_win = QApplication.activeWindow()
        if active_win is self or (active_win is not None and self.isAncestorOf(active_win)):
            return
        if QApplication.activePopupWidget() is not None or QApplication.activeModalWidget() is not None:
            return
        self.hide_panel()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos_pt = event.position().toPoint()
            edge_dir = self._detect_edge_direction(pos_pt)
            if edge_dir is not None:
                self._edge_resize_dir = edge_dir
                self._edge_resize_start_global = event.globalPosition().toPoint()
                self._edge_resize_start_geo = QRect(self.geometry())
                event.accept()
                return
            m = self._HANDLE_MARGIN
            if (
                m < pos_pt.x() < (self.width() - m)
                and m < pos_pt.y() <= max(48, round(54 * self._ui_scale))
            ):
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if (
            self._edge_resize_dir is not None
            and self._edge_resize_start_global is not None
            and self._edge_resize_start_geo is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            self._resize_from_handle(
                self._edge_resize_dir,
                self._edge_resize_start_geo,
                self._edge_resize_start_global,
                event.globalPosition().toPoint(),
                event.modifiers(),
            )
            event.accept()
            return
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if self._edge_resize_dir is not None:
            self._edge_resize_dir = None
            self._edge_resize_start_global = None
            self._edge_resize_start_geo = None
            self._save_panel_size_to_config()
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _should_intercept_paste_as_bookmarks(self, from_search_box: bool = False) -> bool:
        """Check whether Ctrl+V should launch the Google Sheets / Clipboard batch bookmark importer."""
        if not self.vault.is_unlocked() or self.stack.currentIndex() != 2:
            return False
        html_text, plain_text = get_clipboard_html_and_text()
        parsed = parse_clipboard_spreadsheet(html_text=html_text, plain_text=plain_text)
        total_links = int(parsed.get("total_links") or 0)
        if total_links <= 0:
            return False
        if not from_search_box:
            return True
        low_html = (html_text or "").lower()
        if "<table" in low_html or "<a " in low_html or "data-sheets-hyperlink" in low_html:
            return True
        if total_links >= 2:
            return True
        raw_plain = (plain_text or "").strip()
        if "\n" in raw_plain or "\t" in raw_plain:
            return True
        if raw_plain.lower().startswith(("http://", "https://")):
            return True
        return False

    def eventFilter(self, obj: Any, event: QEvent) -> bool:
        if (
            hasattr(self, "search_edit")
            and obj is self.search_edit
            and event.type() == QEvent.Type.KeyPress
        ):
            try:
                key = event.key()  # type: ignore[attr-defined]
                mods = event.modifiers()  # type: ignore[attr-defined]
                if (
                    key == Qt.Key.Key_V
                    and (mods & Qt.KeyboardModifier.ControlModifier)
                    and not (mods & Qt.KeyboardModifier.AltModifier)
                ):
                    if self._should_intercept_paste_as_bookmarks(from_search_box=True):
                        QTimer.singleShot(0, self._on_paste_clipboard_clicked)
                        return True
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: Any) -> None:
        try:
            key = event.key()
            mods = event.modifiers()
            if (
                key == Qt.Key.Key_V
                and (mods & Qt.KeyboardModifier.ControlModifier)
                and not (mods & Qt.KeyboardModifier.AltModifier)
                and self.vault.is_unlocked()
                and self.stack.currentIndex() == 2
            ):
                if self._should_intercept_paste_as_bookmarks(from_search_box=False):
                    self._on_paste_clipboard_clicked()
                    event.accept()
                    return
        except Exception:
            pass
        super().keyPressEvent(event)

