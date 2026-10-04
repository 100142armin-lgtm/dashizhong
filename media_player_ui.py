"""Media player with crystal-clear docked controls, smooth collapsible playlist, high-speed streaming, HD quality switcher, and modern UI."""

from __future__ import annotations

import os
import hashlib
import random
import re
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
import ctypes
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QRect, QRectF, QPointF, QSize, QUrl, QEvent
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaDevices, QAudioDevice
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
    QLabel, QFileDialog, QSlider, QListWidget, QListWidgetItem, QMenu, QSizePolicy,
    QDialog, QLineEdit, QCheckBox, QComboBox, QScrollArea, QFrame, QMessageBox,
    QStyledItemDelegate, QStyle
)
from PyQt6.QtGui import (
    QKeyEvent, QAction, QIcon, QPixmap, QPainter, QPen, QColor,
    QPainterPath, QFont
)
import yt_dlp
from skin import get_app_version, make_version_badge
from yt_feed_monitor import resolve_channel_id, YouTubeFeedMonitor

MAX_INPUT_URLS = 20
MAX_URL_LENGTH = 2048
MAX_TITLE_LENGTH = 240
MAX_QUEUE_ITEMS = 500
DEFAULT_PLAYLIST_LIMIT = 100
MAX_COMPAT_CACHE_BYTES = 512 * 1024 * 1024


# ─── Chinese Simp/Trad Converter & Search Engine ───────────────────────────

def _get_lc_mapper():
    try:
        return ctypes.windll.kernel32.LCMapStringW
    except Exception:
        return None

_LCMapStringW = _get_lc_mapper()
LCMAP_SIMPLIFIED = 0x02000000
LCMAP_TRADITIONAL = 0x04000000


def to_simplified(text: str) -> str:
    if not text or not _LCMapStringW:
        return text
    try:
        buf = ctypes.create_unicode_buffer(len(text) + 2)
        ret = _LCMapStringW(0x0804, LCMAP_SIMPLIFIED, text, len(text), buf, len(buf))
        if ret > 0:
            return buf.value[:ret]
    except Exception:
        pass
    return text


def to_traditional(text: str) -> str:
    if not text or not _LCMapStringW:
        return text
    try:
        buf = ctypes.create_unicode_buffer(len(text) + 2)
        ret = _LCMapStringW(0x0804, LCMAP_TRADITIONAL, text, len(text), buf, len(buf))
        if ret > 0:
            return buf.value[:ret]
    except Exception:
        pass
    return text


def matches_search(query: str, target: str) -> bool:
    clean_q = str(query or "").strip().lower()
    if not clean_q:
        return True
    clean_t = str(target or "").lower()
    words = clean_q.split()
    simp_t = to_simplified(clean_t)
    trad_t = to_traditional(clean_t)
    for word in words:
        simp_w = to_simplified(word)
        trad_w = to_traditional(word)
        if not (word in clean_t or simp_w in simp_t or trad_w in trad_t):
            return False
    return True


def _get_persistent_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    p = Path(base) / "ClockAlarm" / "MediaCache"
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        return Path(tempfile.gettempdir())


def get_media_cache_size(cache_dir: Path | None = None) -> int:
    """Calculate the total size in bytes of all cached files in the persistent media cache."""
    root = cache_dir if cache_dir is not None else _get_persistent_cache_dir()
    if not root.exists() or not root.is_dir():
        return 0
    total = 0
    try:
        for p in root.iterdir():
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def prune_media_cache(cache_dir: Path | None = None, max_bytes: int = 500 * 1024 * 1024) -> int:
    """
    LRU eviction: prune oldest cached media files if total cache exceeds max_bytes.
    Prunes down to 80% of max_bytes to provide headroom and prevent frequent evictions.
    Returns the number of bytes freed.
    """
    root = cache_dir if cache_dir is not None else _get_persistent_cache_dir()
    if not root.exists() or not root.is_dir() or max_bytes <= 0:
        return 0

    formats = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4a', '.mp3', '.ogg', '.opus', '.wav', '.flac'}
    files_info = []
    total_bytes = 0
    try:
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower() in formats:
                try:
                    st = p.stat()
                    total_bytes += st.st_size
                    recent_time = max(getattr(st, "st_atime_ns", 0), getattr(st, "st_mtime_ns", 0))
                    files_info.append((recent_time, st.st_size, p))
                except OSError:
                    pass
    except OSError:
        return 0

    if total_bytes <= max_bytes:
        return 0

    target_bytes = int(max_bytes * 0.8)
    files_info.sort(key=lambda item: item[0])
    freed = 0
    for _, sz, p in files_info:
        if total_bytes - freed <= target_bytes:
            break
        try:
            p.unlink(missing_ok=True)
            freed += sz
        except OSError:
            pass
    return freed


def clear_media_cache(cache_dir: Path | None = None) -> int:
    """Safely clear all media files in the persistent media cache. Returns bytes freed."""
    root = cache_dir if cache_dir is not None else _get_persistent_cache_dir()
    if not root.exists() or not root.is_dir():
        return 0
    freed = 0
    formats = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4a', '.mp3', '.ogg', '.opus', '.wav', '.flac'}
    try:
        for p in root.iterdir():
            if p.is_file() and (p.suffix.lower() in formats or p.name.startswith("media-")):
                try:
                    sz = p.stat().st_size
                    p.unlink(missing_ok=True)
                    freed += sz
                except OSError:
                    pass
    except OSError:
        pass
    return freed


# ─── Custom Playlist Delegate & Widget ─────────────────────────────────────

class PlaylistItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(max(s.width(), 220), max(s.height(), 40))

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background state
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#0c4a6e"))
            painter.fillRect(QRect(option.rect.left(), option.rect.top(), 3, option.rect.height()), QColor("#38bdf8"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#1e293b"))

        # Text and status
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        is_fav = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        is_current = bool(index.data(Qt.ItemDataRole.UserRole + 2))

        text_rect = QRect(
            option.rect.left() + 8,
            option.rect.top() + 4,
            max(20, option.rect.width() - 42),
            option.rect.height() - 8
        )
        if is_current:
            painter.setPen(QColor("#38bdf8"))
            f = painter.font()
            f.setBold(True)
            painter.setFont(f)
        elif option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QColor("#ffffff"))
        else:
            painter.setPen(QColor("#e2e8f0"))

        painter.drawText(text_rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignVCenter, text)

        # Star
        star_rect = QRect(
            option.rect.right() - 30,
            option.rect.top() + (option.rect.height() - 24) // 2,
            24, 24
        )
        f = painter.font()
        f.setPointSize(13)
        painter.setFont(f)
        if is_fav:
            painter.setPen(QColor("#fbbf24"))
            painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "★")
        else:
            painter.setPen(QColor("#64748b"))
            painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "☆")

        painter.restore()


class PlayListWidget(QListWidget):
    star_clicked = pyqtSignal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            item = self.itemAt(pos)
            if item:
                rect = self.visualItemRect(item)
                if pos.x() >= rect.right() - 34:
                    self.star_clicked.emit(self.row(item))
                    return
        super().mousePressEvent(event)



# ─── Icon Factory ──────────────────────────────────────────────────────────

def _make_icon(draw_fn, size=22, color='#e2e8f0'):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_fn(p, float(size), QColor(color))
    p.end()
    return QIcon(pm)


def _make_dual_icon(draw_fn, size=22, off_color='#94a3b8', on_color='#38bdf8'):
    icon = QIcon()
    for state, color in ((QIcon.State.Off, off_color), (QIcon.State.On, on_color)):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_fn(p, float(size), QColor(color))
        p.end()
        icon.addPixmap(pm, QIcon.Mode.Normal, state)
    return icon


# ── Individual icon drawings ──

def _draw_folder(p, s, c):
    p.setPen(QPen(QColor('#e6a800'), 1.2))
    p.setBrush(QColor('#ffc107'))
    tab = QPainterPath()
    tab.moveTo(s * 0.12, s * 0.35)
    tab.lineTo(s * 0.12, s * 0.24)
    tab.lineTo(s * 0.42, s * 0.24)
    tab.lineTo(s * 0.48, s * 0.35)
    tab.closeSubpath()
    p.drawPath(tab)
    p.drawRoundedRect(QRectF(s * 0.12, s * 0.35, s * 0.76, s * 0.42), 2, 2)


def _draw_prev(p, s, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(s * 0.22, s * 0.26, s * 0.07, s * 0.48))
    tri = QPainterPath()
    tri.moveTo(s * 0.76, s * 0.22)
    tri.lineTo(s * 0.36, s * 0.5)
    tri.lineTo(s * 0.76, s * 0.78)
    tri.closeSubpath()
    p.drawPath(tri)


def _draw_play(p, s, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    tri = QPainterPath()
    tri.moveTo(s * 0.28, s * 0.18)
    tri.lineTo(s * 0.78, s * 0.5)
    tri.lineTo(s * 0.28, s * 0.82)
    tri.closeSubpath()
    p.drawPath(tri)


def _draw_pause(p, s, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    w = s * 0.14
    p.drawRoundedRect(QRectF(s * 0.24, s * 0.2, w, s * 0.6), 2, 2)
    p.drawRoundedRect(QRectF(s * 0.62, s * 0.2, w, s * 0.6), 2, 2)


def _draw_next(p, s, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    tri = QPainterPath()
    tri.moveTo(s * 0.24, s * 0.22)
    tri.lineTo(s * 0.64, s * 0.5)
    tri.lineTo(s * 0.24, s * 0.78)
    tri.closeSubpath()
    p.drawPath(tri)
    p.drawRect(QRectF(s * 0.71, s * 0.26, s * 0.07, s * 0.48))


def _draw_speaker(p, s, c):
    p.setPen(QPen(c, 1.2))
    p.setBrush(c)
    body = QPainterPath()
    body.moveTo(s * 0.12, s * 0.42)
    body.lineTo(s * 0.28, s * 0.42)
    body.lineTo(s * 0.48, s * 0.22)
    body.lineTo(s * 0.48, s * 0.78)
    body.lineTo(s * 0.28, s * 0.58)
    body.lineTo(s * 0.12, s * 0.58)
    body.closeSubpath()
    p.drawPath(body)
    p.setBrush(Qt.BrushStyle.NoBrush)
    wave1 = QPainterPath()
    wave1.moveTo(s * 0.58, s * 0.35)
    wave1.quadTo(s * 0.70, s * 0.5, s * 0.58, s * 0.65)
    p.drawPath(wave1)
    wave2 = QPainterPath()
    wave2.moveTo(s * 0.66, s * 0.26)
    wave2.quadTo(s * 0.84, s * 0.5, s * 0.66, s * 0.74)
    p.drawPath(wave2)


def _draw_speaker_muted(p, s, c):
    p.setPen(QPen(c, 1.2))
    p.setBrush(c)
    body = QPainterPath()
    body.moveTo(s * 0.12, s * 0.42)
    body.lineTo(s * 0.28, s * 0.42)
    body.lineTo(s * 0.48, s * 0.22)
    body.lineTo(s * 0.48, s * 0.78)
    body.lineTo(s * 0.28, s * 0.58)
    body.lineTo(s * 0.12, s * 0.58)
    body.closeSubpath()
    p.drawPath(body)
    p.setPen(QPen(QColor('#ff4444'), 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(s * 0.58, s * 0.32), QPointF(s * 0.82, s * 0.68))
    p.drawLine(QPointF(s * 0.58, s * 0.68), QPointF(s * 0.82, s * 0.32))


def _draw_expand(p, s, c):
    pen = QPen(c, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    m, L = s * 0.22, s * 0.2
    for x1, y1, dx, dy in [
        (m, m, L, 0), (m, m, 0, L),
        (s - m, m, -L, 0), (s - m, m, 0, L),
        (m, s - m, L, 0), (m, s - m, 0, -L),
        (s - m, s - m, -L, 0), (s - m, s - m, 0, -L),
    ]:
        p.drawLine(QPointF(x1, y1), QPointF(x1 + dx, y1 + dy))


def _draw_pin(p, s, c):
    p.save()
    p.translate(s * 0.5, s * 0.5)
    p.rotate(-25)
    p.setPen(QPen(c, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(c)
    head = QPainterPath()
    head.moveTo(-s * 0.18, -s * 0.30)
    head.lineTo(s * 0.18, -s * 0.30)
    head.lineTo(s * 0.13, -s * 0.18)
    head.lineTo(s * 0.10, s * 0.05)
    head.lineTo(s * 0.23, s * 0.15)
    head.lineTo(-s * 0.23, s * 0.15)
    head.lineTo(-s * 0.10, s * 0.05)
    head.lineTo(-s * 0.13, -s * 0.18)
    head.closeSubpath()
    p.drawPath(head)
    p.drawLine(QPointF(0, s * 0.15), QPointF(0, s * 0.40))
    p.restore()


def _draw_hd(p, s, c):
    p.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(s * 0.12, s * 0.20, s * 0.76, s * 0.60), 3, 3)
    f = QFont('Arial', max(1, int(s * 0.30)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(s * 0.12, s * 0.20, s * 0.76, s * 0.60), Qt.AlignmentFlag.AlignCenter, "HD")


def _draw_repeat(p, s, c):
    pen = QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    m, t, b = s * 0.18, s * 0.3, s * 0.7
    p.drawLine(QPointF(m, t), QPointF(s - m, t))
    p.drawLine(QPointF(s - m, t), QPointF(s - m, b))
    p.drawLine(QPointF(s - m, b), QPointF(m, b))
    p.drawLine(QPointF(m, b), QPointF(m, t))
    a = s * 0.1
    p.drawLine(QPointF(s - m - a, t - a), QPointF(s - m, t))
    p.drawLine(QPointF(s - m - a, t + a), QPointF(s - m, t))
    p.drawLine(QPointF(m + a, b - a), QPointF(m, b))
    p.drawLine(QPointF(m + a, b + a), QPointF(m, b))


def _draw_repeat_one(p, s, c):
    _draw_repeat(p, s, c)
    p.setPen(QPen(c))
    f = QFont('Arial', max(1, int(s * 0.28)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, '1')


def _draw_shuffle(p, s, c):
    pen = QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    m = s * 0.2
    y_off = s * 0.06
    p.drawLine(QPointF(m, m + y_off), QPointF(s - m, s - m - y_off))
    p.drawLine(QPointF(m, s - m - y_off), QPointF(s - m, m + y_off))
    a = s * 0.1
    p.drawLine(QPointF(s - m - a, m + y_off), QPointF(s - m, m + y_off))
    p.drawLine(QPointF(s - m, m + y_off + a), QPointF(s - m, m + y_off))
    p.drawLine(QPointF(s - m, s - m - y_off), QPointF(s - m, s - m - y_off))
    p.drawLine(QPointF(s - m, s - m - y_off - a), QPointF(s - m, s - m - y_off))


def _draw_plus(p, s, c):
    pen = QPen(c, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    m = s * 0.28
    p.drawLine(QPointF(s / 2, m), QPointF(s / 2, s - m))
    p.drawLine(QPointF(m, s / 2), QPointF(s - m, s / 2))


def _draw_clear(p, s, c):
    pen = QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    m = s * 0.28
    p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
    p.drawLine(QPointF(s - m, m), QPointF(m, s - m))


def _draw_playlist_icon(p, s, c):
    p.setPen(QPen(c, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(s * 0.20, s * 0.28), QPointF(s * 0.80, s * 0.28))
    p.drawLine(QPointF(s * 0.20, s * 0.50), QPointF(s * 0.80, s * 0.50))
    p.drawLine(QPointF(s * 0.20, s * 0.72), QPointF(s * 0.60, s * 0.72))


def _draw_youtube_icon(p, s, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#ff0033'))
    p.drawRoundedRect(QRectF(s * 0.12, s * 0.22, s * 0.76, s * 0.56), 3, 3)
    p.setBrush(QColor('#ffffff'))
    tri = QPainterPath()
    tri.moveTo(s * 0.40, s * 0.35)
    tri.lineTo(s * 0.66, s * 0.50)
    tri.lineTo(s * 0.40, s * 0.65)
    tri.closeSubpath()
    p.drawPath(tri)


# ─── YtDlp Workers ────────────────────────────────────────────────────────

def _find_node_path() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    import os
    for candidate in [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.expanduser(r"~\AppData\Roaming\nvm\current\node.exe"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return None


class YtDlpWorker(QObject):
    item_extracted = pyqtSignal(str, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    limit_reached = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def extract(self, urls: list[str], max_items: int):
        self.cancel()
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        max_items = max(1, min(MAX_QUEUE_ITEMS, int(max_items)))

        def _run():
            emitted = 0
            try:
                ydl_opts = {
                    'format': 'best',
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': True,
                    'playlistend': max_items,
                    'socket_timeout': 15,
                }
                node_path = _find_node_path()
                if node_path:
                    ydl_opts['js_runtimes'] = {'node': {'path': node_path}}
                    ydl_opts['remote_components'] = {'ejs:github'}
                try:
                    local_appdata = os.environ.get("LOCALAPPDATA", "")
                    cfile = Path(local_appdata) / "ClockAlarm" / "cookies.txt"
                    if cfile.is_file() and cfile.stat().st_size > 0:
                        ydl_opts['cookiefile'] = str(cfile)
                except Exception:
                    pass
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    for url in urls:
                        if cancel_event.is_set() or emitted >= max_items:
                            break
                        url = url.strip()
                        if not url:
                            continue

                        if not url.startswith("http"):
                            self.item_extracted.emit(os.path.basename(url), url)
                            emitted += 1
                            continue

                        info = ydl.extract_info(url, download=False)
                        if 'entries' in info:
                            for entry in info['entries']:
                                if cancel_event.is_set() or emitted >= max_items:
                                    break
                                if entry:
                                    entry_url = entry.get('url') or entry.get('webpage_url')
                                    title = entry.get('title', 'Unknown Title')
                                    entry_url = str(entry_url or "")
                                    if entry_url and len(entry_url) <= MAX_URL_LENGTH:
                                        self.item_extracted.emit(
                                            str(title)[:MAX_TITLE_LENGTH],
                                            entry_url,
                                        )
                                        emitted += 1
                        else:
                            title = info.get('title', 'Unknown Title')
                            self.item_extracted.emit(
                                str(title)[:MAX_TITLE_LENGTH], url
                            )
                            emitted += 1
                if emitted >= max_items and not cancel_event.is_set():
                    self.limit_reached.emit(f"Limit: {max_items} items")
                if not cancel_event.is_set():
                    self.finished.emit()
            except Exception as e:
                if not cancel_event.is_set():
                    self.error.emit(str(e))
        threading.Thread(target=_run, daemon=True).start()


def normalize_cookie_content(raw_text: str) -> str:
    """
    Normalizes pasted cookies into standard Netscape format expected by yt-dlp.
    Supports Netscape format, Base64-encoded cookies (Cookie-Editor export),
    JSON format (EditThisCookie / Cookie-Editor), and raw HTTP Header 'Cookie: ...'.
    """
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return ""

    # Case 1: Already Netscape format
    if "# Netscape" in raw_text or ("\t" in raw_text and ("youtube.com" in raw_text or "google.com" in raw_text)):
        if not raw_text.startswith("# Netscape"):
            raw_text = "# Netscape HTTP Cookie File\n" + raw_text
        return raw_text if raw_text.endswith("\n") else raw_text + "\n"

    # Check for Base64 encoded payload (e.g. from Cookie-Editor / EditThisCookie export)
    candidates = [raw_text]
    clean_b64 = raw_text.replace("\r", "").replace("\n", "").strip()
    if not any(c in clean_b64 for c in ("\t", " ", "<", ">")):
        try:
            import base64
            pad = "=" * ((4 - len(clean_b64) % 4) % 4)
            decoded_candidate = base64.b64decode(clean_b64 + pad).decode("utf-8", errors="ignore")
            if any(k in decoded_candidate for k in ("domain", "name", "value", "LOGIN_INFO", "SID")):
                candidates.insert(0, decoded_candidate)
        except Exception:
            pass

    for text in candidates:
        text = text.strip()
        # Case 2: JSON (array, single object, or semicolon/newline separated objects)
        json_items = []
        try:
            import json
            parsed = json.loads(text)
            if isinstance(parsed, list):
                json_items = parsed
            elif isinstance(parsed, dict):
                json_items = [parsed]
        except Exception:
            for segment in text.replace("\n", ";").split(";"):
                segment = segment.strip()
                if segment.startswith("{") and segment.endswith("}"):
                    try:
                        import json
                        obj = json.loads(segment)
                        if isinstance(obj, dict) and ("name" in obj or "value" in obj):
                            json_items.append(obj)
                    except Exception:
                        pass

        if json_items:
            lines = ["# Netscape HTTP Cookie File", "# Converted by ClockAlarm"]
            for item in json_items:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    domain = item.get("domain") or ".youtube.com"
                    flag = "TRUE" if str(domain).startswith(".") else "FALSE"
                    path = item.get("path") or "/"
                    secure = "TRUE" if item.get("secure", True) else "FALSE"
                    try:
                        exp_val = int(float(item.get("expirationDate") or 2147483647))
                    except Exception:
                        exp_val = 2147483647
                    name = str(item.get("name")).strip()
                    val = str(item.get("value")).strip()
                    if name:
                        lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{exp_val}\t{name}\t{val}")
            if len(lines) > 2:
                return "\n".join(lines) + "\n"

        # Case 3: Raw HTTP header key=value; pairs
        h_text = text
        if h_text.lower().startswith("cookie:"):
            h_text = h_text[7:].strip()

        lines = ["# Netscape HTTP Cookie File", "# Converted from HTTP Header by ClockAlarm"]
        pairs = [p.strip() for p in h_text.replace("\r", "").replace("\n", "").split(";") if p.strip()]
        count = 0
        for p in pairs:
            if "=" in p:
                name, val = p.split("=", 1)
                name = name.strip()
                val = val.strip()
                if name:
                    count += 1
                    lines.append(f".youtube.com\tTRUE\t/\tTRUE\t2147483647\t{name}\t{val}")

        if count > 0:
            return "\n".join(lines) + "\n"

    return raw_text if raw_text.endswith("\n") else raw_text + "\n"


class YtDlpStreamWorker(QObject):
    media_ready = pyqtSignal(int, str, int)  # req_id, file_path, height
    media_status = pyqtSignal(int, str)
    error = pyqtSignal(int, str)

    def __init__(self, parent=None, state=None):
        super().__init__(parent)
        self.state = state if isinstance(state, dict) else {}
        self._cancel_event = threading.Event()
        self._prefetch_cancel = threading.Event()
        self._download_lock = threading.Lock()
        self._prefetch_lock = threading.Lock()
        self._completed = {}

    def cancel(self):
        self._cancel_event.set()
        self._prefetch_cancel.set()

    def _download(self, url, target_height, cache_dir, cancel_event):
        # Serialize all writers, including a foreground request for a prefetch.
        # A cancelled writer must release its files before another can resume.
        while not self._download_lock.acquire(timeout=0.1):
            if cancel_event.is_set():
                return None
        try:
            if cancel_event.is_set():
                return None
            root = Path(cache_dir)
            stem = "media-" + hashlib.sha256(f"{url}\0{target_height}".encode()).hexdigest()
            key = (str(root), stem)
            cached = self._completed.get(key)
            if cached and cached.is_file() and cached.stat().st_size > 0:
                return str(cached)
            root.mkdir(parents=True, exist_ok=True)

            formats = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4a', '.mp3', '.ogg', '.opus', '.wav', '.flac'}
            existing = [p for p in root.glob(f'{stem}.*')
                        if p.stem == stem and p.suffix.lower() in formats
                        and p.is_file() and p.stat().st_size > 0]
            if existing:
                playable = max(existing, key=lambda p: p.stat().st_mtime_ns)
                self._completed[key] = playable
                return str(playable)

            persistent_root = None
            try:
                persistent_root = _get_persistent_cache_dir()
                existing_pers = [p for p in persistent_root.glob(f'{stem}.*')
                                 if p.stem == stem and p.suffix.lower() in formats
                                 and p.is_file() and p.stat().st_size > 0]
                if existing_pers:
                    playable = max(existing_pers, key=lambda p: p.stat().st_mtime_ns)
                    try:
                        os.utime(playable, None)
                    except Exception:
                        pass
                    self._completed[key] = playable
                    return str(playable)
            except (NameError, Exception):
                persistent_root = None

            def progress(_status):
                if cancel_event.is_set():
                    raise yt_dlp.utils.DownloadCancelled()

            limit = target_height if target_height > 0 else 1080
            # Prefer fast progressive stream (no ffmpeg remux required), then fallback to split streams
            format_spec = (
                f'best[ext=mp4][height<={limit}]/'
                f'bestvideo[height<={limit}]+bestaudio/'
                f'best[height<={limit}]/best'
            )
            ydl_opts = {
                'extractor_args': {'youtube': {'player_client': ['ios', 'visionos', 'mweb', 'android', 'web']}},
                'format': format_spec,
                'quiet': True, 'no_warnings': True, 'noprogress': True,
                'socket_timeout': 10, 'noplaylist': True,
                'max_filesize': MAX_COMPAT_CACHE_BYTES,
                'outtmpl': str(root / f'{stem}.%(ext)s'),
                'nopart': False, 'progress_hooks': [progress],
                'concurrent_fragment_downloads': 4,
            }
            proxy = None
            try:
                from yt_feed_monitor import detect_local_proxy
                proxy = detect_local_proxy()
            except Exception:
                pass
            if proxy:
                ydl_opts['proxy'] = proxy

            cookie_file = None
            try:
                import os
                node_path = _find_node_path()
                if node_path:
                    ydl_opts['js_runtimes'] = {'node': {'path': node_path}}
                    ydl_opts['remote_components'] = {'ejs:github'}

                media_cfg = self.state.get("media", {}) if isinstance(self.state, dict) else {}
                raw_cookies = (media_cfg.get("cookies_text") or "").strip()
                loc_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "ClockAlarm"
                target_cookie = loc_dir / "cookies.txt"

                if not raw_cookies:
                    try:
                        state_p = loc_dir / "state.json"
                        if state_p.is_file():
                            import json
                            s_data = json.loads(state_p.read_text(encoding="utf-8"))
                            raw_cookies = (s_data.get("media", {}).get("cookies_text") or "").strip()
                    except Exception:
                        pass

                if raw_cookies:
                    normalized = normalize_cookie_content(raw_cookies)
                    if normalized.strip():
                        loc_dir.mkdir(parents=True, exist_ok=True)
                        target_cookie.write_text(normalized, encoding="utf-8")
                        cookie_file = target_cookie

                if not cookie_file:
                    for cc in [
                        target_cookie,
                        loc_dir / "youtube_cookies.txt",
                        root / "cookies.txt",
                        Path(os.path.dirname(__file__)) / "cookies.txt",
                        Path(os.path.dirname(__file__)) / "youtube_cookies.txt",
                    ]:
                        if cc.is_file() and cc.stat().st_size > 0:
                            cookie_file = cc
                            break
            except Exception:
                pass

            if cookie_file:
                ydl_opts['cookiefile'] = str(cookie_file)
                # When authenticated with user cookies and node solver, default/web extracts full quality & zero 429
                ydl_opts['extractor_args'] = {'youtube': {'player_client': ['web', 'default']}}
            else:
                ydl_opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'visionos', 'mweb', 'android', 'web']}}

            try:
                import imageio_ffmpeg
                ydl_opts['ffmpeg_location'] = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                pass
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)
            except Exception as exc:
                if cancel_event.is_set():
                    return None
                err_text = str(exc).lower()
                # If 429 or bot check still occurs, try fallback client chain
                if any(k in err_text for k in ("429", "too many requests", "not a bot", "sign in")):
                    try:
                        fallback_opts = dict(ydl_opts)
                        fallback_opts['extractor_args'] = {'youtube': {'player_client': ['mweb', 'web_safari', 'ios', 'web']}}
                        with yt_dlp.YoutubeDL(fallback_opts) as ydl_fb:
                            ydl_fb.extract_info(url, download=True)
                    except Exception:
                        raise exc
                else:
                    raise
            if cancel_event.is_set():
                return None
            # Never promote .part, metadata or unmerged .fNNN tracks to playback.
            files = [p for p in root.glob(f'{stem}.*')
                     if p.stem == stem and p.suffix.lower() in formats
                     and p.is_file() and p.stat().st_size > 0]
            if not files:
                raise RuntimeError("下载未生成完整的播放文件，请重试。")
            playable = max(files, key=lambda p: p.stat().st_mtime_ns)
            self._completed[key] = playable
            if persistent_root is not None:
                try:
                    dest = persistent_root / playable.name
                    if not dest.exists() and persistent_root.is_dir():
                        shutil.copy2(playable, dest)
                    media_cfg = self.state.get("media", {}) if isinstance(self.state, dict) else {}
                    limit_mb = int(media_cfg.get("cache_limit_mb") or 500)
                    limit_mb = max(50, min(10000, limit_mb))
                    prune_media_cache(persistent_root, max_bytes=limit_mb * 1024 * 1024)
                except Exception:
                    pass
            return str(playable)
        finally:
            self._download_lock.release()

    def retire_cache(self, cache_dir):
        """Retire only this window's private cache, after writers release files."""
        self.cancel()
        def cleanup():
            with self._download_lock:
                shutil.rmtree(cache_dir, ignore_errors=True)
                for key in list(self._completed):
                    if key[0] == str(Path(cache_dir)):
                        del self._completed[key]
        thread = threading.Thread(target=cleanup, daemon=True, name="MediaCacheCleanup")
        thread.start()
        return thread

    def load_media(self, req_id: int, url: str, target_height: int, cache_dir: str):
        self.cancel()
        cancel_event = threading.Event()
        self._cancel_event = cancel_event

        def _run():
            try:
                self.media_status.emit(req_id, "正在缓冲视频…")
                playable = self._download(url, target_height, cache_dir, cancel_event)
                if playable and not cancel_event.is_set():
                    self.media_ready.emit(req_id, playable, target_height)
            except Exception as e:
                if not cancel_event.is_set():
                    self.error.emit(req_id, str(e))
        thread = threading.Thread(target=_run, daemon=True, name="MediaDownload")
        thread.start()
        return thread

    def prefetch(self, url: str, target_height: int, cache_dir: str):
        # LoadedMedia and BufferedMedia may arrive back-to-back.
        if not self._prefetch_lock.acquire(blocking=False):
            return None
        cancel_event = threading.Event()
        self._prefetch_cancel = cancel_event
        def _run():
            try:
                self._download(url, target_height, cache_dir, cancel_event)
            except Exception:
                pass
            finally:
                self._prefetch_lock.release()
        thread = threading.Thread(target=_run, daemon=True, name="MediaPrefetch")
        thread.start()
        return thread


# ─── YouTube Subscriptions Dialog ──────────────────────────────────────────

class YouTubeSubscriptionsDialog(QDialog):
    def __init__(self, parent=None, *, state=None, save_state=None, feed_monitor=None):
        super().__init__(parent)
        self.state = state if isinstance(state, dict) else {}
        self.save_state = save_state
        self.feed_monitor = feed_monitor
        self.setWindowTitle(f"Clock/Alarm v{get_app_version()} - YouTube 频道关注与订阅")
        self.resize(560, 540)
        self.setMinimumSize(480, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }
            QLabel {
                color: #cbd5e1;
            }
            QLineEdit {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 7px 10px;
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
            }
            QPushButton {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 12px;
                color: #f8fafc;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #334155;
            }
            QPushButton#primary {
                background: #0284c7;
                border: 1px solid #0284c7;
                color: #ffffff;
            }
            QPushButton#primary:hover {
                background: #0369a1;
            }
            QCheckBox {
                color: #e2e8f0;
                font-size: 12px;
                spacing: 6px;
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
            QComboBox {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 8px;
                color: #f8fafc;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QScrollArea {
                border: 1px solid #334155;
                background: #0b0f17;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        title_lbl = QLabel("YouTube 频道关注与更新追踪")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        hdr.addWidget(title_lbl)
        hdr.addWidget(make_version_badge(self))
        hdr.addStretch()
        layout.addLayout(hdr)

        desc_lbl = QLabel("特别关注的频道一旦有新视频发布，将第一时间自动收录进播放列表，并发送桌面通知。无需 API Key，零配额消耗。")
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        layout.addWidget(desc_lbl)

        # Input Row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入或批量粘贴频道链接/@Handle（支持同时添加多个，换行/逗号/空格分隔）")
        self.input_field.returnPressed.connect(self._add_channel)
        input_row.addWidget(self.input_field, stretch=1)

        self.add_btn = QPushButton("添加关注")
        self.add_btn.setObjectName("primary")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._add_channel)
        input_row.addWidget(self.add_btn)
        layout.addLayout(input_row)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #38bdf8; font-size: 11px;")
        layout.addWidget(self.status_lbl)

        # Channel Cards Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.scroll_content)
        self.cards_layout.setContentsMargins(8, 8, 8, 8)
        self.cards_layout.setSpacing(8)
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll, stretch=1)

        # Settings Options
        media_cfg = self.state.setdefault("media", {})
        opts_box = QVBoxLayout()
        opts_box.setSpacing(6)

        opts_row = QHBoxLayout()
        self.auto_add_cb = QCheckBox("发现新视频自动加入播放列表")
        self.auto_add_cb.setChecked(bool(media_cfg.get("auto_add_to_playlist", True)))
        self.auto_add_cb.toggled.connect(self._on_auto_add_toggled)
        opts_row.addWidget(self.auto_add_cb)

        self.notify_cb = QCheckBox("发现新视频发送桌面气泡通知")
        self.notify_cb.setChecked(bool(media_cfg.get("notify_on_new_video", True)))
        self.notify_cb.toggled.connect(self._on_notify_toggled)
        opts_row.addWidget(self.notify_cb)
        opts_box.addLayout(opts_row)
        layout.addLayout(opts_box)

        # Bottom row: Check interval + Check Now button + Close
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        interval_lbl = QLabel("检查频率:")
        interval_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        bottom_row.addWidget(interval_lbl)

        self.interval_combo = QComboBox()
        self.interval_combo.addItem("每 15 分钟", 15)
        self.interval_combo.addItem("每 30 分钟 (推荐)", 30)
        self.interval_combo.addItem("每 1 小时", 60)
        self.interval_combo.addItem("每 2 小时", 120)
        self.interval_combo.addItem("每 4 小时", 240)

        current_mins = int(media_cfg.get("subscription_check_mins", 30))
        for i in range(self.interval_combo.count()):
            if self.interval_combo.itemData(i) == current_mins:
                self.interval_combo.setCurrentIndex(i)
                break
        self.interval_combo.currentIndexChanged.connect(self._on_interval_changed)
        bottom_row.addWidget(self.interval_combo)

        bottom_row.addStretch()

        self.check_now_btn = QPushButton("🔄 立即检查更新")
        self.check_now_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_now_btn.clicked.connect(self._check_now)
        bottom_row.addWidget(self.check_now_btn)

        self.close_btn = QPushButton("关闭")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(self.close_btn)

        layout.addLayout(bottom_row)

        self._populate_channels()

    def _populate_channels(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        media_cfg = self.state.setdefault("media", {})
        subs = media_cfg.get("subscriptions", [])

        if not subs:
            empty_lbl = QLabel("暂未关注任何 YouTube 频道\n在上方输入频道链接或 @Handle 开始关注（支持批量多频道）")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #64748b; font-size: 13px; padding: 40px;")
            self.cards_layout.addWidget(empty_lbl)
            self.cards_layout.addStretch()
            return

        for sub in subs:
            status = sub.get("status", "active")
            card = QFrame()
            card.setObjectName("channelCard")
            if status == "resolving":
                border_style = "border: 1px solid #0284c7; background-color: #0f233a;"
            elif status == "error":
                border_style = "border: 1px solid rgba(239,68,68,0.5); background-color: #26171a;"
            else:
                border_style = "border: 1px solid #334155; background-color: #1e293b;"

            card.setStyleSheet(f"""
                #channelCard {{
                    {border_style}
                    border-radius: 8px;
                    padding: 4px;
                }}
                QLabel {{
                    border: none;
                    background: transparent;
                }}
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(10)

            # Left badge / icon
            yt_icon_lbl = QLabel()
            yt_icon_lbl.setPixmap(_make_icon(_draw_youtube_icon, 24).pixmap(24, 24))
            card_layout.addWidget(yt_icon_lbl)

            # Info vbox
            info_box = QVBoxLayout()
            info_box.setSpacing(2)

            title_str = sub.get("title") or sub.get("channel_id") or "Unknown Channel"
            c_title = QLabel(str(title_str))
            c_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #f8fafc;")
            info_box.addWidget(c_title)

            handle_str = sub.get("handle") or sub.get("raw_input") or sub.get("channel_id") or ""
            c_sub = QLabel(str(handle_str))
            c_sub.setStyleSheet("font-size: 11px; color: #94a3b8;")
            info_box.addWidget(c_sub)

            # Status message or latest video
            if status == "resolving":
                c_status = QLabel(sub.get("status_msg") or "⏳ 正在后台极速解析...")
                c_status.setStyleSheet("font-size: 11px; color: #38bdf8; font-weight: 500;")
                info_box.addWidget(c_status)
            elif status == "error":
                c_err = QLabel(sub.get("status_msg") or "⚠️ 解析失败 (点击重试)")
                c_err.setStyleSheet("font-size: 11px; color: #f87171;")
                info_box.addWidget(c_err)
            elif sub.get("last_checked_title"):
                latest_text = f"最新: {sub['last_checked_title']}"
                if len(latest_text) > 42:
                    latest_text = latest_text[:40] + "…"
                c_latest = QLabel(latest_text)
                c_latest.setStyleSheet("font-size: 11px; color: #38bdf8;")
                info_box.addWidget(c_latest)

            card_layout.addLayout(info_box, stretch=1)

            chid = sub.get("channel_id")
            temp_id = sub.get("temp_id") or chid

            if status == "resolving":
                # Cancel button while resolving
                cancel_btn = QPushButton("取消")
                cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                cancel_btn.setStyleSheet("background: #334155; color: #94a3b8; border: 1px solid #475569; font-size: 11px; padding: 4px 8px;")
                cancel_btn.clicked.connect(lambda *args, tid=temp_id: self._delete_channel(tid))
                card_layout.addWidget(cancel_btn)
            elif status == "error":
                # Retry button
                retry_btn = QPushButton("🔄 重试")
                retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                retry_btn.setStyleSheet("background: #0369a1; color: #ffffff; border: 1px solid #38bdf8; font-size: 11px; padding: 4px 8px;")
                retry_btn.clicked.connect(lambda *args, tid=temp_id: self._retry_channel(tid))
                card_layout.addWidget(retry_btn)

                # Delete button
                del_btn = QPushButton("删除")
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.setStyleSheet("background: rgba(239,68,68,0.15); color: #fca5a5; border: 1px solid rgba(239,68,68,0.4); font-size: 11px; padding: 4px 8px;")
                del_btn.clicked.connect(lambda *args, tid=temp_id: self._delete_channel(tid))
                card_layout.addWidget(del_btn)
            else:
                # Active Status / Toggle
                enabled = sub.get("enabled", True)
                toggle_btn = QPushButton("已启用" if enabled else "已停用")
                toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                if enabled:
                    toggle_btn.setStyleSheet("background: #064e3b; color: #34d399; border: 1px solid #059669; font-size: 11px; padding: 4px 8px;")
                else:
                    toggle_btn.setStyleSheet("background: #334155; color: #94a3b8; border: 1px solid #475569; font-size: 11px; padding: 4px 8px;")
                toggle_btn.clicked.connect(lambda *args, cid=chid, en=enabled: self._toggle_channel(cid, not en))
                card_layout.addWidget(toggle_btn)

                # Delete
                del_btn = QPushButton("取消关注")
                del_btn.setObjectName("danger")
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.setStyleSheet("background: rgba(239,68,68,0.15); color: #fca5a5; border: 1px solid rgba(239,68,68,0.4); font-size: 11px; padding: 4px 8px;")
                del_btn.clicked.connect(lambda *args, cid=chid: self._delete_channel(cid))
                card_layout.addWidget(del_btn)

            self.cards_layout.addWidget(card)

        self.cards_layout.addStretch()

    def _add_channel(self):
        text = self.input_field.text().strip()
        if not text:
            return

        # Batch parsing: split by newlines, commas, semicolons, or whitespace
        raw_tokens = [t.strip() for t in re.split(r'[\r\n,;\s]+', text) if t.strip()]
        if not raw_tokens:
            return

        # 0-Wait Optimistic Addition: Clear input box immediately, keep button active!
        self.input_field.clear()
        self.add_btn.setEnabled(True)

        media_cfg = self.state.setdefault("media", {})
        subs = media_cfg.setdefault("subscriptions", [])

        # Track existing entries for deduplication
        existing_keys = set()
        for s in subs:
            if s.get("channel_id"):
                existing_keys.add(s["channel_id"].lower())
            if s.get("handle"):
                existing_keys.add(s["handle"].lower())
            if s.get("raw_input"):
                existing_keys.add(s["raw_input"].lower())

        added_items = []
        for raw in raw_tokens:
            # Check if pure channel ID
            direct_chid = ""
            m_uc = re.search(r"UC[a-zA-Z0-9_-]{22}", raw)
            if m_uc:
                direct_chid = m_uc.group(0)

            # Handle
            handle_m = re.search(r"@([a-zA-Z0-9_.-]+)", raw)
            handle_val = f"@{handle_m.group(1)}" if handle_m else ""

            # Check duplicate
            if (direct_chid and direct_chid.lower() in existing_keys) or \
               (handle_val and handle_val.lower() in existing_keys) or \
               (raw.lower() in existing_keys):
                continue

            temp_id = f"pending_{uuid.uuid4().hex[:8]}"
            real_id = direct_chid or temp_id
            title_display = handle_val or (f"频道 {direct_chid[:10]}…" if direct_chid else raw)

            sub_item = {
                "channel_id": real_id,
                "temp_id": temp_id,
                "raw_input": raw,
                "title": title_display,
                "handle": handle_val,
                "url": f"https://www.youtube.com/channel/{real_id}" if direct_chid else (raw if raw.startswith("http") else f"https://www.youtube.com/{raw}"),
                "enabled": True,
                "status": "resolving",
                "status_msg": "⏳ 正在后台极速解析...",
                "initial_baseline_done": True,
            }
            subs.append(sub_item)
            existing_keys.add(real_id.lower())
            if handle_val:
                existing_keys.add(handle_val.lower())
            existing_keys.add(raw.lower())
            added_items.append(sub_item)

        if not added_items:
            self.status_lbl.setText("所输入的频道均已在关注列表中，无需重复添加。")
            return

        if self.save_state:
            self.save_state()

        # Instant 0-Wait UI update: show all newly created cards in 0.01 seconds
        self._populate_channels()
        self.status_lbl.setText(f"✓ 已入库 {len(added_items)} 个频道，正在后台极速并发解析...")

        # Fire concurrent background resolution workers
        for item in added_items:
            self._start_channel_resolution(item)

    def _start_channel_resolution(self, sub_item: dict):
        temp_id = sub_item.get("temp_id") or sub_item.get("channel_id")
        raw_input = sub_item.get("raw_input") or sub_item.get("handle") or sub_item.get("channel_id")

        def _worker():
            try:
                res = resolve_channel_id(raw_input, timeout=10)
                if not res:
                    QTimer.singleShot(0, lambda: self._on_resolution_failed(temp_id, "未能识别该频道，请确认链接或 @Handle 是否准确。"))
                    return

                # Add to feed monitor for seen IDs if active
                if self.feed_monitor:
                    self.feed_monitor.add_subscription(res)

                QTimer.singleShot(0, lambda r=res: self._on_resolution_succeeded(temp_id, r))
            except Exception as e:
                QTimer.singleShot(0, lambda err=str(e): self._on_resolution_failed(temp_id, f"解析出错: {err}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_resolution_succeeded(self, temp_id: str, res: dict):
        media_cfg = self.state.setdefault("media", {})
        subs = media_cfg.setdefault("subscriptions", [])
        target = None
        for s in subs:
            if s.get("temp_id") == temp_id or s.get("channel_id") == temp_id:
                target = s
                break

        if target:
            target["channel_id"] = res.get("channel_id") or target.get("channel_id")
            target["title"] = res.get("title") or target.get("title")
            target["handle"] = res.get("handle") or target.get("handle")
            target["url"] = res.get("url") or target.get("url")
            target["rss_url"] = res.get("rss_url") or target.get("rss_url")
            target["status"] = "active"
            target["status_msg"] = ""
            target["initial_baseline_done"] = True
            if res.get("entries"):
                target["last_checked_title"] = res["entries"][0]["title"]
                target["last_checked_time"] = res["entries"][0].get("published", "")
            if self.save_state:
                self.save_state()

        self.status_lbl.setText(f"✓ 已成功解析并监控: {res.get('title')}")
        self._populate_channels()

    def _on_resolution_failed(self, temp_id: str, msg: str):
        media_cfg = self.state.setdefault("media", {})
        subs = media_cfg.setdefault("subscriptions", [])
        for s in subs:
            if s.get("temp_id") == temp_id or s.get("channel_id") == temp_id:
                s["status"] = "error"
                s["status_msg"] = msg
                break
        if self.save_state:
            self.save_state()
        self.status_lbl.setText(f"⚠️ {msg}")
        self._populate_channels()

    def _retry_channel(self, target_id: str):
        media_cfg = self.state.setdefault("media", {})
        subs = media_cfg.setdefault("subscriptions", [])
        for s in subs:
            if s.get("temp_id") == target_id or s.get("channel_id") == target_id:
                s["status"] = "resolving"
                s["status_msg"] = "⏳ 正在重试解析..."
                if self.save_state:
                    self.save_state()
                self._populate_channels()
                self._start_channel_resolution(s)
                break

    def _toggle_channel(self, chid: str, new_state: bool):
        if self.feed_monitor:
            self.feed_monitor.toggle_subscription(chid, new_state)
        else:
            media_cfg = self.state.setdefault("media", {})
            for s in media_cfg.get("subscriptions", []):
                if s.get("channel_id") == chid or s.get("temp_id") == chid:
                    s["enabled"] = new_state
                    break
            if self.save_state:
                self.save_state()
        self._populate_channels()

    def _delete_channel(self, chid: str):
        if self.feed_monitor:
            self.feed_monitor.remove_subscription(chid)
        media_cfg = self.state.setdefault("media", {})
        subs = media_cfg.get("subscriptions", [])
        media_cfg["subscriptions"] = [
            s for s in subs
            if s.get("channel_id") != chid and s.get("temp_id") != chid
        ]
        if self.save_state:
            self.save_state()
        self.status_lbl.setText("已移除该频道")
        self._populate_channels()

    def _on_auto_add_toggled(self, checked: bool):
        self.state.setdefault("media", {})["auto_add_to_playlist"] = checked
        if self.save_state:
            self.save_state()

    def _on_notify_toggled(self, checked: bool):
        self.state.setdefault("media", {})["notify_on_new_video"] = checked
        if self.save_state:
            self.save_state()

    def _on_interval_changed(self):
        mins = self.interval_combo.currentData()
        if mins and self.feed_monitor:
            self.feed_monitor.update_check_interval(mins)
        elif mins:
            self.state.setdefault("media", {})["subscription_check_mins"] = mins
            if self.save_state:
                self.save_state()

    def _check_now(self):
        self.check_now_btn.setEnabled(False)
        self.status_lbl.setText("正在后台检索频道更新...")

        def _on_done(count):
            def _ui():
                self.check_now_btn.setEnabled(True)
                if count > 0:
                    self.status_lbl.setText(f"检查完成！共发现 {count} 个新上传视频")
                else:
                    self.status_lbl.setText("检查完成，关注的频道暂无新视频。")
                self._populate_channels()
            QTimer.singleShot(0, _ui)

        if self.feed_monitor:
            self.feed_monitor.check_now_async(on_finish=_on_done)
        else:
            QTimer.singleShot(500, lambda: _on_done(0))


# ─── Media Player Window ──────────────────────────────────────────────────

class MediaPlayerWindow(QWidget):
    def __init__(self, parent=None, *, state=None, save_state=None, feed_monitor=None):
        super().__init__(parent)
        self.state = state if isinstance(state, dict) else {}
        self.save_state = save_state
        self.feed_monitor = feed_monitor
        from skin import get_app_version, make_version_badge
        self.setWindowTitle(f"Clock/Alarm v{get_app_version()} - 视频播放器")
        self.resize(1040, 700)
        self.setMinimumSize(540, 360)

        self._vlc_ready = True
        self._current_request_id = 0
        self._is_changing_media = False
        self._online_source_url = ""
        self._media_retry_pending = False
        self._media_cache_dir = tempfile.mkdtemp(prefix="ClockAlarm-media-")
        self._selected_quality_height = 0  # 0 means Auto / 1080p
        self._pending_seek_pos = 0

        self.setStyleSheet("""
            QWidget { background-color: #0b0f17; color: #f1f5f9; font-family: 'Segoe UI', system-ui, sans-serif; }
            QPlainTextEdit {
                background: #111827; border: 1px solid #1f2937;
                border-radius: 8px; padding: 8px; color: #fff; font-size: 13px;
            }
            QPlainTextEdit:focus { border: 1px solid #0284c7; }
            QPushButton {
                background: transparent; color: #cbd5e1; border: none;
                font-weight: bold; border-radius: 6px; padding: 4px 6px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.12); color: #ffffff; }
            QPushButton:disabled { opacity: 0.35; }
            QPushButton#primary { background: #0284c7; color: #fff; border-radius: 6px; }
            QPushButton#primary:hover { background: #0369a1; }
            QSlider::groove:horizontal {
                border: none; height: 6px;
                background: rgba(255,255,255,0.18); border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #38bdf8; width: 14px; height: 14px;
                margin: -4px 0; border-radius: 7px;
            }
            QSlider::sub-page:horizontal { background: #0284c7; border-radius: 3px; }

            /* Modern Ultra-Clean Scrollbar */
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.22);
                min-height: 24px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(56, 189, 248, 0.7);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none; background: none; height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                height: 0px; border: none;
            }

            /* Playlist View */
            QListWidget {
                background: #0f172a; border: none; outline: none; padding: 4px;
            }
            QListWidget::item {
                padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.04);
                color: #94a3b8; border-radius: 8px; margin: 2px 2px;
                font-size: 13px;
            }
            QListWidget::item:hover {
                background: #1e293b; color: #f8fafc;
            }
            QListWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #0c4a6e);
                color: #ffffff; font-weight: bold; border-left: 3px solid #38bdf8;
            }
        """)

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # ── Left: Video + Controls Container ──
        self.player_widget = QWidget(self)
        self.player_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.player_layout = QVBoxLayout(self.player_widget)
        self.player_layout.setContentsMargins(14, 14, 10, 14)
        self.player_layout.setSpacing(10)

        # Video Frame
        self.video_frame = QVideoWidget(self.player_widget)
        self.video_frame.setStyleSheet("background: #000000; border-radius: 10px;")
        self.video_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.player_layout.addWidget(self.video_frame, stretch=1)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_frame)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.errorOccurred.connect(self._on_media_error)

        # 🎧 Audio endpoint hot-plug / device change listener
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)

        # ── Bottom Controls Bar (Crystal Clear, Fully Visible) ──
        self.controls_widget = QWidget(self.player_widget)
        self.controls_widget.setStyleSheet("""
            QWidget {
                background: #111827; border-radius: 10px; padding: 4px;
            }
        """)
        controls_vbox = QVBoxLayout(self.controls_widget)
        controls_vbox.setContentsMargins(14, 8, 14, 10)
        controls_vbox.setSpacing(6)

        # Progress slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setTracking(True)
        self.slider.sliderMoved.connect(self.set_position)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.setMinimumHeight(18)
        controls_vbox.addWidget(self.slider)
        self._slider_dragging = False

        # Controls row
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self._play_icon = _make_icon(_draw_play, 26, '#ffffff')
        self._pause_icon = _make_icon(_draw_pause, 26, '#ffffff')
        self._speaker_icon = _make_icon(_draw_speaker, 20, '#cbd5e1')
        self._muted_icon = _make_icon(_draw_speaker_muted, 20, '#cbd5e1')
        self._hd_icon = _make_icon(_draw_hd, 20, '#38bdf8')
        self._playlist_icon = _make_icon(_draw_playlist_icon, 20, '#cbd5e1')

        self.prev_btn = QPushButton()
        self.prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prev_btn.setIcon(_make_icon(_draw_prev, 22, '#cbd5e1'))
        self.prev_btn.setIconSize(QSize(22, 22))
        self.prev_btn.setFixedSize(36, 36)
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.setToolTip("上一曲")
        self.prev_btn.clicked.connect(lambda *a: self.play_prev())

        self.play_btn = QPushButton()
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_btn.setIcon(self._play_icon)
        self.play_btn.setIconSize(QSize(26, 26))
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setToolTip("播放 / 暂停 (快捷键: 空格)")
        self.play_btn.clicked.connect(lambda *a: self.toggle_play())

        self.next_btn = QPushButton()
        self.next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_btn.setIcon(_make_icon(_draw_next, 22, '#cbd5e1'))
        self.next_btn.setIconSize(QSize(22, 22))
        self.next_btn.setFixedSize(36, 36)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setToolTip("下一曲")
        self.next_btn.clicked.connect(lambda *a: self.play_next())

        self.vol_btn = QPushButton()
        self.vol_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vol_btn.setIcon(self._speaker_icon)
        self.vol_btn.setIconSize(QSize(20, 20))
        self.vol_btn.setFixedSize(30, 30)
        self.vol_btn.setToolTip("音量 (右键选择输出设备)")
        self.vol_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.vol_btn.customContextMenuRequested.connect(self._show_audio_devices_menu)

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(100)
        self.vol_slider.setMinimumWidth(40)
        self.vol_slider.setMaximumWidth(88)
        self.vol_slider.setTracking(True)
        self.vol_slider.setMinimumHeight(16)
        self.vol_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vol_slider.valueChanged.connect(self.set_volume)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet(
            "color: #94a3b8; font-family: 'Consolas', monospace; font-size: 12px; margin-left: 6px;"
        )

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #38bdf8; font-size: 11px; margin-left: 10px;")

        # Custom HD quality button
        self.quality_btn = QPushButton()
        self.quality_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.quality_btn.setIcon(self._hd_icon)
        self.quality_btn.setIconSize(QSize(22, 22))
        self.quality_btn.setFixedSize(34, 34)
        self.quality_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quality_btn.setToolTip("画质选择 (1080p/720p/480p/360p)")
        self.quality_btn.clicked.connect(self._show_quality_menu)

        # Toggle playlist button (Manual Collapse / Expand)
        self.toggle_playlist_btn = QPushButton()
        self.toggle_playlist_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle_playlist_btn.setIcon(self._playlist_icon)
        self.toggle_playlist_btn.setIconSize(QSize(22, 22))
        self.toggle_playlist_btn.setFixedSize(34, 34)
        self.toggle_playlist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_playlist_btn.setToolTip("折叠 / 展开播放列表")
        self.toggle_playlist_btn.clicked.connect(self.toggle_playlist_panel)

        self.always_on_top_btn = QPushButton()
        self.always_on_top_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.always_on_top_btn.setCheckable(True)
        self.always_on_top_btn.setChecked(False)
        self.always_on_top_btn.setIcon(_make_dual_icon(_draw_pin, 18))
        self.always_on_top_btn.setIconSize(QSize(18, 18))
        self.always_on_top_btn.setFixedSize(32, 32)
        self.always_on_top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.always_on_top_btn.setToolTip("置顶窗口")
        self.always_on_top_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1px solid transparent; border-radius: 6px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.1); }
            QPushButton:checked { background: #0c4a6e; border-color: #38bdf8; }
        """)
        self.always_on_top_btn.clicked.connect(
            lambda checked=False: self.set_always_on_top(bool(checked))
        )
        self._always_on_top = False

        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fullscreen_btn.setIcon(_make_icon(_draw_expand, 18, '#cbd5e1'))
        self.fullscreen_btn.setIconSize(QSize(18, 18))
        self.fullscreen_btn.setFixedSize(32, 32)
        self.fullscreen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fullscreen_btn.setToolTip("全屏 (快捷键: Esc 退出)")
        self.fullscreen_btn.clicked.connect(lambda *a: self.toggle_fullscreen())

        controls.addWidget(self.prev_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.next_btn)
        controls.addSpacing(10)
        controls.addWidget(self.vol_btn)
        controls.addWidget(self.vol_slider)
        controls.addWidget(self.time_label)
        controls.addWidget(self.status_label)
        controls.addStretch()
        controls.addWidget(self.quality_btn)
        controls.addWidget(self.toggle_playlist_btn)
        controls.addWidget(self.always_on_top_btn)
        controls.addWidget(self.fullscreen_btn)

        controls_vbox.addLayout(controls)
        self.player_layout.addWidget(self.controls_widget)

        # ── Right: Modern Clean Collapsible Queue Panel ──
        self.queue_widget = QWidget(self)
        self.queue_widget.setMinimumWidth(260)
        self.queue_widget.setMaximumWidth(320)
        self.queue_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        qlayout = QVBoxLayout(self.queue_widget)
        qlayout.setContentsMargins(10, 14, 14, 14)
        qlayout.setSpacing(10)

        # Top row: playlist header, collapse button & open file
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        list_title = QLabel("播放列表")
        list_title.setStyleSheet("font-weight: 700; font-size: 14px; color: #f8fafc;")
        top_row.addWidget(list_title)
        top_row.addWidget(make_version_badge(self))
        top_row.addStretch()

        self.subs_btn = QPushButton()
        self.subs_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.subs_btn.setIcon(_make_icon(_draw_youtube_icon, 18))
        self.subs_btn.setIconSize(QSize(18, 18))
        self.subs_btn.setFixedSize(32, 32)
        self.subs_btn.setStyleSheet(
            "background: #1e293b; border: 1px solid #334155; border-radius: 6px;"
        )
        self.subs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subs_btn.setToolTip("YouTube 频道关注与订阅追踪")
        self.subs_btn.clicked.connect(self._open_subscriptions_dialog)
        top_row.addWidget(self.subs_btn)

        self.open_file_btn = QPushButton()
        self.open_file_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_file_btn.setIcon(_make_icon(_draw_folder, 18))
        self.open_file_btn.setIconSize(QSize(18, 18))
        self.open_file_btn.setFixedSize(32, 32)
        self.open_file_btn.setStyleSheet(
            "background: #1e293b; border: 1px solid #334155; border-radius: 6px;"
        )
        self.open_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_file_btn.setToolTip("打开本地音视频文件")
        self.open_file_btn.clicked.connect(lambda *a: self.open_file())
        top_row.addWidget(self.open_file_btn)
        qlayout.addLayout(top_row)

        # Segmented Tabs: 📋 播放列表 vs ⭐ 我的最爱
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(4)

        tab_btn_style = """
            QPushButton {
                background: #1e293b; color: #94a3b8; border: 1px solid #334155;
                border-radius: 6px; padding: 5px 6px; font-weight: 600; font-size: 11px;
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff; border-color: #38bdf8;
            }
            QPushButton:hover:!checked {
                background: #334155; color: #f1f5f9;
            }
        """
        self.tab_playlist_btn = QPushButton("📋 播放列表")
        self.tab_playlist_btn.setCheckable(True)
        self.tab_playlist_btn.setChecked(True)
        self.tab_playlist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab_playlist_btn.setStyleSheet(tab_btn_style)
        self.tab_playlist_btn.clicked.connect(lambda: self._set_active_tab("playlist"))
        tabs_row.addWidget(self.tab_playlist_btn, stretch=1)

        self.tab_favorites_btn = QPushButton("⭐ 我的最爱 (0)")
        self.tab_favorites_btn.setCheckable(True)
        self.tab_favorites_btn.setChecked(False)
        self.tab_favorites_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab_favorites_btn.setStyleSheet(tab_btn_style)
        self.tab_favorites_btn.clicked.connect(lambda: self._set_active_tab("favorites"))
        tabs_row.addWidget(self.tab_favorites_btn, stretch=1)

        qlayout.addLayout(tabs_row)

        # Playback Mode Buttons (Unified across all lists)
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(6)

        self.seq_play_btn = QPushButton()
        self.seq_play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.seq_play_btn.setIcon(_make_dual_icon(_draw_repeat, 18))
        self.seq_play_btn.setIconSize(QSize(18, 18))
        self.seq_play_btn.setToolTip("顺序播放 (对双列表均生效)")

        self.single_loop_btn = QPushButton()
        self.single_loop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.single_loop_btn.setIcon(_make_dual_icon(_draw_repeat_one, 18))
        self.single_loop_btn.setIconSize(QSize(18, 18))
        self.single_loop_btn.setToolTip("单曲循环 (对双列表均生效)")

        self.random_play_btn = QPushButton()
        self.random_play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.random_play_btn.setIcon(_make_dual_icon(_draw_shuffle, 18))
        self.random_play_btn.setIconSize(QSize(18, 18))
        self.random_play_btn.setToolTip("随机播放 (对双列表均生效)")

        mode_btn_style = """
            QPushButton {
                background: #1e293b; border: 1px solid #334155; border-radius: 6px;
            }
            QPushButton:checked {
                background: #0284c7; border-color: #38bdf8;
            }
            QPushButton:hover { background: #334155; }
        """
        for btn in (self.seq_play_btn, self.single_loop_btn, self.random_play_btn):
            btn.setCheckable(True)
            btn.setFixedSize(32, 32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(mode_btn_style)
            mode_layout.addWidget(btn)

        mode_layout.addStretch()
        qlayout.addLayout(mode_layout)

        self.seq_play_btn.clicked.connect(lambda *a: self.set_play_mode("sequence"))
        self.single_loop_btn.clicked.connect(lambda *a: self.set_play_mode("single_loop"))
        self.random_play_btn.clicked.connect(lambda *a: self.set_play_mode("random"))

        # Default mode
        self.play_mode = self.state.setdefault("media", {}).setdefault(
            "play_mode", "sequence"
        )
        self.set_play_mode(self.play_mode)

        # Search Bar (Chinese Simp/Trad + English)
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索歌曲 / 视频 (中英简繁)...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background: #0f172a; border: 1px solid #334155; border-radius: 6px;
                padding: 5px 8px; color: #f8fafc; font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8; background: #131f37;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.installEventFilter(self)
        search_row.addWidget(self.search_input)
        qlayout.addLayout(search_row)

        # Queue list (Horizontal scroll disabled, text wrapped, custom star delegate)
        self.queue_list = PlayListWidget()
        self.queue_list.setItemDelegate(PlaylistItemDelegate(self.queue_list))
        self.queue_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.queue_list.setWordWrap(True)
        self.queue_list.itemDoubleClicked.connect(self._on_queue_double_click)
        self.queue_list.star_clicked.connect(self._on_star_clicked)
        self.queue_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.queue_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_list.customContextMenuRequested.connect(self._queue_context_menu)
        qlayout.addWidget(self.queue_list, stretch=1)

        # URL input
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText("粘贴链接 (每行一条)")
        self.url_input.setMaximumHeight(64)
        qlayout.addWidget(self.url_input)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.add_queue_btn = QPushButton()
        self.add_queue_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_queue_btn.setIcon(_make_icon(_draw_plus, 16, '#ffffff'))
        self.add_queue_btn.setIconSize(QSize(16, 16))
        self.add_queue_btn.setObjectName("primary")
        self.add_queue_btn.setFixedHeight(32)
        self.add_queue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_queue_btn.setToolTip("添加到播放列表")
        self.add_queue_btn.clicked.connect(lambda *a: self.add_to_queue())

        self.clear_queue_btn = QPushButton()
        self.clear_queue_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_queue_btn.setIcon(_make_icon(_draw_clear, 16, '#94a3b8'))
        self.clear_queue_btn.setIconSize(QSize(16, 16))
        self.clear_queue_btn.setFixedHeight(32)
        self.clear_queue_btn.setStyleSheet("background:#1e293b; border:1px solid #334155; border-radius:6px;")
        self.clear_queue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_queue_btn.setToolTip("清空当前列表")
        self.clear_queue_btn.clicked.connect(lambda *a: self.clear_queue())

        btn_layout.addWidget(self.add_queue_btn, stretch=3)
        btn_layout.addWidget(self.clear_queue_btn, stretch=1)
        qlayout.addLayout(btn_layout)

        self.main_layout.addWidget(self.player_widget, stretch=1)
        self.main_layout.addWidget(self.queue_widget)

        # Timer
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

        # Extractors
        self.extractor = YtDlpWorker()
        self.extractor.item_extracted.connect(self._on_item_extracted)
        self.extractor.finished.connect(self._on_extract_finished)
        self.extractor.error.connect(self._on_extract_error)
        self.extractor.limit_reached.connect(self._on_extract_limit)

        self.stream_worker = YtDlpStreamWorker(self, state=self.state)
        self.stream_worker.media_ready.connect(self._on_media_ready)
        self.stream_worker.media_status.connect(self._on_media_status)
        self.stream_worker.error.connect(self._on_stream_error)

        # Playback & collection state
        self.playlist = []
        self.favorites = []
        self.favorite_urls = set()
        self.active_tab = "playlist"
        self.playback_source = "playlist"
        self.search_query = ""
        self.current_index = -1
        self.is_playing_state = False
        self.is_fullscreen = False
        self._extract_limited = False

        self._playlist_save_timer = QTimer(self)
        self._playlist_save_timer.setSingleShot(True)
        self._playlist_save_timer.setInterval(200)
        self._playlist_save_timer.timeout.connect(self._flush_playlist_state)
        self._restore_playlist()

    # ── Highlighting & Auto Scrolling ──

    def _scroll_to_current_playlist_item(self):
        if self.playback_source != self.active_tab:
            return
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == self.current_index:
                self.queue_list.setCurrentItem(item)
                self.queue_list.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)
                break

    # ── Player Events ──

    def _ensure_vlc(self) -> bool:
        return self.player is not None

    def _on_media_status_changed(self, status) -> None:
        if self._is_changing_media or not self._media_cache_dir:
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            request = self._current_request_id
            QTimer.singleShot(0, lambda: self.play_next()
                              if request == self._current_request_id else None)
        elif status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            self._media_retry_pending = False
            self._trigger_next_prefetch()

    def _on_playback_state_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.is_playing_state = playing
        self.play_btn.setIcon(self._pause_icon if playing else self._play_icon)

    def _on_media_error(self, error=None, error_string="") -> None:
        if self._media_retry_pending:
            return
        message = str(error_string or (self.player.errorString() if self.player else ""))
        labels = {
            QMediaPlayer.Error.ResourceError: "资源地址失效",
            QMediaPlayer.Error.FormatError: "媒体格式不兼容",
            QMediaPlayer.Error.NetworkError: "网络连接失败",
            QMediaPlayer.Error.AccessDeniedError: "视频需要权限或登录",
        }
        label = labels.get(error, "无法打开媒体")
        req_id = self._current_request_id
        self._finish_media_failure(req_id, label, message)

    # ── Quality Selector Menu ──

    def _show_quality_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0f172a; border: 1px solid #1e293b;
                border-radius: 8px; padding: 6px; color: #f8fafc;
            }
            QMenu::item {
                padding: 6px 22px 6px 16px; border-radius: 6px; font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #0284c7; color: #ffffff;
            }
        """)

        auto_action = QAction("自动 (最高画质)", menu)
        auto_action.setCheckable(True)
        auto_action.setChecked(self._selected_quality_height == 0)
        auto_action.triggered.connect(lambda: self._select_quality(0))
        menu.addAction(auto_action)
        menu.addSeparator()

        for h in [1080, 720, 480, 360]:
            label = f"{h}p HD" if h >= 720 else f"{h}p"
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(self._selected_quality_height == h)
            action.triggered.connect(lambda checked=False, height=h: self._select_quality(height))
            menu.addAction(action)

        menu.exec(self.quality_btn.mapToGlobal(QPointF(0, -menu.sizeHint().height()).toPoint()))

    def _select_quality(self, height: int):
        self._selected_quality_height = height
        pool = self._get_active_playback_list()
        if self.current_index < 0 or self.current_index >= len(pool):
            return

        current_pos = self.player.position() if self.player else 0
        title, url = pool[self.current_index]
        if url.startswith("http"):
            self._current_request_id += 1
            req_id = self._current_request_id
            self.stream_worker.cancel()
            self.stream_worker.load_media(req_id, url, self._selected_quality_height, self._media_cache_dir)
            self._pending_seek_pos = current_pos

    # ── Pre-fetching Next Video ──

    def _trigger_next_prefetch(self):
        pool = self._get_active_playback_list()
        if len(pool) <= 1:
            return
        nxt = self.current_index + 1
        if nxt >= len(pool):
            if self.play_mode == "sequence":
                nxt = 0
            else:
                return
        _title, next_url = pool[nxt]
        if next_url.startswith("http"):
            self.stream_worker.prefetch(next_url, self._selected_quality_height, self._media_cache_dir)

    # ── Player Controls ──

    def set_window_id(self):
        return

    def toggle_playlist_panel(self):
        """Toggle right side playlist panel visibility."""
        is_visible = self.queue_widget.isVisible()
        self.queue_widget.setVisible(not is_visible)
        self.toggle_playlist_btn.setToolTip("展开播放列表" if is_visible else "折叠播放列表")
        if not is_visible:
            self._scroll_to_current_playlist_item()

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.queue_widget.hide()
            self.showFullScreen()
        else:
            self.queue_widget.show()
            self.showNormal()

    def set_always_on_top(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._always_on_top:
            return

        was_fullscreen = self.isFullScreen() or self.is_fullscreen
        normal_geometry = None if was_fullscreen else self.saveGeometry()

        self._always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)

        if was_fullscreen:
            self.showFullScreen()
        else:
            self.show()
            if normal_geometry is not None:
                self.restoreGeometry(normal_geometry)

        self.always_on_top_btn.setToolTip("取消置顶" if enabled else "置顶窗口")

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape and self.is_fullscreen:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key.Key_Space:
            self.toggle_play()
        super().keyPressEvent(event)

    def set_volume(self, value):
        if hasattr(self, "audio_output"):
            self.audio_output.setVolume(max(0.0, min(1.0, value / 100.0)))
        self.vol_btn.setIcon(self._muted_icon if value == 0 else self._speaker_icon)

    def eventFilter(self, obj, event):
        if obj == getattr(self, "search_input", None):
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.search_input.clear()
                self.search_input.clearFocus()
                return True
        return super().eventFilter(obj, event)

    # ── Audio Device Hot-Switching ──

    def _on_audio_outputs_changed(self):
        self._rebind_audio_output()

    def _rebind_audio_output(self):
        try:
            default_dev = QMediaDevices.defaultAudioOutput()
            if not default_dev.isNull() and hasattr(self, "audio_output") and self.audio_output:
                if self.audio_output.device().id() != default_dev.id():
                    self.audio_output.setDevice(default_dev)
        except Exception:
            pass

    def _show_audio_devices_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0f172a; border: 1px solid #1e293b;
                border-radius: 8px; padding: 6px; color: #f8fafc;
            }
            QMenu::item {
                padding: 6px 22px 6px 16px; border-radius: 6px; font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #0284c7; color: #ffffff;
            }
        """)

        title_action = QAction("🎧 选择音频输出设备", menu)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()

        current_dev = self.audio_output.device() if self.audio_output else None
        current_id = current_dev.id() if current_dev else None

        for dev in QMediaDevices.audioOutputs():
            desc = dev.description()
            if dev.isDefault():
                desc += " (系统默认)"
            action = QAction(desc, menu)
            action.setCheckable(True)
            action.setChecked(dev.id() == current_id)
            action.triggered.connect(lambda checked=False, d=dev: self._switch_audio_device(d))
            menu.addAction(action)

        menu.exec(self.vol_btn.mapToGlobal(pos))

    def _switch_audio_device(self, device: QAudioDevice):
        try:
            if hasattr(self, "audio_output") and self.audio_output and not device.isNull():
                self.audio_output.setDevice(device)
                self.status_label.setText(f"已切换声道: {device.description()[:25]}")
        except Exception:
            pass

    # ── Playback Controls ──

    def toggle_play(self):
        pool = self._get_active_playback_list() if hasattr(self, "_get_active_playback_list") else getattr(self, "playlist", [])
        if pool and self.current_index == -1:
            self.play_next()
            return
        if self.is_playing_state:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self._ensure_vlc():
            return
        self.player.play()
        self.is_playing_state = True
        self.play_btn.setIcon(self._pause_icon)

    def pause(self):
        if not self._vlc_ready or self.player is None:
            return
        self.player.pause()
        self.is_playing_state = False
        self.play_btn.setIcon(self._play_icon)

    def stop(self):
        self._current_request_id += 1
        self.stream_worker.cancel()
        self._media_retry_pending = False
        if self._vlc_ready and self.player:
            try:
                self.player.stop()
            except Exception:
                pass
        self.is_playing_state = False
        self.play_btn.setIcon(self._play_icon)
        self.slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self.status_label.setText("")

    # ── Subscriptions & Feeds ──

    def _open_subscriptions_dialog(self):
        dialog = YouTubeSubscriptionsDialog(
            self,
            state=self.state,
            save_state=self.save_state,
            feed_monitor=self.feed_monitor,
        )
        dialog.exec()

    def add_feed_videos(self, videos: list[dict]):
        if not videos:
            return
        added = 0
        for v in videos:
            title = f"[更新 · {v['channel_title']}] {v['title']}"
            url = v["url"]
            if any(u == url for _, u in self.playlist):
                continue
            self.playlist.append((title, url))
            added += 1
        if added:
            media_cfg = (self.state or {}).get("media", {})
            max_limit = max(1, min(2000, int(media_cfg.get("playlist_limit") or 1000)))
            if len(self.playlist) > max_limit:
                to_remove_count = len(self.playlist) - max_limit
                removed = 0
                new_playlist = []
                for t, u in self.playlist:
                    if removed < to_remove_count and u not in self.favorite_urls and t.startswith("[更新 · "):
                        removed += 1
                        continue
                    new_playlist.append((t, u))
                if len(new_playlist) > max_limit:
                    excess = len(new_playlist) - max_limit
                    rem2 = 0
                    final_list = []
                    for t, u in new_playlist:
                        if rem2 < excess and u not in self.favorite_urls:
                            rem2 += 1
                            continue
                        final_list.append((t, u))
                    new_playlist = final_list
                self.playlist = new_playlist
            self._persist_playlist()
            self._populate_list_view()
            self.status_label.setText(f"已收录 {added} 个订阅新视频")

    # ── File & Queue ──

    def _restore_playlist(self):
        media_cfg = self.state.setdefault("media", {})
        saved_playlist = media_cfg.get("playlist", [])
        if not isinstance(saved_playlist, list):
            saved_playlist = []

        restored = []
        allow_online = bool(media_cfg.get("allow_online", True))
        for entry in saved_playlist[:MAX_QUEUE_ITEMS]:
            if isinstance(entry, dict):
                title, url = entry.get("title", ""), entry.get("url", "")
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                title, url = entry[0], entry[1]
            else:
                continue

            title = str(title)[:MAX_TITLE_LENGTH] or "Unknown"
            url = str(url)
            if not url or len(url) > MAX_URL_LENGTH:
                continue
            is_online = url.startswith(("http://", "https://"))
            if is_online and not allow_online:
                continue
            if not is_online and not os.path.isfile(url):
                continue
            restored.append((title, url))

        self.playlist.clear()
        self.playlist.extend(restored)

        # Restore favorites
        saved_favs = media_cfg.get("favorites")
        self.favorites = []
        self.favorite_urls = set()
        if isinstance(saved_favs, list):
            for entry in saved_favs[:MAX_QUEUE_ITEMS]:
                if isinstance(entry, dict):
                    title, url = entry.get("title", ""), entry.get("url", "")
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    title, url = entry[0], entry[1]
                else:
                    continue
                if url:
                    self.favorites.append((str(title)[:MAX_TITLE_LENGTH] or "Unknown", str(url)))
                    self.favorite_urls.add(str(url))
        elif saved_favs is None:
            # First time running new version: auto-seed existing non-update items into favorites!
            for title, url in self.playlist:
                if not title.startswith("[更新 · "):
                    self.favorites.append((title, url))
                    self.favorite_urls.add(url)
            media_cfg["favorites"] = [{"title": t, "url": u} for t, u in self.favorites]
            self._persist_favorites()

        media_cfg["playlist"] = [
            {"title": title, "url": url} for title, url in self.playlist
        ]
        self._populate_list_view()

    def _persist_playlist(self, *, immediate=False):
        self.state.setdefault("media", {})["playlist"] = [
            {"title": str(title)[:MAX_TITLE_LENGTH], "url": str(url)[:MAX_URL_LENGTH]}
            for title, url in self.playlist[:MAX_QUEUE_ITEMS]
        ]
        if not self.save_state:
            return
        if immediate:
            self._playlist_save_timer.stop()
            self._flush_playlist_state()
        else:
            self._playlist_save_timer.start()

    def _persist_favorites(self):
        self.state.setdefault("media", {})["favorites"] = [
            {"title": str(t)[:MAX_TITLE_LENGTH], "url": str(u)[:MAX_URL_LENGTH]}
            for t, u in self.favorites[:MAX_QUEUE_ITEMS]
        ]
        if self.save_state:
            try:
                self.save_state()
            except Exception:
                pass

    def _flush_playlist_state(self):
        if self.save_state:
            try:
                self.save_state()
            except Exception:
                pass

    def _set_active_tab(self, tab_name: str):
        self.active_tab = tab_name
        if self.current_index == -1:
            self.playback_source = tab_name
        self.tab_playlist_btn.setChecked(tab_name == "playlist")
        self.tab_favorites_btn.setChecked(tab_name == "favorites")
        self._populate_list_view()

    def _on_search_text_changed(self, text: str):
        self.search_query = text
        self._populate_list_view()

    def is_favorite(self, url: str) -> bool:
        return url in self.favorite_urls

    def _on_star_clicked(self, row: int):
        item = self.queue_list.item(row)
        if not item:
            return
        orig_idx = item.data(Qt.ItemDataRole.UserRole)
        pool = self.favorites if self.active_tab == "favorites" else self.playlist
        if orig_idx is None or orig_idx < 0 or orig_idx >= len(pool):
            return
        title, url = pool[orig_idx]
        self.toggle_favorite(title, url)

    def toggle_favorite(self, title: str, url: str):
        if not url:
            return
        if url in self.favorite_urls:
            self.favorites = [(t, u) for (t, u) in self.favorites if u != url]
            self.favorite_urls.discard(url)
            self.status_label.setText(f"已移出我的最爱: {title[:20]}")
        else:
            self.favorites.append((title, url))
            self.favorite_urls.add(url)
            self.status_label.setText(f"⭐ 已加入我的最爱: {title[:20]}")
        self._persist_favorites()
        self._populate_list_view()

    def _get_active_playback_list(self) -> list[tuple[str, str]]:
        if self.playback_source == "favorites":
            return self.favorites
        return self.playlist

    def _populate_list_view(self):
        self.queue_list.clear()

        # Update tab counts
        fav_count = len(self.favorites)
        self.tab_favorites_btn.setText(f"⭐ 我的最爱 ({fav_count})")
        self.tab_playlist_btn.setText("📋 播放列表")

        source_list = self.favorites if self.active_tab == "favorites" else self.playlist
        search_str = self.search_query.strip()

        for orig_idx, (title, url) in enumerate(source_list):
            if search_str and not matches_search(search_str, title):
                continue
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, orig_idx)
            is_fav = url in self.favorite_urls
            item.setData(Qt.ItemDataRole.UserRole + 1, is_fav)
            is_curr = (self.playback_source == self.active_tab and self.current_index == orig_idx)
            item.setData(Qt.ItemDataRole.UserRole + 2, is_curr)
            if is_fav:
                item.setToolTip(f"{title}\n⭐ 已在我的最爱 (点击右侧五角星移出)")
            else:
                item.setToolTip(f"{title}\n☆ 点击右侧五角星加入我的最爱")
            self.queue_list.addItem(item)

        self._scroll_to_current_playlist_item()

    def open_file(self):
        media_cfg = self.state.setdefault("media", {})
        start_dir = str(media_cfg.get("last_open_dir") or os.path.expanduser("~"))
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "导入本地音视频",
            start_dir,
            "音视频文件 (*.mp4 *.mkv *.avi *.mp3 *.flv *.mov *.wav *.m4a *.wmv *.webm);;所有文件 (*.*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if filenames:
            media_cfg["last_open_dir"] = os.path.dirname(filenames[0])
            remaining = max(0, MAX_QUEUE_ITEMS - len(self.playlist))
            if remaining == 0:
                return
            for f in filenames[:remaining]:
                title = os.path.basename(f)
                self.playlist.append((title, f))
            self._persist_playlist()
            self._populate_list_view()
            if self.current_index == -1 and self.playlist:
                self.status_label.setText(f"已导入 {min(len(filenames), remaining)} 个本地文件")
                QTimer.singleShot(0, self.play_next)

    def set_buttons_enabled(self, enabled: bool):
        self.add_queue_btn.setEnabled(enabled)
        self.open_file_btn.setEnabled(enabled)

    def add_to_queue(self):
        text = self.url_input.toPlainText().strip()
        if not text:
            return
        urls = [u.strip() for u in text.splitlines() if u.strip()]
        if len(urls) > MAX_INPUT_URLS:
            return
        if any(len(url) > MAX_URL_LENGTH for url in urls):
            return
        media_cfg = self.state.get("media")
        if not isinstance(media_cfg, dict):
            media_cfg = {}
        if not bool(media_cfg.get("allow_online", True)) and any(
            url.startswith(("http://", "https://")) for url in urls
        ):
            return
        remaining = MAX_QUEUE_ITEMS - len(self.playlist)
        if remaining <= 0:
            return
        configured_limit = max(
            1, min(1000, int(media_cfg.get("playlist_limit") or 1000))
        )
        extract_limit = min(configured_limit, remaining)
        self.url_input.clear()
        self.status_label.setText("Extracting...")
        self.set_buttons_enabled(False)
        self._extract_limited = False
        self.extractor.extract(urls, extract_limit)

    def clear_queue(self):
        self.extractor.cancel()
        self.stream_worker.cancel()
        self.set_buttons_enabled(True)
        if self.active_tab == "favorites":
            self.favorites.clear()
            self.favorite_urls.clear()
            self._persist_favorites()
        else:
            self.playlist.clear()
            self._persist_playlist()
        self.current_index = -1
        self.stop()
        self._populate_list_view()

    def _on_item_extracted(self, title, url):
        if len(self.playlist) >= MAX_QUEUE_ITEMS:
            self.extractor.cancel()
            self._on_extract_limit(f"Limit: {MAX_QUEUE_ITEMS}")
            return
        title = str(title)[:MAX_TITLE_LENGTH] or "Unknown"
        url = str(url)
        if not url or len(url) > MAX_URL_LENGTH:
            return
        self.playlist.append((title, url))
        self._persist_playlist()
        self._populate_list_view()

    def _on_extract_finished(self):
        self.set_buttons_enabled(True)
        if not self._extract_limited:
            self.status_label.setText("")
        if self.current_index == -1 and self.playlist:
            self.play_next()

    def _on_extract_limit(self, message):
        self._extract_limited = True
        self.set_buttons_enabled(True)
        self.status_label.setText(str(message))

    def _on_extract_error(self, err):
        self.set_buttons_enabled(True)
        self.status_label.setText(f"Error: {err}")

    def _on_queue_double_click(self, item):
        orig_idx = item.data(Qt.ItemDataRole.UserRole)
        if orig_idx is not None:
            self.playback_source = self.active_tab
            self.play_index(orig_idx)
        else:
            self.playback_source = self.active_tab
            self.play_index(self.queue_list.row(item))

    def _queue_context_menu(self, pos):
        item = self.queue_list.itemAt(pos)
        if item is None:
            return
        orig_idx = item.data(Qt.ItemDataRole.UserRole)
        pool = self.favorites if self.active_tab == "favorites" else self.playlist
        if orig_idx is None or orig_idx >= len(pool):
            orig_idx = self.queue_list.row(item)
            if orig_idx >= len(pool):
                return
        title, url = pool[orig_idx]
        is_fav = url in self.favorite_urls

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0f172a; border: 1px solid #1e293b;
                border-radius: 8px; padding: 6px; color: #f8fafc;
            }
            QMenu::item {
                padding: 6px 22px 6px 16px; border-radius: 6px; font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #0284c7; color: #ffffff;
            }
        """)

        play_action = QAction("▶ 播放此项", menu)
        play_action.triggered.connect(lambda: (setattr(self, "playback_source", self.active_tab), self.play_index(orig_idx)))
        menu.addAction(play_action)

        if is_fav:
            fav_action = QAction("☆ 从我的最爱中移除", menu)
        else:
            fav_action = QAction("⭐ 添加到我的最爱", menu)
        fav_action.triggered.connect(lambda: self.toggle_favorite(title, url))
        menu.addAction(fav_action)

        menu.addSeparator()

        copy_action = QAction("📋 复制链接", menu)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(url))
        menu.addAction(copy_action)

        remove_action = QAction("✕ 移除此项", menu)
        remove_action.triggered.connect(lambda: self._remove_item(orig_idx))
        menu.addAction(remove_action)

        menu.exec(self.queue_list.mapToGlobal(pos))

    def _remove_item(self, idx: int):
        pool = self.favorites if self.active_tab == "favorites" else self.playlist
        if 0 <= idx < len(pool):
            title, url = pool.pop(idx)
            if self.active_tab == "favorites":
                self.favorite_urls.discard(url)
                self._persist_favorites()
            else:
                self._persist_playlist()
            if self.playback_source == self.active_tab:
                if idx == self.current_index:
                    self.stop()
                    self.current_index = -1
                elif idx < self.current_index:
                    self.current_index -= 1
            self._populate_list_view()

    # ── Playback ──

    def play_prev(self):
        pool = self._get_active_playback_list() if hasattr(self, "_get_active_playback_list") else getattr(self, "playlist", [])
        if not pool:
            return
        if self.play_mode == "random":
            self.play_next()
        else:
            prev_idx = self.current_index - 1
            self.play_index(prev_idx if prev_idx >= 0 else len(pool) - 1)

    def play_next(self):
        pool = self._get_active_playback_list() if hasattr(self, "_get_active_playback_list") else getattr(self, "playlist", [])
        if not pool:
            return
        if self.play_mode == "single_loop":
            self.play_index(max(0, self.current_index))
        elif self.play_mode == "random":
            if len(pool) <= 1:
                self.play_index(0)
            else:
                self.play_index(random.randint(0, len(pool) - 1))
        else:
            nxt = self.current_index + 1
            self.play_index(nxt if nxt < len(pool) else 0)

    def set_play_mode(self, mode: str):
        self.play_mode = mode
        self.seq_play_btn.setChecked(mode == "sequence")
        self.single_loop_btn.setChecked(mode == "single_loop")
        self.random_play_btn.setChecked(mode == "random")
        self.state.setdefault("media", {})["play_mode"] = mode
        if hasattr(self, "_playlist_save_timer"):
            self._persist_playlist()

    def play_index(self, index: int):
        pool = self._get_active_playback_list() if hasattr(self, "_get_active_playback_list") else getattr(self, "playlist", [])
        if index < 0 or index >= len(pool):
            return
        self.current_index = index
        self._populate_list_view()

        self._current_request_id += 1
        req_id = self._current_request_id
        self.stream_worker.cancel()
        self._online_source_url = ""
        self._media_retry_pending = False
        self._pending_seek_pos = 0

        title, url = pool[index]
        if url.startswith("http"):
            self._online_source_url = url
            self.stream_worker.load_media(req_id, url, self._selected_quality_height, self._media_cache_dir)
        else:
            self._play_stream(req_id, title, url)

    def _on_media_status(self, req_id: int, message: str):
        if req_id == self._current_request_id:
            self.status_label.setText(message)

    def _on_media_ready(self, req_id: int, path: str, height: int):
        if req_id != self._current_request_id or self.current_index < 0:
            return
        self._media_retry_pending = False
        pool = self._get_active_playback_list()
        title = pool[self.current_index][0] if 0 <= self.current_index < len(pool) else ""
        q_label = f" [{height}p]" if height > 0 else ""
        self.status_label.setText(f"{title}{q_label}")
        seek_pos = getattr(self, "_pending_seek_pos", 0)
        self._pending_seek_pos = 0
        self._play_stream(req_id, title, path, seek_pos_ms=seek_pos)

    def _on_stream_error(self, req_id: int, err: str):
        if req_id != self._current_request_id:
            return
        self._finish_media_failure(req_id, "加载失败", str(err))

    def _finish_media_failure(self, req_id: int, label: str, detail: str):
        if req_id != self._current_request_id or self._media_retry_pending:
            return
        self._media_retry_pending = True
        short_detail = detail.strip() or "未知原因"
        is_bot_or_429 = any(k in short_detail.lower() for k in ("not a bot", "429", "too many requests", "sign in"))
        if is_bot_or_429:
            self.status_label.setText("播放失败：当前代理节点被 YouTube 拦截验证 (429/人机验证)，请在代理软件中切换其他节点")
            self.status_label.setToolTip(
                "YouTube 对当前代理节点触发了人机验证 (HTTP 429)。\n"
                "解决办法：\n"
                "1. 在代理软件（如 v2rayN / Clash）中切换至其他节点线路。\n"
                "2. 或在 %LOCALAPPDATA%\\ClockAlarm\\ 目录下放置导出的 cookies.txt，以登录身份免除拦截。"
            )
            self.is_playing_state = False
            self.play_btn.setIcon(self._play_icon)
            self._media_retry_pending = False
            return

        if len(short_detail) > 120:
            short_detail = short_detail[:117] + "…"
        self.status_label.setText(f"播放失败：{label}（{short_detail}），即将播放下一项")
        self.is_playing_state = False
        self.play_btn.setIcon(self._play_icon)
        QTimer.singleShot(1500, lambda r=req_id: self._advance_after_failure(r))

    def _advance_after_failure(self, req_id: int):
        if req_id != self._current_request_id:
            return
        self._media_retry_pending = False
        pool = self._get_active_playback_list()
        if len(pool) <= 1:
            self.status_label.setText("播放失败：列表中没有其他可播放项目")
            return
        nxt = (max(self.current_index, 0) + 1) % len(pool)
        self.play_index(nxt)

    def _play_stream(self, req_id: int, title: str, uri: str, seek_pos_ms: int = 0):
        if req_id != self._current_request_id:
            return
        if not self._ensure_vlc():
            return
        self._is_changing_media = True
        try:
            self.player.stop()
            source = QUrl(uri) if uri.startswith(("http://", "https://")) else QUrl.fromLocalFile(uri)
            self.player.setSource(source)
            self.audio_output.setVolume(self.vol_slider.value() / 100.0)
            self.player.play()
            if seek_pos_ms > 0:
                QTimer.singleShot(300, lambda p=seek_pos_ms, r=req_id:
                                  self.player.setPosition(p) if r == self._current_request_id else None)
            self.is_playing_state = True
            self.play_btn.setIcon(self._pause_icon)
            self.setWindowTitle(f"Clock/Alarm v{get_app_version()} - {title}")
            self._scroll_to_current_playlist_item()
        finally:
            self._is_changing_media = False

    # ── UI Update ──

    def _format_time(self, ms: int) -> str:
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def update_ui(self):
        if self._is_changing_media or not self._vlc_ready or self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            return
        if self._slider_dragging:
            return
        try:
            length = self.player.duration()
            if length > 0:
                cur_time = self.player.position()
                pos = cur_time / length
                self.slider.blockSignals(True)
                self.slider.setValue(int(pos * 1000))
                self.slider.blockSignals(False)
                self.time_label.setText(
                    f"{self._format_time(cur_time)} / {self._format_time(length)}"
                )
        except Exception:
            pass

    def _on_slider_pressed(self):
        self._slider_dragging = True

    def _on_slider_released(self):
        self._slider_dragging = False
        self.set_position(self.slider.value())

    def set_position(self, value):
        if self._vlc_ready and self.player and not self._is_changing_media:
            try:
                duration = self.player.duration()
                if duration > 0:
                    self.player.setPosition(int(duration * value / 1000.0))
            except Exception:
                pass

    def closeEvent(self, event):
        self._current_request_id += 1
        self.stream_worker.cancel()
        if self._vlc_ready and self.player:
            try:
                self.player.stop()
                self.player.setSource(QUrl())
            except Exception:
                pass
        self._persist_playlist(immediate=True)
        if self._media_cache_dir:
            self.stream_worker.retire_cache(self._media_cache_dir)
            self._media_cache_dir = ""
        event.accept()

    def showEvent(self, event):
        if not self._media_cache_dir:
            self._media_cache_dir = tempfile.mkdtemp(prefix="ClockAlarm-media-")
        super().showEvent(event)
