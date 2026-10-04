"""
YouTube RSS Feed Monitor
Fetches official YouTube Atom feeds for subscribed channels without requiring API keys.
"""

from __future__ import annotations

import gzip
import logging
import re
import socket
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

ATOM_NS = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"

MAX_SEEN_IDS = 500

_WORKING_PROXY: Optional[str] = None
_PROXY_DETECTED = False
_PROXY_LOCK = threading.Lock()


def detect_local_proxy(force_recheck: bool = False) -> Optional[str]:
    """
    Sub-millisecond probe for common local proxy ports (v2ray, clash, sing-box, etc.).
    Prevents 8-second direct connection timeout stalls on GFW-restricted networks.
    """
    global _WORKING_PROXY, _PROXY_DETECTED
    with _PROXY_LOCK:
        if _PROXY_DETECTED and not force_recheck:
            return _WORKING_PROXY

        _PROXY_DETECTED = True
        # Check standard local proxy ports
        candidate_ports = (10808, 7890, 10809, 1080, 1082, 8080)
        for port in candidate_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.04)
                res = s.connect_ex(("127.0.0.1", port))
                s.close()
                if res == 0:
                    _WORKING_PROXY = f"http://127.0.0.1:{port}"
                    logger.info(f"Detected active local proxy: {_WORKING_PROXY}")
                    return _WORKING_PROXY
            except Exception:
                continue

        _WORKING_PROXY = None
        return None


def http_get(url: str, timeout: int = 8) -> str:
    """
    High-speed HTTP GET with automatic gzip decompression, browser headers,
    and automatic local proxy detection (e.g. Clash/V2Ray on ports 10808, 7890).
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"不合法的 URL 协议方案: {parsed.scheme}，仅允许 http 与 https")
    req = urllib.request.Request(url, headers=headers)

    # 1. Fast Path: Use detected local proxy immediately if available
    proxy = detect_local_proxy()
    if proxy:
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    return gzip.decompress(raw).decode("utf-8", errors="replace")
                return raw.decode("utf-8", errors="replace")
        except Exception as proxy_err:
            logger.debug(f"Detected proxy {proxy} request failed: {proxy_err}")

    # 2. Try direct connection (with a moderate timeout)
    try:
        with urllib.request.urlopen(req, timeout=min(5, timeout)) as resp:  # nosec B310 - scheme validated above
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                return gzip.decompress(raw).decode("utf-8", errors="replace")
            return raw.decode("utf-8", errors="replace")
    except Exception as direct_err:
        # 3. Fallback scan all common ports if direct failed
        for p_port in (10808, 7890, 10809, 1080, 8080):
            p_url = f"http://127.0.0.1:{p_port}"
            if p_url == proxy:
                continue
            try:
                p_handler = urllib.request.ProxyHandler({"http": p_url, "https": p_url})
                opener = urllib.request.build_opener(p_handler)
                with opener.open(req, timeout=timeout) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                        return gzip.decompress(raw).decode("utf-8", errors="replace")
                    return raw.decode("utf-8", errors="replace")
            except Exception:
                continue
        raise direct_err


def parse_atom_feed(xml_text: str) -> dict[str, Any]:
    """Parse YouTube Atom XML feed into structured dictionary."""
    if not xml_text:
        return {}
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise ValueError("检测到不安全的 XML 实体声明 (DTD/ENTITY)，已拒绝解析以防范 XML 实体注入攻击")
    root = ET.fromstring(xml_text)  # nosec B314 - DTD and entity expansion prohibited above
    
    channel_title = ""
    title_elem = root.find(f"{ATOM_NS}title")
    if title_elem is not None and title_elem.text:
        channel_title = title_elem.text.strip()

    channel_id = ""
    yt_chid_elem = root.find(f"{YT_NS}channelId")
    if yt_chid_elem is not None and yt_chid_elem.text:
        channel_id = yt_chid_elem.text.strip()

    entries: list[dict[str, Any]] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        vid_elem = entry.find(f"{YT_NS}videoId")
        if vid_elem is None or not vid_elem.text:
            continue
        video_id = vid_elem.text.strip()

        v_title_elem = entry.find(f"{ATOM_NS}title")
        v_title = v_title_elem.text.strip() if v_title_elem is not None and v_title_elem.text else video_id

        pub_elem = entry.find(f"{ATOM_NS}published")
        published = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else ""

        link_elem = entry.find(f"{ATOM_NS}link")
        link = ""
        if link_elem is not None:
            link = link_elem.attrib.get("href", "")
        if not link:
            link = f"https://www.youtube.com/watch?v={video_id}"

        # Thumbnail
        thumb_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        media_group = entry.find(f"{MEDIA_NS}group")
        if media_group is not None:
            media_thumb = media_group.find(f"{MEDIA_NS}thumbnail")
            if media_thumb is not None and "url" in media_thumb.attrib:
                thumb_url = media_thumb.attrib["url"]

        author_name = channel_title
        author_elem = entry.find(f"{ATOM_NS}author/{ATOM_NS}name")
        if author_elem is not None and author_elem.text:
            author_name = author_elem.text.strip()

        entries.append({
            "video_id": video_id,
            "title": v_title,
            "url": link,
            "published": published,
            "thumbnail": thumb_url,
            "channel_title": author_name or channel_title,
            "channel_id": channel_id,
        })

    return {
        "channel_id": channel_id,
        "channel_title": channel_title,
        "entries": entries,
    }


def fetch_channel_feed(channel_id: str, timeout: int = 8) -> dict[str, Any]:
    """Fetch and parse the official YouTube RSS feed for given channel ID."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}"
    content = http_get(url, timeout=timeout)
    feed_data = parse_atom_feed(content)
    if not feed_data.get("channel_id"):
        feed_data["channel_id"] = channel_id
    return feed_data


def resolve_channel_id(input_str: str, timeout: int = 8) -> Optional[dict[str, Any]]:
    """
    Resolve channel handle, URL, or channel ID into channel details.
    Returns dict with keys: channel_id, title, handle, url, rss_url, entries
    or None if unresolved.
    """
    clean_input = input_str.strip()
    if not clean_input:
        return None

    # Case 1: Pure Channel ID (e.g. UC...)
    pure_id_match = re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", clean_input)
    if pure_id_match:
        chid = pure_id_match.group(0)
        try:
            feed = fetch_channel_feed(chid, timeout=timeout)
            return {
                "channel_id": chid,
                "title": feed.get("channel_title") or chid,
                "handle": "",
                "url": f"https://www.youtube.com/channel/{chid}",
                "rss_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={chid}",
                "entries": feed.get("entries", []),
            }
        except Exception as e:
            logger.warning(f"Error fetching feed for pure ID {chid}: {e}")
            return {
                "channel_id": chid,
                "title": chid,
                "handle": "",
                "url": f"https://www.youtube.com/channel/{chid}",
                "rss_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={chid}",
                "entries": [],
            }

    # Case 2: URL with /channel/UC...
    url_chid_match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", clean_input)
    if url_chid_match:
        chid = url_chid_match.group(1)
        try:
            feed = fetch_channel_feed(chid, timeout=timeout)
            title = feed.get("channel_title") or chid
            entries = feed.get("entries", [])
        except Exception:
            title = chid
            entries = []
        return {
            "channel_id": chid,
            "title": title,
            "handle": "",
            "url": f"https://www.youtube.com/channel/{chid}",
            "rss_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={chid}",
            "entries": entries,
        }

    # Case 3: Handle (e.g. @mkbhd or https://youtube.com/@mkbhd)
    handle_match = re.search(r"@([a-zA-Z0-9_.-]+)", clean_input)
    handle = f"@{handle_match.group(1)}" if handle_match else ""

    probe_url = clean_input
    if not probe_url.startswith("http://") and not probe_url.startswith("https://"):
        if handle:
            probe_url = f"https://www.youtube.com/{handle}"
        else:
            probe_url = f"https://www.youtube.com/@{clean_input.lstrip('/')}"

    try:
        html = http_get(probe_url, timeout=timeout)

        # Probe for channel ID
        chid = ""
        m = re.search(
            r'(?:<link\s+rel="canonical"\s+href="https://www\.youtube\.com/channel/'
            r'|<meta\s+itemprop="(?:identifier|channelId)"\s+content="'
            r'|"(?:browse_id|channelId)"\s*:\s*"'
            r'|channel/(UC[a-zA-Z0-9_-]{22}))(UC[a-zA-Z0-9_-]{22})?',
            html,
        )
        if m:
            chid = m.group(1) or m.group(2) or ""

        # Title from HTML og:title or title tag (preferred over feed to avoid mojibake)
        channel_title = ""
        tm = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if tm:
            channel_title = tm.group(1).replace(" - YouTube", "").strip()
        if not channel_title:
            tm = re.search(r"<title>([^<]+)</title>", html)
            if tm:
                channel_title = tm.group(1).replace(" - YouTube", "").strip()

        entries = []
        if chid:
            try:
                feed = fetch_channel_feed(chid, timeout=min(6, timeout))
                entries = feed.get("entries", [])
                if not channel_title and feed.get("channel_title"):
                    channel_title = feed["channel_title"]
            except Exception:
                pass

            return {
                "channel_id": chid,
                "title": channel_title or (handle if handle else chid),
                "handle": handle,
                "url": f"https://www.youtube.com/channel/{chid}",
                "rss_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={chid}",
                "entries": entries,
            }
    except Exception as e:
        logger.warning(f"Fast probe failed for {probe_url}: {e}")

    # Fallback: yt_dlp flat extraction if installed
    try:
        import yt_dlp
        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 6,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(probe_url, download=False)
            if info:
                chid = info.get("channel_id") or info.get("id")
                title = info.get("channel") or info.get("uploader") or info.get("title")
                if chid and chid.startswith("UC"):
                    return {
                        "channel_id": chid,
                        "title": title or chid,
                        "handle": handle,
                        "url": f"https://www.youtube.com/channel/{chid}",
                        "rss_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={chid}",
                        "entries": [],
                    }
    except Exception as e:
        logger.debug(f"yt_dlp fallback failed: {e}")

    return None


class YouTubeFeedMonitor(QObject):
    """
    Background monitor that periodically checks YouTube channel RSS feeds
    and emits signals when new videos are discovered.
    """

    new_videos_signal = pyqtSignal(list)  # list[dict]
    check_started_signal = pyqtSignal()
    check_finished_signal = pyqtSignal(int)  # int: count of new videos
    status_signal = pyqtSignal(str)

    def __init__(
        self,
        state: dict[str, Any],
        save_state: Callable[[], None],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.save_state = save_state
        self._lock = threading.Lock()
        self._is_checking = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)
        self._setup_timer()

    def _setup_timer(self) -> None:
        media_state = self.state.setdefault("media", {})
        mins = int(media_state.get("subscription_check_mins", 30))
        mins = max(5, min(1440, mins))  # Clamp between 5m and 24h
        interval_ms = mins * 60 * 1000
        self.timer.setInterval(interval_ms)
        self.timer.start()

    def update_check_interval(self, mins: int) -> None:
        mins = max(5, min(1440, int(mins)))
        media_state = self.state.setdefault("media", {})
        media_state["subscription_check_mins"] = mins
        self.save_state()
        self.timer.setInterval(mins * 60 * 1000)

    def _on_timer_tick(self) -> None:
        self.check_now_async()

    def check_now_async(self, on_finish: Optional[Callable[[int], None]] = None) -> None:
        """Trigger an asynchronous check of all subscribed channels."""
        if self._is_checking:
            return
        t = threading.Thread(target=self._run_check_worker, args=(on_finish,), daemon=True)
        t.start()

    def _run_check_worker(self, on_finish: Optional[Callable[[int], None]] = None) -> None:
        with self._lock:
            if self._is_checking:
                return
            self._is_checking = True

        self.check_started_signal.emit()
        self.status_signal.emit("正在检查 YouTube 频道更新...")

        new_videos: list[dict[str, Any]] = []

        try:
            media_state = self.state.setdefault("media", {})
            subs = list(media_state.get("subscriptions", []))
            seen_ids = set(media_state.get("seen_video_ids", []))

            for sub in subs:
                if not sub.get("enabled", True):
                    continue
                chid = sub.get("channel_id")
                if not chid:
                    continue

                try:
                    feed = fetch_channel_feed(chid, timeout=10)
                    entries = feed.get("entries", [])

                    # If channel's initial baseline has not been set yet, record existing
                    # videos so user is not flooded with historical videos upon subscription
                    is_initial = sub.get("initial_baseline_done", False) is False

                    sub_new: list[dict[str, Any]] = []
                    for entry in entries:
                        vid = entry["video_id"]
                        if vid not in seen_ids:
                            if not is_initial:
                                sub_new.append(entry)
                            seen_ids.add(vid)

                    if is_initial:
                        sub["initial_baseline_done"] = True
                        if entries:
                            sub["last_checked_title"] = entries[0]["title"]
                            sub["last_checked_time"] = entries[0]["published"]

                    if sub_new:
                        sub["last_checked_title"] = sub_new[0]["title"]
                        sub["last_checked_time"] = sub_new[0]["published"]
                        new_videos.extend(sub_new)

                except Exception as e:
                    logger.warning(f"Failed to check feed for channel {chid}: {e}")

            # Cap seen_video_ids to MAX_SEEN_IDS
            seen_list = list(seen_ids)
            if len(seen_list) > MAX_SEEN_IDS:
                seen_list = seen_list[-MAX_SEEN_IDS:]
            media_state["seen_video_ids"] = seen_list
            self.save_state()

        except Exception as e:
            logger.error(f"Error in YouTube feed check worker: {e}", exc_info=True)
        finally:
            with self._lock:
                self._is_checking = False

        self.check_finished_signal.emit(len(new_videos))
        if new_videos:
            self.new_videos_signal.emit(new_videos)
            self.status_signal.emit(f"发现 {len(new_videos)} 个新视频")
        else:
            self.status_signal.emit("YouTube 频道已是最新状态")

        if on_finish:
            try:
                on_finish(len(new_videos))
            except Exception:
                pass

    def add_subscription(self, channel_data: dict[str, Any]) -> bool:
        """Add a newly subscribed channel."""
        media_state = self.state.setdefault("media", {})
        subs = media_state.setdefault("subscriptions", [])
        chid = channel_data.get("channel_id")
        if not chid:
            return False

        # Check existing
        for s in subs:
            if s.get("channel_id") == chid:
                s.update(channel_data)
                self.save_state()
                return True

        # Pre-seed seen_video_ids with channel's current videos to avoid flooding
        seen_ids = set(media_state.get("seen_video_ids", []))
        entries = channel_data.get("entries")
        if not entries:
            try:
                feed = fetch_channel_feed(chid, timeout=6)
                entries = feed.get("entries", [])
            except Exception as e:
                logger.warning(f"Could not pre-seed feed for {chid}: {e}")
                entries = []

        for entry in (entries or []):
            seen_ids.add(entry["video_id"])
        if entries:
            channel_data["last_checked_title"] = entries[0]["title"]
            channel_data["last_checked_time"] = entries[0].get("published", "")

        channel_data["initial_baseline_done"] = True
        channel_data.setdefault("enabled", True)
        subs.append(channel_data)

        # Cap seen_video_ids
        seen_list = list(seen_ids)
        if len(seen_list) > MAX_SEEN_IDS:
            seen_list = seen_list[-MAX_SEEN_IDS:]
        media_state["seen_video_ids"] = seen_list
        self.save_state()
        return True

    def remove_subscription(self, channel_id: str) -> bool:
        media_state = self.state.setdefault("media", {})
        subs = media_state.get("subscriptions", [])
        initial_len = len(subs)
        media_state["subscriptions"] = [s for s in subs if s.get("channel_id") != channel_id]
        if len(media_state["subscriptions"]) != initial_len:
            self.save_state()
            return True
        return False

    def toggle_subscription(self, channel_id: str, enabled: bool) -> bool:
        media_state = self.state.setdefault("media", {})
        subs = media_state.get("subscriptions", [])
        for s in subs:
            if s.get("channel_id") == channel_id:
                s["enabled"] = enabled
                self.save_state()
                return True
        return False
