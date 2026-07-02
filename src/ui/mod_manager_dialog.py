"""模组管理对话框。

提供模组浏览、启用/禁用、删除、冲突检测功能。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QProgressBar, QFrame, QScrollArea,
    QGridLayout, QSplitter, QMessageBox, QComboBox, QLineEdit
)

from .widgets import DialogTitleBar, CardWidget, Toast

logger = logging.getLogger(__name__)


class ScanModsThread(QThread):
    scan_finished = pyqtSignal(list, list)
    scan_failed = pyqtSignal(str)

    def __init__(self, mod_manager):
        super().__init__()
        self._mod_manager = mod_manager

    def run(self):
        try:
            mods = self._mod_manager.scan_mods()
            conflicts = self._mod_manager.detect_conflicts() if mods else []
            self.scan_finished.emit(mods, conflicts)
        except Exception as e:
            logger.error("扫描模组失败: %s", e, exc_info=True)
            self.scan_failed.emit(str(e))


class ModManagerDialog(QDialog):
    mods_changed = pyqtSignal()

    def __init__(self, mods_dir: Path, parent=None):
        super().__init__(parent)
        self._mods_dir = mods_dir
        self._mod_manager = None
        self._mods: list = []
        self._conflicts: list = []
        self._selected_mod = None
        self._scan_thread: Optional[ScanModsThread] = None

        self._setup_window()
        self._setup_ui()
        self._init_manager()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.tr("模组管理"))
        self.setMinimumSize(860, 600)
        self.resize(960, 680)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setModal(True)

    def _init_manager(self):
        try:
            from src.modloader import ModManager
            self._mod_manager = ModManager(mods_dir=self._mods_dir)
            self._refresh_mods()
        except Exception as e:
            logger.error("初始化模组管理器失败: %s", e, exc_info=True)
            Toast.error(f"初始化失败: {e}")

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        title_bar = DialogTitleBar(self, self.tr("模组管理"))
        title_bar.close_clicked.connect(self.reject)
        root_layout.addWidget(title_bar)

        content = QWidget()
        content.setObjectName("DialogContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.setSpacing(12)

        toolbar_card = CardWidget()
        tl = toolbar_card.content_layout
        tl.setContentsMargins(16, 12, 16, 12)
        tl.setSpacing(12)

        toolbar_row = QHBoxLayout()
        toolbar_row.setSpacing(10)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(self.tr("搜索模组..."))
        self._search_input.setFixedHeight(32)
        self._search_input.textChanged.connect(self._apply_filter)
        toolbar_row.addWidget(self._search_input, 1)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems([
            self.tr("全部模组"),
            self.tr("已启用"),
            self.tr("已禁用"),
            self.tr("Forge"),
            self.tr("Fabric"),
            self.tr("Quilt"),
        ])
        self._filter_combo.setFixedHeight(32)
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar_row.addWidget(self._filter_combo)

        self._refresh_btn = QPushButton(self.tr("刷新"))
        self._refresh_btn.setObjectName("SecondaryButton")
        self._refresh_btn.setFixedSize(80, 32)
        self._refresh_btn.clicked.connect(self._refresh_mods)
        toolbar_row.addWidget(self._refresh_btn)

        self._download_btn = QPushButton(self.tr("下载模组"))
        self._download_btn.setObjectName("PrimaryButton")
        self._download_btn.setFixedSize(100, 32)
        self._download_btn.clicked.connect(self._open_download_dialog)
        toolbar_row.addWidget(self._download_btn)

        self._add_btn = QPushButton(self.tr("添加模组"))
        self._add_btn.setObjectName("SecondaryButton")
        self._add_btn.setFixedSize(90, 32)
        self._add_btn.clicked.connect(self._add_mod_file)
        toolbar_row.addWidget(self._add_btn)

        tl.addLayout(toolbar_row)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)

        self._total_label = QLabel(self.tr("总计: 0"))
        self._total_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        stats_row.addWidget(self._total_label)

        self._enabled_label = QLabel(self.tr("已启用: 0"))
        self._enabled_label.setStyleSheet("color: #10B981; font-size: 12px;")
        stats_row.addWidget(self._enabled_label)

        self._disabled_label = QLabel(self.tr("已禁用: 0"))
        self._disabled_label.setStyleSheet("color: #F59E0B; font-size: 12px;")
        stats_row.addWidget(self._disabled_label)

        if self._conflicts:
            self._conflict_label = QLabel(self.tr(f"冲突: {len(self._conflicts)}"))
            self._conflict_label.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: bold;")
            stats_row.addWidget(self._conflict_label)

        stats_row.addStretch()
        tl.addLayout(stats_row)

        content_layout.addWidget(toolbar_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self._mod_list = QListWidget()
        self._mod_list.setObjectName("ModList")
        self._mod_list.setSpacing(4)
        self._mod_list.currentItemChanged.connect(self._on_mod_selected)
        left_layout.addWidget(self._mod_list)

        splitter.addWidget(left_panel)

        right_panel = QScrollArea()
        right_panel.setWidgetResizable(True)
        right_panel.setFrameShape(QFrame.Shape.NoFrame)

        self._detail_content = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_content)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
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
        splitter.setSizes([400, 400])

        content_layout.addWidget(splitter, 1)

        root_layout.addWidget(content, 1)

    def _build_detail_ui(self):
        dw = self._detail_widget
        dl = QVBoxLayout(dw)
        dl.setContentsMargins(16, 0, 0, 0)
        dl.setSpacing(16)

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

        self._mod_name_label = QLabel("")
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setBold(True)
        self._mod_name_label.setFont(name_font)
        title_col.addWidget(self._mod_name_label)

        self._mod_id_label = QLabel("")
        self._mod_id_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        title_col.addWidget(self._mod_id_label)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)

        self._mod_version_label = QLabel("")
        self._mod_version_label.setStyleSheet("""
            background-color: #E0E7FF; color: #4338CA;
            padding: 2px 8px; border-radius: 4px;
            font-size: 11px; font-weight: bold;
        """)
        meta_row.addWidget(self._mod_version_label)

        self._mod_loader_label = QLabel("")
        meta_row.addWidget(self._mod_loader_label)

        self._mod_state_label = QLabel("")
        meta_row.addWidget(self._mod_state_label)

        meta_row.addStretch()
        title_col.addLayout(meta_row)

        header_row.addLayout(title_col, 1)
        hl.addLayout(header_row)

        dl.addWidget(header_card)

        action_card = CardWidget()
        al = action_card.content_layout
        al.setContentsMargins(20, 16, 20, 16)
        al.setSpacing(12)

        action_title = QLabel(self.tr("操作"))
        action_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        al.addWidget(action_title)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._toggle_btn = QPushButton(self.tr("禁用"))
        self._toggle_btn.setObjectName("SecondaryButton")
        self._toggle_btn.setFixedHeight(36)
        self._toggle_btn.clicked.connect(self._toggle_selected_mod)
        action_row.addWidget(self._toggle_btn)

        self._delete_btn = QPushButton(self.tr("删除"))
        self._delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
        """)
        self._delete_btn.setFixedHeight(36)
        self._delete_btn.clicked.connect(self._delete_selected_mod)
        action_row.addWidget(self._delete_btn)

        action_row.addStretch()
        al.addLayout(action_row)

        dl.addWidget(action_card)

        info_card = CardWidget()
        il = info_card.content_layout
        il.setContentsMargins(20, 16, 20, 16)
        il.setSpacing(12)

        info_title = QLabel(self.tr("模组信息"))
        info_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        il.addWidget(info_title)

        info_grid = QGridLayout()
        info_grid.setSpacing(12)
        info_grid.setColumnStretch(1, 1)

        row = 0
        self._author_label = self._add_info_row(info_grid, row, self.tr("作者")); row += 1
        self._size_label = self._add_info_row(info_grid, row, self.tr("大小")); row += 1
        self._file_label = self._add_info_row(info_grid, row, self.tr("文件")); row += 1
        self._game_versions_label = self._add_info_row(info_grid, row, self.tr("支持版本")); row += 1

        il.addLayout(info_grid)

        desc_title = QLabel(self.tr("描述"))
        desc_title.setStyleSheet("font-size: 13px; font-weight: 600; margin-top: 8px;")
        il.addWidget(desc_title)

        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("color: #4B5563; font-size: 12px; line-height: 1.5;")
        il.addWidget(self._desc_label)

        dl.addWidget(info_card)

    def _add_info_row(self, grid: QGridLayout, row: int, label_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        grid.addWidget(label, row, 0)

        value = QLabel("")
        value.setStyleSheet("font-size: 12px;")
        value.setWordWrap(True)
        grid.addWidget(value, row, 1)

        return value

    def _refresh_mods(self):
        if self._mod_manager is None:
            return

        self._mod_list.clear()
        self._empty_detail.show()
        self._detail_widget.hide()
        self._search_input.setEnabled(False)
        self._filter_combo.setEnabled(False)
        self._refresh_btn.setEnabled(False)

        self._scan_thread = ScanModsThread(self._mod_manager)
        self._scan_thread.scan_finished.connect(self._on_scan_finished)
        self._scan_thread.scan_failed.connect(self._on_scan_failed)
        self._scan_thread.start()

    def _on_scan_finished(self, mods: list, conflicts: list):
        self._mods = mods
        self._conflicts = conflicts
        self._search_input.setEnabled(True)
        self._filter_combo.setEnabled(True)
        self._refresh_btn.setEnabled(True)

        enabled_count = sum(1 for m in mods if m.is_enabled)
        disabled_count = sum(1 for m in mods if m.is_disabled)

        self._total_label.setText(self.tr(f"总计: {len(mods)}"))
        self._enabled_label.setText(self.tr(f"已启用: {enabled_count}"))
        self._disabled_label.setText(self.tr(f"已禁用: {disabled_count}"))

        self._apply_filter()
        self.mods_changed.emit()

    def _on_scan_failed(self, error: str):
        self._search_input.setEnabled(True)
        self._filter_combo.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        Toast.error(self.tr(f"扫描模组失败: {error}"))

    def _apply_filter(self):
        self._mod_list.clear()

        search_text = self._search_input.text().lower() if hasattr(self, '_search_input') else ""
        filter_idx = self._filter_combo.currentIndex() if hasattr(self, '_filter_combo') else 0

        for mod in self._mods:
            if search_text:
                name_match = search_text in mod.name.lower() if mod.name else False
                id_match = search_text in mod.mod_id.lower() if mod.mod_id else False
                if not (name_match or id_match):
                    continue

            if filter_idx == 1 and not mod.is_enabled:
                continue
            elif filter_idx == 2 and not mod.is_disabled:
                continue
            elif filter_idx == 3 and mod.loader_type.value != "forge":
                continue
            elif filter_idx == 4 and mod.loader_type.value != "fabric":
                continue
            elif filter_idx == 5 and mod.loader_type.value != "quilt":
                continue

            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 56))
            widget = self._create_mod_list_item(mod)
            self._mod_list.addItem(item)
            self._mod_list.setItemWidget(item, widget)
            item.setData(Qt.ItemDataRole.UserRole, mod)

    def _create_mod_list_item(self, mod) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setStyleSheet("background-color: #F3F4F6; border-radius: 6px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if mod.icon_path and Path(mod.icon_path).exists():
            pm = QPixmap(mod.icon_path)
            if not pm.isNull():
                scaled = pm.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                icon.setPixmap(scaled)
                icon.setText("")
            else:
                icon.setText("📦")
        else:
            icon.setText("📦")
        layout.addWidget(icon)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)

        name_label = QLabel(mod.name or mod.filename)
        name_font = name_label.font()
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_row.addWidget(name_label)

        state_color = "#10B981" if mod.is_enabled else "#F59E0B"
        state_text = "●" if mod.is_enabled else "○"
        state_label = QLabel(state_text)
        state_label.setStyleSheet(f"color: {state_color}; font-size: 10px;")
        name_row.addWidget(state_label)
        name_row.addStretch()

        info_col.addLayout(name_row)

        meta_parts = []
        if mod.version:
            meta_parts.append(mod.version)
        if mod.author:
            meta_parts.append(mod.author)
        meta_label = QLabel(" · ".join(meta_parts) if meta_parts else mod.filename)
        meta_label.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        info_col.addWidget(meta_label)

        layout.addLayout(info_col, 1)

        return widget

    def _on_mod_selected(self, current, previous):
        if current is None:
            self._selected_mod = None
            self._empty_detail.show()
            self._detail_widget.hide()
            return

        mod = current.data(Qt.ItemDataRole.UserRole)
        self._selected_mod = mod
        self._show_mod_detail(mod)

    def _show_mod_detail(self, mod):
        self._empty_detail.hide()
        self._detail_widget.show()

        display_name = mod.name or mod.filename
        self._mod_name_label.setText(display_name)
        self._mod_id_label.setText(mod.mod_id or "")
        self._mod_version_label.setText(mod.version or self.tr("未知版本"))

        loader_colors = {
            "forge": ("#F16436", "Forge"),
            "fabric": ("#9B7CC7", "Fabric"),
            "quilt": ("#9966CC", "Quilt"),
            "unknown": ("#6B7280", "Unknown"),
        }
        loader_color, loader_text = loader_colors.get(
            mod.loader_type.value, ("#6B7280", mod.loader_type.value)
        )
        self._mod_loader_label.setText(loader_text)
        self._mod_loader_label.setStyleSheet(f"""
            background-color: {loader_color}20; color: {loader_color};
            padding: 2px 8px; border-radius: 4px;
            font-size: 11px; font-weight: bold;
        """)

        if mod.is_enabled:
            self._mod_state_label.setText(self.tr("已启用"))
            self._mod_state_label.setStyleSheet("""
                background-color: #D1FAE5; color: #065F46;
                padding: 2px 8px; border-radius: 4px;
                font-size: 11px; font-weight: bold;
            """)
            self._toggle_btn.setText(self.tr("禁用"))
        else:
            self._mod_state_label.setText(self.tr("已禁用"))
            self._mod_state_label.setStyleSheet("""
                background-color: #FEF3C7; color: #92400E;
                padding: 2px 8px; border-radius: 4px;
                font-size: 11px; font-weight: bold;
            """)
            self._toggle_btn.setText(self.tr("启用"))

        if mod.icon_path and Path(mod.icon_path).exists():
            pm = QPixmap(mod.icon_path)
            if not pm.isNull():
                scaled = pm.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                self._icon_label.setPixmap(scaled)
                self._icon_label.setText("")
            else:
                self._icon_label.setText("📦")
        else:
            self._icon_label.setText("📦")

        self._author_label.setText(mod.author or self.tr("未知"))

        size_text = f"{mod.file_size / 1024 / 1024:.2f} MB" if mod.file_size else self.tr("未知")
        self._size_label.setText(size_text)
        self._file_label.setText(mod.filename)

        versions_text = ", ".join(mod.game_versions) if mod.game_versions else self.tr("未知")
        self._game_versions_label.setText(versions_text)
        self._desc_label.setText(mod.description or self.tr("暂无描述"))

    def _toggle_selected_mod(self):
        if not self._selected_mod or not self._mod_manager:
            return

        mod = self._selected_mod
        try:
            if mod.is_enabled:
                self._mod_manager.disable_mod(mod)
                Toast.success(self.tr(f"已禁用: {mod.name or mod.filename}"))
            else:
                self._mod_manager.enable_mod(mod)
                Toast.success(self.tr(f"已启用: {mod.name or mod.filename}"))
            self._refresh_mods()
        except Exception as e:
            logger.error("切换模组状态失败: %s", e, exc_info=True)
            Toast.error(self.tr(f"操作失败: {e}"))

    def _delete_selected_mod(self):
        if not self._selected_mod or not self._mod_manager:
            return

        mod = self._selected_mod
        display_name = mod.name or mod.filename

        reply = QMessageBox.warning(
            self,
            self.tr("删除模组"),
            self.tr(f"确定要删除模组 '{display_name}' 吗？\n此操作不可恢复。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._mod_manager.delete_mod(mod)
            Toast.success(self.tr(f"已删除: {display_name}"))
            self._selected_mod = None
            self._refresh_mods()
        except Exception as e:
            logger.error("删除模组失败: %s", e, exc_info=True)
            Toast.error(self.tr(f"删除失败: {e}"))

    def _add_mod_file(self):
        from PyQt6.QtWidgets import QFileDialog
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("选择模组文件"),
            "",
            self.tr("模组文件 (*.jar *.zip);;所有文件 (*.*)")
        )
        if not files:
            return

        if not self._mod_manager:
            return

        import shutil
        added = 0
        for f in files:
            try:
                src = Path(f)
                dst = self._mods_dir / src.name
                if dst.exists():
                    base = dst.stem
                    suffix = dst.suffix
                    counter = 1
                    while dst.exists():
                        dst = self._mods_dir / f"{base}_{counter}{suffix}"
                        counter += 1
                shutil.copy2(src, dst)
                added += 1
            except Exception as e:
                logger.error("添加模组文件失败 %s: %s", f, e)

        if added > 0:
            Toast.success(self.tr(f"已添加 {added} 个模组"))
            self._refresh_mods()

    def _open_download_dialog(self):
        try:
            from .mod_download_dialog import ModDownloadDialog
            dialog = ModDownloadDialog(
                game_version=None,
                mods_dir=self._mods_dir,
                parent=self
            )
            dialog.mod_downloaded.connect(self._on_mod_downloaded)
            dialog.exec()
        except Exception as e:
            logger.error("打开模组下载对话框失败: %s", e, exc_info=True)
            Toast.error(self.tr(f"无法打开下载对话框: {e}"))

    def _on_mod_downloaded(self):
        self._refresh_mods()
