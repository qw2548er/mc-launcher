"""主窗口模块。

实现 Minecraft 启动器的主界面，包含版本列表、启动按钮、快速设置和状态栏。
集成真实版本管理、下载进度显示、游戏启动和日志显示功能。
"""

from __future__ import annotations

import logging
import os
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
    QGridLayout, QMessageBox, QApplication, QInputDialog
)

from .widgets import (
    TitleBar, CardWidget, Toast, ToastType, LoadingSpinner, VersionListItem
)
from .styles import ThemeManager, Theme
from .game_log_window import GameLogWindow

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


class LaunchThread(QThread):
    launch_started = pyqtSignal()
    launch_progress = pyqtSignal(str)
    launch_log = pyqtSignal(str, str)
    launch_finished = pyqtSignal(bool, str)
    game_exited = pyqtSignal(int)

    def __init__(
        self,
        version_id: str,
        username: str,
        java_path: str,
        game_dir: str,
        max_memory_gb: int,
        extra_jvm_args: str = "",
        account=None,
        server_address: str = "",
        server_port: int = 0,
    ):
        super().__init__()
        self._version_id = version_id
        self._username = username
        self._java_path = java_path
        self._game_dir = Path(game_dir)
        self._max_memory_gb = max_memory_gb
        self._extra_jvm_args = extra_jvm_args
        self._account = account
        self._server_address = server_address
        self._server_port = server_port
        self._launcher = None
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if self._launcher:
            self._launcher.kill()

    def run(self):
        try:
            from src.core.launcher import GameLauncher, LaunchError
            from src.core.java_detector import JavaDetector

            self.launch_started.emit()
            self.launch_progress.emit("正在初始化启动器...")

            launcher = GameLauncher()
            self._launcher = launcher

            account = self._account
            if account is None:
                from src.core.account import AccountInfo
                import uuid as uuid_mod
                account_uuid = str(uuid_mod.uuid3(uuid_mod.NAMESPACE_DNS, f"offline:{self._username}"))
                account = AccountInfo(
                    uuid=account_uuid,
                    type="offline",
                    username=self._username,
                )

            java_path = None
            if self._java_path:
                java_path = Path(self._java_path)
                self.launch_progress.emit(f"使用指定的 Java: {java_path}")
            else:
                self.launch_progress.emit("正在自动检测合适的 Java...")
                detector = JavaDetector()
                best_java = detector.get_best_match(self._version_id)
                if best_java:
                    java_path = best_java.path
                    self.launch_progress.emit(f"自动选择 Java {best_java.major_version} ({best_java.vendor})")
                else:
                    required_ver = JavaDetector.get_required_java_version(self._version_id)
                    raise LaunchError(f"未找到 Java {required_ver} 或更高版本。\n请安装 Java {required_ver} 后重试，或手动指定 Java 路径。")

            def on_log(line: str, level: str):
                self.launch_log.emit(line, level)

            def on_progress(status: str):
                self.launch_progress.emit(status)

            def on_exit(exit_code: int):
                self.game_exited.emit(exit_code)

            self.launch_progress.emit("正在执行启动前检查...")

            max_mem_mb = self._max_memory_gb * 1024
            check_result = launcher.pre_check(
                self._version_id,
                game_dir=self._game_dir,
                java_path=java_path,
                max_memory_mb=max_mem_mb
            )

            if not check_result.can_launch:
                error_msg = check_result.get_error_message()
                if check_result.warnings:
                    error_msg += "\n\n警告:\n" + check_result.get_warning_message()
                self.launch_finished.emit(False, error_msg)
                return

            if check_result.warnings:
                logger.warning("启动前检查警告:\n%s", check_result.get_warning_message())

            self.launch_progress.emit("正在启动游戏...")

            process = launcher.launch(
                version_id=self._version_id,
                account=account,
                java_path=java_path,
                max_memory_mb=max_mem_mb,
                min_memory_mb=min(512, max_mem_mb // 2),
                game_dir=self._game_dir,
                on_log=on_log,
                on_exit=on_exit,
                on_progress=on_progress,
                extra_jvm_args=self._extra_jvm_args if self._extra_jvm_args else None,
                server_address=self._server_address if self._server_address else None,
                server_port=self._server_port if self._server_port else None,
            )

            self.launch_finished.emit(True, "")

            process.wait()

        except Exception as e:
            logger.error("启动游戏异常: %s", e, exc_info=True)
            self.launch_finished.emit(False, str(e))


class MainWindow(QMainWindow):
    launch_clicked = pyqtSignal(str)
    version_selected = pyqtSignal(str)
    close_game_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._selected_version: Optional[str] = None
        self._is_launching = False
        self._is_game_running = False
        self._drag_position = None
        self._version_manager = None
        self._modloader_manager = None
        self._version_items: dict[str, VersionListItem] = {}
        self._all_versions: list[dict] = []
        self._installed_ids: set[str] = set()
        self._installed_loaders: dict[str, str] = {}
        self._latest_release: str = ""
        self._latest_snapshot: str = ""
        self._download_thread: Optional[DownloadThread] = None
        self._launch_thread: Optional[LaunchThread] = None
        self._downloading_version: Optional[str] = None
        self._launcher = None
        self._log_window: Optional[GameLogWindow] = None
        self._game_hide_launcher = True
        self._java_detector = None
        self._java_warning_widget: Optional[QFrame] = None
        self._account_manager = None
        self._game_dir: Optional[Path] = None

        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        self._connect_signals()

        QTimer.singleShot(100, self._init_version_manager)
        QTimer.singleShot(200, self._init_account_manager)

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
            from src.modloader import ModLoaderManager
            config = get_config()
            self._game_dir = Path(config.get("game_directory", str(Path.home() / ".minecraft")))
            self._version_manager = VersionManager(game_dir=self._game_dir)
            self._modloader_manager = ModLoaderManager(game_dir=self._game_dir)
            self._load_versions(force_refresh=False)
            self._init_launcher()
        except Exception as e:
            logger.error("初始化版本管理器失败: %s", e, exc_info=True)
            Toast.error(f"版本管理器初始化失败: {e}")

    def _init_launcher(self):
        try:
            from src.core.java_detector import JavaDetector
            from src.utils.config import get_config
            config = get_config()
            self._java_detector = JavaDetector()
            javas = self._java_detector.scan()
            self._java_path_combo.clear()
            self._java_path_combo.addItem(self.tr("自动选择最合适的 Java"), "")
            for j in javas:
                vendor = j.vendor.split(" ")[0] if j.vendor else ""
                label = f"Java {j.major_version}"
                if vendor and vendor != "Unknown":
                    label += f" ({vendor})"
                label += f" - {j.path}"
                self._java_path_combo.addItem(label, str(j.path))

            saved_java = config.get("java_path", "")
            if saved_java:
                idx = self._java_path_combo.findData(saved_java)
                if idx >= 0:
                    self._java_path_combo.setCurrentIndex(idx)
                else:
                    self._java_path_combo.addItem(saved_java, saved_java)
                    self._java_path_combo.setCurrentIndex(self._java_path_combo.count() - 1)

            game_dir = config.get("game_directory", str(Path.home() / ".minecraft"))
            if self._game_dir_combo.findText(game_dir) == -1:
                self._game_dir_combo.addItem(game_dir)
            self._game_dir_combo.setCurrentText(game_dir)

            max_mem_mb = config.get("java_args.max_memory_mb", 4096)
            max_mem_gb = max(1, max_mem_mb // 1024)
            self._memory_slider.setValue(max_mem_gb)
            self._memory_value.setText(f"{max_mem_gb} GB")

            saved_username = config.get("offline_username", "Steve")
            saved_java = config.get("java_path", "")

            if self._selected_version:
                self._check_java_compatibility()
            elif javas:
                best = javas[0]
                self.set_java_status(f"Java {best.major_version}")
            else:
                self.set_java_status(self.tr("未检测到"))

        except Exception as e:
            logger.error("初始化 Java 检测器失败: %s", e, exc_info=True)

    def _init_account_manager(self):
        try:
            from src.core.account import AccountManager
            from src.core.skin_manager import get_skin_manager

            self._account_manager = AccountManager()
            self._account_manager.load()

            accounts = self._account_manager.get_all()
            if not accounts:
                from src.utils.config import get_config
                config = get_config()
                default_name = config.get("offline_username", "Steve")
                try:
                    self._account_manager.add_offline_account(default_name)
                except ValueError:
                    self._account_manager.add_offline_account("Steve")

            self._refresh_account_display()
        except Exception as e:
            logger.error("初始化账号管理器失败: %s", e, exc_info=True)

    def _refresh_account_display(self):
        if not self._account_manager:
            return

        selected = self._account_manager.get_selected()
        if not selected:
            self._welcome_label.setText(self.tr("欢迎回来，玩家！"))
            self._account_label.setText(self.tr("未登录"))
            self._change_name_btn.setText(self.tr("添加账号"))
            self._title_bar.update_accounts([], "")
            self._title_bar.set_account(None)
            return

        self._welcome_label.setText(self.tr("欢迎回来，") + selected.username + "！")
        type_text = self.tr("正版登录") if selected.is_microsoft else self.tr("离线模式")
        self._account_label.setText(f"{type_text} · {selected.username}")

        if selected.is_microsoft:
            valid = self._account_manager.ensure_valid_token(selected)
            if valid is None and selected.is_token_expired:
                self._account_label.setStyleSheet("color: #EF4444; font-size: 13px;")
            else:
                self._account_label.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        else:
            self._account_label.setStyleSheet("color: #9CA3AF; font-size: 13px;")

        self._change_name_btn.setText(self.tr("切换账号") if self._account_manager.get_count() > 1 else self.tr("管理账号"))

        accounts_data = []
        for acc in self._account_manager.get_all():
            accounts_data.append({
                "uuid": acc.uuid,
                "username": acc.username,
                "type": acc.type,
            })
        self._title_bar.update_accounts(accounts_data, selected.uuid)
        self._title_bar.set_account(selected)

        self._load_account_avatar(selected)

    def _load_account_avatar(self, account):
        try:
            from src.core.skin_manager import get_skin_manager
            from PyQt6.QtCore import QThread, pyqtSignal as Signal

            class _AvatarThread(QThread):
                loaded = Signal(str, str)
                def __init__(self, uuid_str, username, skin_url, size):
                    super().__init__()
                    self.uuid = uuid_str
                    self.username = username
                    self.skin_url = skin_url
                    self.size = size
                def run(self):
                    try:
                        mgr = get_skin_manager()
                        p = mgr.get_avatar(self.uuid, self.username, self.skin_url, size=self.size, download=True)
                        if p:
                            self.loaded.emit(self.uuid, str(p))
                    except Exception:
                        pass

            def on_avatar(uuid_str, path):
                try:
                    from PyQt6.QtGui import QPixmap
                    pm = QPixmap(path)
                    if not pm.isNull():
                        scaled = pm.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.FastTransformation)
                        self._avatar_label.setPixmap(scaled)
                        self._avatar_label.setText("")
                        self._avatar_label.setStyleSheet("border-radius: 24px;")
                except Exception:
                    pass

            mgr = get_skin_manager()
            cached = mgr.get_avatar_path(account.uuid, 64)
            if cached.exists() and cached.stat().st_size > 0:
                on_avatar(account.uuid, str(cached))
                return

            self._avatar_label.setText("⏳")
            t = _AvatarThread(account.uuid, account.username, account.skin_url, 64)
            t.loaded.connect(on_avatar)
            t.start()
            self._avatar_thread = t
        except Exception as e:
            logger.debug("加载头像失败: %s", e)

    def _switch_account_from_menu(self, account_uuid: str):
        if not self._account_manager:
            return
        self._account_manager.switch_account(account_uuid)
        self._refresh_account_display()
        from .widgets import Toast
        acc = self._account_manager.get_selected()
        if acc:
            Toast.success(self, self.tr("已切换到: ") + acc.username)

    def _add_account_from_menu(self):
        from .account_dialog import AccountDialog
        dialog = AccountDialog(self)
        dialog.accounts_changed.connect(self._refresh_account_display)
        dialog.exec()

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

        self._setup_left_panel(content)
        self._setup_main_content(content)
        root_layout.addLayout(content, 1)

        self._setup_status_bar()

        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.maximize_clicked.connect(self._toggle_maximize)
        self._title_bar.close_clicked.connect(self._on_close)
        self._title_bar.settings_clicked.connect(self._open_settings)
        self._title_bar.account_clicked.connect(self._open_accounts)
        self._title_bar.downloads_clicked.connect(self._open_downloads)

    def _setup_left_panel(self, parent_layout: QHBoxLayout) -> None:
        left_panel = QWidget()
        left_panel.setFixedWidth(300)
        left_panel.setObjectName("LeftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        tab_bar = QWidget()
        tab_bar.setFixedHeight(52)
        tab_bar.setObjectName("NavTabBar")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(12, 8, 12, 0)
        tab_bar_layout.setSpacing(4)

        self._nav_versions_btn = self._create_nav_btn(self.tr("版本"), True)
        self._nav_versions_btn.clicked.connect(lambda: self._switch_page(0))
        tab_bar_layout.addWidget(self._nav_versions_btn)

        self._nav_servers_btn = self._create_nav_btn(self.tr("多人"), False)
        self._nav_servers_btn.clicked.connect(lambda: self._switch_page(1))
        tab_bar_layout.addWidget(self._nav_servers_btn)

        left_layout.addWidget(tab_bar)

        self._left_stack = QStackedWidget()
        left_layout.addWidget(self._left_stack, 1)

        versions_page = QWidget()
        vp_layout = QVBoxLayout(versions_page)
        vp_layout.setContentsMargins(0, 0, 0, 0)
        vp_layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(52)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel(self.tr("版本列表"))
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setObjectName("IconButton")
        self._refresh_btn.setFixedSize(32, 32)
        self._refresh_btn.setToolTip(self.tr("刷新版本列表"))
        header_layout.addWidget(self._refresh_btn)

        vp_layout.addWidget(header)

        self._version_list = QListWidget()
        self._version_list.setObjectName("VersionList")
        self._version_list.setSpacing(2)
        self._version_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._version_list.setFrameShape(QFrame.Shape.NoFrame)
        vp_layout.addWidget(self._version_list, 1)

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

        vp_layout.addWidget(filter_row)

        self._left_stack.addWidget(versions_page)

        servers_sidebar = QWidget()
        ss_layout = QVBoxLayout(servers_sidebar)
        ss_layout.setContentsMargins(12, 8, 12, 12)
        ss_layout.setSpacing(8)

        ss_hint = QLabel(self.tr("点击右侧「多人游戏」标签管理服务器列表"))
        ss_hint.setWordWrap(True)
        ss_hint.setStyleSheet("color: #6B7280; font-size: 12px; padding: 8px;")
        ss_layout.addWidget(ss_hint)
        ss_layout.addStretch()

        self._left_stack.addWidget(servers_sidebar)

        parent_layout.addWidget(left_panel)

        separator = QFrame()
        separator.setObjectName("Separator")
        separator.setFixedWidth(1)
        parent_layout.addWidget(separator)

    def _create_nav_btn(self, text: str, active: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(active)
        btn.setFixedHeight(36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setProperty("nav_active", active)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #9CA3AF;
                font-size: 13px;
                font-weight: 600;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: rgba(55, 65, 81, 0.5);
                color: #D1D5DB;
            }
            QPushButton:checked {
                background: rgba(124, 58, 237, 0.2);
                color: #A855F7;
            }
        """)
        return btn

    def _switch_page(self, index: int) -> None:
        self._nav_versions_btn.setChecked(index == 0)
        self._nav_servers_btn.setChecked(index == 1)
        self._left_stack.setCurrentIndex(index)
        self._right_stack.setCurrentIndex(index)

        if index == 1 and hasattr(self, '_server_page') and self._server_page:
            QTimer.singleShot(100, self._server_page._refresh_all)

    def _setup_main_content(self, parent_layout: QHBoxLayout) -> None:
        self._right_stack = QStackedWidget()

        home_page = QWidget()
        home_layout = QVBoxLayout(home_page)
        home_layout.setContentsMargins(40, 30, 40, 20)
        home_layout.setSpacing(20)

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
        home_layout.addWidget(scroll, 1)

        self._right_stack.addWidget(home_page)

        from .server_page import ServerPage
        self._server_page = ServerPage(self)
        self._server_page.join_server_requested.connect(self._join_server_direct)
        self._right_stack.addWidget(self._server_page)

        parent_layout.addWidget(self._right_stack, 1)

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

        self._change_name_btn = QPushButton(self.tr("更改用户名"))
        self._change_name_btn.setObjectName("SecondaryButton")
        self._change_name_btn.setFixedHeight(32)
        self._change_name_btn.clicked.connect(self._change_username)
        top_row.addWidget(self._change_name_btn)

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

        self._launch_status = QLabel("")
        self._launch_status.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        self._launch_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._launch_status.hide()
        ll.addWidget(self._launch_status)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row.setSpacing(12)

        self._launch_btn = QPushButton(self.tr("启动游戏"))
        self._launch_btn.setObjectName("LaunchButton")
        self._launch_btn.setFixedSize(220, 60)
        self._launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._launch_btn.clicked.connect(self._on_launch)
        self._launch_btn.setEnabled(False)
        btn_row.addWidget(self._launch_btn)

        self._log_btn = QPushButton(self.tr("游戏日志"))
        self._log_btn.setObjectName("SecondaryButton")
        self._log_btn.setFixedSize(120, 60)
        self._log_btn.clicked.connect(self._show_log_window)
        btn_row.addWidget(self._log_btn)

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
        self._memory_slider.valueChanged.connect(self._on_memory_changed)
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

        show_log_action = tray_menu.addAction(self.tr("显示游戏日志"))
        show_log_action.triggered.connect(self._show_log_window)

        tray_menu.addSeparator()
        self._kill_action = tray_menu.addAction(self.tr("终止游戏"))
        self._kill_action.setEnabled(False)
        self._kill_action.triggered.connect(self._kill_game)

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
        self.close_game_requested.connect(self._kill_game)
        self._java_path_combo.editTextChanged.connect(self._on_java_path_changed)
        self._game_dir_combo.editTextChanged.connect(self._on_game_dir_changed)

        self._title_bar.switch_account_requested.connect(self._switch_account_from_menu)
        self._title_bar.add_account_requested.connect(self._add_account_from_menu)
        self._title_bar.manage_accounts_requested.connect(self._open_accounts)
        self._title_bar.mods_clicked.connect(self._open_mod_manager)
        self._title_bar.skins_clicked.connect(self._open_skin_manager)

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

        self._installed_loaders = {}
        if self._modloader_manager:
            try:
                modded_versions = self._modloader_manager.get_installed_modded_versions()
                for vid, loader_type in modded_versions:
                    self._installed_loaders[vid] = loader_type
                    if vid not in self._installed_ids:
                        self._installed_ids.add(vid)
                        is_existing = False
                        for v in self._all_versions:
                            if v.get("id") == vid:
                                is_existing = True
                                break
                        if not is_existing:
                            self._all_versions.append({
                                "id": vid,
                                "type": "local",
                                "release_time": "",
                                "url": "",
                                "loader_type": loader_type
                            })
            except Exception as e:
                logger.error("检测已安装模组加载器版本失败: %s", e)

        self._apply_filter()
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↻")
        total_installed = len(self._installed_ids)
        self.set_download_status(f"共 {len(versions) + len(self._installed_loaders)} 个版本，已安装 {total_installed} 个")

        from src.utils.config import get_config
        config = get_config()
        default_ver = config.get("default_version", "")
        if default_ver and default_ver in self._installed_ids:
            for i in range(self._version_list.count()):
                item = self._version_list.item(i)
                widget = self._version_list.itemWidget(item)
                if isinstance(widget, VersionListItem) and widget.version_id == default_ver:
                    self._version_list.setCurrentItem(item)
                    break
        elif self._installed_ids:
            for i in range(self._version_list.count()):
                item = self._version_list.item(i)
                widget = self._version_list.itemWidget(item)
                if isinstance(widget, VersionListItem) and widget.is_installed:
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

            loader_type = v.get("loader_type") or self._installed_loaders.get(vid, "vanilla")

            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 76))
            widget = VersionListItem(
                vid, vtype, release_time, is_installed, is_latest, loader_type
            )
            widget.download_clicked.connect(self._start_download)
            widget.cancel_clicked.connect(self._cancel_download)
            widget.delete_clicked.connect(self._delete_version)
            widget.install_loader_clicked.connect(self._open_install_loader_dialog)
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
        if self._is_game_running:
            reply = QMessageBox.question(
                self,
                self.tr("确认退出"),
                self.tr("游戏正在运行中，确定要退出启动器吗？\n游戏将继续运行。"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.hide()
        Toast.info(self.tr("启动器已最小化到系统托盘"))

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _change_username(self) -> None:
        self._open_accounts()

    def _on_launch(self) -> None:
        if self._is_launching or self._is_game_running:
            return

        if not self._selected_version:
            Toast.warning(self.tr("请先选择一个版本"))
            return

        if self._selected_version not in self._installed_ids:
            Toast.warning(self.tr("该版本尚未安装，请先下载"))
            return

        if not self._account_manager:
            Toast.error(self.tr("账号系统未初始化"))
            return

        account = self._account_manager.get_selected()
        if not account:
            Toast.warning(self.tr("请先添加一个账号"))
            self._open_accounts()
            return

        if account.is_microsoft:
            valid = self._account_manager.ensure_valid_token(account)
            if valid is None:
                Toast.error(self.tr("正版账号登录已过期，请重新登录"))
                self._open_accounts()
                return
            account = valid

        from src.utils.config import get_config
        config = get_config()
        username = account.username

        java_path = self._java_path_combo.currentData()
        if not java_path:
            java_path = self._java_path_combo.currentText()
        if java_path == self.tr("自动检测"):
            java_path = ""

        game_dir = self._game_dir_combo.currentText()
        if not game_dir:
            game_dir = str(Path.home() / ".minecraft")

        max_memory_gb = self._memory_slider.value()

        self._is_launching = True
        self._launch_btn.setEnabled(False)
        self._launch_btn.setText(self.tr("启动中..."))
        self._launch_spinner.show()
        self._launch_spinner.start()
        self._launch_status.show()
        self._launch_status.setText(self.tr("正在检查启动环境..."))
        self.set_download_status(self.tr("正在启动 Minecraft ") + self._selected_version + "...")

        self._log_window = GameLogWindow(self)
        self._log_window.set_game_running(True, self._selected_version)
        self._log_window.kill_requested.connect(self._kill_game)

        self._launch_thread = LaunchThread(
            version_id=self._selected_version,
            username=username,
            java_path=java_path,
            game_dir=game_dir,
            max_memory_gb=max_memory_gb,
            account=account,
        )
        self._launch_thread.launch_started.connect(self._on_launch_started)
        self._launch_thread.launch_progress.connect(self._on_launch_progress)
        self._launch_thread.launch_log.connect(self._on_launch_log)
        self._launch_thread.launch_finished.connect(self._on_launch_finished)
        self._launch_thread.game_exited.connect(self._on_game_exited)
        self._launch_thread.start()

    def _on_launch_started(self):
        pass

    def _on_launch_progress(self, status: str):
        self._launch_status.setText(status)
        if self._log_window:
            self._log_window.append_log(f"[Launcher] {status}", "INFO")

    def _on_launch_log(self, line: str, level: str):
        if self._log_window:
            self._log_window.append_log(line, level)

    def _on_launch_finished(self, success: bool, error_msg: str):
        self._launch_spinner.stop()
        self._launch_spinner.hide()

        if success:
            self._is_game_running = True
            self._is_launching = False
            self._launch_btn.setText(self.tr("游戏运行中"))
            self._launch_btn.setEnabled(False)
            self._launch_status.setText(self.tr("游戏已启动！"))
            self._launch_status.setStyleSheet("color: #10B981; font-size: 13px;")
            self._kill_action.setEnabled(True)
            self.set_download_status(self.tr("Minecraft ") + self._selected_version + self.tr(" 运行中"))

            self._log_window.show()

            from src.utils.config import get_config
            config = get_config()
            self._game_hide_launcher = config.get("launch.close_launcher", True)

            if self._game_hide_launcher:
                QTimer.singleShot(2000, self._hide_launcher_after_launch)

            Toast.success(self.tr("Minecraft ") + self._selected_version + self.tr(" 已启动！"))
        else:
            self._is_launching = False
            self._launch_btn.setEnabled(True)
            self._launch_btn.setText(self.tr("启动游戏"))
            self._launch_status.setText(self.tr("启动失败"))
            self._launch_status.setStyleSheet("color: #EF4444; font-size: 13px;")
            self.set_download_status(self.tr("启动失败"))

            if self._log_window:
                self._log_window.append_log(f"\n[Launcher] 启动失败: {error_msg}", "ERROR")
                self._log_window.show()

            QMessageBox.critical(
                self,
                self.tr("启动失败"),
                self.tr("无法启动 Minecraft:\n\n") + error_msg
            )

    def _hide_launcher_after_launch(self):
        if self._is_game_running:
            self.hide()

    def _on_game_exited(self, exit_code: int):
        self._is_game_running = False
        self._is_launching = False
        self._kill_action.setEnabled(False)

        can_launch = (self._selected_version is not None and
                      self._selected_version in self._installed_ids and
                      self._downloading_version is None)
        self._launch_btn.setEnabled(can_launch)
        self._launch_btn.setText(self.tr("启动游戏"))
        self._launch_status.hide()
        self.set_download_status(f"共 {len(self._all_versions)} 个版本，已安装 {len(self._installed_ids)} 个")

        if self._log_window:
            self._log_window.on_game_exit(exit_code)

        if self._game_hide_launcher and self.isHidden():
            self.showNormal()
            self.activateWindow()
            self.raise_()

        if exit_code == 0:
            Toast.info(self.tr("游戏已退出"))
        else:
            Toast.warning(self.tr(f"游戏异常退出 (退出码: {exit_code})"))

    def _kill_game(self):
        if self._launch_thread:
            self._launch_thread.cancel()
            self._is_game_running = False
            self._kill_action.setEnabled(False)

    def _show_log_window(self):
        if self._log_window is None:
            self._log_window = GameLogWindow(self)
            self._log_window.kill_requested.connect(self._kill_game)
        self._log_window.show()
        self._log_window.activateWindow()
        self._log_window.raise_()

    def _join_server_direct(self, address: str, port: int, name: str) -> None:
        if self._is_launching or self._is_game_running:
            Toast.warning(self.tr("游戏已在运行中"))
            return

        if not self._selected_version:
            Toast.warning(self.tr("请先在「版本」标签页选择一个版本"))
            self._switch_page(0)
            return

        if self._selected_version not in self._installed_ids:
            Toast.warning(self.tr("该版本尚未安装，请先下载"))
            self._switch_page(0)
            return

        if not self._account_manager:
            Toast.error(self.tr("账号系统未初始化"))
            return

        account = self._account_manager.get_selected()
        if not account:
            Toast.warning(self.tr("请先添加一个账号"))
            self._open_accounts()
            return

        if account.is_microsoft:
            valid = self._account_manager.ensure_valid_token(account)
            if valid is None:
                Toast.error(self.tr("正版账号登录已过期，请重新登录"))
                self._open_accounts()
                return
            account = valid

        from src.utils.config import get_config
        username = account.username

        java_path = self._java_path_combo.currentData()
        if not java_path:
            java_path = self._java_path_combo.currentText()
        if java_path == self.tr("自动检测"):
            java_path = ""

        game_dir = self._game_dir_combo.currentText()
        if not game_dir:
            game_dir = str(Path.home() / ".minecraft")

        max_memory_gb = self._memory_slider.value()

        self._is_launching = True
        self._nav_versions_btn.setChecked(True)
        self._nav_servers_btn.setChecked(False)
        self._left_stack.setCurrentIndex(0)
        self._right_stack.setCurrentIndex(0)
        self._launch_btn.setEnabled(False)
        self._launch_btn.setText(self.tr("启动中..."))
        self._launch_spinner.show()
        self._launch_spinner.start()
        self._launch_status.show()
        self._launch_status.setText(self.tr("正在加入服务器 ") + name + "...")
        self.set_download_status(self.tr("正在加入服务器 ") + name + "...")

        self._log_window = GameLogWindow(self)
        self._log_window.set_game_running(True, self._selected_version)
        self._log_window.kill_requested.connect(self._kill_game)

        self._launch_thread = LaunchThread(
            version_id=self._selected_version,
            username=username,
            java_path=java_path,
            game_dir=game_dir,
            max_memory_gb=max_memory_gb,
            account=account,
            server_address=address,
            server_port=port,
        )
        self._launch_thread.launch_started.connect(self._on_launch_started)
        self._launch_thread.launch_progress.connect(self._on_launch_progress)
        self._launch_thread.launch_log.connect(self._on_launch_log)
        self._launch_thread.launch_finished.connect(self._on_launch_finished)
        self._launch_thread.game_exited.connect(self._on_game_exited)
        self._launch_thread.start()

    def _reset_launch_button(self) -> None:
        self._is_launching = False
        self._launch_spinner.stop()
        can_launch = (self._selected_version is not None and
                      self._selected_version in self._installed_ids and
                      self._downloading_version is None and
                      not self._is_game_running)
        self._launch_btn.setEnabled(can_launch)
        self._launch_btn.setText(self.tr("启动游戏"))

    def _on_version_changed(self, current: QListWidgetItem, previous) -> None:
        if current is None:
            self._selected_version = None
            self._version_display.setText(self.tr("请选择版本"))
            self._launch_btn.setEnabled(False)
            self._hide_java_warning()
            return
        widget = self._version_list.itemWidget(current)
        if isinstance(widget, VersionListItem):
            self._selected_version = widget.version_id
            self._version_display.setText(widget.version_id)
            can_launch = (widget.version_id in self._installed_ids and
                          self._downloading_version is None and
                          not self._is_game_running)
            self._launch_btn.setEnabled(can_launch)
            self.version_selected.emit(widget.version_id)
            self._check_java_compatibility()

    def _refresh_versions(self) -> None:
        Toast.info(self.tr("正在刷新版本列表..."))
        self._load_versions(force_refresh=True)

    def _start_download(self, version_id: str):
        if self._downloading_version is not None:
            Toast.warning(f"已有版本正在下载: {self._downloading_version}")
            return
        if self._is_game_running:
            Toast.warning(self.tr("游戏正在运行中，请先退出游戏"))
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
        if self._is_game_running:
            Toast.warning(self.tr("游戏正在运行中，请先退出游戏"))
            return

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

                if self._selected_version == version_id:
                    self._launch_btn.setEnabled(False)
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
                self._launch_btn.setEnabled(not self._is_game_running)
        else:
            if widget:
                widget.set_error(message)
            Toast.error(f"下载 {version_id} 失败: {message}")

        self.set_download_status(f"共 {len(self._all_versions)} 个版本，已安装 {len(self._installed_ids)} 个")

    def _on_memory_changed(self, value: int) -> None:
        self._memory_value.setText(f"{value} GB")
        try:
            from src.utils.config import get_config
            config = get_config()
            config.set("java_args.max_memory_mb", value * 1024)
            config.save()
        except Exception:
            pass

    def _on_java_path_changed(self, text: str) -> None:
        try:
            from src.utils.config import get_config
            config = get_config()
            config.set("java_path", text)
            config.save()
        except Exception:
            pass
        if self._selected_version:
            self._check_java_compatibility()

    def _check_java_compatibility(self) -> None:
        if not self._selected_version or not self._java_detector:
            self._hide_java_warning()
            return

        from src.core.java_detector import JavaDetector
        required_ver = JavaDetector.get_required_java_version(self._selected_version)

        java_path = self._java_path_combo.currentData()
        if not java_path:
            java_path = self._java_path_combo.currentText()

        selected_java = None
        if java_path and java_path != self.tr("自动选择最合适的 Java"):
            from pathlib import Path
            selected_java = self._java_detector.check_java(Path(java_path))
        else:
            selected_java = self._java_detector.get_best_match(self._selected_version)

        if selected_java is None:
            self._show_java_warning(
                self.tr(f"⚠️ 未找到 Java {required_ver}"),
                self.tr(f"Minecraft {self._selected_version} 需要 Java {required_ver} 或更高版本。"),
                required_ver
            )
            self.set_java_status(self.tr(f"需要 Java {required_ver}"), warning=True)
            return

        is_compat, reason = self._java_detector.check_compatibility(selected_java, self._selected_version)
        if not is_compat:
            self._show_java_warning(
                self.tr(f"⚠️ Java 版本不兼容"),
                self.tr(f"当前选择的 Java {selected_java.major_version} 不满足要求。{reason}"),
                required_ver
            )
            self.set_java_status(f"Java {selected_java.major_version}", warning=True)
        else:
            self._hide_java_warning()
            self.set_java_status(f"Java {selected_java.major_version} ✓")

    def _show_java_warning(self, title: str, message: str, required_version: int) -> None:
        if self._java_warning_widget is not None:
            self._hide_java_warning()

        self._java_warning_widget = QFrame()
        self._java_warning_widget.setStyleSheet("""
            QFrame {
                background: rgba(239, 68, 68, 0.15);
                border: 1px solid rgba(239, 68, 68, 0.4);
                border-radius: 8px;
                padding: 12px;
                margin: 0;
            }
        """)
        warn_layout = QHBoxLayout(self._java_warning_widget)
        warn_layout.setContentsMargins(12, 8, 12, 8)
        warn_layout.setSpacing(12)

        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size: 18px; border: none;")
        warn_layout.addWidget(icon_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #FCA5A5; font-weight: 700; font-size: 13px; border: none;")
        text_layout.addWidget(title_label)
        msg_label = QLabel(message)
        msg_label.setStyleSheet("color: #D1D5DB; font-size: 12px; border: none;")
        msg_label.setWordWrap(True)
        text_layout.addWidget(msg_label)
        warn_layout.addLayout(text_layout, 1)

        download_btn = QPushButton(self.tr("下载 Java"))
        download_btn.setObjectName("PrimaryButton")
        download_btn.setFixedHeight(32)
        download_btn.clicked.connect(lambda: self._open_java_download(required_version))
        warn_layout.addWidget(download_btn)

        main_content = self.findChild(QWidget, "MainContent")
        if main_content:
            layout = main_content.layout()
            if layout:
                launch_area = main_content.findChild(QWidget, "LaunchArea")
                if launch_area:
                    idx = layout.indexOf(launch_area)
                    if idx >= 0:
                        layout.insertWidget(idx, self._java_warning_widget)
                        return
                layout.addWidget(self._java_warning_widget)

    def _hide_java_warning(self) -> None:
        if self._java_warning_widget is not None:
            self._java_warning_widget.hide()
            self._java_warning_widget.deleteLater()
            self._java_warning_widget = None

    def _open_java_download(self, version: int) -> None:
        import webbrowser
        from src.core.java_detector import JavaDetector
        url = JavaDetector.get_java_download_url(version)
        webbrowser.open(url)

    def _on_game_dir_changed(self, text: str) -> None:
        try:
            from src.utils.config import get_config
            config = get_config()
            config.set("game_directory", text)
            config.save()
        except Exception:
            pass

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
        dialog.accounts_changed.connect(self._refresh_account_display)
        dialog.account_selected.connect(lambda uuid: self._refresh_account_display())
        dialog.exec()

    def _open_downloads(self) -> None:
        from .download_dialog import DownloadDialog
        dialog = DownloadDialog(self)
        dialog.exec()

    def _open_mod_manager(self) -> None:
        if not self._modloader_manager:
            Toast.warning(self.tr("模组管理器未初始化"))
            return
        try:
            from .mod_manager_dialog import ModManagerDialog
            dialog = ModManagerDialog(mods_dir=self._modloader_manager.mods_dir, parent=self)
            dialog.mods_changed.connect(self._on_mods_changed)
            dialog.exec()
        except Exception as e:
            logger.error("打开模组管理器失败: %s", e, exc_info=True)
            Toast.error(self.tr(f"打开模组管理器失败: {e}"))

    def _on_mods_changed(self):
        pass

    def _open_skin_manager(self) -> None:
        try:
            from .skin_dialog import SkinManagerDialog
            account = None
            if self._account_manager:
                account = self._account_manager.get_selected()
            dialog = SkinManagerDialog(account=account, parent=self)
            dialog.skin_changed.connect(self._on_skin_changed)
            dialog.exec()
        except Exception as e:
            logger.error("打开皮肤管理器失败: %s", e, exc_info=True)
            Toast.error(self.tr(f"打开皮肤管理器失败: {e}"))

    def _on_skin_changed(self):
        self._refresh_account_display()

    def _open_install_loader_dialog(self, version_id: str):
        if not self._game_dir:
            Toast.warning(self.tr("游戏目录未设置"))
            return
        try:
            from .modloader_install_dialog import ModLoaderInstallDialog
            dialog = ModLoaderInstallDialog(mc_version=version_id, game_dir=self._game_dir, parent=self)
            dialog.install_completed.connect(self._on_loader_installed)
            dialog.exec()
        except Exception as e:
            logger.error("打开加载器安装对话框失败: %s", e, exc_info=True)
            Toast.error(self.tr(f"打开安装对话框失败: {e}"))

    def _on_loader_installed(self, mc_version: str, loader_type: str, version_id: str):
        self._load_versions(force_refresh=True)
        loader_names = {
            "forge": "Forge",
            "fabric": "Fabric",
            "quilt": "Quilt",
            "neoforge": "NeoForge"
        }
        loader_name = loader_names.get(loader_type, loader_type.capitalize())
        Toast.success(self.tr(f"{loader_name} 加载器安装成功！"))

    def set_account_info(self, username: str, is_microsoft: bool = False) -> None:
        self._welcome_label.setText(self.tr("欢迎回来，") + username + "！")
        account_type = self.tr("正版登录") if is_microsoft else self.tr("离线模式")
        self._account_label.setText(f"{account_type} · {username}")

    def set_java_status(self, version: str | None, warning: bool = False) -> None:
        if version:
            self._java_status.setText(self.tr("Java: ") + version)
            if warning:
                self._java_status.setStyleSheet("color: #EF4444; font-weight: 600;")
            else:
                self._java_status.setStyleSheet("")
        else:
            self._java_status.setText(self.tr("Java: 未检测"))
            self._java_status.setStyleSheet("color: #F59E0B;")

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
        idx = self._java_path_combo.findData(path)
        if idx >= 0:
            self._java_path_combo.setCurrentIndex(idx)
        elif self._java_path_combo.findText(path) == -1:
            self._java_path_combo.addItem(path, path)
            self._java_path_combo.setCurrentIndex(self._java_path_combo.count() - 1)
        else:
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
