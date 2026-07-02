"""加载动画组件。

提供旋转圆圈动画，用于表示加载状态。
"""

from PyQt6.QtCore import Qt, QTimer, QRectF, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QConicalGradient, QPaintEvent
from PyQt6.QtWidgets import QWidget


class LoadingSpinner(QWidget):
    def __init__(self, parent=None, center_on_parent: bool = True,
                 size: int = 40, color: str = "#7C3AED"):
        super().__init__(parent)
        self._size = size
        self._color = QColor(color)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._is_spinning = False
        self.setFixedSize(size, size)
        if center_on_parent and parent is not None:
            self._center_to_parent()

    def _center_to_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.move(
                (parent.width() - self.width()) // 2,
                (parent.height() - self.height()) // 2
            )

    def start(self) -> None:
        if not self._is_spinning:
            self._timer.start(16)
            self._is_spinning = True
            self.show()

    def stop(self) -> None:
        self._timer.stop()
        self._is_spinning = False
        self.hide()

    def is_spinning(self) -> bool:
        return self._is_spinning

    def _rotate(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen_width = max(3, self._size // 10)
        rect = QRectF(
            pen_width,
            pen_width,
            self._size - pen_width * 2,
            self._size - pen_width * 2
        )

        gradient = QConicalGradient(rect.center(), self._angle)
        base_color = QColor(self._color)
        base_color.setAlpha(0)
        gradient.setColorAt(0, base_color)
        gradient.setColorAt(0.7, self._color)
        gradient.setColorAt(1, self._color)

        pen = QPen(gradient, pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, self._angle * 16, 300 * 16)
