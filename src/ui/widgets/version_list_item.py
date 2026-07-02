"""版本列表项组件。

显示版本名称、类型标签（正式版/快照版等）、安装状态、下载进度和操作按钮。
"""

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QProgressBar, QPushButton, QSizePolicy)


class VersionListItem(QWidget):
    download_clicked = pyqtSignal(str)
    cancel_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)

    def __init__(self, version_id: str, version_type: str = "release",
                 release_time: str = "", is_installed: bool = False,
                 is_latest: bool = False, parent=None):
        super().__init__(parent)
        self.version_id = version_id
        self.version_type = version_type
        self.release_time = release_time
        self.is_installed = is_installed
        self.is_latest = is_latest
        self.is_downloading = False
        self.download_progress = 0
        self.download_speed = ""
        self.download_eta = ""
        self.current_file = ""

        self.setup_ui()
        self.set_installed(is_installed)

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        self.check_label = QLabel("")
        self.check_label.setFixedSize(24, 24)
        font = QFont()
        font.setFamily("Segoe UI Emoji")
        self.check_label.setFont(font)
        self.check_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.check_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        info_layout.setContentsMargins(0, 0, 0, 0)

        name_layout = QHBoxLayout()
        name_layout.setSpacing(8)

        self.name_label = QLabel(self.version_id)
        name_font = QFont()
        name_font.setPointSize(10)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        name_layout.addWidget(self.name_label)

        if self.is_latest:
            latest_tag = QLabel("最新")
            latest_tag.setStyleSheet("""
                QLabel {
                    background-color: #7C3AED;
                    color: white;
                    padding: 2px 8px;
                    border-radius: 4px;
                    font-size: 9px;
                    font-weight: bold;
                }
            """)
            name_layout.addWidget(latest_tag)

        self.type_label = QLabel(self._get_type_text())
        self.type_label.setStyleSheet(f"""
            QLabel {{
                background-color: {self._get_type_color()};
                color: white;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 9px;
                font-weight: bold;
            }}
        """)
        name_layout.addWidget(self.type_label)
        name_layout.addStretch()

        info_layout.addLayout(name_layout)

        if self.release_time:
            self.time_label = QLabel(self.release_time)
            time_font = QFont()
            time_font.setPointSize(8)
            self.time_label.setFont(time_font)
            self.time_label.setStyleSheet("color: #888888;")
            info_layout.addWidget(self.time_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("")
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 8px;
                background-color: #e0e0e0;
                text-align: center;
                font-size: 9px;
                color: #333333;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4CAF50, stop:1 #8BC34A);
            }
        """)
        self.progress_bar.hide()
        info_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        status_font = QFont()
        status_font.setPointSize(8)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("color: #666666;")
        info_layout.addWidget(self.status_label)

        layout.addLayout(info_layout, stretch=1)

        self.action_btn = QPushButton()
        self.action_btn.setFixedSize(80, 32)
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.clicked.connect(self._on_action_clicked)
        layout.addWidget(self.action_btn)

        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            VersionListItem {
                background-color: transparent;
                border-radius: 8px;
            }
            VersionListItem:hover {
                background-color: #f5f5f5;
            }
        """)

    def _get_type_text(self) -> str:
        type_map = {
            "release": "正式版",
            "snapshot": "快照版",
            "old_beta": "Beta",
            "old_alpha": "Alpha",
            "local": "本地版"
        }
        return type_map.get(self.version_type, self.version_type)

    def _get_type_color(self) -> str:
        color_map = {
            "release": "#4CAF50",
            "snapshot": "#FF9800",
            "old_beta": "#9C27B0",
            "old_alpha": "#E91E63",
            "local": "#607D8B"
        }
        return color_map.get(self.version_type, "#607D8B")

    def set_installed(self, installed: bool):
        self.is_installed = installed
        if installed:
            self.check_label.setText("✓")
            self.check_label.setStyleSheet("color: #4CAF50; font-size: 18px; font-weight: bold;")
            self.action_btn.setText("删除")
            self.action_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #d32f2f;
                }
            """)
            self.status_label.setText("已安装")
            self.status_label.setStyleSheet("color: #4CAF50;")
            self.progress_bar.hide()
            self.is_downloading = False
        else:
            self.check_label.setText("")
            self.action_btn.setText("下载")
            self.action_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1976D2;
                }
            """)
            self.status_label.setText("未安装")
            self.status_label.setStyleSheet("color: #888888;")
            self.progress_bar.hide()
            self.is_downloading = False

    def set_downloading(self, downloading: bool):
        self.is_downloading = downloading
        if downloading:
            self.check_label.setText("↓")
            self.check_label.setStyleSheet("color: #2196F3; font-size: 16px; font-weight: bold;")
            self.action_btn.setText("取消")
            self.action_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF9800;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #F57C00;
                }
            """)
            self.progress_bar.show()
            self.status_label.setStyleSheet("color: #2196F3;")
        else:
            self.set_installed(self.is_installed)

    def update_progress(self, progress: float, speed: str = "", eta: str = "",
                        current_file: str = ""):
        self.download_progress = progress
        self.download_speed = speed
        self.download_eta = eta
        self.current_file = current_file

        self.progress_bar.setValue(int(min(progress, 100)))
        if progress > 0:
            self.progress_bar.setFormat(f"{progress:.1f}%")

        status_parts = []
        if speed:
            status_parts.append(speed)
        if eta:
            status_parts.append(f"剩余: {eta}")
        if current_file:
            short_file = current_file.split("/")[-1] if "/" in current_file else current_file
            if len(short_file) > 30:
                short_file = short_file[:27] + "..."
            status_parts.append(short_file)

        if status_parts:
            self.status_label.setText(" | ".join(status_parts))
        else:
            self.status_label.setText("下载中...")

    def set_error(self, error_msg: str):
        self.is_downloading = False
        self.check_label.setText("✗")
        self.check_label.setStyleSheet("color: #f44336; font-size: 16px; font-weight: bold;")
        self.action_btn.setText("重试")
        self.action_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self.progress_bar.hide()
        if len(error_msg) > 50:
            error_msg = error_msg[:47] + "..."
        self.status_label.setText(f"失败: {error_msg}")
        self.status_label.setStyleSheet("color: #f44336;")
        self.is_installed = False

    def _on_action_clicked(self):
        if self.is_downloading:
            self.cancel_clicked.emit(self.version_id)
        elif self.is_installed:
            self.delete_clicked.emit(self.version_id)
        else:
            self.download_clicked.emit(self.version_id)
