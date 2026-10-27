from __future__ import annotations

import datetime
import uuid
import os
import sys
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, QPoint, QTime, QSize
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QIcon, QFontDatabase, QMouseEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QComboBox,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QTabWidget,
    QStackedWidget,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTimeEdit,
    QCheckBox,
    QGridLayout,
    QSizePolicy,
    QAbstractItemView,
    QCompleter,
    QProgressBar,
)
import pytz

from alarm_sounds import RINGTONES, ensure_ringtones, play_ringtone, stop_ringtone
from skin import get_app_version, make_version_badge


def style_combo_popup(combo: QComboBox) -> None:
    view = combo.view()
    if view:
        view.setStyleSheet("""
            QAbstractItemView {
                background-color: #0d1b2a !important;
                color: #ffffff !important;
                selection-background-color: #0284c7 !important;
                selection-color: #ffffff !important;
                border: 1px solid #00e5ff !important;
                outline: none !important;
                padding: 4px !important;
            }
            QAbstractItemView::item {
                min-height: 28px !important;
                padding: 6px 12px !important;
                color: #ffffff !important;
                background-color: #0d1b2a !important;
            }
            QAbstractItemView::item:hover {
                background-color: #0284c7 !important;
                color: #ffffff !important;
            }
            QAbstractItemView::item:selected {
                background-color: #0284c7 !important;
                color: #ffffff !important;
            }
        """)


COUNTRY_NAMES_ZH = {
    "AE": "阿拉伯联合酋长国", "AR": "阿根廷", "AT": "奥地利", "AU": "澳大利亚",
    "BE": "比利时", "BR": "巴西", "CA": "加拿大", "CH": "瑞士", "CL": "智利",
    "CN": "中国", "CO": "哥伦比亚", "CZ": "捷克", "DE": "德国", "DK": "丹麦",
    "EG": "埃及", "ES": "西班牙", "FI": "芬兰", "FR": "法国", "GB": "英国", "GR": "希腊",
    "HK": "中国香港", "HU": "匈牙利", "ID": "印度尼西亚", "IE": "爱尔兰",
    "IL": "以色列", "IN": "印度", "IT": "意大利", "JP": "日本", "KE": "肯尼亚", "KR": "韩国",
    "MO": "中国澳门", "MX": "墨西哥", "MY": "马来西亚", "NG": "尼日利亚",
    "NL": "荷兰", "NO": "挪威", "NZ": "新西兰", "PE": "秘鲁", "PH": "菲律宾", "PK": "巴基斯坦",
    "PL": "波兰", "PT": "葡萄牙", "RO": "罗马尼亚", "RU": "俄罗斯", "SA": "沙特阿拉伯",
    "SE": "瑞典", "SG": "新加坡", "TH": "泰国", "TR": "土耳其", "TW": "中国台湾",
    "UA": "乌克兰", "US": "美国", "VN": "越南", "ZA": "南非",
}


def timezone_country_choices() -> list[tuple[str, str]]:
    """All pytz country zones, labelled by country/region and representative city."""
    choices: list[tuple[str, str]] = [("协调世界时 · UTC", "UTC")]
    for code, zones in pytz.country_timezones.items():
        fallback = str(pytz.country_names.get(code, code))
        country = COUNTRY_NAMES_ZH.get(code, fallback)
        for zone in zones:
            city = zone.split("/")[-1].replace("_", " ")
            choices.append((f"{country}（{code}） · {city}", zone))
    return sorted(choices, key=lambda item: item[0].casefold())

class ClockWidget(QFrame):
    def __init__(self, tz_name: str, display_name: str = "", on_remove=None, parent=None):
        super().__init__(parent)
        self.tz_name = tz_name
        self.tz = pytz.timezone(tz_name)
        self.setObjectName("clockCard")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        # Left Info Stack
        left_box = QVBoxLayout()
        left_box.setSpacing(5)

        raw_name = display_name or tz_name.split("/")[-1].replace("_", " ")
        self.name_label = QLabel(raw_name)
        self.name_label.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 700;")
        self.name_label.setWordWrap(True)
        left_box.addWidget(self.name_label)

        # Badge row: Sun/Moon + Time difference
        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)

        self.diff_label = QLabel("+0h (与本地时差)")
        self.diff_label.setStyleSheet("""
            background: rgba(56, 189, 248, 0.12);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            padding: 2px 8px;
        """)
        badge_row.addWidget(self.diff_label)
        badge_row.addStretch()
        left_box.addLayout(badge_row)

        self.date_label = QLabel("2026年9月11日")
        self.date_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        left_box.addWidget(self.date_label)

        layout.addLayout(left_box, stretch=1)

        # Right Time Stack
        right_box = QVBoxLayout()
        right_box.setSpacing(2)
        right_box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.time_label = QLabel("00:00:00")
        self.time_label.setStyleSheet("""
            color: #ffffff;
            font-size: 26px;
            font-family: 'Segoe UI', 'Consolas', 'Courier New', monospace;
            font-weight: 700;
            letter-spacing: 1px;
        """)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_box.addWidget(self.time_label)

        layout.addLayout(right_box)

        # Remove button
        remove_btn = QPushButton("✕")
        remove_btn.setObjectName("removeClock")
        remove_btn.setFixedSize(28, 28)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setToolTip("移除这个世界时钟")
        if callable(on_remove):
            remove_btn.clicked.connect(lambda: on_remove(self))
        layout.addWidget(remove_btn)

        self.setStyleSheet("""
            QFrame#clockCard {
                background: #172238;
                border: 1px solid rgba(56, 189, 248, 0.18);
                border-radius: 12px;
            }
            QFrame#clockCard:hover {
                background: #1b2842;
                border: 1px solid rgba(56, 189, 248, 0.45);
            }
            QLabel {
                background: transparent;
                border: none;
            }
            QPushButton#removeClock {
                background: rgba(255, 255, 255, 0.05);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 13px;
                font-size: 16px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton#removeClock:hover {
                background: rgba(239, 68, 68, 0.25);
                color: #fca5a5;
                border: 1px solid rgba(239, 68, 68, 0.5);
            }
        """)

    def update_time(self, local_now: datetime.datetime):
        now_tz = local_now.astimezone(self.tz)
        weekdays_cn = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
        self.time_label.setText(now_tz.strftime("%H:%M:%S"))
        self.date_label.setText(f"{now_tz.year}年{now_tz.month}月{now_tz.day}日 {weekdays_cn[now_tz.weekday()]}")

        diff = (now_tz.utcoffset() - local_now.astimezone().utcoffset()).total_seconds() / 3600
        sign = "+" if diff >= 0 else ""

        # Day / Night indicator
        is_day = 6 <= now_tz.hour < 18
        icon = "☀️ 白天" if is_day else "🌙 夜间"

        # Date difference tag
        local_date = local_now.astimezone().date()
        tz_date = now_tz.date()
        if tz_date < local_date:
            day_tag = "· 昨天"
        elif tz_date > local_date:
            day_tag = "· 明天"
        else:
            day_tag = "· 今天"

        diff_text = f"时差 {sign}{diff:g}h" if diff != 0 else "与本地同时间"
        self.diff_label.setText(f"{icon} · {diff_text} {day_tag}")
        if is_day:
            self.diff_label.setStyleSheet("""
                background: rgba(245, 158, 11, 0.12);
                color: #fbbf24;
                border: 1px solid rgba(245, 158, 11, 0.3);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
            """)
        else:
            self.diff_label.setStyleSheet("""
                background: rgba(139, 92, 246, 0.15);
                color: #c084fc;
                border: 1px solid rgba(139, 92, 246, 0.35);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
            """)


class _ResizeHandle(QWidget):
    """Reliable manual resize zone for a frameless top-level window."""

    def __init__(self, host: QWidget, edges, cursor) -> None:
        super().__init__(host)
        self._host = host
        self._edges = edges
        self._press_global = None
        self._start_geometry = None
        self.setCursor(cursor)
        self.setMouseTracking(True)
        # A nearly invisible painted pixel keeps the edge hit-testable on a
        # translucent, frameless Windows window.
        self.setStyleSheet("background: rgba(255,255,255,2); border: none;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_geometry = self._host.geometry()
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._press_global is None or self._start_geometry is None:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        start = self._start_geometry
        min_w = max(180, self._host.minimumWidth())
        min_h = max(90, self._host.minimumHeight())
        x, y, width, height = start.x(), start.y(), start.width(), start.height()

        if self._edges & Qt.Edge.LeftEdge:
            right_edge = start.x() + start.width()
            x = min(start.x() + delta.x(), right_edge - min_w)
            width = right_edge - x
        elif self._edges & Qt.Edge.RightEdge:
            width = max(min_w, start.width() + delta.x())
        if self._edges & Qt.Edge.TopEdge:
            bottom_edge = start.y() + start.height()
            y = min(start.y() + delta.y(), bottom_edge - min_h)
            height = bottom_edge - y
        elif self._edges & Qt.Edge.BottomEdge:
            height = max(min_h, start.height() + delta.y())

        self._host.setGeometry(x, y, width, height)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_global = None
        self._start_geometry = None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        event.accept()


class FloatingWorldClock(QWidget):
    def __init__(self, state_dict: dict, host=None, parent=None):
        super().__init__(parent)
        self.state_dict = state_dict
        self.host = host
        
        from skin import bundle_root
        font_candidates = [
            bundle_root() / "assets" / "fonts" / "DS-DIGI.TTF",
            Path(__file__).resolve().parent / "assets" / "fonts" / "DS-DIGI.TTF",
            Path(sys.executable).resolve().parent / "app" / "assets" / "fonts" / "DS-DIGI.TTF",
            Path(sys.executable).resolve().parent / "assets" / "fonts" / "DS-DIGI.TTF",
        ]
        for fpath in font_candidates:
            if fpath.is_file():
                QFontDatabase.addApplicationFont(str(fpath))
                break

        self.is_pinned = True
        self._drag_pos = None

        # Set window flags FIRST, without calling show() yet
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(680, 430)
        from skin import get_app_version
        self.setWindowTitle(f"Clock/Alarm v{get_app_version()}")
        self.setMinimumSize(220, 100)
        self.setMouseTracking(True)
        self._drag_pos = None
        self._resize_dir = None
        self._resize_start_global = None
        self._resize_start_geom = None
        self._resize_handles: list[_ResizeHandle] = []
        self._clock_font_px = 0
        self._place_top_right()
        
        self.main_layout = QVBoxLayout(self)
        # Keep the painted panel on the actual window edge. Transparent outer
        # margins make frameless windows impossible to hit with the mouse on
        # some Windows/DPI combinations.
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.bg_widget = QFrame()
        self.bg_widget.setObjectName("bg_widget")
        # autoFillBackground is REQUIRED for QFrame to paint its CSS background
        # inside a WA_TranslucentBackground parent window
        self.bg_widget.setAutoFillBackground(False)
        self.bg_widget.setStyleSheet("""
            QFrame#bg_widget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #141c2b, stop:0.5 #0d1522, stop:1 #060b13);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 16px;
            }
            QFrame#bg_widget QLabel {
                color: #ffffff;
            }
            QFrame#bg_widget QCheckBox {
                color: #ffffff;
            }
            QFrame#timeHero {
                background: qradialgradient(cx:0.5, cy:0.4, radius:0.8, fx:0.5, fy:0.4, stop:0 #091322, stop:1 #03070f);
                border: 1px solid rgba(56, 189, 248, 0.28);
                border-radius: 12px;
            }
            QFrame#detailsPanel {
                background: rgba(8, 18, 25, 0.96);
                border: 1px solid rgba(56, 189, 248, 0.22);
                border-radius: 12px;
            }
            QSpinBox, QComboBox, QLineEdit, QTimeEdit, QListWidget {
                background: #020617; color: #f8fafc;
                border: 1px solid #00e5ff; border-radius: 6px;
                padding: 4px; min-height: 28px; font-size: 13px;
            }
            QComboBox QAbstractItemView {
                background-color: #0d1b2a;
                color: #ffffff;
                selection-background-color: #0284c7;
                selection-color: #ffffff;
                border: 1px solid #00e5ff;
                outline: none;
                padding: 4px;
            }
            QComboBox QAbstractItemView::item {
                min-height: 28px;
                padding: 6px 10px;
                color: #ffffff;
                background-color: #0d1b2a;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #0284c7;
                color: #ffffff;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #0369a1;
                color: #ffffff;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { width: 10px; height: 10px; }
            QListWidget::item { padding: 8px; border-radius: 6px; margin: 2px; background: rgba(0,0,0,0.5); border: 1px solid rgba(0,229,255,0.1); color: #f8fafc; }
            QListWidget::item:selected { background: rgba(0,229,255,0.2); border: 1px solid #00e5ff; }
            QPushButton {
                background: rgba(0, 229, 255, 0.15); color: #00e5ff; border: 1px solid #00e5ff;
                font-weight: bold; font-size: 12px; padding: 6px 12px; border-radius: 6px;
            }
            QPushButton:hover { background: rgba(0, 229, 255, 0.3); color: #ffffff; }
            QPushButton#sectionButton {
                background: transparent; color: #8ea6b4;
                border: none; border-radius: 8px; padding: 7px 12px;
                font-size: 12px; font-weight: 700;
            }
            QPushButton#sectionButton:hover { background: rgba(56,189,248,0.10); color: #e0f2fe; }
            QPushButton#sectionButton:checked { background: rgba(56,189,248,0.16); color: #67e8f9; }
            QPushButton#overlayButton {
                background: rgba(255, 255, 255, 0.08); color: #38bdf8;
                border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 6px; padding: 2px 6px;
                font-size: 12px; font-weight: 800;
            }
            QPushButton#overlayButton:hover { background: rgba(56, 189, 248, 0.25); color: #ffffff; }
            QPushButton#windowButton {
                background: transparent; border: none; border-radius: 8px;
                color: #94a3b8; padding: 0; font-size: 16px; font-weight: 700;
            }
            QPushButton#windowButton:hover { background: rgba(148,163,184,0.16); color: #ffffff; }
            QPushButton#closeButton {
                background: transparent; border: none; border-radius: 8px;
                color: #94a3b8; padding: 0; font-size: 19px; font-weight: 500;
            }
            QPushButton#closeButton:hover { background: #c42b1c; color: #ffffff; }
            QPushButton#danger {
                background: rgba(255, 0, 60, 0.15); color: #ff003c; border: 1px solid #ff003c;
            }
            QPushButton#danger:hover { background: rgba(255, 0, 60, 0.3); color: #ffffff; }
        """)
        self.bg_layout = QVBoxLayout(self.bg_widget)
        self.bg_layout.setContentsMargins(3, 3, 3, 3)
        self.bg_layout.setSpacing(4)
        
        self.time_hero = self._build_time_hero()
        self.bg_layout.addWidget(self.time_hero, stretch=1)

        self.feature_toggle_btn = QPushButton("\u25BC")
        self.feature_toggle_btn.setParent(self.time_hero)
        self.feature_toggle_btn.setObjectName("overlayButton")
        self.feature_toggle_btn.setFixedSize(28, 22)
        self.feature_toggle_btn.setToolTip("快捷功能菜单")
        self.feature_toggle_btn.clicked.connect(self._toggle_feature_menu)

        from bookmarks_ui import BookmarkOrbWidget
        from bookmarks_vault import get_bookmarks_vault

        self.bookmarks_panel = None
        self.bookmark_orb = BookmarkOrbWidget(self.time_hero)
        self.bookmark_orb.set_visual_state(
            unlocked=get_bookmarks_vault().is_unlocked(),
            panel_open=False,
        )
        self.bookmark_orb.clicked.connect(self.toggle_bookmarks_panel)
        self.bookmark_orb.context_action_requested.connect(self._on_bookmark_orb_context_action)

        self.feature_menu = QWidget()
        section_row = QHBoxLayout(self.feature_menu)
        section_row.setContentsMargins(0, 0, 0, 0)
        section_row.setSpacing(6)
        self.section_buttons = []
        for index, text in enumerate(("世界时钟", "闹钟", "倒计时")):
            btn = QPushButton(f"{text}  ›")
            btn.setObjectName("sectionButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, i=index: self._toggle_details(i))
            section_row.addWidget(btn)
            self.section_buttons.append(btn)
        section_row.addStretch(1)
        from skin import make_version_badge
        self.ver_badge = make_version_badge(self)
        section_row.addWidget(self.ver_badge)

        self.pin_btn = QPushButton()
        self.pin_btn.setObjectName("windowButton")
        self.pin_btn.setFixedSize(30, 28)
        self.pin_btn.setToolTip("置顶/取消置顶")
        self._set_pin_style()
        self.pin_btn.clicked.connect(self.toggle_pin)
        section_row.addWidget(self.pin_btn)

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(30, 28)
        close_btn.setToolTip("关闭")
        close_btn.clicked.connect(self.hide)
        section_row.addWidget(close_btn)

        self.feature_menu.hide()
        self.bg_layout.addWidget(self.feature_menu)

        self._timezone_labels: dict[str, str] = {}
        self.details_panel = QFrame(objectName="detailsPanel")
        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(8, 8, 8, 8)
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self._build_clock_tab())
        self.detail_stack.addWidget(self._build_alarm_tab())
        self.detail_stack.addWidget(self._build_timer_tab())
        details_layout.addWidget(self.detail_stack)
        self.details_panel.hide()
        self._expanded_index = -1
        self._collapsed_height = self.height()
        # Reuse the existing controls and timer state in a separate window.
        self.tools_window = QFrame(self, Qt.WindowType.Window)
        self.tools_window.setObjectName("bg_widget")
        from skin import get_app_version, make_version_badge
        self.tools_window.setWindowTitle(f"Clock/Alarm v{get_app_version()} — 闹钟 / 世界时钟 / 倒计时")
        self.tools_window.resize(720, 580)
        self.tools_window.setMinimumSize(520, 420)
        self.tools_window.setStyleSheet("""
            QFrame#bg_widget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0f172a, stop:0.5 #0c1322, stop:1 #080d17);
                border: 1px solid rgba(56, 189, 248, 0.2);
                border-radius: 14px;
                color: #f8fafc;
                font-family: 'Segoe UI', 'Microsoft YaHei', 'Segoe UI Emoji', 'Segoe UI Symbol', -apple-system, sans-serif;
            }
            QLabel {
                color: #cbd5e1;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QSpinBox, QComboBox, QLineEdit, QTimeEdit {
                background: #172238;
                color: #f8fafc;
                border: 1px solid #2d3f5a;
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QSpinBox:focus, QComboBox:focus, QLineEdit:focus, QTimeEdit:focus {
                border: 1px solid #38bdf8;
            }
            QCheckBox {
                color: #cbd5e1;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #475569;
                background: #1e293b;
            }
            QCheckBox::indicator:checked {
                background: #0284c7;
                border-color: #38bdf8;
            }
            QPushButton {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 14px;
                color: #f8fafc;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #334155;
                border-color: #475569;
            }
            QPushButton#primary {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                border: none;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton#primary:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #0284c7);
            }
            QPushButton#danger {
                background: rgba(239, 68, 68, 0.15);
                color: #fca5a5;
                border: 1px solid rgba(239, 68, 68, 0.4);
            }
            QPushButton#danger:hover {
                background: rgba(239, 68, 68, 0.3);
                color: #ffffff;
            }
        """)
        tools_layout = QVBoxLayout(self.tools_window)
        tools_layout.setContentsMargins(16, 14, 16, 14)
        tools_layout.setSpacing(12)

        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(8)

        tabs_container = QFrame()
        tabs_container.setStyleSheet("""
            QFrame {
                background-color: #172033;
                border: 1px solid #223249;
                border-radius: 10px;
                padding: 2px;
            }
        """)
        tabs_layout = QHBoxLayout(tabs_container)
        tabs_layout.setContentsMargins(3, 3, 3, 3)
        tabs_layout.setSpacing(4)

        self.tools_buttons = []
        for index, title in enumerate(("世界时钟", "闹钟", "倒计时")):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #94a3b8;
                    border: none;
                    border-radius: 7px;
                    font-size: 13px;
                    font-weight: 600;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.06);
                    color: #f8fafc;
                }
                QPushButton:checked {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                    color: #ffffff;
                    font-weight: bold;
                }
            """)
            button.clicked.connect(lambda checked=False, i=index: self.show_tools(i))
            tabs_layout.addWidget(button)
            self.tools_buttons.append(button)

        nav_bar.addWidget(tabs_container)
        nav_bar.addStretch(1)
        nav_bar.addWidget(make_version_badge(self.tools_window))
        tools_layout.addLayout(nav_bar)

        tools_layout.addWidget(self.details_panel, stretch=1)
        self.details_panel.show()
        
        self.main_layout.addWidget(self.bg_widget, stretch=1)
        self.resize_grip = QSizeGrip(self)
        self.resize_grip.setFixedSize(18, 18)
        self.resize_grip.setToolTip("拖动调整面板大小")
        self.resize_grip.setStyleSheet("QSizeGrip { background:transparent; border:none; }")
        self._create_resize_handles()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        
        self.clocks: list[ClockWidget] = []
        
        saved = self.state_dict.get("world_clock") or []
        for tz in saved:
            self.add_clock_by_name(tz, self._timezone_labels.get(str(tz), ""))
            
        self.tick()

    def _create_resize_handles(self) -> None:
        specs = (
            (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeFDiagCursor),
            (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.RightEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeFDiagCursor),
        )
        self._resize_handles = [_ResizeHandle(self, edges, cursor) for edges, cursor in specs]
        self._place_resize_handles()

    def _place_resize_handles(self) -> None:
        if len(self._resize_handles) != 8:
            return
        rect = self.rect()
        left, top = rect.left(), rect.top()
        width, height = rect.width(), rect.height()
        edge, corner = 10, 16
        geometries = (
            (left, top + corner, edge, max(0, height - corner * 2)),
            (left + width - edge, top + corner, edge, max(0, height - corner * 2)),
            (left + corner, top, max(0, width - corner * 2), edge),
            (left + corner, top + height - edge, max(0, width - corner * 2), edge),
            (left, top, corner, corner),
            (left + width - corner, top, corner, corner),
            (left, top + height - corner, corner, corner),
            (left + width - corner, top + height - corner, corner, corner),
        )
        for handle, geometry in zip(self._resize_handles, geometries):
            handle.setGeometry(*geometry)
            handle.raise_()
        if hasattr(self, "resize_grip"):
            bg_rect = self.bg_widget.geometry()
            self.resize_grip.move(
                max(0, bg_rect.x() + bg_rect.width() - self.resize_grip.width() - 1),
                max(0, bg_rect.y() + bg_rect.height() - self.resize_grip.height() - 1),
            )
            self.resize_grip.raise_()
        if hasattr(self, "feature_toggle_btn"):
            self.feature_toggle_btn.move(14, 8)
            self.feature_toggle_btn.raise_()
        if hasattr(self, "bookmark_orb") and hasattr(self, "time_hero"):
            menu_h = (self.feature_menu.height() + 4) if (hasattr(self, "feature_menu") and self.feature_menu.isVisible()) else 0
            hero_w = max(120, self.width() - 6)
            hero_h = max(60, self.height() - 6 - menu_h)
            orb_size = max(24, min(68, int(min(hero_w * 0.16, hero_h * 0.25))))
            self.bookmark_orb.set_orb_size(orb_size)
            margin_left = max(12, int(hero_w * 0.032))
            margin_bottom = max(6, int(hero_h * 0.045))
            orb_y = max(34, hero_h - orb_size - margin_bottom)
            self.bookmark_orb.move(margin_left, orb_y)
            self.bookmark_orb.raise_()

    def _build_time_hero(self) -> QWidget:
        """Edge-to-edge giant HH:MM with a smaller live seconds display."""
        hero = QFrame(objectName="timeHero")
        hero.setMinimumHeight(60)
        hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(0, 0, 4, 2)
        layout.setSpacing(0)

        time_group = QWidget()
        time_group.setStyleSheet("background:transparent; border:none;")
        time_row = QHBoxLayout(time_group)
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(0)
        time_row.addStretch(1)

        self.local_time = QLabel("00:00")
        self.local_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.local_time.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.local_time.setStyleSheet(
            "color:#f8fdff; font-family:'DS-Digital','Consolas',monospace;"
            " font-weight:700; letter-spacing:0px;"
            " border:none; background:transparent;"
        )
        time_font = QFont("DS-Digital")
        time_font.setPixelSize(190)
        time_font.setBold(True)
        self.local_time.setFont(time_font)
        time_row.addWidget(self.local_time, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.local_seconds = QLabel(":00")
        self.local_seconds.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.local_seconds.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.local_seconds.setStyleSheet(
            "color:#7dd3fc; font-family:'DS-Digital','Consolas',monospace;"
            " font-weight:700; letter-spacing:0px; border:none; background:transparent;"
        )
        seconds_font = QFont("DS-Digital")
        seconds_font.setPixelSize(72)
        seconds_font.setBold(True)
        self.local_seconds.setFont(seconds_font)
        time_row.addWidget(
            self.local_seconds,
            alignment=Qt.AlignmentFlag.AlignBottom,
        )
        time_row.addStretch(1)
        layout.addWidget(time_group, stretch=1)

        self.local_date = QLabel("2026年08月04日星期二")
        self.local_date.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.local_date.setStyleSheet(
            "color:#7dd3fc; font-size:13px; font-weight:700; letter-spacing:1px;"
            " border:none; background:transparent;"
        )
        self.local_date.setFixedHeight(22)
        layout.addWidget(self.local_date)
        return hero

    def _toggle_feature_menu(self) -> None:
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: rgba(13, 22, 36, 0.96);
                color: #f8fafc;
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: 10px;
                padding: 6px;
            }
            QMenu::item {
                padding: 8px 18px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 700;
            }
            QMenu::item:selected {
                background: rgba(56, 189, 248, 0.22);
                color: #38bdf8;
            }
        """)

        def toggle_clock_details():
            self.show_tools(1)

        actions = [
            ("⏰  闹钟 / 世界时钟 / 倒计时", toggle_clock_details),
            ("✨  灵动书签 (加密收藏夹)", self.toggle_bookmarks_panel),
            ("📋  待办事项", lambda: self.host.show_todos() if self.host else None),
            ("📝  便签", lambda: self.host.show_notes() if self.host else None),
            ("✂️  区域截图", lambda: self.host.start_screenshot_region() if self.host else None),
            ("🎥  屏幕录像", lambda: self.host.show_recorder_board() if self.host else None),
            ("🎬  视频播放器", lambda: self.host.show_media_player2() if self.host else None),
            ("🧹  电脑清理", lambda: self.host.start_deep_clean() if self.host else None),
        ]

        for text, slot in actions:
            act = QAction(text, menu)
            act.triggered.connect(slot)
            menu.addAction(act)

        menu.addSeparator()
        settings_action = QAction("⚙️  设置", menu)
        settings_action.triggered.connect(
            lambda: self.host.show_settings() if self.host else None
        )
        menu.addAction(settings_action)

        pos = self.feature_toggle_btn.mapToGlobal(QPoint(0, self.feature_toggle_btn.height() + 4))
        menu.exec(pos)

    def _ensure_bookmarks_panel(self):
        from bookmarks_ui import BookmarksFloatingPanel

        if getattr(self, "bookmarks_panel", None) is None:
            save_fn = getattr(getattr(self.host, "store", None), "save_state", None)
            self.bookmarks_panel = BookmarksFloatingPanel(
                parent=None,
                config_getter=lambda: self.state_dict,
                config_saver=save_fn,
            )
            self.bookmarks_panel.state_changed.connect(self._on_bookmarks_state_changed)
        return self.bookmarks_panel

    def _on_bookmarks_state_changed(self, unlocked: bool, is_visible: bool, accent_hex: str) -> None:
        if hasattr(self, "bookmark_orb"):
            self.bookmark_orb.set_visual_state(
                unlocked=unlocked,
                panel_open=is_visible,
                accent_hex=accent_hex,
            )

    def toggle_bookmarks_panel(self) -> None:
        panel = self._ensure_bookmarks_panel()
        orb = getattr(self, "bookmark_orb", None)
        panel.toggle_near_orb(orb_widget=orb, anchor_window=self)

    def show_bookmarks_panel(self) -> None:
        panel = self._ensure_bookmarks_panel()
        orb = getattr(self, "bookmark_orb", None)
        panel.show_near_orb(orb_widget=orb, anchor_window=self)

    def _on_bookmark_orb_context_action(self, action_key: str) -> None:
        from bookmarks_ui import export_bookmarks_html_interactive

        panel = self._ensure_bookmarks_panel()
        if action_key == "lock":
            panel.lock_vault()
        elif action_key == "export_html":
            export_bookmarks_html_interactive(self, panel.vault)
        elif action_key == "security":
            panel.open_security_dialog()

    def _place_top_right(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if scr:
            geo = scr.availableGeometry()
            x = geo.right() - self.width() - 24
            y = geo.top() + 40
            self.move(max(geo.left(), x), max(geo.top(), y))

    def _fit_time_font(self) -> None:
        """Keep HH:MM huge while reserving compact room for live seconds."""
        if not hasattr(self, "time_hero") or not hasattr(self, "local_time"):
            return
        target = self.local_time.text() or "00:00"
        seconds_target = self.local_seconds.text() or ":00"
        area = self.time_hero.contentsRect()
        max_width = max(120, area.width() - 4)
        max_height = max(70, area.height() - self.local_date.height() - 2)
        low, high, best = 16, 320, 16
        while low <= high:
            pixel_size = (low + high) // 2
            font = QFont(self.local_time.font())
            font.setPixelSize(pixel_size)
            font.setBold(True)
            metrics = QFontMetrics(font)
            bounds = metrics.boundingRect(target)
            seconds_size = max(10, int(pixel_size * 0.38))
            seconds_font = QFont(self.local_seconds.font())
            seconds_font.setPixelSize(seconds_size)
            seconds_font.setBold(True)
            seconds_metrics = QFontMetrics(seconds_font)
            required_width = (
                metrics.horizontalAdvance(target)
                + seconds_metrics.horizontalAdvance(seconds_target)
            )
            if required_width <= max_width and bounds.height() <= max_height:
                best = pixel_size
                low = pixel_size + 1
            else:
                high = pixel_size - 1
        if best != self._clock_font_px:
            self._clock_font_px = best
            font = QFont(self.local_time.font())
            font.setPixelSize(best)
            font.setBold(True)
            self.local_time.setFont(font)
            seconds_font = QFont(self.local_seconds.font())
            seconds_font.setPixelSize(max(34, int(best * 0.38)))
            seconds_font.setBold(True)
            self.local_seconds.setFont(seconds_font)

    def _toggle_details(self, index: int) -> None:
        self.show_tools(index)

    def show_tools(self, index: int = 1) -> None:
        self._expanded_index = index
        self.detail_stack.setCurrentIndex(index)
        for i, button in enumerate(self.tools_buttons):
            button.setChecked(i == index)
        self.tools_window.showNormal()
        self.tools_window.raise_()
        self.tools_window.activateWindow()


    def _build_clock_tab(self):
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 14, 12, 12)
        lay.setSpacing(12)

        # Header card
        hdr_card = QFrame()
        hdr_card.setStyleSheet("""
            QFrame {
                background: #172238;
                border: 1px solid rgba(56, 189, 248, 0.2);
                border-radius: 12px;
            }
        """)
        hdr_layout = QVBoxLayout(hdr_card)
        hdr_layout.setContentsMargins(14, 12, 14, 12)
        hdr_layout.setSpacing(8)

        t_lbl = QLabel("🌍 全球时区与本地时间对比")
        t_lbl.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold;")
        d_lbl = QLabel("支持按国家、地区或代表城市快速检索，实时显示全球昼夜与相对时差。")
        d_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        hdr_layout.addWidget(t_lbl)
        hdr_layout.addWidget(d_lbl)

        # Search / Add row
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.tz_combo = QComboBox()
        self.tz_combo.setEditable(True)
        self.tz_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for label, zone in timezone_country_choices():
            self.tz_combo.addItem(label, zone)
            self._timezone_labels.setdefault(zone, label)
        style_combo_popup(self.tz_combo)
        self.tz_combo.setCurrentIndex(-1)
        self.tz_combo.setFixedHeight(36)
        self.tz_combo.setStyleSheet("""
            QComboBox {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 2px 8px;
                color: #ffffff;
                font-size: 13px;
            }
            QComboBox:focus {
                border: 1px solid #38bdf8;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
        """)
        self.tz_combo.lineEdit().setPlaceholderText("🔍 输入国家、地区或城市名称搜索…")
        self.tz_combo.lineEdit().setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #ffffff;
                font-size: 13px;
                padding: 0 4px;
            }
        """)
        completer = self.tz_combo.completer()
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

        add_btn = QPushButton("＋ 添加时区")
        add_btn.setObjectName("primary")
        add_btn.setMinimumWidth(88)
        add_btn.setFixedHeight(36)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #0284c7);
            }
        """)
        add_btn.clicked.connect(self.add_clock)

        search_row.addWidget(self.tz_combo, 1)
        search_row.addWidget(add_btn)
        hdr_layout.addLayout(search_row)

        lay.addWidget(hdr_card)

        # Clocks Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.clocks_container = QWidget()
        self.clocks_layout = QVBoxLayout(self.clocks_container)
        self.clocks_layout.setContentsMargins(0, 4, 0, 0)
        self.clocks_layout.setSpacing(10)
        self.clocks_layout.addStretch()

        self.scroll.setWidget(self.clocks_container)
        lay.addWidget(self.scroll, stretch=1)

        return w

    def _build_alarm_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.setContentsMargins(12, 14, 12, 12)

        # Alarm list
        self.list_alarms = QListWidget()
        self.list_alarms.setMinimumHeight(160)
        self.list_alarms.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_alarms.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 2px 0;
            }
            QListWidget::item:selected {
                background: transparent;
            }
        """)
        lay.addWidget(self.list_alarms, stretch=1)

        # Form card
        form_card = QFrame()
        form_card.setObjectName("alarmFormCard")
        form_card.setStyleSheet("""
            QFrame#alarmFormCard {
                background: #172238;
                border: 1px solid rgba(56, 189, 248, 0.2);
                border-radius: 12px;
            }
            QLabel {
                color: #94a3b8;
                font-size: 12px;
                font-weight: 600;
            }
        """)
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(14, 12, 14, 12)
        form_layout.setSpacing(10)

        f_title = QLabel("➕ 新增闹钟提醒")
        f_title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
        form_layout.addWidget(f_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("响铃时间:"), 0, 0)
        self.time_alarm = QTimeEdit(QTime.currentTime())
        self.time_alarm.setDisplayFormat("HH:mm")
        self.time_alarm.setFixedHeight(36)
        self.time_alarm.setStyleSheet("""
            QTimeEdit {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
            }
            QTimeEdit:focus {
                border: 1px solid #38bdf8;
            }
        """)
        grid.addWidget(self.time_alarm, 0, 1)

        grid.addWidget(QLabel("重复周期:"), 0, 2)
        self.cmb_alarm_repeat = QComboBox()
        self.cmb_alarm_repeat.addItems(["仅一次", "每天"])
        style_combo_popup(self.cmb_alarm_repeat)
        self.cmb_alarm_repeat.setFixedHeight(36)
        self.cmb_alarm_repeat.setStyleSheet("""
            QComboBox {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                color: #ffffff;
                font-size: 12px;
            }
            QComboBox:focus {
                border: 1px solid #38bdf8;
            }
        """)
        grid.addWidget(self.cmb_alarm_repeat, 0, 3)

        grid.addWidget(QLabel("提醒备注:"), 1, 0)
        self.txt_alarm_name = QLineEdit()
        self.txt_alarm_name.setPlaceholderText("例如：起床、晨会、吃药、喝水")
        self.txt_alarm_name.setFixedHeight(36)
        self.txt_alarm_name.setStyleSheet("""
            QLineEdit {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                color: #ffffff;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
            }
        """)
        grid.addWidget(self.txt_alarm_name, 1, 1, 1, 3)

        grid.addWidget(QLabel("提示铃声:"), 2, 0)
        self.cmb_alarm_ring = QComboBox()
        ensure_ringtones()
        for rid, name in RINGTONES:
            self.cmb_alarm_ring.addItem(name, rid)
        style_combo_popup(self.cmb_alarm_ring)
        self.cmb_alarm_ring.setFixedHeight(36)
        self.cmb_alarm_ring.setStyleSheet("""
            QComboBox {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                color: #ffffff;
                font-size: 12px;
            }
            QComboBox:focus {
                border: 1px solid #38bdf8;
            }
        """)
        grid.addWidget(self.cmb_alarm_ring, 2, 1, 1, 2)

        btn_prev2 = QPushButton("试听")
        btn_prev2.setFixedHeight(36)
        btn_prev2.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_prev2.setStyleSheet("""
            QPushButton {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #38bdf8;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: #334155;
            }
        """)
        btn_prev2.clicked.connect(lambda: play_ringtone(self.cmb_alarm_ring.currentData() or "beep"))
        grid.addWidget(btn_prev2, 2, 3)

        form_layout.addLayout(grid)

        self.chk_alarm_tts = QCheckBox("响铃时同步语音播报提醒备注")
        self.chk_alarm_tts.setChecked(True)
        form_layout.addWidget(self.chk_alarm_tts)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.btn_alarm_add = QPushButton("＋ 保存并开启闹钟")
        self.btn_alarm_add.setFixedHeight(38)
        self.btn_alarm_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_alarm_add.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff;
                border: none;
                border-radius: 7px;
                font-size: 13px;
                font-weight: bold;
                padding: 6px 18px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #0284c7);
            }
        """)
        self.btn_alarm_add.clicked.connect(self._add_alarm)

        self.btn_alarm_del = QPushButton("删除选中")
        self.btn_alarm_del.setObjectName("danger")
        self.btn_alarm_del.setFixedHeight(38)
        self.btn_alarm_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_alarm_del.clicked.connect(self._delete_alarm)

        btns.addWidget(self.btn_alarm_add, stretch=1)
        btns.addWidget(self.btn_alarm_del)
        form_layout.addLayout(btns)

        lay.addWidget(form_card)

        self._refresh_alarm_list()
        scroll.setWidget(w)
        return scroll

    def _build_timer_tab(self):
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.setContentsMargins(12, 14, 12, 12)

        # Hero Card
        hero_card = QFrame()
        hero_card.setObjectName("timerHero")
        hero_card.setStyleSheet("""
            QFrame#timerHero {
                background: qradialgradient(cx:0.5, cy:0.4, radius:0.8, fx:0.5, fy:0.4, stop:0 #132238, stop:1 #090e18);
                border: 1px solid rgba(56, 189, 248, 0.28);
                border-radius: 14px;
            }
        """)
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(20, 16, 20, 16)
        hero_layout.setSpacing(8)

        # Top status badge
        self.lbl_timer_status = QLabel("⏱️ 倒计时就绪")
        self.lbl_timer_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_timer_status.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600;")
        hero_layout.addWidget(self.lbl_timer_status)

        # Big Time Readout
        self.lbl_timer_display = QLabel("00:05:00")
        self.lbl_timer_display.setStyleSheet("""
            color: #ffffff;
            font-size: 46px;
            font-family: 'Segoe UI', 'Consolas', 'Courier New', monospace;
            font-weight: 800;
            letter-spacing: 2px;
        """)
        self.lbl_timer_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(self.lbl_timer_display)

        # Sub label: 时 分 秒
        sub_units = QLabel("时        :        分        :        秒")
        sub_units.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_units.setStyleSheet("color: #64748b; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        hero_layout.addWidget(sub_units)

        # Dynamic Progress Bar
        self.timer_progress = QProgressBar()
        self.timer_progress.setRange(0, 100)
        self.timer_progress.setValue(100)
        self.timer_progress.setTextVisible(False)
        self.timer_progress.setFixedHeight(6)
        self.timer_progress.setStyleSheet("""
            QProgressBar {
                background: #0f172a;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
                border-radius: 3px;
            }
        """)
        hero_layout.addWidget(self.timer_progress)

        lay.addWidget(hero_card)

        # Quick Presets Row
        presets_box = QVBoxLayout()
        presets_box.setSpacing(4)
        p_label = QLabel("⚡ 快捷预设时长:")
        p_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        presets_box.addWidget(p_label)

        presets_row = QHBoxLayout()
        presets_row.setSpacing(6)
        preset_items = [
            (1, "1分钟"),
            (3, "3分钟"),
            (5, "5分钟"),
            (10, "10分钟"),
            (15, "15分钟"),
            (25, "25分番茄钟"),
            (30, "30分钟"),
            (60, "1小时"),
        ]
        for mins, label in preset_items:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: #172238;
                    color: #94a3b8;
                    border: 1px solid #334155;
                    border-radius: 12px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #0284c7;
                    color: #ffffff;
                    border-color: #38bdf8;
                }
            """)
            btn.clicked.connect(lambda *args, m=mins: self._apply_timer_preset(m))
            presets_row.addWidget(btn)
        presets_box.addLayout(presets_row)
        lay.addLayout(presets_box)

        # Custom Time Steppers
        time_card = QFrame()
        time_card.setObjectName("timerFormCard")
        time_card.setStyleSheet("""
            QFrame#timerFormCard {
                background: #172238;
                border: 1px solid rgba(56, 189, 248, 0.2);
                border-radius: 12px;
            }
            QLabel {
                color: #94a3b8;
                font-size: 12px;
                font-weight: 600;
            }
        """)
        time_layout = QVBoxLayout(time_card)
        time_layout.setContentsMargins(14, 12, 14, 12)
        time_layout.setSpacing(10)

        spin_row = QHBoxLayout()
        spin_row.setSpacing(10)

        self.spin_h = QSpinBox()
        self.spin_h.setRange(0, 23)
        self.spin_h.setSuffix(" 小时")
        self.spin_h.valueChanged.connect(self._on_timer_spin_changed)

        self.spin_m = QSpinBox()
        self.spin_m.setRange(0, 59)
        self.spin_m.setSuffix(" 分钟")
        self.spin_m.setValue(5)
        self.spin_m.valueChanged.connect(self._on_timer_spin_changed)

        self.spin_s = QSpinBox()
        self.spin_s.setRange(0, 59)
        self.spin_s.setSuffix(" 秒钟")
        self.spin_s.valueChanged.connect(self._on_timer_spin_changed)

        for s in (self.spin_h, self.spin_m, self.spin_s):
            s.setFixedHeight(36)
            s.setStyleSheet("""
                QSpinBox {
                    background: #0f172a;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 4px 10px;
                    color: #ffffff;
                    font-size: 13px;
                    font-weight: bold;
                }
                QSpinBox:focus {
                    border: 1px solid #38bdf8;
                }
            """)
            spin_row.addWidget(s)
        time_layout.addLayout(spin_row)

        self.txt_timer_name = QLineEdit()
        self.txt_timer_name.setPlaceholderText("提示备注，例如：烧水、小憩、番茄钟休息")
        self.txt_timer_name.setFixedHeight(36)
        self.txt_timer_name.setStyleSheet("""
            QLineEdit {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                color: #ffffff;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
            }
        """)
        time_layout.addWidget(self.txt_timer_name)

        ring_row = QHBoxLayout()
        ring_row.setSpacing(8)
        ring_row.addWidget(QLabel("到期铃声:"))
        self.cmb_timer_ring = QComboBox()
        for rid, name in RINGTONES:
            self.cmb_timer_ring.addItem(name, rid)
        style_combo_popup(self.cmb_timer_ring)
        self.cmb_timer_ring.setFixedHeight(36)
        self.cmb_timer_ring.setStyleSheet("""
            QComboBox {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                color: #ffffff;
                font-size: 12px;
            }
            QComboBox:focus {
                border: 1px solid #38bdf8;
            }
        """)
        btn_preview = QPushButton("试听")
        btn_preview.setFixedHeight(36)
        btn_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_preview.setStyleSheet("""
            QPushButton {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #38bdf8;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: #334155;
            }
        """)
        btn_preview.clicked.connect(lambda: play_ringtone(self.cmb_timer_ring.currentData() or "beep"))
        ring_row.addWidget(self.cmb_timer_ring, 1)
        ring_row.addWidget(btn_preview)
        time_layout.addLayout(ring_row)

        self.chk_timer_tts = QCheckBox("倒计时结束时语音播报备注")
        self.chk_timer_tts.setChecked(True)
        time_layout.addWidget(self.chk_timer_tts)

        lay.addWidget(time_card)

        # Bottom Actions
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.btn_timer_start = QPushButton("开始计时")
        self.btn_timer_start.setFixedHeight(40)
        self.btn_timer_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_timer_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff;
                border: none;
                border-radius: 7px;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 18px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #0284c7);
            }
        """)
        self.btn_timer_start.clicked.connect(self._start_timer)

        self.btn_timer_pause = QPushButton("暂停")
        self.btn_timer_pause.setFixedHeight(40)
        self.btn_timer_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_timer_pause.setEnabled(False)
        self.btn_timer_pause.setStyleSheet("""
            QPushButton {
                background: #075985;
                color: #e0f2fe;
                border: 1px solid #0284c7;
                border-radius: 7px;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 18px;
            }
            QPushButton:hover {
                background: #0369a1;
            }
            QPushButton:disabled {
                background: #1e293b;
                color: #64748b;
                border-color: #334155;
            }
        """)
        self.btn_timer_pause.clicked.connect(self._pause_timer)

        self.btn_timer_reset = QPushButton("重置")
        self.btn_timer_reset.setFixedHeight(40)
        self.btn_timer_reset.setObjectName("danger")
        self.btn_timer_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_timer_reset.clicked.connect(self._reset_timer)

        btns.addWidget(self.btn_timer_start, stretch=1)
        btns.addWidget(self.btn_timer_pause, stretch=1)
        btns.addWidget(self.btn_timer_reset)
        lay.addLayout(btns)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._update_timer_ui)
        self.refresh_timer.start(500)
        return w

    def _apply_timer_preset(self, minutes: int):
        h = minutes // 60
        m = minutes % 60
        self.spin_h.setValue(h)
        self.spin_m.setValue(m)
        self.spin_s.setValue(0)
        if not self.state_dict.get("timer", {}).get("active"):
            self.lbl_timer_display.setText(f"{h:02d}:{m:02d}:00")
            if hasattr(self, "timer_progress"):
                self.timer_progress.setValue(100)
            if hasattr(self, "lbl_timer_status"):
                self.lbl_timer_status.setText(f"⏱️ 预设已就绪: {minutes} 分钟")

    def _on_timer_spin_changed(self):
        if not self.state_dict.get("timer", {}).get("active"):
            h = self.spin_h.value()
            m = self.spin_m.value()
            s = self.spin_s.value()
            self.lbl_timer_display.setText(f"{h:02d}:{m:02d}:{s:02d}")
            if hasattr(self, "timer_progress"):
                self.timer_progress.setValue(100)
            if hasattr(self, "lbl_timer_status"):
                self.lbl_timer_status.setText("⏱️ 倒计时就绪")

    def _set_pin_style(self):
        if self.is_pinned:
            self.pin_btn.setText("◆")
            self.pin_btn.setToolTip("已置顶，点击取消")
            self.pin_btn.setStyleSheet(
                "QPushButton { background:rgba(56,189,248,0.14); border:none; border-radius:8px;"
                " color:#67e8f9; font-size:13px; }"
                "QPushButton:hover { background:rgba(56,189,248,0.25); color:#ffffff; }"
            )
        else:
            self.pin_btn.setText("◇")
            self.pin_btn.setToolTip("置顶")
            self.pin_btn.setStyleSheet(
                "QPushButton { background:transparent; border:none; border-radius:8px;"
                " color:#78909c; font-size:14px; }"
                "QPushButton:hover { background:rgba(148,163,184,0.16); color:#ffffff; }"
            )

    def _update_window_flags(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.is_pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # Only re-show if window was already visible (changing flags hides it)
        if self.isVisible():
            self.show()

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self._set_pin_style()
        self._update_window_flags()

    def toggle_accordion(self):
        if self.accordion_widget.isHidden():
            self.accordion_widget.show()
            if hasattr(self, "toggle_btn"):
                self.toggle_btn.setText("▲ 收起其他时区")
        else:
            self.accordion_widget.hide()
            if hasattr(self, "toggle_btn"):
                self.toggle_btn.setText("▼ 展开其他时区")

    def tick(self):
        now = datetime.datetime.now().astimezone()
        weekdays_cn = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
        time_text = now.strftime("%H:%M")
        if self.local_time.text() != time_text:
            self.local_time.setText(time_text)
            QTimer.singleShot(0, self._fit_time_font)
        self.local_seconds.setText(now.strftime(":%S"))
        self.local_date.setText(
            f"{now.year:04d}年{now.month:02d}月{now.day:02d}日{weekdays_cn[now.weekday()]}"
        )

        now_utc = datetime.datetime.now(datetime.timezone.utc).astimezone()
        for cw in self.clocks:
            cw.update_time(now_utc)

    def add_clock(self):
        index = self.tz_combo.currentIndex()
        tz = self.tz_combo.itemData(index) if index >= 0 else None
        if not tz:
            typed = self.tz_combo.currentText().strip()
            exact = self.tz_combo.findText(typed, Qt.MatchFlag.MatchExactly)
            if exact >= 0:
                index = exact
                tz = self.tz_combo.itemData(exact)
        if not tz:
            self.tz_combo.setFocus()
            self.tz_combo.lineEdit().selectAll()
            return
        display = self.tz_combo.itemText(index)
        self.add_clock_by_name(str(tz), display)
        self.state_dict["world_clock"] = [cw.tz_name for cw in self.clocks]
        self.tz_combo.setCurrentIndex(-1)
        self.tz_combo.clearEditText()

    def add_clock_by_name(self, tz_name: str, display_name: str = ""):
        if any(cw.tz_name == tz_name for cw in self.clocks):
            return
        if tz_name not in pytz.all_timezones_set:
            return
        cw = ClockWidget(
            tz_name,
            display_name or self._timezone_labels.get(tz_name, ""),
            on_remove=self._remove_clock,
        )
        self.clocks.append(cw)
        self.clocks_layout.insertWidget(self.clocks_layout.count() - 1, cw)
        self.tick()

    def _remove_clock(self, clock: ClockWidget) -> None:
        if clock not in self.clocks:
            return
        self.clocks.remove(clock)
        self.clocks_layout.removeWidget(clock)
        clock.deleteLater()
        self.state_dict["world_clock"] = [cw.tz_name for cw in self.clocks]

    def _add_alarm(self):
        time_str = self.time_alarm.time().toString("HH:mm")
        name = self.txt_alarm_name.text().strip() or "闹钟"
        repeat = "once" if self.cmb_alarm_repeat.currentIndex() == 0 else "daily"
        alarm = {
            "id": str(uuid.uuid4())[:8],
            "time": time_str,
            "name": name,
            "repeat": repeat,
            "enabled": True,
            "ringtone": self.cmb_alarm_ring.currentData() or "beep",
            "tts": bool(self.chk_alarm_tts.isChecked()),
            "last_triggered_date": "",
        }
        self.state_dict.setdefault("alarms", []).append(alarm)
        self._refresh_alarm_list(select_id=alarm["id"])
        self._grow_for_alarm_count()
        self.txt_alarm_name.clear()

    def _delete_alarm(self):
        curr = self.list_alarms.currentItem()
        if not curr: return
        alarm_id = curr.data(Qt.ItemDataRole.UserRole)
        self.state_dict["alarms"] = [a for a in (self.state_dict.get("alarms") or []) if a.get("id") != alarm_id]
        self._refresh_alarm_list()

    def _toggle_alarm(self, alarm_id: str):
        for a in self.state_dict.get("alarms") or []:
            if a.get("id") == alarm_id:
                a["enabled"] = not a.get("enabled", True)
                break
        self._refresh_alarm_list(select_id=alarm_id)

    def _delete_alarm_by_id(self, alarm_id: str):
        self.state_dict["alarms"] = [a for a in (self.state_dict.get("alarms") or []) if a.get("id") != alarm_id]
        self._refresh_alarm_list()

    def _refresh_alarm_list(self, select_id: str | None = None):
        self.list_alarms.clear()
        name_map = {rid: name for rid, name in RINGTONES}
        selected_item = None
        for a in self.state_dict.get("alarms") or []:
            rep = "每天" if a.get("repeat") == "daily" else "仅一次"
            st = "已开启" if a.get("enabled") else "已关闭"
            ring = name_map.get(str(a.get("ringtone") or "beep"), "经典哔哔")
            text = f"⏰ {a.get('time')}  ·  {rep}  ·  {a.get('name')}\n   铃声：{ring}  ·  状态：{st}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, a.get("id"))
            item.setSizeHint(QSize(0, 68))
            self.list_alarms.addItem(item)

            # Rich Alarm Card Widget
            card = QFrame()
            card.setObjectName("alarmCard")
            enabled = bool(a.get("enabled", True))
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(12)

            # Left Time and Name
            left_v = QVBoxLayout()
            left_v.setSpacing(4)

            time_row = QHBoxLayout()
            time_row.setSpacing(10)
            time_lbl = QLabel(str(a.get("time") or "00:00"))
            time_lbl.setStyleSheet(f"""
                color: {'#ffffff' if enabled else '#64748b'};
                font-size: 24px;
                font-family: 'Segoe UI', 'Consolas', monospace;
                font-weight: 700;
            """)
            name_lbl = QLabel(str(a.get("name") or "闹钟"))
            name_lbl.setStyleSheet(f"""
                color: {'#cbd5e1' if enabled else '#64748b'};
                font-size: 13px;
                font-weight: 600;
            """)
            time_row.addWidget(time_lbl)
            time_row.addWidget(name_lbl)
            time_row.addStretch()
            left_v.addLayout(time_row)

            # Badges
            b_row = QHBoxLayout()
            b_row.setSpacing(6)
            rep_lbl = QLabel(rep)
            if a.get("repeat") == "daily":
                rep_lbl.setStyleSheet("background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); border-radius: 4px; padding: 1px 6px; font-size: 11px;")
            else:
                rep_lbl.setStyleSheet("background: rgba(148,163,184,0.12); color: #94a3b8; border: 1px solid rgba(148,163,184,0.25); border-radius: 4px; padding: 1px 6px; font-size: 11px;")
            b_row.addWidget(rep_lbl)

            ring_lbl = QLabel(f"🔔 {ring}")
            ring_lbl.setStyleSheet("background: rgba(56,189,248,0.12); color: #38bdf8; border: 1px solid rgba(56,189,248,0.25); border-radius: 4px; padding: 1px 6px; font-size: 11px;")
            b_row.addWidget(ring_lbl)

            if a.get("tts"):
                tts_lbl = QLabel("🗣️ 语音播报")
                tts_lbl.setStyleSheet("background: rgba(245,158,11,0.12); color: #fbbf24; border: 1px solid rgba(245,158,11,0.25); border-radius: 4px; padding: 1px 6px; font-size: 11px;")
                b_row.addWidget(tts_lbl)

            b_row.addStretch()
            left_v.addLayout(b_row)
            cl.addLayout(left_v, stretch=1)

            # Right Toggle and Delete buttons
            toggle_btn = QPushButton("已开启" if enabled else "已停用")
            toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if enabled:
                toggle_btn.setStyleSheet("background: #064e3b; color: #34d399; border: 1px solid #059669; border-radius: 6px; font-size: 11px; padding: 4px 10px; font-weight: bold;")
            else:
                toggle_btn.setStyleSheet("background: #1e293b; color: #64748b; border: 1px solid #334155; border-radius: 6px; font-size: 11px; padding: 4px 10px;")
            aid = a.get("id")
            toggle_btn.clicked.connect(lambda *args, al_id=aid: self._toggle_alarm(al_id))
            cl.addWidget(toggle_btn)

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(26, 26)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setToolTip("删除此闹钟")
            del_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255,255,255,0.05);
                    color: #94a3b8;
                    border: 1px solid rgba(255,255,255,0.1);
                    border-radius: 13px;
                    font-size: 13px;
                    font-weight: bold;
                    padding: 0;
                }
                QPushButton:hover {
                    background: rgba(239,68,68,0.25);
                    color: #fca5a5;
                    border: 1px solid rgba(239,68,68,0.5);
                }
            """)
            del_btn.clicked.connect(lambda *args, al_id=aid: self._delete_alarm_by_id(al_id))
            cl.addWidget(del_btn)

            card.setStyleSheet("""
                QFrame#alarmCard {
                    background: #172238;
                    border: 1px solid rgba(56, 189, 248, 0.16);
                    border-radius: 10px;
                }
                QFrame#alarmCard:hover {
                    background: #1b2842;
                    border: 1px solid rgba(56, 189, 248, 0.35);
                }
                QLabel {
                    background: transparent;
                    border: none;
                }
            """)
            self.list_alarms.setItemWidget(item, card)

            if select_id and a.get("id") == select_id:
                selected_item = item

        if self.list_alarms.count() == 0:
            empty = QListWidgetItem("（还没有闹钟，请在下方添加）")
            empty.setSizeHint(QSize(0, 52))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_alarms.addItem(empty)
            empty_card = QFrame()
            empty_card.setStyleSheet("background: #172238; border: 1px dashed rgba(56,189,248,0.25); border-radius: 10px;")
            el = QVBoxLayout(empty_card)
            el.setContentsMargins(12, 14, 12, 14)
            lbl = QLabel("⏰ 暂未设置任何闹钟\n请在下方设置时间并点击「＋ 保存并开启闹钟」快速创建")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #64748b; font-size: 12px; line-height: 1.4;")
            el.addWidget(lbl)
            self.list_alarms.setItemWidget(empty, empty_card)
        elif selected_item is not None:
            self.list_alarms.setCurrentItem(selected_item)
            self.list_alarms.scrollToItem(
                selected_item,
                QAbstractItemView.ScrollHint.EnsureVisible,
            )
            QTimer.singleShot(
                0,
                lambda item=selected_item: self.list_alarms.scrollToItem(
                    item, QAbstractItemView.ScrollHint.EnsureVisible
                ),
            )
        alarm_count = len(self.state_dict.get("alarms") or [])
        self.list_alarms.setMinimumHeight(min(334, max(160, alarm_count * 70 + 16)))
        self.list_alarms.setMaximumHeight(360)

    def _grow_for_alarm_count(self) -> None:
        """Give newly added alarms visible room, then rely on list scrolling."""
        count = len(self.state_dict.get("alarms") or [])
        list_height = min(334, max(160, count * 70 + 16))
        self.list_alarms.setMinimumHeight(list_height)
        self.list_alarms.setMaximumHeight(360)
        if hasattr(self, "tools_window"):
            return
        if not self.isVisible() or self._expanded_index != 1:
            return
        screen = self.screen()
        max_height = screen.availableGeometry().height() - 32 if screen else 860
        extra = min(3, max(0, count - 1)) * 70
        target = min(max_height, max(self.height(), 610 + extra))
        if target > self.height():
            self.resize(self.width(), target)

    def _update_timer_ui(self):
        t_cfg = self.state_dict.get("timer") or {}
        active = bool(t_cfg.get("active"))
        rem = int(t_cfg.get("remaining") or 0)
        h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
        self.lbl_timer_display.setText(f"{h:02d}:{m:02d}:{s:02d}")

        total = int(t_cfg.get("total") or (self.spin_h.value() * 3600 + self.spin_m.value() * 60 + self.spin_s.value()) or 1)
        if total > 0 and hasattr(self, "timer_progress"):
            pct = max(0, min(100, int((rem / total) * 100)))
            self.timer_progress.setValue(pct)
            if hasattr(self, "lbl_timer_status"):
                if active:
                    self.lbl_timer_status.setText(f"🕒 正在倒计时... (剩余 {pct}%)")
                    self.lbl_timer_status.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 600;")
                elif t_cfg.get("paused"):
                    self.lbl_timer_status.setText("⏸ 倒计时已暂停")
                    self.lbl_timer_status.setStyleSheet("color: #fbbf24; font-size: 12px; font-weight: 600;")
                elif rem == 0 and not active:
                    self.lbl_timer_status.setText("✓ 计时已完成")
                    self.lbl_timer_status.setStyleSheet("color: #34d399; font-size: 12px; font-weight: 600;")
                else:
                    self.lbl_timer_status.setText("⏱ 倒计时就绪")
                    self.lbl_timer_status.setStyleSheet("color: #94a3b8; font-size: 12px;")

        self.btn_timer_start.setEnabled(not active)
        self.btn_timer_pause.setEnabled(active or bool(t_cfg.get("paused")))
        self.btn_timer_pause.setText("继续" if t_cfg.get("paused") else "暂停")

    def _start_timer(self):
        t_cfg = self.state_dict.setdefault("timer", {})
        total = self.spin_h.value() * 3600 + self.spin_m.value() * 60 + self.spin_s.value()
        if total <= 0: return
        t_cfg["active"] = True
        t_cfg["remaining"] = total
        t_cfg["total"] = total
        t_cfg["label"] = self.txt_timer_name.text().strip() or "倒计时"
        t_cfg["paused"] = False
        t_cfg["ringtone"] = self.cmb_timer_ring.currentData() or "beep"
        t_cfg["tts"] = bool(self.chk_timer_tts.isChecked())
        if hasattr(self, "timer_progress"):
            self.timer_progress.setMaximum(100)
            self.timer_progress.setValue(100)
        self._update_timer_ui()

    def _pause_timer(self):
        t_cfg = self.state_dict.setdefault("timer", {})
        if t_cfg.get("active"):
            t_cfg["active"] = False
            t_cfg["paused"] = True
        elif t_cfg.get("paused") and int(t_cfg.get("remaining") or 0) > 0:
            t_cfg["active"] = True
            t_cfg["paused"] = False
        self._update_timer_ui()

    def _reset_timer(self):
        t_cfg = self.state_dict.setdefault("timer", {})
        t_cfg["active"] = False
        t_cfg["remaining"] = 0
        t_cfg["paused"] = False
        stop_ringtone()
        if hasattr(self, "timer_progress"):
            self.timer_progress.setValue(0)
        self._update_timer_ui()

    # ── Resize / drag edge detection ──────────────────────────────────────
    def resizeEvent(self, event):
        """Scale the clock face with the window without clipping the digits."""
        self._place_resize_handles()
        super().resizeEvent(event)
        QTimer.singleShot(0, self._place_resize_handles)
        if hasattr(self, "local_time"):
            self._fit_time_font()
            QTimer.singleShot(0, self._fit_time_font)

    _EDGE = 8  # px from edge = resize zone

    def _get_resize_edges(self, pos):
        """Return (left, right, top, bottom) booleans for resize edges."""
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        e = self._EDGE
        return (
            x < e,          # left
            x > w - e,      # right
            y < e,          # top
            y > h - e,      # bottom
        )

    def _cursor_for_edges(self, left, right, top, bottom):
        from PyQt6.QtCore import Qt as _Qt
        if (left and top) or (right and bottom):
            return _Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return _Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return _Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return _Qt.CursorShape.SizeVerCursor
        return _Qt.CursorShape.ArrowCursor

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            left, right, top, bottom = self._get_resize_edges(pos)
            if any((left, right, top, bottom)):
                # Start resize
                self._resize_dir = (left, right, top, bottom)
                self._resize_start_global = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
                self._drag_pos = None
            else:
                # Start drag-to-move
                self._drag_pos = event.globalPosition().toPoint()
                self._resize_dir = None
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        if event.buttons() == Qt.MouseButton.LeftButton:
            if self._resize_dir is not None:
                # Handle resize
                left, right, top, bottom = self._resize_dir
                gpos = event.globalPosition().toPoint()
                dx = gpos.x() - self._resize_start_global.x()
                dy = gpos.y() - self._resize_start_global.y()
                r = self._resize_start_geom
                new_x, new_y = r.x(), r.y()
                new_w, new_h = r.width(), r.height()
                if left:
                    new_x = r.x() + dx
                    new_w = max(220, r.width() - dx)
                if right:
                    new_w = max(220, r.width() + dx)
                if top:
                    new_y = r.y() + dy
                    new_h = max(100, r.height() - dy)
                if bottom:
                    new_h = max(100, r.height() + dy)
                self.setGeometry(new_x, new_y, new_w, new_h)
            elif self._drag_pos is not None:
                # Handle move
                delta = event.globalPosition().toPoint() - self._drag_pos
                self.move(self.pos() + delta)
                self._drag_pos = event.globalPosition().toPoint()
            event.accept()
        else:
            # Update cursor based on hover position
            left, right, top, bottom = self._get_resize_edges(pos)
            self.setCursor(self._cursor_for_edges(left, right, top, bottom))

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        self._resize_dir = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        event.accept()


class AlarmRingingDialog(QDialog):
    """Mobile-like popup window for alarm ringing.
    Appears centered on desktop, rings continuously until user clicks '关闭闹钟'.
    """

    def __init__(self, alarm_data: dict, parent=None):
        super().__init__(parent)
        self.alarm_data = alarm_data
        from skin import get_app_version, make_version_badge
        self.setWindowTitle(f"闹钟提醒 - Clock/Alarm v{get_app_version()}")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(440, 260)

        scr = QGuiApplication.primaryScreen()
        if scr:
            geo = scr.availableGeometry()
            x = geo.left() + (geo.width() - 440) // 2
            y = geo.top() + (geo.height() - 260) // 2
            self.move(x, y)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #220819, stop:1 #0a0209);
                border: 2px solid #ff2a6d;
                border-radius: 16px;
            }
            QLabel { color: #ffffff; }
        """)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(24, 20, 24, 20)
        bl.setSpacing(10)

        top_row = QHBoxLayout()
        icon_lbl = QLabel("⏰ 闹钟响铃提醒")
        icon_lbl.setStyleSheet("color: #ff2a6d; font-size: 16px; font-weight: 800; border: none; background: transparent;")
        top_row.addWidget(icon_lbl, 1)
        top_row.addWidget(make_version_badge(self))
        bl.addLayout(top_row)

        alarm_time = str(self.alarm_data.get("time") or datetime.datetime.now().strftime("%H:%M"))
        lbl_time = QLabel(alarm_time)
        lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_time.setStyleSheet("""
            color: #ffffff;
            font-size: 52px;
            font-family: 'DS-Digital', 'Consolas', monospace;
            font-weight: 800;
            border: none;
            background: transparent;
        """)
        bl.addWidget(lbl_time)

        alarm_name = str(self.alarm_data.get("name") or "提醒时间已到")
        lbl_name = QLabel(alarm_name)
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_name.setStyleSheet("color: #ff85a2; font-size: 15px; font-weight: 700; border: none; background: transparent;")
        bl.addWidget(lbl_name)

        btn_dismiss = QPushButton("🔔  关闭闹钟  🔔")
        btn_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_dismiss.setStyleSheet("""
            QPushButton {
                background: #ff2a6d;
                color: #ffffff;
                font-size: 18px;
                font-weight: 800;
                border: none;
                border-radius: 12px;
                min-height: 48px;
            }
            QPushButton:hover {
                background: #ff5288;
            }
            QPushButton:pressed {
                background: #d9004c;
            }
        """)
        btn_dismiss.clicked.connect(self.dismiss)
        bl.addWidget(btn_dismiss)

        layout.addWidget(box)

        # Start continuous looping ringtone
        ringtone_id = str(self.alarm_data.get("ringtone") or "beep")
        try:
            from alarm_sounds import play_ringtone
            play_ringtone(ringtone_id, loop=True)
        except Exception:
            pass

    def dismiss(self) -> None:
        try:
            from alarm_sounds import stop_ringtone
            stop_ringtone()
        except Exception:
            pass
        self.close()

    def closeEvent(self, event) -> None:
        try:
            from alarm_sounds import stop_ringtone
            stop_ringtone()
        except Exception:
            pass
        super().closeEvent(event)

    def reject(self) -> None:
        try:
            from alarm_sounds import stop_ringtone
            stop_ringtone()
        except Exception:
            pass
        super().reject()
