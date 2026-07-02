"""账号对话框模块。

提供账号管理界面，支持添加正版/离线账号、切换、删除账号。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QFrame, QSizePolicy,
    QMessageBox, QInputDialog
)

from .widgets import DialogTitleBar, CardWidget, Toast, ToastType

logger = logging.getLogger(__name__)


@dataclass
class AccountEntry:
    uuid: str
    username: str
    account_type: str
    access_token: str = ""
    is_selected: bool = False


class AccountDialog(QDialog):
    account_added = pyqtSignal(str, str)
    account_removed = pyqtSignal(str)
    account_selected = pyqtSignal(str)
    login_microsoft = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accounts: list[AccountEntry] = []
        self._setup_window()
        self._setup_ui()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("账号管理"))
        self.setMinimumSize(560, 480)
        self.resize(600, 520)
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

        title_bar = DialogTitleBar(self, self.tr("账号管理"))
        title_bar.close_clicked.connect(self.reject)
        root_layout.addWidget(title_bar)

        content = QHBoxLayout()
        content.setContentsMargins(16, 16, 16, 8)
        content.setSpacing(16)

        self._setup_account_list(content)
        self._setup_detail_panel(content)
        root_layout.addLayout(content, 1)

        self._setup_bottom_bar(root_layout)

    def _setup_account_list(self, parent_layout: QHBoxLayout) -> None:
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_label = QLabel(self.tr("账号列表"))
        header_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        header_row.addWidget(header_label)
        header_row.addStretch()

        self._add_btn = QPushButton("+")
        self._add_btn.setObjectName("IconButton")
        self._add_btn.setFixedSize(32, 32)
        self._add_btn.setToolTip(self.tr("添加账号"))
        self._add_btn.clicked.connect(self._show_add_menu)
        header_row.addWidget(self._add_btn)

        list_layout.addLayout(header_row)

        self._account_list = QListWidget()
        self._account_list.setSpacing(2)
        self._account_list.currentItemChanged.connect(self._on_account_selected)
        list_layout.addWidget(self._account_list, 1)

        parent_layout.addWidget(list_container, 2)

        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFixedWidth(1)
        parent_layout.addWidget(sep)

    def _setup_detail_panel(self, parent_layout: QHBoxLayout) -> None:
        panel = QWidget()
        panel.setFixedWidth(260)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(16)
        panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._avatar_label = QLabel("👤")
        self._avatar_label.setFixedSize(80, 80)
        self._avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar_label.setStyleSheet(
            "background-color: #7C3AED; border-radius: 40px;"
            "font-size: 36px; color: white;"
        )
        panel_layout.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._name_label = QLabel(self.tr("未选择账号"))
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setWeight(QFont.Weight.Bold)
        self._name_label.setFont(name_font)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._name_label)

        self._type_label = QLabel("")
        self._type_label.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        self._type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._type_label)

        self._uuid_label = QLabel("")
        self._uuid_label.setStyleSheet("color: #6B7280; font-size: 11px;")
        self._uuid_label.setWordWrap(True)
        self._uuid_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._uuid_label)

        panel_layout.addSpacing(20)

        self._select_btn = QPushButton(self.tr("切换到此账号"))
        self._select_btn.setObjectName("PrimaryButton")
        self._select_btn.clicked.connect(self._select_account)
        self._select_btn.setEnabled(False)
        panel_layout.addWidget(self._select_btn)

        self._refresh_btn = QPushButton(self.tr("刷新令牌"))
        self._refresh_btn.clicked.connect(self._refresh_account)
        self._refresh_btn.setEnabled(False)
        panel_layout.addWidget(self._refresh_btn)

        self._remove_btn = QPushButton(self.tr("删除账号"))
        self._remove_btn.setStyleSheet(
            "QPushButton { color: #EF4444; border-color: #EF444460; }"
            "QPushButton:hover { background-color: #EF444420; }"
        )
        self._remove_btn.clicked.connect(self._remove_account)
        self._remove_btn.setEnabled(False)
        panel_layout.addWidget(self._remove_btn)

        panel_layout.addStretch()
        parent_layout.addWidget(panel, 1)

    def _setup_bottom_bar(self, parent_layout: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setFixedHeight(56)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(20, 8, 20, 12)
        bar_layout.addStretch()

        close_btn = QPushButton(self.tr("关闭"))
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(self.accept)
        bar_layout.addWidget(close_btn)

        parent_layout.addWidget(bar)

    def _show_add_menu(self) -> None:
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        offline_action = menu.addAction(self.tr("离线登录"))
        microsoft_action = menu.addAction(self.tr("微软正版登录"))
        action = menu.exec(self._add_btn.mapToGlobal(
            self._add_btn.rect().bottomLeft()
        ))
        if action == offline_action:
            self._add_offline_account()
        elif action == microsoft_action:
            self._add_microsoft_account()

    def _add_offline_account(self) -> None:
        username, ok = QInputDialog.getText(
            self, self.tr("离线登录"), self.tr("请输入玩家名:")
        )
        if not ok or not username.strip():
            return
        username = username.strip()
        if len(username) > 16:
            Toast.warning(self.tr("玩家名不能超过 16 个字符"))
            return
        account_uuid = str(uuid.uuid3(uuid.NAMESPACE_OID, f"OfflinePlayer:{username}"))
        entry = AccountEntry(
            uuid=account_uuid,
            username=username,
            account_type="offline"
        )
        for acc in self._accounts:
            if acc.username == username and acc.account_type == "offline":
                Toast.warning(self.tr("该离线账号已存在"))
                return
        self._accounts.append(entry)
        self._refresh_list()
        self.account_added.emit(account_uuid, "offline")
        Toast.success(self.tr("已添加离线账号: {0}").format(username))

    def _add_microsoft_account(self) -> None:
        Toast.info(self.tr("正在打开浏览器进行微软登录..."))
        self.login_microsoft.emit()

    def add_microsoft_account(self, username: str, account_uuid: str,
                               access_token: str) -> None:
        entry = AccountEntry(
            uuid=account_uuid,
            username=username,
            account_type="microsoft",
            access_token=access_token
        )
        self._accounts = [a for a in self._accounts if a.uuid != account_uuid]
        self._accounts.append(entry)
        self._refresh_list()
        self.account_added.emit(account_uuid, "microsoft")
        Toast.success(self.tr("已登录: {0}").format(username))

    def _on_account_selected(self, current: QListWidgetItem, previous) -> None:
        if current is None:
            self._name_label.setText(self.tr("未选择账号"))
            self._type_label.setText("")
            self._uuid_label.setText("")
            self._select_btn.setEnabled(False)
            self._refresh_btn.setEnabled(False)
            self._remove_btn.setEnabled(False)
            return
        idx = self._account_list.row(current)
        if 0 <= idx < len(self._accounts):
            acc = self._accounts[idx]
            self._name_label.setText(acc.username)
            type_text = self.tr("正版登录") if acc.account_type == "microsoft" else self.tr("离线模式")
            if acc.is_selected:
                type_text += " · " + self.tr("当前使用")
            self._type_label.setText(type_text)
            self._uuid_label.setText(f"UUID: {acc.uuid[:8]}...{acc.uuid[-8:]}")
            is_microsoft = acc.account_type == "microsoft"
            self._refresh_btn.setEnabled(is_microsoft)
            self._select_btn.setEnabled(not acc.is_selected)
            self._remove_btn.setEnabled(True)

    def _select_account(self) -> None:
        item = self._account_list.currentItem()
        if item is None:
            return
        idx = self._account_list.row(item)
        if 0 <= idx < len(self._accounts):
            acc = self._accounts[idx]
            for a in self._accounts:
                a.is_selected = False
            acc.is_selected = True
            self._refresh_list()
            self.account_selected.emit(acc.uuid)
            Toast.success(self.tr("已切换到: {0}").format(acc.username))

    def _refresh_account(self) -> None:
        item = self._account_list.currentItem()
        if item is None:
            return
        Toast.info(self.tr("令牌刷新功能需要实现 OAuth 流程"))

    def _remove_account(self) -> None:
        item = self._account_list.currentItem()
        if item is None:
            return
        idx = self._account_list.row(item)
        if 0 <= idx < len(self._accounts):
            acc = self._accounts[idx]
            reply = QMessageBox.question(
                self, self.tr("删除账号"),
                self.tr("确定要删除账号 {0} 吗？").format(acc.username),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self._accounts[idx]
                self._refresh_list()
                self.account_removed.emit(acc.uuid)
                Toast.info(self.tr("已删除账号"))

    def _refresh_list(self) -> None:
        self._account_list.clear()
        for acc in self._accounts:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 60))
            widget = self._create_account_item_widget(acc)
            self._account_list.addItem(item)
            self._account_list.setItemWidget(item, widget)

    def _create_account_item_widget(self, acc: AccountEntry) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        avatar = QLabel("👤")
        avatar.setFixedSize(40, 40)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if acc.account_type == "microsoft":
            avatar.setStyleSheet(
                "background-color: #10B981; border-radius: 20px; font-size: 18px; color: white;"
            )
        else:
            avatar.setStyleSheet(
                "background-color: #7C3AED; border-radius: 20px; font-size: 18px; color: white;"
            )
        layout.addWidget(avatar)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_label = QLabel(acc.username)
        name_font = QFont()
        name_font.setWeight(QFont.Weight.DemiBold)
        name_font.setPointSize(12)
        name_label.setFont(name_font)
        name_row.addWidget(name_label)

        if acc.is_selected:
            selected_tag = QLabel(self.tr("当前"))
            selected_tag.setStyleSheet(
                "background-color: #7C3AED; color: white; font-size: 10px;"
                "font-weight: 700; padding: 2px 8px; border-radius: 6px;"
            )
            name_row.addWidget(selected_tag)
        name_row.addStretch()
        info_col.addLayout(name_row)

        type_text = self.tr("正版") if acc.account_type == "microsoft" else self.tr("离线")
        type_label = QLabel(type_text)
        type_label.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        info_col.addWidget(type_label)

        layout.addLayout(info_col, 1)
        return widget

    def set_accounts(self, accounts: list[dict]) -> None:
        self._accounts = []
        for a in accounts:
            self._accounts.append(AccountEntry(
                uuid=a.get("uuid", ""),
                username=a.get("username", ""),
                account_type=a.get("type", "offline"),
                access_token=a.get("access_token", ""),
                is_selected=a.get("is_selected", False)
            ))
        self._refresh_list()
