"""Java 管理界面组件。

提供 Java 列表展示、添加/删除 Java、设置默认 Java、显示兼容性等功能。
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QGroupBox, QFrame, QProgressBar, QSizePolicy, QSpacerItem
)

from src.core.java_detector import JavaDetector, JavaInfo
from .widgets import Toast

logger = logging.getLogger(__name__)


class ScanThread(QThread):
    scan_finished = pyqtSignal(list)
    scan_progress = pyqtSignal(str)

    def __init__(self, detector: JavaDetector, force: bool = False):
        super().__init__()
        self._detector = detector
        self._force = force

    def run(self):
        try:
            self.scan_progress.emit("正在扫描系统 Java...")
            javas = self._detector.scan(force=self._force)
            self.scan_finished.emit(javas)
        except Exception as e:
            logger.error("Java 扫描失败: %s", e, exc_info=True)
            self.scan_finished.emit([])


class JavaListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QListWidget {
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 8px;
                background: rgba(0,0,0,0.2);
                padding: 4px;
                outline: none;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-radius: 6px;
                margin: 2px 4px;
            }
            QListWidget::item:selected {
                background: rgba(139, 92, 246, 0.3);
            }
            QListWidget::item:hover:!selected {
                background: rgba(255,255,255,0.05);
            }
        """)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)


class JavaManagerWidget(QWidget):
    java_selected = pyqtSignal(object)
    java_list_changed = pyqtSignal(list)

    def __init__(self, parent=None, mc_version: str = ""):
        super().__init__(parent)
        self._detector = JavaDetector()
        self._javas: list[JavaInfo] = []
        self._selected_java: Optional[JavaInfo] = None
        self._mc_version = mc_version
        self._scan_thread: Optional[ScanThread] = None
        self._setup_ui()
        self.refresh_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("已安装的 Java")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        self._scan_btn = QPushButton("重新扫描")
        self._scan_btn.setObjectName("IconButton")
        self._scan_btn.clicked.connect(lambda: self.refresh_list(force=True))
        header.addWidget(self._scan_btn)

        self._add_btn = QPushButton("添加 Java")
        self._add_btn.setObjectName("IconButton")
        self._add_btn.clicked.connect(self._add_java)
        header.addWidget(self._add_btn)

        self._remove_btn = QPushButton("删除")
        self._remove_btn.setObjectName("DangerButton")
        self._remove_btn.clicked.connect(self._remove_java)
        header.addWidget(self._remove_btn)

        layout.addLayout(header)

        self._java_list = JavaListWidget()
        self._java_list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._java_list, 1)

        self._detail_frame = QFrame()
        self._detail_frame.setStyleSheet("""
            QFrame {
                background: rgba(0,0,0,0.2);
                border-radius: 8px;
                padding: 12px;
            }
        """)
        detail_layout = QVBoxLayout(self._detail_frame)
        detail_layout.setContentsMargins(12, 12, 12, 12)
        detail_layout.setSpacing(6)

        self._detail_version = QLabel("")
        self._detail_version.setFont(QFont("", 10, QFont.Weight.Bold))
        detail_layout.addWidget(self._detail_version)

        self._detail_vendor = QLabel("")
        self._detail_vendor.setStyleSheet("color: #9CA3AF;")
        detail_layout.addWidget(self._detail_vendor)

        self._detail_path = QLabel("")
        self._detail_path.setStyleSheet("color: #9CA3AF; font-family: monospace;")
        self._detail_path.setWordWrap(True)
        detail_layout.addWidget(self._detail_path)

        self._detail_arch = QLabel("")
        self._detail_arch.setStyleSheet("color: #9CA3AF;")
        detail_layout.addWidget(self._detail_arch)

        self._compat_label = QLabel("")
        detail_layout.addWidget(self._compat_label)

        detail_layout.addStretch()

        self._set_default_btn = QPushButton("设为默认")
        self._set_default_btn.setObjectName("PrimaryButton")
        self._set_default_btn.clicked.connect(self._set_as_default)
        self._set_default_btn.setEnabled(False)
        detail_layout.addWidget(self._set_default_btn)

        layout.addWidget(self._detail_frame)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setFixedHeight(2)
        self._progress.setStyleSheet("""
            QProgressBar {
                border: none;
                background: transparent;
            }
            QProgressBar::chunk {
                background: #8B5CF6;
                border-radius: 1px;
            }
        """)
        layout.addWidget(self._progress)

        self._no_java_hint = QFrame()
        self._no_java_hint.setStyleSheet("""
            QFrame {
                background: rgba(239, 68, 68, 0.1);
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 8px;
                padding: 16px;
            }
        """)
        no_java_layout = QVBoxLayout(self._no_java_hint)
        no_java_layout.setSpacing(8)

        no_java_title = QLabel("⚠️ 未找到合适的 Java")
        no_java_title.setFont(QFont("", 10, QFont.Weight.Bold))
        no_java_title.setStyleSheet("color: #FCA5A5;")
        no_java_layout.addWidget(no_java_title)

        required_ver = JavaDetector.get_required_java_version(self._mc_version) if self._mc_version else 17
        self._no_java_msg = QLabel(f"当前版本需要 Java {required_ver} 或更高版本")
        self._no_java_msg.setStyleSheet("color: #D1D5DB;")
        self._no_java_msg.setWordWrap(True)
        no_java_layout.addWidget(self._no_java_msg)

        self._download_btn = QPushButton("前往下载 Java")
        self._download_btn.setObjectName("PrimaryButton")
        self._download_btn.clicked.connect(self._download_java)
        no_java_layout.addWidget(self._download_btn, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(self._no_java_hint)
        self._no_java_hint.setVisible(False)

    def set_mc_version(self, mc_version: str):
        self._mc_version = mc_version
        required_ver = JavaDetector.get_required_java_version(mc_version) if mc_version else 17
        self._no_java_msg.setText(f"当前版本 {mc_version} 需要 Java {required_ver} 或更高版本")
        self._update_compatibility()
        self._update_no_java_hint()

    def refresh_list(self, force: bool = False):
        if self._scan_thread and self._scan_thread.isRunning():
            return

        self._scan_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._scan_thread = ScanThread(self._detector, force)
        self._scan_thread.scan_finished.connect(self._on_scan_finished)
        self._scan_thread.scan_progress.connect(lambda m: None)
        self._scan_thread.start()

    def _on_scan_finished(self, javas: list[JavaInfo]):
        self._javas = javas
        self._scan_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._populate_list()
        self._update_no_java_hint()
        self.java_list_changed.emit(javas)

    def _populate_list(self):
        self._java_list.clear()
        for java in self._javas:
            item = QListWidgetItem()
            widget = self._create_java_item_widget(java)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, java)
            self._java_list.addItem(item)
            self._java_list.setItemWidget(item, widget)

    def _create_java_item_widget(self, java: JavaInfo) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        is_compatible, reason = True, ""
        if self._mc_version:
            is_compatible, reason = self._detector.is_compatible(java, self._mc_version)

        version_label = QLabel(f"Java {java.major_version}")
        version_label.setFont(QFont("", 10, QFont.Weight.Bold))
        layout.addWidget(version_label)

        vendor_label = QLabel(java.vendor)
        vendor_label.setStyleSheet("color: #9CA3AF;")
        layout.addWidget(vendor_label)

        arch_label = QLabel("64-bit" if java.is_64bit else "32-bit")
        arch_label.setStyleSheet(f"color: {'#9CA3AF' if java.is_64bit else '#F59E0B'};")
        layout.addWidget(arch_label)

        layout.addStretch()

        if is_compatible:
            compat_label = QLabel("✓ 兼容")
            compat_label.setStyleSheet("color: #10B981; font-weight: 600;")
        else:
            compat_label = QLabel(f"✗ {reason}")
            compat_label.setStyleSheet("color: #EF4444; font-weight: 600;")
        layout.addWidget(compat_label)

        return widget

    def _on_selection_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self._selected_java = None
            self._detail_frame.setVisible(False)
            self._set_default_btn.setEnabled(False)
            self.java_selected.emit(None)
            return

        self._selected_java = current.data(Qt.ItemDataRole.UserRole)
        self._show_detail(self._selected_java)
        self._set_default_btn.setEnabled(True)
        self.java_selected.emit(self._selected_java)

    def _show_detail(self, java: JavaInfo):
        self._detail_frame.setVisible(True)
        self._detail_version.setText(f"Java {java.major_version} ({java.version})")
        self._detail_vendor.setText(f"发行商: {java.vendor}")
        self._detail_path.setText(f"路径: {java.path}")
        self._detail_arch.setText(f"架构: {java.arch} ({'64位' if java.is_64bit else '32位'})")
        self._update_compatibility()

    def _update_compatibility(self):
        if not self._selected_java or not self._mc_version:
            self._compat_label.setText("")
            return

        is_compatible, reason = self._detector.is_compatible(self._selected_java, self._mc_version)
        if is_compatible:
            self._compat_label.setText("✓ 与当前版本兼容")
            self._compat_label.setStyleSheet("color: #10B981; font-weight: 600;")
        else:
            self._compat_label.setText(f"✗ 不兼容: {reason}")
            self._compat_label.setStyleSheet("color: #EF4444; font-weight: 600;")

    def _update_no_java_hint(self):
        if not self._mc_version:
            self._no_java_hint.setVisible(False)
            return

        required_ver = JavaDetector.get_required_java_version(self._mc_version)
        has_compatible = any(
            self._detector.is_compatible(j, self._mc_version)[0] for j in self._javas
        )
        self._no_java_hint.setVisible(not has_compatible)

    def _add_java(self):
        if sys.platform == "win32":
            filter_str = "Java 可执行文件 (java.exe);;所有文件 (*)"
        else:
            filter_str = "Java 可执行文件 (java);;所有文件 (*)"

        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Java 可执行文件", "", filter_str
        )
        if not path:
            return

        java_path = Path(path)
        info = self._detector.add_custom_java(java_path)
        if info:
            Toast.success(self, f"已添加 Java {info.major_version}")
            self.refresh_list()
        else:
            QMessageBox.warning(
                self, "无效的 Java",
                "所选路径不是有效的 Java 可执行文件。"
            )

    def _remove_java(self):
        if not self._selected_java:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要从列表中移除 Java {self._selected_java.major_version} 吗？\n\n"
            f"路径: {self._selected_java.path}\n\n"
            "这不会卸载系统中的 Java，只是从启动器列表中移除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._detector.remove_java(self._selected_java.path)
            Toast.success(self, "已移除")
            self.refresh_list()

    def _set_as_default(self):
        if not self._selected_java:
            return

        from src.utils.config import get_config
        config = get_config()
        config.set("java_path", str(self._selected_java.path))
        config.save()
        Toast.success(self, f"已设置 Java {self._selected_java.major_version} 为默认")

    def _download_java(self):
        required_ver = JavaDetector.get_required_java_version(self._mc_version) if self._mc_version else 17
        url = JavaDetector.get_java_download_url(required_ver)
        webbrowser.open(url)

    def get_selected_java(self) -> Optional[JavaInfo]:
        return self._selected_java

    def get_all_javas(self) -> list[JavaInfo]:
        return self._javas

    def select_java_by_path(self, path: str):
        for i in range(self._java_list.count()):
            item = self._java_list.item(i)
            java = item.data(Qt.ItemDataRole.UserRole)
            if java and str(java.path) == path:
                self._java_list.setCurrentItem(item)
                return
