"""添加/编辑服务器对话框。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QFrame, QMessageBox,
)

from src.core.server_manager import ServerInfo, DEFAULT_PORT


class AddServerDialog(QDialog):
    """添加或编辑服务器对话框。"""

    def __init__(self, server_info: ServerInfo | None = None, parent=None):
        super().__init__(parent)
        self._server_info = server_info
        self._is_edit = server_info is not None
        self._setup_ui()
        if self._is_edit and server_info:
            self._name_edit.setText(server_info.name)
            self._addr_edit.setText(server_info.address)
            self._port_spin.setValue(server_info.port)

    def _setup_ui(self) -> None:
        title = self.tr("编辑服务器") if self._is_edit else self.tr("添加服务器")
        self.setWindowTitle(title)
        self.setFixedSize(420, 260)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 20)
        layout.setSpacing(16)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title_label)

        hint = QLabel(self.tr("填写服务器信息，地址支持域名或IP。"))
        hint.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(4)

        name_row = QHBoxLayout()
        name_label = QLabel(self.tr("服务器名称:"))
        name_label.setFixedWidth(90)
        name_row.addWidget(name_label)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(self.tr("例如: 我的服务器"))
        self._name_edit.setFixedHeight(34)
        name_row.addWidget(self._name_edit, 1)
        layout.addLayout(name_row)

        addr_row = QHBoxLayout()
        addr_label = QLabel(self.tr("服务器地址:"))
        addr_label.setFixedWidth(90)
        addr_row.addWidget(addr_label)
        self._addr_edit = QLineEdit()
        self._addr_edit.setPlaceholderText("mc.example.com")
        self._addr_edit.setFixedHeight(34)
        addr_regex = QRegularExpression(r"[a-zA-Z0-9\.\-:]+")
        self._addr_edit.setValidator(QRegularExpressionValidator(addr_regex))
        addr_row.addWidget(self._addr_edit, 1)
        layout.addLayout(addr_row)

        port_row = QHBoxLayout()
        port_label = QLabel(self.tr("端口:"))
        port_label.setFixedWidth(90)
        port_row.addWidget(port_label)
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(DEFAULT_PORT)
        self._port_spin.setFixedHeight(34)
        self._port_spin.setFixedWidth(120)
        port_row.addWidget(self._port_spin)
        port_row.addStretch()
        layout.addLayout(port_row)

        layout.addStretch()

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #374151;")
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        cancel_btn = QPushButton(self.tr("取消"))
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.setFixedHeight(36)
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_text = self.tr("保存") if self._is_edit else self.tr("添加")
        ok_btn = QPushButton(ok_text)
        ok_btn.setObjectName("PrimaryButton")
        ok_btn.setFixedHeight(36)
        ok_btn.setFixedWidth(90)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _on_ok(self) -> None:
        name = self._name_edit.text().strip()
        address = self._addr_edit.text().strip()
        port = self._port_spin.value()

        if not name:
            QMessageBox.warning(self, self.tr("提示"), self.tr("请输入服务器名称"))
            return
        if not address:
            QMessageBox.warning(self, self.tr("提示"), self.tr("请输入服务器地址"))
            return

        address = address.split(":")[0].strip()
        if not address:
            QMessageBox.warning(self, self.tr("提示"), self.tr("服务器地址无效"))
            return

        self.result_name = name
        self.result_address = address
        self.result_port = port
        self.accept()

    def get_result(self) -> tuple[str, str, int]:
        return self.result_name, self.result_address, self.result_port
