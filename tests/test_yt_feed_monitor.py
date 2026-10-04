import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication
import yt_feed_monitor as yfm

MOCK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <link rel="self" href="http://www.youtube.com/feeds/videos.xml?channel_id=UCbj0c5T2IVVNnL65rZp5-ow"/>
 <id>yt:channel:UCbj0c5T2IVVNnL65rZp5-ow</id>
 <yt:channelId>UCbj0c5T2IVVNnL65rZp5-ow</yt:channelId>
 <title>Marques Brownlee</title>
 <author>
  <name>Marques Brownlee</name>
  <uri>https://www.youtube.com/channel/UCbj0c5T2IVVNnL65rZp5-ow</uri>
 </author>
 <published>2008-03-21T18:00:00+00:00</published>
 <entry>
  <id>yt:video:abc123xyz45</id>
  <yt:videoId>abc123xyz45</yt:videoId>
  <yt:channelId>UCbj0c5T2IVVNnL65rZp5-ow</yt:channelId>
  <title>The Ultimate Smartphone Review 2026</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=abc123xyz45"/>
  <author>
   <name>Marques Brownlee</name>
   <uri>https://www.youtube.com/channel/UCbj0c5T2IVVNnL65rZp5-ow</uri>
  </author>
  <published>2026-09-10T12:00:00+00:00</published>
  <updated>2026-09-10T12:30:00+00:00</updated>
  <media:group>
   <media:title>The Ultimate Smartphone Review 2026</media:title>
   <media:thumbnail url="https://i1.ytimg.com/vi/abc123xyz45/hqdefault.jpg" width="480" height="360"/>
  </media:group>
 </entry>
 <entry>
  <id>yt:video:def456uvw78</id>
  <yt:videoId>def456uvw78</yt:videoId>
  <yt:channelId>UCbj0c5T2IVVNnL65rZp5-ow</yt:channelId>
  <title>MacBook Pro M5 Review</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=def456uvw78"/>
  <published>2026-09-08T10:00:00+00:00</published>
 </entry>
</feed>
"""

class TestYouTubeFeedMonitor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_parse_atom_feed(self):
        feed = yfm.parse_atom_feed(MOCK_XML)
        self.assertEqual(feed["channel_id"], "UCbj0c5T2IVVNnL65rZp5-ow")
        self.assertEqual(feed["channel_title"], "Marques Brownlee")
        self.assertEqual(len(feed["entries"]), 2)

        first = feed["entries"][0]
        self.assertEqual(first["video_id"], "abc123xyz45")
        self.assertEqual(first["title"], "The Ultimate Smartphone Review 2026")
        self.assertEqual(first["url"], "https://www.youtube.com/watch?v=abc123xyz45")
        self.assertEqual(first["published"], "2026-09-10T12:00:00+00:00")
        self.assertEqual(first["thumbnail"], "https://i1.ytimg.com/vi/abc123xyz45/hqdefault.jpg")
        self.assertEqual(first["channel_title"], "Marques Brownlee")

        second = feed["entries"][1]
        self.assertEqual(second["video_id"], "def456uvw78")
        self.assertEqual(second["title"], "MacBook Pro M5 Review")
        # default thumbnail fallback
        self.assertEqual(second["thumbnail"], "https://i.ytimg.com/vi/def456uvw78/hqdefault.jpg")

    def test_resolve_channel_id_pure(self):
        with patch.object(yfm, "fetch_channel_feed", return_value={"channel_title": "Test Channel"}):
            res = yfm.resolve_channel_id("UCbj0c5T2IVVNnL65rZp5-ow")
            self.assertIsNotNone(res)
            self.assertEqual(res["channel_id"], "UCbj0c5T2IVVNnL65rZp5-ow")
            self.assertEqual(res["title"], "Test Channel")

    def test_resolve_channel_id_channel_url(self):
        with patch.object(yfm, "fetch_channel_feed", return_value={"channel_title": "Test Channel"}):
            res = yfm.resolve_channel_id("https://www.youtube.com/channel/UCbj0c5T2IVVNnL65rZp5-ow")
            self.assertIsNotNone(res)
            self.assertEqual(res["channel_id"], "UCbj0c5T2IVVNnL65rZp5-ow")

    @patch.object(yfm, "fetch_channel_feed")
    def test_monitor_flow(self, mock_fetch):
        mock_fetch.return_value = {
            "channel_id": "UC1234567890123456789012",
            "channel_title": "Tech News",
            "entries": [
                {
                    "video_id": "vid1",
                    "title": "Video 1",
                    "url": "https://www.youtube.com/watch?v=vid1",
                    "published": "2026-09-10T10:00:00Z",
                    "thumbnail": "",
                    "channel_title": "Tech News",
                    "channel_id": "UC1234567890123456789012",
                }
            ]
        }

        saved_states = []
        state = {
            "media": {
                "subscriptions": [],
                "seen_video_ids": [],
                "subscription_check_mins": 30,
            }
        }
        def mock_save():
            saved_states.append(dict(state))

        monitor = yfm.YouTubeFeedMonitor(state=state, save_state=mock_save)

        # 1. Add subscription
        channel_info = {
            "channel_id": "UC1234567890123456789012",
            "title": "Tech News",
            "handle": "@technews",
            "url": "https://www.youtube.com/channel/UC1234567890123456789012",
        }
        success = monitor.add_subscription(channel_info)
        self.assertTrue(success)
        self.assertIn("vid1", state["media"]["seen_video_ids"])
        self.assertEqual(len(state["media"]["subscriptions"]), 1)

        # 2. Worker check when no new videos:
        emitted_videos = []
        monitor.new_videos_signal.connect(lambda vids: emitted_videos.extend(vids))
        monitor._run_check_worker()
        self.assertEqual(len(emitted_videos), 0)

        # 3. New video arrives:
        mock_fetch.return_value["entries"].insert(0, {
            "video_id": "vid2_new",
            "title": "Video 2 Breaking",
            "url": "https://www.youtube.com/watch?v=vid2_new",
            "published": "2026-09-10T11:00:00Z",
            "thumbnail": "",
            "channel_title": "Tech News",
            "channel_id": "UC1234567890123456789012",
        })
        monitor._run_check_worker()
        self.assertEqual(len(emitted_videos), 1)
        self.assertEqual(emitted_videos[0]["video_id"], "vid2_new")
        self.assertIn("vid2_new", state["media"]["seen_video_ids"])

        # 4. Toggle & remove subscription
        self.assertTrue(monitor.toggle_subscription("UC1234567890123456789012", False))
        self.assertFalse(state["media"]["subscriptions"][0]["enabled"])

        self.assertTrue(monitor.remove_subscription("UC1234567890123456789012"))
        self.assertEqual(len(state["media"]["subscriptions"]), 0)

    def test_media_player_add_feed_videos(self):
        from media_player_ui import MediaPlayerWindow
        state = {"media": {"playlist": [], "allow_online": True}}
        win = MediaPlayerWindow(state=state, save_state=lambda: None)
        self.assertEqual(len(win.playlist), 0)

        videos = [
            {
                "title": "Review 2026",
                "channel_title": "Tech Channel",
                "url": "https://www.youtube.com/watch?v=rev2026",
            }
        ]
        win.add_feed_videos(videos)
        self.assertEqual(len(win.playlist), 1)
        self.assertEqual(win.queue_list.count(), 1)
        self.assertIn("Review 2026", win.playlist[0][0])
        self.assertEqual(win.playlist[0][1], "https://www.youtube.com/watch?v=rev2026")

        # Adding duplicate should not duplicate
        win.add_feed_videos(videos)
        self.assertEqual(len(win.playlist), 1)
        self.assertEqual(win.queue_list.count(), 1)

    def test_subscriptions_dialog_ui(self):
        from media_player_ui import YouTubeSubscriptionsDialog
        saved = []
        state = {
            "media": {
                "subscriptions": [
                    {
                        "channel_id": "UCtest123",
                        "title": "Channel A",
                        "handle": "@channelA",
                        "enabled": True,
                        "last_checked_title": "Video Alpha",
                    }
                ],
                "auto_add_to_playlist": True,
                "notify_on_new_video": True,
                "subscription_check_mins": 60,
            }
        }
        dlg = YouTubeSubscriptionsDialog(
            state=state,
            save_state=lambda: saved.append(True),
            feed_monitor=None,
        )
        self.assertEqual(dlg.interval_combo.currentData(), 60)
        self.assertTrue(dlg.auto_add_cb.isChecked())
        self.assertTrue(dlg.notify_cb.isChecked())
        # Toggling options
        dlg.auto_add_cb.setChecked(False)
        self.assertFalse(state["media"]["auto_add_to_playlist"])
        dlg.notify_cb.setChecked(False)
        self.assertFalse(state["media"]["notify_on_new_video"])

        # Toggle channel
        dlg._toggle_channel("UCtest123", False)
        self.assertFalse(state["media"]["subscriptions"][0]["enabled"])

        # Delete channel
        dlg._delete_channel("UCtest123")
        self.assertEqual(len(state["media"]["subscriptions"]), 0)

    def test_detect_local_proxy(self):
        # Test proxy detection with mock socket
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0  # port open
            mock_sock_cls.return_value = mock_sock

            proxy = yfm.detect_local_proxy(force_recheck=True)
            self.assertIsNotNone(proxy)
            self.assertTrue(proxy.startswith("http://127.0.0.1:"))

    def test_batch_channel_addition_optimistic_ui(self):
        from media_player_ui import YouTubeSubscriptionsDialog
        saved = []
        state = {
            "media": {
                "subscriptions": [],
                "subscription_check_mins": 30,
            }
        }
        dlg = YouTubeSubscriptionsDialog(
            state=state,
            save_state=lambda: saved.append(True),
            feed_monitor=None,
        )

        # Batch input with multiple channels (newline and comma separated)
        batch_input = """
        https://www.youtube.com/@mkbhd
        @LinusTechTips, UCbj0c5T2IVVNnL65rZp5-ow
        """
        dlg.input_field.setText(batch_input)

        # Mock resolve_channel_id so worker threads do not make real network calls in test
        with patch("media_player_ui.resolve_channel_id", return_value={
            "channel_id": "UCbj0c5T2IVVNnL65rZp5-ow",
            "title": "Mock Channel",
            "handle": "@mock",
            "entries": [{"video_id": "v1", "title": "Mock Title", "published": "2026-09-10"}],
        }):
            dlg._add_channel()

            # 1. Input field must be cleared immediately (0 wait)
            self.assertEqual(dlg.input_field.text(), "")
            self.assertTrue(dlg.add_btn.isEnabled())

            # 2. Subscriptions list must immediately contain all 3 items (optimistic addition)
            subs = state["media"]["subscriptions"]
            self.assertEqual(len(subs), 3)
            # All 3 were created with resolving state
            self.assertTrue(any(s["handle"] == "@mkbhd" for s in subs))
            self.assertTrue(any(s["handle"] == "@LinusTechTips" for s in subs))
            self.assertTrue(any(s["channel_id"] == "UCbj0c5T2IVVNnL65rZp5-ow" for s in subs))

            # 3. Simulate successful resolution callback
            temp_id = subs[0]["channel_id"]
            dlg._on_resolution_succeeded(temp_id, {
                "channel_id": "UCreal123",
                "title": "MKBHD Official",
                "handle": "@mkbhd",
                "entries": [{"video_id": "v99", "title": "Phone Review 2026", "published": "2026-09-10"}],
            })
            self.assertEqual(subs[0]["status"], "active")
            self.assertEqual(subs[0]["title"], "MKBHD Official")
            self.assertEqual(subs[0]["last_checked_title"], "Phone Review 2026")

            # 4. Simulate failed resolution callback & retry
            dlg._on_resolution_failed(subs[1]["channel_id"], "网络超时")
            self.assertEqual(subs[1]["status"], "error")

            dlg._retry_channel(subs[1]["channel_id"])
            self.assertEqual(subs[1]["status"], "resolving")

            # 5. Duplicate input check - should not add existing
            dlg.input_field.setText("@mkbhd")
            dlg._add_channel()
            self.assertEqual(len(state["media"]["subscriptions"]), 3)

    def test_http_get_rejects_non_http_schemes(self):
        with self.assertRaises(ValueError):
            yfm.http_get("file:///C:/Windows/win.ini")
        with self.assertRaises(ValueError):
            yfm.http_get("ftp://example.com/test")

    def test_parse_atom_feed_rejects_dtd_entity_bombs(self):
        malicious_xml = """<?xml version="1.0"?>
        <!DOCTYPE lolz [
         <!ENTITY lol "lol">
         <!ENTITY lol2 "&lol;&lol;">
        ]>
        <feed xmlns="http://www.w3.org/2005/Atom"><title>&lol2;</title></feed>"""
        with self.assertRaises(ValueError):
            yfm.parse_atom_feed(malicious_xml)


if __name__ == "__main__":
    unittest.main()

