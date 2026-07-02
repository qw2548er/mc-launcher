"""设置对话框模块。

提供通用设置、Java设置、游戏设置、下载设置和关于页面。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QTabWidget, QLineEdit, QSpinBox, QSlider, QComboBox, QCheckBox,
    QGroupBox, QFileDialog, QScrollArea, QFrame, QGridLayout, QSizePolicy,
    QMessageBox, QTextEdit, QRadioButton, QButtonGroup, QSpacerItem
)

from .widgets import DialogTitleBar
from .styles import ThemeManager, Theme, ThemeColor

logger = logging.getLogger(__name__)

LAUNCHER_VERSION = "1.0.0"


class SettingsDialog(QDialog):
    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_window()
        self._setup_ui()
        self._load_settings()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("设置"))
        self.setMinimumSize(700, 550)
        self.resize(750, 600)
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

        self._title_bar = DialogTitleBar(self, self.tr("设置"))
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

    def _setup_nav(self, parent_layout: QHBoxLayout) -> None:
        nav = QWidget()
        nav.setFixedWidth(180)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(12, 20, 12, 20)
        nav_layout.setSpacing(4)

        nav_title = QLabel(self.tr("设置"))
        nav_title.setStyleSheet("font-size: 18px; font-weight: 800; padding: 0 8px 16px;")
        nav_layout.addWidget(nav_title)

        self._nav_buttons = []
        nav_items = [
            ("general", self.tr("通用")),
            ("java", self.tr("Java")),
            ("game", self.tr("游戏")),
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
        self._setup_game_tab()
        self._setup_download_tab()
        self._setup_about_tab()

        scroll.setWidget(self._content_stack)
        parent_layout.addWidget(scroll, 1)

    def _setup_general_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        appearance_group = QGroupBox(self.tr("外观"))
        app_layout = QGridLayout()
        app_layout.setSpacing(14)

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
        beh_layout = QGridLayout()
        beh_layout.setSpacing(14)

        self._autostart_check = QCheckBox(self.tr("开机自启动"))
        beh_layout.addWidget(self._autostart_check, 0, 0, 1, 2)

        self._minimize_tray_check = QCheckBox(self.tr("关闭时最小化到托盘"))
        self._minimize_tray_check.setChecked(True)
        beh_layout.addWidget(self._minimize_tray_check, 1, 0, 1, 2)

        self._check_update_check = QCheckBox(self.tr("启动时检查更新"))
        self._check_update_check.setChecked(True)
        beh_layout.addWidget(self._check_update_check, 2, 0, 1, 2)

        behavior_group.setLayout(beh_layout)
        layout.addWidget(behavior_group)
        layout.addStretch()

        self._content_stack.addTab(page, "general")
        self._nav_buttons[0][1].setProperty("active", "true")

    def _setup_java_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        java_group = QGroupBox(self.tr("Java 配置"))
        java_layout = QGridLayout()
        java_layout.setSpacing(14)

        java_layout.addWidget(QLabel(self.tr("Java 路径")), 0, 0)
        java_path_row = QHBoxLayout()
        self._java_path_edit = QLineEdit()
        self._java_path_edit.setPlaceholderText(self.tr("自动检测"))
        java_path_row.addWidget(self._java_path_edit, 1)
        self._java_browse_btn = QPushButton(self.tr("浏览"))
        self._java_browse_btn.setObjectName("IconButton")
        self._java_browse_btn.clicked.connect(self._browse_java)
        java_path_row.addWidget(self._java_browse_btn)
        java_layout.addLayout(java_path_row, 0, 1)

        self._auto_detect_btn = QPushButton(self.tr("自动检测 Java"))
        java_layout.addWidget(self._auto_detect_btn, 1, 1)

        java_group.setLayout(java_layout)
        layout.addWidget(java_group)

        mem_group = QGroupBox(self.tr("内存分配"))
        mem_layout = QGridLayout()
        mem_layout.setSpacing(14)

        mem_layout.addWidget(QLabel(self.tr("最小内存 (GB)")), 0, 0)
        self._min_mem_spin = QSpinBox()
        self._min_mem_spin.setRange(1, 32)
        self._min_mem_spin.setValue(2)
        self._min_mem_spin.setSuffix(" GB")
        mem_layout.addWidget(self._min_mem_spin, 0, 1)

        mem_layout.addWidget(QLabel(self.tr("最大内存 (GB)")), 1, 0)
        self._max_mem_spin = QSpinBox()
        self._max_mem_spin.setRange(1, 32)
        self._max_mem_spin.setValue(4)
        self._max_mem_spin.setSuffix(" GB")
        mem_layout.addWidget(self._max_mem_spin, 1, 1)

        mem_hint = QLabel(self.tr("提示：建议最大内存设置为物理内存的一半，不超过 8GB"))
        mem_hint.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        mem_layout.addWidget(mem_hint, 2, 0, 1, 2)

        mem_group.setLayout(mem_layout)
        layout.addWidget(mem_group)

        jvm_group = QGroupBox(self.tr("JVM 参数"))
        jvm_layout = QVBoxLayout()
        self._jvm_args_edit = QTextEdit()
        self._jvm_args_edit.setPlaceholderText(
            "-XX:+UnlockExperimentalVMOptions\n-XX:+UseG1GC"
        )
        self._jvm_args_edit.setMaximumHeight(100)
        jvm_layout.addWidget(self._jvm_args_edit)
        jvm_hint = QLabel(self.tr("每行一个参数，留空使用默认参数"))
        jvm_hint.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        jvm_layout.addWidget(jvm_hint)
        jvm_group.setLayout(jvm_layout)
        layout.addWidget(jvm_group)
        layout.addStretch()

        self._content_stack.addTab(page, "java")

    def _setup_game_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        dir_group = QGroupBox(self.tr("目录"))
        dir_layout = QGridLayout()
        dir_layout.setSpacing(14)

        dir_layout.addWidget(QLabel(self.tr("游戏目录")), 0, 0)
        game_dir_row = QHBoxLayout()
        self._game_dir_edit = QLineEdit()
        self._game_dir_edit.setText(str(Path.home() / ".minecraft"))
        game_dir_row.addWidget(self._game_dir_edit, 1)
        self._dir_browse_btn = QPushButton(self.tr("浏览"))
        self._dir_browse_btn.setObjectName("IconButton")
        self._dir_browse_btn.clicked.connect(self._browse_game_dir)
        game_dir_row.addWidget(self._dir_browse_btn)
        dir_layout.addLayout(game_dir_row, 0, 1)

        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        window_group = QGroupBox(self.tr("窗口"))
        win_layout = QGridLayout()
        win_layout.setSpacing(14)

        win_layout.addWidget(QLabel(self.tr("窗口宽度")), 0, 0)
        self._width_spin = QSpinBox()
        self._width_spin.setRange(800, 7680)
        self._width_spin.setValue(854)
        win_layout.addWidget(self._width_spin, 0, 1)

        win_layout.addWidget(QLabel(self.tr("窗口高度")), 1, 0)
        self._height_spin = QSpinBox()
        self._height_spin.setRange(600, 4320)
        self._height_spin.setValue(480)
        win_layout.addWidget(self._height_spin, 1, 1)

        self._fullscreen_check = QCheckBox(self.tr("全屏模式"))
        win_layout.addWidget(self._fullscreen_check, 2, 0, 1, 2)

        window_group.setLayout(win_layout)
        layout.addWidget(window_group)

        launch_group = QGroupBox(self.tr("启动选项"))
        launch_layout = QVBoxLayout()

        self._close_launcher_check = QCheckBox(self.tr("启动游戏后关闭启动器"))
        launch_layout.addWidget(self._close_launcher_check)

        self._demo_mode_check = QCheckBox(self.tr("演示模式"))
        launch_layout.addWidget(self._demo_mode_check)

        launch_group.setLayout(launch_layout)
        layout.addWidget(launch_group)
        layout.addStretch()

        self._content_stack.addTab(page, "game")

    def _setup_download_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        source_group = QGroupBox(self.tr("下载源"))
        source_layout = QGridLayout()
        source_layout.setSpacing(14)

        source_layout.addWidget(QLabel(self.tr("下载源")), 0, 0)
        self._source_combo = QComboBox()
        self._source_combo.addItems([
            self.tr("官方源 (Mojang)"),
            self.tr("BMCLAPI 镜像"),
            self.tr("MCBBS 镜像"),
        ])
        source_layout.addWidget(self._source_combo, 0, 1)

        source_group.setLayout(source_layout)
        layout.addWidget(source_group)

        dl_group = QGroupBox(self.tr("下载设置"))
        dl_layout = QGridLayout()
        dl_layout.setSpacing(14)

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

        dl_group.setLayout(dl_layout)
        layout.addWidget(dl_group)
        layout.addStretch()

        self._content_stack.addTab(page, "download")

    def _setup_about_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)
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
            "使用 Python + PyQt6 开发"
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

    def _browse_java(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择 Java 可执行文件"), "",
            "Java (*.exe java);;所有文件 (*)"
        )
        if path:
            self._java_path_edit.setText(path)

    def _browse_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, self.tr("选择游戏目录"), str(Path.home())
        )
        if path:
            self._game_dir_edit.setText(path)

    def _check_update(self) -> None:
        QMessageBox.information(
            self, self.tr("检查更新"),
            self.tr("当前已是最新版本！")
        )

    def _show_license(self) -> None:
        QMessageBox.information(
            self, self.tr("开源协议"),
            "MIT License\n\n"
            "Copyright (c) 2024 Minecraft Launcher\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
            "of this software and associated documentation files, to deal\n"
            "in the Software without restriction."
        )

    def _load_settings(self) -> None:
        tm = ThemeManager.instance()
        if tm.current_theme == Theme.DARK:
            self._theme_combo.setCurrentIndex(0)
        else:
            self._theme_combo.setCurrentIndex(1)

    def _save_settings(self) -> None:
        theme_index = self._theme_combo.currentIndex()
        new_theme = Theme.DARK if theme_index == 0 else Theme.LIGHT
        ThemeManager.instance().set_theme(new_theme)

        color_index = self._color_combo.currentIndex()
        colors = [ThemeColor.PURPLE, ThemeColor.BLUE, ThemeColor.INDIGO]
        if 0 <= color_index < len(colors):
            ThemeManager.instance().set_accent_color(colors[color_index])

        settings = {
            "theme": new_theme.value,
            "accent_color": color_index,
            "language": self._lang_combo.currentIndex(),
            "autostart": self._autostart_check.isChecked(),
            "minimize_to_tray": self._minimize_tray_check.isChecked(),
            "check_update": self._check_update_check.isChecked(),
            "java_path": self._java_path_edit.text(),
            "min_memory": self._min_mem_spin.value(),
            "max_memory": self._max_mem_spin.value(),
            "jvm_args": self._jvm_args_edit.toPlainText(),
            "game_dir": self._game_dir_edit.text(),
            "window_width": self._width_spin.value(),
            "window_height": self._height_spin.value(),
            "fullscreen": self._fullscreen_check.isChecked(),
            "close_after_launch": self._close_launcher_check.isChecked(),
            "demo_mode": self._demo_mode_check.isChecked(),
            "download_source": self._source_combo.currentIndex(),
            "download_threads": self._threads_spin.value(),
            "speed_limit": self._speed_spin.value(),
            "verify_downloads": self._verify_check.isChecked(),
        }

        self.settings_changed.emit(settings)
        from .widgets import Toast
        Toast.success(self.tr("设置已保存"))
        self.accept()

