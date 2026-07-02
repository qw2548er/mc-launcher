"""模组加载器安装对话框。

支持选择 Forge/Fabric/Quilt 加载器版本，显示安装进度和状态。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QProgressBar, QComboBox, QTabWidget, QListWidget, QListWidgetItem,
    QFrame, QSizePolicy, QMessageBox
)

from .widgets import DialogTitleBar, CardWidget, Toast

logger = logging.getLogger(__name__)


class LoadVersionsThread(QThread):
    versions_loaded = pyqtSignal(str, list)
    load_failed = pyqtSignal(str, str)

    def __init__(self, modloader_manager, mc_version: str, loader_type: str):
        super().__init__()
        self._manager = modloader_manager
        self._mc_version = mc_version
        self._loader_type = loader_type

    def run(self):
        try:
            if self._loader_type == "forge":
                versions = self._manager.forge.get_versions(self._mc_version)
            elif self._loader_type == "fabric":
                versions = self._manager.fabric.get_versions(self._mc_version)
            elif self._loader_type == "quilt":
                versions = self._manager.quilt.get_versions(self._mc_version)
            else:
                versions = []
            self.versions_loaded.emit(self._loader_type, versions)
        except Exception as e:
            logger.error("加载 %s 版本失败: %s", self._loader_type, e, exc_info=True)
            self.load_failed.emit(self._loader_type, str(e))


class InstallLoaderThread(QThread):
    progress_updated = pyqtSignal(float, str)
    install_finished = pyqtSignal(bool, str, str)

    def __init__(self, modloader_manager, mc_version: str, loader_type: str,
                 loader_version, game_dir: Path):
        super().__init__()
        self._manager = modloader_manager
        self._mc_version = mc_version
        self._loader_type = loader_type
        self._loader_version = loader_version
        self._game_dir = game_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            def on_progress(progress_info):
                if self._cancel:
                    return
                percent = progress_info.percent if hasattr(progress_info, 'percent') else 0
                message = progress_info.message if hasattr(progress_info, 'message') else ""
                self.progress_updated.emit(percent, message)

            if self._loader_type == "forge":
                result = self._manager.forge.install(
                    self._mc_version, self._loader_version,
                    progress_callback=on_progress
                )
            elif self._loader_type == "fabric":
                result = self._manager.fabric.install(
                    self._mc_version, self._loader_version,
                    progress_callback=on_progress
                )
            elif self._loader_type == "quilt":
                result = self._manager.quilt.install(
                    self._mc_version, self._loader_version,
                    progress_callback=on_progress
                )
            else:
                self.install_finished.emit(False, "", "不支持的加载器类型")
                return

            if result.success:
                version_id = result.new_version_id if hasattr(result, 'new_version_id') else ""
                self.install_finished.emit(True, version_id, result.message or "安装成功")
            else:
                self.install_finished.emit(False, "", result.message or "安装失败")
        except Exception as e:
            logger.error("安装 %s 失败: %s", self._loader_type, e, exc_info=True)
            self.install_finished.emit(False, "", str(e))


class ModLoaderInstallDialog(QDialog):
    install_completed = pyqtSignal(str, str, str)

    def __init__(self, mc_version: str, game_dir: Path, parent=None):
        super().__init__(parent)
        self._mc_version = mc_version
        self._game_dir = game_dir
        self._modloader_manager = None
        self._load_thread: Optional[LoadVersionsThread] = None
        self._install_thread: Optional[InstallLoaderThread] = None
        self._forge_versions: list = []
        self._fabric_versions: list = []
        self._quilt_versions: list = []
        self._selected_loader = "forge"
        self._is_installing = False

        self._setup_window()
        self._setup_ui()
        self._init_manager()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("安装模组加载器"))
        self.setMinimumSize(560, 480)
        self.resize(620, 540)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setModal(True)

    def _init_manager(self):
        try:
            from src.modloader import ModLoaderManager
            self._modloader_manager = ModLoaderManager(game_dir=self._game_dir)
            self._load_all_versions()
        except Exception as e:
            logger.error("初始化模组加载器管理器失败: %s", e, exc_info=True)
            Toast.error(f"初始化失败: {e}")

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        title_bar = DialogTitleBar(self, self.tr("安装模组加载器"))
        title_bar.close_clicked.connect(self.reject)
        root_layout.addWidget(title_bar)

        content = QWidget()
        content.setObjectName("DialogContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(16)

        info_card = CardWidget()
        il = info_card.content_layout
        il.setContentsMargins(20, 16, 20, 16)
        il.setSpacing(8)

        version_label = QLabel(f"Minecraft 版本: <b>{self._mc_version}</b>")
        version_label.setStyleSheet("font-size: 14px;")
        il.addWidget(version_label)

        hint_label = QLabel(self.tr("选择要安装的模组加载器和版本，点击安装按钮开始安装。"))
        hint_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        il.addWidget(hint_label)

        content_layout.addWidget(info_card)

        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("LoaderTabs")

        self._forge_list = QListWidget()
        self._fabric_list = QListWidget()
        self._quilt_list = QListWidget()

        self._tab_widget.addTab(self._forge_list, "Forge")
        self._tab_widget.addTab(self._fabric_list, "Fabric")
        self._tab_widget.addTab(self._quilt_list, "Quilt")
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        content_layout.addWidget(self._tab_widget, 1)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("")
        self._progress_bar.setFixedHeight(24)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 12px;
                background-color: #e0e0e0;
                text-align: center;
                font-size: 11px;
                color: #333333;
            }
            QProgressBar::chunk {
                border-radius: 12px;
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7C3AED, stop:1 #A855F7);
            }
        """)
        self._progress_bar.hide()
        content_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        btn_row.addStretch()

        self._cancel_btn = QPushButton(self.tr("取消"))
        self._cancel_btn.setObjectName("SecondaryButton")
        self._cancel_btn.setFixedSize(100, 36)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)

        self._install_btn = QPushButton(self.tr("安装"))
        self._install_btn.setObjectName("PrimaryButton")
        self._install_btn.setFixedSize(120, 36)
        self._install_btn.clicked.connect(self._on_install)
        self._install_btn.setEnabled(False)
        btn_row.addWidget(self._install_btn)

        content_layout.addLayout(btn_row)

        root_layout.addWidget(content, 1)

        self._set_loading_state(True)

    def _set_loading_state(self, loading: bool):
        if loading:
            self._status_label.setText(self.tr("正在加载可用版本..."))
            self._install_btn.setEnabled(False)
        else:
            self._status_label.setText(self.tr("请选择要安装的版本"))
            self._install_btn.setEnabled(True)

    def _load_all_versions(self):
        for loader_type in ["forge", "fabric", "quilt"]:
            thread = LoadVersionsThread(self._modloader_manager, self._mc_version, loader_type)
            thread.versions_loaded.connect(self._on_versions_loaded)
            thread.load_failed.connect(self._on_versions_load_failed)
            thread.start()
            if loader_type == "forge":
                self._forge_load_thread = thread
            elif loader_type == "fabric":
                self._fabric_load_thread = thread
            else:
                self._quilt_load_thread = thread

    def _on_versions_loaded(self, loader_type: str, versions: list):
        list_widget = None
        if loader_type == "forge":
            self._forge_versions = versions
            list_widget = self._forge_list
        elif loader_type == "fabric":
            self._fabric_versions = versions
            list_widget = self._fabric_list
        elif loader_type == "quilt":
            self._quilt_versions = versions
            list_widget = self._quilt_list

        if list_widget:
            list_widget.clear()
            for v in versions:
                item = QListWidgetItem()
                widget = self._create_version_item_widget(v, loader_type)
                item.setSizeHint(widget.sizeHint())
                list_widget.addItem(item)
                list_widget.setItemWidget(item, widget)

        if not self._is_installing:
            all_loaded = (self._forge_versions or self._forge_list.count() > 0 or
                         self._fabric_versions or self._quilt_versions)
            if all_loaded:
                self._set_loading_state(False)

    def _create_version_item_widget(self, version, loader_type: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        name_label = QLabel(version.version)
        name_font = name_label.font()
        name_font.setBold(True)
        name_label.setFont(name_font)
        layout.addWidget(name_label)

        layout.addStretch()

        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(6)

        if hasattr(version, 'is_recommended') and version.is_recommended:
            rec_tag = QLabel("推荐")
            rec_tag.setStyleSheet("""
                QLabel {
                    background-color: #10B981;
                    color: white;
                    padding: 2px 8px;
                    border-radius: 4px;
                    font-size: 9px;
                    font-weight: bold;
                }
            """)
            tags_layout.addWidget(rec_tag)

        if hasattr(version, 'is_latest') and version.is_latest:
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
            tags_layout.addWidget(latest_tag)

        if version.release_date:
            date_tag = QLabel(version.release_date[:10] if len(version.release_date) >= 10 else version.release_date)
            date_tag.setStyleSheet("color: #9CA3AF; font-size: 11px;")
            tags_layout.addWidget(date_tag)

        layout.addLayout(tags_layout)

        widget.mousePressEvent = lambda e, lw=layout.parent(), v=version: self._on_version_selected(v, loader_type)
        return widget

    def _on_versions_load_failed(self, loader_type: str, error: str):
        logger.warning("加载 %s 版本失败: %s", loader_type, error)
        tab_idx = {"forge": 0, "fabric": 1, "quilt": 2}.get(loader_type, 0)
        tab = self._tab_widget.widget(tab_idx)
        if tab:
            error_label = QLabel(self.tr(f"加载失败: {error}"))
            error_label.setStyleSheet("color: #EF4444; padding: 20px;")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout = QVBoxLayout(tab)
            layout.addWidget(error_label)

    def _on_tab_changed(self, index: int):
        loader_types = ["forge", "fabric", "quilt"]
        if 0 <= index < len(loader_types):
            self._selected_loader = loader_types[index]
        self._update_install_button()

    def _on_version_selected(self, version, loader_type: str):
        self._selected_version = version
        self._selected_loader = loader_type
        self._update_install_button()

    def _update_install_button(self):
        has_selection = hasattr(self, '_selected_version') and self._selected_version is not None
        self._install_btn.setEnabled(has_selection and not self._is_installing)

    def _on_install(self):
        if not hasattr(self, '_selected_version') or self._selected_version is None:
            Toast.warning(self.tr("请先选择一个版本"))
            return

        if self._is_installing:
            return

        reply = QMessageBox.question(
            self,
            self.tr("确认安装"),
            self.tr(f"确定要安装 {self._selected_loader.capitalize()} {self._selected_version.version} 吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._is_installing = True
        self._install_btn.setEnabled(False)
        self._cancel_btn.setText(self.tr("取消安装"))
        self._progress_bar.show()
        self._progress_bar.setValue(0)
        self._tab_widget.setEnabled(False)
        self._status_label.setText(self.tr("正在准备安装..."))

        self._install_thread = InstallLoaderThread(
            self._modloader_manager,
            self._mc_version,
            self._selected_loader,
            self._selected_version,
            self._game_dir
        )
        self._install_thread.progress_updated.connect(self._on_install_progress)
        self._install_thread.install_finished.connect(self._on_install_finished)
        self._install_thread.start()

    def _on_install_progress(self, progress: float, status: str):
        self._progress_bar.setValue(int(min(progress, 100)))
        if progress > 0:
            self._progress_bar.setFormat(f"{progress:.1f}%")
        self._status_label.setText(status)

    def _on_install_finished(self, success: bool, version_id: str, message: str):
        self._is_installing = False
        self._tab_widget.setEnabled(True)
        self._cancel_btn.setText(self.tr("关闭"))

        if success:
            self._progress_bar.setValue(100)
            self._status_label.setStyleSheet("color: #10B981; font-size: 12px;")
            self._status_label.setText(self.tr(f"安装成功！版本: {version_id}"))
            self._install_btn.setText(self.tr("完成"))
            self._install_btn.setEnabled(True)
            self._install_btn.clicked.disconnect()
            self._install_btn.clicked.connect(self.accept)
            Toast.success(self.tr(f"{self._selected_loader.capitalize()} 安装成功！"))
            self.install_completed.emit(self._mc_version, self._selected_loader, version_id)
        else:
            self._progress_bar.hide()
            self._status_label.setStyleSheet("color: #EF4444; font-size: 12px;")
            self._status_label.setText(self.tr(f"安装失败: {message}"))
            self._install_btn.setText(self.tr("重试"))
            self._install_btn.setEnabled(True)
            Toast.error(self.tr(f"安装失败: {message}"))

    def _on_cancel(self):
        if self._is_installing and self._install_thread:
            reply = QMessageBox.question(
                self,
                self.tr("取消安装"),
                self.tr("确定要取消安装吗？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._install_thread.cancel()
                self._is_installing = False
                self.reject()
        else:
            self.reject()
