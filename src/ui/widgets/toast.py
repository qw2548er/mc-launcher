"""Toast 消息提示组件。

提供自动消失的消息提示框，支持成功、警告、错误、信息四种类型。
"""

from enum import Enum
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, pyqtProperty
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QGraphicsOpacityEffect
)


class ToastType(Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class Toast(QWidget):
    _active_toasts: list["Toast"] = []

    def __init__(self, message: str, toast_type: ToastType = ToastType.INFO,
                 duration: int = 3000, parent=None):
        super().__init__(parent)
        self._message = message
        self._toast_type = toast_type
        self._duration = duration
        self._opacity = 1.0
        self._setup_ui()
        self._setup_animation()

    def _setup_ui(self) -> None:
        self.setObjectName("ToastWidget")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        icon_map = {
            ToastType.INFO: "ℹ️",
            ToastType.SUCCESS: "✅",
            ToastType.WARNING: "⚠️",
            ToastType.ERROR: "❌",
        }

        self._icon_label = QLabel(icon_map.get(self._toast_type, "ℹ️"))
        self._icon_label.setFixedSize(20, 20)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._msg_label = QLabel(self._message)
        self._msg_label.setWordWrap(True)
        self._msg_label.setMinimumWidth(200)
        self._msg_label.setMaximumWidth(400)
        layout.addWidget(self._msg_label)

        self.adjustSize()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

    def _setup_animation(self) -> None:
        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_out.finished.connect(self._on_faded_out)

        self._slide_in = QPropertyAnimation(self, b"pos")
        self._slide_in.setDuration(400)
        self._slide_in.setEasingCurve(QEasingCurve.Type.OutBack)

    def show(self) -> None:
        self._position_toast()
        super().show()
        QTimer.singleShot(self._duration, self._start_fade_out)

    def _position_toast(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.width() - self.width() - 24
        y = geo.height() - self.height() - 24
        offset = len(Toast._active_toasts) * (self.height() + 8)
        y -= offset
        self._slide_in.setStartValue(QPoint(x + 50, y))
        self._slide_in.setEndValue(QPoint(x, y))
        self.move(x, y)
        self._slide_in.start()

    def _start_fade_out(self) -> None:
        self._fade_out.start()

    def _on_faded_out(self) -> None:
        if self in Toast._active_toasts:
            Toast._active_toasts.remove(self)
        self.close()
        self._reposition_toasts()

    @classmethod
    def _reposition_toasts(cls) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        for i, toast in enumerate(cls._active_toasts):
            x = geo.width() - toast.width() - 24
            y = geo.height() - toast.height() - 24 - i * (toast.height() + 8)
            anim = QPropertyAnimation(toast, b"pos")
            anim.setDuration(200)
            anim.setEndValue(QPoint(x, y))
            anim.start()

    @classmethod
    def show_message(cls, message: str, toast_type: ToastType = ToastType.INFO,
                     duration: int = 3000) -> None:
        toast = cls(message, toast_type, duration)
        cls._active_toasts.append(toast)
        toast.show()

    @classmethod
    def info(cls, message: str, duration: int = 3000) -> None:
        cls.show_message(message, ToastType.INFO, duration)

    @classmethod
    def success(cls, message: str, duration: int = 3000) -> None:
        cls.show_message(message, ToastType.SUCCESS, duration)

    @classmethod
    def warning(cls, message: str, duration: int = 4000) -> None:
        cls.show_message(message, ToastType.WARNING, duration)

    @classmethod
    def error(cls, message: str, duration: int = 5000) -> None:
        cls.show_message(message, ToastType.ERROR, duration)
