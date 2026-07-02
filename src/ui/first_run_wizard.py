"""首次启动向导模块。

首次启动时引导用户完成基本配置：Java 检测、游戏目录选择、内存设置。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QLineEdit, QComboBox, QSlider, QProgressBar, QFrame,
    QStackedWidget, QSizePolicy, QMessageBox, QSpacerItem
)
from PyQt6.QtGui import QFont

from .widgets import Toast, ToastType
from src.core.java_detector import JavaDetector, JavaInfo

logger = logging.getLogger(__name__)


class FirstRunWizard(QDialog):
    """首次启动向导对话框。

    引导用户完成：欢迎页 → Java 检测 → 游戏目录 → 内存设置 → 完成。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._java_installations: list[JavaInfo] = []
        self._selected_java: Optional[JavaInfo] = None
        self._game_dir: Path = Path.home() / ".minecraft"
        self._memory_mb: int = 4096
        self._setup_window()
        self._setup_ui()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("欢迎使用 Minecraft Launcher"))
        self.setMinimumSize(640, 480)
        self.resize(700, 520)
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

        self._setup_title_bar(root_layout)

        content = QWidget()
        content.setObjectName("CardWidget")
        content.setStyleSheet("#CardWidget { border-radius: 0; border: none; }")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(40, 20, 40, 20)
        content_layout.setSpacing(16)

        self._stack = QStackedWidget()
        content_layout.addWidget(self._stack, 1)

        self._setup_welcome_page()
        self._setup_java_page()
        self._setup_gamedir_page()
        self._setup_memory_page()
        self._setup_finish_page()

        root_layout.addWidget(content, 1)

        self._setup_bottom_bar(root_layout)

    def _setup_title_bar(self, root_layout: QVBoxLayout) -> None:
        from .widgets import DialogTitleBar
        title_bar = DialogTitleBar(self, self.tr("首次启动向导"))
        title_bar.close_clicked.connect(self.reject)
        root_layout.addWidget(title_bar)

    def _setup_welcome_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        title = QLabel("⛏ Minecraft Launcher")
        title_font = QFont()
        title_font.setPointSize(28)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(self.tr("欢迎！让我们完成一些初始设置。\n这只需要一分钟。"))
        subtitle.setStyleSheet("color: #9CA3AF; font-size: 15px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addStretch()
        self._stack.addWidget(page)

    def _setup_java_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        title = QLabel(self.tr("Java 检测"))
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        layout.addWidget(title)

        desc = QLabel(self.tr("启动器需要 Java 才能运行 Minecraft。正在自动检测..."))
        desc.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self._java_progress = QProgressBar()
        self._java_progress.setRange(0, 0)
        self._java_progress.setTextVisible(False)
        layout.addWidget(self._java_progress)

        self._java_status = QLabel(self.tr("正在检测系统中的 Java..."))
        self._java_status.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        layout.addWidget(self._java_status)

        java_list_container = QWidget()
        self._java_list_layout = QVBoxLayout(java_list_container)
        self._java_list_layout.setSpacing(8)
        self._java_combo = QComboBox()
        self._java_combo.setMinimumHeight(36)
        self._java_list_layout.addWidget(self._java_combo)
        layout.addWidget(java_list_container)

        browse_row = QHBoxLayout()
        browse_row.setSpacing(8)
        browse_label = QLabel(self.tr("手动指定 Java 路径:"))
        browse_label.setStyleSheet("color: #9CA3AF;")
        browse_row.addWidget(browse_label)
        self._java_path_edit = QLineEdit()
        self._java_path_edit.setPlaceholderText(self.tr("选择 java 可执行文件路径"))
        browse_row.addWidget(self._java_path_edit, 1)
        self._browse_java_btn = QPushButton(self.tr("浏览"))
        self._browse_java_btn.setObjectName("IconButton")
        self._browse_java_btn.clicked.connect(self._browse_java)
        browse_row.addWidget(self._browse_java_btn)
        layout.addLayout(browse_row)

        layout.addStretch()
        self._stack.addWidget(page)

    def _setup_gamedir_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        title = QLabel(self.tr("游戏目录"))
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        layout.addWidget(title)

        desc = QLabel(self.tr("选择 Minecraft 的游戏目录（存放版本、模组、存档等）。\n默认目录为用户目录下的 .minecraft 文件夹。"))
        desc.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self._gamedir_edit = QLineEdit(str(self._game_dir))
        dir_row.addWidget(self._gamedir_edit, 1)
        browse_dir_btn = QPushButton(self.tr("浏览"))
        browse_dir_btn.setObjectName("IconButton")
        browse_dir_btn.clicked.connect(self._browse_gamedir)
        dir_row.addWidget(browse_dir_btn)
        layout.addLayout(dir_row)

        tip = QLabel(self.tr("💡 提示：如果已有 .minecraft 文件夹，请选择它以保留原有数据。"))
        tip.setStyleSheet("color: #F59E0B; font-size: 12px; padding: 8px; background: #F59E0B10; border-radius: 6px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addStretch()
        self._stack.addWidget(page)

    def _setup_memory_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        title = QLabel(self.tr("内存设置"))
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        layout.addWidget(title)

        desc = QLabel(self.tr("设置分配给 Minecraft 的最大内存。\n建议设置为物理内存的一半，不超过 8GB。"))
        desc.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        mem_row = QHBoxLayout()
        mem_row.setSpacing(16)
        self._memory_slider = QSlider(Qt.Orientation.Horizontal)
        total_mem_gb = self._detect_total_memory_gb()
        self._memory_slider.setRange(1, min(total_mem_gb * 2, 32))
        recommended = min(4, total_mem_gb // 2)
        self._memory_slider.setValue(recommended)
        self._memory_value = QLabel(f"{recommended} GB")
        self._memory_value.setMinimumWidth(70)
        self._memory_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._memory_value.setStyleSheet("font-size: 18px; font-weight: 700;")
        mem_row.addWidget(self._memory_slider, 1)
        mem_row.addWidget(self._memory_value)
        self._memory_slider.valueChanged.connect(
            lambda v: self._memory_value.setText(f"{v} GB")
        )
        layout.addLayout(mem_row)

        rec_label = QLabel(self.tr(f"建议：{recommended} GB（物理内存 {total_mem_gb} GB 的一半）"))
        rec_label.setStyleSheet("color: #10B981; font-size: 12px;")
        layout.addWidget(rec_label)

        warning = QLabel(self.tr("⚠️ 内存过大可能导致 GC 停顿，内存过小可能导致游戏崩溃。"))
        warning.setStyleSheet("color: #F59E0B; font-size: 12px; padding: 8px; background: #F59E0B10; border-radius: 6px;")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        layout.addStretch()
        self._stack.addWidget(page)

    def _setup_finish_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        title = QLabel("✅" + self.tr("设置完成！"))
        title_font = QFont()
        title_font.setPointSize(26)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet("color: #9CA3AF; font-size: 14px;")
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        layout.addStretch()
        self._stack.addWidget(page)

    def _setup_bottom_bar(self, root_layout: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setFixedHeight(64)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(20, 8, 20, 16)
        bar_layout.setSpacing(12)

        self._back_btn = QPushButton(self.tr("上一步"))
        self._back_btn.clicked.connect(self._prev_page)
        self._back_btn.setEnabled(False)
        bar_layout.addWidget(self._back_btn)

        bar_layout.addStretch()

        self._page_indicator = QLabel("1 / 5")
        self._page_indicator.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        bar_layout.addWidget(self._page_indicator)

        bar_layout.addStretch()

        self._next_btn = QPushButton(self.tr("下一步"))
        self._next_btn.setObjectName("PrimaryButton")
        self._next_btn.clicked.connect(self._next_page)
        bar_layout.addWidget(self._next_btn)

        root_layout.addWidget(bar)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(200, self._start_java_detection)

    def _start_java_detection(self) -> None:
        try:
            detector = JavaDetector()
            self._java_installations = detector.scan()
            self._java_progress.setRange(0, 1)
            self._java_progress.setValue(1)

            if self._java_installations:
                self._java_status.setText(self.tr(f"检测到 {len(self._java_installations)} 个 Java 安装"))
                for j in self._java_installations:
                    ver = j.version or "未知版本"
                    self._java_combo.addItem(f"Java {ver} ({j.path})", j)
                self._selected_java = self._java_installations[0]
            else:
                self._java_status.setText(self.tr("未检测到 Java，请手动指定 Java 路径"))
                Toast.warning(self.tr("未检测到 Java，请手动选择 Java 路径"))

        except Exception as e:
            logger.error("Java 检测失败: %s", e)
            self._java_progress.setRange(0, 1)
            self._java_progress.setValue(1)
            self._java_status.setText(self.tr("检测失败，请手动指定 Java 路径"))

    def _browse_java(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择 Java 可执行文件"), "",
            "Java (*.exe java);;所有文件 (*)"
        )
        if path:
            self._java_path_edit.setText(path)

    def _browse_gamedir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, self.tr("选择游戏目录"), str(Path.home())
        )
        if path:
            self._gamedir_edit.setText(path)

    @staticmethod
    def _detect_total_memory_gb() -> int:
        try:
            import psutil
            return int(psutil.virtual_memory().total / (1024**3))
        except ImportError:
            import os
            if os.path.exists("/proc/meminfo"):
                try:
                    with open("/proc/meminfo") as f:
                        for line in f:
                            if line.startswith("MemTotal:"):
                                return int(line.split()[1]) // (1024 * 1024)
                except Exception:
                    pass
        return 8

    def _prev_page(self) -> None:
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
            self._update_nav()

    def _next_page(self) -> None:
        idx = self._stack.currentIndex()

        if idx == 1:
            java_path = self._java_path_edit.text().strip()
            if not self._selected_java and not java_path:
                if self._java_combo.count() == 0:
                    Toast.warning(self.tr("请选择或指定 Java 路径"))
                    return
            if java_path:
                check_detector = JavaDetector()
                java_info = check_detector.check_java(Path(java_path))
                if java_info:
                    self._selected_java = java_info
                else:
                    self._selected_java = None
        elif idx == 2:
            dir_text = self._gamedir_edit.text().strip()
            if not dir_text:
                Toast.warning(self.tr("请选择游戏目录"))
                return
            self._game_dir = Path(dir_text)
            try:
                self._game_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                Toast.error(self.tr("无法创建游戏目录，请检查权限"))
                return
        elif idx == 3:
            self._memory_mb = self._memory_slider.value() * 1024

        if idx < self._stack.count() - 1:
            if idx == self._stack.count() - 2:
                self._build_summary()
                self._next_btn.setText(self.tr("完成"))
            self._stack.setCurrentIndex(idx + 1)
            self._update_nav()
        else:
            self.accept()

    def _update_nav(self) -> None:
        idx = self._stack.currentIndex()
        total = self._stack.count()
        self._page_indicator.setText(f"{idx + 1} / {total}")
        self._back_btn.setEnabled(idx > 0)
        if idx == total - 1:
            self._next_btn.setText(self.tr("开始使用"))
        elif idx == total - 2:
            self._next_btn.setText(self.tr("下一步"))
        else:
            self._next_btn.setText(self.tr("下一步"))

    def _build_summary(self) -> None:
        java_text = str(self._selected_java.path) if self._selected_java else self._java_path_edit.text()
        summary = (
            f"Java 路径: {java_text}\n"
            f"游戏目录: {self._game_dir}\n"
            f"内存分配: {self._memory_mb // 1024} GB\n\n"
            f"{self.tr('点击「开始使用」进入启动器主界面。')}"
        )
        self._summary_label.setText(summary)

    def get_result(self) -> dict:
        """获取向导配置结果。

        Returns:
            配置字典
        """
        java_path = str(self._selected_java.path) if self._selected_java else self._java_path_edit.text()
        return {
            "java_path": java_path,
            "game_dir": str(self._game_dir),
            "max_memory_mb": self._memory_mb,
            "min_memory_mb": min(self._memory_mb // 2, 2048),
        }