"""自定义标题栏组件。

提供无边框窗口的标题栏，包含最小化、最大化、关闭按钮和窗口拖动功能。
"""

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPainter, QColor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpacerItem
)


class TitleBar(QWidget):
    minimize_clicked = pyqtSignal()
    maximize_clicked = pyqtSignal()
    close_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    account_clicked = pyqtSignal()
    downloads_clicked = pyqtSignal()

    def __init__(self, parent=None, title: str = "Minecraft Launcher"):
        super().__init__(parent)
        self._title = title
        self._is_maximized = False
        self._drag_position: QPoint | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("TitleBar")
        self.setFixedHeight(48)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(4)

        self._logo_label = QLabel()
        self._logo_label.setFixedSize(28, 28)
        self._logo_label.setStyleSheet(
            "background-color: #7C3AED; border-radius: 6px;"
            "qproperty-alignment: AlignCenter;"
        )
        layout.addWidget(self._logo_label)

        self._title_label = QLabel(self._title)
        layout.addWidget(self._title_label)

        layout.addStretch()

        self._theme_btn = self._create_icon_button("🌙", self._toggle_theme, "切换主题")
        layout.addWidget(self._theme_btn)

        self._downloads_btn = self._create_icon_button("⬇", self.downloads_clicked.emit, "下载管理")
        layout.addWidget(self._downloads_btn)

        self._account_btn = self._create_icon_button("👤", self.account_clicked.emit, "账号管理")
        layout.addWidget(self._account_btn)

        self._settings_btn = self._create_icon_button("⚙", self.settings_clicked.emit, "设置")
        layout.addWidget(self._settings_btn)

        layout.addItem(QSpacerItem(8, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

        self._min_btn = self._create_title_button("—", self.minimize_clicked.emit)
        layout.addWidget(self._min_btn)

        self._max_btn = self._create_title_button("□", self.maximize_clicked.emit)
        layout.addWidget(self._max_btn)

        self._close_btn = QPushButton("✕")
        self._close_btn.setObjectName("CloseButton")
        self._close_btn.setProperty("class", "TitleBarButton")
        self._close_btn.setFixedSize(46, 32)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.close_clicked.emit)
        self._close_btn.setToolTip("关闭")
        layout.addWidget(self._close_btn)

    def _create_title_button(self, text: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("TitleBarButton")
        btn.setFixedSize(46, 32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(callback)
        return btn

    def _create_icon_button(self, text: str, callback, tooltip: str = "") -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("IconButton")
        btn.setFixedSize(36, 36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(callback)
        btn.setToolTip(tooltip)
        return btn

    def _toggle_theme(self) -> None:
        from ..styles.theme_manager import ThemeManager
        ThemeManager.instance().toggle_theme()

    def set_maximized_state(self, is_maximized: bool) -> None:
        self._is_maximized = is_maximized
        self._max_btn.setText("❐" if is_maximized else "□")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_position is not None and event.buttons() == Qt.MouseButton.LeftButton:
            if self._is_maximized:
                self.maximize_clicked.emit()
                self._drag_position = QPoint(self.window().width() // 2, 10)
            self.window().move(event.globalPosition().toPoint() - self._drag_position)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_clicked.emit()
        super().mouseDoubleClickEvent(event)
