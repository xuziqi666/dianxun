from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QPainter, QColor, QPen
from PySide6.QtWidgets import QApplication, QWidget


def physical_geometry(screen):
    # QScreen positions are logical; Win32 monitor origins remain physical on
    # mixed-DPI desktops. Match by device name instead of scaling the origin.
    try:
        import win32api
        for monitor, _, rect in win32api.EnumDisplayMonitors():
            if win32api.GetMonitorInfo(monitor)["Device"].lower() == screen.name().lower():
                left, top, right, bottom = rect
                return QRect(left, top, right - left, bottom - top)
    except ImportError:
        pass
    geometry = screen.geometry()
    ratio = screen.devicePixelRatio()
    return QRect(geometry.x(), geometry.y(), round(geometry.width() * ratio), round(geometry.height() * ratio))


def logical_to_physical(pos):
    screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
    if not screen:
        return pos
    geometry = screen.geometry()
    physical = physical_geometry(screen)
    ratio = screen.devicePixelRatio()
    return QPoint(physical.x() + round((pos.x() - geometry.x()) * ratio),
                  physical.y() + round((pos.y() - geometry.y()) * ratio))


def physical_to_logical(x, y):
    for screen in QApplication.screens():
        geometry = screen.geometry()
        ratio = screen.devicePixelRatio()
        physical = physical_geometry(screen)
        if physical.contains(QPoint(x, y)):
            return QPoint(geometry.x() + round((x - physical.x()) / ratio),
                          geometry.y() + round((y - physical.y()) / ratio))
    return QPoint(x, y)


def desktop_geometry():
    screens = QApplication.screens()
    geometry = screens[0].geometry()
    for screen in screens[1:]:
        geometry = geometry.united(screen.geometry())
    return geometry


class PickPointOverlay(QWidget):
    pointPicked = Signal(int, int)
    finished = Signal()

    def __init__(self, stream_mode=False, message=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.stream_mode = stream_mode
        self.message = message or "单击添加目标位置 · Esc 取消"
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(desktop_geometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(19, 37, 23, 60))
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QApplication.font())
        painter.fillRect(0, 0, self.width(), 48, QColor(26, 58, 37, 230))
        painter.drawText(QRect(0, 0, self.width(), 48), Qt.AlignCenter, self.message)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = logical_to_physical(event.globalPosition().toPoint())
        self.pointPicked.emit(pos.x(), pos.y())
        if not self.stream_mode:
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.finished.emit()
        event.accept()


class PointMarkerOverlay(QWidget):
    def __init__(self, points):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.points = points
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(desktop_geometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for index, point in enumerate(self.points, 1):
            pos = physical_to_logical(point.x, point.y) - self.geometry().topLeft()
            painter.setBrush(QColor("#23734d" if point.enabled else "#83917c"))
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(pos, 13, 13)
            painter.drawText(QRect(pos.x() - 13, pos.y() - 13, 26, 26), Qt.AlignCenter, str(index))
