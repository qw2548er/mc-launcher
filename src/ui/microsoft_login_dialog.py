"""Microsoft 登录对话框。

显示设备码登录流程：
1. 显示用户码和验证链接
2. 提供"复制代码"和"打开浏览器"按钮
3. 后台轮询等待授权
4. 授权成功后自动返回
"""

from __future__ import annotations

import logging
import webbrowser
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QClipboard
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QProgressBar, QMessageBox
)

from src.core.auth import MicrosoftAuth, DeviceCodeInfo, AuthResult, AuthError
from .widgets import DialogTitleBar, Toast, ToastType

logger = logging.getLogger(__name__)


class _LoginPollThread(QThread):
    """后台轮询登录结果的线程。"""
    login_success = pyqtSignal(object)
    login_failed = pyqtSignal(str)
    progress_msg = pyqtSignal(str)

    def __init__(self, auth: MicrosoftAuth):
        super().__init__()
        self._auth = auth

    def run(self):
        try:
            result = self._auth.full_login(
                progress_callback=lambda msg: self.progress_msg.emit(msg)
            )
            self.login_success.emit(result)
        except AuthError as e:
            self.login_failed.emit(str(e))
        except Exception as e:
            logger.exception("登录线程异常")
            self.login_failed.emit(f"登录失败: {e}")

    def cancel(self):
        self._auth.cancel()


class MicrosoftLoginDialog(QDialog):
    """Microsoft 正版登录对话框。"""

    login_successful = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auth = MicrosoftAuth()
        self._poll_thread: Optional[_LoginPollThread] = None
        self._device_code: Optional[DeviceCodeInfo] = None
        self._setup_window()
        self._setup_ui()
        QTimer.singleShot(100, self._start_login)

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("微软正版登录"))
        self.setFixedSize(480, 440)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog
        )
        self.setModal(True)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title_bar = DialogTitleBar(self, self.tr("微软正版登录"))
        title_bar.close_clicked.connect(self._on_close)
        root.addWidget(title_bar)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(16)

        title = QLabel(self.tr("使用微软账号登录"))
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(self.tr("请按照以下步骤完成登录："))
        subtitle.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        step1 = QLabel(self.tr("1. 点击下方按钮打开浏览器"))
        step1.setStyleSheet("font-size: 13px;")
        layout.addWidget(step1)

        step2 = QLabel(self.tr("2. 在网页中输入以下代码并授权"))
        step2.setStyleSheet("font-size: 13px;")
        layout.addWidget(step2)

        code_frame = QFrame()
        code_frame.setStyleSheet(
            "QFrame { background-color: #1F2937; border-radius: 12px; "
            "border: 2px solid #7C3AED; }"
        )
        code_layout = QVBoxLayout(code_frame)
        code_layout.setContentsMargins(24, 20, 24, 20)
        code_layout.setSpacing(8)

        code_hint = QLabel(self.tr("授权代码"))
        code_hint.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        code_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_layout.addWidget(code_hint)

        self._code_label = QLabel("--------")
        code_font = QFont()
        code_font.setPointSize(28)
        code_font.setWeight(QFont.Weight.Bold)
        code_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 120)
        self._code_label.setFont(code_font)
        self._code_label.setStyleSheet("color: #A78BFA; letter-spacing: 4px;")
        self._code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_layout.addWidget(self._code_label)

        self._copy_btn = QPushButton(self.tr("📋 复制代码"))
        self._copy_btn.setStyleSheet(
            "QPushButton { background-color: #374151; color: white; border: none;"
            "border-radius: 8px; padding: 8px 16px; font-size: 13px; }"
            "QPushButton:hover { background-color: #4B5563; }"
        )
        self._copy_btn.clicked.connect(self._copy_code)
        code_layout.addWidget(self._copy_btn, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(code_frame)

        self._open_browser_btn = QPushButton(self.tr("🌐 打开浏览器并登录"))
        self._open_browser_btn.setObjectName("PrimaryButton")
        self._open_browser_btn.setMinimumHeight(44)
        self._open_browser_btn.setFont(QFont("", 12, QFont.Weight.DemiBold))
        self._open_browser_btn.clicked.connect(self._open_browser)
        self._open_browser_btn.setEnabled(False)
        layout.addWidget(self._open_browser_btn)

        self._status_label = QLabel(self.tr("正在获取登录代码..."))
        self._status_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        layout.addStretch()

        cancel_btn = QPushButton(self.tr("取消"))
        cancel_btn.setMinimumHeight(36)
        cancel_btn.clicked.connect(self._on_close)
        layout.addWidget(cancel_btn)

        root.addWidget(content, 1)

    def _start_login(self):
        try:
            self._device_code = self._auth.start_device_code_flow()
            self._code_label.setText(self._device_code.user_code)
            self._open_browser_btn.setEnabled(True)
            self._status_label.setText(self.tr("等待您在浏览器中完成授权..."))

            self._poll_thread = _LoginPollThread(self._auth)
            self._poll_thread.login_success.connect(self._on_login_success)
            self._poll_thread.login_failed.connect(self._on_login_failed)
            self._poll_thread.progress_msg.connect(self._on_progress)
            self._poll_thread.start()
            self._progress.show()
        except AuthError as e:
            self._status_label.setText(self.tr("启动登录失败"))
            QMessageBox.critical(self, self.tr("登录失败"), str(e))

    def _copy_code(self):
        if self._device_code:
            clipboard = self._get_clipboard()
            clipboard.setText(self._device_code.user_code)
            Toast.success(self, self.tr("代码已复制到剪贴板"))

    def _get_clipboard(self):
        from PyQt6.QtWidgets import QApplication
        return QApplication.clipboard()

    def _open_browser(self):
        if self._device_code:
            opened = self._auth.open_browser_for_login()
            if opened:
                self._status_label.setText(self.tr("浏览器已打开，请在网页中完成授权"))
            else:
                self._status_label.setText(
                    self.tr("请手动打开浏览器访问: %s").format(self._device_code.verification_uri)
                )
                QMessageBox.information(
                    self, self.tr("请手动打开浏览器"),
                    self.tr("请打开浏览器访问以下地址：\n%1\n并输入代码：%2").format(
                        self._device_code.verification_uri,
                        self._device_code.user_code
                    )
                )

    def _on_progress(self, msg: str):
        self._status_label.setText(msg)

    def _on_login_success(self, result: AuthResult):
        self._progress.hide()
        self.login_successful.emit(result)
        self.accept()

    def _on_login_failed(self, error: str):
        self._progress.hide()
        self._status_label.setText(self.tr("登录失败"))
        QMessageBox.critical(self, self.tr("登录失败"), error)
        self._open_browser_btn.setEnabled(False)
        self.reject()

    def _on_close(self):
        if self._poll_thread and self._poll_thread.isRunning():
            self._poll_thread.cancel()
            self._poll_thread.wait(3000)
        self.reject()

    def closeEvent(self, event):
        self._on_close()
        event.accept()
