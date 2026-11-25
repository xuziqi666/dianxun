import copy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json5
from loguru import logger
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QSpinBox, QWidget

from Plugin.Manager import PluginManager
from Util.MultiClickClass import ClickPoint, MultiClickClass
from Util.Parser import ScriptParser, parse_script
from Util.RunScriptClass import RunScriptClass

logger.remove()
APP = QApplication.instance() or QApplication([])


class Frame(QWidget):
    def __init__(self, path=""):
        super().__init__()
        self.path = str(path)
        self.stimes = QSpinBox()
        self.stimes.setValue(1)
        self.logs = []

    def get_script_path(self):
        return self.path

    def append_log(self, text):
        self.logs.append(text)

    def set_status(self, text):
        self.status = text

    def playtune(self, text):
        pass

    def show_multiclick_countdown(self, value):
        pass

    def update_multiclick_runtime(self, *args):
        pass


def point(name="A", interval=60000, enabled=True, click_type="Single"):
    return ClickPoint(enabled, name, 400, 500, "Left", click_type, interval, interval, interval)


def event(delay=0, action_type="mouse left down"):
    return {"type": "event", "delay": delay, "event_type": "EM", "action_type": action_type, "action": [400, 500]}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="点巡-execution-")
        self.frame = Frame()
        self.worker = None

    def tearDown(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)
        APP.processEvents()
        self.frame.close()
        self.temp.cleanup()

    def script(self, content, name="script.json5"):
        path = Path(self.temp.name) / name
        path.write_text(json5.dumps(content), encoding="utf-8")
        return path

    def start_multi(self, points=None, **kwargs):
        self.worker = MultiClickClass(self.frame, points or [point()], countdown_seconds=0,
                                      corner_stop=False, **kwargs)
        self.worker.start()

    def until(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            time.sleep(0.002)
        self.assertTrue(predicate())

    @patch("Util.MultiClickClass.ScriptEvent.execute", lambda e, c: c.sleep(e.delay))
    def test_max_clicks_does_not_wait_last_long_interval_in_all_modes(self):
        for mode in ("Sequential", "Random", "Parallel"):
            with self.subTest(mode=mode):
                self.start_multi(mode=mode, max_clicks=1)
                self.assertTrue(self.worker.wait(300))
                self.assertEqual(self.worker.click_count, 1)
                self.assertEqual(self.worker.outcome, "completed")

    @patch("Util.MultiClickClass.ScriptEvent.execute", lambda e, c: c.sleep(e.delay))
    def test_round_limit_counts_only_enabled_points(self):
        self.start_multi([point("A", 1), point("disabled", 1, False), point("B", 1)],
                         mode="Sequential", max_rounds=2)
        self.assertTrue(self.worker.wait(500))
        self.assertEqual(self.worker.click_count, 4)
        self.assertEqual(self.worker.message, "已完成 2 轮")

    @patch("Util.MultiClickClass.ScriptEvent.execute", lambda e, c: c.sleep(e.delay))
    def test_duration_expires_during_long_interval(self):
        started = time.monotonic()
        self.start_multi(mode="Sequential", max_duration_seconds=1)
        self.assertTrue(self.worker.wait(1500))
        self.assertLess(time.monotonic() - started, 1.4)
        self.assertEqual(self.worker.click_count, 1)
        self.assertIn("最长运行时间", self.worker.message)

    @patch("Util.MultiClickClass.ScriptEvent.execute", lambda e, c: c.sleep(e.delay))
    def test_pause_excludes_duration_and_stop_interrupts_pause(self):
        self.start_multi(mode="Sequential", max_duration_seconds=1)
        self.until(lambda: self.worker.click_count == 1)
        self.worker.set_pause(True)
        time.sleep(0.08)
        elapsed = self.worker.active_elapsed()
        time.sleep(0.08)
        self.assertAlmostEqual(self.worker.active_elapsed(), elapsed, delta=0.02)
        started = time.monotonic()
        self.worker.stop()
        self.assertTrue(self.worker.wait(250))
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(self.worker.outcome, "stopped")

    @patch("Util.MultiClickClass.ScriptEvent.execute", lambda e, c: c.sleep(e.delay))
    def test_corner_stop_while_paused(self):
        position = [QPoint(500, 500)]
        with patch("Util.MultiClickClass.QCursor.pos", lambda: position[0]):
            self.worker = MultiClickClass(self.frame, [point()], countdown_seconds=0, corner_stop=True, mode="Sequential")
            self.worker.start()
            self.until(lambda: self.worker.click_count == 1)
            self.worker.set_pause(True)
            position[0] = QPoint(0, 0)
            self.assertTrue(self.worker.wait(250))
        self.assertIn("左上角", self.worker.message)

    @patch("Util.MultiClickClass.ScriptEvent.execute", lambda e, c: c.sleep(e.delay))
    def test_corner_stop_during_long_interval(self):
        position = [QPoint(500, 500)]
        with patch("Util.MultiClickClass.QCursor.pos", lambda: position[0]):
            self.worker = MultiClickClass(self.frame, [point()], countdown_seconds=0, corner_stop=True, mode="Random")
            self.worker.start()
            self.until(lambda: self.worker.click_count == 1)
            position[0] = QPoint(0, 0)
            self.assertTrue(self.worker.wait(250))
        self.assertEqual(self.worker.click_count, 1)

    def test_countdown_stop_never_executes_click(self):
        seen = []
        with patch("Util.MultiClickClass.ScriptEvent.execute", lambda e, c: seen.append(e.action_type)):
            self.worker = MultiClickClass(self.frame, [point()], countdown_seconds=30, corner_stop=False)
            self.worker.start()
            time.sleep(0.04)
            self.worker.stop()
            self.assertTrue(self.worker.wait(250))
        self.assertEqual(seen, [])

    def test_multiclick_execution_failure_reports_failed(self):
        def execute(e, c):
            if e.action_type.endswith("down"):
                raise RuntimeError("input failed")
        with patch("Util.MultiClickClass.ScriptEvent.execute", execute):
            self.start_multi()
            self.assertTrue(self.worker.wait(300))
        self.assertEqual(self.worker.outcome, "failed")
        self.assertIn("input failed", self.worker.error_message)
        self.assertNotIn("已完成", self.worker.message)

    def test_parser_rejects_unknown_type_missing_goto_and_nested_invalid_event(self):
        for content, expected in (
            ({"scripts": [{"type": "oops"}]}, "scripts[1]"),
            ({"scripts": [{"type": "goto", "tolabel": "missing"}]}, "跳转目标不存在"),
            ({"scripts": [{"type": "sequence", "events": [event(delay=-1)]}]}, ".events[1]"),
            ({"scripts": []}, "没有可执行"),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected.replace("[", r"\[").replace("]", r"\]")):
                parse_script(self.script(content))

    def test_parser_preserves_order_and_does_not_mutate_source(self):
        content = {"scripts": [event(), {"type": "sequence", "events": [event(action_type="mouse left up")]}]}
        original = copy.deepcopy(content)
        head = ScriptParser.from_content(content)
        self.assertEqual(content, original)
        self.assertEqual(head.content["action_type"], "mouse left down")
        self.assertEqual(head.next_object.content["events"].content["action_type"], "mouse left up")

    def run_script(self, content, mock_execute=None):
        self.frame.path = str(self.script(content))
        self.worker = RunScriptClass(self.frame)
        execute = mock_execute or (lambda e, c: c.sleep(e.delay))
        with patch("Util.RunScriptClass.ScriptEvent.execute", execute):
            self.worker.start()
            self.assertTrue(self.worker.wait(1000))
        return self.worker

    def test_new_and_legacy_scripts_complete(self):
        for content in ({"scripts": [event(), event(action_type="mouse left up")]},
                        [[0, "EM", "mouse left down", [400, 500]], [0, "EM", "mouse left up", [-1, -1]]]):
            with self.subTest(content=content):
                worker = self.run_script(content)
                self.assertEqual(worker.outcome, "completed")

    def test_input_failure_and_plugin_failure_keep_object_location(self):
        def fail(event, context):
            raise RuntimeError("设备不可用")
        worker = self.run_script({"scripts": [event()]}, fail)
        self.assertEqual(worker.outcome, "failed")
        self.assertIn("scripts[1]", worker.error_message)
        self.assertIn("设备不可用", worker.error_message)
        worker = self.run_script({"scripts": [{"type": "custom", "call": ["missing_plugin"]}]})
        self.assertEqual(worker.outcome, "failed")
        self.assertIn("missing_plugin", worker.error_message)

    def test_script_stop_interrupts_event_delay_without_executing_down(self):
        self.frame.path = str(self.script({"scripts": [event(delay=60000)]}))
        self.worker = RunScriptClass(self.frame)
        seen = []
        def execute(e, context):
            context.sleep(e.delay)
            seen.append(e.action_type)
        with patch("Util.RunScriptClass.ScriptEvent.execute", execute):
            self.worker.start()
            time.sleep(0.04)
            self.worker.set_pause(True)
            self.worker.stop()
            self.assertTrue(self.worker.wait(250))
        self.assertNotIn("mouse left down", seen)
        self.assertEqual(self.worker.outcome, "stopped")

    def test_subroutine_relative_path_and_error_propagation(self):
        self.script({"scripts": [event(), event(action_type="mouse left up")]}, "child.json5")
        worker = self.run_script({"scripts": [{"type": "subroutine", "path": ["child.json5"]}]})
        self.assertEqual(worker.outcome, "completed")
        worker = self.run_script({"scripts": [{"type": "subroutine", "path": ["missing.json5"]}]})
        self.assertEqual(worker.outcome, "failed")
        self.assertIn("missing.json5", worker.error_message)


if __name__ == "__main__":
    unittest.main()
