"""账号对话框模块。

提供账号管理界面，支持添加正版/离线账号、切换、删除账号，
显示皮肤头像，集成 Microsoft OAuth 登录流程。
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QFrame, QSizePolicy,
    QMessageBox, QInputDialog, QMenu
)

from src.core.account import AccountManager, AccountInfo
from src.core.auth import AuthResult
from src.core.skin_manager import get_skin_manager
from .widgets import DialogTitleBar, Toast

logger = logging.getLogger(__name__)

AVATAR_SIZE_LIST = 40
AVATAR_SIZE_DETAIL = 96


class _AvatarLoadThread(QThread):
    """后台加载头像的线程。"""
    avatar_loaded = pyqtSignal(str, str)

    def __init__(self, uuid_str: str, username: str, skin_url: Optional[str], size: int):
        super().__init__()
        self._uuid = uuid_str
        self._username = username
        self._skin_url = skin_url
        self._size = size

    def run(self):
        try:
            mgr = get_skin_manager()
            avatar_path = mgr.get_avatar(
                self._uuid, self._username, self._skin_url,
                size=self._size, download=True
            )
            if avatar_path:
                self.avatar_loaded.emit(self._uuid, str(avatar_path))
        except Exception as e:
            logger.debug("加载头像失败 %s: %s", self._uuid, e)


class AccountDialog(QDialog):
    """账号管理对话框。"""

    account_added = pyqtSignal(str)
    account_removed = pyqtSignal(str)
    account_selected = pyqtSignal(str)
    accounts_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._account_manager = AccountManager()
        self._accounts: list[AccountInfo] = []
        self._avatar_threads: list[_AvatarLoadThread] = []
        self._avatar_cache: dict[str, QPixmap] = {}
        self._setup_window()
        self._setup_ui()
        self._load_accounts()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("账号管理"))
        self.setMinimumSize(620, 520)
        self.resize(680, 560)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog
        )
        self.setModal(True)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title_bar = DialogTitleBar(self, self.tr("账号管理"))
        title_bar.close_clicked.connect(self.reject)
        root.addWidget(title_bar)

        content = QHBoxLayout()
        content.setContentsMargins(16, 16, 16, 8)
        content.setSpacing(16)

        self._setup_account_list(content)
        self._setup_detail_panel(content)
        root.addLayout(content, 1)

        self._setup_bottom_bar(root)

    def _setup_account_list(self, parent_layout: QHBoxLayout) -> None:
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_label = QLabel(self.tr("账号列表"))
        header_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        header_row.addWidget(header_label)

        count_label = QLabel("")
        count_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self._count_label = count_label
        header_row.addWidget(count_label)

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
        self._account_list.setObjectName("AccountList")
        self._account_list.currentItemChanged.connect(self._on_account_selected)
        list_layout.addWidget(self._account_list, 1)

        parent_layout.addWidget(list_container, 2)

        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFixedWidth(1)
        parent_layout.addWidget(sep)

    def _setup_detail_panel(self, parent_layout: QHBoxLayout) -> None:
        panel = QWidget()
        panel.setFixedWidth(280)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(12)
        panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._avatar_label = QLabel("👤")
        self._avatar_label.setFixedSize(AVATAR_SIZE_DETAIL, AVATAR_SIZE_DETAIL)
        self._avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar_label.setStyleSheet(
            "background-color: #374151; border-radius: 12px; font-size: 42px;"
        )
        self._avatar_label.setScaledContents(True)
        panel_layout.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._name_label = QLabel(self.tr("未选择账号"))
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setWeight(QFont.Weight.Bold)
        self._name_label.setFont(name_font)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._name_label)

        self._type_label = QLabel("")
        self._type_label.setStyleSheet("font-size: 13px;")
        self._type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._type_label)

        self._uuid_label = QLabel("")
        self._uuid_label.setStyleSheet("color: #6B7280; font-size: 11px;")
        self._uuid_label.setWordWrap(True)
        self._uuid_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._uuid_label)

        self._token_status = QLabel("")
        self._token_status.setStyleSheet("font-size: 11px;")
        self._token_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._token_status.setWordWrap(True)
        panel_layout.addWidget(self._token_status)

        panel_layout.addSpacing(12)

        self._select_btn = QPushButton(self.tr("切换到此账号"))
        self._select_btn.setObjectName("PrimaryButton")
        self._select_btn.setMinimumHeight(38)
        self._select_btn.clicked.connect(self._select_account)
        self._select_btn.setEnabled(False)
        panel_layout.addWidget(self._select_btn)

        self._refresh_btn = QPushButton(self.tr("刷新令牌"))
        self._refresh_btn.setMinimumHeight(36)
        self._refresh_btn.clicked.connect(self._refresh_account)
        self._refresh_btn.setEnabled(False)
        panel_layout.addWidget(self._refresh_btn)

        self._remove_btn = QPushButton(self.tr("删除账号"))
        self._remove_btn.setMinimumHeight(36)
        self._remove_btn.setStyleSheet(
            "QPushButton { color: #EF4444; border-color: #EF444460; }"
            "QPushButton:hover { background-color: #EF444420; }"
        )
        self._remove_btn.clicked.connect(self._remove_account)
        self._remove_btn.setEnabled(False)
        panel_layout.addWidget(self._remove_btn)

        panel_layout.addSpacing(8)

        self._skin_btn = QPushButton(self.tr("管理皮肤"))
        self._skin_btn.setMinimumHeight(36)
        self._skin_btn.setObjectName("SecondaryButton")
        self._skin_btn.clicked.connect(self._open_skin_manager)
        self._skin_btn.setEnabled(False)
        panel_layout.addWidget(self._skin_btn)

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
        close_btn.setMinimumHeight(36)
        close_btn.clicked.connect(self.accept)
        bar_layout.addWidget(close_btn)

        parent_layout.addWidget(bar)

    def _load_accounts(self):
        self._accounts = self._account_manager.get_all()
        self._refresh_list()
        self._count_label.setText(f"({len(self._accounts)} 个账号)")

        selected = self._account_manager.get_selected()
        if selected:
            for i, acc in enumerate(self._accounts):
                if acc.uuid == selected.uuid:
                    self._account_list.setCurrentRow(i)
                    break

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        offline_action = menu.addAction(self.tr("添加离线账号"))
        offline_action.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_ComputerIcon
        ))
        microsoft_action = menu.addAction(self.tr("微软正版登录"))
        microsoft_action.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_DriveNetIcon
        ))

        action = menu.exec(self._add_btn.mapToGlobal(
            self._add_btn.rect().bottomLeft()
        ))
        if action == offline_action:
            self._add_offline_account()
        elif action == microsoft_action:
            self._add_microsoft_account()

    def _add_offline_account(self) -> None:
        username, ok = QInputDialog.getText(
            self, self.tr("添加离线账号"),
            self.tr("请输入玩家名:\n(3-16位字母、数字、下划线)")
        )
        if not ok or not username.strip():
            return
        username = username.strip()

        try:
            account = self._account_manager.add_offline_account(username)
            self._load_accounts()
            self._load_avatar_async(account)
            self.accounts_changed.emit()
            Toast.success(self.tr("已添加离线账号: {0}").format(username))

            for i, acc in enumerate(self._accounts):
                if acc.uuid == account.uuid:
                    self._account_list.setCurrentRow(i)
                    break
        except ValueError as e:
            QMessageBox.warning(self, self.tr("输入错误"), str(e))

    def _add_microsoft_account(self) -> None:
        from .microsoft_login_dialog import MicrosoftLoginDialog
        dialog = MicrosoftLoginDialog(self)
        dialog.login_successful.connect(self._on_ms_login_success)
        dialog.exec()

    def _on_ms_login_success(self, result: AuthResult):
        profile = result.profile
        account = self._account_manager.add_microsoft_account(
            account_uuid=profile.uuid,
            username=profile.username,
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_in=result.expires_in,
            skin_url=profile.skin_url,
            skin_variant=profile.skin_variant,
        )
        self._load_accounts()
        self._load_avatar_async(account)
        self.accounts_changed.emit()
        self.account_added.emit(account.uuid)
        Toast.success(self.tr("登录成功: {0}").format(profile.username))

        for i, acc in enumerate(self._accounts):
            if acc.uuid == account.uuid:
                self._account_list.setCurrentRow(i)
                break

    def _on_account_selected(self, current: QListWidgetItem, previous) -> None:
        if current is None:
            self._name_label.setText(self.tr("未选择账号"))
            self._type_label.setText("")
            self._uuid_label.setText("")
            self._token_status.setText("")
            self._avatar_label.setText("👤")
            self._avatar_label.setPixmap(QPixmap())
            self._select_btn.setEnabled(False)
            self._refresh_btn.setEnabled(False)
            self._remove_btn.setEnabled(False)
            self._skin_btn.setEnabled(False)
            return

        idx = self._account_list.row(current)
        if 0 <= idx < len(self._accounts):
            acc = self._accounts[idx]
            self._name_label.setText(acc.username)

            type_text = self.tr("正版登录") if acc.is_microsoft else self.tr("离线模式")
            if acc.is_selected:
                type_text += "  ● " + self.tr("当前使用")
            type_color = "#10B981" if acc.is_microsoft else "#7C3AED"
            self._type_label.setText(type_text)
            self._type_label.setStyleSheet(f"font-size: 13px; color: {type_color};")

            short_uuid = f"{acc.uuid[:8]}...{acc.uuid[-8:]}"
            self._uuid_label.setText(f"UUID: {short_uuid}")

            if acc.is_microsoft:
                self._refresh_btn.setEnabled(True)
                if acc.is_token_expired:
                    self._token_status.setText(self.tr("⚠ Token 已过期，需要刷新"))
                    self._token_status.setStyleSheet("color: #EF4444; font-size: 11px;")
                else:
                    self._token_status.setText(self.tr("✓ Token 有效"))
                    self._token_status.setStyleSheet("color: #10B981; font-size: 11px;")
            else:
                self._refresh_btn.setEnabled(False)
                self._token_status.setText("")

            self._select_btn.setEnabled(not acc.is_selected)
            self._remove_btn.setEnabled(True)
            self._skin_btn.setEnabled(True)

            self._load_avatar_for_detail(acc)

    def _load_avatar_for_detail(self, acc: AccountInfo):
        self._avatar_label.setPixmap(QPixmap())
        self._avatar_label.setText("⏳")
        self._avatar_label.setStyleSheet(
            "background-color: #374151; border-radius: 12px; font-size: 36px;"
        )

        mgr = get_skin_manager()
        cached = mgr.get_avatar_path(acc.uuid, AVATAR_SIZE_DETAIL)
        if cached.exists() and cached.stat().st_size > 0:
            pm = QPixmap(str(cached))
            if not pm.isNull():
                self._avatar_label.setPixmap(pm)
                self._avatar_label.setText("")
                self._avatar_label.setStyleSheet(
                    "background-color: transparent; border-radius: 12px;"
                )
                return

        thread = _AvatarLoadThread(acc.uuid, acc.username, acc.skin_url, AVATAR_SIZE_DETAIL)
        thread.avatar_loaded.connect(self._on_detail_avatar_loaded)
        self._avatar_threads.append(thread)
        thread.start()

    def _on_detail_avatar_loaded(self, uuid_str: str, path: str):
        current = self._get_current_account()
        if current and current.uuid == uuid_str:
            pm = QPixmap(path)
            if not pm.isNull():
                self._avatar_label.setPixmap(pm)
                self._avatar_label.setText("")
                self._avatar_label.setStyleSheet(
                    "background-color: transparent; border-radius: 12px;"
                )

    def _load_avatar_async(self, acc: AccountInfo, size: int = AVATAR_SIZE_LIST):
        mgr = get_skin_manager()
        cached = mgr.get_avatar_path(acc.uuid, size)
        if cached.exists() and cached.stat().st_size > 0:
            self._avatar_cache[acc.uuid] = QPixmap(str(cached))
            return

        thread = _AvatarLoadThread(acc.uuid, acc.username, acc.skin_url, size)
        thread.avatar_loaded.connect(self._on_list_avatar_loaded)
        self._avatar_threads.append(thread)
        thread.start()

    def _on_list_avatar_loaded(self, uuid_str: str, path: str):
        pm = QPixmap(path)
        if not pm.isNull():
            self._avatar_cache[uuid_str] = pm
            for i in range(self._account_list.count()):
                item = self._account_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == uuid_str:
                    widget = self._account_list.itemWidget(item)
                    if widget:
                        avatar_label = widget.findChild(QLabel, "avatar_label")
                        if avatar_label:
                            avatar_label.setPixmap(pm)
                            avatar_label.setText("")
                    break

    def _select_account(self) -> None:
        acc = self._get_current_account()
        if acc:
            self._account_manager.switch_account(acc.uuid)
            self._load_accounts()
            self.account_selected.emit(acc.uuid)
            self.accounts_changed.emit()
            Toast.success(self.tr("已切换到: {0}").format(acc.username))

    def _refresh_account(self) -> None:
        acc = self._get_current_account()
        if not acc or not acc.is_microsoft:
            return

        Toast.info(self.tr("正在刷新令牌..."))
        valid = self._account_manager.ensure_valid_token(acc)
        if valid:
            self._load_accounts()
            Toast.success(self.tr("令牌刷新成功"))
        else:
            QMessageBox.warning(
                self, self.tr("刷新失败"),
                self.tr("令牌刷新失败，请重新登录。")
            )

    def _remove_account(self) -> None:
        acc = self._get_current_account()
        if not acc:
            return

        reply = QMessageBox.question(
            self, self.tr("删除账号"),
            self.tr("确定要删除账号 {0} 吗？\n此操作不可恢复。").format(acc.username),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._account_manager.remove_account(acc.uuid)
            self._avatar_cache.pop(acc.uuid, None)
            self._load_accounts()
            self.account_removed.emit(acc.uuid)
            self.accounts_changed.emit()
            Toast.info(self.tr("已删除账号"))

    def _get_current_account(self) -> Optional[AccountInfo]:
        item = self._account_list.currentItem()
        if item is None:
            return None
        idx = self._account_list.row(item)
        if 0 <= idx < len(self._accounts):
            return self._accounts[idx]
        return None

    def _refresh_list(self) -> None:
        self._account_list.clear()
        for acc in self._accounts:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, acc.uuid)
            item.setSizeHint(QSize(0, 64))
            widget = self._create_account_item_widget(acc)
            self._account_list.addItem(item)
            self._account_list.setItemWidget(item, widget)
            self._load_avatar_async(acc)

    def _create_account_item_widget(self, acc: AccountInfo) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        avatar = QLabel("👤")
        avatar.setObjectName("avatar_label")
        avatar.setFixedSize(AVATAR_SIZE_LIST, AVATAR_SIZE_LIST)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setScaledContents(True)
        if acc.uuid in self._avatar_cache:
            pm = self._avatar_cache[acc.uuid]
            if not pm.isNull():
                avatar.setPixmap(pm)
                avatar.setText("")

        if acc.is_microsoft:
            bg_color = "#10B981"
        else:
            bg_color = "#7C3AED"
        if acc.uuid not in self._avatar_cache:
            avatar.setStyleSheet(
                f"background-color: {bg_color}; border-radius: "
                f"{AVATAR_SIZE_LIST // 2}px; font-size: 18px; color: white;"
            )
        else:
            avatar.setStyleSheet(
                f"border-radius: {AVATAR_SIZE_LIST // 2}px;"
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

        if acc.is_microsoft:
            ms_tag = QLabel("MS")
            ms_tag.setStyleSheet(
                "background-color: #10B981; color: white; font-size: 9px;"
                "font-weight: 700; padding: 2px 5px; border-radius: 4px;"
            )
            name_row.addWidget(ms_tag)

        name_row.addStretch()
        info_col.addLayout(name_row)

        type_text = self.tr("正版") if acc.is_microsoft else self.tr("离线")
        if acc.is_microsoft and acc.is_token_expired:
            type_text += " · " + self.tr("需要刷新")
            type_color = "#EF4444"
        else:
            type_color = "#9CA3AF"
        type_label = QLabel(type_text)
        type_label.setStyleSheet(f"color: {type_color}; font-size: 11px;")
        info_col.addWidget(type_label)

        layout.addLayout(info_col, 1)
        return widget

    def _open_skin_manager(self) -> None:
        from .skin_dialog import SkinManagerDialog
        acc = self._get_current_account()
        if not acc:
            return
        dialog = SkinManagerDialog(acc, self)
        dialog.skin_changed.connect(self._on_skin_changed)
        dialog.exec()

    def _on_skin_changed(self) -> None:
        self._avatar_cache.clear()
        self._refresh_list()
        selected = self._account_manager.get_selected()
        if selected:
            for i, acc in enumerate(self._accounts):
                if acc.uuid == selected.uuid:
                    self._account_list.setCurrentRow(i)
                    break
        self.accounts_changed.emit()
