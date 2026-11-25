import random
import threading
import time
from dataclasses import dataclass, replace
from typing import List

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCursor
from loguru import logger

from Event import ScriptEvent


@dataclass
class ClickPoint:
    enabled: bool
    name: str
    x: int
    y: int
    button: str
    click_type: str
    interval_ms: int
    interval_min_ms: int = 0
    interval_max_ms: int = 0


class ImmediateClickContext:
    """Zero-delay input events still expect an executor with sleep()."""
    @staticmethod
    def sleep(msecs):
        if msecs > 0:
            time.sleep(msecs / 1000.0)


def execute_click(point, context=None, can_continue=None):
    context = context or ImmediateClickContext()
    count = 2 if point.click_type == "Double" else 1
    for index in range(count):
        if can_continue and not can_continue():
            return False
        try:
            ScriptEvent({
                "delay": 0, "event_type": "EM",
                "action_type": f"mouse {point.button.lower()} down",
                "action": [point.x, point.y],
            }).execute(context)
        finally:
            # Always release the button, including when execution fails/stops.
            ScriptEvent({
                "delay": 0, "event_type": "EM",
                "action_type": f"mouse {point.button.lower()} up",
                "action": [-1, -1],
            }).execute(ImmediateClickContext())
        if index + 1 < count:
            context.sleep(40)
    return True


class MultiClickClass(QThread):
    statusSignal = Signal(bool)
    tnumrdSignal = Signal(str)
    logSignal = Signal(str)
    playtuneSignal = Signal(str)
    countdownSignal = Signal(int)
    statsSignal = Signal(int, int, str)

    def __init__(self, frame, points: List[ClickPoint], mode="Parallel",
                 countdown_seconds=3, max_duration_seconds=0,
                 max_clicks=0, corner_stop=True, max_rounds=0):
        super().__init__(frame)
        self.points = [replace(point) for point in points if point.enabled]
        self.mode = mode
        self.countdown_seconds = max(0, int(countdown_seconds))
        self.max_duration_seconds = max(0, int(max_duration_seconds))
        self.max_clicks = max(0, int(max_clicks))
        self.max_rounds = max(0, int(max_rounds))
        self.corner_stop = corner_stop
        self.stop_flag = False
        self.pause_flag = False
        self._wake = threading.Event()
        self._clock_lock = threading.Lock()
        self.paused_total = 0.0
        self.pause_started = None
        self.started_at = None
        self.finished_at = None
        self.click_count = 0
        self.outcome = "stopped"
        self.message = "已停止"
        self.error_message = ""
        self.logSignal.connect(frame.append_log)
        self.tnumrdSignal.connect(frame.set_status)
        self.playtuneSignal.connect(frame.playtune)
        self.countdownSignal.connect(frame.show_multiclick_countdown)
        self.statsSignal.connect(frame.update_multiclick_runtime)

    def stop(self):
        self.stop_flag = True
        self._wake.set()

    def set_pause(self, paused=True):
        with self._clock_lock:
            if paused == self.pause_flag:
                return
            now = time.monotonic()
            if paused:
                self.pause_started = now
            elif self.pause_started is not None:
                self.paused_total += now - self.pause_started
                self.pause_started = None
            self.pause_flag = paused
        self._wake.set()

    def toggle_pause(self):
        self.set_pause(not self.pause_flag)
        self.logSignal.emit("任务已暂停" if self.pause_flag else "任务已继续")

    def active_elapsed(self):
        with self._clock_lock:
            if self.started_at is None:
                return 0.0
            end = self.pause_started if self.pause_started is not None else (self.finished_at or time.monotonic())
            return max(0.0, end - self.started_at - self.paused_total)

    def _finish_by_limit(self, message):
        if not self.stop_flag:
            self.outcome = "completed"
            self.message = message
            self.logSignal.emit(message)
        self.stop_flag = True
        return True

    def should_stop_by_limit(self, start_time=None, click_count=None):
        if self.stop_flag:
            return True
        count = self.click_count if click_count is None else click_count
        if self.max_clicks and count >= self.max_clicks:
            return self._finish_by_limit(f"已完成 {count} 次点击")
        if self.max_rounds and count >= self.max_rounds * len(self.points):
            return self._finish_by_limit(f"已完成 {self.max_rounds} 轮")
        if self.max_duration_seconds and self.active_elapsed() >= self.max_duration_seconds:
            return self._finish_by_limit("已达到最长运行时间")
        if self.corner_stop:
            pos = QCursor.pos()
            if pos.x() <= 2 and pos.y() <= 2:
                self.message = "鼠标移到左上角，已停止"
                self.logSignal.emit(self.message)
                self.stop()
                return True
        return False

    def _checkpoint(self):
        while not self.should_stop_by_limit():
            if not self.pause_flag:
                return True
            self._wake.wait(0.02)
            self._wake.clear()
        return False

    def sleep(self, msecs):
        remaining = max(0.0, float(msecs)) / 1000.0
        while remaining > 0 and self._checkpoint():
            started = time.monotonic()
            self._wake.wait(min(0.01, remaining))
            self._wake.clear()
            if not self.pause_flag:
                remaining -= time.monotonic() - started

    @staticmethod
    def next_interval(point):
        low = max(1, point.interval_min_ms or point.interval_ms)
        high = max(low, point.interval_max_ms or point.interval_ms)
        return random.randint(low, high)

    def click_point(self, point):
        return execute_click(point, self, self._checkpoint)

    def _perform_point(self, point):
        if not self._checkpoint() or not self.click_point(point):
            return False
        self.click_count += 1
        self.emit_stats(point)
        self.should_stop_by_limit()
        return not self.stop_flag

    def emit_stats(self, point):
        button = {"Left": "左键", "Right": "右键", "Middle": "中键"}[point.button]
        click_type = "双击" if point.click_type == "Double" else "单击"
        self.statsSignal.emit(self.click_count, int(self.active_elapsed()),
                              f"{point.name} · {button}{click_type}")

    def run(self):
        success = False
        try:
            if not self.points:
                raise ValueError("没有启用的点位")
            for left in range(self.countdown_seconds, 0, -1):
                if not self._checkpoint():
                    return
                self.countdownSignal.emit(left)
                self.sleep(1000)
            if not self._checkpoint():
                return
            with self._clock_lock:
                self.started_at = time.monotonic()
                self.paused_total = 0.0
                self.pause_started = None
            self.playtuneSignal.emit("start.wav")
            self.tnumrdSignal.emit("正在运行")
            self.logSignal.emit("多点连点已启动")
            next_run = [0.0] * len(self.points)
            index = 0
            while self._checkpoint():
                if self.mode == "Parallel":
                    now = self.active_elapsed()
                    due = [i for i, deadline in enumerate(next_run) if now >= deadline]
                    if not due:
                        self.sleep(min(10, max(1, (min(next_run) - now) * 1000)))
                        continue
                    for i in due:
                        point = self.points[i]
                        if not self._perform_point(point):
                            break
                        next_run[i] = self.active_elapsed() + self.next_interval(point) / 1000
                else:
                    point = random.choice(self.points) if self.mode == "Random" else self.points[index]
                    if not self._perform_point(point):
                        break
                    index = (index + 1) % len(self.points)
                    self.sleep(self.next_interval(point))
            success = self.outcome == "completed"
        except Exception as exc:
            self.outcome = "failed"
            self.error_message = str(exc)
            self.message = f"多点连点失败：{exc}"
            logger.exception("Multi-click failed")
            self.logSignal.emit(self.message)
        finally:
            self.finished_at = time.monotonic()
            self.logSignal.emit(self.message)
            self.tnumrdSignal.emit(self.message)
            self.playtuneSignal.emit("end.wav")
            self.statusSignal.emit(success)
