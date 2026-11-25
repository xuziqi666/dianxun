"""点巡工作台的 Qt widgets；状态统一保存在 UIFunc。"""
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QAbstractSpinBox, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from Util.Profiles import BUTTON_LABELS, CLICK_LABELS, MODE_LABELS


ICONS = {
    "logo": '<path d="M5 4v16M5 7h8a5 5 0 0 1 0 10h-2M9 12h9m-3-3 3 3-3 3"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "target": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>',
    "play": '<path d="m9 5 11 7-11 7Z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M15 8V4H4v11h4"/>',
    "key": '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h.1m4 0h.1m4 0h.1M7 14h10"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5m0 3h.01"/>',
    "mouse": '<rect x="6" y="2" width="12" height="20" rx="6"/><path d="M12 3v6"/>',
    "window": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18m-6 3h3"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="white"/><circle cx="15" cy="17" r="3" fill="white"/>',
    "undo": '<path d="m8 4-5 5 5 5M3 9h11a6 6 0 0 1 0 12"/>',
    "up": '<path d="m5 14 7-7 7 7"/>',
    "down": '<path d="m5 10 7 7 7-7"/>',
    "dots": '<circle cx="5" cy="12" r=".8"/><circle cx="12" cy="12" r=".8"/><circle cx="19" cy="12" r=".8"/>',
    "log": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
}


def icon(name, color="#687b66"):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
           f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.6" '
           f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def label(text, name="", parent=None):
    widget = QLabel(text, parent)
    widget.setTextFormat(Qt.PlainText)
    widget.setObjectName(name)
    return widget


def button(text="", symbol=None, name="", tooltip=None):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(Qt.PointingHandCursor)
    if symbol:
        widget.setIcon(icon(symbol, "#ffffff" if name == "primaryButton" else "#76846e"))
        widget.setIconSize(QSize(16, 16))
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


def field(title, control):
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(label(title, "fieldLabel"))
    layout.addWidget(control)
    return container


class PointRow(QWidget):
    selected = Signal(int)
    enabledChanged = Signal(int, bool)
    testRequested = Signal(int)

    def __init__(self, index, point, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("pointRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 7, 10)
        layout.setSpacing(8)
        order = label(f"{index + 1:02d}", "pointOrder")
        order.setFixedWidth(19)
        self.enabled_check = QCheckBox()
        self.enabled_check.setAccessibleName(f"启用 {point.name}")
        self.enabled_check.setChecked(point.enabled)
        self.enabled_check.setFixedWidth(19)
        self.enabled_check.clicked.connect(lambda value: self.enabledChanged.emit(index, value))
        identity = QVBoxLayout()
        identity.setSpacing(3)
        name = label(point.name, "pointName")
        name.setMinimumWidth(50)
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        name.setToolTip(point.name)
        coords = label(f"{point.x}, {point.y}", "pointCoordinates")
        identity.addWidget(name)
        identity.addWidget(coords)
        action = label(f"{BUTTON_LABELS[point.button]} {CLICK_LABELS[point.click_type]}", "pointAction")
        action.setFixedWidth(74)
        low = point.interval_min_ms or point.interval_ms
        high = point.interval_max_ms or point.interval_ms
        interval_text = f"{low} ms" if low == high else f"{low / 1000:g}–{high / 1000:g} s"
        interval = label(interval_text, "pointInterval")
        interval.setFixedWidth(92)
        interval.setToolTip(f"间隔 {low}～{high} 毫秒")
        self.test_button = button("", "play", "iconButton", f"测试 {point.name}")
        self.test_button.setFixedSize(28, 28)
        self.test_button.setAccessibleName(f"测试 {point.name}")
        self.test_button.clicked.connect(lambda: self.testRequested.emit(index))
        layout.addWidget(order)
        layout.addWidget(self.enabled_check)
        layout.addLayout(identity, 1)
        layout.addWidget(action)
        layout.addWidget(interval)
        layout.addWidget(self.test_button)
        for child in (order, name, coords, action, interval):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setProperty("pointEnabled", point.enabled)

    def mousePressEvent(self, event):
        self.selected.emit(self.index)
        super().mousePressEvent(event)

    def set_locked(self, locked):
        self.enabled_check.setEnabled(not locked)
        self.test_button.setEnabled(not locked)


class TargetPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.point = None
        self.setFixedHeight(100)

    def set_point(self, point):
        self.point = point
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#dfe7d9")))
        painter.setBrush(QColor("#f1f4ed"))
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 6, 6)
        screens = QApplication.screens()
        if not screens:
            return
        bounds = screens[0].geometry()
        for screen in screens[1:]:
            bounds = bounds.united(screen.geometry())
        scale = min((rect.width() - 26) / bounds.width(), (rect.height() - 28) / bounds.height())
        origin = QPointF(rect.center().x() - bounds.width() * scale / 2,
                         rect.center().y() - bounds.height() * scale / 2)
        for screen in screens:
            geo = screen.geometry()
            monitor = QRectF(origin.x() + (geo.x() - bounds.x()) * scale,
                             origin.y() + (geo.y() - bounds.y()) * scale,
                             geo.width() * scale, geo.height() * scale)
            painter.setBrush(QColor("#fbfcf8"))
            painter.drawRoundedRect(monitor, 3, 3)
        if self.point:
            # Convert to logical coordinates before placing the physical target.
            from Util.Screen import physical_to_logical
            logical = physical_to_logical(self.point.x, self.point.y)
            x = origin.x() + (logical.x() - bounds.x()) * scale
            y = origin.y() + (logical.y() - bounds.y()) * scale
            painter.setPen(QPen(QColor("#67934d"), 1.2))
            painter.setBrush(QColor("#2479a353"))
            painter.drawEllipse(QPointF(x, y), 8, 8)
            painter.drawLine(QPointF(x - 13, y), QPointF(x + 13, y))
            painter.drawLine(QPointF(x, y - 13), QPointF(x, y + 13))


class FloatingControlWindow(QWidget):
    def __init__(self, owner):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.owner = owner
        self.drag_offset = None
        self.setWindowTitle("点巡 · 悬浮控制")
        self.setObjectName("floatingWindow")
        self.setStyleSheet(WORKBENCH_STYLE)
        self.setFixedSize(650, 68)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 10)
        layout.setSpacing(10)
        layout.addWidget(label("点巡", "floatBrand"))
        copy = QVBoxLayout()
        copy.setSpacing(2)
        self.status_label = label("准备就绪", "runtimeTitle")
        self.detail_label = label("", "mutedText")
        self.detail_label.setMaximumWidth(180)
        copy.addWidget(self.status_label)
        copy.addWidget(self.detail_label)
        layout.addLayout(copy, 1)
        self.start_button = button("开始", "play", "primaryButton")
        self.stop_button = button("停止", "stop", "dangerButton")
        self.expand_button = button("工作台", "window")
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.expand_button)
        self.start_button.clicked.connect(owner.toggle_multiclick_start)
        self.stop_button.clicked.connect(owner.stop_multiclick)
        self.expand_button.clicked.connect(owner.restore_workbench)

    def sync(self):
        self.status_label.setText(self.owner.runtime_title.text())
        self.detail_label.setText(self.owner.runtime_detail.text())
        self.detail_label.setToolTip(self.owner.runtime_detail.text())
        self.start_button.setText(self.owner.bt_multiclick_start.text())
        self.start_button.setIcon(self.owner.bt_multiclick_start.icon())
        self.start_button.setEnabled(self.owner.bt_multiclick_start.isEnabled())
        self.stop_button.setEnabled(self.owner.bt_multiclick_stop.isEnabled())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None

    def closeEvent(self, event):
        if not self.owner.closing:
            event.ignore()
            self.owner.restore_workbench()
        else:
            event.accept()


def build_workbench(owner):
    owner.resize(1240, 790)
    owner.setMinimumSize(1000, 680)
    owner.setStyleSheet(WORKBENCH_STYLE)
    owner.centralwidget = QWidget(owner)
    owner.setCentralWidget(owner.centralwidget)
    root = QVBoxLayout(owner.centralwidget)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    header = QFrame()
    header.setObjectName("appHeader")
    header.setFixedHeight(64)
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(18, 0, 20, 0)
    brand = QWidget()
    brand.setFixedWidth(166)
    brand_layout = QHBoxLayout(brand)
    brand_layout.setContentsMargins(0, 0, 0, 0)
    mark = label("")
    mark.setPixmap(icon("logo", "#ffffff").pixmap(22, 22))
    mark.setAlignment(Qt.AlignCenter)
    mark.setObjectName("brandMark")
    mark.setFixedSize(30, 30)
    brand_layout.addWidget(mark)
    brand_copy = QVBoxLayout()
    brand_copy.setSpacing(0)
    owner.title_label = label("点巡", "brandLabel")
    owner.subtitle_label = label("自动点击工作台", "brandSubtitle")
    owner.title_label.setFixedHeight(25)
    owner.subtitle_label.setFixedHeight(12)
    brand_copy.setAlignment(Qt.AlignVCenter)
    brand_copy.addWidget(owner.title_label)
    brand_copy.addWidget(owner.subtitle_label)
    brand_layout.addLayout(brand_copy)
    brand_layout.addStretch()
    header_layout.addWidget(brand)
    owner.breadcrumb_label = label("工作台   ›   自动点击", "breadcrumb")
    header_layout.addWidget(owner.breadcrumb_label, 1)
    owner.bt_workbench_log = button("运行记录", "log", "ghostButton")
    owner.bt_workbench_export = button("导出方案", "copy", "ghostButton")
    owner.bt_workbench_float = button("悬浮模式", "window")
    header_layout.addWidget(owner.bt_workbench_log)
    header_layout.addWidget(owner.bt_workbench_export)
    header_layout.addWidget(owner.bt_workbench_float)
    root.addWidget(header)

    owner.pages = QStackedWidget()
    owner.click_tab = QWidget()
    owner.script_tab = QWidget()
    owner.pages.addWidget(owner.click_tab)
    owner.pages.addWidget(owner.script_tab)
    root.addWidget(owner.pages, 1)
    body = QHBoxLayout(owner.click_tab)
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(0)
    sidebar = QFrame()
    sidebar.setObjectName("profileSidebar")
    sidebar.setFixedWidth(184)
    side = QVBoxLayout(sidebar)
    side.setContentsMargins(12, 24, 12, 16)
    side.setSpacing(8)
    heading = QHBoxLayout()
    heading.addWidget(label("我的方案", "fieldLabel"))
    heading.addStretch()
    owner.bt_profile_new = button("", "plus", "iconButton", "新建方案")
    owner.bt_profile_new.setFixedSize(28, 28)
    heading.addWidget(owner.bt_profile_new)
    side.addLayout(heading)
    owner.profile_list_widget = QListWidget()
    owner.profile_list_widget.setObjectName("profileList")
    owner.profile_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    side.addWidget(owner.profile_list_widget)
    side.addWidget(label("从一个点位开始", "sideHeading"))
    side_note = label("添加位置，设置间隔，\n验证后即可运行。", "sideNote")
    side.addWidget(side_note)
    side.addStretch(1)
    owner.bt_profile_import = button("导入方案", "copy", "sideButton")
    owner.bt_script_page = button("脚本录制与运行", "mouse", "sideButton")
    owner.bt_settings = button("快捷键与运行设置", "key", "sideButton")
    owner.bt_help = button("使用说明", "help", "sideButton")
    for item in (owner.bt_profile_import, owner.bt_script_page, owner.bt_settings, owner.bt_help):
        side.addWidget(item)
    body.addWidget(sidebar)

    workspace = QWidget()
    work = QVBoxLayout(workspace)
    work.setContentsMargins(0, 0, 0, 0)
    work.setSpacing(0)
    columns = QHBoxLayout()
    columns.setSpacing(0)
    editor = QWidget()
    edit = QVBoxLayout(editor)
    edit.setContentsMargins(24, 26, 18, 14)
    edit.setSpacing(12)
    edit.addWidget(label("POINT AUTOMATION", "eyebrow"))
    title_line = QHBoxLayout()
    owner.workbench_task_title = label("默认方案", "taskTitle")
    owner.workbench_task_title.setMaximumWidth(400)
    owner.save_status_label = label("已保存", "saveStatus")
    owner.bt_profile_more = button("", "dots", "iconButton", "方案操作")
    owner.bt_profile_more.setFixedSize(28, 28)
    title_line.addWidget(owner.workbench_task_title)
    title_line.addWidget(owner.save_status_label)
    title_line.addStretch()
    title_line.addWidget(owner.bt_profile_more)
    edit.addLayout(title_line)
    edit.addWidget(label("按设定节奏，重复完成一组点击。", "mutedText"))
    toolbar = QHBoxLayout()
    owner.bt_multiclick_pick = button("添加点位  F4", "plus", "primaryButton")
    owner.bt_multiclick_mark = button("预览点位", "target")
    owner.bt_point_more = button("", "dots", "iconButton", "更多添加方式")
    owner.bt_point_more.setFixedSize(30, 32)
    owner.bt_undo = button("", "undo", "iconButton", "撤销编辑 · Ctrl+Z")
    owner.bt_undo.setFixedSize(30, 32)
    toolbar.addWidget(owner.bt_multiclick_pick)
    toolbar.addWidget(owner.bt_multiclick_mark)
    toolbar.addWidget(owner.bt_point_more)
    toolbar.addStretch()
    toolbar.addWidget(owner.bt_undo)
    edit.addLayout(toolbar)

    options = QFrame()
    options.setObjectName("runOptions")
    options_layout = QHBoxLayout(options)
    options_layout.setContentsMargins(0, 8, 0, 8)
    options_layout.setSpacing(6)
    owner.choice_multiclick_mode = QComboBox()
    owner.choice_multiclick_mode.setObjectName("plainCombo")
    for value, title in MODE_LABELS.items():
        owner.choice_multiclick_mode.addItem(title, value)
    owner.choice_run_limit = QComboBox()
    owner.choice_run_limit.setObjectName("plainCombo")
    for text, value in (("手动停止", "none"), ("完成轮数", "rounds"),
                        ("点击次数", "clicks"), ("运行时长", "duration"), ("组合条件", "custom")):
        owner.choice_run_limit.addItem(text, value)
    owner.spin_run_limit = QSpinBox()
    owner.spin_run_limit.setRange(1, 9999999)
    owner.spin_run_limit.setButtonSymbols(QAbstractSpinBox.NoButtons)
    owner.spin_run_limit.setMaximumWidth(96)
    owner.bt_run_options = button("", "settings", "iconButton", "运行设置")
    owner.bt_run_options.setFixedSize(28, 28)
    options_layout.addWidget(label("执行方式", "fieldLabel"))
    options_layout.addWidget(owner.choice_multiclick_mode)
    options_layout.addSpacing(8)
    options_layout.addWidget(label("结束条件", "fieldLabel"))
    options_layout.addWidget(owner.choice_run_limit)
    options_layout.addWidget(owner.spin_run_limit)
    options_layout.addStretch()
    options_layout.addWidget(owner.bt_run_options)
    edit.addWidget(options)
    list_head = QHBoxLayout()
    list_head.setContentsMargins(8, 0, 34, 0)
    owner.workbench_point_count = label("点位 / 坐标", "fieldLabel")
    list_head.addWidget(owner.workbench_point_count, 1)
    action_head = label("点击动作", "fieldLabel")
    action_head.setFixedWidth(74)
    interval_head = label("间隔", "fieldLabel")
    interval_head.setFixedWidth(92)
    list_head.addWidget(action_head)
    list_head.addWidget(interval_head)
    edit.addLayout(list_head)
    owner.point_stack = QStackedWidget()
    owner.point_list_widget = QListWidget()
    owner.point_list_widget.setObjectName("pointList")
    owner.point_list_widget.setSpacing(3)
    owner.point_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    owner.empty_page = QWidget()
    empty_layout = QVBoxLayout(owner.empty_page)
    empty_layout.addStretch()
    empty_symbol = label("")
    empty_symbol.setPixmap(icon("target", "#7e9670").pixmap(44, 44))
    empty_symbol.setAlignment(Qt.AlignCenter)
    empty_layout.addWidget(empty_symbol)
    empty_layout.addWidget(label("添加第一个点位", "emptyTitle"), 0, Qt.AlignCenter)
    empty_layout.addWidget(label("选好位置，再设置点击节奏。", "mutedText"), 0, Qt.AlignCenter)
    owner.bt_empty_add = button("添加点位", "plus", "primaryButton")
    empty_layout.addWidget(owner.bt_empty_add, 0, Qt.AlignCenter)
    empty_layout.addStretch(2)
    owner.point_stack.addWidget(owner.point_list_widget)
    owner.point_stack.addWidget(owner.empty_page)
    edit.addWidget(owner.point_stack, 1)
    edit.addWidget(label("选择点位编辑参数 · ↑↓ 切换 · Delete 删除", "listFootnote"))
    columns.addWidget(editor, 1)

    owner.inspector_scroll = QScrollArea()
    owner.inspector_scroll.setObjectName("inspectorScroll")
    owner.inspector_scroll.setWidgetResizable(True)
    owner.inspector_scroll.setFrameShape(QFrame.NoFrame)
    owner.inspector_scroll.setFixedWidth(276)
    inspector = QWidget()
    inspector.setObjectName("inspector")
    inspect = QVBoxLayout(inspector)
    inspect.setContentsMargins(20, 24, 20, 14)
    inspect.setSpacing(10)
    inspector_heading = QHBoxLayout()
    inspector_heading.addWidget(label("点位属性", "inspectorTitle"))
    inspector_heading.addStretch()
    owner.inspector_badge = label("—", "pointBadge")
    inspector_heading.addWidget(owner.inspector_badge)
    inspect.addLayout(inspector_heading)
    owner.edit_point_name = QLineEdit()
    owner.edit_point_name.setMaxLength(60)
    owner.spin_point_x = QSpinBox()
    owner.spin_point_y = QSpinBox()
    for spin in (owner.spin_point_x, owner.spin_point_y):
        spin.setRange(-100000, 100000)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    owner.choice_point_button = QComboBox()
    owner.choice_point_type = QComboBox()
    for value, text in BUTTON_LABELS.items():
        owner.choice_point_button.addItem(text, value)
    for value, text in CLICK_LABELS.items():
        owner.choice_point_type.addItem(text, value)
    owner.spin_point_min = QSpinBox()
    owner.spin_point_max = QSpinBox()
    for spin in (owner.spin_point_min, owner.spin_point_max):
        spin.setRange(1, 999999)
        spin.setSuffix(" ms")
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    inspect.addWidget(field("名称", owner.edit_point_name))
    for first_title, first, second_title, second in (
        ("X 坐标", owner.spin_point_x, "Y 坐标", owner.spin_point_y),
        ("鼠标按键", owner.choice_point_button, "点击类型", owner.choice_point_type),
        ("最小间隔", owner.spin_point_min, "最大间隔", owner.spin_point_max),
    ):
        pair = QHBoxLayout()
        pair.setSpacing(10)
        pair.addWidget(field(first_title, first), 1)
        pair.addWidget(field(second_title, second), 1)
        inspect.addLayout(pair)
    interval_note = label("两值相同则固定间隔，不同时随机等待。", "smallNote")
    interval_note.setWordWrap(True)
    inspect.addWidget(interval_note)
    inspect.addWidget(label("目标位置示意", "sectionLabel"))
    owner.target_preview = TargetPreview()
    inspect.addWidget(owner.target_preview)
    inspect.addWidget(label("桌面位置示意 · 预览点位可查看屏幕标记", "smallNote"))
    owner.bt_inspector_test = button("测试此点位", "target")
    inspect.addWidget(owner.bt_inspector_test)
    row = QHBoxLayout()
    owner.bt_point_up = button("上移", "up")
    owner.bt_point_down = button("下移", "down")
    row.addWidget(owner.bt_point_up)
    row.addWidget(owner.bt_point_down)
    inspect.addLayout(row)
    row = QHBoxLayout()
    owner.bt_point_copy = button("复制", "copy")
    owner.bt_point_delete = button("删除点位", name="dangerLink")
    row.addWidget(owner.bt_point_copy)
    row.addWidget(owner.bt_point_delete)
    inspect.addLayout(row)
    inspect.addStretch()
    owner.inspector_scroll.setWidget(inspector)
    columns.addWidget(owner.inspector_scroll)
    work.addLayout(columns, 1)

    runtime = QFrame()
    runtime.setObjectName("runtimeBar")
    runtime.setFixedHeight(70)
    runtime_layout = QHBoxLayout(runtime)
    runtime_layout.setContentsMargins(24, 8, 22, 8)
    runtime_layout.setSpacing(10)
    owner.runtime_dot = label("●", "runtimeDot")
    runtime_layout.addWidget(owner.runtime_dot)
    runtime_copy = QVBoxLayout()
    runtime_copy.setSpacing(3)
    owner.runtime_title = label("等待添加点位", "runtimeTitle")
    owner.runtime_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    owner.tnumrd = owner.runtime_title
    owner.runtime_detail = label("添加并启用一个点位后即可开始", "runtimeDetail")
    owner.runtime_detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    runtime_copy.addWidget(owner.runtime_title)
    runtime_copy.addWidget(owner.runtime_detail)
    runtime_layout.addLayout(runtime_copy, 1)
    owner.bt_multiclick_stop = button("停止  F8", "stop", "dangerButton")
    owner.bt_multiclick_start = button("开始运行  F7", "play", "primaryButton")
    owner.bt_multiclick_start.setMinimumWidth(134)
    runtime_layout.addWidget(owner.bt_multiclick_stop)
    runtime_layout.addWidget(owner.bt_multiclick_start)
    work.addWidget(runtime)
    body.addWidget(workspace, 1)


WORKBENCH_STYLE = """
QMainWindow, QDialog, QWidget { background: #ffffff; color: #27302a; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 12px; }
QLabel { background: transparent; border: 0; }
QFrame#appHeader { border-bottom: 1px solid #e5eae3; }
QLabel#brandMark { background: #23734d; border-radius: 7px; }
QLabel#brandLabel { font-size: 18px; font-weight: 700; color: #244c34; }
QLabel#brandSubtitle { font-size: 8px; letter-spacing: 2px; color: #8e9b88; }
QLabel#breadcrumb { color: #6e7c6b; }
QLabel#eyebrow { font-size: 9px; letter-spacing: 1.5px; color: #8b9b80; }
QLabel#taskTitle { font-size: 24px; font-weight: 600; }
QLabel#saveStatus { color: #8f9d85; font-size: 10px; }
QLabel#fieldLabel { color: #8b987f; font-size: 10px; }
QLabel#mutedText, QLabel#runtimeDetail { color: #929e88; font-size: 11px; }
QLabel#smallNote, QLabel#listFootnote { color: #98a38d; font-size: 10px; }
QLabel#sideHeading { color: #71816a; font-size: 11px; padding-top: 18px; border-top: 1px solid #e2e8dc; }
QLabel#sideNote { color: #97a08d; font-size: 11px; padding-top: 2px; }
QLabel#inspectorTitle { font-size: 12px; font-weight: 600; }
QLabel#pointBadge { color: #809573; background: #edf3e8; border-radius: 4px; padding: 3px 7px; font-size: 10px; }
QLabel#sectionLabel { color: #8d9b80; font-size: 10px; padding-top: 12px; border-top: 1px solid #e6ecdf; }
QLabel#pointOrder, QLabel#pointCoordinates { color: #91a086; font-size: 10px; }
QLabel#pointName { font-size: 12px; font-weight: 500; }
QLabel#pointAction { color: #728267; font-size: 11px; }
QLabel#pointInterval { color: #607455; font-size: 11px; }
QLabel#runtimeTitle { font-size: 12px; font-weight: 500; }
QLabel#runtimeDot { color: #6e9461; font-size: 10px; }
QLabel#emptyTitle { font-size: 14px; color: #596d4c; padding-top: 12px; }
QLabel#floatBrand { font-size: 18px; font-weight: 700; color: #23734d; }
QFrame#profileSidebar, QFrame#profileSidebar QWidget { background: #f7f8f5; }
QFrame#profileSidebar { border-right: 1px solid #e5ebe1; }
QWidget#inspector, QScrollArea#inspectorScroll { background: #fcfdf9; border-left: 1px solid #e7ece1; }
QFrame#runtimeBar { border-top: 1px solid #e3eadd; background: #ffffff; }
QFrame#runOptions { border-top: 1px solid #e9ede5; border-bottom: 1px solid #e9ede5; background: #fcfdfb; }
QWidget#pointRow { background: transparent; }
QWidget#pointRow[pointEnabled="false"] QLabel { color: #a6af9d; }
QWidget#floatingWindow { border: 1px solid #d2dfcc; border-radius: 8px; }
QListWidget { border: 0; outline: 0; background: transparent; }
QListWidget#profileList::item { color: #65745e; min-height: 32px; padding: 6px 8px; border-radius: 6px; }
QListWidget#profileList::item:selected { background: #e8f0e5; color: #28633e; font-weight: 600; }
QListWidget#pointList::item { border: 1px solid transparent; border-bottom-color: #edf0e8; border-radius: 6px; }
QListWidget#pointList::item:selected { background: #f0f6ec; border-color: #cadcc1; }
QListWidget#pointList::item:hover { background: #f7faf4; }
QPushButton { min-height: 32px; border: 1px solid #dce3d6; border-radius: 5px; padding: 0 11px; background: #ffffff; color: #42523b; }
QPushButton:hover { background: #f4f8f0; border-color: #b9cbb0; }
QPushButton:pressed { background: #eaf1e5; }
QPushButton:focus { border-color: #729c5e; }
QPushButton:disabled { color: #b1baaa; border-color: #e8ece3; background: #f7f8f4; }
QPushButton#primaryButton { background: #23734d; border-color: #23734d; color: #ffffff; font-weight: 500; }
QPushButton#primaryButton:hover { background: #1d6342; }
QPushButton#primaryButton:disabled { background: #9eb9a5; border-color: #9eb9a5; color: #f0f5ee; }
QPushButton#dangerButton { color: #af6257; border-color: #ead7d2; }
QPushButton#dangerButton:disabled { color: #b4bcad; border-color: #e7ece2; background: #ffffff; }
QPushButton#dangerLink { color: #b16e60; border-color: transparent; background: transparent; }
QPushButton#ghostButton, QPushButton#sideButton, QPushButton#iconButton { border-color: transparent; background: transparent; }
QPushButton#iconButton { min-height: 22px; padding: 0; }
QPushButton::menu-indicator { image: none; width: 0; }
QPushButton#sideButton { text-align: left; padding-left: 6px; font-size: 11px; color: #7e8b75; }
QPushButton#ghostButton:hover, QPushButton#iconButton:hover, QPushButton#sideButton:hover { background: #edf3e7; }
QLineEdit, QComboBox, QSpinBox { min-height: 32px; padding: 0 8px; border: 1px solid #dce4d4; border-radius: 5px; background: #ffffff; color: #4b6040; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #7fa06e; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #a7b19e; background: #f6f8f2; }
QComboBox#plainCombo { border: 0; background: transparent; min-height: 26px; font-size: 11px; }
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox::down-arrow { image: url(__DOWN_ICON__); width: 12px; height: 12px; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; }
QCheckBox { background: transparent; spacing: 7px; }
QCheckBox::indicator { width: 12px; height: 12px; border: 1px solid #b6c3ab; border-radius: 2px; background: #ffffff; }
QCheckBox::indicator:checked { background: #347245; border-color: #347245; image: url(__CHECK_ICON__); }
QCheckBox::indicator:disabled { border-color: #d4decc; background: #eef2e9; }
QCheckBox::indicator:checked:disabled { background: #9fb197; }
QTextEdit { border: 1px solid #dfe6d7; border-radius: 6px; padding: 8px; background: #ffffff; selection-background-color: #d6e7cf; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
QScrollBar::handle:vertical { background: #dce5d3; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { color: #465a3d; background: #f6faef; border: 1px solid #dce5d2; padding: 5px; }
"""

_icon_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "workbench"
WORKBENCH_STYLE = WORKBENCH_STYLE.replace("__CHECK_ICON__", (_icon_root / "check.svg").as_posix())
WORKBENCH_STYLE = WORKBENCH_STYLE.replace("__DOWN_ICON__", (_icon_root / "chevron-down.svg").as_posix())
