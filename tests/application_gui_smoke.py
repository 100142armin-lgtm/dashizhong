"""Offline cross-module Qt smoke test. Uses private state and generated media only."""
import copy
import datetime
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QObject, QTime, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication
import numpy as np
import cv2
import alarm_sounds
import media_player_ui as media
import world_clock_ui as clock
import settings_ui as settings
import hotkeys
from main import ClockAlarmApp
from simple_boards import TodosController, NotesController
from storage import DEFAULT_STATE
from hotkeys import parse_hotkey_combo
from settings_ui import CleanerDialog
from theme import apply_app_palette


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    apply_app_palette(app, 'dark')
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        app.setFont(QFont(families[0], 10))
    errors = []
    def hook(kind, value, tb):
        errors.append(str(value))
        traceback.print_exception(kind, value, tb)
    sys.excepthook = hook
    def pump(seconds=0.1, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            assert not errors, errors
            if until and until(): return
            time.sleep(0.005)
        if until: assert until(), 'GUI condition timed out'
    state = copy.deepcopy(DEFAULT_STATE)
    saves, notifications, rings = [], [], []
    save = lambda: saves.append(1)
    alarm_sounds.play_ringtone = lambda *a, **kw: rings.append(a)
    stopped_rings = []
    alarm_sounds.stop_ringtone = lambda: stopped_rings.append(1)
    clock.play_ringtone = alarm_sounds.play_ringtone
    clock.stop_ringtone = lambda: None
    clock.ensure_ringtones = lambda: {}
    host = ClockAlarmApp.__new__(ClockAlarmApp)
    QObject.__init__(host)
    host.store = SimpleNamespace(state=state, save_state=save)
    host.tray = SimpleNamespace(showMessage=lambda *args: notifications.append(args))
    host.show_ringing_alarm = lambda alarm: rings.append(alarm['id'])

    board = clock.FloatingWorldClock(state)
    board.show()
    for index in range(3):
        board.show_tools(index)
        pump()
        assert board.tools_window.isWindow() and board.detail_stack.currentIndex() == index
    board.add_clock_by_name('Asia/Shanghai', '上海')
    assert any(c.tz_name == 'Asia/Shanghai' for c in board.clocks)
    board.time_alarm.setTime(QTime.currentTime())
    board.txt_alarm_name.setText('测试闹钟')
    board._add_alarm()
    pump()
    state['alarms'][-1]['time'] = datetime.datetime.now().strftime('%H:%M')
    host._alarm_tick()
    count = len(rings)
    assert count == 1 and not state['alarms'][-1]['enabled']
    host._alarm_tick()
    assert len(rings) == count
    board._delete_alarm()
    pump()
    assert state['alarms'] == []
    board.spin_h.setValue(0)
    board.spin_m.setValue(0)
    board.spin_s.setValue(2)
    board.txt_timer_name.setText('测试倒计时')
    board._start_timer()
    board._pause_timer()
    host._alarm_tick()
    assert state['timer']['remaining'] == 2
    assert '继续' in board.btn_timer_pause.text(), 'Paused timer must advertise resume'
    board._pause_timer()
    host._alarm_tick()
    host._alarm_tick()
    assert state['timer']['remaining'] == 0 and not state['timer']['active']
    assert notifications[-1][1] == '测试倒计时', 'Timer notification lost its label'
    board._reset_timer()
    ringing = clock.AlarmRingingDialog({'name': '测试提醒', 'ringtone': 'beep'})
    ringing.show()
    pump()
    ringing.dismiss()
    assert stopped_rings
    print('PASS clock: independent tabs, world clock, once-only alarm, pause/resume/finish timer')

    todos = TodosController(state, save)
    todos.show_all()
    todos.show_all()
    assert len(todos.windows) == 1
    todo_window = next(iter(todos.windows.values()))
    todo_window.mgr.add('测试项目')
    todo_window.refresh()
    todos.show_manager()
    notes = NotesController(state, save)
    notes.add_note()
    assert len(notes.windows) == 1
    notes.show_manager()
    pump()
    assert todos.manager_win.isVisible() and notes.manager_win.isVisible()
    clean_options = CleanerDialog(state, save)
    clean_options.show()
    pump()
    assert {key for key, check in clean_options.checks.items() if check.isChecked()} == {'temp', 'thumbs'}
    clean_options.reject()  # Never confirm or run actual cleanup.
    assert parse_hotkey_combo('Ctrl+Alt+A') is not None
    assert parse_hotkey_combo('not-a-hotkey') is None
    print('PASS todo/notes manager windows, cleaner safe defaults, hotkey parsing')

    # Stub OS mutations: validate settings and registrations without changing Windows.
    os_choices = {'autostart': False, 'association': False}
    settings.is_autostart_enabled = lambda: os_choices['autostart']
    settings.set_autostart = lambda enabled: os_choices.update(autostart=enabled)
    settings.is_right_click_association_enabled = lambda: os_choices['association']
    settings.set_right_click_association = lambda enabled: os_choices.update(association=enabled)
    preferences = settings.SettingsDialog(state, save)
    preferences.show()
    pump()
    preferences.autostart.setChecked(True)
    preferences.right_click_menu.setChecked(True)
    preferences.playlist_limit.setValue(30)
    preferences._save()
    assert state['prefs']['autostart'] and state['prefs']['autostart_consent']
    assert state['media']['playlist_limit'] == 30 and state['media']['right_click_association']
    bindings = {}
    def register(_window, key, modifiers, vk):
        bindings[key] = (modifiers, vk)
        return True
    def unregister(_window, key):
        bindings.pop(key, None)
        return True
    hotkeys._user32 = lambda: SimpleNamespace(RegisterHotKey=register, UnregisterHotKey=unregister)
    manager = hotkeys.ClockAlarmHotkeys({}, state)
    assert len(bindings) == len(hotkeys.HOTKEY_MAP)
    manager.pause_screenshot_hotkeys()
    assert hotkeys.HOTKEY_MAP['screenshot'] not in bindings
    manager.resume_screenshot_hotkeys()
    assert len(bindings) == len(hotkeys.HOTKEY_MAP)
    manager.close()
    assert not bindings
    print('PASS settings save and hotkey registrations (OS APIs mocked)')

    with tempfile.TemporaryDirectory(prefix='media-smoke-') as folder:
        movie = Path(folder) / 'synthetic.avi'
        writer = cv2.VideoWriter(str(movie), cv2.VideoWriter_fourcc(*'MJPG'), 10, (160, 120))
        assert writer.isOpened()
        for n in range(12):
            writer.write(np.full((120, 160, 3), n * 15, dtype=np.uint8))
        writer.release()
        player = media.MediaPlayerWindow(state=state, save_state=save)
        player.audio_output.setMuted(True)
        player.show()
        player.playlist = [('一', str(movie)), ('二', str(movie))]
        player.queue_list.addItems(['一', '二'])
        player.set_play_mode('sequence')
        player.play_index(0)
        pump(8, lambda: player.player.duration() > 0)
        pump(8, lambda: player.current_index == 1)
        player.pause()
        player.set_always_on_top(True)
        player.toggle_playlist_panel()
        player.resize(560, 380)
        pump()
        player.stop()
        request = player._current_request_id
        player._on_media_ready(request - 1, str(movie), 0)
        assert not player.is_playing_state
        cache_dir = Path(player._media_cache_dir)
        player.close()
        pump(3, lambda: not cache_dir.exists())
        player.show()
        assert player._media_cache_dir and Path(player._media_cache_dir) != cache_dir
        assert Path(player._media_cache_dir).is_dir()
        player.play_index(0)
        pump(8, lambda: player.player.duration() > 0)
        player.close()
        pump()
    print('PASS media: generated video decode, automatic next, pause/stop, topmost, resize, close/reopen')
    app.closeAllWindows()
    pump()
    assert not errors, errors


if __name__ == '__main__':
    main()
