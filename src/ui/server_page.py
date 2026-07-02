"""多人游戏服务器页面。

提供服务器列表展示、状态刷新、添加/编辑/删除服务器、一键加入等功能。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, QSize, pyqtSignal, QThread, QTimer, QObject,
)
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFrame, QMessageBox, QMenu,
)

from src.core.server_manager import ServerManager, ServerInfo, get_server_manager
from src.core.server_ping import ServerStatus, DEFAULT_PORT
from src.utils.logger import get_logger
from .widgets import CardWidget, Toast

logger = get_logger(__name__)


def ping_color(ms: int) -> str:
    if ms < 0:
        return "#6B7280"
    if ms < 100:
        return "#10B981"
    if ms < 200:
        return "#3B82F6"
    if ms < 300:
        return "#F59E0B"
    return "#EF4444"


def ping_bars(ms: int) -> str:
    if ms < 0:
        return "✕"
    if ms < 100:
        return "▮▮▮▮▮"
    if ms < 150:
        return "▮▮▮▮▯"
    if ms < 250:
        return "▮▮▮▯▯"
    if ms < 400:
        return "▮▮▯▯▯"
    if ms < 600:
        return "▮▯▯▯▯"
    return "▯▯▯▯▯"


class ServerListItem(QFrame):
    """服务器列表项 Widget。"""

    join_clicked = pyqtSignal(str, int)
    edit_clicked = pyqtSignal(str, int)
    delete_clicked = pyqtSignal(str, int)

    def __init__(self, info: ServerInfo, status: ServerStatus, parent=None):
        super().__init__(parent)
        self._info = info
        self._status = status
        self.setFixedHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("ServerListItem")
        self._selected = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(56, 56)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet(
            "background-color: #1F2937; border-radius: 6px;"
        )
        self._update_icon()
        layout.addWidget(self._icon_label)

        center_col = QVBoxLayout()
        center_col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self._name_label = QLabel(self._info.name)
        self._name_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #F3F4F6;")
        name_row.addWidget(self._name_label)
        name_row.addStretch()

        self._players_label = QLabel(self._status.players_text)
        self._players_label.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        name_row.addWidget(self._players_label)
        center_col.addLayout(name_row)

        self._motd_label = QLabel()
        self._motd_label.setWordWrap(False)
        self._motd_label.setStyleSheet("font-size: 12px; color: #D1D5DB;")
        self._motd_label.setMaximumHeight(32)
        self._update_motd()
        center_col.addWidget(self._motd_label)

        addr_text = f"{self._info.address}:{self._info.port}"
        if self._status.version_name:
            addr_text += f"  ·  {self._status.version_name}"
        self._addr_label = QLabel(addr_text)
        self._addr_label.setStyleSheet("font-size: 11px; color: #6B7280;")
        center_col.addWidget(self._addr_label)

        layout.addLayout(center_col, 1)

        ping_col = QVBoxLayout()
        ping_col.setSpacing(2)
        ping_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ping_bars = QLabel(ping_bars(self._status.latency_ms))
        self._ping_bars.setStyleSheet(
            f"font-size: 16px; color: {ping_color(self._status.latency_ms)};"
        )
        self._ping_bars.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ping_col.addWidget(self._ping_bars)

        ms_text = "???" if self._status.latency_ms < 0 else f"{self._status.latency_ms}ms"
        self._ping_ms = QLabel(ms_text)
        self._ping_ms.setStyleSheet("font-size: 10px; color: #6B7280;")
        self._ping_ms.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ping_col.addWidget(self._ping_ms)
        layout.addLayout(ping_col)

    def _update_icon(self):
        pm = None
        if self._status.favicon_path and Path(self._status.favicon_path).exists():
            pm = QPixmap(str(self._status.favicon_path))
        elif self._info.icon_path and Path(self._info.icon_path).exists():
            pm = QPixmap(self._info.icon_path)
        if pm and not pm.isNull():
            scaled = pm.scaled(
                56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._icon_label.setPixmap(scaled)
            self._icon_label.setText("")
        else:
            default_pm = QPixmap(56, 56)
            default_pm.fill(QColor("#374151"))
            painter = QPainter(default_pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#6B7280"))
            painter.setFont(QFont("", 18))
            painter.drawText(default_pm.rect(), Qt.AlignmentFlag.AlignCenter, "🖥")
            painter.end()
            self._icon_label.setPixmap(default_pm)

    def _update_motd(self):
        if not self._status.online:
            txt = self._status.error or self.tr("无法连接")
            self._motd_label.setText(f'<span style="color:#EF4444">{txt}</span>')
            return
        html = self._status.motd_html
        if not html:
            txt = self._status.motd_text or ""
            self._motd_label.setText(txt)
            return
        html = html.replace("\n", " ")
        self._motd_label.setText(html)

    def update_status(self, status: ServerStatus):
        self._status = status
        self._players_label.setText(status.players_text)
        color = ping_color(status.latency_ms)
        self._ping_bars.setText(ping_bars(status.latency_ms))
        self._ping_bars.setStyleSheet(f"font-size: 16px; color: {color};")
        ms_text = "???" if status.latency_ms < 0 else f"{status.latency_ms}ms"
        self._ping_ms.setText(ms_text)
        self._update_motd()
        self._update_icon()

    def set_selected(self, selected: bool):
        self._selected = selected
        self.setProperty("selected", selected)
        self.setStyle(self.style())

    def mouseDoubleClickEvent(self, event):
        self.join_clicked.emit(self._info.address, self._info.port)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        join_action = menu.addAction(self.tr("加入服务器"))
        menu.addSeparator()
        edit_action = menu.addAction(self.tr("编辑"))
        delete_action = menu.addAction(self.tr("删除"))
        action = menu.exec(event.globalPos())
        if action == join_action:
            self.join_clicked.emit(self._info.address, self._info.port)
        elif action == edit_action:
            self.edit_clicked.emit(self._info.address, self._info.port)
        elif action == delete_action:
            self.delete_clicked.emit(self._info.address, self._info.port)


class _StatusUpdateSignal(QObject):
    status_updated = pyqtSignal(str, object)


class ServerPage(QWidget):
    """多人游戏服务器页面。"""

    join_server_requested = pyqtSignal(str, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mgr = get_server_manager()
        self._items: dict[str, tuple[QListWidgetItem, ServerListItem]] = {}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(30000)
        self._refresh_timer.timeout.connect(self._refresh_all)
        self._selected_server: Optional[tuple[str, int]] = None
        self._signal = _StatusUpdateSignal()
        self._signal.status_updated.connect(self._apply_status_update)
        self._setup_ui()
        self._connect_signals()
        self._mgr.set_status_callback(self._on_status_callback)
        self._load_servers()
        QTimer.singleShot(500, self._refresh_all)
        self._refresh_timer.start()

    def _setup_ui(self):
        self.setObjectName("ServerPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 20)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_label = QLabel(self.tr("多人游戏"))
        title_label.setStyleSheet("font-size: 24px; font-weight: 800;")
        title_col.addWidget(title_label)
        sub_label = QLabel(self.tr("选择一个服务器加入，或添加你喜欢的服务器。"))
        sub_label.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        title_col.addWidget(sub_label)
        header_row.addLayout(title_col, 1)

        self._refresh_btn = QPushButton("↻  " + self.tr("刷新"))
        self._refresh_btn.setObjectName("SecondaryButton")
        self._refresh_btn.setFixedHeight(36)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_row.addWidget(self._refresh_btn)

        self._add_btn = QPushButton("+  " + self.tr("添加服务器"))
        self._add_btn.setObjectName("PrimaryButton")
        self._add_btn.setFixedHeight(36)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_row.addWidget(self._add_btn)

        layout.addLayout(header_row)

        list_card = CardWidget()
        list_layout = list_card.content_layout
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        list_header = QWidget()
        list_header.setFixedHeight(40)
        list_header.setStyleSheet(
            "background-color: rgba(55, 65, 81, 0.3); border-bottom: 1px solid #374151;"
        )
        lh_layout = QHBoxLayout(list_header)
        lh_layout.setContentsMargins(20, 0, 20, 0)
        lh_label = QLabel(self.tr("服务器列表"))
        lh_label.setStyleSheet("color: #9CA3AF; font-size: 12px; font-weight: 600;")
        lh_layout.addWidget(lh_label)
        lh_layout.addStretch()
        self._count_label = QLabel()
        self._count_label.setStyleSheet("color: #6B7280; font-size: 12px;")
        lh_layout.addWidget(self._count_label)
        list_layout.addWidget(list_header)

        self._server_list = QListWidget()
        self._server_list.setObjectName("ServerListWidget")
        self._server_list.setFrameShape(QFrame.Shape.NoFrame)
        self._server_list.setSpacing(2)
        self._server_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._server_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._server_list.setStyleSheet("""
            QListWidget#ServerListWidget {
                background: transparent;
                border: none;
                padding: 4px;
            }
            QListWidget#ServerListWidget::item {
                background: rgba(31, 41, 55, 0.5);
                border-radius: 8px;
                margin: 2px 4px;
            }
            QListWidget#ServerListWidget::item:selected {
                background: rgba(124, 58, 237, 0.2);
                border: 1px solid rgba(124, 58, 237, 0.5);
            }
            QListWidget#ServerListWidget::item:hover {
                background: rgba(55, 65, 81, 0.6);
            }
        """)
        list_layout.addWidget(self._server_list, 1)

        self._empty_label = QLabel(self.tr("还没有服务器，点击「添加服务器」开始吧"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #6B7280; font-size: 14px; padding: 40px;")
        list_layout.addWidget(self._empty_label)

        layout.addWidget(list_card, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._join_btn = QPushButton(self.tr("加入服务器"))
        self._join_btn.setFixedHeight(52)
        self._join_btn.setMinimumWidth(200)
        self._join_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._join_btn.setEnabled(False)
        self._join_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7C3AED, stop:1 #A855F7);
                color: white; border: none; border-radius: 12px;
                font-size: 16px; font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #8B5CF6, stop:1 #C084FC);
            }
            QPushButton:disabled {
                background: #374151; color: #6B7280;
            }
        """)
        btn_row.addWidget(self._join_btn)

        btn_row.addStretch()

        self._edit_btn = QPushButton(self.tr("编辑"))
        self._edit_btn.setObjectName("SecondaryButton")
        self._edit_btn.setFixedHeight(52)
        self._edit_btn.setFixedWidth(100)
        self._edit_btn.setEnabled(False)
        btn_row.addWidget(self._edit_btn)

        self._delete_btn = QPushButton(self.tr("删除"))
        self._delete_btn.setObjectName("SecondaryButton")
        self._delete_btn.setFixedHeight(52)
        self._delete_btn.setFixedWidth(100)
        self._delete_btn.setEnabled(False)
        btn_row.addWidget(self._delete_btn)

        layout.addLayout(btn_row)

    def _connect_signals(self):
        self._add_btn.clicked.connect(self._add_server)
        self._refresh_btn.clicked.connect(self._refresh_all)
        self._server_list.currentItemChanged.connect(self._on_selection_changed)
        self._join_btn.clicked.connect(self._join_selected)
        self._edit_btn.clicked.connect(self._edit_selected)
        self._delete_btn.clicked.connect(self._delete_selected)

    def _load_servers(self):
        self._server_list.clear()
        self._items.clear()
        servers = self._mgr.get_all()
        for s in servers:
            self._add_item(s)
        self._update_empty_state()

    def _add_item(self, info: ServerInfo):
        status = self._mgr.get_status(info.address, info.port)
        key = self._mgr._make_key(info.address, info.port)
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 72))
        item.setData(Qt.ItemDataRole.UserRole, key)
        widget = ServerListItem(info, status)
        widget.join_clicked.connect(self._join_server)
        widget.edit_clicked.connect(self._edit_server)
        widget.delete_clicked.connect(self._delete_server)
        self._server_list.addItem(item)
        self._server_list.setItemWidget(item, widget)
        self._items[key] = (item, widget)
        self._update_empty_state()

    def _update_empty_state(self):
        count = len(self._items)
        self._empty_label.setVisible(count == 0)
        self._count_label.setText(self.tr("共 %d 个服务器") % count)

    def _on_selection_changed(self, current, previous):
        has_selection = current is not None
        self._join_btn.setEnabled(has_selection)
        self._edit_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        if current:
            key = current.data(Qt.ItemDataRole.UserRole)
            for k, (it, w) in self._items.items():
                w.set_selected(k == key)
            for info in self._mgr.get_all():
                if self._mgr._make_key(info.address, info.port) == key:
                    self._selected_server = (info.address, info.port)
                    break
        else:
            self._selected_server = None

    def _add_server(self):
        from .add_server_dialog import AddServerDialog
        dialog = AddServerDialog(parent=self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            name, addr, port = dialog.get_result()
            if self._mgr.get(addr, port):
                Toast.warning(self.tr("该服务器已在列表中"))
                return
            self._mgr.add(name, addr, port)
            info = self._mgr.get(addr, port)
            if info:
                self._add_item(info)
                Toast.success(self.tr("服务器已添加"))

    def _edit_server(self, address: str, port: int):
        info = self._mgr.get(address, port)
        if not info:
            return
        from .add_server_dialog import AddServerDialog
        dialog = AddServerDialog(server_info=info, parent=self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            name, new_addr, new_port = dialog.get_result()
            self._mgr.update(address, port, name, new_addr, new_port)
            self._load_servers()
            self._refresh_all()

    def _delete_server(self, address: str, port: int):
        reply = QMessageBox.question(
            self, self.tr("删除服务器"),
            self.tr("确定要从列表中删除该服务器吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._mgr.remove(address, port)
            self._load_servers()
            Toast.info(self.tr("服务器已删除"))

    def _refresh_all(self):
        self._mgr.refresh_all()

    def _join_selected(self):
        if self._selected_server:
            addr, port = self._selected_server
            self._join_server(addr, port)

    def _edit_selected(self):
        if self._selected_server:
            addr, port = self._selected_server
            self._edit_server(addr, port)

    def _delete_selected(self):
        if self._selected_server:
            addr, port = self._selected_server
            self._delete_server(addr, port)

    def _join_server(self, address: str, port: int):
        info = self._mgr.get(address, port)
        name = info.name if info else address
        status = self._mgr.get_status(address, port)
        if not status.online:
            reply = QMessageBox.question(
                self, self.tr("服务器离线"),
                self.tr("当前服务器似乎离线，仍然尝试加入吗？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.join_server_requested.emit(address, port, name)

    def _on_status_callback(self, key: str, status: ServerStatus):
        self._signal.status_updated.emit(key, status)

    def _apply_status_update(self, key: str, status: ServerStatus):
        if key in self._items:
            try:
                _, widget = self._items[key]
                widget.update_status(status)
            except Exception as e:
                logger.debug("更新服务器UI状态失败: %s", e)
