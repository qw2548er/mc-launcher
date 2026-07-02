"""下载项组件。

显示单个下载任务的文件名、进度条、速度、状态和操作按钮。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, QPushButton
)


class DownloadItemWidget(QWidget):
    pause_clicked = pyqtSignal(str)
    resume_clicked = pyqtSignal(str)
    cancel_clicked = pyqtSignal(str)

    def __init__(self, task_id: str, filename: str, parent=None):
        super().__init__(parent)
        self._task_id = task_id
        self._filename = filename
        self._is_paused = False
        self._status = "pending"
        self._setup_ui()

    @property
    def status(self) -> str:
        return self._status

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._name_label = QLabel(self._filename)
        self._name_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        top_row.addWidget(self._name_label, 1)

        self._speed_label = QLabel("0 KB/s")
        self._speed_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self._speed_label.setMinimumWidth(80)
        self._speed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self._speed_label)

        self._status_label = QLabel("等待中")
        self._status_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self._status_label.setMinimumWidth(60)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self._status_label)

        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setObjectName("IconButton")
        self._pause_btn.setFixedSize(32, 32)
        self._pause_btn.setToolTip("暂停")
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        top_row.addWidget(self._pause_btn)

        self._cancel_btn = QPushButton("✕")
        self._cancel_btn.setObjectName("IconButton")
        self._cancel_btn.setFixedSize(32, 32)
        self._cancel_btn.setToolTip("取消")
        self._cancel_btn.clicked.connect(lambda: self.cancel_clicked.emit(self._task_id))
        top_row.addWidget(self._cancel_btn)

        layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        bottom_row.addWidget(self._progress_bar, 1)

        self._percent_label = QLabel("0%")
        self._percent_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self._percent_label.setMinimumWidth(45)
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom_row.addWidget(self._percent_label)

        layout.addLayout(bottom_row)

    @property
    def task_id(self) -> str:
        return self._task_id

    def _on_pause_clicked(self) -> None:
        if self._is_paused:
            self.resume_clicked.emit(self._task_id)
        else:
            self.pause_clicked.emit(self._task_id)

    def update_progress(self, percent: float, speed: float = 0,
                        downloaded: int = 0, total: int = 0) -> None:
        self._progress_bar.setValue(int(percent))
        self._percent_label.setText(f"{percent:.1f}%")
        if speed > 0:
            self._speed_label.setText(self._format_speed(speed))
        if total > 0:
            self._status_label.setText(
                f"{self._format_size(downloaded)} / {self._format_size(total)}"
            )

    def set_status(self, status: str) -> None:
        self._status = status
        status_map = {
            "pending": "等待中",
            "downloading": "下载中",
            "paused": "已暂停",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
            "skipped": "已跳过",
        }
        self._status_label.setText(status_map.get(status, status))
        if status == "downloading":
            self._is_paused = False
            self._pause_btn.setText("⏸")
            self._pause_btn.setToolTip("暂停")
        elif status == "paused":
            self._is_paused = True
            self._pause_btn.setText("▶")
            self._pause_btn.setToolTip("继续")
            self._speed_label.setText("—")
        elif status in ("completed", "failed", "cancelled", "skipped"):
            self._pause_btn.setEnabled(False)
            self._speed_label.setText("—")

    def set_speed(self, speed: float) -> None:
        if speed > 0:
            self._speed_label.setText(self._format_speed(speed))
        else:
            self._speed_label.setText("—")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    @staticmethod
    def _format_speed(bytes_per_sec: float) -> str:
        if bytes_per_sec < 1024:
            return f"{bytes_per_sec:.0f} B/s"
        elif bytes_per_sec < 1024 * 1024:
            return f"{bytes_per_sec / 1024:.1f} KB/s"
        else:
            return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
