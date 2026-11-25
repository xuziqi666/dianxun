import copy
from dataclasses import dataclass
from pathlib import Path
import threading
import time

from PySide6.QtCore import QThread, Signal, Slot
from loguru import logger

from Event import ScriptEvent
from Plugin.Manager import PluginManager
from Util.Global import State
from Util.MultiClickClass import ImmediateClickContext
from Util.Parser import parse_script


class ExecutionStopped(Exception):
    pass


class RunScriptMeta:
    def _init_execution(self):
        self._condition = threading.Condition()
        self._stop_requested = False
        self.eventPause = False
        self._pressed = {}
        self._path_stack = []
        self.outcome = "stopped"
        self.message = "脚本已停止"
        self.error_message = ""

    def is_stopping(self):
        return self._stop_requested

    def stop(self):
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()

    def set_pause(self, paused=True):
        with self._condition:
            self.eventPause = paused
            self._condition.notify_all()

    def resume(self):
        self.set_pause(False)

    def _checkpoint(self):
        with self._condition:
            while self.eventPause and not self.is_stopping():
                self._condition.wait(0.02)
            if self.is_stopping():
                raise ExecutionStopped()

    def sleep(self, msecs):
        remaining = max(0.0, float(msecs)) / 1000.0
        self._checkpoint()
        while remaining > 0:
            with self._condition:
                if self.is_stopping():
                    raise ExecutionStopped()
                if self.eventPause:
                    self._condition.wait(0.02)
                    continue
                started = time.monotonic()
                self._condition.wait(min(remaining, 0.02))
                if not self.eventPause:
                    remaining -= time.monotonic() - started
        self._checkpoint()

    def run_script_from_path(self, script_path, runtimes=None):
        path = Path(script_path).resolve()
        if len(self._path_stack) >= 32 or path in self._path_stack:
            raise ValueError(f"子脚本循环调用：{path.name}")
        try:
            head = parse_script(path)
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(f"{path.name}：解析脚本失败：{exc}") from exc
        self._path_stack.append(path)
        try:
            loops = self.runtimes if runtimes is None else runtimes
            iteration = 0
            while loops == 0 or iteration < loops:
                self._checkpoint()
                self._status(f"{path.name} 运行中 · 第 {iteration + 1}/{loops or '∞'} 次")
                self.run_script_from_objects(head)
                iteration += 1
        finally:
            self._path_stack.pop()

    def run_script_from_objects(self, head_object, attach=None):
        current = head_object
        while current is not None:
            self._checkpoint()
            try:
                if attach:
                    PluginManager.call_group(attach, current)
                current = self.run_object(current)
            except ExecutionStopped:
                raise
            except Exception as exc:
                raise RuntimeError(f"{Path(current.source_path).name} · {current.location}：{exc}") from exc
        return True

    def run_object(self, node):
        content = node.content
        if content.get("call"):
            PluginManager.call_group(content["call"], node)
        kind = content["type"]
        if kind == "event":
            event = ScriptEvent(copy.deepcopy(content))
            self._log(str(event))
            action_type = content["action_type"]
            key = None
            if content["event_type"] in ("EM", "EK") and action_type.endswith((" down", " up")):
                key = (content["event_type"], action_type.rsplit(" ", 1)[0],
                       content["action"][0] if content["event_type"] == "EK" else "")
            if key and action_type.endswith(" down"):
                release = copy.deepcopy(content)
                release["delay"] = 0
                release["action_type"] = action_type[:-5] + " up"
                if content["event_type"] == "EM":
                    release["action"] = [-1, -1]
                self._pressed[key] = release
            event.execute(self)
            if key and action_type.endswith(" up"):
                self._pressed.pop(key, None)
        elif kind == "sequence":
            self.run_script_from_objects(content["events"], content.get("attach"))
        elif kind == "if":
            return node.next_object if PluginManager.call(content["judge"], node) else node.next_object_if_false
        elif kind == "subroutine":
            for sub_path in content["path"]:
                self._checkpoint()
                path = Path(sub_path)
                if not path.is_absolute():
                    path = Path(node.source_path).parent / path
                self.run_script_from_path(path, runtimes=1)
        elif kind not in ("goto", "custom"):
            raise ValueError(f"不支持的动作：{kind}")
        return node.next_object

    def _release_inputs(self):
        for content in reversed(list(self._pressed.values())):
            try:
                ScriptEvent(content).execute(ImmediateClickContext())
            except Exception as exc:
                logger.exception("Failed to release input")
                self._log(f"释放按键失败：{exc}")
        self._pressed.clear()


class RunScriptClass(QThread, RunScriptMeta):
    logSignal = Signal(str)
    tnumrdSignal = Signal(str)
    statusSignal = Signal(bool)
    playtuneSignal = Signal(str)

    def __init__(self, frame):
        super().__init__(frame)
        self._init_execution()
        self.script_path = frame.get_script_path()
        self.runtimes = frame.stimes.value()
        self.logSignal.connect(frame.append_log)
        self.tnumrdSignal.connect(frame.set_status)
        self.playtuneSignal.connect(frame.playtune)

    # QThread also declares a static sleep(); use the cancellable executor wait.
    def sleep(self, msecs):
        RunScriptMeta.sleep(self, msecs)

    def _log(self, text):
        self.logSignal.emit(text)

    def _status(self, text):
        self.tnumrdSignal.emit(text)

    def run(self):
        try:
            if not self.script_path:
                raise FileNotFoundError("未找到脚本，请先录制或选择脚本")
            self.playtuneSignal.emit("start.wav")
            self.run_script_from_path(self.script_path)
            self._checkpoint()
            self.outcome = "completed"
            self.message = "脚本已完成"
        except ExecutionStopped:
            self.outcome = "stopped"
            self.message = "脚本已停止"
        except Exception as exc:
            self.outcome = "failed"
            self.message = "脚本运行失败"
            self.error_message = str(exc)
            logger.exception("Script execution failed")
            self._log(f"{self.message}：{exc}")
        finally:
            self._release_inputs()
            self._status(self.message)
            self._log(self.message)
            self.playtuneSignal.emit("end.wav")
            self.statusSignal.emit(self.outcome == "completed")


@dataclass
class StopFlag:
    value: bool


class RunScriptCMDClass(QThread, RunScriptMeta):
    def __init__(self, script_path, run_times, flag):
        super().__init__()
        self._init_execution()
        self.script_paths = script_path
        self.runtimes = run_times
        self.flag = flag

    def is_stopping(self):
        return self._stop_requested or self.flag.value

    def sleep(self, msecs):
        RunScriptMeta.sleep(self, msecs)

    def _log(self, text):
        logger.info(text)

    def _status(self, text):
        logger.info(text)

    def run(self):
        try:
            for path in self.script_paths:
                self.run_script_from_path(path)
            self.outcome = "completed"
            self.message = "脚本已完成"
        except ExecutionStopped:
            self.message = "脚本已停止"
        except Exception as exc:
            self.outcome = "failed"
            self.message = "脚本运行失败"
            self.error_message = str(exc)
            logger.exception("Script execution failed")
        finally:
            self._release_inputs()
            logger.info(self.message)
