"""主窗口模块。

实现 Minecraft 启动器的主界面，包含版本列表、启动按钮、快速设置和状态栏。
集成真实版本管理、下载进度显示功能。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, QSize, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QEvent, QThread
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


class VersionLoadThread(QThread):
    versions_loaded = pyqtSignal(list, set, str, str)
    load_failed = pyqtSignal(str)

    def __init__(self, version_manager, force_refresh=False):
        super().__init__()
        self._vm = version_manager
        self._force_refresh = force_refresh

    def run(self):
        try:
            manifest = self._vm.fetch_remote_versions(force_refresh=self._force_refresh)
            installed = self._vm.get_installed_versions()
            installed_ids = {v.id for v in installed}
            versions = []
            for v in manifest.versions:
                versions.append({
                    "id": v.id,
                    "type": v.type,
                    "release_time": v.release_time[:10] if v.release_time else "",
                    "url": v.url
                })
            self.versions_loaded.emit(
                versions,
                installed_ids,
                manifest.latest_release,
                manifest.latest_snapshot
            )
        except Exception as e:
            logger.error("加载版本列表失败: %s", e)
            self.load_failed.emit(str(e))


class DownloadThread(QThread):
    progress_updated = pyqtSignal(float, str, str, str)
    download_finished = pyqtSignal(bool, str)
    status_changed = pyqtSignal(str)

    def __init__(self, version_manager, version_id: str, include_assets: bool = True):
        super().__init__()
        self._vm = version_manager
        self._version_id = version_id
        self._include_assets = include_assets
        self._cancel = False

    def cancel(self):
        self._cancel = True
        self._vm.cancel_install()

    def run(self):
        try:
            self.status_changed.emit("正在获取版本信息...")

            def on_progress(report):
                if self._cancel:
                    return
                progress = report.progress
                speed = report.speed_formatted

                if report.remaining_time > 0:
                    remaining_secs = int(report.remaining_time)
                    if remaining_secs < 60:
                        eta = f"{remaining_secs}秒"
                    elif remaining_secs < 3600:
                        eta = f"{remaining_secs // 60}分{remaining_secs % 60}秒"
                    else:
                        eta = f"{remaining_secs // 3600}时{(remaining_secs % 3600) // 60}分"
                else:
                    eta = ""

                current_file = ""
                if report.current_item:
                    tag = report.current_item.tag or ""
                    if tag.startswith("asset:"):
                        current_file = tag.replace("asset:", "")
                    elif tag == "client":
                        current_file = "client.jar"
                    elif tag == "library":
                        current_file = report.current_item.path.name
                    elif tag == "native":
                        current_file = report.current_item.path.name
                    elif tag == "asset_index":
                        current_file = "资源索引"

                self.progress_updated.emit(progress, speed, eta, current_file)

            success = self._vm.install_version(
                self._version_id,
                progress_callback=on_progress,
                include_assets=self._include_assets
            )
            msg = "安装成功" if success else "安装失败"
            self.download_finished.emit(success, msg)
        except Exception as e:
            logger.error("下载版本异常: %s", e, exc_info=True)
            self.download_finished.emit(False, str(e))


class MainWindow(QMainWindow):
    launch_clicked = pyqtSignal(str)
    version_selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._selected_version: Optional[str] = None
        self._is_launching = False
        self._drag_position = None
        self._version_manager = None
        self._version_items: dict[str, VersionListItem] = {}
        self._all_versions: list[dict] = []
        self._installed_ids: set[str] = set()
        self._latest_release: str = ""
        self._latest_snapshot: str = ""
        self._download_thread: Optional[DownloadThread] = None
        self._downloading_version: Optional[str] = None

        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        self._connect_signals()

        QTimer.singleShot(100, self._init_version_manager)

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("Minecraft Launcher"))
        self.setMinimumSize(1000, 650)
        self.resize(1100, 720)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

    def _init_version_manager(self):
        try:
            from src.version.version_manager import VersionManager
            from src.utils.config import get_config
            config = get_config()
            game_dir = Path(config.get("game_directory", str(Path.home() / ".minecraft")))
            self._version_manager = VersionManager(game_dir=game_dir)
            self._load_versions(force_refresh=False)
        except Exception as e:
            logger.error("初始化版本管理器失败: %s", e, exc_info=True)
            Toast.error(f"版本管理器初始化失败: {e}")

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
        left_panel.setFixedWidth(300)
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

        left_layout.addWidget(header)

        self._version_list = QListWidget()
        self._version_list.setObjectName("VersionList")
        self._version_list.setSpacing(2)
        self._version_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._version_list.setFrameShape(QFrame.Shape.NoFrame)
        left_layout.addWidget(self._version_list, 1)

        filter_row = QWidget()
        filter_row.setFixedHeight(50)
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(12, 0, 12, 8)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems([
            self.tr("正式版"),
            self.tr("全部版本"),
            self.tr("快照版"),
            self.tr("远古版"),
            self.tr("已安装"),
        ])
        self._filter_combo.setCurrentIndex(0)
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
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)

    def _load_versions(self, force_refresh: bool = False):
        if self._version_manager is None:
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("⟳")
        self.set_download_status("正在加载版本列表...")

        self._load_thread = VersionLoadThread(self._version_manager, force_refresh)
        self._load_thread.versions_loaded.connect(self._on_versions_loaded)
        self._load_thread.load_failed.connect(self._on_versions_load_failed)
        self._load_thread.start()

    def _on_versions_loaded(self, versions, installed_ids, latest_release, latest_snapshot):
        self._all_versions = versions
        self._installed_ids = installed_ids
        self._latest_release = latest_release
        self._latest_snapshot = latest_snapshot
        self._apply_filter()
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↻")
        self.set_download_status(f"共 {len(versions)} 个版本，已安装 {len(installed_ids)} 个")

        from src.utils.config import get_config
        config = get_config()
        default_ver = config.get("default_version", "")
        if default_ver and default_ver in installed_ids:
            for i in range(self._version_list.count()):
                item = self._version_list.item(i)
                widget = self._version_list.itemWidget(item)
                if isinstance(widget, VersionListItem) and widget.version_id == default_ver:
                    self._version_list.setCurrentItem(item)
                    break

    def _on_versions_load_failed(self, error):
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↻")
        self.set_download_status("版本列表加载失败")
        Toast.error(f"加载版本列表失败: {error}")

    def _apply_filter(self):
        if not self._all_versions:
            return

        filter_idx = self._filter_combo.currentIndex()
        self._version_list.clear()
        self._version_items.clear()

        filtered = []
        for v in self._all_versions:
            vtype = v.get("type", "release")
            vid = v.get("id", "")
            is_installed = vid in self._installed_ids

            if filter_idx == 0:
                if vtype == "release":
                    filtered.append(v)
            elif filter_idx == 1:
                filtered.append(v)
            elif filter_idx == 2:
                if vtype == "snapshot":
                    filtered.append(v)
            elif filter_idx == 3:
                if vtype in ("old_beta", "old_alpha"):
                    filtered.append(v)
            elif filter_idx == 4:
                if is_installed:
                    filtered.append(v)

        for v in filtered:
            vid = v.get("id", "")
            vtype = v.get("type", "release")
            release_time = v.get("release_time", "")
            is_installed = vid in self._installed_ids
            is_latest = vid == self._latest_release

            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 76))
            widget = VersionListItem(
                vid, vtype, release_time, is_installed, is_latest
            )
            widget.download_clicked.connect(self._start_download)
            widget.cancel_clicked.connect(self._cancel_download)
            widget.delete_clicked.connect(self._delete_version)
            self._version_list.addItem(item)
            self._version_list.setItemWidget(item, widget)
            self._version_items[vid] = widget

            if self._downloading_version == vid:
                widget.set_downloading(True)

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

        if self._selected_version not in self._installed_ids:
            Toast.warning("该版本尚未安装，请先下载")
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
        can_launch = (self._selected_version is not None and
                      self._selected_version in self._installed_ids and
                      self._downloading_version is None)
        self._launch_btn.setEnabled(can_launch)
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
            can_launch = (widget.version_id in self._installed_ids and
                          self._downloading_version is None)
            self._launch_btn.setEnabled(can_launch)
            self.version_selected.emit(widget.version_id)

    def _refresh_versions(self) -> None:
        Toast.info(self.tr("正在刷新版本列表..."))
        self._load_versions(force_refresh=True)

    def _start_download(self, version_id: str):
        if self._downloading_version is not None:
            Toast.warning(f"已有版本正在下载: {self._downloading_version}")
            return

        reply = QMessageBox.question(
            self,
            "下载版本",
            f"确定要下载版本 {version_id} 吗？\n这将下载客户端、库文件和资源文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._downloading_version = version_id
        widget = self._version_items.get(version_id)
        if widget:
            widget.set_downloading(True)
            widget.update_progress(0, "准备中...", "", "")

        self._launch_btn.setEnabled(False)
        self.set_download_status(f"正在下载 {version_id}...")

        self._download_thread = DownloadThread(
            self._version_manager, version_id, include_assets=True
        )
        self._download_thread.progress_updated.connect(self._on_download_progress)
        self._download_thread.download_finished.connect(self._on_download_finished)
        self._download_thread.status_changed.connect(self._on_download_status)
        self._download_thread.start()

    def _cancel_download(self, version_id: str):
        if self._download_thread and self._downloading_version == version_id:
            reply = QMessageBox.question(
                self,
                "取消下载",
                f"确定要取消下载 {version_id} 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._download_thread.cancel()
                Toast.info("下载已取消")

    def _delete_version(self, version_id: str):
        reply = QMessageBox.warning(
            self,
            "删除版本",
            f"确定要删除版本 {version_id} 吗？\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if self._version_manager.uninstall_version(version_id):
                self._installed_ids.discard(version_id)
                widget = self._version_items.get(version_id)
                if widget:
                    widget.set_installed(False)
                Toast.success(f"版本 {version_id} 已删除")
                self.set_download_status(f"共 {len(self._all_versions)} 个版本，已安装 {len(self._installed_ids)} 个")

                from src.utils.config import get_config
                config = get_config()
                if config.get("default_version", "") == version_id:
                    config.set("default_version", "")
                    config.save()
            else:
                Toast.error(f"删除版本 {version_id} 失败")
        except Exception as e:
            logger.error("删除版本失败: %s", e, exc_info=True)
            Toast.error(f"删除失败: {e}")

    def _on_download_progress(self, progress, speed, eta, current_file):
        widget = self._version_items.get(self._downloading_version)
        if widget:
            widget.update_progress(progress, speed, eta, current_file)
        self.set_download_status(
            f"下载 {self._downloading_version}: {progress:.1f}% | {speed}"
        )

    def _on_download_status(self, status):
        widget = self._version_items.get(self._downloading_version)
        if widget:
            widget.update_progress(0, status, "", "")

    def _on_download_finished(self, success, message):
        version_id = self._downloading_version
        self._downloading_version = None
        widget = self._version_items.get(version_id)

        if success:
            self._installed_ids.add(version_id)
            if widget:
                widget.set_installed(True)
            Toast.success(f"版本 {version_id} 下载完成！")

            from src.utils.config import get_config
            config = get_config()
            config.set("default_version", version_id)
            config.save()

            if self._selected_version == version_id:
                self._launch_btn.setEnabled(True)
        else:
            if widget:
                widget.set_error(message)
            Toast.error(f"下载 {version_id} 失败: {message}")

        self.set_download_status(f"共 {len(self._all_versions)} 个版本，已安装 {len(self._installed_ids)} 个")

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
