# -*- coding: utf-8 -*-
"""点巡 workbench and recorder integration."""
import copy
import datetime
from pathlib import Path
import sys
from dataclasses import asdict, replace

import json5
from loguru import logger
from PySide6.QtCore import Qt, QSettings, QSignalBlocker, QSize, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSlider,
    QSpinBox, QVBoxLayout, QWidget,
)

import Recorder
from Event import ScriptEvent, flag_multiplemonitor
from Plugin.Manager import PluginManager
from UIWorkbench import (FloatingControlWindow, PointRow, WORKBENCH_STYLE,
                         build_workbench, button, field, icon, label)
from Util.Global import State
from Util.MultiClickClass import ClickPoint, MultiClickClass, execute_click
from Util.Profiles import normalize_point, normalize_profile
from Util.RunScriptClass import RunScriptClass
from Util.Screen import PickPointOverlay, PointMarkerOverlay, logical_to_physical


def to_abs_path(*paths):
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    return str(root.joinpath(*paths))


def get_assets_path(*paths):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return str(root.joinpath("assets", *paths))


scripts = []
scripts_map = {"current_index": 0, "choice_language": "简体中文"}


def update_script_map():
    scripts_map.update({name: index for index, name in enumerate(scripts)})


class UIFunc(QMainWindow):
    updateStateSignal = Signal(State)

    def __init__(self, app, data_dir=None, enable_hooks=True):
        super().__init__()
        self.app = app
        self.data_dir = Path(data_dir) if data_dir is not None else Path(to_abs_path())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = QSettings(str(self.data_dir / "config.ini"), QSettings.IniFormat)
        self.state = State.IDLE
        self.closing = False
        self.runthread = None
        self.multiclick_thread = None
        self.multiclick_stopping = False
        self.pick_overlay = None
        self.marker_overlay = None
        self.floating_control = None
        self._picking_restore_float = False
        self._selected_row = -1
        self._populating = False
        self._history = []
        self._logs = []
        self._keys_down = set()
        self._consumed_keys = set()
        self.keys_pool = []
        self.hotkey_set_btn = None
        self._hotkey_being_set = None
        self.record = []
        self.actioncount = 0
        self._hooks_enabled = enable_hooks
        self._load_errors = []
        self._hotkeys = {
            "script_start": str(self.config.value("Config/StartHotKey", "f6")).lower(),
            "script_stop": str(self.config.value("Config/StopHotKey", "f9")).lower(),
            "record": str(self.config.value("Config/RecordHotKey", "f10")).lower(),
            "multi_start": str(self.config.value("Config/MultiClickStartHotKey", "f7")).lower(),
            "multi_stop": str(self.config.value("Config/MultiClickStopHotKey", "f8")).lower(),
            "pick": str(self.config.value("Config/MultiClickPickHotKey", "f4")).lower(),
        }
        self._sync_hotkey_values()
        self.load_multiclick_profiles()
        self.multiclick_points = [ClickPoint(**point) for point in self.current_multiclick_profile()["points"]]
        self._selected_row = 0 if self.multiclick_points else -1
        build_workbench(self)
        self._build_script_page()
        self._build_settings_dialog()
        self._connect_workbench()
        self.player = QSoundEffect(self)
        self.player.setVolume(self.volumeSlider.value() / 100)
        self.volumeSlider.valueChanged.connect(lambda value: self.player.setVolume(value / 100))
        self._refresh_all()
        self.setWindowTitle("点巡")
        window_icon = get_assets_path("Mondrian.ico")
        self.setWindowIcon(QIcon(window_icon if Path(window_icon).exists() else to_abs_path("Mondrian.ico")))
        self.setFont(QFont("Microsoft YaHei UI", 9))
        self._configure_logging()
        PluginManager.reload()
        if enable_hooks:
            Recorder.setuphook()
            Recorder.set_callback(self.on_record_event)
            Recorder.set_cursor_pose_change(self.cursor_pos_change)
            Recorder.set_interval(self.mouse_move_interval_ms.value())
        for error in self._load_errors:
            self.append_log(error)
        if self._load_errors:
            self.set_status("部分方案未能加载", "；".join(self._load_errors), error=True)
        self._runtime_timer = QTimer(self)
        self._runtime_timer.setInterval(200)
        self._runtime_timer.timeout.connect(self._tick_runtime)
        self._runtime_timer.start()

    def _configure_logging(self):
        log_dir = self.data_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        self._log_sink = logger.add(str(log_dir / "{time:YYYY-MM-DD}.log"),
                                    rotation="20 MB", retention=10, level="INFO")

    def _connect_workbench(self):
        self.profile_list_widget.currentItemChanged.connect(self._on_profile_item_changed)
        self.point_list_widget.currentRowChanged.connect(self._on_workbench_point_selected)
        self.bt_profile_new.clicked.connect(self.new_multiclick_profile)
        self.bt_profile_import.clicked.connect(self.import_multiclick_profile)
        self.bt_workbench_export.clicked.connect(self.export_multiclick_profile)
        self.bt_multiclick_pick.clicked.connect(self.pick_click_point)
        self.bt_empty_add.clicked.connect(self.pick_click_point)
        self.bt_multiclick_mark.clicked.connect(self.show_point_markers)
        self.bt_inspector_test.clicked.connect(self.test_selected_click_point)
        self.bt_point_up.clicked.connect(lambda: self.move_click_point(-1))
        self.bt_point_down.clicked.connect(lambda: self.move_click_point(1))
        self.bt_point_copy.clicked.connect(self.duplicate_click_point)
        self.bt_point_delete.clicked.connect(self.delete_selected_click_point)
        self.bt_undo.clicked.connect(self.undo_multiclick_edit)
        self.bt_multiclick_start.clicked.connect(self.toggle_multiclick_start)
        self.bt_multiclick_stop.clicked.connect(self.stop_multiclick)
        self.bt_workbench_log.clicked.connect(self.show_multiclick_log)
        self.bt_workbench_float.clicked.connect(self.toggle_float_panel)
        self.bt_script_page.clicked.connect(lambda: self.show_page(1))
        self.bt_settings.clicked.connect(self.show_run_settings)
        self.bt_run_options.clicked.connect(self.show_run_settings)
        self.bt_help.clicked.connect(self.show_help)
        self.choice_multiclick_mode.activated.connect(self._change_mode)
        self.choice_run_limit.activated.connect(self._change_limit_type)
        self.spin_run_limit.editingFinished.connect(self._change_limit_value)
        for control in (self.edit_point_name, self.spin_point_x, self.spin_point_y,
                        self.spin_point_min, self.spin_point_max):
            control.editingFinished.connect(self._apply_inspector_edits)
        self.choice_point_button.activated.connect(self._apply_inspector_edits)
        self.choice_point_type.activated.connect(self._apply_inspector_edits)

        self.profile_menu = QMenu(self)
        for text, method in (("重命名方案", self.rename_multiclick_profile),
                             ("保存方案", self.save_current_multiclick_profile),
                             ("导出方案…", self.export_multiclick_profile),
                             ("删除方案", self.delete_current_multiclick_profile)):
            self.profile_menu.addAction(text, method)
        self.bt_profile_more.setMenu(self.profile_menu)
        point_menu = QMenu(self)
        point_menu.addAction("连续采点", self.start_stream_pick_points)
        point_menu.addAction("添加鼠标当前位置", self.add_current_click_point)
        point_menu.addAction("重新拾取选中点位", self.repick_click_point)
        self.bt_point_more.setMenu(point_menu)
        self._shortcuts = []
        for keys, method in (("Ctrl+S", self.save_current_multiclick_profile),
                             ("Ctrl+Z", self.undo_multiclick_edit),
                             ("Delete", self._delete_shortcut)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(method)
            self._shortcuts.append(shortcut)

    def _build_script_page(self):
        layout = QVBoxLayout(self.script_tab)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        header = QHBoxLayout()
        back = button("返回自动点击", "window")
        back.clicked.connect(lambda: self.show_page(0))
        header.addWidget(back)
        header.addWidget(label("脚本录制与运行", "inspectorTitle"))
        header.addStretch()
        layout.addLayout(header)
        layout.addWidget(label("录制鼠标与键盘操作，再按所选次数执行。", "mutedText"))
        fields = QHBoxLayout()
        self.choice_script = QComboBox()
        self.choice_script.setMinimumWidth(200)
        self.refresh_scripts()
        self.stimes = QSpinBox()
        self.stimes.setRange(0, 99999)
        self.stimes.setValue(int(self.config.value("Config/LoopTimes", 1)))
        self.stimes.setSpecialValueText("无限循环")
        self.mouse_move_interval_ms = QSpinBox()
        self.mouse_move_interval_ms.setRange(1, 1000)
        self.mouse_move_interval_ms.setValue(int(self.config.value("Config/Precision", 200)))
        self.mouse_move_interval_ms.setSuffix(" ms")
        self.bt_open_script_files = button("管理脚本")
        self.bt_refresh_scripts = button("刷新列表")
        fields.addWidget(field("脚本", self.choice_script), 2)
        fields.addWidget(field("执行次数 · 0 为无限", self.stimes), 1)
        fields.addWidget(field("录制鼠标轨迹间隔", self.mouse_move_interval_ms), 1)
        fields.addWidget(self.bt_open_script_files, 0, Qt.AlignBottom)
        fields.addWidget(self.bt_refresh_scripts, 0, Qt.AlignBottom)
        layout.addLayout(fields)
        actions = QHBoxLayout()
        self.btrecord = button("开始录制  F10", "mouse")
        self.btpauserecord = button("暂停录制", "pause")
        self.btrun = button("运行脚本  F6", "play", "primaryButton")
        self.bt_script_stop = button("停止  F9", "stop", "dangerButton")
        for control in (self.btrecord, self.btpauserecord, self.btrun, self.bt_script_stop):
            actions.addWidget(control)
        actions.addStretch()
        actions.addWidget(label("提示音", "fieldLabel"))
        self.volumeSlider = QSlider(Qt.Horizontal)
        self.volumeSlider.setRange(0, 100)
        self.volumeSlider.setFixedWidth(90)
        self.volumeSlider.setValue(50)
        actions.addWidget(self.volumeSlider)
        layout.addLayout(actions)
        self.script_status_label = label("请选择脚本，或录制一组操作。", "runtimeTitle")
        self.script_error_label = label("", "errorMessage")
        self.script_error_label.setWordWrap(True)
        self.script_error_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.script_error_label.hide()
        layout.addWidget(self.script_status_label)
        layout.addWidget(self.script_error_label)
        self.textlog = QPlainTextEdit()
        self.textlog.setReadOnly(True)
        self.textlog.setPlaceholderText("运行过程与具体错误会显示在这里")
        self.textlog.document().setMaximumBlockCount(2000)
        layout.addWidget(self.textlog, 1)
        self.label_cursor_pos = label("鼠标位置：—", "mutedText")
        layout.addWidget(self.label_cursor_pos)
        self.btrecord.clicked.connect(self.OnBtrecordButton)
        self.btpauserecord.clicked.connect(self.pauseRecordMethod)
        self.btrun.clicked.connect(self.OnBtrunButton)
        self.bt_script_stop.clicked.connect(self.stop_script)
        self.bt_open_script_files.clicked.connect(self.OnBtOpenScriptFilesButton)
        self.bt_refresh_scripts.clicked.connect(self.refresh_scripts)
        self.stimes.valueChanged.connect(self._save_script_config)
        self.choice_script.currentTextChanged.connect(self._save_script_config)
        self.mouse_move_interval_ms.valueChanged.connect(self._save_script_config)
        self.mouse_move_interval_ms.valueChanged.connect(Recorder.set_interval)

    def _build_settings_dialog(self):
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("快捷键与运行设置")
        self.settings_dialog.setMinimumWidth(420)
        layout = QVBoxLayout(self.settings_dialog)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(13)
        layout.addWidget(label("运行设置", "inspectorTitle"))
        form = QFormLayout()
        self.spin_countdown = QSpinBox()
        self.spin_countdown.setRange(0, 60)
        self.spin_countdown.setSuffix(" 秒")
        self.spin_max_duration = QSpinBox()
        self.spin_max_duration.setRange(0, 86400)
        self.spin_max_duration.setSuffix(" 秒")
        self.spin_max_duration.setSpecialValueText("不限")
        self.spin_max_clicks = QSpinBox()
        self.spin_max_clicks.setRange(0, 9999999)
        self.spin_max_clicks.setSpecialValueText("不限")
        self.spin_max_rounds = QSpinBox()
        self.spin_max_rounds.setRange(0, 9999999)
        self.spin_max_rounds.setSpecialValueText("不限")
        self.check_corner_stop = QCheckBox("鼠标移到屏幕左上角时停止")
        form.addRow("启动前倒计时", self.spin_countdown)
        form.addRow("最长运行", self.spin_max_duration)
        form.addRow("最多点击动作", self.spin_max_clicks)
        form.addRow("最多轮数", self.spin_max_rounds)
        form.addRow("", self.check_corner_stop)
        layout.addLayout(form)
        note = label("多个结束条件同时设置时，达到任意一项即结束。暂停期间不计入运行时长。", "smallNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(label("全局快捷键 · 点击按钮后按新组合键", "sectionLabel"))
        hotkeys = QFormLayout()
        self.hotkey_buttons = {}
        for key, caption in (("multi_start", "自动点击：开始 / 暂停"), ("multi_stop", "停止任务"),
                             ("pick", "连续采点"), ("script_start", "脚本：运行 / 暂停"),
                             ("script_stop", "停止脚本"), ("record", "录制 / 暂停录制")):
            control = button(self._hotkeys[key].upper())
            control.clicked.connect(lambda checked=False, k=key: self.OnHotkeyButton(self.hotkey_buttons[k], k))
            self.hotkey_buttons[key] = control
            hotkeys.addRow(caption, control)
        self.hotkey_start = self.hotkey_buttons["script_start"]
        self.hotkey_stop = self.hotkey_buttons["script_stop"]
        self.hotkey_record = self.hotkey_buttons["record"]
        self.hotkey_multiclick_start = self.hotkey_buttons["multi_start"]
        self.hotkey_multiclick_stop = self.hotkey_buttons["multi_stop"]
        layout.addLayout(hotkeys)
        self.hotkey_hint = label("Esc 可取消正在设置的快捷键。", "smallNote")
        self.hotkey_hint.setWordWrap(True)
        layout.addWidget(self.hotkey_hint)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText("完成")
        close.rejected.connect(self.settings_dialog.close)
        layout.addWidget(close)
        self.settings_dialog.finished.connect(self._cancel_hotkey_setting)
        for spin in (self.spin_countdown, self.spin_max_duration,
                     self.spin_max_clicks, self.spin_max_rounds):
            spin.editingFinished.connect(self._apply_run_settings)
        self.check_corner_stop.clicked.connect(self._apply_run_settings)

    def load_multiclick_profiles(self):
        raw = self.config.value("Config/MultiClickProfiles", "")
        self.multiclick_profiles = {}
        try:
            loaded = json5.loads(raw) if raw else {}
            if not isinstance(loaded, dict):
                raise ValueError("方案集合需要是一个对象")
            for name, profile in loaded.items():
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("方案名称不能为空")
                self.multiclick_profiles[name] = normalize_profile(profile)
        except (ValueError, TypeError) as exc:
            self._load_errors.append(f"读取本地方案失败：{exc}；原配置已保留。")
        if not self.multiclick_profiles:
            try:
                points = json5.loads(self.config.value("Config/MultiClickPoints", "[]"))
                legacy = {
                    "mode": self.config.value("Config/MultiClickMode", "Sequential"),
                    "countdown": self.config.value("Config/MultiClickCountdown", 3),
                    "max_duration": self.config.value("Config/MultiClickMaxDuration", 0),
                    "max_clicks": self.config.value("Config/MultiClickMaxClicks", 0),
                    "max_rounds": self.config.value("Config/MultiClickMaxRounds", 0),
                    "corner_stop": self.config.value("Config/MultiClickCornerStop", True),
                    "points": points,
                }
                self.multiclick_profiles["默认方案"] = normalize_profile(legacy)
            except (ValueError, TypeError) as exc:
                self._load_errors.append(f"读取旧点位失败：{exc}；原配置已保留。")
                self.multiclick_profiles["默认方案"] = normalize_profile({})
        requested = self.config.value("Config/MultiClickProfile", "默认方案")
        self.active_profile_name = requested if requested in self.multiclick_profiles else next(iter(self.multiclick_profiles))

    def current_multiclick_profile_name(self):
        return self.active_profile_name

    def current_multiclick_profile(self):
        return self.multiclick_profiles[self.active_profile_name]

    def serialize_multiclick_points(self):
        return [asdict(point) for point in self.multiclick_points]

    def make_multiclick_profile(self):
        profile = copy.deepcopy(self.current_multiclick_profile())
        profile["points"] = self.serialize_multiclick_points()
        return normalize_profile(profile)

    def collect_multiclick_points(self):
        return [replace(point) for point in self.multiclick_points]

    def multiclick_points_valid(self):
        try:
            self.make_multiclick_profile()
            return True
        except (ValueError, TypeError) as exc:
            self.set_status("点位配置无效", str(exc), error=True)
            return False

    def _save_profiles(self):
        self.config.setValue("Config/MultiClickProfiles", json5.dumps(self.multiclick_profiles, ensure_ascii=False))
        self.config.setValue("Config/MultiClickProfile", self.active_profile_name)
        profile = self.current_multiclick_profile()
        for name, key in (("mode", "Mode"), ("countdown", "Countdown"), ("max_duration", "MaxDuration"),
                          ("max_clicks", "MaxClicks"), ("max_rounds", "MaxRounds"), ("corner_stop", "CornerStop")):
            self.config.setValue(f"Config/MultiClick{key}", profile[name])
        self.config.setValue("Config/MultiClickPoints", json5.dumps(profile["points"], ensure_ascii=False))
        self.config.sync()
        success = self.config.status() == QSettings.NoError
        self.save_status_label.setText("✓ 已保存" if success else "保存失败")
        if not success:
            self.set_status("方案保存失败", "无法写入 config.ini，请检查目录是否可写。", error=True)
            self.append_log("方案保存失败：config.ini 无法写入")
        return success

    def save_current_multiclick_profile(self):
        if self.state != State.IDLE or self.pick_overlay:
            return False
        try:
            self.multiclick_profiles[self.active_profile_name] = self.make_multiclick_profile()
        except (ValueError, TypeError) as exc:
            self.set_status("方案未保存", str(exc), error=True)
            return False
        return self._save_profiles()

    def onconfigchange(self, *args):
        if self.state == State.IDLE and not self._populating:
            self.save_current_multiclick_profile()

    def _remember(self):
        self._history.append(self.make_multiclick_profile())
        self._history = self._history[-30:]

    def _commit_points(self):
        self.multiclick_profiles[self.active_profile_name]["points"] = self.serialize_multiclick_points()
        saved = self._save_profiles()
        self._refresh_all(reset_status=True)
        if not saved:
            self.set_status("方案保存失败", "当前修改尚未写入磁盘", error=True)

    def _refresh_all(self, reset_status=False):
        self._refresh_profile_list()
        self._refresh_workbench_points()
        self._populate_point_inspector()
        self._refresh_run_options()
        self._update_controls()
        if reset_status or self.runtime_title.text() == "等待添加点位":
            self._show_ready_status()

    def _refresh_profile_list(self):
        blocker = QSignalBlocker(self.profile_list_widget)
        self.profile_list_widget.clear()
        for name, profile in self.multiclick_profiles.items():
            count = len(profile["points"])
            item = QListWidgetItem(icon("copy"), f"{name}    {count or '—'}")
            item.setData(Qt.UserRole, name)
            item.setToolTip(name)
            self.profile_list_widget.addItem(item)
            if name == self.active_profile_name:
                self.profile_list_widget.setCurrentItem(item)
        del blocker
        self.workbench_task_title.setText(self.active_profile_name)
        self.workbench_task_title.setToolTip(self.active_profile_name)
        self.profile_list_widget.setMaximumHeight(max(105, min(330, len(self.multiclick_profiles) * 48 + 4)))

    def _refresh_workbench_points(self):
        blocker = QSignalBlocker(self.point_list_widget)
        scroll = self.point_list_widget.verticalScrollBar().value()
        self.point_list_widget.clear()
        for index, point in enumerate(self.multiclick_points):
            item = QListWidgetItem()
            item.setSizeHint(QSize(100, 76))
            self.point_list_widget.addItem(item)
            row = PointRow(index, point)
            row.selected.connect(self._select_workbench_point)
            row.enabledChanged.connect(self._set_point_enabled)
            row.testRequested.connect(self.test_click_point_by_row)
            row.set_locked(self.state != State.IDLE or bool(self.pick_overlay))
            self.point_list_widget.setItemWidget(item, row)
        self.point_list_widget.setCurrentRow(self._selected_row)
        self.point_list_widget.verticalScrollBar().setValue(scroll)
        del blocker
        self.point_stack.setCurrentIndex(0 if self.multiclick_points else 1)
        self.workbench_point_count.setText(f"点位 / 坐标 · {len(self.multiclick_points)} 个")

    def _on_profile_item_changed(self, current, previous):
        if not current or self.state != State.IDLE:
            return
        name = current.data(Qt.UserRole)
        if name == self.active_profile_name:
            return
        self.active_profile_name = name
        self.multiclick_points = [ClickPoint(**point) for point in self.current_multiclick_profile()["points"]]
        self._selected_row = 0 if self.multiclick_points else -1
        self._history.clear()
        self._save_profiles()
        self._refresh_all(reset_status=True)

    def load_selected_multiclick_profile(self, name):
        if name not in self.multiclick_profiles:
            return
        for index in range(self.profile_list_widget.count()):
            item = self.profile_list_widget.item(index)
            if item.data(Qt.UserRole) == name:
                self.profile_list_widget.setCurrentItem(item)
                break

    def _select_workbench_point(self, row):
        self.point_list_widget.setCurrentRow(row)

    def _on_workbench_point_selected(self, row):
        self._selected_row = row if 0 <= row < len(self.multiclick_points) else -1
        self._populate_point_inspector()

    def _populate_point_inspector(self):
        controls = (self.edit_point_name, self.spin_point_x, self.spin_point_y,
                    self.choice_point_button, self.choice_point_type, self.spin_point_min, self.spin_point_max)
        blockers = [QSignalBlocker(control) for control in controls]
        valid = 0 <= self._selected_row < len(self.multiclick_points)
        point = self.multiclick_points[self._selected_row] if valid else None
        self.inspector_badge.setText(f"{self._selected_row + 1:02d}" if valid else "—")
        self.edit_point_name.setText(point.name if point else "")
        self.spin_point_x.setValue(point.x if point else 0)
        self.spin_point_y.setValue(point.y if point else 0)
        self.choice_point_button.setCurrentIndex(self.choice_point_button.findData(point.button if point else "Left"))
        self.choice_point_type.setCurrentIndex(self.choice_point_type.findData(point.click_type if point else "Single"))
        self.spin_point_min.setValue((point.interval_min_ms or point.interval_ms) if point else 1000)
        self.spin_point_max.setValue((point.interval_max_ms or point.interval_ms) if point else 1000)
        self.target_preview.set_point(point)
        del blockers
        self._update_controls()

    def _apply_inspector_edits(self, *args):
        if self._populating or self.state != State.IDLE or self.pick_overlay or self._selected_row < 0:
            return
        point = self.multiclick_points[self._selected_row]
        low, high = self.spin_point_min.value(), self.spin_point_max.value()
        if low > high:
            if self.sender() is self.spin_point_max:
                low = high
            else:
                high = low
        try:
            data = normalize_point({
                **asdict(point), "name": self.edit_point_name.text(),
                "x": self.spin_point_x.value(), "y": self.spin_point_y.value(),
                "button": self.choice_point_button.currentData(),
                "click_type": self.choice_point_type.currentData(),
                "interval_ms": low, "interval_min_ms": low, "interval_max_ms": high,
            }, self._selected_row + 1)
        except ValueError as exc:
            self._populate_point_inspector()
            self.set_status("点位未修改", str(exc), error=True)
            return
        if data == asdict(point):
            return
        self._remember()
        self.multiclick_points[self._selected_row] = ClickPoint(**data)
        self._commit_points()

    def _set_point_enabled(self, row, enabled):
        if self.state != State.IDLE or self.pick_overlay:
            return
        self._remember()
        self.multiclick_points[row].enabled = enabled
        self._selected_row = row
        self._commit_points()

    def add_click_point(self, x, y, button="Left", click_type="Single", interval_ms=1000,
                        enabled=True, name="", interval_min_ms=0, interval_max_ms=0, save=True):
        if self.state != State.IDLE:
            return False
        try:
            data = normalize_point({
                "x": x, "y": y, "button": button, "click_type": click_type,
                "interval_ms": interval_ms, "enabled": enabled,
                "name": name or f"点位 {len(self.multiclick_points) + 1}",
                "interval_min_ms": interval_min_ms, "interval_max_ms": interval_max_ms,
            }, len(self.multiclick_points) + 1)
        except ValueError as exc:
            self.set_status("无法添加点位", str(exc), error=True)
            return False
        self._remember()
        self.multiclick_points.append(ClickPoint(**data))
        self._selected_row = len(self.multiclick_points) - 1
        if save:
            self._commit_points()
        return True

    def add_current_click_point(self):
        from PySide6.QtGui import QCursor
        pos = logical_to_physical(QCursor.pos())
        self.add_click_point(pos.x(), pos.y())

    def move_click_point(self, delta):
        row, target = self._selected_row, self._selected_row + delta
        if self.state != State.IDLE or row < 0 or not 0 <= target < len(self.multiclick_points):
            return
        self._remember()
        self.multiclick_points[row], self.multiclick_points[target] = self.multiclick_points[target], self.multiclick_points[row]
        self._selected_row = target
        self._commit_points()

    def duplicate_click_point(self):
        if self.state != State.IDLE or self._selected_row < 0:
            return
        self._remember()
        point = replace(self.multiclick_points[self._selected_row])
        point.name += " 副本"
        self._selected_row += 1
        self.multiclick_points.insert(self._selected_row, point)
        self._commit_points()

    def delete_selected_click_point(self):
        if self.state != State.IDLE or self._selected_row < 0:
            return
        self._remember()
        self.multiclick_points.pop(self._selected_row)
        self._selected_row = min(self._selected_row, len(self.multiclick_points) - 1)
        self._commit_points()

    def _delete_shortcut(self):
        if self.pages.currentIndex() == 0 and not isinstance(QApplication.focusWidget(), (QLineEdit, QSpinBox)):
            self.delete_selected_click_point()

    def undo_multiclick_edit(self):
        if self.state != State.IDLE or self.pick_overlay or not self._history:
            return
        profile = self._history.pop()
        self.multiclick_profiles[self.active_profile_name] = profile
        self.multiclick_points = [ClickPoint(**point) for point in profile["points"]]
        self._selected_row = min(max(0, self._selected_row), len(self.multiclick_points) - 1)
        self._save_profiles()
        self._refresh_all(reset_status=True)

    def new_multiclick_profile(self):
        if self.state != State.IDLE:
            return
        name, accepted = QInputDialog.getText(self, "新建方案", "方案名称：")
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.multiclick_profiles:
            self.set_status("方案名称已存在", "请使用另一个名称。", error=True)
            return
        self.multiclick_profiles[name] = normalize_profile({})
        self._refresh_profile_list()
        self.load_selected_multiclick_profile(name)

    def rename_multiclick_profile(self):
        old = self.active_profile_name
        name, accepted = QInputDialog.getText(self, "重命名方案", "方案名称：", text=old)
        name = name.strip()
        if not accepted or not name or name == old or self.state != State.IDLE:
            return
        if name in self.multiclick_profiles:
            self.set_status("方案名称已存在", "请使用另一个名称。", error=True)
            return
        self.multiclick_profiles = {name if key == old else key: value for key, value in self.multiclick_profiles.items()}
        self.active_profile_name = name
        self._save_profiles()
        self._refresh_profile_list()

    def delete_current_multiclick_profile(self):
        if self.state != State.IDLE:
            return
        answer = QMessageBox.question(self, "删除方案", f"删除“{self.active_profile_name}”及其点位？",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.multiclick_profiles.pop(self.active_profile_name)
        if not self.multiclick_profiles:
            self.multiclick_profiles["默认方案"] = normalize_profile({})
        self.active_profile_name = next(iter(self.multiclick_profiles))
        self.multiclick_points = [ClickPoint(**point) for point in self.current_multiclick_profile()["points"]]
        self._selected_row = 0 if self.multiclick_points else -1
        self._history.clear()
        self._save_profiles()
        self._refresh_all(reset_status=True)

    def import_multiclick_profile(self, path=None):
        if self.state != State.IDLE:
            return False
        if not isinstance(path, (str, Path)):
            path, _ = QFileDialog.getOpenFileName(self, "导入方案", "", "方案文件 (*.json *.json5)")
        if not path:
            return False
        try:
            with open(path, encoding="utf-8-sig") as file:
                data = json5.load(file)
            if not isinstance(data, dict):
                raise ValueError("方案文件需要是一个对象")
            profile = normalize_profile(data.get("profile", data))
            base = data.get("name", Path(path).stem)
            if not isinstance(base, str) or not base.strip():
                raise ValueError("方案名称不能为空")
            name = base.strip()
            index = 2
            while name in self.multiclick_profiles:
                name = f"{base.strip()} ({index})"
                index += 1
        except (OSError, ValueError, TypeError) as exc:
            self.append_log(f"导入方案失败：{exc}")
            self.set_status("导入方案失败", str(exc), error=True)
            return False
        self.multiclick_profiles[name] = profile
        self._refresh_profile_list()
        self.load_selected_multiclick_profile(name)
        self.set_status("方案已导入", name)
        return True

    def export_multiclick_profile(self, path=None):
        if not self.save_current_multiclick_profile():
            return False
        if not isinstance(path, (str, Path)):
            path, _ = QFileDialog.getSaveFileName(self, "导出方案", f"{self.active_profile_name}.json5", "方案文件 (*.json *.json5)")
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8") as file:
                json5.dump({"name": self.active_profile_name, "profile": self.make_multiclick_profile()},
                           file, ensure_ascii=False, indent=2)
        except (OSError, ValueError) as exc:
            self.set_status("导出方案失败", str(exc), error=True)
            self.append_log(f"导出方案失败：{exc}")
            return False
        self.set_status("方案已导出", str(path))
        return True

    def _refresh_run_options(self):
        self._populating = True
        profile = self.current_multiclick_profile()
        self.choice_multiclick_mode.setCurrentIndex(self.choice_multiclick_mode.findData(profile["mode"]))
        limits = [(key, profile[key]) for key in ("max_rounds", "max_clicks", "max_duration") if profile[key]]
        kind = {"max_rounds": "rounds", "max_clicks": "clicks", "max_duration": "duration"}
        key = kind[limits[0][0]] if len(limits) == 1 else "custom" if limits else "none"
        self.choice_run_limit.setCurrentIndex(self.choice_run_limit.findData(key))
        self.spin_run_limit.setVisible(key not in ("none", "custom"))
        self.spin_run_limit.setMaximum(86400 if key == "duration" else 9999999)
        self.spin_run_limit.setSuffix({"rounds": " 轮", "clicks": " 次", "duration": " 秒"}.get(key, ""))
        if limits:
            self.spin_run_limit.setValue(limits[0][1])
        for control, profile_key in ((self.spin_countdown, "countdown"), (self.spin_max_duration, "max_duration"),
                                     (self.spin_max_clicks, "max_clicks"), (self.spin_max_rounds, "max_rounds")):
            control.setValue(profile[profile_key])
        self.check_corner_stop.setChecked(profile["corner_stop"])
        self._populating = False

    def _change_mode(self, *args):
        if self.state != State.IDLE:
            return
        self._remember()
        self.current_multiclick_profile()["mode"] = self.choice_multiclick_mode.currentData()
        self._save_profiles()
        self._update_controls()

    def _change_limit_type(self, *args):
        if self.state != State.IDLE:
            return
        kind = self.choice_run_limit.currentData()
        if kind == "custom":
            self.show_run_settings()
            self._refresh_run_options()
            return
        self._remember()
        profile = self.current_multiclick_profile()
        for key in ("max_rounds", "max_clicks", "max_duration"):
            profile[key] = 0
        key = {"rounds": "max_rounds", "clicks": "max_clicks", "duration": "max_duration"}.get(kind)
        if key:
            profile[key] = 20 if kind == "rounds" else 100 if kind == "clicks" else 60
        self._save_profiles()
        self._refresh_run_options()
        self._show_ready_status()

    def _change_limit_value(self):
        if self._populating or self.state != State.IDLE:
            return
        key = {"rounds": "max_rounds", "clicks": "max_clicks", "duration": "max_duration"}.get(self.choice_run_limit.currentData())
        if key and self.current_multiclick_profile()[key] != self.spin_run_limit.value():
            self._remember()
            self.current_multiclick_profile()[key] = self.spin_run_limit.value()
            self._save_profiles()
            self._refresh_run_options()

    def _apply_run_settings(self):
        if self._populating or self.state != State.IDLE:
            return
        profile = self.current_multiclick_profile()
        edited = {"countdown": self.spin_countdown.value(), "max_duration": self.spin_max_duration.value(),
                  "max_clicks": self.spin_max_clicks.value(), "max_rounds": self.spin_max_rounds.value(),
                  "corner_stop": self.check_corner_stop.isChecked()}
        if all(profile[key] == value for key, value in edited.items()):
            return
        self._remember()
        profile.update(edited)
        self._save_profiles()
        self._refresh_run_options()
        self._show_ready_status()

    def show_run_settings(self):
        if self.state != State.IDLE:
            return
        self._refresh_run_options()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def pick_click_point(self):
        self._start_pick(False)

    def start_stream_pick_points(self):
        self._start_pick(True)

    def repick_click_point(self):
        if self._selected_row >= 0:
            self._start_pick(False, self._selected_row)

    def _start_pick(self, stream, replace_row=None):
        if self.state != State.IDLE or self.pick_overlay:
            return
        self._picking_restore_float = bool(self.floating_control and self.floating_control.isVisible())
        message = "连续采点：单击添加位置 · Esc 结束" if stream else "单击选择目标位置 · Esc 取消"
        self.pick_overlay = PickPointOverlay(stream_mode=stream, message=message)
        self.pick_overlay.pointPicked.connect(
            lambda x, y: self._picked_point(x, y, replace_row))
        self.pick_overlay.finished.connect(self._finish_pick)
        self.pick_overlay.show()
        self.pick_overlay.raise_()
        self.pick_overlay.activateWindow()
        self.hide()
        if self.floating_control:
            self.floating_control.hide()
        self._update_controls()

    def _picked_point(self, x, y, replace_row):
        if replace_row is not None and replace_row < len(self.multiclick_points):
            self._remember()
            self.multiclick_points[replace_row].x = x
            self.multiclick_points[replace_row].y = y
            self._selected_row = replace_row
            self._commit_points()
        else:
            self.add_click_point(x, y)

    def _finish_pick(self):
        overlay = self.pick_overlay
        self.pick_overlay = None
        if overlay:
            overlay.deleteLater()
        if not self.closing:
            if self._picking_restore_float:
                self.floating_control.show()
                self.floating_control.raise_()
            else:
                self.show()
                self.raise_()
                self.activateWindow()
        self._update_controls()

    def show_point_markers(self):
        if not self.multiclick_points:
            self.set_status("等待添加点位", "添加点位后即可预览屏幕标记。")
            return
        if self.marker_overlay:
            self.marker_overlay.close()
            self.marker_overlay.deleteLater()
        self.marker_overlay = PointMarkerOverlay(self.collect_multiclick_points())
        self.marker_overlay.show()
        QTimer.singleShot(2500, self._close_point_markers)

    def _close_point_markers(self):
        if self.marker_overlay:
            self.marker_overlay.close()
            self.marker_overlay.deleteLater()
            self.marker_overlay = None

    def test_selected_click_point(self):
        self.test_click_point_by_row(self._selected_row)

    def test_click_point_by_row(self, row):
        if self.state != State.IDLE or self.pick_overlay:
            return False
        if not 0 <= row < len(self.multiclick_points):
            self.set_status("请先选择一个点位")
            return False
        self._select_workbench_point(row)
        point = self.multiclick_points[row]
        try:
            self.execute_single_click(point)
        except Exception as exc:
            logger.exception("Point test failed")
            self.set_status("点位测试失败", str(exc), error=True)
            self.append_log(f"点位测试失败 · {point.name}：{exc}")
            return False
        self.set_status(f"测试完成 · {point.name}", f"坐标 {point.x}, {point.y}")
        self.append_log(f"点位测试完成 · {point.name} · {point.button}/{point.click_type} · ({point.x}, {point.y})")
        return True

    def execute_single_click(self, point):
        return execute_click(point)

    def toggle_multiclick_start(self):
        if self.state == State.IDLE:
            self.start_multiclick()
        elif self.state == State.MULTI_RUNNING:
            self.pause_multiclick()

    def start_multiclick(self):
        if self.state != State.IDLE or self.pick_overlay or self.multiclick_thread:
            return
        self._apply_inspector_edits()
        if not any(point.enabled for point in self.multiclick_points):
            self.set_status("没有启用的点位", "启用至少一个点位后即可开始。")
            return
        if not self.save_current_multiclick_profile():
            return
        profile = self.current_multiclick_profile()
        self.multiclick_stopping = False
        self.multiclick_thread = MultiClickClass(
            self, self.collect_multiclick_points(), mode=profile["mode"],
            countdown_seconds=profile["countdown"], max_duration_seconds=profile["max_duration"],
            max_clicks=profile["max_clicks"], max_rounds=profile["max_rounds"], corner_stop=profile["corner_stop"])
        self.multiclick_thread.finished.connect(self.handle_multiclick_status)
        self._last_point_label = "等待开始"
        self.update_state(State.MULTI_RUNNING)
        self.set_status("准备开始", f"即将执行 {self.active_profile_name}")
        self.multiclick_thread.start()

    def pause_multiclick(self):
        if not self.multiclick_thread or self.multiclick_stopping:
            return
        self.multiclick_thread.toggle_pause()
        self.set_status("已暂停" if self.multiclick_thread.pause_flag else "正在运行")
        self._update_controls()

    def stop_multiclick(self):
        if self.multiclick_thread:
            self.multiclick_stopping = True
            self.multiclick_thread.stop()
            self.set_status("正在停止…")
            self._update_controls()

    @Slot()
    def handle_multiclick_status(self):
        thread = self.multiclick_thread
        if thread is None:
            return
        self.multiclick_thread = None
        self.multiclick_stopping = False
        self.update_state(State.IDLE)
        self._close_point_markers()
        self.set_status(thread.message,
                        f"已执行 {thread.click_count} 次 · 运行 {int(thread.active_elapsed())} 秒" +
                        (f" · {thread.error_message}" if thread.error_message else ""),
                        error=thread.outcome == "failed")
        thread.deleteLater()

    @Slot(int, int, str)
    def update_multiclick_runtime(self, clicks, elapsed, point_label):
        self._last_point_label = point_label
        if self.multiclick_thread and not self.multiclick_stopping:
            title = "已暂停" if self.multiclick_thread.pause_flag else "正在运行"
            rounds = clicks // max(1, len(self.multiclick_thread.points))
            self.set_status(title, f"已执行 {clicks} 次 · {rounds} 轮 · {elapsed} 秒 · {point_label}")

    @Slot(int)
    def show_multiclick_countdown(self, seconds_left):
        if self.multiclick_thread and not self.multiclick_stopping:
            self.set_status(f"{seconds_left} 秒后开始", f"即将执行 {self.active_profile_name}")

    def _tick_runtime(self):
        thread = self.multiclick_thread
        if thread and thread.started_at is not None and not self.multiclick_stopping:
            self.update_multiclick_runtime(thread.click_count, int(thread.active_elapsed()), self._last_point_label)

    def _show_ready_status(self):
        if self.state != State.IDLE:
            return
        count = sum(point.enabled for point in self.multiclick_points)
        if not self.multiclick_points:
            self.set_status("等待添加点位", "添加并启用一个点位后即可开始")
        elif not count:
            self.set_status("没有启用的点位", "启用至少一个点位后即可开始")
        else:
            self.set_status("准备就绪", f"{count} 个已启用点位 · 启动前倒计时 {self.current_multiclick_profile()['countdown']} 秒")

    @Slot(str)
    def set_status(self, title, detail=None, error=False):
        self.runtime_title.setText(title)
        if detail is not None:
            self.runtime_detail.setText(detail)
            self.runtime_detail.setToolTip(detail)
        self.runtime_dot.setStyleSheet(f"color:{'#b34f41' if error else '#4a8655'}")
        self.runtime_title.setToolTip(title)
        if hasattr(self, "script_status_label") and self.pages.currentIndex() == 1:
            self.script_status_label.setText(title)
        if self.floating_control:
            self.floating_control.sync()

    @Slot(str)
    def append_log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        text = f"{timestamp}  {message}"
        self._logs.append(text)
        self._logs = self._logs[-2000:]
        self.textlog.appendPlainText(text)
        if hasattr(self, "log_view"):
            self.log_view.appendPlainText(text)

    def show_multiclick_log(self):
        if not hasattr(self, "log_dialog"):
            self.log_dialog = QDialog(self)
            self.log_dialog.setWindowTitle("运行记录")
            self.log_dialog.resize(700, 420)
            layout = QVBoxLayout(self.log_dialog)
            self.log_view = QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.document().setMaximumBlockCount(2000)
            layout.addWidget(self.log_view)
            close = button("关闭")
            close.clicked.connect(self.log_dialog.close)
            layout.addWidget(close, 0, Qt.AlignRight)
        self.log_view.setPlainText("\n".join(self._logs))
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_dialog.activateWindow()

    def update_state(self, state):
        self.state = state
        self.updateStateSignal.emit(state)
        self._update_controls()

    def _update_controls(self):
        locked = self.state != State.IDLE or bool(self.pick_overlay)
        has_point = 0 <= self._selected_row < len(self.multiclick_points)
        for control in (self.bt_profile_new, self.profile_list_widget, self.bt_profile_more,
                        self.bt_profile_import, self.bt_workbench_export, self.bt_multiclick_pick,
                        self.bt_empty_add, self.bt_point_more, self.choice_multiclick_mode,
                        self.choice_run_limit, self.spin_run_limit, self.bt_settings, self.bt_run_options):
            control.setEnabled(not locked)
        for control in (self.edit_point_name, self.spin_point_x, self.spin_point_y, self.spin_point_min,
                        self.spin_point_max, self.choice_point_button, self.choice_point_type,
                        self.bt_inspector_test, self.bt_point_copy, self.bt_point_delete):
            control.setEnabled(has_point and not locked)
        self.bt_point_up.setEnabled(has_point and self._selected_row > 0 and not locked)
        self.bt_point_down.setEnabled(has_point and self._selected_row < len(self.multiclick_points) - 1 and not locked)
        self.bt_multiclick_mark.setEnabled(bool(self.multiclick_points) and not locked)
        self.bt_undo.setEnabled(bool(self._history) and not locked)
        for index in range(self.point_list_widget.count()):
            row = self.point_list_widget.itemWidget(self.point_list_widget.item(index))
            row.set_locked(locked)
        enabled = any(point.enabled for point in self.multiclick_points)
        running = self.state == State.MULTI_RUNNING
        paused = running and self.multiclick_thread and self.multiclick_thread.pause_flag
        self.bt_multiclick_start.setText(
            f"继续运行  {self.multiclick_start_hotkey.upper()}" if paused else
            f"暂停任务  {self.multiclick_start_hotkey.upper()}" if running else
            f"开始运行  {self.multiclick_start_hotkey.upper()}")
        self.bt_multiclick_start.setIcon(icon("pause" if running and not paused else "play", "#ffffff"))
        self.bt_multiclick_start.setEnabled(enabled and self.state in (State.IDLE, State.MULTI_RUNNING)
                                             and not self.pick_overlay and not self.multiclick_stopping)
        self.bt_multiclick_stop.setText("正在停止…" if self.multiclick_stopping else f"停止  {self.multiclick_stop_hotkey.upper()}")
        self.bt_multiclick_stop.setEnabled(running and not self.multiclick_stopping)
        for control in (self.spin_countdown, self.spin_max_duration, self.spin_max_clicks,
                        self.spin_max_rounds, self.check_corner_stop, *self.hotkey_buttons.values()):
            control.setEnabled(not locked or self.state == State.SETTING_HOT_KEYS)
        self.bt_workbench_float.setEnabled(self.state in (State.IDLE, State.MULTI_RUNNING))
        if hasattr(self, "btrun"):
            script_running = self.state in (State.RUNNING, State.PAUSE_RUNNING)
            recording = self.state in (State.RECORDING, State.PAUSE_RECORDING)
            self.btrun.setEnabled(self.state == State.IDLE or script_running)
            self.btrun.setText("继续脚本" if self.state == State.PAUSE_RUNNING else "暂停脚本" if script_running
                              else f"运行脚本  {self._hotkeys['script_start'].upper()}")
            self.btrecord.setEnabled(self.state == State.IDLE or recording)
            self.btrecord.setText("完成录制" if recording else f"开始录制  {self._hotkeys['record'].upper()}")
            self.btpauserecord.setEnabled(recording)
            self.btpauserecord.setText("继续录制" if self.state == State.PAUSE_RECORDING else "暂停录制")
            self.bt_script_stop.setEnabled(script_running or recording)
            self.bt_script_stop.setText(f"停止  {self._hotkeys['script_stop'].upper()}")
            for control in (self.choice_script, self.stimes, self.mouse_move_interval_ms,
                            self.bt_open_script_files, self.bt_refresh_scripts):
                control.setEnabled(not locked)
        self.bt_multiclick_pick.setText(f"添加点位  {self.multiclick_pick_hotkey.upper()}")
        if self.floating_control:
            self.floating_control.sync()

    def toggle_float_panel(self):
        if self.floating_control and self.floating_control.isVisible():
            self.restore_workbench()
            return
        if self.floating_control is None:
            self.floating_control = FloatingControlWindow(self)
            screen = QApplication.primaryScreen().availableGeometry()
            self.floating_control.move(screen.center().x() - 325, screen.top() + 30)
        self.floating_control.sync()
        self.floating_control.show()
        self.floating_control.raise_()
        self.hide()

    def restore_workbench(self):
        self.show()
        self.raise_()
        self.activateWindow()
        if self.floating_control:
            self.floating_control.hide()

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.breadcrumb_label.setText("工作台   ›   脚本运行" if index else "工作台   ›   自动点击")
        self.bt_workbench_export.setVisible(index == 0)
        self.bt_workbench_float.setVisible(index == 0)

    def show_help(self):
        QMessageBox.information(self, "使用说明",
            "1. 添加点位：点击后在屏幕上选位置；连续采点按 Esc 结束。\n"
            "2. 选择点位，在右侧编辑名称、坐标、按键和间隔。\n"
            "3. 预览显示屏幕标记；测试会在目标位置真实点击。\n"
            "4. 开始后可暂停、继续或停止；配置在运行结束后恢复编辑。\n"
            "5. 修改会自动保存到本地，导入同名方案会生成副本。\n\n"
            "每个单击或双击动作计一次执行；每执行启用点位数量的动作计一轮。\n"
            "顺序模式依次执行各点；随机模式每次重新选点；独立计时模式按各点间隔执行。\n"
            "快捷键可在“快捷键与运行设置”中修改。")

    def refresh_scripts(self):
        directory = self.data_dir / "scripts"
        directory.mkdir(exist_ok=True)
        current = self.choice_script.currentText() if self.choice_script.count() else self.config.value("Config/Script", "")
        scripts[:] = sorted((path.name for path in directory.iterdir() if path.suffix.lower() in (".txt", ".json5")), reverse=True)
        self.scripts = scripts
        update_script_map()
        blocker = QSignalBlocker(self.choice_script)
        self.choice_script.clear()
        self.choice_script.addItems(self.scripts)
        if current in self.scripts:
            self.choice_script.setCurrentText(current)
        del blocker

    def get_script_path(self):
        name = self.choice_script.currentText()
        return str(self.data_dir / "scripts" / name) if name else ""

    def _save_script_config(self, *args):
        if not hasattr(self, "stimes"):
            return
        self.config.setValue("Config/LoopTimes", self.stimes.value())
        self.config.setValue("Config/Precision", self.mouse_move_interval_ms.value())
        self.config.setValue("Config/Script", self.choice_script.currentText())
        self.config.sync()

    def OnBtOpenScriptFilesButton(self):
        if not self.scripts:
            self.set_status("暂无脚本", "请先录制一组操作。")
            return
        if self.data_dir.resolve() != Path(to_abs_path()).resolve():
            self.set_status("脚本目录", str(self.data_dir / "scripts"))
            return
        from UIFileDialogFunc import FileDialog
        scripts_map["current_index"] = self.choice_script.currentIndex()
        FileDialog().show()
        self.refresh_scripts()
        self.choice_script.setCurrentIndex(scripts_map["current_index"])

    def OnBtrunButton(self):
        if self.state in (State.RUNNING, State.PAUSE_RUNNING):
            paused = self.state == State.RUNNING
            self.runthread.set_pause(paused)
            self.update_state(State.PAUSE_RUNNING if paused else State.RUNNING)
            self.set_status("脚本已暂停" if paused else "脚本运行中")
            return
        if self.state != State.IDLE or self.pick_overlay or self.runthread:
            return
        self.show_page(1)
        self.script_error_label.hide()
        self.runthread = RunScriptClass(self)
        self.runthread.finished.connect(self.handle_runscript_status)
        self.update_state(State.RUNNING)
        self.runthread.start()

    def stop_script(self):
        if self.runthread:
            self.runthread.stop()
            self.set_status("正在停止脚本…")
            self.btrun.setEnabled(False)
            self.bt_script_stop.setEnabled(False)
        elif self.state in (State.RECORDING, State.PAUSE_RECORDING):
            self.recordMethod()

    @Slot()
    def handle_runscript_status(self):
        thread = self.runthread
        if thread is None:
            return
        self.runthread = None
        self.update_state(State.IDLE)
        self.set_status(thread.message, thread.error_message or "可选择脚本再次运行", error=thread.outcome == "failed")
        self.script_error_label.setVisible(thread.outcome == "failed")
        self.script_error_label.setText(thread.error_message)
        thread.deleteLater()

    def recordMethod(self):
        if self.state in (State.RECORDING, State.PAUSE_RECORDING):
            if not self.record:
                self.update_state(State.IDLE)
                self.set_status("未录制到动作", "本次没有生成脚本。")
                return
            name = datetime.datetime.now().strftime("%m%d_%H%M%S_%f") + ".json5"
            try:
                with open(self.data_dir / "scripts" / name, "w", encoding="utf-8") as file:
                    json5.dump({"scripts": self.record}, file, ensure_ascii=False, indent=2)
            except OSError as exc:
                self.append_log(f"保存录制失败：{exc}")
                self.set_status("录制保存失败", str(exc), error=True)
                return
            self.record = []
            self.refresh_scripts()
            self.choice_script.setCurrentText(name)
            self.update_state(State.IDLE)
            self.set_status("录制已保存", name)
        elif self.state == State.IDLE and not self.pick_overlay:
            self.show_page(1)
            self.script_error_label.hide()
            self.record = []
            self.actioncount = 0
            Recorder.globals.latest_time = -1
            self.update_state(State.RECORDING)
            self.set_status("正在录制", "已录制 0 个动作")

    def OnBtrecordButton(self):
        if self.state in (State.RECORDING, State.PAUSE_RECORDING):
            # The stop button's down/up pair is captured before its clicked signal.
            while self.record and self.record[-1].get("event_type") == "EM" and len(self.record) >= 2:
                if self.record[-1].get("action_type") == "mouse left up" and self.record[-2].get("action_type") == "mouse left down":
                    self.record = self.record[:-2]
                break
        self.recordMethod()

    def pauseRecordMethod(self):
        if self.state == State.RECORDING:
            self.update_state(State.PAUSE_RECORDING)
            self.set_status("录制已暂停")
        elif self.state == State.PAUSE_RECORDING:
            Recorder.globals.latest_time = -1
            self.update_state(State.RECORDING)
            self.set_status("正在录制")

    def _sync_hotkey_values(self):
        self.multiclick_start_hotkey = self._hotkeys["multi_start"]
        self.multiclick_stop_hotkey = self._hotkeys["multi_stop"]
        self.multiclick_pick_hotkey = self._hotkeys["pick"]

    def OnHotkeyButton(self, btn_obj, key):
        self.hotkey_set_btn = btn_obj
        self._hotkey_being_set = key
        self.update_state(State.SETTING_HOT_KEYS)
        btn_obj.setText("请按快捷键…")
        self.hotkey_hint.setText("按新的按键或组合键，Esc 取消。")

    def _cancel_hotkey_setting(self, *args):
        if self._hotkey_being_set:
            self.hotkey_buttons[self._hotkey_being_set].setText(self._hotkeys[self._hotkey_being_set].upper())
            self._hotkey_being_set = None
            self.hotkey_set_btn = None
            self.update_state(State.IDLE)

    def _dispatch_hotkey(self, key_name):
        if self._hotkey_being_set:
            if key_name == "escape":
                self._cancel_hotkey_setting()
                return True
            if key_name in (value for key, value in self._hotkeys.items() if key != self._hotkey_being_set):
                self.hotkey_hint.setText("该快捷键已被其他操作使用，请重新输入。")
                return True
            self._hotkeys[self._hotkey_being_set] = key_name
            for key, config_key in (("script_start", "StartHotKey"), ("script_stop", "StopHotKey"),
                                    ("record", "RecordHotKey"), ("multi_start", "MultiClickStartHotKey"),
                                    ("multi_stop", "MultiClickStopHotKey"), ("pick", "MultiClickPickHotKey")):
                self.config.setValue(f"Config/{config_key}", self._hotkeys[key])
                self.hotkey_buttons[key].setText(self._hotkeys[key].upper())
            self.config.sync()
            self._sync_hotkey_values()
            self._hotkey_being_set = None
            self.hotkey_set_btn = None
            self.hotkey_hint.setText("快捷键已保存，全局生效。")
            self.update_state(State.IDLE)
            return True
        action = next((key for key, value in self._hotkeys.items() if value == key_name), None)
        if not action:
            return False
        if QApplication.activeModalWidget():
            return True
        if self.pick_overlay:
            if action == "pick":
                self.pick_overlay.close()
            return True
        if action in ("multi_stop", "script_stop"):
            if self.multiclick_thread:
                self.stop_multiclick()
            else:
                self.stop_script()
        elif action == "multi_start":
            self.toggle_multiclick_start()
        elif action == "script_start":
            self.OnBtrunButton()
        elif action == "pick" and self.state == State.IDLE:
            self.start_stream_pick_points()
        elif action == "record":
            if self.state in (State.RECORDING, State.PAUSE_RECORDING):
                self.pauseRecordMethod()
            else:
                self.recordMethod()
        return True

    @Slot(ScriptEvent)
    def on_record_event(self, event):
        if event.event_type == "EK":
            key = event.action[1].lower()
            modifiers = Recorder.globals.key_combination_trigger
            if event.action_type == "key up":
                self._keys_down.discard(key)
                if key in self.keys_pool:
                    self.keys_pool.remove(key)
                if key in self._consumed_keys:
                    self._consumed_keys.discard(key)
                    return
            elif event.action_type == "key down":
                if key in self._keys_down and (self.state != State.RECORDING or key in self._consumed_keys):
                    return
                self._keys_down.add(key)
                if key in modifiers:
                    if key not in self.keys_pool:
                        self.keys_pool.append(key)
                else:
                    full_key = "+".join([*self.keys_pool, key])
                    if full_key in self._hotkeys.values() or self._hotkey_being_set:
                        # Modifier presses immediately before a hotkey belong
                        # to the hotkey, rather than the recorded action stream.
                        while self.record and self.record[-1].get("event_type") == "EK" and \
                                self.record[-1].get("action_type") == "key down" and \
                                self.record[-1]["action"][1].lower() in self.keys_pool:
                            self.record.pop()
                    if self._dispatch_hotkey(full_key):
                        self._consumed_keys.update([key, *self.keys_pool])
                        return
        elif event.action_type in ("mouse x1 down", "mouse x2 down", "mouse middle down"):
            key = {"mouse x1 down": "xbutton1", "mouse x2 down": "xbutton2", "mouse middle down": "middle"}[event.action_type]
            if self._dispatch_hotkey(key):
                return
        if self.state == State.RECORDING:
            content = copy.deepcopy(event.__dict__)
            if event.event_type == "EM" and not flag_multiplemonitor:
                content["action"] = [f"{value}%" for value in event.action]
            content["type"] = "event"
            self.record.append(content)
            self.actioncount += 1
            self.set_status("正在录制", f"已录制 {self.actioncount} 个动作")
            self.append_log(str(event))

    @Slot(tuple)
    def cursor_pos_change(self, pos):
        self.label_cursor_pos.setText(f"鼠标位置：{pos[0]}, {pos[1]}")

    @Slot(str)
    def playtune(self, filename):
        if self.player.volume() > 0:
            self.player.setSource(QUrl.fromLocalFile(get_assets_path("sounds", filename)))
            self.player.play()

    def closeEvent(self, event):
        self.closing = True
        threads = [thread for thread in (self.multiclick_thread, self.runthread) if thread]
        for thread in threads:
            thread.stop()
        if any(not thread.wait(1000) for thread in threads):
            self.closing = False
            event.ignore()
            self.set_status("正在停止任务，完成后可退出")
            return
        if self.pick_overlay:
            self.pick_overlay.close()
        self._close_point_markers()
        if self.floating_control:
            self.floating_control.close()
        if self._hooks_enabled:
            try:
                Recorder.dispose()
            except RuntimeError:
                pass
        self.config.sync()
        logger.remove(self._log_sink)
        event.accept()
