import copy
import math
from pathlib import Path
import re

import json5


class JsonObject:
    def __init__(self, content, location="", source_path=""):
        self.content = content
        self.location = location
        self.source_path = source_path
        self.next_object = None
        self.next_object_if_false = None


def validate_event(content):
    for key in ("delay", "event_type", "action_type", "action"):
        if key not in content:
            raise ValueError(f"动作缺少 {key}")
    delay = content["delay"]
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
        raise ValueError("delay 必须是非负的毫秒数")
    event_type, action_type, action = content["event_type"], content["action_type"], content["action"]
    if event_type == "EM":
        valid_actions = {f"mouse {button} {state}" for button in ("left", "right", "middle") for state in ("up", "down")}
        valid_actions.update(("mouse move", "mouse wheel up", "mouse wheel down"))
        if action_type not in valid_actions:
            raise ValueError(f"不支持的鼠标动作：{action_type}")
        if not isinstance(action, (list, tuple)) or len(action) != 2:
            raise ValueError("鼠标 action 需要为 [x, y]")
        absolute = all(isinstance(value, int) and not isinstance(value, bool) for value in action)
        relative = all(isinstance(value, str) and re.fullmatch(r"(?:0(?:\.\d+)?|1(?:\.0+)?)%", value) for value in action)
        numeric_relative = all(isinstance(value, float) and math.isfinite(value) and 0 <= value <= 1 for value in action)
        if not (absolute or relative or numeric_relative):
            raise ValueError("鼠标坐标需要为整数像素，或 0～1 的相对坐标")
    elif event_type == "EK":
        if action_type not in ("key down", "key up"):
            raise ValueError(f"不支持的键盘动作：{action_type}")
        if not isinstance(action, (list, tuple)) or len(action) != 3:
            raise ValueError("键盘 action 需要为 [键码, 键名, 扩展标记]")
        code, name, extended = action
        if not isinstance(code, int) or not 0 <= code <= 255 or not isinstance(name, str) or not name:
            raise ValueError("键码或键名无效")
        if extended not in (0, 1, False, True):
            raise ValueError("扩展标记需要为 0 或 1")
    elif event_type == "EX":
        if action_type != "input" or not isinstance(action, str):
            raise ValueError("文本输入动作需要 action_type: input 和字符串 action")
    else:
        raise ValueError(f"不支持的 event_type：{event_type}")


class ScriptParser:
    @staticmethod
    def load_content(script_path):
        try:
            with open(script_path, encoding="utf-8-sig") as file:
                return json5.load(file)
        except UnicodeDecodeError:
            with open(script_path, encoding="gbk") as file:
                return json5.load(file)

    @staticmethod
    def parse(script_path, *args):
        return ScriptParser.from_content(ScriptParser.load_content(script_path), script_path)

    @staticmethod
    def from_content(content, script_path=""):
        if not isinstance(content, dict) or not isinstance(content.get("scripts"), list):
            raise ValueError("新格式脚本需要包含 scripts 数组")
        if not content["scripts"]:
            raise ValueError("脚本中没有可执行的动作")
        label_maps, pending = {}, {}
        head = ScriptParser.link_objects(copy.deepcopy(content["scripts"]), None,
                                          label_maps, pending, "scripts", str(script_path))
        for node, target in pending.items():
            if target not in label_maps:
                raise ValueError(f"{node.location}：跳转目标不存在：{target}")
            node.next_object = label_maps[target]
        return head

    @staticmethod
    def link_objects(objects, target_object, label_maps, pending_dict,
                     location="scripts", source_path=""):
        if not isinstance(objects, list):
            raise ValueError(f"{location} 需要是动作数组")
        for index in range(len(objects) - 1, -1, -1):
            content = objects[index]
            position = f"{location}[{index + 1}]"
            try:
                if not isinstance(content, dict):
                    raise ValueError("动作需要是一个对象")
                node = JsonObject(content, position, source_path)
                label = content.get("label")
                if label is not None:
                    if not isinstance(label, str) or not label:
                        raise ValueError("label 需要为非空字符串")
                    if label in label_maps:
                        raise ValueError(f"重复的 label：{label}")
                    label_maps[label] = node
                node.next_object = target_object
                kind = content.get("type")
                if kind == "event":
                    validate_event(content)
                elif kind == "sequence":
                    content["events"] = ScriptParser.link_objects(
                        content.get("events"), None, label_maps, pending_dict,
                        position + ".events", source_path)
                elif kind == "if":
                    if not isinstance(content.get("judge"), str) or not content["judge"]:
                        raise ValueError("if 动作需要 judge 插件函数名")
                    node.next_object = ScriptParser.link_objects(
                        content.get("do", []), target_object, label_maps, pending_dict,
                        position + ".do", source_path)
                    node.next_object_if_false = ScriptParser.link_objects(
                        content.get("else", []), target_object, label_maps, pending_dict,
                        position + ".else", source_path)
                elif kind == "goto":
                    target = content.get("tolabel")
                    if not isinstance(target, str) or not target:
                        raise ValueError("goto 动作需要 tolabel")
                    pending_dict[node] = target
                elif kind == "subroutine":
                    paths = content.get("path")
                    if isinstance(paths, str):
                        paths = [paths]
                    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) and path for path in paths):
                        raise ValueError("subroutine 动作需要 path 脚本路径数组")
                    content["path"] = paths
                elif kind != "custom":
                    raise ValueError(f"不支持的动作 type：{kind}")
                for key in ("call", "attach"):
                    if key in content and (not isinstance(content[key], list) or
                                           not all(isinstance(value, str) for value in content[key])):
                        raise ValueError(f"{key} 需要为插件函数名数组")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{position}：{exc}") from exc
            target_object = node
        return target_object


class LegacyParser:
    @staticmethod
    def parse(script_path, *args):
        return LegacyParser.from_content(ScriptParser.load_content(script_path), script_path)

    @staticmethod
    def from_content(content, script_path=""):
        if not isinstance(content, list) or not content:
            raise ValueError("旧格式脚本需要包含动作数组")
        events = []
        for index, event in enumerate(content, 1):
            if not isinstance(event, list) or len(event) < 4:
                raise ValueError(f"第 {index} 个旧格式动作需要包含延时、类型、动作和参数")
            if not isinstance(event[1], str) or not isinstance(event[2], str):
                raise ValueError(f"第 {index} 个旧格式动作的类型无效")
            events.append({"delay": event[0], "event_type": event[1].upper(),
                           "action_type": event[2].lower(), "action": event[3], "type": "event"})
        return ScriptParser.from_content({"scripts": events}, script_path)


def parse_script(script_path):
    content = ScriptParser.load_content(script_path)
    parser = LegacyParser if isinstance(content, list) else ScriptParser
    return parser.from_content(content, script_path)
