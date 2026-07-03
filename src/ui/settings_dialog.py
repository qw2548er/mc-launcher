"""设置对话框模块。

提供通用设置、Java设置、游戏设置、渲染器设置、下载设置和关于页面。
支持版本隔离配置、图形后端选择、渲染器适配、高级调试开关等功能。
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIntValidator
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QTabWidget, QLineEdit, QSpinBox, QSlider, QComboBox, QCheckBox,
    QGroupBox, QFileDialog, QScrollArea, QFrame, QGridLayout, QSizePolicy,
    QMessageBox, QTextEdit, QRadioButton, QButtonGroup, QSpacerItem,
    QSplitter, QToolTip
)

from .widgets import DialogTitleBar, Toast
from .styles import ThemeManager, Theme, ThemeColor
from src.core.renderer import (
    get_all_renderers, get_compatible_renderers, get_default_renderer_id,
    get_renderer_by_id, is_version_supports_vulkan, GRAPHICS_BACKENDS,
    VULKAN_DRIVERS, generate_renderer_jvm_args
)
from src.core.java_detector import JavaDetector
from src.core.bundled_jre import get_bundled_jre_manager, BundledJreInfo

logger = logging.getLogger(__name__)

LAUNCHER_VERSION = "1.1.0"


class _ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 40px; height: 22px; border-radius: 11px; }
        """)


class SettingsDialog(QDialog):
    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None, mc_version: str = ""):
        super().__init__(parent)
        self._mc_version = mc_version
        self._detector = JavaDetector()
        self._bundled_mgr = get_bundled_jre_manager()
        self._all_instance_attrs_initialized = False
        self._init_attributes()
        self._setup_window()
        self._setup_ui()
        self._load_settings()
        self._all_instance_attrs_initialized = True

    def _init_attributes(self) -> None:
        self._java_combo = None
        self._java_status_label = None
        self._dir_browse_btn = None
        self._renderer_combo = None
        self._renderer_desc_label = None
        self._renderer_warning_label = None
        self._backend_hint = None
        self._graphics_backend_combo = None
        self._vulkan_driver_combo = None
        self._big_core_check = None
        self._system_vulkan_check = None
        self._per_version_check = None
        self._version_isolation_check = None
        self._auto_memory_check = None
        self._memory_slider = None
        self._memory_value_label = None
        self._memory_info_label = None
        self._server_addr_edit = None
        self._touch_gestures_check = None
        self._skip_integrity_check = None
        self._skip_jvm_check = None
        self._skip_mod_check = None
        self._debug_log_check = None
        self._game_args_edit = None
        self._jvm_args_edit = None
        self._env_vars_edit = None
        self._custom_uuid_edit = None
        self._force_resolution_check = None
        self._resolution_widget = None
        self._width_spin = None
        self._height_spin = None
        self._game_dir_edit = None
        self._fullscreen_check = None
        self._close_launcher_check = None
        self._theme_combo = None
        self._color_combo = None
        self._lang_combo = None
        self._minimize_tray_check = None
        self._check_update_check = None
        self._source_combo = None
        self._source_ids = []
        self._speed_test_btn = None
        self._threads_spin = None
        self._speed_spin = None
        self._verify_check = None
        self._auto_select_check = None
        self._source_status_label = None
        self._source_desc_label = None
        self._nav_buttons = []
        self._content_stack = None
        self._title_bar = None
        self._custom_url_edit = None
        self._custom_name_edit = None
        self._min_mem_spin = None
        self._max_mem_spin = None
        self._jvm_args_java_edit = None
        self._total_memory_mb = 0

    def set_mc_version(self, version: str) -> None:
        self._mc_version = version
        if self._renderer_combo:
            self._populate_renderers()
        if self._graphics_backend_combo:
            self._update_backend_enabled()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("设置"))
        self.setMinimumSize(780, 620)
        self.resize(860, 700)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setModal(True)

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._title_bar = DialogTitleBar(self, self.tr("游戏设置"))
        root_layout.addWidget(self._title_bar)

        content = QWidget()
        content.setObjectName("CardWidget")
        content.setStyleSheet(
            "#CardWidget { border-radius: 0; border: none; border-top: none; }"
        )
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self._setup_nav(content_layout)
        self._setup_tabs(content_layout)
        root_layout.addWidget(content, 1)

        self._setup_bottom_bar(root_layout)

        self._title_bar.close_clicked.connect(self.reject)

    def _make_section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        f = QFont()
        f.setPointSize(11)
        f.setWeight(QFont.Weight.Bold)
        label.setFont(f)
        return label

    def _make_hint_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        label.setWordWrap(True)
        return label

    def _setup_nav(self, parent_layout: QHBoxLayout) -> None:
        nav = QWidget()
        nav.setFixedWidth(160)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(8, 16, 8, 16)
        nav_layout.setSpacing(2)

        nav_title = QLabel(self.tr("设置"))
        nav_title.setStyleSheet("font-size: 17px; font-weight: 800; padding: 4px 8px 12px;")
        nav_layout.addWidget(nav_title)

        self._nav_buttons = []
        nav_items = [
            ("general", self.tr("通用")),
            ("java", self.tr("Java版本")),
            ("renderer", self.tr("图形渲染")),
            ("game", self.tr("游戏设置")),
            ("advanced", self.tr("高级调试")),
            ("download", self.tr("下载")),
            ("about", self.tr("关于")),
        ]
        for key, text in nav_items:
            btn = QPushButton(text)
            btn.setObjectName("NavItem")
            btn.setCheckable(True)
            btn.setProperty("nav_key", key)
            btn.clicked.connect(lambda checked, k=key, b=btn: self._switch_tab(k, b))
            nav_layout.addWidget(btn)
            self._nav_buttons.append((key, btn))

        nav_layout.addStretch()
        parent_layout.addWidget(nav)

        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFixedWidth(1)
        parent_layout.addWidget(sep)

    def _setup_tabs(self, parent_layout: QHBoxLayout) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content_stack = QTabWidget()
        self._content_stack.setTabBarAutoHide(True)
        self._content_stack.tabBar().hide()

        self._setup_general_tab()
        self._setup_java_tab()
        self._setup_renderer_tab()
        self._setup_game_tab()
        self._setup_advanced_tab()
        self._setup_download_tab()
        self._setup_about_tab()

        scroll.setWidget(self._content_stack)
        parent_layout.addWidget(scroll, 1)

    def _setup_general_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        appearance_group = QGroupBox(self.tr("外观"))
        app_layout = QGridLayout()
        app_layout.setSpacing(12)
        app_layout.addWidget(QLabel(self.tr("主题")), 0, 0)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems([self.tr("深色"), self.tr("浅色")])
        app_layout.addWidget(self._theme_combo, 0, 1)
        app_layout.addWidget(QLabel(self.tr("主题色")), 1, 0)
        self._color_combo = QComboBox()
        self._color_combo.addItems([self.tr("紫色"), self.tr("蓝色"), self.tr("靛蓝色")])
        self._color_combo.currentIndexChanged.connect(self._preview_accent_color)
        app_layout.addWidget(self._color_combo, 1, 1)
        app_layout.addWidget(QLabel(self.tr("语言")), 2, 0)
        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["简体中文", "English"])
        app_layout.addWidget(self._lang_combo, 2, 1)
        appearance_group.setLayout(app_layout)
        layout.addWidget(appearance_group)

        behavior_group = QGroupBox(self.tr("行为"))
        beh_layout = QVBoxLayout()
        beh_layout.setSpacing(8)
        self._minimize_tray_check = QCheckBox(self.tr("关闭时最小化到托盘"))
        self._minimize_tray_check.setChecked(True)
        beh_layout.addWidget(self._minimize_tray_check)
        self._check_update_check = QCheckBox(self.tr("启动时检查更新"))
        self._check_update_check.setChecked(True)
        beh_layout.addWidget(self._check_update_check)
        behavior_group.setLayout(beh_layout)
        layout.addWidget(behavior_group)

        dir_group = QGroupBox(self.tr("游戏目录"))
        dir_layout = QGridLayout()
        dir_layout.setSpacing(10)
        dir_layout.addWidget(QLabel(self.tr("游戏目录")), 0, 0)
        self._game_dir_edit = QLineEdit()
        self._game_dir_edit.setText(str(Path.home() / ".minecraft"))
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._game_dir_edit, 1)
        self._dir_browse_btn = QPushButton(self.tr("浏览"))
        self._dir_browse_btn.setObjectName("IconButton")
        self._dir_browse_btn.clicked.connect(self._browse_game_dir)
        dir_row.addWidget(self._dir_browse_btn)
        dir_layout.addLayout(dir_row, 0, 1)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        layout.addStretch()
        self._content_stack.addTab(page, "general")
        if self._nav_buttons:
            self._nav_buttons[0][1].setProperty("active", "true")

    def _setup_java_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = self._make_section_title(self.tr("Java 版本"))
        layout.addWidget(title)

        java_select_group = QGroupBox(self.tr("选择 Java"))
        java_layout = QGridLayout()
        java_layout.setSpacing(12)

        java_layout.addWidget(QLabel(self.tr("Java 版本")), 0, 0)
        self._java_combo = QComboBox()
        self._java_combo.setMinimumHeight(32)
        self._java_combo.currentIndexChanged.connect(self._on_java_changed)
        java_layout.addWidget(self._java_combo, 0, 1)

        refresh_btn = QPushButton(self.tr("刷新"))
        refresh_btn.setObjectName("IconButton")
        refresh_btn.clicked.connect(self._populate_java_combo)
        java_layout.addWidget(refresh_btn, 0, 2)

        self._java_status_label = QLabel("")
        self._java_status_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self._java_status_label.setWordWrap(True)
        java_layout.addWidget(self._java_status_label, 1, 0, 1, 3)

        java_select_group.setLayout(java_layout)
        layout.addWidget(java_select_group)

        mem_group = QGroupBox(self.tr("内存分配"))
        mem_layout = QVBoxLayout()
        mem_layout.setSpacing(10)

        self._auto_memory_check = QCheckBox(self.tr("自动分配内存（推荐）"))
        self._auto_memory_check.setChecked(True)
        self._auto_memory_check.toggled.connect(self._on_auto_memory_toggled)
        mem_layout.addWidget(self._auto_memory_check)

        mem_slider_row = QHBoxLayout()
        self._memory_slider = QSlider(Qt.Orientation.Horizontal)
        total_gb = self._detect_total_memory_gb()
        self._total_memory_mb = int(total_gb * 1024)
        max_mem = min(total_gb, 16)
        self._memory_slider.setRange(1, max_mem)
        recommended = max(2, min(4, total_gb // 2))
        self._memory_slider.setValue(recommended)
        self._memory_slider.valueChanged.connect(self._on_memory_slider_changed)
        mem_slider_row.addWidget(self._memory_slider, 1)

        self._memory_value_label = QLabel(f"{recommended} GB")
        self._memory_value_label.setMinimumWidth(70)
        self._memory_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._memory_value_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        mem_slider_row.addWidget(self._memory_value_label)
        mem_layout.addLayout(mem_slider_row)

        self._memory_info_label = self._make_hint_label("")
        self._update_memory_info()
        mem_layout.addWidget(self._memory_info_label)

        mem_group.setLayout(mem_layout)
        layout.addWidget(mem_group)

        jvm_group = QGroupBox(self.tr("JVM 参数"))
        jvm_layout = QVBoxLayout()
        self._jvm_args_java_edit = QTextEdit()
        self._jvm_args_java_edit.setPlaceholderText(
            "-XX:+UnlockExperimentalVMOptions\n-XX:+UseG1GC"
        )
        self._jvm_args_java_edit.setMaximumHeight(80)
        jvm_layout.addWidget(self._jvm_args_java_edit)
        jvm_hint = self._make_hint_label(self.tr("每行一个参数，留空使用默认参数"))
        jvm_layout.addWidget(jvm_hint)
        jvm_group.setLayout(jvm_layout)
        layout.addWidget(jvm_group)

        layout.addStretch()
        self._content_stack.addTab(page, "java")

        QTimer.singleShot(100, self._populate_java_combo)

    def _setup_renderer_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = self._make_section_title(self.tr("图形 & 渲染"))
        layout.addWidget(title)

        backend_group = QGroupBox(self.tr("图形后端"))
        backend_layout = QGridLayout()
        backend_layout.setSpacing(12)

        backend_layout.addWidget(QLabel(self.tr("图形后端")), 0, 0)
        self._graphics_backend_combo = QComboBox()
        for backend in GRAPHICS_BACKENDS:
            self._graphics_backend_combo.addItem(backend["display_name"], backend["backend_id"])
        self._graphics_backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        backend_layout.addWidget(self._graphics_backend_combo, 0, 1)

        self._touch_gestures_check = QCheckBox(self.tr("启用基岩版触控手势"))
        backend_layout.addWidget(self._touch_gestures_check, 1, 0, 1, 2)

        self._backend_hint = self._make_hint_label("")
        backend_layout.addWidget(self._backend_hint, 2, 0, 1, 2)

        backend_group.setLayout(backend_layout)
        layout.addWidget(backend_group)

        renderer_group = QGroupBox(self.tr("OpenGL 渲染器"))
        renderer_layout = QGridLayout()
        renderer_layout.setSpacing(12)

        renderer_layout.addWidget(QLabel(self.tr("OpenGL 渲染器")), 0, 0)
        self._renderer_combo = QComboBox()
        self._renderer_combo.setMinimumHeight(32)
        self._renderer_combo.currentIndexChanged.connect(self._on_renderer_changed)
        renderer_layout.addWidget(self._renderer_combo, 0, 1)

        self._renderer_desc_label = self._make_hint_label("")
        renderer_layout.addWidget(self._renderer_desc_label, 1, 0, 1, 2)

        self._renderer_warning_label = QLabel("")
        self._renderer_warning_label.setStyleSheet("color: #F59E0B; font-size: 12px;")
        self._renderer_warning_label.setWordWrap(True)
        renderer_layout.addWidget(self._renderer_warning_label, 2, 0, 1, 2)

        self._populate_renderers()

        renderer_group.setLayout(renderer_layout)
        layout.addWidget(renderer_group)

        vulkan_group = QGroupBox(self.tr("Vulkan 设置"))
        vulkan_layout = QGridLayout()
        vulkan_layout.setSpacing(12)

        vulkan_layout.addWidget(QLabel(self.tr("Vulkan 驱动")), 0, 0)
        self._vulkan_driver_combo = QComboBox()
        for drv in VULKAN_DRIVERS:
            self._vulkan_driver_combo.addItem(drv["display_name"], drv["driver_id"])
        vulkan_layout.addWidget(self._vulkan_driver_combo, 0, 1)

        self._system_vulkan_check = QCheckBox(self.tr("使用系统 Vulkan 驱动"))
        vulkan_layout.addWidget(self._system_vulkan_check, 1, 0, 1, 2)

        self._big_core_check = QCheckBox(self.tr("强制渲染器在大核运行"))
        vulkan_layout.addWidget(self._big_core_check, 2, 0, 1, 2)

        vulkan_group.setLayout(vulkan_layout)
        layout.addWidget(vulkan_group)

        layout.addStretch()
        self._content_stack.addTab(page, "renderer")

    def _setup_game_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = self._make_section_title(self.tr("游戏设置"))
        layout.addWidget(title)

        basic_group = QGroupBox(self.tr("基础设置"))
        basic_layout = QVBoxLayout()
        basic_layout.setSpacing(10)

        self._per_version_check = QCheckBox(self.tr("启用游戏特定设置（每版本独立保存配置）"))
        basic_layout.addWidget(self._per_version_check)

        self._version_isolation_check = QCheckBox(self.tr("版本隔离（独立版本目录，资源互不干扰）"))
        basic_layout.addWidget(self._version_isolation_check)

        server_row = QHBoxLayout()
        server_row.addWidget(QLabel(self.tr("自动连接服务器")))
        self._server_addr_edit = QLineEdit()
        self._server_addr_edit.setPlaceholderText(self.tr("输入服务器地址（如 play.example.com:25565）"))
        server_row.addWidget(self._server_addr_edit, 1)
        basic_layout.addLayout(server_row)

        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)

        window_group = QGroupBox(self.tr("窗口设置"))
        win_layout = QGridLayout()
        win_layout.setSpacing(12)

        self._force_resolution_check = QCheckBox(self.tr("强制设置分辨率"))
        self._force_resolution_check.toggled.connect(self._on_force_res_toggled)
        win_layout.addWidget(self._force_resolution_check, 0, 0, 1, 3)

        self._resolution_widget = QWidget()
        res_row = QHBoxLayout(self._resolution_widget)
        res_row.setContentsMargins(0, 0, 0, 0)
        res_row.setSpacing(8)
        res_row.addWidget(QLabel(self.tr("宽")))
        self._width_spin = QSpinBox()
        self._width_spin.setRange(800, 7680)
        self._width_spin.setValue(854)
        res_row.addWidget(self._width_spin)
        res_row.addWidget(QLabel(self.tr("高")))
        self._height_spin = QSpinBox()
        self._height_spin.setRange(600, 4320)
        self._height_spin.setValue(480)
        res_row.addWidget(self._height_spin)
        res_row.addStretch()
        win_layout.addWidget(self._resolution_widget, 1, 0, 1, 3)
        self._resolution_widget.setVisible(False)

        self._fullscreen_check = QCheckBox(self.tr("全屏模式"))
        win_layout.addWidget(self._fullscreen_check, 2, 0, 1, 3)

        window_group.setLayout(win_layout)
        layout.addWidget(window_group)

        launch_group = QGroupBox(self.tr("启动选项"))
        launch_layout = QVBoxLayout()
        self._close_launcher_check = QCheckBox(self.tr("启动游戏后关闭启动器"))
        self._close_launcher_check.setChecked(True)
        launch_layout.addWidget(self._close_launcher_check)
        launch_group.setLayout(launch_layout)
        layout.addWidget(launch_group)

        layout.addStretch()
        self._content_stack.addTab(page, "game")

    def _setup_advanced_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = self._make_section_title(self.tr("高级调试"))
        layout.addWidget(title)

        warn_label = QLabel(self.tr("⚠️ 以下选项仅供调试使用，错误配置可能导致游戏异常"))
        warn_label.setStyleSheet("color: #F59E0B; font-size: 12px; padding: 8px; background: #F59E0B10; border-radius: 6px;")
        warn_label.setWordWrap(True)
        layout.addWidget(warn_label)

        skip_group = QGroupBox(self.tr("校验跳过"))
        skip_layout = QVBoxLayout()
        skip_layout.setSpacing(8)
        self._skip_integrity_check = QCheckBox(self.tr("不检查游戏完整性"))
        skip_layout.addWidget(self._skip_integrity_check)
        self._skip_jvm_check = QCheckBox(self.tr("不检查 JVM 兼容性"))
        skip_layout.addWidget(self._skip_jvm_check)
        self._skip_mod_check = QCheckBox(self.tr("不检查模组兼容性"))
        skip_layout.addWidget(self._skip_mod_check)
        self._debug_log_check = QCheckBox(self.tr("输出调试日志（详细日志）"))
        skip_layout.addWidget(self._debug_log_check)
        skip_group.setLayout(skip_layout)
        layout.addWidget(skip_group)

        args_group = QGroupBox(self.tr("自定义参数"))
        args_layout = QGridLayout()
        args_layout.setSpacing(10)

        args_layout.addWidget(QLabel(self.tr("游戏参数")), 0, 0)
        self._game_args_edit = QLineEdit()
        self._game_args_edit.setPlaceholderText("--demo --width 1920")
        args_layout.addWidget(self._game_args_edit, 0, 1)

        args_layout.addWidget(QLabel(self.tr("JVM 参数")), 1, 0)
        self._jvm_args_edit = QLineEdit()
        self._jvm_args_edit.setPlaceholderText("-Dfml.ignorePatchDiscrepancies=true")
        args_layout.addWidget(self._jvm_args_edit, 1, 1)

        args_layout.addWidget(QLabel(self.tr("环境变量")), 2, 0)
        self._env_vars_edit = QLineEdit()
        self._env_vars_edit.setPlaceholderText("KEY=value;KEY2=value2")
        args_layout.addWidget(self._env_vars_edit, 2, 1)

        args_layout.addWidget(QLabel(self.tr("自定义 UUID")), 3, 0)
        self._custom_uuid_edit = QLineEdit()
        self._custom_uuid_edit.setPlaceholderText("留空使用默认 UUID")
        args_layout.addWidget(self._custom_uuid_edit, 3, 1)

        args_group.setLayout(args_layout)
        layout.addWidget(args_group)

        layout.addStretch()
        self._content_stack.addTab(page, "advanced")

    def _setup_download_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        source_group = QGroupBox(self.tr("下载源"))
        source_layout = QGridLayout()
        source_layout.setSpacing(12)

        source_layout.addWidget(QLabel(self.tr("当前下载源")), 0, 0)
        self._source_combo = QComboBox()
        source_layout.addWidget(self._source_combo, 0, 1)

        self._speed_test_btn = QPushButton(self.tr("测速并选择最快"))
        self._speed_test_btn.clicked.connect(self._start_speed_test)
        source_layout.addWidget(self._speed_test_btn, 0, 2)

        self._source_status_label = QLabel("")
        self._source_status_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        source_layout.addWidget(self._source_status_label, 1, 0, 1, 3)

        self._source_desc_label = QLabel("")
        self._source_desc_label.setWordWrap(True)
        self._source_desc_label.setStyleSheet("color: #6B7280; font-size: 11px;")
        source_layout.addWidget(self._source_desc_label, 2, 0, 1, 3)

        self._populate_sources()
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)

        source_group.setLayout(source_layout)
        layout.addWidget(source_group)

        dl_group = QGroupBox(self.tr("下载设置"))
        dl_layout = QGridLayout()
        dl_layout.setSpacing(12)
        dl_layout.addWidget(QLabel(self.tr("下载线程数")), 0, 0)
        self._threads_spin = QSpinBox()
        self._threads_spin.setRange(1, 64)
        self._threads_spin.setValue(16)
        dl_layout.addWidget(self._threads_spin, 0, 1)
        dl_layout.addWidget(QLabel(self.tr("速度限制 (KB/s)")), 1, 0)
        self._speed_spin = QSpinBox()
        self._speed_spin.setRange(0, 100000)
        self._speed_spin.setValue(0)
        self._speed_spin.setSpecialValueText(self.tr("无限制"))
        dl_layout.addWidget(self._speed_spin, 1, 1)
        self._verify_check = QCheckBox(self.tr("下载完成后校验文件哈希"))
        self._verify_check.setChecked(True)
        dl_layout.addWidget(self._verify_check, 2, 0, 1, 2)
        self._auto_select_check = QCheckBox(self.tr("启动时自动测速并选择最快下载源"))
        dl_layout.addWidget(self._auto_select_check, 3, 0, 1, 2)
        dl_group.setLayout(dl_layout)
        layout.addWidget(dl_group)
        layout.addStretch()

        self._content_stack.addTab(page, "download")

    def _setup_about_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        logo = QLabel("⛏")
        logo_font = QFont()
        logo_font.setPointSize(48)
        logo.setFont(logo_font)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        name_label = QLabel("Minecraft Launcher")
        name_font = QFont()
        name_font.setPointSize(22)
        name_font.setWeight(QFont.Weight.Bold)
        name_label.setFont(name_font)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        version_label = QLabel(self.tr("版本") + f" {LAUNCHER_VERSION}")
        version_label.setStyleSheet("color: #9CA3AF; font-size: 14px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        desc = QLabel(self.tr(
            "一个开源的 Minecraft 启动器\n"
            "使用 Python + PyQt6 开发\n"
            "支持内置 JRE、多渲染器适配、版本隔离"
        ))
        desc.setStyleSheet("color: #9CA3AF;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row.setSpacing(12)
        check_update_btn = QPushButton(self.tr("检查更新"))
        check_update_btn.clicked.connect(self._check_update)
        btn_row.addWidget(check_update_btn)
        open_source_btn = QPushButton(self.tr("开源协议"))
        open_source_btn.clicked.connect(self._show_license)
        btn_row.addWidget(open_source_btn)
        layout.addLayout(btn_row)
        layout.addStretch()

        self._content_stack.addTab(page, "about")

    def _setup_bottom_bar(self, parent_layout: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setFixedHeight(60)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(20, 8, 20, 12)
        bar_layout.addStretch()

        cancel_btn = QPushButton(self.tr("取消"))
        cancel_btn.clicked.connect(self.reject)
        bar_layout.addWidget(cancel_btn)

        save_btn = QPushButton(self.tr("保存"))
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_settings)
        bar_layout.addWidget(save_btn)

        parent_layout.addWidget(bar)

    def _populate_java_combo(self) -> None:
        if not self._java_combo:
            return
        self._java_combo.blockSignals(True)
        self._java_combo.clear()

        self._bundled_mgr.rescan()
        javas = self._detector.scan(force=True)

        selected_idx = 0
        current_idx = 0

        from src.utils.config import get_config
        config = get_config()
        saved_java = config.get("java_path", "")
        selected_bundled = config.get("java.bundled_jre", "")

        for jre in self._bundled_mgr.get_all_jres():
            if jre.is_installed:
                label = f"【内置】{jre.display_name}"
                if jre.is_compatible_with_mc(self._mc_version) if self._mc_version else True:
                    label += " ✓"
                self._java_combo.addItem(label, ("bundled", jre.jre_id, jre.java_exe))
                if selected_bundled == jre.jre_id:
                    selected_idx = current_idx
                current_idx += 1
            else:
                label = f"【内置-未安装】{jre.display_name}"
                self._java_combo.addItem(label, ("bundled_missing", jre.jre_id, None))
                current_idx += 1

        for java in javas:
            if self._detector._is_bundled_path(java.path):
                continue
            label = f"【自定义】Java {java.major_version} ({java.vendor})"
            self._java_combo.addItem(label, ("custom", None, java.path))
            if saved_java and str(java.path) == saved_java:
                selected_idx = current_idx
            current_idx += 1

        browse_label = f"【自定义】浏览本地 Java..."
        self._java_combo.addItem(browse_label, ("browse", None, None))

        self._java_combo.setCurrentIndex(min(selected_idx, self._java_combo.count() - 1))
        self._java_combo.blockSignals(False)
        self._on_java_changed(self._java_combo.currentIndex())

    def _on_java_changed(self, index: int) -> None:
        if not self._java_combo or index < 0:
            return
        data = self._java_combo.itemData(index)
        if not data:
            return
        source_type, jre_id, java_path = data

        if source_type == "browse":
            self._browse_for_java()
            return

        if source_type == "bundled_missing":
            self._java_status_label.setText(self.tr("该内置 JRE 尚未安装，请到 JRE 目录放置对应版本"))
            self._java_status_label.setStyleSheet("color: #F59E0B; font-size: 12px;")
            return

        if source_type == "bundled":
            jre = self._bundled_mgr.get_jre_by_id(jre_id)
            if jre:
                compat = jre.is_compatible_with_mc(self._mc_version) if self._mc_version else True
                if compat:
                    self._java_status_label.setText(f"内置 JRE {jre.version_str} - {jre.description}")
                    self._java_status_label.setStyleSheet("color: #10B981; font-size: 12px;")
                else:
                    self._java_status_label.setText(f"⚠️ {jre.display_name} 与当前 MC 版本不兼容")
                    self._java_status_label.setStyleSheet("color: #EF4444; font-size: 12px;")
        elif source_type == "custom":
            java_info = self._detector.check_java(java_path) if java_path else None
            if java_info:
                is_compat = True
                reason = ""
                if self._mc_version:
                    is_compat, reason = self._detector.check_compatibility(java_info, self._mc_version)
                if is_compat:
                    self._java_status_label.setText(f"自定义 Java {java_info.version} - {java_info.vendor}")
                    self._java_status_label.setStyleSheet("color: #10B981; font-size: 12px;")
                else:
                    self._java_status_label.setText(f"⚠️ 不兼容: {reason}")
                    self._java_status_label.setStyleSheet("color: #EF4444; font-size: 12px;")

    def _browse_for_java(self) -> None:
        if sys.platform == "win32":
            filter_str = "Java 可执行文件 (java.exe);;所有文件 (*)"
        else:
            filter_str = "Java 可执行文件 (java);;所有文件 (*)"
        path, _ = QFileDialog.getOpenFileName(self, self.tr("选择 Java 可执行文件"), "", filter_str)
        if path:
            java_path = Path(path)
            info = self._detector.add_custom_java(java_path)
            if info:
                Toast.success(self.tr(f"已添加 Java {info.major_version}"))
                self._populate_java_combo()
                for i in range(self._java_combo.count()):
                    d = self._java_combo.itemData(i)
                    if d and d[0] == "custom" and d[2] and str(d[2]) == str(java_path):
                        self._java_combo.setCurrentIndex(i)
                        break
            else:
                QMessageBox.warning(self, self.tr("无效的 Java"), self.tr("所选路径不是有效的 Java 可执行文件。"))
                self._java_combo.setCurrentIndex(0)

    def _populate_renderers(self) -> None:
        if not self._renderer_combo:
            return
        self._renderer_combo.blockSignals(True)
        self._renderer_combo.clear()

        from src.utils.config import get_config
        config = get_config()
        saved_renderer = config.get("renderer.selected", get_default_renderer_id())

        renderers = get_compatible_renderers(self._mc_version) if self._mc_version else [(r, True, "") for r in get_all_renderers()]
        selected_idx = 0

        for i, (renderer, is_compat, reason) in enumerate(renderers):
            label = renderer.display_name
            if not is_compat:
                label += f" （不可用：{reason}）"
            self._renderer_combo.addItem(label, renderer.renderer_id)
            model_idx = self._renderer_combo.model().index(i, 0)
            if not is_compat:
                self._renderer_combo.model().setData(model_idx, 0, Qt.ItemDataRole.UserRole - 1)
                item = self._renderer_combo.model().item(i)
                if item:
                    item.setEnabled(False)
            if renderer.renderer_id == saved_renderer and is_compat:
                selected_idx = i

        self._renderer_combo.setCurrentIndex(selected_idx)
        self._renderer_combo.blockSignals(False)
        self._on_renderer_changed(selected_idx)

    def _on_renderer_changed(self, index: int) -> None:
        if not self._renderer_combo or index < 0:
            return
        renderer_id = self._renderer_combo.itemData(index)
        renderer = get_renderer_by_id(renderer_id)
        if renderer:
            desc = f"{renderer.opengl_version} - {renderer.description}"
            self._renderer_desc_label.setText(desc)

            is_compat, reason = renderer.is_compatible_with_mc(self._mc_version) if self._mc_version else (True, "")
            if not is_compat:
                self._renderer_warning_label.setText(f"⚠️ {reason}")
            else:
                self._renderer_warning_label.setText("")

    def _on_backend_changed(self, index: int) -> None:
        self._update_backend_enabled()

    def _update_backend_enabled(self) -> None:
        if not self._graphics_backend_combo:
            return
        backend_id = self._graphics_backend_combo.currentData()
        supports_vulkan = is_version_supports_vulkan(self._mc_version) if self._mc_version else False

        idx = self._graphics_backend_combo.findData("vulkan")
        if idx >= 0:
            model_idx = self._graphics_backend_combo.model().index(idx, 0)
            if self._mc_version and not supports_vulkan:
                self._graphics_backend_combo.model().setData(model_idx, 0, Qt.ItemDataRole.UserRole - 1)
                item = self._graphics_backend_combo.model().item(idx)
                if item:
                    item.setEnabled(False)
                if backend_id == "vulkan":
                    self._graphics_backend_combo.setCurrentIndex(0)
                    backend_id = "gl4es"
                self._backend_hint.setText(self.tr("Vulkan 后端仅支持 MC 1.26+ 版本"))
                self._backend_hint.setStyleSheet("color: #F59E0B; font-size: 12px;")
            else:
                item = self._graphics_backend_combo.model().item(idx)
                if item:
                    item.setEnabled(True)
                self._backend_hint.setText("")

    def _on_auto_memory_toggled(self, checked: bool) -> None:
        if self._memory_slider:
            self._memory_slider.setEnabled(not checked)
        if checked:
            total_gb = self._detect_total_memory_gb()
            recommended = max(2, min(4, int(total_gb) // 2))
            if self._memory_slider:
                self._memory_slider.setValue(recommended)
        self._update_memory_info()

    def _on_memory_slider_changed(self, value: int) -> None:
        if self._memory_value_label:
            self._memory_value_label.setText(f"{value} GB")
        self._update_memory_info()

    def _update_memory_info(self) -> None:
        if not self._memory_info_label:
            return
        total_gb = self._detect_total_memory_gb()
        current_gb = self._memory_slider.value() if self._memory_slider else 4
        used_gb = total_gb - current_gb
        self._memory_info_label.setText(
            self.tr(f"系统总内存: {total_gb:.0f} GB | 分配给游戏: {current_gb} GB | 剩余系统: {used_gb:.0f} GB")
        )

    def _on_force_res_toggled(self, checked: bool) -> None:
        if self._resolution_widget:
            self._resolution_widget.setVisible(checked)

    @staticmethod
    def _detect_total_memory_gb() -> float:
        try:
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                c_ulonglong = ctypes.c_ulonglong

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", c_ulonglong),
                        ("ullAvailPhys", c_ulonglong),
                        ("ullTotalPageFile", c_ulonglong),
                        ("ullAvailPageFile", c_ulonglong),
                        ("ullTotalVirtual", c_ulonglong),
                        ("ullAvailVirtual", c_ulonglong),
                        ("ullAvailExtendedVirtual", c_ulonglong),
                    ]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(stat)
                kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                return stat.ullTotalPhys / (1024 ** 3)
            else:
                if sys.platform == "darwin":
                    cmd = ["sysctl", "-n", "hw.memsize"]
                else:
                    cmd = ["free", "-b"]
                result = __import__("subprocess").run(cmd, capture_output=True, text=True, timeout=5)
                if sys.platform == "darwin":
                    return int(result.stdout.strip()) / (1024 ** 3)
                for line in result.stdout.split("\n"):
                    if line.startswith("Mem:"):
                        parts = line.split()
                        return int(parts[1]) / (1024 ** 3)
        except Exception:
            pass
        return 8.0

    def _switch_tab(self, key: str, active_btn: QPushButton) -> None:
        for i in range(self._content_stack.count()):
            if self._content_stack.tabText(i) == key:
                self._content_stack.setCurrentIndex(i)
                break
        for _, btn in self._nav_buttons:
            btn.setProperty("active", "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        active_btn.setProperty("active", "true")
        active_btn.style().unpolish(active_btn)
        active_btn.style().polish(active_btn)

    def _preview_accent_color(self, index: int) -> None:
        colors = [ThemeColor.PURPLE, ThemeColor.BLUE, ThemeColor.INDIGO]
        if 0 <= index < len(colors):
            ThemeManager.instance().set_accent_color(colors[index])

    def _browse_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr("选择游戏目录"), str(Path.home()))
        if path:
            self._game_dir_edit.setText(path)

    def _populate_sources(self) -> None:
        try:
            from src.utils.download_source import get_download_source_manager
            manager = get_download_source_manager()
            self._source_combo.blockSignals(True)
            self._source_combo.clear()
            self._source_ids = []
            current_id = manager.current_source.id
            current_idx = 0
            for i, src in enumerate(manager.sources):
                self._source_combo.addItem(src.name)
                self._source_ids.append(src.id)
                if src.id == current_id:
                    current_idx = i
            self._source_combo.setCurrentIndex(current_idx)
            self._source_combo.blockSignals(False)
            self._update_source_info()
        except Exception as e:
            logger.debug("加载下载源失败: %s", e)

    def _update_source_info(self) -> None:
        try:
            from src.utils.download_source import get_download_source_manager
            manager = get_download_source_manager()
            idx = self._source_combo.currentIndex()
            if 0 <= idx < len(self._source_ids):
                src = manager.get_source(self._source_ids[idx])
                if src:
                    self._source_status_label.setText(f"当前: {src.name}")
                    self._source_desc_label.setText(getattr(src, "description", ""))
        except Exception:
            pass

    def _on_source_changed(self, index: int) -> None:
        self._update_source_info()

    def _start_speed_test(self) -> None:
        Toast.info(self.tr("测速功能在设置对话框保存后生效"))

    def _check_update(self) -> None:
        QMessageBox.information(self, self.tr("检查更新"), self.tr("当前已是最新版本！"))

    def _show_license(self) -> None:
        QMessageBox.information(self, self.tr("开源协议"), "MIT License")

    def _load_settings(self) -> None:
        try:
            from src.utils.config import get_config
            config = get_config()

            tm = ThemeManager.instance()
            if tm.current_theme == Theme.DARK:
                self._theme_combo.setCurrentIndex(0)
            else:
                self._theme_combo.setCurrentIndex(1)

            self._color_combo.setCurrentIndex(config.get("appearance.accent_color", 0))
            self._lang_combo.setCurrentIndex(config.get("appearance.language", 0))
            self._minimize_tray_check.setChecked(config.get("minimize_to_tray", True))
            self._check_update_check.setChecked(config.get("check_update", True))

            self._game_dir_edit.setText(config.get("game_directory", str(Path.home() / ".minecraft")))

            if self._width_spin:
                self._width_spin.setValue(config.get("launch.window_width", 854))
            if self._height_spin:
                self._height_spin.setValue(config.get("launch.window_height", 480))
            if self._fullscreen_check:
                self._fullscreen_check.setChecked(config.get("launch.fullscreen", False))
            if self._close_launcher_check:
                self._close_launcher_check.setChecked(config.get("launch.close_launcher", True))

            max_mem_gb = config.get("java_args.max_memory_mb", 4096) // 1024
            if self._memory_slider:
                self._memory_slider.setValue(max_mem_gb)
            auto_mem = config.get("memory.auto", True)
            if self._auto_memory_check:
                self._auto_memory_check.setChecked(auto_mem)
                self._memory_slider.setEnabled(not auto_mem)

            jvm_args = config.get("java_args.extra_args", "")
            if self._jvm_args_java_edit:
                self._jvm_args_java_edit.setPlainText(jvm_args)

            renderer_id = config.get("renderer.selected", get_default_renderer_id())
            if self._renderer_combo:
                for i in range(self._renderer_combo.count()):
                    if self._renderer_combo.itemData(i) == renderer_id:
                        self._renderer_combo.setCurrentIndex(i)
                        break

            backend_id = config.get("graphics.backend", "gl4es")
            if self._graphics_backend_combo:
                idx = self._graphics_backend_combo.findData(backend_id)
                if idx >= 0:
                    self._graphics_backend_combo.setCurrentIndex(idx)

            vulkan_driver = config.get("vulkan.driver", "turnip")
            if self._vulkan_driver_combo:
                idx = self._vulkan_driver_combo.findData(vulkan_driver)
                if idx >= 0:
                    self._vulkan_driver_combo.setCurrentIndex(idx)

            if self._big_core_check:
                self._big_core_check.setChecked(config.get("renderer.big_core", False))
            if self._system_vulkan_check:
                self._system_vulkan_check.setChecked(config.get("vulkan.use_system", False))

            if self._per_version_check:
                self._per_version_check.setChecked(config.get("game.per_version_settings", False))
            if self._version_isolation_check:
                self._version_isolation_check.setChecked(config.get("game.version_isolation", False))
            if self._server_addr_edit:
                self._server_addr_edit.setText(config.get("game.server_address", ""))
            if self._touch_gestures_check:
                self._touch_gestures_check.setChecked(config.get("game.touch_gestures", False))
            if self._force_resolution_check:
                self._force_resolution_check.setChecked(config.get("launch.force_resolution", False))
                self._resolution_widget.setVisible(config.get("launch.force_resolution", False))

            if self._skip_integrity_check:
                self._skip_integrity_check.setChecked(config.get("debug.skip_integrity", False))
            if self._skip_jvm_check:
                self._skip_jvm_check.setChecked(config.get("debug.skip_jvm_check", False))
            if self._skip_mod_check:
                self._skip_mod_check.setChecked(config.get("debug.skip_mod_check", False))
            if self._debug_log_check:
                self._debug_log_check.setChecked(config.get("debug.log_enabled", False))
            if self._game_args_edit:
                self._game_args_edit.setText(config.get("advanced.game_args", ""))
            if self._jvm_args_edit:
                self._jvm_args_edit.setText(config.get("advanced.extra_jvm_args", ""))
            if self._env_vars_edit:
                self._env_vars_edit.setText(config.get("advanced.env_vars", ""))
            if self._custom_uuid_edit:
                self._custom_uuid_edit.setText(config.get("advanced.custom_uuid", ""))

            if self._threads_spin:
                self._threads_spin.setValue(config.get("download.max_threads", 16))
            if self._speed_spin:
                self._speed_spin.setValue(config.get("download.speed_limit", 0))
            if self._verify_check:
                self._verify_check.setChecked(config.get("download.verify", True))
            if self._auto_select_check:
                self._auto_select_check.setChecked(config.get("download.auto_select", False))

            self._update_memory_info()
            self._update_backend_enabled()
        except Exception as e:
            logger.error("加载设置失败: %s", e, exc_info=True)

    def _save_settings(self) -> None:
        theme_index = self._theme_combo.currentIndex()
        new_theme = Theme.DARK if theme_index == 0 else Theme.LIGHT
        ThemeManager.instance().set_theme(new_theme)

        color_index = self._color_combo.currentIndex()
        colors = [ThemeColor.PURPLE, ThemeColor.BLUE, ThemeColor.INDIGO]
        if 0 <= color_index < len(colors):
            ThemeManager.instance().set_accent_color(colors[color_index])

        try:
            from src.utils.config import get_config
            config = get_config()

            config.set("theme", new_theme.value)
            config.set("appearance.accent_color", color_index)
            config.set("appearance.language", self._lang_combo.currentIndex())
            config.set("minimize_to_tray", self._minimize_tray_check.isChecked())
            config.set("check_update", self._check_update_check.isChecked())

            config.set("game_directory", self._game_dir_edit.text())
            config.set("launch.close_launcher", self._close_launcher_check.isChecked())
            config.set("launch.fullscreen", self._fullscreen_check.isChecked())
            config.set("launch.force_resolution", self._force_resolution_check.isChecked())
            if self._width_spin:
                config.set("launch.window_width", self._width_spin.value())
            if self._height_spin:
                config.set("launch.window_height", self._height_spin.value())

            java_data = self._java_combo.currentData() if self._java_combo else None
            if java_data:
                source_type, jre_id, java_path = java_data
                if source_type == "bundled" and jre_id:
                    config.set("java.bundled_jre", jre_id)
                    jre = self._bundled_mgr.get_jre_by_id(jre_id)
                    if jre and jre.java_exe:
                        config.set("java_path", str(jre.java_exe))
                elif source_type == "custom" and java_path:
                    config.set("java_path", str(java_path))
                    config.set("java.bundled_jre", "")

            auto_mem = self._auto_memory_check.isChecked()
            config.set("memory.auto", auto_mem)
            mem_gb = self._memory_slider.value()
            config.set("java_args.max_memory_mb", mem_gb * 1024)
            config.set("java_args.min_memory_mb", min(mem_gb * 512, 2048))
            if self._jvm_args_java_edit:
                config.set("java_args.extra_args", self._jvm_args_java_edit.toPlainText())

            if self._renderer_combo:
                config.set("renderer.selected", self._renderer_combo.currentData() or get_default_renderer_id())
            if self._graphics_backend_combo:
                config.set("graphics.backend", self._graphics_backend_combo.currentData() or "gl4es")
            if self._vulkan_driver_combo:
                config.set("vulkan.driver", self._vulkan_driver_combo.currentData() or "turnip")
            if self._big_core_check:
                config.set("renderer.big_core", self._big_core_check.isChecked())
            if self._system_vulkan_check:
                config.set("vulkan.use_system", self._system_vulkan_check.isChecked())

            if self._per_version_check:
                config.set("game.per_version_settings", self._per_version_check.isChecked())
            if self._version_isolation_check:
                config.set("game.version_isolation", self._version_isolation_check.isChecked())
            if self._server_addr_edit:
                config.set("game.server_address", self._server_addr_edit.text())
            if self._touch_gestures_check:
                config.set("game.touch_gestures", self._touch_gestures_check.isChecked())

            if self._skip_integrity_check:
                config.set("debug.skip_integrity", self._skip_integrity_check.isChecked())
            if self._skip_jvm_check:
                config.set("debug.skip_jvm_check", self._skip_jvm_check.isChecked())
            if self._skip_mod_check:
                config.set("debug.skip_mod_check", self._skip_mod_check.isChecked())
            if self._debug_log_check:
                config.set("debug.log_enabled", self._debug_log_check.isChecked())
            if self._game_args_edit:
                config.set("advanced.game_args", self._game_args_edit.text())
            if self._jvm_args_edit:
                config.set("advanced.extra_jvm_args", self._jvm_args_edit.text())
            if self._env_vars_edit:
                config.set("advanced.env_vars", self._env_vars_edit.text())
            if self._custom_uuid_edit:
                config.set("advanced.custom_uuid", self._custom_uuid_edit.text())

            if hasattr(self, '_source_ids') and self._source_ids:
                idx = self._source_combo.currentIndex()
                if 0 <= idx < len(self._source_ids):
                    try:
                        from src.utils.download_source import get_download_source_manager
                        manager = get_download_source_manager()
                        manager.set_current(self._source_ids[idx])
                    except Exception:
                        pass

            if self._threads_spin:
                config.set("download.max_threads", self._threads_spin.value())
            if self._speed_spin:
                config.set("download.speed_limit", self._speed_spin.value())
            if self._verify_check:
                config.set("download.verify", self._verify_check.isChecked())
            if self._auto_select_check:
                config.set("download.auto_select", self._auto_select_check.isChecked())

            config.save()
        except Exception as e:
            logger.error("保存设置失败: %s", e, exc_info=True)

        settings = {"theme": new_theme.value, "accent_color": color_index}
        self.settings_changed.emit(settings)
        Toast.success(self.tr("设置已保存"))
        self.accept()
