"""卡片组件。

提供圆角卡片容器，带阴影效果，用于组织界面内容。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFrame


class CardWidget(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CardWidget")
        self._clickable = False
        self._content_layout = QVBoxLayout(self)
        self._content_layout.setContentsMargins(20, 20, 20, 20)
        self._content_layout.setSpacing(12)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = clickable
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
