"""Isolated Windows UI verification. Real input targets only the counter below.

Run with --preview to inspect the workbench. While open, write a JSON object to
<output>/command.json with a unique id and action: capture, settings, floating,
restore, error, native, or quit. No existing config or script is read or changed.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
import json5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from PySide6.QtTest import QTest
import win32api
import win32con
import win32gui

from UIFunc import UIFunc
import Recorder
from Util.Global import State
from Util.MultiClickClass import ClickPoint, execute_click
from Util.Profiles import normalize_profile
from Util.Screen import logical_to_physical


class CounterTarget(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("点巡验证专用点击计数器")
        self.resize(300, 160)
        self.events = []
        self.setStyleSheet("background:#edf5e8;color:#2e5733;font:14px 'Microsoft YaHei UI';")
        layout = QVBoxLayout(self)
        text = QLabel("专用验证窗口\n点击只累加计数")
        text.setAlignment(Qt.AlignCenter)
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(text)
        self.counter_label = QLabel("0 次按下")
        self.counter_label.setAlignment(Qt.AlignCenter)
        self.counter_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.counter_label)

    def event(self, event):
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            self.events.append(int(event.button().value))
            self.counter_label.setText(f"{len(self.events)} 次按下")
        return super().event(event)


class Verification:
    def __init__(self, output, hold):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="点巡-desktop-")
        self.w = UIFunc(QApplication.instance(), data_dir=self.temp.name, enable_hooks=True)
        self.w.player.setVolume(0)
        self.hold = hold
        self.last_command = None
        self.report = {"isolated_data": "temporary directory; local path omitted", "checks": {}, "captures": {}}
        self.key_trace = []
        Recorder.set_callback(self.trace_key)
        self.seed_demo()
        self.w.move(45, 55)
        self.w.show()
        win32gui.ShowWindow(int(self.w.winId()), win32con.SW_SHOWNORMAL)
        self.w.raise_()
        self.w.activateWindow()
        self.poller = QTimer(self.w)
        self.poller.setInterval(150)
        self.poller.timeout.connect(self.poll_commands)
        self.poller.start()
        QTimer.singleShot(600, self.initial_capture)

    def seed_demo(self):
        sample = normalize_profile({"mode": "Sequential", "max_rounds": 20, "points": [
            {"name": "展开详情", "x": 846, "y": 362, "interval_ms": 800},
            {"name": "切换下一页", "x": 1124, "y": 708, "interval_min_ms": 1200, "interval_max_ms": 1600},
            {"name": "刷新内容", "x": 524, "y": 241, "click_type": "Double", "interval_ms": 2000},
            {"name": "返回列表", "x": 284, "y": 184, "interval_ms": 600},
        ]})
        self.w.multiclick_profiles = {"页面巡检": sample,
            "表单重复操作": normalize_profile({"points": [
                {"name": "打开表单", "x": 612, "y": 380}, {"name": "确认提交", "x": 908, "y": 664}]}),
            "空白方案": normalize_profile({})}
        self.w.active_profile_name = "页面巡检"
        self.w.multiclick_points = [ClickPoint(**data) for data in sample["points"]]
        self.w._selected_row = 1
        self.w._history.clear()
        self.w._refresh_all(reset_status=True)

    def write_report(self):
        (self.output / "desktop-report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")

    def trace_key(self, event):
        if event.event_type == "EK":
            self.key_trace.append([event.action_type, event.action[1], int(self.w.state)])

    def capture(self, name="workbench-desktop", widget=None):
        widget = widget or self.w
        QApplication.processEvents()
        path = self.output / f"{name}.png"
        widget.grab().save(str(path))
        self.report["captures"][name] = {"path": path.name, "width": widget.width(), "height": widget.height()}
        self.write_report()

    def initial_capture(self):
        self.capture()
        self.report["ready"] = True
        self.write_report()
        if not self.hold:
            self.run_native()

    def poll_commands(self):
        try:
            command = json.loads((self.output / "command.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return
        if command.get("id") == self.last_command:
            return
        self.last_command = command.get("id")
        action = command.get("action")
        if action == "capture":
            self.w.restore_workbench()
            self.w.resize(command.get("width", 1240), command.get("height", 790))
            QTimer.singleShot(250, lambda: self.capture(command.get("name", "workbench-desktop")))
        elif action == "capture-settings":
            self.w.restore_workbench()
            self.w.show_run_settings()
            QTimer.singleShot(250, lambda: self.capture("workbench-settings", self.w.settings_dialog))
        elif action == "capture-floating":
            self.w.restore_workbench()
            self.w.toggle_float_panel()
            QTimer.singleShot(250, lambda: self.capture("workbench-floating", self.w.floating_control))
        elif action == "settings":
            self.w.show_run_settings()
            QTimer.singleShot(250, lambda: self.capture("workbench-settings", self.w.settings_dialog))
        elif action == "floating":
            self.w.settings_dialog.hide()
            self.w.toggle_float_panel()
            QTimer.singleShot(250, lambda: self.capture("workbench-floating", self.w.floating_control))
        elif action == "restore":
            self.w.restore_workbench()
            self.w.settings_dialog.hide()
            self.w.show_page(0)
        elif action == "error":
            self.w.restore_workbench()
            self.error_flow()
        elif action == "native":
            self.run_native()
        elif action == "quit":
            self.w.close()
            QApplication.instance().quit()

    def error_flow(self):
        path = Path(self.temp.name) / "scripts" / "错误反馈验证.json5"
        path.write_text('{scripts:[{type:"sequence",events:[{type:"invalid"}]}]}', encoding="utf-8")
        self.w.refresh_scripts()
        self.w.choice_script.setCurrentText(path.name)
        self.w.OnBtrunButton()
        QTimer.singleShot(500, lambda: self.capture("workbench-script-error"))

    @staticmethod
    def key(code):
        win32api.keybd_event(code, 0, 0, 0)
        win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)

    def run_native(self):
        self.w.settings_dialog.hide()
        self.w.restore_workbench()
        self.w.show_page(0)
        self.target = CounterTarget()
        area = QApplication.primaryScreen().availableGeometry()
        self.target.move(area.right() - 315, area.bottom() - 195)
        self.target.show()
        self.target.raise_()
        self.saved_cursor = win32api.GetCursorPos()
        self.flow = self.native_flow()
        self.report["native_status"] = "running"
        self.write_report()
        QTimer.singleShot(200, self.advance)

    def advance(self):
        try:
            delay = next(self.flow)
            QTimer.singleShot(delay, self.advance)
        except StopIteration:
            self.report["native_status"] = "passed"
            self.finish_native()
        except Exception:
            self.report["native_status"] = "failed"
            self.report["native_error"] = traceback.format_exc()
            self.finish_native()

    def finish_native(self):
        self.report["diagnostics"] = {"keys": self.key_trace[-80:], "logs": self.w._logs[-30:],
                                      "state": int(self.w.state), "keys_down": list(self.w._keys_down),
                                      "target_events": self.target.events}
        if self.w.multiclick_thread:
            self.w.stop_multiclick()
        if self.w.runthread:
            self.w.stop_script()
        self.target.close()
        win32api.SetCursorPos(self.saved_cursor)
        self.write_report()
        if not self.hold:
            self.w.close()
            QApplication.instance().quit()

    def native_flow(self):
        center = logical_to_physical(self.target.mapToGlobal(self.target.rect().center()))
        x, y = center.x(), center.y()
        self.w.multiclick_profiles["安全验证"] = normalize_profile({"countdown": 0, "corner_stop": False})
        self.w._refresh_profile_list()
        self.w.load_selected_multiclick_profile("安全验证")
        self.w.add_click_point(x, y, name="专用计数器", click_type="Double")
        self.w.test_click_point_by_row(0)
        yield 100
        assert len(self.target.events) == 2, self.target.events
        self.report["checks"]["real_double_click"] = len(self.target.events)
        for key in ("Right", "Middle"):
            self.w.multiclick_points[0].button = key
            self.w.multiclick_points[0].click_type = "Single"
            self.w.test_click_point_by_row(0)
            yield 100
        assert len(self.target.events) == 4
        self.report["checks"]["real_right_and_middle_click"] = True

        self.w.multiclick_points[0].button = "Left"
        self.w.multiclick_points[0].interval_ms = 50
        self.w.multiclick_points[0].interval_min_ms = 50
        self.w.multiclick_points[0].interval_max_ms = 50
        self.w.current_multiclick_profile()["max_clicks"] = 3
        self.w._refresh_all()
        before = len(self.target.events)
        self.key(win32con.VK_F7)
        yield 350
        assert self.w.state == State.IDLE
        assert len(self.target.events) - before == 3, (before, self.target.events, self.w._logs)
        self.report["checks"]["global_f7_start_and_count_limit"] = True

        self.w.current_multiclick_profile()["max_clicks"] = 0
        self.w.multiclick_points[0].interval_min_ms = 60000
        self.w.multiclick_points[0].interval_max_ms = 60000
        self.w._refresh_all()
        self.key(win32con.VK_F7)
        yield 100
        assert self.w.multiclick_thread is not None
        self.key(win32con.VK_F7)
        yield 80
        assert self.w.multiclick_thread.pause_flag
        clicks = len(self.target.events)
        self.key(win32con.VK_F7)
        yield 60
        assert not self.w.multiclick_thread.pause_flag
        started = time.monotonic()
        self.key(win32con.VK_F8)
        while self.w.multiclick_thread and time.monotonic() - started < 1:
            yield 5
        latency = (time.monotonic() - started) * 1000
        assert self.w.multiclick_thread is None
        assert len(self.target.events) == clicks
        assert latency < 300
        self.report["checks"]["global_f7_pause_resume"] = True
        self.report["checks"]["global_f8_long_wait_stop_ms"] = round(latency, 1)

        self.w.current_multiclick_profile()["corner_stop"] = True
        self.w._refresh_all()
        self.key(win32con.VK_F7)
        yield 80
        self.key(win32con.VK_F7)
        yield 60
        assert self.w.multiclick_thread.pause_flag
        started = time.monotonic()
        win32api.SetCursorPos((0, 0))
        while self.w.multiclick_thread and time.monotonic() - started < 1:
            yield 5
        assert self.w.multiclick_thread is None
        self.report["checks"]["corner_stop_while_paused_ms"] = round((time.monotonic() - started) * 1000, 1)

        count = len(self.w.multiclick_points)
        self.w.pick_click_point()
        yield 80
        execute_click(ClickPoint(True, "采点", x, y, "Left", "Single", 1000))
        yield 120
        assert self.w.pick_overlay is None
        assert len(self.w.multiclick_points) == count + 1
        assert abs(self.w.multiclick_points[-1].x - x) < 3
        assert abs(self.w.multiclick_points[-1].y - y) < 3
        self.report["checks"]["real_screen_point_pick"] = True
        self.key(win32con.VK_F4)
        yield 100
        assert self.w.pick_overlay is not None
        self.key(win32con.VK_ESCAPE)
        yield 100
        assert self.w.pick_overlay is None
        self.report["checks"]["global_f4_stream_pick_and_escape"] = True

        self.key(win32con.VK_F10)
        yield 80
        assert self.w.state == State.RECORDING
        execute_click(ClickPoint(True, "录制", x, y, "Left", "Single", 1000))
        yield 100
        self.key(win32con.VK_F9)
        yield 100
        assert self.w.state == State.IDLE
        assert self.w.get_script_path()
        recorded = json5.loads(Path(self.w.get_script_path()).read_text(encoding="utf-8"))
        assert len(recorded["scripts"]) >= 2
        self.report["checks"]["real_record_and_save"] = len(recorded["scripts"])
        before = len(self.target.events)
        self.key(win32con.VK_F6)
        yield 500
        assert self.w.runthread is None
        assert not self.w.script_error_label.isVisible(), self.w.script_error_label.text()
        assert len(self.target.events) > before
        self.report["checks"]["real_recorded_script_replay"] = True
        self.error_flow()
        yield 350
        assert self.w.runthread is None
        assert "scripts[1].events[1]" in self.w.script_error_label.text()
        assert "失败" in self.w.script_status_label.text()
        assert self.w.btrun.isEnabled()
        self.report["checks"]["script_error_visible_and_state_restored"] = True
        self.capture("workbench-script-error")
        self.w.show_page(0)
        self.seed_demo()
        self.capture("workbench-desktop")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    verification = Verification(args.output, args.preview)
    sys.exit(app.exec())
