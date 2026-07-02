"""皮肤管理对话框。

显示当前账号的皮肤预览，支持选择本地皮肤文件、刷新正版皮肤、清除自定义皮肤。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QGroupBox, QWidget, QMessageBox
)

from src.core.account import AccountInfo, AccountManager
from src.core.skin_manager import SkinModel, get_skin_manager
from src.ui.widgets.dialog_title_bar import DialogTitleBar
from src.ui.widgets.toast import Toast


class _PreviewLoaderThread(QThread):
    preview_ready = pyqtSignal(str)

    def __init__(self, uuid_str: str, skin_url: Optional[str], cape_url: Optional[str],
                 skin_model: str, size: int, parent=None):
        super().__init__(parent)
        self._uuid = uuid_str
        self._skin_url = skin_url
        self._cape_url = cape_url
        self._skin_model = skin_model
        self._size = size

    def run(self):
        try:
            mgr = get_skin_manager()
            path = mgr.get_preview(
                self._uuid,
                skin_url=self._skin_url,
                cape_url=self._cape_url,
                skin_model=self._skin_model,
                size=self._size,
            )
            if path:
                self.preview_ready.emit(str(path))
        except Exception:
            pass


class _RefreshSkinThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, uuid_str: str, parent=None):
        super().__init__(parent)
        self._uuid = uuid_str

    def run(self):
        try:
            mgr = get_skin_manager()
            textures = mgr.fetch_mojang_textures(self._uuid)
            if textures and textures.skin_url:
                mgr.clear_cache(self._uuid)
                mgr.download_skin(textures.skin_url, self._uuid)
                if textures.cape_url:
                    mgr.download_cape(textures.cape_url, self._uuid)
                try:
                    acc_mgr = AccountManager()
                    acc_mgr.update_microsoft_account(
                        self._uuid,
                        skin_url=textures.skin_url,
                        skin_variant=textures.skin_model,
                    )
                except Exception:
                    pass
                self.finished.emit(True, "皮肤已刷新")
            else:
                self.finished.emit(False, "未能获取皮肤信息")
        except Exception as e:
            self.finished.emit(False, f"刷新失败: {e}")


class SkinManagerDialog(QDialog):
    skin_changed = pyqtSignal()

    def __init__(self, account: Optional[AccountInfo] = None, parent=None):
        super().__init__(parent)
        self._account = account or AccountManager().get_selected()
        self._preview_path: Optional[Path] = None
        self._setup_ui()
        self._load_preview()

    def _setup_ui(self):
        self.setWindowTitle("皮肤管理")
        self.setFixedSize(420, 480)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setObjectName("SkinDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_bar = DialogTitleBar(self, "皮肤管理")
        title_bar.close_clicked.connect(self.close)
        layout.addWidget(title_bar)

        content = QWidget()
        content.setObjectName("DialogContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 24)
        content_layout.setSpacing(16)

        account_box = QGroupBox("当前账号")
        acc_layout = QHBoxLayout(account_box)
        acc_layout.setSpacing(12)

        if self._account:
            self._account_name_label = QLabel(self._account.username)
            self._account_name_label.setStyleSheet("font-size: 16px; font-weight: 600;")
            type_text = "正版账号" if self._account.is_microsoft else "离线账号"
            self._account_type_label = QLabel(type_text)
            self._account_type_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")

            info_layout = QVBoxLayout()
            info_layout.addWidget(self._account_name_label)
            info_layout.addWidget(self._account_type_label)
            acc_layout.addLayout(info_layout, 1)

        content_layout.addWidget(account_box)

        preview_box = QGroupBox("皮肤预览")
        prev_layout = QVBoxLayout(preview_box)
        prev_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._preview_label = QLabel()
        self._preview_label.setFixedSize(160, 256)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet(
            "background-color: #1F2937; border-radius: 8px; border: 1px solid #374151;"
        )
        self._preview_label.setText("加载中...")
        prev_layout.addWidget(self._preview_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._skin_info_label = QLabel("")
        self._skin_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._skin_info_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        prev_layout.addWidget(self._skin_info_label)

        content_layout.addWidget(preview_box)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._browse_btn = QPushButton("选择本地皮肤")
        self._browse_btn.setObjectName("SecondaryButton")
        self._browse_btn.clicked.connect(self._browse_skin_file)
        btn_layout.addWidget(self._browse_btn)

        self._refresh_btn = QPushButton("刷新皮肤")
        self._refresh_btn.clicked.connect(self._refresh_skin)
        self._refresh_btn.setEnabled(self._account is not None and self._account.is_microsoft)
        btn_layout.addWidget(self._refresh_btn)

        self._clear_btn = QPushButton("清除自定义")
        self._clear_btn.setObjectName("SecondaryButton")
        self._clear_btn.clicked.connect(self._clear_custom_skin)
        btn_layout.addWidget(self._clear_btn)

        content_layout.addLayout(btn_layout)

        if not self._account:
            warn = QLabel("未选择账号，请先添加账号")
            warn.setStyleSheet("color: #F59E0B; font-size: 12px;")
            content_layout.addWidget(warn)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(self.close)
        content_layout.addWidget(close_btn)

        layout.addWidget(content, 1)

    def _load_preview(self):
        if not self._account:
            self._preview_label.setText("未登录")
            return
        uuid_str = self._account.uuid
        skin_url = self._account.skin_url
        skin_model = self._account.skin_variant or SkinModel.CLASSIC
        mgr = get_skin_manager()

        custom_path = mgr.get_custom_skin_path(uuid_str)
        if custom_path:
            self._skin_info_label.setText("正在使用自定义皮肤")
        elif skin_url:
            model_text = "Alex (细胳膊)" if skin_model == SkinModel.SLIM else "Steve (经典)"
            self._skin_info_label.setText(f"皮肤模型: {model_text}")
        else:
            skin_type = mgr.get_default_skin_type(uuid_str)
            self._skin_info_label.setText(f"默认皮肤: {'Alex' if skin_type == 'alex' else 'Steve'}")

        self._loader = _PreviewLoaderThread(
            uuid_str, skin_url, None, skin_model, 256, self
        )
        self._loader.preview_ready.connect(self._on_preview_ready)
        self._loader.start()

    def _on_preview_ready(self, path_str: str):
        pm = QPixmap(path_str)
        if not pm.isNull():
            self._preview_label.setPixmap(pm)
            self._preview_label.setText("")
        else:
            self._preview_label.setText("预览失败")

    def _browse_skin_file(self):
        if not self._account:
            Toast.warning("请先选择账号")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择皮肤文件", "",
            "PNG 图片 (*.png);;所有文件 (*)"
        )
        if not file_path:
            return
        mgr = get_skin_manager()
        success = mgr.set_custom_skin(self._account.uuid, Path(file_path))
        if success:
            Toast.success("自定义皮肤已设置")
            self.skin_changed.emit()
            self._load_preview()
        else:
            Toast.error("设置皮肤失败，请确认是有效的PNG皮肤文件")

    def _refresh_skin(self):
        if not self._account or not self._account.is_microsoft:
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("刷新中...")

        self._refresh_thread = _RefreshSkinThread(self._account.uuid, self)
        self._refresh_thread.finished.connect(self._on_refresh_done)
        self._refresh_thread.start()

    def _on_refresh_done(self, success: bool, msg: str):
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("刷新皮肤")
        if success:
            Toast.success(msg)
            acc = AccountManager().get_by_uuid(self._account.uuid)
            if acc:
                self._account = acc
            self.skin_changed.emit()
            self._load_preview()
        else:
            Toast.error(msg)

    def _clear_custom_skin(self):
        if not self._account:
            return
        mgr = get_skin_manager()
        if mgr.clear_custom_skin(self._account.uuid):
            Toast.success("已清除自定义皮肤")
            self.skin_changed.emit()
            self._load_preview()
        else:
            Toast.info("当前没有使用自定义皮肤")
