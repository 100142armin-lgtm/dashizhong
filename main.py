"""Clock/Alarm application shell for the retained desktop tools."""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from cleaner import CleanReport, run_deep_clean_async
from hotkeys import ClockAlarmHotkeys
from skin import bundle_root
from storage import JsonStore
from theme import apply_app_palette


def _install_exception_hooks() -> Path:
    log_path = Path(__file__).resolve().parent / "Clock-Alarm-error.log"
    if getattr(sys, "frozen", False):
        log_path = Path(sys.executable).resolve().parent / "Clock-Alarm-error.log"

    def _write(message: str) -> None:
        try:
            # Prevent unbounded growth: if log exceeds 1 MB, retain only the tail 100 KB
            if log_path.is_file() and log_path.stat().st_size > 1024 * 1024:
                try:
                    content = log_path.read_text(encoding="utf-8", errors="ignore")
                    tail = content[-100 * 1024 :]
                    nl = tail.find("\n")
                    if nl != -1:
                        tail = tail[nl + 1 :]
                    log_path.write_text(tail, encoding="utf-8")
                except Exception:
                    pass
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(message if message.endswith("\n") else message + "\n")
        except OSError:
            pass

    def _hook(exc_type, exc_value, exc_traceback) -> None:
        _write(
            f"\n[{datetime.now().isoformat(timespec='seconds')}]\n"
            + "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        )

    sys.excepthook = _hook

    class _Logger:
        def write(self, message):
            _write(message)

        def flush(self):
            pass

    if sys.stdout is None or getattr(sys, "frozen", False):
        sys.stdout = _Logger()
        sys.stderr = _Logger()
    return log_path


def _get_video_from_argv() -> str | None:
    import sys
    import os
    for arg in sys.argv[1:]:
        if arg in ("-B", "-u", "-d", "--play") or arg.endswith(".py"):
            continue
        if os.path.exists(arg):
            return os.path.abspath(arg)
        if arg.startswith("http://") or arg.startswith("https://") or arg.startswith("www."):
            return arg
    return None


class ClockAlarmApp(QObject):
    clean_finished = pyqtSignal(object)
    clean_progress = pyqtSignal(object)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        self.store = JsonStore()
        media_cfg = self.store.state.get("media")
        if isinstance(media_cfg, dict) and media_cfg.get("right_click_association"):
            try:
                from settings_ui import set_right_click_association

                set_right_click_association(True)
            except Exception as exc:
                self.store.append_log(
                    "context_menu_error",
                    "Failed to repair the Windows video association",
                    error=str(exc),
                )
        self._cleaning = False
        self.cleaner_progress_window = None
        self._screenshot_active = False
        self.recorder_board = None
        self.world_clock_board = None
        self.media_player_board = None
        self.todo_board = None
        self.notes_ctl = None
        self._shutdown_started = False

        mode = str((self.store.state.get("prefs") or {}).get("theme") or "dark")
        apply_app_palette(app, mode)

        self.tray = self._make_tray()
        callbacks = {
            "world_clock": self.show_world_clock,
            "bookmarks": self.show_bookmarks,
            "screenshot": self.start_screenshot_region,
            "recorder": self.show_recorder_board,
            "todos": self.show_todos,
            "notes": self.show_notes,
            "media_player": self.show_media_player2,
            "cleaner": self.start_deep_clean,
        }
        self.hotkeys = ClockAlarmHotkeys(callbacks=callbacks, state=self.store.state)

        self._apply_saved_autostart()

        self.clean_finished.connect(self._on_clean_finished)
        self.clean_progress.connect(self._on_clean_progress)
        self.app.aboutToQuit.connect(self._shutdown_recorder)
        self.alarm_timer = QTimer(self)
        self.alarm_timer.timeout.connect(self._alarm_tick)
        self.alarm_timer.start(1000)

        from yt_feed_monitor import YouTubeFeedMonitor

        self.feed_monitor = YouTubeFeedMonitor(
            state=self.store.state,
            save_state=self.store.save_state,
            parent=self,
        )
        self.feed_monitor.new_videos_signal.connect(self._on_new_youtube_videos)
        self._last_notified_video_url = None

        self.store.append_log("login", "Clock/Alarm started")
        video_arg = _get_video_from_argv()
        if video_arg:
            QTimer.singleShot(400, lambda: self.show_media_player_with_video(video_arg))
        else:
            QTimer.singleShot(200, self.show_world_clock)

        if (self.store.state.get("prefs") or {}).get("check_updates", True):
            QTimer.singleShot(4000, lambda: self.check_for_updates(interactive=False))

        # 启动就绪后异步预热截图依赖模块（numpy, PIL, mss, screenshot_app），彻底消除首次按快捷键时的卡顿
        QTimer.singleShot(800, self._prewarm_screenshot)

    def _prewarm_screenshot(self) -> None:
        """Asynchronously pre-warm screenshot modules in background thread after startup."""
        import threading

        def _worker() -> None:
            try:
                import numpy  # noqa: F401
                import PIL.Image  # noqa: F401
                import mss  # noqa: F401
                import screenshot_app  # noqa: F401
                import gdrive_uploader  # noqa: F401
            except Exception:
                pass

        t = threading.Thread(target=_worker, daemon=True, name="ScreenshotPrewarm")
        t.start()

    def _cb(self) -> SimpleNamespace:
        return SimpleNamespace(
            save_state=self.store.save_state,
            rebind_screenshot_hotkeys=self.rebind_screenshot_hotkeys,
            pause_screenshot_hotkeys=self.pause_screenshot_hotkeys,
            resume_screenshot_hotkeys=self.resume_screenshot_hotkeys,
        )

    def _make_tray(self) -> QSystemTrayIcon:
        logo = bundle_root() / "logo.png"
        icon = QIcon(str(logo)) if logo.exists() else QIcon()
        tray = QSystemTrayIcon(icon, self.app)
        menu = QMenu()
        for text, callback in (
            ("闹钟 / 世界时钟 / 倒计时", self.show_clock_tools),
            ("灵动书签 (加密收藏夹)", self.show_bookmarks),
            ("区域截图", self.start_screenshot_region),
            ("屏幕录像", self.show_recorder_board),
            ("待办事项", self.show_todos),
            ("便签", self.show_notes),
            ("视频播放器", self.show_media_player2),
            ("电脑清理", self.start_deep_clean),
        ):
            action = QAction(text, menu)
            action.triggered.connect(lambda _checked=False, cb=callback: cb())
            menu.addAction(action)
        menu.addSeparator()
        settings_action = QAction("设置", menu)
        settings_action.triggered.connect(
            lambda _checked=False: self.show_settings()
        )
        menu.addAction(settings_action)
        update_action = QAction("检查新版本...", menu)
        update_action.triggered.connect(
            lambda _checked=False: self.check_for_updates(interactive=True)
        )
        menu.addAction(update_action)
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.setToolTip("Clock/Alarm")
        tray.activated.connect(self._tray_activated)
        tray.messageClicked.connect(self._on_tray_message_clicked)
        tray.show()
        return tray

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_world_clock()

    def show_hub(self) -> None:
        """Compatibility entry point for the global hotkey; opens the clock shell."""
        self.show_world_clock()

    def _screenshot_windows(self) -> list[QWidget]:
        # Todo/notes controllers own multiple windows; they are not QWidgets.
        candidates = [self.world_clock_board, self.recorder_board,
                      self.media_player_board, self.cleaner_progress_window,
                      getattr(self, "_settings_dialog", None)]
        for controller in (self.todo_board, self.notes_ctl):
            if controller is not None:
                candidates.extend(getattr(controller, "windows", {}).values())
                candidates.append(getattr(controller, "manager_win", None))
        if self.world_clock_board is not None:
            candidates.append(getattr(self.world_clock_board, "tools_window", None))
            candidates.append(getattr(self.world_clock_board, "bookmarks_panel", None))
        windows = []
        for window in candidates:
            if isinstance(window, QWidget) and window not in windows:
                windows.append(window)
        return windows

    def start_screenshot_region(self) -> None:
        if self._screenshot_active:
            return
        self._screenshot_active = True
        hidden_windows = []

        def restore_windows(_image=None) -> None:
            self._screenshot_active = False
            for board in hidden_windows:
                try:
                    board.show()
                except RuntimeError:
                    pass
            hidden_windows.clear()

        def notify_user(title: str, msg: str, is_info: bool = True) -> None:
            if getattr(self, "tray", None):
                icon = QSystemTrayIcon.MessageIcon.Information if is_info else QSystemTrayIcon.MessageIcon.Warning
                self.tray.showMessage(title, msg, icon, 8000)

        def launch() -> None:
            try:
                from screenshot_app import start_screenshot
                start_screenshot(
                    state=self.store.state,
                    on_done=restore_windows,
                    notify_callback=notify_user,
                    host=self,
                )
            except Exception as exc:
                restore_windows()
                QMessageBox.warning(None, "截图失败", str(exc))

        try:
            # Only hide windows if explicitly configured (default False to allow capturing player/clock)
            hide_windows = False
            if hasattr(self, "store") and self.store is not None:
                cfg = getattr(self.store, "state", {}).get("screenshot", {})
                hide_windows = bool(cfg.get("hide_windows", False))
            else:
                # Fallback for test harnesses mocking host as SimpleNamespace without store
                hide_windows = getattr(self, "_hide_windows_mock", True)

            if hide_windows:
                for window in self._screenshot_windows():
                    if window.isVisible():
                        hidden_windows.append(window)
                        window.hide()
            QTimer.singleShot(30, launch)
        except Exception as exc:
            restore_windows()
            QMessageBox.warning(None, "截图失败", str(exc))

    def rebind_screenshot_hotkeys(self) -> str:
        result = self.hotkeys.rebind()
        self.store.save_state()
        return result

    def pause_screenshot_hotkeys(self) -> None:
        try:
            self.hotkeys.pause_screenshot_hotkeys()
        except Exception:
            pass

    def resume_screenshot_hotkeys(self) -> None:
        try:
            self.hotkeys.resume_screenshot_hotkeys()
        except Exception:
            pass

    def show_recorder_board(self) -> None:
        from recorder_ui import FloatingRecorderBoard

        if self.recorder_board is None:
            self.recorder_board = FloatingRecorderBoard(self._cb(), self.store.state)
        self.recorder_board.showNormal()
        self.recorder_board.raise_()

    def show_world_clock(self) -> None:
        from world_clock_ui import FloatingWorldClock

        if self.world_clock_board is None:
            self.world_clock_board = FloatingWorldClock(self.store.state, host=self)
        self.world_clock_board.show()
        self.world_clock_board.raise_()
        self.world_clock_board.activateWindow()

    def show_clock_tools(self) -> None:
        if self.world_clock_board is None:
            self.show_world_clock()
        self.world_clock_board.show_tools(1)

    def show_bookmarks(self) -> None:
        if self.world_clock_board is None:
            self.show_world_clock()
        if self.world_clock_board is not None:
            self.world_clock_board.toggle_bookmarks_panel()

    def show_media_player2(self) -> None:
        from media_player_ui import MediaPlayerWindow

        if self.media_player_board is None:
            self.media_player_board = MediaPlayerWindow(
                state=self.store.state,
                save_state=self.store.save_state,
                feed_monitor=getattr(self, "feed_monitor", None),
            )
        self.media_player_board.show()
        self.media_player_board.raise_()

    def show_media_player_with_video(self, video_path: str) -> None:
        import os
        self.show_media_player2()
        if self.media_player_board:
            title = os.path.basename(video_path)
            if video_path.startswith("http"):
                title = "在线视频"
            
            exists = False
            for idx, (t, u) in enumerate(self.media_player_board.playlist):
                if u == video_path:
                    self.media_player_board.play_index(idx)
                    exists = True
                    break
            if not exists:
                self.media_player_board.playlist.append((title, video_path))
                self.media_player_board.queue_list.addItem(title)
                self.media_player_board._persist_playlist()
                self.media_player_board.play_index(len(self.media_player_board.playlist) - 1)

    def _on_new_youtube_videos(self, videos: list[dict]) -> None:
        if not videos:
            return
        media_cfg = self.store.state.setdefault("media", {})
        auto_add = bool(media_cfg.get("auto_add_to_playlist", True))
        notify = bool(media_cfg.get("notify_on_new_video", True))

        # 1. Update playlist
        if auto_add:
            if self.media_player_board is not None:
                self.media_player_board.add_feed_videos(videos)
            else:
                playlist = media_cfg.setdefault("playlist", [])
                max_limit = max(1, min(2000, int(media_cfg.get("playlist_limit") or 1000)))
                fav_urls = set()
                for f in media_cfg.get("favorites", []):
                    if isinstance(f, dict) and f.get("url"):
                        fav_urls.add(f["url"])
                    elif isinstance(f, (list, tuple)) and len(f) >= 2 and f[1]:
                        fav_urls.add(f[1])
                for v in videos:
                    tag = f"[更新 · {v['channel_title']}] {v['title']}"
                    url = v["url"]
                    if not any(
                        (isinstance(item, dict) and item.get("url") == url)
                        or (isinstance(item, (list, tuple)) and len(item) >= 2 and item[1] == url)
                        for item in playlist
                    ):
                        playlist.append({"title": tag, "url": url})
                if len(playlist) > max_limit:
                    to_remove_count = len(playlist) - max_limit
                    removed = 0
                    new_playlist = []
                    # First pass: trim oldest auto-feed items that are not in favorites
                    for item in playlist:
                        u = item.get("url") if isinstance(item, dict) else (item[1] if isinstance(item, (list, tuple)) and len(item) >= 2 else None)
                        t = item.get("title", "") if isinstance(item, dict) else (item[0] if isinstance(item, (list, tuple)) and len(item) >= 1 else "")
                        if removed < to_remove_count and u not in fav_urls and t.startswith("[更新 · "):
                            removed += 1
                            continue
                        new_playlist.append(item)
                    # Second pass if still over limit: trim non-favorite items
                    if len(new_playlist) > max_limit:
                        excess = len(new_playlist) - max_limit
                        rem2 = 0
                        final_list = []
                        for item in new_playlist:
                            u = item.get("url") if isinstance(item, dict) else (item[1] if isinstance(item, (list, tuple)) and len(item) >= 2 else None)
                            if rem2 < excess and u not in fav_urls:
                                rem2 += 1
                                continue
                            final_list.append(item)
                        new_playlist = final_list
                    media_cfg["playlist"] = new_playlist
                self.store.save_state()

        # 2. Tray notification
        if notify and getattr(self, "tray", None):
            latest = videos[0]
            self._last_notified_video_url = latest.get("url")
            count = len(videos)
            if count == 1:
                title_msg = f"YouTube 订阅更新 · {latest.get('channel_title')}"
                body_msg = f"发布了新视频：\n{latest.get('title')}"
            else:
                title_msg = f"YouTube 关注频道有 {count} 个新更新"
                body_msg = f"【{latest.get('channel_title')}】{latest.get('title')}\n等共 {count} 个视频"
            self.tray.showMessage(
                title_msg,
                body_msg,
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )

    def _on_tray_message_clicked(self) -> None:
        if getattr(self, "_pending_update_info", None):
            info = self._pending_update_info
            self._pending_update_info = None
            self.show_update_dialog(info)
            return
        if getattr(self, "_last_notified_video_url", None):
            self.show_media_player_with_video(self._last_notified_video_url)
        else:
            self.show_media_player2()

    def check_for_updates(self, interactive: bool = False) -> None:
        from skin import get_app_version
        from update_checker import UpdateCheckWorker

        current_ver = get_app_version()
        self._update_worker = UpdateCheckWorker(current_version=current_ver, parent=self)

        def _on_finished(info):
            if info.has_update:
                ignored = (self.store.state.get("prefs") or {}).get("ignored_update_version")
                if interactive or info.latest_version != ignored:
                    self._pending_update_info = info
                    if getattr(self, "tray", None):
                        self.tray.showMessage(
                            f"发现新版本 Clock/Alarm v{info.latest_version}",
                            "点击查看更新详情并前往下载新版本",
                            QSystemTrayIcon.MessageIcon.Information,
                            10000,
                        )
                    if interactive:
                        self.show_update_dialog(info)
            elif interactive:
                QMessageBox.information(
                    None,
                    "检查更新",
                    f"当前已是最新版本 (v{current_ver})，无需更新。",
                )

        def _on_failed(err):
            if interactive:
                QMessageBox.warning(
                    None,
                    "检查更新失败",
                    f"检查更新时发生错误：\n{err}\n\n请检查网络连接后重试。",
                )

        self._update_worker.check_finished.connect(_on_finished)
        self._update_worker.check_failed.connect(_on_failed)
        self._update_worker.start()

    def show_update_dialog(self, info) -> None:
        from update_dialog import UpdateDialog

        def on_ignore(ver):
            self.store.state.setdefault("prefs", {})["ignored_update_version"] = ver
            self.store.save_state()

        dlg = UpdateDialog(info, on_ignore=on_ignore)
        dlg.exec()

    def show_settings(self) -> None:
        from settings_ui import SettingsDialog

        if getattr(self, "_settings_dialog", None) is not None:
            try:
                if self._settings_dialog.isVisible():
                    self._settings_dialog.showNormal()
                    self._settings_dialog.raise_()
                    self._settings_dialog.activateWindow()
                    return
            except Exception:
                pass

        def save_and_rebind():
            self.store.save_state()
            self.hotkeys.rebuild()

        dialog = SettingsDialog(self.store.state, save_and_rebind)
        self._settings_dialog = dialog
        dialog.setModal(False)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def start_deep_clean(self, scopes: list[str] | None = None) -> None:
        if self._cleaning:
            if self.cleaner_progress_window:
                self.cleaner_progress_window.showNormal()
                self.cleaner_progress_window.raise_()
                self.cleaner_progress_window.activateWindow()
            return
        if scopes is None:
            from PyQt6.QtWidgets import QDialog
            from settings_ui import CleanerDialog

            dialog = CleanerDialog(self.store.state, self.store.save_state)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selected_scopes = dialog.selected_scopes()
        else:
            selected_scopes = list(scopes)
        if not selected_scopes:
            QMessageBox.information(None, "电脑清理", "没有选择任何清理项目。")
            return
        try:
            from settings_ui import CleanerProgressDialog
            progress_window = CleanerProgressDialog(selected_scopes, threading.Event())
            if self.cleaner_progress_window:
                self.cleaner_progress_window.close()
                self.cleaner_progress_window.deleteLater()
            self.cleaner_progress_window = progress_window
            progress_window.show()
            progress_window.raise_()
        except Exception as exc:
            QMessageBox.warning(None, "无法打开清理进度", str(exc))
            return
        self._cleaning = True

        def done(report: CleanReport) -> None:
            self.clean_finished.emit(report)

        try:
            run_deep_clean_async(done, scopes=selected_scopes,
                                 on_progress=self.clean_progress.emit,
                                 cancel_event=progress_window.cancel_event)
        except Exception as exc:
            self._on_clean_finished(CleanReport(failed=True, errors=[str(exc)]))

    def _on_clean_progress(self, progress: object) -> None:
        if self.cleaner_progress_window and self._cleaning:
            self.cleaner_progress_window.update_progress(progress)

    def _on_clean_finished(self, report: object) -> None:
        self._cleaning = False
        if isinstance(report, CleanReport):
            if self.cleaner_progress_window:
                self.cleaner_progress_window.finish(report)
            summary = report.summary()
            self.tray.showMessage(
                "清理已停止" if report.cancelled else "清理结果", summary,
                QSystemTrayIcon.MessageIcon.Information, 6000
            )
            self.store.append_log("clean_done", summary)

    def _apply_saved_autostart(self) -> None:
        """Apply only a recorded user choice; legacy implicit persistence is disabled."""
        from autostart import set_autostart

        prefs = self.store.state.setdefault("prefs", {})
        if not bool(prefs.get("autostart_consent")):
            prefs["autostart"] = False
            set_autostart(False)
            self.store.save_state()
            return
        set_autostart(bool(prefs.get("autostart")))

    def show_todos(self) -> None:
        from simple_boards import TodosController

        if self.todo_board is None:
            self.todo_board = TodosController(self.store.state, self.store.save_state)
        self.todo_board.show_all()

    def show_todos_manager(self) -> None:
        from simple_boards import TodosController

        if self.todo_board is None:
            self.todo_board = TodosController(self.store.state, self.store.save_state)
        self.todo_board.show_manager()

    def show_notes(self) -> None:
        from simple_boards import NotesController

        if self.notes_ctl is None:
            self.notes_ctl = NotesController(self.store.state, self.store.save_state)
        self.notes_ctl.show_all()

    def show_notes_manager(self) -> None:
        from simple_boards import NotesController

        if self.notes_ctl is None:
            self.notes_ctl = NotesController(self.store.state, self.store.save_state)
        self.notes_ctl.show_manager()

    def add_note(self) -> None:
        from simple_boards import NotesController

        if self.notes_ctl is None:
            self.notes_ctl = NotesController(self.store.state, self.store.save_state)
        self.notes_ctl.add_note()

    def show_alarm_board(self) -> None:
        self.show_world_clock()

    def _alarm_tick(self) -> None:
        import datetime as dt

        now = dt.datetime.now()
        timer_cfg = self.store.state.setdefault("timer", {})
        if (
            timer_cfg.get("active")
            and int(timer_cfg.get("remaining") or 0) > 0
            and not timer_cfg.get("paused")
        ):
            timer_cfg["remaining"] = int(timer_cfg.get("remaining") or 0) - 1
            if timer_cfg["remaining"] <= 0:
                timer_cfg["active"] = False
                try:
                    from alarm_sounds import play_ringtone

                    play_ringtone(str(timer_cfg.get("ringtone") or "beep"))
                except Exception:
                    pass
                name = timer_cfg.get("label") or timer_cfg.get("name") or "时间到"
                self.tray.showMessage(
                    "倒计时", name, QSystemTrayIcon.MessageIcon.Information, 6000
                )
                self.store.save_state()

        current_time = now.strftime("%H:%M")
        current_day = now.strftime("%Y-%m-%d")
        for alarm in self.store.state.get("alarms") or []:
            if not alarm.get("enabled"):
                continue
            if alarm.get("time") == current_time and alarm.get("last_triggered_date") != current_day:
                alarm["last_triggered_date"] = current_day
                if alarm.get("repeat") == "once":
                    alarm["enabled"] = False
                self.store.save_state()
                self.show_ringing_alarm(alarm)

    def show_ringing_alarm(self, alarm_data: dict) -> None:
        try:
            from world_clock_ui import AlarmRingingDialog

            active_dialog = getattr(self, "_active_alarm_dialog", None)
            if active_dialog is not None:
                try:
                    active_dialog.close()
                except Exception:
                    pass
            dialog = AlarmRingingDialog(alarm_data)
            self._active_alarm_dialog = dialog
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception as exc:
            print(f"Failed to show alarm dialog: {exc}")

    def _shutdown_recorder(self) -> None:
        board = self.recorder_board
        if board is None:
            return
        try:
            board.shutdown_for_exit()
        except Exception:
            pass

    def quit(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._shutdown_recorder()
        try:
            self.hotkeys.close()
        except Exception:
            pass
        self.store.save_state()
        self.app.quit()


def main() -> int:
    _install_exception_hooks()
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ClockAlarm.DesktopToolkit"
            )
            # Enable Per-Monitor DPI Awareness V2 (-4) or fallback to Per-Monitor Aware (-3)
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            except Exception:
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setApplicationName("Clock/Alarm")
    logo = bundle_root() / "logo.png"
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))
    try:
        ClockAlarmApp(app)
    except Exception as exc:
        traceback.print_exc()
        QMessageBox.critical(None, "Clock/Alarm", f"启动失败：{exc}")
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
