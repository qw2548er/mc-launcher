"""下载对话框模块。

显示下载队列列表，支持暂停、继续、取消下载，展示进度和速度。
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QFrame, QSizePolicy, QSpacerItem
)

from .widgets import DialogTitleBar, DownloadItemWidget, CardWidget, Toast, ToastType

logger = logging.getLogger(__name__)


class DownloadDialog(QDialog):
    pause_all = pyqtSignal()
    resume_all = pyqtSignal()
    cancel_all = pyqtSignal()
    pause_task = pyqtSignal(str)
    resume_task = pyqtSignal(str)
    cancel_task = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._download_widgets: dict[str, DownloadItemWidget] = {}
        self._setup_window()
        self._setup_ui()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("下载管理"))
        self.setMinimumSize(580, 500)
        self.resize(620, 560)
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

        title_bar = DialogTitleBar(self, self.tr("下载管理"))
        title_bar.close_clicked.connect(self.reject)
        root_layout.addWidget(title_bar)

        summary_card = CardWidget()
        sl = summary_card.content_layout
        sl.setContentsMargins(20, 16, 20, 16)
        sl.setSpacing(12)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(24)

        self._total_progress = QProgressBar()
        self._total_progress.setObjectName("LargeProgressBar")
        self._total_progress.setRange(0, 100)
        self._total_progress.setValue(0)
        self._total_progress.setTextVisible(False)
        summary_row.addWidget(self._total_progress, 1)

        stats_col = QVBoxLayout()
        stats_col.setSpacing(4)

        self._percent_label = QLabel("0%")
        self._percent_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        stats_col.addWidget(self._percent_label)

        self._speed_label = QLabel(self.tr("速度: 0 KB/s"))
        self._speed_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        stats_col.addWidget(self._speed_label)

        self._remaining_label = QLabel(self.tr("剩余时间: 计算中"))
        self._remaining_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        stats_col.addWidget(self._remaining_label)

        summary_row.addLayout(stats_col)
        sl.addLayout(summary_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._pause_all_btn = QPushButton(self.tr("全部暂停"))
        self._pause_all_btn.clicked.connect(self._on_pause_all)
        btn_row.addWidget(self._pause_all_btn)

        self._clear_btn = QPushButton(self.tr("清除已完成"))
        self._clear_btn.clicked.connect(self._clear_completed)
        btn_row.addWidget(self._clear_btn)

        btn_row.addStretch()

        self._task_count_label = QLabel(self.tr("任务数: 0"))
        self._task_count_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        btn_row.addWidget(self._task_count_label)

        sl.addLayout(btn_row)
        root_layout.addWidget(summary_card)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(16, 8, 16, 16)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_container)
        root_layout.addWidget(scroll, 1)

        bottom_bar = QWidget()
        bottom_bar.setFixedHeight(56)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(20, 8, 20, 12)
        bottom_layout.addStretch()

        close_btn = QPushButton(self.tr("关闭"))
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(close_btn)

        root_layout.addWidget(bottom_bar)

    def add_download(self, task_id: str, filename: str) -> None:
        if task_id in self._download_widgets:
            return
        widget = DownloadItemWidget(task_id, filename)
        widget.pause_clicked.connect(self.pause_task.emit)
        widget.resume_clicked.connect(self.resume_task.emit)
        widget.cancel_clicked.connect(self._on_cancel_task)
        self._download_widgets[task_id] = widget
        self._list_layout.insertWidget(self._list_layout.count() - 1, widget)
        self._update_task_count()

    def update_download(self, task_id: str, percent: float, speed: float = 0,
                        downloaded: int = 0, total: int = 0,
                        status: str = "downloading") -> None:
        widget = self._download_widgets.get(task_id)
        if widget is None:
            return
        widget.update_progress(percent, speed, downloaded, total)
        widget.set_status(status)

    def set_total_progress(self, percent: float, total_speed: float = 0,
                           remaining: str = "") -> None:
        self._total_progress.setValue(int(percent))
        self._percent_label.setText(f"{percent:.1f}%")
        if total_speed > 0:
            self._speed_label.setText(self.tr("速度: ") + self._format_speed(total_speed))
        else:
            self._speed_label.setText(self.tr("速度: —"))
        if remaining:
            self._remaining_label.setText(self.tr("剩余时间: ") + remaining)
        else:
            self._remaining_label.setText(self.tr("剩余时间: 计算中"))

    def remove_download(self, task_id: str) -> None:
        widget = self._download_widgets.pop(task_id, None)
        if widget is not None:
            self._list_layout.removeWidget(widget)
            widget.deleteLater()
            self._update_task_count()

    def _on_pause_all(self) -> None:
        if self._pause_all_btn.text() == self.tr("全部暂停"):
            self.pause_all.emit()
            self._pause_all_btn.setText(self.tr("全部继续"))
        else:
            self.resume_all.emit()
            self._pause_all_btn.setText(self.tr("全部暂停"))

    def _on_cancel_task(self, task_id: str) -> None:
        self.cancel_task.emit(task_id)

    def _clear_completed(self) -> None:
        finished_statuses = {"completed", "cancelled", "failed", "skipped"}
        to_remove = [tid for tid, w in self._download_widgets.items()
                     if w.status in finished_statuses]
        for tid in to_remove:
            self.remove_download(tid)
        if to_remove:
            Toast.info(self.tr("已清除 {0} 个任务").format(len(to_remove)))

    def _update_task_count(self) -> None:
        count = len(self._download_widgets)
        self._task_count_label.setText(self.tr("任务数: {0}").format(count))

    @staticmethod
    def _format_speed(bytes_per_sec: float) -> str:
        if bytes_per_sec < 1024:
            return f"{bytes_per_sec:.0f} B/s"
        elif bytes_per_sec < 1024 * 1024:
            return f"{bytes_per_sec / 1024:.1f} KB/s"
        else:
            return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
