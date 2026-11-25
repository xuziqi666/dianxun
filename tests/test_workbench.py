import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

import json5
from UIFunc import UIFunc
from Event import ScriptEvent
import Recorder
from Util.Global import State
from Util.Profiles import normalize_profile


APP = QApplication.instance() or QApplication([])
APP.setStyle("Fusion")


def pump_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        QTest.qWait(5)
    APP.processEvents()
    if not predicate():
        raise AssertionError("界面未在限定时间内恢复预期状态")


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="点巡-test-")
        self.window = UIFunc(APP, data_dir=self.temp.name, enable_hooks=False)
        self.window.player.setVolume(0)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.close()
        APP.processEvents()
        self.temp.cleanup()

    def new_profile(self, name):
        with patch.object(QInputDialog, "getText", return_value=(name, True)):
            self.window.new_multiclick_profile()

    def test_empty_window_and_single_data_source(self):
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.point_stack.currentIndex(), 1)
        self.assertFalse(self.window.bt_multiclick_start.isEnabled())
        self.assertFalse(self.window.edit_point_name.isEnabled())
        self.assertFalse((Path(self.temp.name) / "config.ini").exists())

    def test_save_reload_and_switch_do_not_contaminate_profiles(self):
        first = self.window.current_multiclick_profile_name()
        self.window.add_click_point(-140, 250, name="第一方案右键", button="Right", click_type="Double",
                                    interval_min_ms=1200, interval_max_ms=1600)
        saved = copy.deepcopy(self.window.make_multiclick_profile())
        self.new_profile("第二方案")
        self.assertEqual(self.window.serialize_multiclick_points(), [])
        self.window.add_click_point(700, 800, enabled=False, name="第二方案点位")
        self.window.load_selected_multiclick_profile(first)
        self.assertEqual(self.window.make_multiclick_profile(), saved)
        settings = QSettings(str(Path(self.temp.name) / "config.ini"), QSettings.IniFormat)
        profiles = json5.loads(settings.value("Config/MultiClickProfiles"))
        self.assertEqual(profiles[first], saved)
        self.assertEqual(profiles["第二方案"]["points"][0]["x"], 700)
        self.window.close()
        self.window = UIFunc(APP, data_dir=self.temp.name, enable_hooks=False)
        self.window.player.setVolume(0)
        self.assertEqual(self.window.make_multiclick_profile(), saved)

    def test_inspector_selection_preserves_values_and_atomic_edit(self):
        self.window.add_click_point(100, 200, button="Right", click_type="Double", name="右键双击")
        self.window.add_click_point(300, 400, button="Middle", name="中键单击")
        self.window._select_workbench_point(0)
        self.assertEqual(self.window.choice_point_button.currentData(), "Right")
        self.assertEqual(self.window.choice_point_type.currentData(), "Double")
        self.window._select_workbench_point(1)
        self.assertEqual(self.window.multiclick_points[0].button, "Right")
        self.assertEqual(self.window.multiclick_points[0].click_type, "Double")
        self.window.edit_point_name.setText("已修改")
        self.window.spin_point_x.setValue(-50)
        self.window.spin_point_min.setValue(1400)
        self.window._apply_inspector_edits()
        point = self.window.multiclick_points[1]
        self.assertEqual((point.name, point.x, point.interval_min_ms, point.interval_max_ms),
                         ("已修改", -50, 1400, 1400))
        self.window.undo_multiclick_edit()
        self.assertEqual(self.window.multiclick_points[1].name, "中键单击")

    def test_copy_reorder_delete_and_undo(self):
        self.window.add_click_point(10, 20, name="A")
        self.window.duplicate_click_point()
        self.window.move_click_point(-1)
        self.assertEqual([point.name for point in self.window.multiclick_points], ["A 副本", "A"])
        self.window.delete_selected_click_point()
        self.assertEqual(len(self.window.multiclick_points), 1)
        self.window.undo_multiclick_edit()
        self.assertEqual(len(self.window.multiclick_points), 2)

    def test_export_import_duplicate_and_invalid_import(self):
        self.window.add_click_point(100, 200, name="本地点位")
        path = Path(self.temp.name) / "export.json5"
        self.assertTrue(self.window.export_multiclick_profile(path))
        original = self.window.active_profile_name
        self.assertTrue(self.window.import_multiclick_profile(path))
        self.assertEqual(self.window.active_profile_name, original + " (2)")
        before = copy.deepcopy(self.window.multiclick_profiles)
        path.write_text('{"points":[{"x":"oops"}]}', encoding="utf-8")
        self.assertFalse(self.window.import_multiclick_profile(path))
        self.assertEqual(self.window.multiclick_profiles, before)

    def test_disabled_point_is_saved_and_start_rejected(self):
        self.window.add_click_point(50, 60, name="停用点位")
        self.window._set_point_enabled(0, False)
        self.assertFalse(self.window.serialize_multiclick_points()[0]["enabled"])
        self.assertFalse(self.window.bt_multiclick_start.isEnabled())
        self.window.start_multiclick()
        self.assertIsNone(self.window.multiclick_thread)

    def test_single_and_double_test_execute_complete_pairs(self):
        self.window.add_click_point(300, 400, name="测试点", button="Middle", click_type="Double")
        events = []
        with patch("Util.MultiClickClass.ScriptEvent.execute", lambda event, context: (context.sleep(event.delay), events.append(copy.deepcopy(event.__dict__)))):
            self.assertTrue(self.window.test_click_point_by_row(0))
        self.assertEqual([event["action_type"] for event in events],
                         ["mouse middle down", "mouse middle up"] * 2)
        self.assertEqual(events[0]["action"], [300, 400])
        self.assertEqual(events[1]["action"], [-1, -1])
        self.assertEqual(self.window.state, State.IDLE)

    def test_test_error_is_visible_and_button_released(self):
        self.window.add_click_point(300, 400)
        events = []
        def execute(event, context):
            events.append(event.action_type)
            if event.action_type.endswith("down"):
                raise RuntimeError("模拟输入失败")
        with patch("Util.MultiClickClass.ScriptEvent.execute", execute):
            self.assertFalse(self.window.test_click_point_by_row(0))
        self.assertEqual(events, ["mouse left down", "mouse left up"])
        self.assertIn("失败", self.window.runtime_title.text())
        self.assertIn("模拟输入失败", self.window.runtime_detail.text())
        self.assertEqual(self.window.state, State.IDLE)

    def test_floating_controls_never_reparent_main_controls(self):
        self.window.add_click_point(100, 200)
        parent = self.window.bt_multiclick_start.parent()
        self.window.toggle_float_panel()
        APP.processEvents()
        self.assertIs(self.window.bt_multiclick_start.parent(), parent)
        self.assertIsNot(self.window.floating_control.start_button, self.window.bt_multiclick_start)
        self.window.restore_workbench()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.bt_multiclick_start.isVisible())

    def test_running_locks_configuration_and_stops_long_wait(self):
        self.window.add_click_point(500, 500, interval_ms=60000)
        profile = self.window.current_multiclick_profile()
        profile.update(countdown=0, corner_stop=False)
        with patch("Util.MultiClickClass.ScriptEvent.execute", lambda event, context: context.sleep(event.delay)):
            self.window.start_multiclick()
            pump_until(lambda: self.window.multiclick_thread.click_count >= 1)
            self.assertFalse(self.window.edit_point_name.isEnabled())
            self.assertFalse(self.window.choice_multiclick_mode.isEnabled())
            self.assertFalse(self.window.profile_list_widget.isEnabled())
            self.window.pause_multiclick()
            self.assertTrue(self.window.multiclick_thread.pause_flag)
            before = time.monotonic()
            self.window.stop_multiclick()
            pump_until(lambda: self.window.multiclick_thread is None)
        self.assertLess(time.monotonic() - before, 0.3)
        self.assertTrue(self.window.edit_point_name.isEnabled())
        self.assertEqual(self.window.state, State.IDLE)

    def test_empty_and_invalid_script_restore_state_with_error(self):
        self.window.OnBtrunButton()
        pump_until(lambda: self.window.runthread is None)
        self.assertEqual(self.window.state, State.IDLE)
        self.assertIn("未找到脚本", self.window.script_error_label.text())
        path = Path(self.temp.name) / "scripts" / "bad.json5"
        path.write_text('{scripts:[{type:"what"}]}', encoding="utf-8")
        self.window.refresh_scripts()
        self.window.OnBtrunButton()
        pump_until(lambda: self.window.runthread is None)
        self.assertIn("scripts[1]", self.window.script_error_label.text())
        self.assertIn("解析脚本失败", self.window.script_error_label.text())
        self.assertNotIn("已完成", self.window.script_status_label.text())
        self.assertTrue(self.window.btrun.isEnabled())

    def test_legacy_profile_boolean_migration(self):
        profile = normalize_profile({"corner_stop": "false", "points": [
            {"x": -10, "y": 20, "enabled": "false", "interval_ms": 900}]})
        self.assertFalse(profile["corner_stop"])
        self.assertFalse(profile["points"][0]["enabled"])
        self.assertEqual(profile["points"][0]["interval_min_ms"], 900)

    def test_rename_and_delete_persist(self):
        self.new_profile("将重命名")
        with patch.object(QInputDialog, "getText", return_value=("新名字", True)):
            self.window.rename_multiclick_profile()
        self.assertIn("新名字", self.window.multiclick_profiles)
        self.assertNotIn("将重命名", self.window.multiclick_profiles)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.window.delete_current_multiclick_profile()
        self.assertNotIn("新名字", self.window.multiclick_profiles)

    def test_normal_keyboard_combination_records_both_modifier_edges(self):
        self.window.recordMethod()
        modifier = Recorder.globals.key_combination_trigger[0]
        for kind, code, name in (("key down", 162, modifier), ("key down", 67, "C"),
                                 ("key up", 67, "C"), ("key up", 162, modifier)):
            self.window.on_record_event(ScriptEvent({"event_type": "EK", "action_type": kind,
                                                    "delay": 0, "action": [code, name, 0]}))
        self.assertEqual([item["action_type"] for item in self.window.record],
                         ["key down", "key down", "key up", "key up"])
        self.window.record = []
        self.window.recordMethod()

    def test_modified_stop_hotkey_is_excluded_from_recording(self):
        modifier = Recorder.globals.key_combination_trigger[0]
        self.window._hotkeys["script_stop"] = modifier + "+f9"
        self.window.recordMethod()
        for kind, code, name in (("key down", 162, modifier), ("key down", 120, "F9"),
                                 ("key up", 120, "F9"), ("key up", 162, modifier)):
            self.window.on_record_event(ScriptEvent({"event_type": "EK", "action_type": kind,
                                                    "delay": 0, "action": [code, name, 0]}))
        self.assertEqual(self.window.state, State.IDLE)
        self.assertEqual(self.window.record, [])


if __name__ == "__main__":
    unittest.main()
