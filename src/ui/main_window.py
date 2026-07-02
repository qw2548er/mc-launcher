"""主窗口模块。

实现 Minecraft 启动器的主界面，包含版本列表、启动按钮、快速设置和状态栏。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, QSize, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QEvent
)
from PyQt6.QtGui import QIcon, QFont, QPixmap, QPainter, QColor, QBrush, QLinearGradient
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QSlider, QStatusBar, QFrame,
    QFileDialog, QSizePolicy, QScrollArea, QStackedWidget, QSpacerItem,
    QGridLayout, QMessageBox, QApplication
)

from .widgets import (
    TitleBar, CardWidget, Toast, ToastType, LoadingSpinner, VersionListItem
)
from .styles import ThemeManager, Theme

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    launch_clicked = pyqtSignal(str)
    version_selected = pyqtSignal(str)
    install_version_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._selected_version: Optional[str] = None
        self._is_launching = False
        self._drag_position = None
        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        self._connect_signals()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("Minecraft Launcher"))
        self.setMinimumSize(1000, 650)
        self.resize(1100, 720)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._title_bar = TitleBar(self)
        root_layout.addWidget(self._title_bar)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        self._setup_version_list(content)
        self._setup_main_content(content)
        root_layout.addLayout(content, 1)

        self._setup_status_bar()

        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.maximize_clicked.connect(self._toggle_maximize)
        self._title_bar.close_clicked.connect(self._on_close)
        self._title_bar.settings_clicked.connect(self._open_settings)
        self._title_bar.account_clicked.connect(self._open_accounts)
        self._title_bar.downloads_clicked.connect(self._open_downloads)

    def _setup_version_list(self, parent_layout: QHBoxLayout) -> None:
        left_panel = QWidget()
        left_panel.setFixedWidth(280)
        left_panel.setObjectName("LeftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(60)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel(self.tr("版本列表"))
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setObjectName("IconButton")
        self._refresh_btn.setFixedSize(32, 32)
        self._refresh_btn.setToolTip(self.tr("刷新版本列表"))
        header_layout.addWidget(self._refresh_btn)

        self._install_btn = QPushButton("+")
        self._install_btn.setObjectName("IconButton")
        self._install_btn.setFixedSize(32, 32)
        self._install_btn.setToolTip(self.tr("安装新版本"))
        header_layout.addWidget(self._install_btn)

        left_layout.addWidget(header)

        self._version_list = QListWidget()
        self._version_list.setObjectName("VersionList")
        self._version_list.setSpacing(2)
        self._version_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_layout.addWidget(self._version_list, 1)

        filter_row = QWidget()
        filter_row.setFixedHeight(50)
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(12, 0, 12, 8)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems([
            self.tr("全部版本"),
            self.tr("正式版"),
            self.tr("快照版"),
            self.tr("已安装"),
        ])
        filter_layout.addWidget(self._filter_combo)

        left_layout.addWidget(filter_row)

        parent_layout.addWidget(left_panel)

        separator = QFrame()
        separator.setObjectName("Separator")
        separator.setFixedWidth(1)
        parent_layout.addWidget(separator)

    def _setup_main_content(self, parent_layout: QHBoxLayout) -> None:
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(40, 30, 40, 20)
        right_layout.setSpacing(20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 16, 0)
        scroll_layout.setSpacing(24)

        self._setup_welcome_section(scroll_layout)
        self._setup_launch_section(scroll_layout)
        self._setup_quick_settings(scroll_layout)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        right_layout.addWidget(scroll, 1)

        parent_layout.addWidget(right_panel, 1)

    def _setup_welcome_section(self, parent_layout: QVBoxLayout) -> None:
        welcome_card = CardWidget()
        wl = welcome_card.content_layout
        wl.setContentsMargins(28, 24, 28, 24)
        wl.setSpacing(16)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        self._avatar_label = QLabel()
        self._avatar_label.setObjectName("AvatarLabel")
        self._avatar_label.setFixedSize(48, 48)
        self._avatar_label.setStyleSheet(
            "border-radius: 24px; background-color: #7C3AED;"
        )
        self._avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar_label.setText("👤")
        top_row.addWidget(self._avatar_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        self._welcome_label = QLabel(self.tr("欢迎回来，玩家！"))
        self._welcome_label.setStyleSheet("font-size: 22px; font-weight: 800;")
        text_col.addWidget(self._welcome_label)

        self._account_label = QLabel(self.tr("离线模式 · 未登录"))
        self._account_label.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        text_col.addWidget(self._account_label)

        top_row.addLayout(text_col, 1)
        wl.addLayout(top_row)

        parent_layout.addWidget(welcome_card)

    def _setup_launch_section(self, parent_layout: QVBoxLayout) -> None:
        launch_card = CardWidget()
        ll = launch_card.content_layout
        ll.setContentsMargins(28, 28, 28, 28)
        ll.setSpacing(20)
        ll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        version_row = QHBoxLayout()
        version_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_row.setSpacing(12)

        prefix_label = QLabel(self.tr("当前版本:"))
        prefix_label.setStyleSheet("font-size: 14px; color: #9CA3AF;")
        version_row.addWidget(prefix_label)

        self._version_display = QLabel(self.tr("请选择版本"))
        self._version_display.setStyleSheet("font-size: 18px; font-weight: 700;")
        version_row.addWidget(self._version_display)

        ll.addLayout(version_row)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._launch_btn = QPushButton(self.tr("启动游戏"))
        self._launch_btn.setObjectName("LaunchButton")
        self._launch_btn.setFixedSize(280, 70)
        self._launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._launch_btn.clicked.connect(self._on_launch)
        self._launch_btn.setEnabled(False)
        btn_row.addWidget(self._launch_btn)

        ll.addLayout(btn_row)

        self._launch_spinner = LoadingSpinner(self, size=32)
        self._launch_spinner.hide()

        parent_layout.addWidget(launch_card)

    def _setup_quick_settings(self, parent_layout: QVBoxLayout) -> None:
        settings_card = CardWidget()
        sl = settings_card.content_layout
        sl.setContentsMargins(24, 20, 24, 20)
        sl.setSpacing(16)

        title = QLabel(self.tr("快速设置"))
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        sl.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(1, 1)

        mem_label = QLabel(self.tr("内存分配"))
        mem_label.setStyleSheet("color: #9CA3AF;")
        grid.addWidget(mem_label, 0, 0)

        mem_row = QHBoxLayout()
        mem_row.setSpacing(12)
        self._memory_slider = QSlider(Qt.Orientation.Horizontal)
        self._memory_slider.setRange(1, 32)
        self._memory_slider.setValue(4)
        self._memory_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._memory_slider.setTickInterval(1)
        mem_row.addWidget(self._memory_slider, 1)
        self._memory_value = QLabel("4 GB")
        self._memory_value.setMinimumWidth(60)
        self._memory_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mem_row.addWidget(self._memory_value)
        self._memory_slider.valueChanged.connect(
            lambda v: self._memory_value.setText(f"{v} GB")
        )
        grid.addLayout(mem_row, 0, 1)

        java_label = QLabel(self.tr("Java 路径"))
        java_label.setStyleSheet("color: #9CA3AF;")
        grid.addWidget(java_label, 1, 0)

        java_row = QHBoxLayout()
        java_row.setSpacing(8)
        self._java_path_combo = QComboBox()
        self._java_path_combo.setEditable(True)
        self._java_path_combo.setPlaceholderText(self.tr("自动检测"))
        java_row.addWidget(self._java_path_combo, 1)
        self._browse_java_btn = QPushButton(self.tr("浏览"))
        self._browse_java_btn.setObjectName("IconButton")
        self._browse_java_btn.clicked.connect(self._browse_java)
        java_row.addWidget(self._browse_java_btn)
        grid.addLayout(java_row, 1, 1)

        dir_label = QLabel(self.tr("游戏目录"))
        dir_label.setStyleSheet("color: #9CA3AF;")
        grid.addWidget(dir_label, 2, 0)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self._game_dir_combo = QComboBox()
        self._game_dir_combo.setEditable(True)
        default_dir = str(Path.home() / ".minecraft")
        self._game_dir_combo.addItem(default_dir)
        dir_row.addWidget(self._game_dir_combo, 1)
        self._browse_dir_btn = QPushButton(self.tr("浏览"))
        self._browse_dir_btn.setObjectName("IconButton")
        self._browse_dir_btn.clicked.connect(self._browse_game_dir)
        dir_row.addWidget(self._browse_dir_btn)
        grid.addLayout(dir_row, 2, 1)

        sl.addLayout(grid)
        parent_layout.addWidget(settings_card)

    def _setup_status_bar(self) -> None:
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._java_status = QLabel(self.tr("Java: 未检测"))
        self._status_bar.addWidget(self._java_status)

        self._mem_status = QLabel(self.tr("内存: —"))
        self._status_bar.addPermanentWidget(self._mem_status)

        self._download_status = QLabel("")
        self._status_bar.addPermanentWidget(self._download_status)

    def _setup_tray(self) -> None:
        from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setToolTip(self.tr("Minecraft Launcher"))

        tray_menu = QMenu()
        show_action = tray_menu.addAction(self.tr("显示主窗口"))
        show_action.triggered.connect(self._show_from_tray)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction(self.tr("退出"))
        quit_action.triggered.connect(QApplication.instance().quit)
        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _connect_signals(self) -> None:
        self._version_list.currentItemChanged.connect(self._on_version_changed)
        self._refresh_btn.clicked.connect(self._refresh_versions)
        self._install_btn.clicked.connect(self._install_selected_version)

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._title_bar.set_maximized_state(False)
        else:
            self.showMaximized()
            self._title_bar.set_maximized_state(True)

    def _on_close(self) -> None:
        self.hide()
        Toast.info(self.tr("启动器已最小化到系统托盘"))

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _on_launch(self) -> None:
        if self._is_launching or not self._selected_version:
            return
        self._is_launching = True
        self._launch_btn.setEnabled(False)
        self._launch_btn.setText(self.tr("启动中..."))
        self._launch_spinner.start()
        self.launch_clicked.emit(self._selected_version)
        QTimer.singleShot(3000, self._reset_launch_button)

    def _reset_launch_button(self) -> None:
        self._is_launching = False
        self._launch_spinner.stop()
        self._launch_btn.setEnabled(self._selected_version is not None)
        self._launch_btn.setText(self.tr("启动游戏"))

    def _on_version_changed(self, current: QListWidgetItem, previous) -> None:
        if current is None:
            self._selected_version = None
            self._version_display.setText(self.tr("请选择版本"))
            self._launch_btn.setEnabled(False)
            return
        widget = self._version_list.itemWidget(current)
        if isinstance(widget, VersionListItem):
            self._selected_version = widget.version_id
            self._version_display.setText(widget.version_id)
            self._launch_btn.setEnabled(True)
            self.version_selected.emit(widget.version_id)

    def _refresh_versions(self) -> None:
        Toast.info(self.tr("正在刷新版本列表..."))

    def _install_selected_version(self) -> None:
        if self._selected_version:
            self.install_version_requested.emit(self._selected_version)

    def _browse_java(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择 Java 可执行文件"), "",
            "Java (*.exe java);;所有文件 (*)"
        )
        if path:
            self._java_path_combo.setCurrentText(path)

    def _browse_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, self.tr("选择游戏目录"), str(Path.home())
        )
        if path:
            self._game_dir_combo.setCurrentText(path)

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        dialog.exec()

    def _open_accounts(self) -> None:
        from .account_dialog import AccountDialog
        dialog = AccountDialog(self)
        dialog.exec()

    def _open_downloads(self) -> None:
        from .download_dialog import DownloadDialog
        dialog = DownloadDialog(self)
        dialog.exec()

    def populate_versions(self, versions: list[dict], installed: set[str] | None = None,
                          latest_release: str = "") -> None:
        self._version_list.clear()
        installed = installed or set()
        for v in versions:
            vid = v.get("id", "")
            vtype = v.get("type", "release")
            is_installed = vid in installed
            is_latest = vid == latest_release
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 70))
            widget = VersionListItem(vid, vtype, is_installed, is_latest)
            self._version_list.addItem(item)
            self._version_list.setItemWidget(item, widget)

    def set_account_info(self, username: str, is_microsoft: bool = False) -> None:
        self._welcome_label.setText(self.tr("欢迎回来，") + username + "！")
        account_type = self.tr("正版登录") if is_microsoft else self.tr("离线模式")
        self._account_label.setText(f"{account_type} · {username}")

    def set_java_status(self, version: str | None) -> None:
        if version:
            self._java_status.setText(self.tr("Java: ") + version)
        else:
            self._java_status.setText(self.tr("Java: 未检测"))

    def set_memory_status(self, used: int, total: int) -> None:
        self._mem_status.setText(f"内存: {used}MB / {total}MB")

    def set_download_status(self, text: str) -> None:
        self._download_status.setText(text)

    def get_memory_allocation(self) -> int:
        return self._memory_slider.value()

    def get_java_path(self) -> str:
        return self._java_path_combo.currentText()

    def get_game_dir(self) -> str:
        return self._game_dir_combo.currentText()

    def set_memory_allocation(self, gb: int) -> None:
        self._memory_slider.setValue(gb)

    def set_java_path(self, path: str) -> None:
        if self._java_path_combo.findText(path) == -1:
            self._java_path_combo.addItem(path)
        self._java_path_combo.setCurrentText(path)

    def set_game_dir(self, path: str) -> None:
        if self._game_dir_combo.findText(path) == -1:
            self._game_dir_combo.addItem(path)
        self._game_dir_combo.setCurrentText(path)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(50, lambda: ThemeManager.instance()._apply_theme())

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            self._title_bar.set_maximized_state(self.isMaximized())
        super().changeEvent(event)
