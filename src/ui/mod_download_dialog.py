"""Modrinth 模组下载对话框。

提供从 Modrinth 搜索、查看详情和下载模组的功能。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPixmap, QFont, QImage
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QProgressBar, QFrame, QScrollArea,
    QGridLayout, QComboBox, QLineEdit, QMessageBox, QSplitter
)

from .widgets import DialogTitleBar, CardWidget, Toast

logger = logging.getLogger(__name__)


class SearchThread(QThread):
    search_finished = pyqtSignal(object)
    search_failed = pyqtSignal(str)

    def __init__(self, api, query: str, game_version: Optional[str], loader: Optional[str]):
        super().__init__()
        self._api = api
        self._query = query
        self._game_version = game_version
        self._loader = loader

    def run(self):
        try:
            result = self._api.search_mods(
                query=self._query,
                game_version=self._game_version,
                loader=self._loader,
                limit=20
            )
            self.search_finished.emit(result)
        except Exception as e:
            logger.error("搜索模组失败: %s", e, exc_info=True)
            self.search_failed.emit(str(e))


class DownloadModThread(QThread):
    progress_updated = pyqtSignal(float, str)
    download_finished = pyqtSignal(bool, str, str)

    def __init__(self, api, project, version, mods_dir: Path):
        super().__init__()
        self._api = api
        self._project = project
        self._version = version
        self._mods_dir = mods_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            def on_progress(progress: float, status: str):
                if self._cancel:
                    return
                self.progress_updated.emit(progress, status)

            result = self._api.download_mod_file(
                self._version,
                self._mods_dir,
                progress_callback=on_progress
            )
            if result:
                self.download_finished.emit(True, str(result), f"下载成功: {self._project.title}")
            else:
                self.download_finished.emit(False, "", "下载失败")
        except Exception as e:
            logger.error("下载模组失败: %s", e, exc_info=True)
            self.download_finished.emit(False, "", str(e))


class ModDownloadDialog(QDialog):
    mod_downloaded = pyqtSignal()

    def __init__(self, game_version: Optional[str], mods_dir: Path, parent=None):
        super().__init__(parent)
        self._game_version = game_version
        self._mods_dir = mods_dir
        self._api = None
        self._projects: list = []
        self._selected_project = None
        self._selected_version = None
        self._search_thread: Optional[SearchThread] = None
        self._download_thread: Optional[DownloadModThread] = None
        self._is_downloading = False

        self._setup_window()
        self._setup_ui()
        self._init_api()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("下载模组"))
        self.setMinimumSize(860, 600)
        self.resize(960, 680)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setModal(True)

    def _init_api(self):
        try:
            from src.modloader import ModrinthAPI
            self._api = ModrinthAPI()
            self._perform_search("")
        except Exception as e:
            logger.error("初始化 Modrinth API 失败: %s", e, exc_info=True)
            Toast.error(f"初始化失败: {e}")

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        title_bar = DialogTitleBar(self, self.tr("下载模组 - Modrinth"))
        title_bar.close_clicked.connect(self.reject)
        root_layout.addWidget(title_bar)

        content = QWidget()
        content.setObjectName("DialogContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.setSpacing(12)

        search_card = CardWidget()
        sl = search_card.content_layout
        sl.setContentsMargins(16, 12, 16, 12)
        sl.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(self.tr("搜索 Modrinth 模组..."))
        self._search_input.setFixedHeight(36)
        self._search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_input, 1)

        self._search_btn = QPushButton(self.tr("搜索"))
        self._search_btn.setObjectName("PrimaryButton")
        self._search_btn.setFixedSize(80, 36)
        self._search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self._search_btn)

        sl.addLayout(search_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        version_label = QLabel(self.tr("MC 版本:"))
        version_label.setStyleSheet("color: #6B7280; font-size: 12px;")
        filter_row.addWidget(version_label)

        self._version_combo = QComboBox()
        self._version_combo.setFixedHeight(28)
        self._version_combo.addItem(self.tr("全部版本"), "")
        if self._game_version:
            self._version_combo.addItem(self._game_version, self._game_version)
            self._version_combo.setCurrentIndex(1)
        filter_row.addWidget(self._version_combo)

        loader_label = QLabel(self.tr("加载器:"))
        loader_label.setStyleSheet("color: #6B7280; font-size: 12px;")
        filter_row.addWidget(loader_label)

        self._loader_combo = QComboBox()
        self._loader_combo.setFixedHeight(28)
        self._loader_combo.addItems([
            self.tr("全部"),
            "Forge",
            "Fabric",
            "Quilt",
        ])
        filter_row.addWidget(self._loader_combo)

        filter_row.addStretch()
        sl.addLayout(filter_row)

        content_layout.addWidget(search_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self._result_count_label = QLabel(self.tr("正在搜索..."))
        self._result_count_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        left_layout.addWidget(self._result_count_label)

        self._mod_list = QListWidget()
        self._mod_list.setObjectName("ModSearchList")
        self._mod_list.setSpacing(4)
        self._mod_list.currentItemChanged.connect(self._on_project_selected)
        left_layout.addWidget(self._mod_list)

        splitter.addWidget(left_panel)

        right_panel = QScrollArea()
        right_panel.setWidgetResizable(True)
        right_panel.setFrameShape(QFrame.Shape.NoFrame)

        self._detail_content = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_content)
        self._detail_layout.setContentsMargins(16, 0, 0, 0)
        self._detail_layout.setSpacing(12)

        self._empty_detail = QLabel(self.tr("选择一个模组查看详情"))
        self._empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_detail.setStyleSheet("color: #9CA3AF; font-size: 14px; padding: 40px;")
        self._detail_layout.addWidget(self._empty_detail)

        self._detail_widget = QWidget()
        self._detail_widget.hide()
        self._build_detail_ui()
        self._detail_layout.addWidget(self._detail_widget)
        self._detail_layout.addStretch()

        right_panel.setWidget(self._detail_content)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 420])

        content_layout.addWidget(splitter, 1)

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
                    stop:0 #10B981, stop:1 #34D399);
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

        self._close_btn = QPushButton(self.tr("关闭"))
        self._close_btn.setObjectName("SecondaryButton")
        self._close_btn.setFixedSize(100, 36)
        self._close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._close_btn)

        self._install_btn = QPushButton(self.tr("下载安装"))
        self._install_btn.setObjectName("PrimaryButton")
        self._install_btn.setFixedSize(120, 36)
        self._install_btn.clicked.connect(self._on_install)
        self._install_btn.setEnabled(False)
        btn_row.addWidget(self._install_btn)

        content_layout.addLayout(btn_row)

        root_layout.addWidget(content, 1)

    def _build_detail_ui(self):
        dw = self._detail_widget
        dl = QVBoxLayout(dw)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(12)

        header_card = CardWidget()
        hl = header_card.content_layout
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(64, 64)
        self._icon_label.setStyleSheet(
            "background-color: #F3F4F6; border-radius: 8px;"
        )
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setText("📦")
        header_row.addWidget(self._icon_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        self._title_label = QLabel("")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setWordWrap(True)
        title_col.addWidget(self._title_label)

        self._author_label = QLabel("")
        self._author_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        title_col.addWidget(self._author_label)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self._downloads_label = QLabel("")
        self._downloads_label.setStyleSheet("color: #6B7280; font-size: 11px;")
        stats_row.addWidget(self._downloads_label)

        self._follows_label = QLabel("")
        self._follows_label.setStyleSheet("color: #6B7280; font-size: 11px;")
        stats_row.addWidget(self._follows_label)

        stats_row.addStretch()
        title_col.addLayout(stats_row)

        header_row.addLayout(title_col, 1)
        hl.addLayout(header_row)

        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("color: #4B5563; font-size: 12px; line-height: 1.5;")
        hl.addWidget(self._desc_label)

        categories_row = QHBoxLayout()
        categories_row.setSpacing(6)
        self._categories_layout = categories_row
        categories_row.addStretch()
        hl.addLayout(categories_row)

        dl.addWidget(header_card)

        versions_card = CardWidget()
        vl = versions_card.content_layout
        vl.setContentsMargins(20, 16, 20, 16)
        vl.setSpacing(8)

        versions_title = QLabel(self.tr("可用版本"))
        versions_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        vl.addWidget(versions_title)

        self._version_list = QListWidget()
        self._version_list.setFixedHeight(150)
        self._version_list.currentItemChanged.connect(self._on_version_selected)
        vl.addWidget(self._version_list)

        dl.addWidget(versions_card)

    def _on_search(self):
        if self._api is None:
            return
        query = self._search_input.text().strip()
        self._perform_search(query)

    def _perform_search(self, query: str):
        if self._search_thread and self._search_thread.isRunning():
            return

        self._search_input.setEnabled(False)
        self._search_btn.setEnabled(False)
        self._result_count_label.setText(self.tr("正在搜索..."))
        self._mod_list.clear()

        game_version = self._version_combo.currentData() if hasattr(self, '_version_combo') else None
        loader_idx = self._loader_combo.currentIndex() if hasattr(self, '_loader_combo') else 0
        loader = None
        if loader_idx == 1:
            loader = "forge"
        elif loader_idx == 2:
            loader = "fabric"
        elif loader_idx == 3:
            loader = "quilt"

        self._search_thread = SearchThread(self._api, query, game_version, loader)
        self._search_thread.search_finished.connect(self._on_search_finished)
        self._search_thread.search_failed.connect(self._on_search_failed)
        self._search_thread.start()

    def _on_search_finished(self, result):
        self._search_input.setEnabled(True)
        self._search_btn.setEnabled(True)
        self._projects = result.projects

        total = result.total_hits
        shown = len(result.projects)
        self._result_count_label.setText(self.tr(f"找到 {total} 个结果 (显示前 {shown} 个)"))

        for project in result.projects:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 56))
            widget = self._create_project_item(project)
            self._mod_list.addItem(item)
            self._mod_list.setItemWidget(item, widget)
            item.setData(Qt.ItemDataRole.UserRole, project)

    def _on_search_failed(self, error: str):
        self._search_input.setEnabled(True)
        self._search_btn.setEnabled(True)
        self._result_count_label.setText(self.tr("搜索失败"))
        Toast.error(self.tr(f"搜索失败: {error}"))

    def _create_project_item(self, project) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setStyleSheet("background-color: #F3F4F6; border-radius: 6px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setText("📦")
        layout.addWidget(icon)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        name_label = QLabel(project.title)
        name_font = name_label.font()
        name_font.setBold(True)
        name_label.setFont(name_font)
        info_col.addWidget(name_label)

        desc_short = project.description[:60] + "..." if len(project.description) > 60 else project.description
        desc_label = QLabel(desc_short)
        desc_label.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        info_col.addWidget(desc_label)

        layout.addLayout(info_col, 1)

        downloads_label = QLabel(f"⬇ {project.downloads:,}")
        downloads_label.setStyleSheet("color: #9CA3AF; font-size: 10px;")
        layout.addWidget(downloads_label)

        return widget

    def _on_project_selected(self, current, previous):
        if current is None or self._api is None:
            self._selected_project = None
            self._empty_detail.show()
            self._detail_widget.hide()
            self._install_btn.setEnabled(False)
            return

        project = current.data(Qt.ItemDataRole.UserRole)
        self._selected_project = project
        self._show_project_detail(project)
        self._load_project_versions(project)

    def _show_project_detail(self, project):
        self._empty_detail.hide()
        self._detail_widget.show()

        self._title_label.setText(project.title)
        self._author_label.setText(self.tr(f"作者: {project.author}"))
        self._desc_label.setText(project.description or self.tr("暂无描述"))

        downloads = project.downloads
        if downloads >= 1000000:
            dl_text = f"⬇ {downloads / 1000000:.1f}M"
        elif downloads >= 1000:
            dl_text = f"⬇ {downloads / 1000:.1f}K"
        else:
            dl_text = f"⬇ {downloads}"
        self._downloads_label.setText(dl_text)

        follows = project.follows
        if follows >= 1000:
            fl_text = f"❤ {follows / 1000:.1f}K"
        else:
            fl_text = f"❤ {follows}"
        self._follows_label.setText(fl_text)

        while self._categories_layout.count() > 1:
            item = self._categories_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for cat in project.categories[:6]:
            if cat in ("forge", "fabric", "quilt", "mod"):
                continue
            cat_label = QLabel(cat)
            cat_label.setStyleSheet("""
                background-color: #E5E7EB; color: #374151;
                padding: 2px 8px; border-radius: 4px;
                font-size: 10px;
            """)
            self._categories_layout.insertWidget(self._categories_layout.count() - 1, cat_label)

        self._icon_label.setText("📦")

    def _load_project_versions(self, project):
        self._version_list.clear()
        self._selected_version = None
        self._install_btn.setEnabled(False)
        self._version_list.addItem(self.tr("加载版本中..."))

        try:
            versions = self._api.get_project_versions(project.project_id)
            self._version_list.clear()

            game_version = self._version_combo.currentData() if hasattr(self, '_version_combo') else None
            loader_idx = self._loader_combo.currentIndex() if hasattr(self, '_loader_combo') else 0
            loader_filter = None
            if loader_idx == 1:
                loader_filter = "forge"
            elif loader_idx == 2:
                loader_filter = "fabric"
            elif loader_idx == 3:
                loader_filter = "quilt"

            filtered = []
            for v in versions:
                if game_version and game_version not in v.game_versions:
                    continue
                if loader_filter and loader_filter not in [l.lower() for l in v.loaders]:
                    continue
                filtered.append(v)

            if not filtered:
                self._version_list.addItem(self.tr("没有找到匹配的版本"))
                return

            for v in filtered[:15]:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, v)
                loaders = ", ".join(v.loaders)
                gv = ", ".join(v.game_versions[:3])
                if len(v.game_versions) > 3:
                    gv += "..."
                text = f"{v.version_number} | {loaders} | {gv}"
                item.setText(text)
                self._version_list.addItem(item)

        except Exception as e:
            logger.error("加载版本列表失败: %s", e, exc_info=True)
            self._version_list.clear()
            self._version_list.addItem(self.tr(f"加载失败: {e}"))

    def _on_version_selected(self, current, previous):
        if current is None:
            self._selected_version = None
            self._install_btn.setEnabled(False)
            return

        version = current.data(Qt.ItemDataRole.UserRole)
        if version is None:
            self._selected_version = None
            self._install_btn.setEnabled(False)
            return

        self._selected_version = version
        self._install_btn.setEnabled(self._selected_project is not None and not self._is_downloading)

    def _on_install(self):
        if not self._selected_project or not self._selected_version:
            Toast.warning(self.tr("请先选择模组和版本"))
            return

        if self._is_downloading:
            return

        reply = QMessageBox.question(
            self,
            self.tr("确认下载"),
            self.tr(f"确定要下载 {self._selected_project.title} v{self._selected_version.version_number} 吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._is_downloading = True
        self._install_btn.setEnabled(False)
        self._close_btn.setEnabled(False)
        self._progress_bar.show()
        self._progress_bar.setValue(0)
        self._status_label.setText(self.tr("准备下载..."))

        self._download_thread = DownloadModThread(
            self._api,
            self._selected_project,
            self._selected_version,
            self._mods_dir
        )
        self._download_thread.progress_updated.connect(self._on_download_progress)
        self._download_thread.download_finished.connect(self._on_download_finished)
        self._download_thread.start()

    def _on_download_progress(self, progress: float, status: str):
        self._progress_bar.setValue(int(min(progress, 100)))
        if progress > 0:
            self._progress_bar.setFormat(f"{progress:.1f}%")
        self._status_label.setText(status)

    def _on_download_finished(self, success: bool, file_path: str, message: str):
        self._is_downloading = False
        self._close_btn.setEnabled(True)
        self._install_btn.setEnabled(True)

        if success:
            self._progress_bar.setValue(100)
            self._status_label.setStyleSheet("color: #10B981; font-size: 12px;")
            self._status_label.setText(self.tr(message))
            Toast.success(self.tr(message))
            self.mod_downloaded.emit()
            QTimer.singleShot(1500, self.accept)
        else:
            self._progress_bar.hide()
            self._status_label.setStyleSheet("color: #EF4444; font-size: 12px;")
            self._status_label.setText(self.tr(f"下载失败: {message}"))
            Toast.error(self.tr(message))
