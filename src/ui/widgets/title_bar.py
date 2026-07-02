"""自定义标题栏组件。

提供无边框窗口的标题栏，包含最小化、最大化、关闭按钮和窗口拖动功能。
右上角显示当前账号头像，点击弹出账号切换菜单。
"""

from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QSize
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpacerItem, QMenu
)

from .player_avatar import PlayerAvatar


class TitleBar(QWidget):
    minimize_clicked = pyqtSignal()
    maximize_clicked = pyqtSignal()
    close_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    account_clicked = pyqtSignal()
    downloads_clicked = pyqtSignal()
    mods_clicked = pyqtSignal()
    skins_clicked = pyqtSignal()
    switch_account_requested = pyqtSignal(str)
    manage_accounts_requested = pyqtSignal()
    add_account_requested = pyqtSignal()

    def __init__(self, parent=None, title: str = "Minecraft Launcher"):
        super().__init__(parent)
        self._title = title
        self._is_maximized = False
        self._drag_position: QPoint | None = None
        self._accounts: list[dict] = []
        self._selected_uuid: str = ""
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

        self._mods_btn = self._create_icon_button("🧩", self.mods_clicked.emit, "模组管理")
        layout.addWidget(self._mods_btn)

        self._skins_btn = self._create_icon_button("👕", self.skins_clicked.emit, "皮肤管理")
        layout.addWidget(self._skins_btn)

        self._account_avatar = PlayerAvatar(size=34, parent=self)
        self._account_avatar.setToolTip("账号")
        self._account_avatar.clicked.connect(self._show_account_menu)
        layout.addWidget(self._account_avatar)

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

    def set_account_avatar(self, avatar_path: str):
        pm = QPixmap(avatar_path)
        if not pm.isNull():
            scaled = pm.scaled(
                34, 34,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation
            )
            from PyQt6.QtGui import QPainterPath
            result = QPixmap(34, 34)
            result.fill(Qt.GlobalColor.transparent)
            painter = QPainter(result)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, 34, 34)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, scaled)
            painter.end()
            self._account_avatar._pixmap = result
            self._account_avatar.update()

    def set_account(self, account) -> None:
        self._account_avatar.set_account(account)

    def update_accounts(self, accounts: list[dict], selected_uuid: str):
        self._accounts = accounts
        self._selected_uuid = selected_uuid

    def _show_account_menu(self):
        menu = QMenu(self)
        menu.setObjectName("AccountMenu")

        has_accounts = len(self._accounts) > 0
        selected_acc = None
        for acc in self._accounts:
            if acc.get("uuid") == self._selected_uuid:
                selected_acc = acc
                break

        if selected_acc:
            name = selected_acc.get("username", "未知")
            acc_type = "正版" if selected_acc.get("type") == "microsoft" else "离线"
            header = menu.addAction(f"  {name}  ({acc_type})")
            header.setEnabled(False)
            header.setStyleSheet("font-weight: bold; color: #A78BFA; padding: 8px 16px;")
            menu.addSeparator()

        for acc in self._accounts:
            uuid_str = acc.get("uuid", "")
            name = acc.get("username", "未知")
            is_microsoft = acc.get("type") == "microsoft"
            is_selected = uuid_str == self._selected_uuid

            prefix = "✓ " if is_selected else "    "
            label = f"{prefix}{name}  {'(MS)' if is_microsoft else '(离线)'}"
            action = menu.addAction(label)
            action.setData(uuid_str)
            if not is_selected:
                action.triggered.connect(
                    lambda checked, u=uuid_str: self.switch_account_requested.emit(u)
                )
            else:
                action.setEnabled(False)

        menu.addSeparator()

        add_action = menu.addAction("➕ 添加账号")
        add_action.triggered.connect(self.add_account_requested.emit)

        manage_action = menu.addAction("⚙ 管理账号...")
        manage_action.triggered.connect(self.manage_accounts_requested.emit)

        if not has_accounts:
            header = menu.actions()[0] if menu.actions() else None
            if header:
                header.setText("  未登录")

        menu.exec(self._account_avatar.mapToGlobal(
            QPoint(self._account_avatar.width() - 220, self._account_avatar.height())
        ))

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
