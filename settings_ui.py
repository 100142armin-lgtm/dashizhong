"""User-controlled settings and explicit cleaner consent dialogs."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import tempfile
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QKeyEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QKeySequenceEdit,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from autostart import is_autostart_enabled, set_autostart
from cleaner import CLEAN_SCOPES, DEFAULT_SCOPES, CleanProgress, CleanReport
from skin import get_app_version, make_version_badge


RISKY_CLEAN_SCOPES = {"prefetch", "recycle", "wu", "delivery"}


class HotkeyKeySequenceEdit(QKeySequenceEdit):
    """Interactive hotkey recorder widget that captures key presses seamlessly."""

    def __init__(self, default_text: str = "", parent=None):
        super().__init__(parent)
        self.setKeySequence(QKeySequence(default_text))
        self.setStyleSheet(
            """
            QKeySequenceEdit {
                background: #0f172a;
                color: #38bdf8;
                border: 1px solid #0284c7;
                border-radius: 6px;
                padding: 5px 8px;
                font-weight: 700;
            }
            QKeySequenceEdit:focus {
                background: #1e293b;
                border: 2px solid #38bdf8;
                color: #fde047;
            }
            """
        )

    def text(self) -> str:
        return self.keySequence().toString()


VIDEO_CONTEXT_EXTENSIONS = (
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpeg", ".mpg", ".ts", ".mts", ".m2ts", ".3gp",
)


def _right_click_key_paths() -> list[str]:
    base = r"Software\Classes\SystemFileAssociations"
    return [
        base + r"\video\shell\PlayWithClockAlarm",
        *(base + rf"\{extension}\shell\PlayWithClockAlarm"
          for extension in VIDEO_CONTEXT_EXTENSIONS),
    ]


def _delete_registry_tree(root, path: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            children = []
            index = 0
            while True:
                try:
                    children.append(winreg.EnumKey(key, index))
                    index += 1
                except OSError:
                    break
        for child in children:
            _delete_registry_tree(root, path + "\\" + child)
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def is_right_click_association_enabled() -> bool:
    import winreg

    for key_path in _right_click_key_paths():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
                value, _value_type = winreg.QueryValueEx(key, "")
                if "Clock-Alarm.exe" in str(value):
                    return True
        except OSError:
            continue
    return False


def set_right_click_association(enabled: bool) -> None:
    import sys
    import winreg
    from pathlib import Path
    
    if enabled:
        if getattr(sys, "frozen", False):
            exe_path = sys.executable
        else:
            app_root = Path(__file__).resolve().parent
            parent_exe = app_root.parent / "Clock-Alarm.exe"
            if parent_exe.exists():
                exe_path = str(parent_exe)
            else:
                exe_path = sys.executable
                
        exe_path = str(Path(exe_path).resolve())
        if not Path(exe_path).is_file():
            raise FileNotFoundError(f"播放器启动文件不存在：{exe_path}")
        cmd_value = f'"{exe_path}" --play "%1"'

        for key_path in _right_click_key_paths():
            command_path = key_path + r"\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "使用 Clock/Alarm 播放")
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, f'"{exe_path}",0')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_path) as cmd_key:
                winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd_value)

        # Register as an application as well as a context-menu verb. This is
        # what makes Clock/Alarm appear in Windows 11's "Open with" chooser.
        application_key = r"Software\Classes\Applications\Clock-Alarm.exe"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, application_key) as key:
            winreg.SetValueEx(key, "FriendlyAppName", 0, winreg.REG_SZ, "Clock/Alarm 视频播放器")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, application_key + r"\DefaultIcon") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, application_key + r"\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cmd_value)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, application_key + r"\SupportedTypes") as key:
            for extension in VIDEO_CONTEXT_EXTENSIONS:
                winreg.SetValueEx(key, extension, 0, winreg.REG_SZ, "")

        capabilities_key = r"Software\ClockAlarm\Capabilities"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, capabilities_key) as key:
            winreg.SetValueEx(key, "ApplicationName", 0, winreg.REG_SZ, "Clock/Alarm 视频播放器")
            winreg.SetValueEx(key, "ApplicationDescription", 0, winreg.REG_SZ, "使用 Clock/Alarm 播放本地视频")
            winreg.SetValueEx(key, "ApplicationIcon", 0, winreg.REG_SZ, f'"{exe_path}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, capabilities_key + r"\FileAssociations") as key:
            for extension in VIDEO_CONTEXT_EXTENSIONS:
                winreg.SetValueEx(key, extension, 0, winreg.REG_SZ, "ClockAlarm.Video")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications") as key:
            winreg.SetValueEx(key, "ClockAlarm", 0, winreg.REG_SZ, capabilities_key)

        progid_key = r"Software\Classes\ClockAlarm.Video"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, progid_key) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Clock/Alarm 视频文件")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, progid_key + r"\DefaultIcon") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, progid_key + r"\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cmd_value)
        for extension in VIDEO_CONTEXT_EXTENSIONS:
            open_with_key = rf"Software\Classes\{extension}\OpenWithProgids"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, open_with_key) as key:
                winreg.SetValueEx(key, "ClockAlarm.Video", 0, winreg.REG_NONE, b"")
    else:
        for key_path in _right_click_key_paths():
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path + r"\command")
            except FileNotFoundError:
                pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            except FileNotFoundError:
                pass
        _delete_registry_tree(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\Applications\Clock-Alarm.exe",
        )
        _delete_registry_tree(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\ClockAlarm.Video",
        )
        _delete_registry_tree(
            winreg.HKEY_CURRENT_USER,
            r"Software\ClockAlarm\Capabilities",
        )
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\RegisteredApplications",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, "ClockAlarm")
        except FileNotFoundError:
            pass
        for extension in VIDEO_CONTEXT_EXTENSIONS:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    rf"Software\Classes\{extension}\OpenWithProgids",
                    0,
                    winreg.KEY_SET_VALUE,
                ) as key:
                    winreg.DeleteValue(key, "ClockAlarm.Video")
            except FileNotFoundError:
                pass

    try:
        import ctypes

        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


def _selected_cleaner_scopes(state: dict) -> list[str]:
    cleaner = state.get("cleaner")
    if not isinstance(cleaner, dict):
        return list(DEFAULT_SCOPES)
    scopes = cleaner.get("scopes")
    if not isinstance(scopes, list):
        return list(DEFAULT_SCOPES)
    allowed = {scope_id for scope_id, _label, _description in CLEAN_SCOPES}
    return [str(scope) for scope in scopes if str(scope) in allowed]


class _StyledDialog(QDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        from skin import get_app_version, make_version_badge
        self.setWindowTitle(f"Clock/Alarm v{get_app_version()} — {title}")
        self.setMinimumWidth(560)
        self.setStyleSheet(
            """
            QDialog { background: #07111f; color: #e2e8f0; }
            QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget { background: transparent; }
            QLabel, QCheckBox, QGroupBox { color: #e2e8f0; }
            QGroupBox {
                border: 1px solid #26445f; border-radius: 10px;
                margin-top: 10px; padding: 12px;
                font-weight: 700;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QCheckBox { spacing: 8px; padding: 4px; }
            QCheckBox::indicator {
                width: 16px; height: 16px; border: 1px solid #64748b;
                border-radius: 4px; background: #0f172a;
            }
            QCheckBox::indicator:checked { background: #0ea5e9; border-color: #38bdf8; }
            QPushButton {
                color: #f8fafc; background: #164e63; border: 1px solid #0e7490;
                border-radius: 7px; padding: 7px 14px; font-weight: 700;
            }
            QPushButton:hover { background: #155e75; }
            QSpinBox {
                color: #f8fafc; background: #0f172a; border: 1px solid #475569;
                border-radius: 6px; padding: 5px;
            }
            """
        )


class SettingsDialog(_StyledDialog):
    """Persistent preferences that require an explicit user choice."""

    def __init__(
        self,
        state: dict,
        save_state: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__("Clock/Alarm 设置", parent)
        self.state = state
        self.save_state = save_state
        self.resize(600, 700)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        header_row = QHBoxLayout()
        title_lbl = QLabel("⚙️ Clock/Alarm 系统设置")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #38bdf8;")
        header_row.addWidget(title_lbl)
        header_row.addStretch(1)
        header_row.addWidget(make_version_badge(self))
        main_layout.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(2, 0, 16, 0)

        general = QGroupBox("常规")
        general_layout = QVBoxLayout(general)
        self.autostart = QCheckBox("登录 Windows 后自动启动 Clock/Alarm")
        self.autostart.setChecked(is_autostart_enabled())
        general_layout.addWidget(self.autostart)
        note = QLabel("默认关闭；只有点击“保存设置”后才会修改开机启动。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#94a3b8; font-weight:400;")
        general_layout.addWidget(note)

        self.right_click_menu = QCheckBox("关联 Windows 右键菜单 (使用此播放器播放视频)")
        media_cfg = state.get("media") if isinstance(state.get("media"), dict) else {}
        initial_right_click = bool(
            media_cfg.get("right_click_association", False)
            or is_right_click_association_enabled()
        )
        self.right_click_menu.setChecked(initial_right_click)
        general_layout.addWidget(self.right_click_menu)

        prefs_cfg = state.get("prefs") if isinstance(state.get("prefs"), dict) else {}
        self.check_updates_auto = QCheckBox("软件启动时自动检查新版本并提醒")
        self.check_updates_auto.setChecked(bool(prefs_cfg.get("check_updates", True)))
        general_layout.addWidget(self.check_updates_auto)

        update_row = QHBoxLayout()
        update_row.setSpacing(10)
        self.btn_check_update = QPushButton("检查更新")
        self.btn_check_update.setFixedHeight(30)
        self.btn_check_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_update.clicked.connect(self._on_manual_check_update)
        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
        update_row.addWidget(self.btn_check_update)
        update_row.addWidget(self.lbl_update_status, stretch=1)
        general_layout.addLayout(update_row)

        layout.addWidget(general)

        cleaner_group = QGroupBox("电脑清理默认范围")
        cleaner_layout = QVBoxLayout(cleaner_group)
        selected = set(_selected_cleaner_scopes(state))
        self.cleaner_checks: dict[str, QCheckBox] = {}
        for scope_id, label, description in CLEAN_SCOPES:
            suffix = "（不可恢复）" if scope_id == "recycle" else ""
            check = QCheckBox(f"{label}{suffix} — {description}")
            check.setChecked(scope_id in selected)
            self.cleaner_checks[scope_id] = check
            cleaner_layout.addWidget(check)
        cleaner_note = QLabel("实际清理时仍会再次显示范围并要求确认。")
        cleaner_note.setStyleSheet("color:#94a3b8; font-weight:400;")
        cleaner_layout.addWidget(cleaner_note)
        layout.addWidget(cleaner_group)

        media_group = QGroupBox("视频播放器")
        media_layout = QVBoxLayout(media_group)
        media_layout.setSpacing(8)

        media_form = QFormLayout()
        media_form.setContentsMargins(0, 0, 0, 0)
        self.allow_online = QCheckBox("允许解析在线视频链接 and YouTube")
        self.allow_online.setChecked(bool(media_cfg.get("allow_online", True)))
        media_form.addRow(self.allow_online)
        self.playlist_limit = QSpinBox()
        self.playlist_limit.setRange(1, 200)
        self.playlist_limit.setValue(
            max(1, min(200, int(media_cfg.get("playlist_limit") or 100)))
        )
        self.playlist_limit.setSuffix(" 项")
        media_form.addRow("单次播放列表上限", self.playlist_limit)
        media_layout.addLayout(media_form)

        # Collapsible YouTube Cookies Configuration
        self.cookies_toggle = QCheckBox("配置 YouTube 登录 Cookies (解决 429 人机验证 / 会员视频)")
        existing_cookies = str(media_cfg.get("cookies_text") or "")
        if not existing_cookies:
            try:
                local_appdata = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
                c_file = Path(local_appdata) / "ClockAlarm" / "cookies.txt"
                if c_file.is_file():
                    existing_cookies = c_file.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                pass
        self.cookies_toggle.setChecked(bool(existing_cookies))
        self.cookies_toggle.setToolTip("开启后，播放器将以您的 Google/YouTube 登录身份请求视频流，彻底消除 429 人机拦截")
        media_layout.addWidget(self.cookies_toggle)

        self.cookies_card = QWidget()
        self.cookies_card.setObjectName("cookies_card")
        self.cookies_card.setStyleSheet(
            """
            QWidget#cookies_card {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            """
        )
        card_vbox = QVBoxLayout(self.cookies_card)
        card_vbox.setContentsMargins(10, 8, 10, 8)
        card_vbox.setSpacing(6)

        card_tip = QLabel("💡 从浏览器导出或抓包复制 YouTube Cookie 粘贴于此。播放器将以您的账号身份解析，消除 429 人机拦截。")
        card_tip.setWordWrap(True)
        card_tip.setStyleSheet("color: #94a3b8; font-size: 11px;")
        card_vbox.addWidget(card_tip)

        self.cookies_edit = QPlainTextEdit()
        self.cookies_edit.setFixedHeight(100)
        self.cookies_edit.setPlaceholderText(
            "在此粘贴 Cookies，支持以下格式：\n"
            "1. Netscape cookies.txt 格式（推荐，使用浏览器插件导出）\n"
            "2. F12 抓包复制的 'Cookie: SID=...; __Secure-3PSID=...' 请求头文本\n"
            "3. EditThisCookie 导出的 JSON 格式"
        )
        self.cookies_edit.setStyleSheet(
            """
            QPlainTextEdit {
                background: #0f172a;
                color: #f1f5f9;
                border: 1px solid #334155;
                border-radius: 6px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
                padding: 4px 6px;
            }
            QPlainTextEdit:focus {
                border: 1px solid #38bdf8;
            }
            """
        )
        self.cookies_edit.setPlainText(existing_cookies)
        card_vbox.addWidget(self.cookies_edit)

        # Status and Action Buttons Row
        status_btn_row = QHBoxLayout()
        status_btn_row.setContentsMargins(0, 0, 0, 0)
        status_btn_row.setSpacing(6)

        self.lbl_cookie_status = QLabel("")
        status_btn_row.addWidget(self.lbl_cookie_status, 1)

        self.btn_cookie_import = QPushButton("📁 导入文件…")
        self.btn_cookie_import.setFixedHeight(26)
        self.btn_cookie_import.setToolTip("从本地选择导出的 cookies.txt 或 json 文件直接导入")
        self.btn_cookie_import.setStyleSheet(
            "QPushButton { background: #334155; color: #cbd5e1; border: 1px solid #475569; border-radius: 4px; padding: 0 8px; font-size: 11px; }"
            "QPushButton:hover { background: #475569; color: #ffffff; border-color: #64748b; }"
        )
        self.btn_cookie_import.clicked.connect(self._import_cookie_file)
        status_btn_row.addWidget(self.btn_cookie_import)

        self.btn_cookie_clear = QPushButton("🗑️ 清空")
        self.btn_cookie_clear.setFixedHeight(26)
        self.btn_cookie_clear.setStyleSheet(
            "QPushButton { background: #334155; color: #cbd5e1; border: 1px solid #475569; border-radius: 4px; padding: 0 8px; font-size: 11px; }"
            "QPushButton:hover { background: #dc2626; color: #ffffff; border-color: #ef4444; }"
        )
        self.btn_cookie_clear.clicked.connect(lambda: self.cookies_edit.setPlainText(""))
        status_btn_row.addWidget(self.btn_cookie_clear)

        self.btn_cookie_help = QPushButton("❓ 提取教程")
        self.btn_cookie_help.setFixedHeight(26)
        self.btn_cookie_help.setStyleSheet(
            "QPushButton { background: #334155; color: #38bdf8; border: 1px solid #0284c7; border-radius: 4px; padding: 0 8px; font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { background: #0284c7; color: #ffffff; }"
        )
        self.btn_cookie_help.clicked.connect(self._show_cookie_help)
        status_btn_row.addWidget(self.btn_cookie_help)

        card_vbox.addLayout(status_btn_row)

        self.cookies_card.setVisible(self.cookies_toggle.isChecked())
        self.cookies_toggle.toggled.connect(self.cookies_card.setVisible)
        self.cookies_edit.textChanged.connect(self._update_cookie_status_ui)
        self._update_cookie_status_ui()

        media_layout.addWidget(self.cookies_card)

        # Media Cache Management Section
        cache_card = QWidget()
        cache_card.setStyleSheet("""
            QWidget {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        cache_vbox = QVBoxLayout(cache_card)
        cache_vbox.setContentsMargins(10, 8, 10, 8)
        cache_vbox.setSpacing(6)

        cache_title = QLabel("💾 离线视频缓存与存储空间控制")
        cache_title.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 12px;")
        cache_vbox.addWidget(cache_title)

        cache_row = QHBoxLayout()
        cache_row.setContentsMargins(0, 0, 0, 0)
        cache_row.setSpacing(10)

        lbl_limit = QLabel("缓存容量上限:")
        lbl_limit.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        cache_row.addWidget(lbl_limit)

        self.cache_limit_spin = QSpinBox()
        self.cache_limit_spin.setRange(50, 5000)
        self.cache_limit_spin.setSingleStep(50)
        self.cache_limit_spin.setValue(int(media_cfg.get("cache_limit_mb") or 500))
        self.cache_limit_spin.setSuffix(" MB")
        self.cache_limit_spin.setToolTip("超出上限时将自动按 LRU（最近最少使用）淘汰最旧的离线视频，确保占用永不超标")
        cache_row.addWidget(self.cache_limit_spin)

        self.lbl_cache_size = QLabel("当前已占用: 计算中…")
        self.lbl_cache_size.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 10px;")
        cache_row.addWidget(self.lbl_cache_size)
        cache_row.addStretch()

        self.btn_clear_cache = QPushButton("🗑️ 清空缓存")
        self.btn_clear_cache.setFixedHeight(26)
        self.btn_clear_cache.setStyleSheet(
            "QPushButton { background: #334155; color: #f87171; border: 1px solid #475569; border-radius: 4px; padding: 0 10px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #dc2626; color: #ffffff; border-color: #ef4444; }"
        )
        self.btn_clear_cache.clicked.connect(self._clear_cache_action)
        cache_row.addWidget(self.btn_clear_cache)

        self.btn_open_cache = QPushButton("📂 打开目录")
        self.btn_open_cache.setFixedHeight(26)
        self.btn_open_cache.setStyleSheet(
            "QPushButton { background: #334155; color: #cbd5e1; border: 1px solid #475569; border-radius: 4px; padding: 0 8px; font-size: 11px; }"
            "QPushButton:hover { background: #475569; color: #ffffff; border-color: #64748b; }"
        )
        self.btn_open_cache.clicked.connect(self._open_cache_action)
        cache_row.addWidget(self.btn_open_cache)

        cache_vbox.addLayout(cache_row)
        media_layout.addWidget(cache_card)
        self._refresh_cache_size_ui()

        layout.addWidget(media_group)

        # Screenshot & Clipboard Section
        screenshot_group = QGroupBox("截图与剪贴板")
        screenshot_form = QFormLayout(screenshot_group)
        screenshot_cfg = state.setdefault("screenshot", {})
        
        self.screenshot_auto_copy = QCheckBox("截图框选完成后自动复制到剪贴板")
        self.screenshot_auto_copy.setChecked(bool(screenshot_cfg.get("auto_copy", True)))
        screenshot_form.addRow(self.screenshot_auto_copy)
        
        self.screenshot_auto_save = QCheckBox("截图完成后自动保存图片到本地")
        self.screenshot_auto_save.setChecked(bool(screenshot_cfg.get("auto_save", True)))
        screenshot_form.addRow(self.screenshot_auto_save)

        self.screenshot_hide_windows = QCheckBox("截图时自动隐藏本软件的窗口 (如播放器、时钟等)")
        self.screenshot_hide_windows.setChecked(bool(screenshot_cfg.get("hide_windows", False)))
        self.screenshot_hide_windows.setToolTip("默认不勾选（截图时保留播放器、时钟等窗口可见，方便直接截取本软件内容）；勾选后将在截图前自动隐藏本软件的所有窗口。")
        screenshot_form.addRow(self.screenshot_hide_windows)
        
        dir_widget = QWidget()
        dir_layout = QHBoxLayout(dir_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(6)
        
        from pathlib import Path
        default_dir = str(Path.home() / "Pictures" / "ParrotScreenshots")
        self.screenshot_save_dir = QLineEdit()
        self.screenshot_save_dir.setText(str(screenshot_cfg.get("save_dir") or default_dir))
        self.screenshot_save_dir.setPlaceholderText("选择保存截图的文件夹")
        
        browse_btn = QPushButton("浏览…")
        browse_btn.setFixedWidth(75)
        
        def _choose_dir():
            current_val = self.screenshot_save_dir.text().strip() or default_dir
            chosen = QFileDialog.getExistingDirectory(
                None,
                "选择截图保存文件夹",
                current_val,
                QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontUseNativeDialog
            )
            if chosen:
                self.screenshot_save_dir.setText(chosen)
                
        browse_btn.clicked.connect(_choose_dir)
        dir_layout.addWidget(self.screenshot_save_dir)
        dir_layout.addWidget(browse_btn)
        
        screenshot_form.addRow("截图保存目录", dir_widget)
        layout.addWidget(screenshot_group)

        # Google Drive Cloud Upload Section (ShareX 1:1 Clean Style)
        gdrive_group = QGroupBox("☁️ Google Drive 截图云端上传 (ShareX 风格)")
        gdrive_layout = QVBoxLayout(gdrive_group)
        gdrive_layout.setSpacing(10)
        gdrive_cfg = screenshot_cfg.setdefault("gdrive", {})
        self.gdrive_creds = dict(gdrive_cfg.get("credentials") or {})

        from gdrive_uploader import find_sharex_gdrive_config
        sharex_info = find_sharex_gdrive_config()

        # Row 1: Status (Green when connected) + Connect / Disconnect button
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(10)

        self.gdrive_status_label = QLabel()
        self.gdrive_status_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        status_row.addWidget(self.gdrive_status_label)
        status_row.addStretch()

        self.gdrive_auth_btn = QPushButton("连接 Google Drive")
        self.gdrive_auth_btn.setFixedHeight(30)
        self.gdrive_auth_btn.setStyleSheet(
            "background-color: #0284c7; color: white; font-weight: bold; border-radius: 6px; padding: 0 16px;"
        )

        self.gdrive_revoke_btn = QPushButton("断开连接")
        self.gdrive_revoke_btn.setFixedHeight(30)
        self.gdrive_revoke_btn.setStyleSheet(
            "background-color: #334155; color: #f87171; font-weight: bold; border-radius: 6px; padding: 0 14px;"
        )

        status_row.addWidget(self.gdrive_auth_btn)
        status_row.addWidget(self.gdrive_revoke_btn)
        gdrive_layout.addLayout(status_row)

        # Optional ShareX one-click sync banner if ShareX is detected
        if sharex_info:
            sharex_box = QWidget()
            sharex_box.setStyleSheet("background: rgba(14, 165, 233, 0.1); border: 1px dashed #0284c7; border-radius: 6px;")
            s_layout = QHBoxLayout(sharex_box)
            s_layout.setContentsMargins(10, 6, 10, 6)
            s_lbl = QLabel("💡 检测到本机已安装 ShareX")
            s_lbl.setStyleSheet("color: #38bdf8; font-size: 12px; border: none; background: transparent;")
            s_btn = QPushButton("📥 一键导入配置")
            s_btn.setFixedHeight(26)
            s_btn.setStyleSheet("background-color: #0284c7; color: white; font-size: 11px; font-weight: bold; border-radius: 4px; padding: 0 10px; border: none;")
            s_btn.setToolTip("点击自动将 ShareX 中的文件夹 ID 及上传设置同步至此处")
            s_btn.clicked.connect(lambda: self._import_sharex_settings(sharex_info))
            s_layout.addWidget(s_lbl)
            s_layout.addStretch()
            s_layout.addWidget(s_btn)
            gdrive_layout.addWidget(sharex_box)

        # Checkboxes 1:1 matching ShareX
        self.gdrive_is_public = QCheckBox("公开上传")
        self.gdrive_is_public.setChecked(bool(gdrive_cfg.get("is_public", True)))
        self.gdrive_is_public.setToolTip("上传后自动将文件设为任何人可读，生成公开预览分享链接")
        gdrive_layout.addWidget(self.gdrive_is_public)

        self.gdrive_direct_link = QCheckBox("使用直链")
        self.gdrive_direct_link.setChecked(bool(gdrive_cfg.get("direct_link", False)))
        self.gdrive_direct_link.setToolTip("勾选后将自动复制图片直接外链 (lh3.googleusercontent.com/d/ID)；未勾选则复制 Google Drive 标准预览分享页面")
        gdrive_layout.addWidget(self.gdrive_direct_link)

        self.gdrive_use_folder = QCheckBox("上传文件到选定的文件夹")
        self.gdrive_use_folder.setChecked(bool(gdrive_cfg.get("use_folder", True)))
        gdrive_layout.addWidget(self.gdrive_use_folder)

        # Folder ID input row
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(8)

        folder_label = QLabel("文件夹 ID:")
        folder_label.setStyleSheet("font-size: 12px; color: #cbd5e1;")

        self.gdrive_folder_id = QLineEdit()
        default_fid = gdrive_cfg.get("folder_id")
        if not default_fid and sharex_info and sharex_info.get("folder_id"):
            default_fid = sharex_info.get("folder_id")
        self.gdrive_folder_id.setText(str(default_fid or ""))
        self.gdrive_folder_id.setPlaceholderText("例如: 1ZsewY2AEYQx-aI6VGaerKldyOWr-yQxi")
        self.gdrive_folder_id.setEnabled(self.gdrive_use_folder.isChecked())

        folder_help_btn = QPushButton("❓ 如何获取 ID")
        folder_help_btn.setFixedHeight(28)
        folder_help_btn.setStyleSheet(
            "QPushButton { background: #334155; color: #cbd5e1; font-weight: 600; border: 1px solid #475569; border-radius: 5px; padding: 0 10px; font-size: 12px; }"
            "QPushButton:hover { background: #475569; color: #f8fafc; border-color: #64748b; }"
        )
        folder_help_btn.setToolTip("点击查看如何从浏览器获取 Google Drive 文件夹 ID 的详细步骤说明")
        folder_help_btn.clicked.connect(self._show_gdrive_folder_help)

        self.gdrive_use_folder.toggled.connect(self.gdrive_folder_id.setEnabled)

        folder_row.addWidget(folder_label)
        folder_row.addWidget(self.gdrive_folder_id, 1)
        folder_row.addWidget(folder_help_btn)
        gdrive_layout.addLayout(folder_row)

        # Action buttons: Test connection
        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 0, 0, 0)
        self.gdrive_test_btn = QPushButton("🧪 测试连接与文件夹有效性")
        self.gdrive_test_btn.setFixedHeight(28)
        self.gdrive_test_btn.setStyleSheet("background-color: #1e293b; color: #38bdf8; border: 1px solid #0284c7; border-radius: 5px; padding: 0 14px;")
        self.gdrive_test_btn.clicked.connect(self._on_gdrive_test)
        test_row.addWidget(self.gdrive_test_btn)
        test_row.addStretch()
        gdrive_layout.addLayout(test_row)

        # Optional Advanced: custom OAuth credentials (collapsed by default)
        self.gdrive_custom_toggle = QCheckBox("使用自定义 OAuth 凭据 (高级选项)")
        self.gdrive_custom_toggle.setChecked(bool(gdrive_cfg.get("use_custom_creds", False)))
        gdrive_layout.addWidget(self.gdrive_custom_toggle)

        self.gdrive_custom_box = QWidget()
        custom_vbox = QVBoxLayout(self.gdrive_custom_box)
        custom_vbox.setContentsMargins(0, 4, 0, 0)
        custom_vbox.setSpacing(4)
        custom_form = QFormLayout()
        custom_form.setContentsMargins(0, 0, 0, 0)

        self.gdrive_client_id = QLineEdit()
        self.gdrive_client_id.setText(str(gdrive_cfg.get("client_id") or ""))
        self.gdrive_client_id.setPlaceholderText("留空则默认使用 ShareX 官方内置凭据")

        self.gdrive_client_secret = QLineEdit()
        self.gdrive_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.gdrive_client_secret.setText(str(gdrive_cfg.get("client_secret") or ""))
        self.gdrive_client_secret.setPlaceholderText("留空则默认使用 ShareX 官方内置凭据")

        custom_form.addRow("Client ID", self.gdrive_client_id)
        custom_form.addRow("Client Secret", self.gdrive_client_secret)
        custom_vbox.addLayout(custom_form)

        self.gdrive_custom_box.setVisible(self.gdrive_custom_toggle.isChecked())
        self.gdrive_custom_toggle.toggled.connect(self.gdrive_custom_box.setVisible)
        gdrive_layout.addWidget(self.gdrive_custom_box)

        self._update_gdrive_status_ui()
        self.gdrive_auth_btn.clicked.connect(self._on_gdrive_auth)
        self.gdrive_revoke_btn.clicked.connect(self._on_gdrive_revoke)

        layout.addWidget(gdrive_group)

        # Blink Encrypted Bookmarks & Security Section
        bookmarks_group = QGroupBox("🔐 灵动书签与安全密码 (Blink 加密收藏夹)")
        bookmarks_layout = QVBoxLayout(bookmarks_group)
        bookmarks_layout.setSpacing(8)
        bookmarks_cfg = state.setdefault("bookmarks", {})

        bm_tip = QLabel(
            "💡 灵动书签采用 <b>AES-256-GCM 硬件级加密</b> 与 <b>16 位安全急救码双密钥机制</b>。<br>"
            "忘记密码时凭急救码即可无损重置密码，100% 保留全部历史书签；支持随时一键导出本地备份。"
        )
        bm_tip.setWordWrap(True)
        bm_tip.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 400;")
        bookmarks_layout.addWidget(bm_tip)

        self.bookmarks_auto_lock = QCheckBox("收起或关闭灵动书签面板时，自动加密锁定书签保险库")
        self.bookmarks_auto_lock.setChecked(bool(bookmarks_cfg.get("auto_lock_on_close", False)))
        bookmarks_layout.addWidget(self.bookmarks_auto_lock)

        bm_btn_row1 = QHBoxLayout()
        bm_btn_row1.setSpacing(8)
        btn_bm_pwd = QPushButton("🔑 修改主密码 / 急救码无损重置")
        btn_bm_pwd.clicked.connect(lambda: self._open_bookmarks_security("password"))
        btn_bm_regen = QPushButton("♻️ 重新生成 16 位安全急救码")
        btn_bm_regen.clicked.connect(lambda: self._open_bookmarks_security("regenerate"))
        bm_btn_row1.addWidget(btn_bm_pwd)
        bm_btn_row1.addWidget(btn_bm_regen)
        bm_btn_row1.addStretch(1)
        bookmarks_layout.addLayout(bm_btn_row1)

        bm_btn_row2 = QHBoxLayout()
        bm_btn_row2.setSpacing(8)
        btn_bm_exp_html = QPushButton("📤 一键导出全部书签 (.html)")
        btn_bm_exp_html.clicked.connect(self._export_bookmarks_html)
        btn_bm_exp_enc = QPushButton("🔐 导出加密备份包 (.blinkbak)")
        btn_bm_exp_enc.clicked.connect(self._export_bookmarks_encrypted)
        btn_bm_imp = QPushButton("📥 增量导入书签 / 恢复备份...")
        btn_bm_imp.clicked.connect(lambda: self._open_bookmarks_security("backup"))
        bm_btn_row2.addWidget(btn_bm_exp_html)
        bm_btn_row2.addWidget(btn_bm_exp_enc)
        bm_btn_row2.addWidget(btn_bm_imp)
        bm_btn_row2.addStretch(1)
        bookmarks_layout.addLayout(bm_btn_row2)

        layout.addWidget(bookmarks_group)

        # Global Hotkey Customization Section
        hotkey_group = QGroupBox("全局快捷键自定义")
        hotkey_layout = QVBoxLayout(hotkey_group)
        
        hotkeys_cfg = state.setdefault("hotkeys_config", {})
        self.hotkeys_master = QCheckBox("启用全局快捷键功能")
        self.hotkeys_master.setChecked(bool(hotkeys_cfg.setdefault("enabled", True)))
        hotkey_layout.addWidget(self.hotkeys_master)
        
        hotkey_form = QFormLayout()
        self.hotkey_enables = {}
        self.hotkey_inputs = {}
        
        hotkey_meta = [
            ("world_clock", "闹钟 / 时钟 / 倒计时", "Ctrl+Alt+T"),
            ("bookmarks", "灵动书签 (加密收藏夹)", "Ctrl+Alt+B"),
            ("screenshot", "区域截图", "Ctrl+Alt+A"),
            ("recorder", "屏幕录像", "Ctrl+Alt+R"),
            ("todos", "待办事项", "Ctrl+Alt+D"),
            ("notes", "便签", "Ctrl+Alt+N"),
            ("media_player", "视频播放器", "Ctrl+Alt+V"),
            ("cleaner", "电脑清理", "Ctrl+Alt+C"),
        ]
        
        combos = hotkeys_cfg.setdefault("combos", {})
        enables = hotkeys_cfg.setdefault("enables", {})
        
        for key, name, default_combo in hotkey_meta:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            
            enable_chk = QCheckBox("启用")
            enable_chk.setChecked(bool(enables.setdefault(key, True)))
            
            input_edit = HotkeyKeySequenceEdit(str(combos.setdefault(key, default_combo)))
            input_edit.setMinimumWidth(180)
            
            row_layout.addWidget(enable_chk)
            row_layout.addWidget(input_edit)
            
            hotkey_form.addRow(name, row_widget)
            
            self.hotkey_enables[key] = enable_chk
            self.hotkey_inputs[key] = input_edit
            
        hotkey_layout.addLayout(hotkey_form)
        layout.addWidget(hotkey_group)

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存设置")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _save(self) -> None:
        desired_autostart = self.autostart.isChecked()
        status = set_autostart(desired_autostart)
        actual_autostart = is_autostart_enabled()
        if actual_autostart != desired_autostart:
            QMessageBox.warning(self, "开机自启动", status)
            self.autostart.setChecked(actual_autostart)
            return

        prefs = self.state.setdefault("prefs", {})
        prefs["autostart"] = desired_autostart
        prefs["autostart_consent"] = True

        scopes = [
            scope_id
            for scope_id, check in self.cleaner_checks.items()
            if check.isChecked()
        ]
        cleaner = self.state.setdefault("cleaner", {})
        cleaner["scopes"] = scopes
        cleaner["scope_selection_version"] = 1

        media = self.state.setdefault("media", {})
        media["allow_online"] = self.allow_online.isChecked()
        media["playlist_limit"] = int(self.playlist_limit.value())
        if hasattr(self, "cache_limit_spin"):
            limit_mb = int(self.cache_limit_spin.value())
            media["cache_limit_mb"] = limit_mb
            try:
                from media_player_ui import prune_media_cache
                prune_media_cache(max_bytes=limit_mb * 1024 * 1024)
            except Exception:
                pass
        cookies_text = self.cookies_edit.toPlainText().strip() if self.cookies_toggle.isChecked() else ""
        media["cookies_text"] = cookies_text

        # Synchronize cookies to local disk for yt-dlp
        try:
            local_appdata = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
            cookie_file = Path(local_appdata) / "ClockAlarm" / "cookies.txt"
            if cookies_text:
                from media_player_ui import normalize_cookie_content
                normalized = normalize_cookie_content(cookies_text)
                cookie_file.parent.mkdir(parents=True, exist_ok=True)
                cookie_file.write_text(normalized, encoding="utf-8")
            else:
                if cookie_file.is_file():
                    try:
                        cookie_file.unlink()
                    except Exception:
                        pass
        except Exception:
            pass

        # Save Screenshot configuration
        screenshot_cfg = self.state.setdefault("screenshot", {})
        screenshot_cfg["auto_copy"] = self.screenshot_auto_copy.isChecked()
        screenshot_cfg["auto_save"] = self.screenshot_auto_save.isChecked()
        screenshot_cfg["hide_windows"] = self.screenshot_hide_windows.isChecked()
        save_dir_text = self.screenshot_save_dir.text().strip()
        if save_dir_text:
            screenshot_cfg["save_dir"] = save_dir_text

        # Save Google Drive configuration (ShareX-style)
        gdrive_cfg = screenshot_cfg.setdefault("gdrive", {})
        gdrive_cfg["is_public"] = self.gdrive_is_public.isChecked()
        gdrive_cfg["direct_link"] = self.gdrive_direct_link.isChecked()
        gdrive_cfg["use_folder"] = self.gdrive_use_folder.isChecked()
        gdrive_cfg["folder_id"] = self.gdrive_folder_id.text().strip()
        gdrive_cfg["use_custom_creds"] = self.gdrive_custom_toggle.isChecked()
        gdrive_cfg["client_id"] = self.gdrive_client_id.text().strip()
        gdrive_cfg["client_secret"] = self.gdrive_client_secret.text().strip()
        if hasattr(self, "gdrive_creds") and self.gdrive_creds:
            gdrive_cfg["credentials"] = self.gdrive_creds

        # Save Hotkeys configuration
        hotkeys_cfg = self.state.setdefault("hotkeys_config", {})
        hotkeys_cfg["enabled"] = self.hotkeys_master.isChecked()
        
        combos = {}
        enables = {}
        for key in self.hotkey_inputs:
            combos[key] = self.hotkey_inputs[key].text().strip()
            enables[key] = self.hotkey_enables[key].isChecked()
            
        hotkeys_cfg["combos"] = combos
        hotkeys_cfg["enables"] = enables

        # Save Right-Click Context Menu association
        try:
            set_right_click_association(self.right_click_menu.isChecked())
        except Exception as exc:
            QMessageBox.critical(self, "右键菜单关联失败", str(exc))
            return
        self.state.setdefault("media", {})["right_click_association"] = (
            self.right_click_menu.isChecked()
        )

        prefs = self.state.setdefault("prefs", {})
        prefs["check_updates"] = bool(self.check_updates_auto.isChecked())

        if hasattr(self, "bookmarks_auto_lock"):
            bm_cfg = self.state.setdefault("bookmarks", {})
            bm_cfg["auto_lock_on_close"] = bool(self.bookmarks_auto_lock.isChecked())

        self.save_state()
        self.accept()

    def _open_bookmarks_security(self, tab: str = "password") -> None:
        from bookmarks_ui import VaultSecurityDialog

        dlg = VaultSecurityDialog(parent=self, initial_tab=tab)
        dlg.exec()

    def _export_bookmarks_html(self) -> None:
        from bookmarks_ui import export_bookmarks_html_interactive

        export_bookmarks_html_interactive(self)

    def _export_bookmarks_encrypted(self) -> None:
        from bookmarks_ui import export_bookmarks_encrypted_interactive

        export_bookmarks_encrypted_interactive(self)

    def _on_manual_check_update(self) -> None:
        from skin import get_app_version
        from update_checker import UpdateCheckWorker
        from update_dialog import UpdateDialog

        self.btn_check_update.setEnabled(False)
        self.lbl_update_status.setText("正在检查新版本...")

        current_ver = get_app_version()
        self._update_worker = UpdateCheckWorker(current_version=current_ver, parent=self)

        def _on_finished(info):
            self.btn_check_update.setEnabled(True)
            if info.has_update:
                self.lbl_update_status.setText(f"发现新版本 v{info.latest_version}，建议升级")
                self.lbl_update_status.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: bold;")
                dlg = UpdateDialog(info, on_ignore=self._on_ignore_version, parent=self)
                dlg.exec()
            else:
                self.lbl_update_status.setText(f"当前已是最新版本 (v{info.current_version})")
                self.lbl_update_status.setStyleSheet("color: #34d399; font-size: 12px; font-weight: 600;")

        def _on_failed(err):
            self.btn_check_update.setEnabled(True)
            self.lbl_update_status.setText("检查失败，请检查网络后重试")
            self.lbl_update_status.setStyleSheet("color: #f87171; font-size: 12px;")

        self._update_worker.check_finished.connect(_on_finished)
        self._update_worker.check_failed.connect(_on_failed)
        self._update_worker.start()

    def _on_ignore_version(self, version: str) -> None:
        prefs = self.state.setdefault("prefs", {})
        prefs["ignored_update_version"] = version
        self.save_state()

    def _update_cookie_status_ui(self) -> None:
        text = self.cookies_edit.toPlainText().strip()
        if not text:
            self.lbl_cookie_status.setText("状态：未配置")
            self.lbl_cookie_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
            return

        from media_player_ui import normalize_cookie_content
        norm = normalize_cookie_content(text)
        has_login = any(k in norm for k in ("LOGIN_INFO", "SSID", "SAPISID", "SID", "APISID", "__Secure-3PSID"))
        valid_lines = [l for l in norm.splitlines() if l.strip() and not l.strip().startswith("#")]
        if has_login:
            self.lbl_cookie_status.setText(f"状态：已配置有效登录凭据 ({len(valid_lines)} 条)")
            self.lbl_cookie_status.setStyleSheet("color: #34d399; font-size: 11px; font-weight: 600;")
        elif valid_lines:
            self.lbl_cookie_status.setText(f"状态：已解析 {len(valid_lines)} 条 Cookie")
            self.lbl_cookie_status.setStyleSheet("color: #38bdf8; font-size: 11px;")
        else:
            self.lbl_cookie_status.setText("状态：格式待识别")
            self.lbl_cookie_status.setStyleSheet("color: #facc15; font-size: 11px;")

    def _import_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择导出的 YouTube Cookies 文件",
            "",
            "Cookie 文件 (*.txt *.json);;文本文件 (*.txt);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
            self.cookies_edit.setPlainText(content)
            self.cookies_toggle.setChecked(True)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", f"无法读取该文件: {exc}")

    def _show_cookie_help(self) -> None:
        help_text = (
            "<h3>YouTube Cookies 提取与配置指南</h3>"
            "<p>当网络节点被 YouTube 拦截出现 <b>429 / Sign in to confirm you're not a bot</b> 提示时，"
            "配置浏览器的 YouTube 登录 Cookies 可以让播放器以您的真实登录身份请求视频流，<b>彻底消除 429 人机拦截</b>，并可播放会员及受限视频。</p>"
            "<hr style='border: none; border-top: 1px solid #334155; margin: 10px 0;'>"
            "<p><b>方法一：使用 Chrome / Edge 扩展一键导出（推荐）</b></p>"
            "<ol style='margin-left: -15px;'>"
            "<li>在 Chrome / Edge 应用商店安装 <code>Get cookies.txt LOCALLY</code> 或 <code>Cookie-Editor</code> 扩展。</li>"
            "<li>在浏览器中登录 <a href='https://www.youtube.com' style='color:#38bdf8;'>youtube.com</a>。</li>"
            "<li>点击该扩展图标，选择 <b>Export / 导出</b> (Netscape 格式)。</li>"
            "<li>点击本界面的 <b>[ 📁 导入文件… ]</b> 或直接将文本粘贴到输入框中。</li>"
            "</ol>"
            "<p><b>方法二：浏览器开发者工具 F12 抓包复制（免插件）</b></p>"
            "<ol style='margin-left: -15px;'>"
            "<li>在浏览器中登录 <a href='https://www.youtube.com' style='color:#38bdf8;'>youtube.com</a>。</li>"
            "<li>按 <b>F12</b> 打开开发者工具，切换到 <b>Network（网络）</b> 标签页。</li>"
            "<li>刷新网页，在请求列表中点击任意一个发往 youtube.com 的请求（例如 <code>browse</code> 或 <code>log_event</code>）。</li>"
            "<li>在右侧 Headers 找到 <code>Cookie:</code>，复制其后的整段文本。</li>"
            "<li>直接粘贴到本软件的文本框即可（软件会自动解析为标准 Netscape 格式）。</li>"
            "</ol>"
            "<p style='color: #94a3b8; font-size: 11px;'>注：Cookies 仅保存在本机用于向 YouTube 获取流媒体直链，绝不上传至任何第三方服务器。</p>"
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("如何获取 YouTube Cookies")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

    def _refresh_cache_size_ui(self) -> None:
        try:
            from media_player_ui import get_media_cache_size
            sz_bytes = get_media_cache_size()
            if sz_bytes >= 1024 * 1024 * 1024:
                size_str = f"{sz_bytes / (1024 * 1024 * 1024):.2f} GB"
            elif sz_bytes >= 1024 * 1024:
                size_str = f"{sz_bytes / (1024 * 1024):.1f} MB"
            elif sz_bytes > 0:
                size_str = f"{sz_bytes / 1024:.1f} KB"
            else:
                size_str = "0.0 MB"
            self.lbl_cache_size.setText(f"当前已占用: {size_str}")
        except Exception:
            self.lbl_cache_size.setText("当前已占用: 0.0 MB")

    def _clear_cache_action(self) -> None:
        reply = QMessageBox.question(
            self,
            "清空媒体缓存",
            "确定要清空本地所有已缓存的离线音视频文件吗？\n\n（此操作仅清除本地缓存的媒体流以释放磁盘空间，绝不会影响您的播放列表和收藏记录）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from media_player_ui import clear_media_cache
                freed = clear_media_cache()
                self._refresh_cache_size_ui()
                mb = freed / (1024 * 1024)
                QMessageBox.information(self, "缓存已清空", f"成功清空本地媒体缓存，已释放约 {mb:.1f} MB 磁盘空间！")
            except Exception as exc:
                QMessageBox.warning(self, "清空失败", f"清理过程中发生错误：{exc}")

    def _open_cache_action(self) -> None:
        try:
            import os
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            loc_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "ClockAlarm" / "MediaCache"
            loc_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(loc_dir)))
        except Exception:
            pass

    def _import_sharex_settings(self, info: dict) -> None:
        if info.get("folder_id"):
            self.gdrive_folder_id.setText(info["folder_id"])
        self.gdrive_is_public.setChecked(bool(info.get("is_public", True)))
        self.gdrive_direct_link.setChecked(bool(info.get("direct_link", False)))
        self.gdrive_use_folder.setChecked(bool(info.get("use_folder", True)))
        self.gdrive_folder_id.setEnabled(self.gdrive_use_folder.isChecked())
        QMessageBox.information(
            self,
            "导入成功",
            f"已成功同步 ShareX 配置：\n\n"
            f"• 文件夹 ID: {info.get('folder_id') or '（未指定）'}\n"
            f"• 公开上传: {'开启' if info.get('is_public') else '关闭'}\n"
            f"• 直链模式: {'开启' if info.get('direct_link') else '关闭'}\n\n"
            "若尚未授权，点击【连接 Google Drive】即可一键授权！",
        )

    def _show_gdrive_folder_help(self) -> None:
        QMessageBox.information(
            self,
            "如何获取文件夹 ID",
            "1. 在浏览器中打开您的 Google Drive (谷歌云盘)；\n"
            "2. 打开用于存放截图的目标文件夹；\n"
            "3. 查看浏览器地址栏，URL 格式形如：\n"
            "   https://drive.google.com/drive/folders/1ZsewY2AEYQx-aI6VGaerKldyOWr-yQxi\n"
            "4. 复制 folders/ 后面的这一串字符串，粘贴到此输入框即可！\n\n"
            "💡 提示：若未勾选【上传文件到选定的文件夹】或留空，截图将保存在云盘根目录。",
        )

    def _update_gdrive_status_ui(self) -> None:
        creds = getattr(self, "gdrive_creds", {})
        token = creds.get("access_token") or creds.get("refresh_token")
        if token:
            display_user = creds.get("name") or creds.get("email") or "Google 用户"
            self.gdrive_status_label.setText(f"<span style='color: #4ade80;'>状态：已登录为 {display_user}。</span>")
            self.gdrive_auth_btn.setVisible(False)
            self.gdrive_revoke_btn.setVisible(True)
            self.gdrive_test_btn.setEnabled(True)
        else:
            self.gdrive_status_label.setText("<span style='color: #94a3b8;'>状态：未连接</span>")
            self.gdrive_auth_btn.setVisible(True)
            self.gdrive_auth_btn.setText("连接 Google Drive")
            self.gdrive_revoke_btn.setVisible(False)
            self.gdrive_test_btn.setEnabled(False)

    def _on_gdrive_auth(self) -> None:
        from gdrive_uploader import GoogleDriveAuthManager

        use_custom = self.gdrive_custom_toggle.isChecked()
        client_id = self.gdrive_client_id.text().strip() if use_custom else ""
        client_secret = self.gdrive_client_secret.text().strip() if use_custom else ""

        if use_custom and (not client_id or not client_secret):
            QMessageBox.warning(
                self,
                "提示",
                "您勾选了自定义 OAuth 凭据，请填入 Client ID 与 Client Secret；或者取消勾选以直接使用官方内置免配凭据。",
            )
            return

        self._gdrive_auth_mgr = GoogleDriveAuthManager(self)

        def _on_success(creds: dict) -> None:
            self.gdrive_creds = creds
            self._update_gdrive_status_ui()
            gdrive_cfg = self.state.setdefault("screenshot", {}).setdefault("gdrive", {})
            gdrive_cfg["credentials"] = creds
            gdrive_cfg["client_id"] = client_id
            gdrive_cfg["client_secret"] = client_secret
            self.save_state()
            display_user = creds.get("name") or creds.get("email") or "Google 用户"
            QMessageBox.information(
                self,
                "连接成功",
                f"🎉 Google Drive 授权成功！\n已登录为：{display_user}\n\n您现在可以在截图工具条中点击 ☁️ 按钮直接将截图上传至 Google 云盘并自动生成公开直链！",
            )

        def _on_failed(err_msg: str) -> None:
            QMessageBox.warning(self, "Google 账号授权失败", err_msg)

        self._gdrive_auth_mgr.auth_success.connect(_on_success)
        self._gdrive_auth_mgr.auth_failed.connect(_on_failed)

        ok, msg = self._gdrive_auth_mgr.start_authorization(client_id, client_secret)
        if ok:
            QMessageBox.information(
                self,
                "正在连接",
                "已为您在默认浏览器中打开 Google 登录授权页面。\n\n请在浏览器中选择您的谷歌账号并点击允许，授权完成后网页会提示成功，软件将自动完成连接！",
            )
        else:
            QMessageBox.warning(self, "启动授权失败", msg)

    def _on_gdrive_revoke(self) -> None:
        reply = QMessageBox.question(
            self,
            "断开连接",
            "确定要断开与当前 Google Drive 账号的连接吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from gdrive_uploader import GoogleDriveAuthManager

            if self.gdrive_creds:
                GoogleDriveAuthManager.revoke_authorization(self.gdrive_creds)
            self.gdrive_creds = {}
            gdrive_cfg = self.state.setdefault("screenshot", {}).setdefault("gdrive", {})
            gdrive_cfg["credentials"] = {}
            self._update_gdrive_status_ui()
            self.save_state()
            QMessageBox.information(self, "已断开", "已断开与 Google Drive 的连接。")

    def _on_gdrive_test(self) -> None:
        from gdrive_uploader import GoogleDriveUploader

        if not self.gdrive_creds:
            QMessageBox.warning(self, "未连接", "当前尚未连接 Google Drive，请先点击【连接 Google Drive】。")
            return
        folder_id = self.gdrive_folder_id.text().strip() if self.gdrive_use_folder.isChecked() else None
        ok, msg = GoogleDriveUploader.test_connection(self.gdrive_creds, folder_id)
        if ok:
            QMessageBox.information(self, "Google Drive 连接测试", f"✅ {msg}")
        else:
            QMessageBox.warning(self, "Google Drive 连接测试", f"❌ {msg}")


class CleanerDialog(_StyledDialog):
    """Select a cleanup scope and confirm it before any deletion starts."""

    def __init__(
        self,
        state: dict,
        save_state: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__("电脑清理", parent)
        self.state = state
        self.save_state = save_state
        self._accepted_scopes: list[str] = []
        self.resize(600, 520)

        layout = QVBoxLayout(self)
        header_row = QHBoxLayout()
        title_lbl = QLabel("🧹 Clock/Alarm 电脑清理")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #38bdf8;")
        header_row.addWidget(title_lbl)
        header_row.addStretch(1)
        header_row.addWidget(make_version_badge(self))
        layout.addLayout(header_row)

        intro = QLabel("请选择本次要清理的项目。未勾选的范围不会被访问。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        selected = set(_selected_cleaner_scopes(state))
        self.checks: dict[str, QCheckBox] = {}
        for scope_id, label, description in CLEAN_SCOPES:
            check = QCheckBox(f"{label} — {description}")
            check.setChecked(scope_id in selected)
            if scope_id in RISKY_CLEAN_SCOPES:
                check.setToolTip("此项目影响系统缓存或不可恢复，请确认后再清理。")
            self.checks[scope_id] = check
            content_layout.addWidget(check)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        warning = QLabel(
            "安全保护始终启用：不会跟随目录链接，不会访问未批准目录；"
            "回收站内容删除后无法恢复。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#fbbf24;")
        layout.addWidget(warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认并开始清理")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _confirm(self) -> None:
        scopes = [
            scope_id for scope_id, check in self.checks.items() if check.isChecked()
        ]
        if not scopes:
            QMessageBox.information(self, "电脑清理", "请至少选择一个清理项目。")
            return

        labels = {
            scope_id: label for scope_id, label, _description in CLEAN_SCOPES
        }
        selected_text = "、".join(labels[scope_id] for scope_id in scopes)
        extra = (
            "\n\n其中包含系统缓存或不可恢复项目，请再次确认。"
            if set(scopes) & RISKY_CLEAN_SCOPES
            else ""
        )
        result = QMessageBox.question(
            self,
            "确认清理范围",
            f"本次只会清理：{selected_text}。{extra}\n\n确定开始吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        cleaner = self.state.setdefault("cleaner", {})
        cleaner["scopes"] = list(scopes)
        cleaner["scope_selection_version"] = 1
        self.save_state()
        self._accepted_scopes = list(scopes)
        self.accept()

    def selected_scopes(self) -> list[str]:
        return list(self._accepted_scopes)


class CleanerProgressDialog(_StyledDialog):
    """Live cleanup feedback; all widget updates run on the GUI thread."""

    def __init__(self, scopes: list[str], cancel_event, parent=None) -> None:
        super().__init__("Clock/Alarm — 清理进度", parent)
        self.resize(640, 500)
        self.cancel_event = cancel_event
        self.running = True
        self._started = time.monotonic()
        self._completed = 0
        labels = {key: label for key, label, _ in CLEAN_SCOPES}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        top_h = QHBoxLayout()
        self.status = QLabel("正在准备清理…")
        self.status.setStyleSheet("font-size:18px; font-weight:700; color:#38bdf8;")
        top_h.addWidget(self.status)
        top_h.addStretch(1)
        top_h.addWidget(make_version_badge(self))
        layout.addLayout(top_h)
        scope_label = QLabel("本次项目：" + "、".join(labels[s] for s in scopes if s in labels))
        scope_label.setWordWrap(True)
        layout.addWidget(scope_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, len(set(scopes) & set(labels))))
        self.progress.setValue(0)
        self.progress.setFormat("项目进度：%v / %m")
        self.progress.setStyleSheet("QProgressBar { border:1px solid #26445f; border-radius:6px; text-align:center; color:white; min-height:24px; } QProgressBar::chunk { background:#0e7490; }")
        layout.addWidget(self.progress)
        self.activity = QProgressBar()
        self.activity.setRange(0, 0)
        self.activity.setFixedHeight(6)
        self.activity.setTextVisible(False)
        self.activity.setStyleSheet("QProgressBar { border:none; background:#0f172a; } QProgressBar::chunk { background:#38bdf8; }")
        layout.addWidget(self.activity)
        self.current_item = QLabel("正在读取所选项目…")
        self.current_item.setTextFormat(Qt.TextFormat.PlainText)
        self.current_item.setWordWrap(True)
        self.current_item.setMinimumHeight(36)
        layout.addWidget(self.current_item)
        self.stats = QLabel()
        self.stats.setStyleSheet("font-size:14px; font-weight:600;")
        self._set_stats(0, 0, 0)
        layout.addWidget(self.stats)
        self.elapsed = QLabel("耗时 00:00")
        layout.addWidget(self.elapsed)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setStyleSheet("background:#0f172a; color:#cbd5e1; border:1px solid #26445f; border-radius:6px;")
        self.details.setPlainText("按项目显示进度；文件数量与释放空间会实时更新。\n占用中或无法访问的文件会跳过。")
        layout.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("停止清理")
        self.cancel_button.clicked.connect(self.request_stop)
        self.close_button = QPushButton("后台运行")
        self.close_button.setToolTip("隐藏窗口后，可再次点击“电脑清理”查看进度。")
        self.close_button.clicked.connect(self.hide)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_elapsed)
        self.timer.start(1000)

    def _update_elapsed(self) -> None:
        seconds = int(time.monotonic() - self._started)
        self.elapsed.setText(f"耗时 {seconds // 60:02d}:{seconds % 60:02d}")

    def _set_stats(self, files: int, size: int, skipped: int) -> None:
        self.stats.setText(f"已清理 {files:,} 个文件  ·  释放 {size / 1048576:.1f} MB  ·  跳过/异常 {skipped}")

    def update_progress(self, progress: object) -> None:
        if not self.running or not isinstance(progress, CleanProgress):
            return
        self.progress.setValue(progress.completed_scopes)
        if not self.cancel_event.is_set():
            self.status.setText(f"正在清理：{progress.label}")
            self.current_item.setText(progress.current_item or "正在检查此项目…")
        self._set_stats(progress.files_removed, progress.bytes_freed, progress.skipped)
        if progress.completed_scopes > self._completed:
            self.details.appendPlainText(f"已处理：{progress.label}")
            self._completed = progress.completed_scopes

    def request_stop(self) -> None:
        if not self.running:
            return
        self.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status.setText("正在停止…")
        self.current_item.setText("当前文件或系统操作结束后停止；已经清理的内容不会恢复。")

    def finish(self, report: CleanReport) -> None:
        self.running = False
        self.timer.stop()
        self._update_elapsed()
        self.activity.hide()
        self.cancel_button.setEnabled(False)
        self.close_button.setText("关闭")
        self.status.setText("清理已停止" if report.cancelled else ("清理结束，有项目失败" if report.failed else "清理完成"))
        self.current_item.setText(report.summary())
        self._set_stats(report.files_removed, report.bytes_freed, len(report.errors))
        if not report.cancelled:
            self.progress.setValue(self.progress.maximum())
        if report.errors:
            self.details.appendPlainText("\n跳过/异常详情（最多显示 50 条）：\n" + "\n".join(report.errors[:50]))
        elif not report.files_removed:
            self.details.appendPlainText("\n本次没有找到可以移除的文件。")
        self.details.appendPlainText("\n" + report.summary())
