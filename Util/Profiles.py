"""Validation shared by local plans, imports and the point editor."""
from dataclasses import asdict

from Util.MultiClickClass import ClickPoint


BUTTON_LABELS = {"Left": "左键", "Right": "右键", "Middle": "中键"}
CLICK_LABELS = {"Single": "单击", "Double": "双击"}
MODE_LABELS = {"Sequential": "按列表顺序", "Parallel": "各点独立计时", "Random": "随机选择点位"}


def integer(value, label, minimum=0, maximum=2147483647):
    if isinstance(value, bool):
        raise ValueError(f"{label}需要填写整数")
    try:
        result = int(value)
        if isinstance(value, float) and value != result:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label}需要填写整数") from None
    if not minimum <= result <= maximum:
        raise ValueError(f"{label}需要在 {minimum}～{maximum} 之间")
    return result


def boolean(value, label):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in ("true", "1", "yes", "on"):
            return True
        if value.lower() in ("false", "0", "no", "off"):
            return False
    if value in (0, 1):
        return bool(value)
    raise ValueError(f"{label}需要为 true 或 false")


def choice(value, values, label):
    reverse = {text: key for key, text in values.items()}
    result = reverse.get(value, value) if isinstance(value, str) else None
    if result not in values:
        raise ValueError(f"{label}无效：{value}")
    return result


def normalize_point(data, index=1):
    if not isinstance(data, dict):
        raise ValueError(f"第 {index} 个点位需要是一个对象")
    label = f"第 {index} 个点位"
    name = data.get("name", f"点位 {index}")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{label}名称不能为空")
    base = data.get("interval_ms", 1000)
    # Zero was used by older versions as the "use interval_ms" sentinel.
    # Keep that migration while validating explicit negative/non-integer values.
    low = integer(data.get("interval_min_ms") or base, f"{label}最小间隔", 1, 999999)
    high = integer(data.get("interval_max_ms") or base, f"{label}最大间隔", low, 999999)
    return asdict(ClickPoint(
        enabled=boolean(data.get("enabled", True), f"{label}启用状态"),
        name=name.strip(),
        x=integer(data.get("x", 0), f"{label} X 坐标", -100000, 100000),
        y=integer(data.get("y", 0), f"{label} Y 坐标", -100000, 100000),
        button=choice(data.get("button", "Left"), BUTTON_LABELS, f"{label}鼠标按键"),
        click_type=choice(data.get("click_type", "Single"), CLICK_LABELS, f"{label}点击类型"),
        interval_ms=low, interval_min_ms=low, interval_max_ms=high,
    ))


def normalize_profile(data):
    if not isinstance(data, dict):
        raise ValueError("方案需要是一个对象")
    points = data.get("points", [])
    if not isinstance(points, list):
        raise ValueError("方案的 points 需要是点位数组")
    old_modes = {"并行": "Parallel", "顺序": "Sequential", "随机": "Random"}
    mode = data.get("mode", "Sequential")
    if isinstance(mode, str):
        mode = old_modes.get(mode, mode)
    return {
        "mode": choice(mode, MODE_LABELS, "执行方式"),
        "countdown": integer(data.get("countdown", 3), "启动倒计时", 0, 60),
        "max_duration": integer(data.get("max_duration", 0), "最长运行时间", 0, 86400),
        "max_clicks": integer(data.get("max_clicks", 0), "最多点击次数", 0, 9999999),
        "max_rounds": integer(data.get("max_rounds", 0), "最多执行轮数", 0, 9999999),
        "corner_stop": boolean(data.get("corner_stop", True), "左上角停止"),
        "points": [normalize_point(point, index) for index, point in enumerate(points, 1)],
    }
