"""玩家头像显示组件。

异步加载玩家头像，支持点击事件，圆形裁剪显示。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QBrush, QColor
from PyQt6.QtWidgets import QWidget

from src.core.account import AccountInfo, AccountManager
from src.core.skin_manager import get_skin_manager


class _AvatarLoaderThread(QThread):
    avatar_loaded = pyqtSignal(str, str)

    def __init__(self, uuid_str: str, username: str, skin_url: Optional[str],
                 size: int, parent=None):
        super().__init__(parent)
        self._uuid = uuid_str
        self._username = username
        self._skin_url = skin_url
        self._size = size

    def run(self):
        try:
            mgr = get_skin_manager()
            path = mgr.get_avatar(
                self._uuid, self._username, self._skin_url,
                size=self._size
            )
            if path:
                self.avatar_loaded.emit(self._uuid, str(path))
        except Exception:
            pass


class PlayerAvatar(QWidget):
    clicked = pyqtSignal()

    def __init__(self, size: int = 32, parent=None):
        super().__init__(parent)
        self._size = size
        self._uuid: str = ""
        self._pixmap: Optional[QPixmap] = None
        self._loading = False
        self._placeholder_color = QColor("#4B5563")
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_account(self, account: Optional[AccountInfo]) -> None:
        if account is None:
            self._uuid = ""
            self._pixmap = None
            self.update()
            return

        self._uuid = account.uuid
        skin_url = account.skin_url
        size = self._size

        mgr = get_skin_manager()
        avatar_path = mgr.get_avatar_path(account.uuid, size)
        if avatar_path.exists() and avatar_path.stat().st_size > 0:
            self._set_pixmap_from_path(avatar_path)
        else:
            self._pixmap = None
            self._loading = True
            self.update()
            self._loader = _AvatarLoaderThread(
                account.uuid, account.username, skin_url, size, self
            )
            self._loader.avatar_loaded.connect(self._on_avatar_loaded)
            self._loader.start()

        if account.is_microsoft and account.skin_url is None:
            self._refresh_skin_async(account.uuid)

    def _refresh_skin_async(self, uuid_str: str) -> None:
        def _do_refresh():
            try:
                mgr = get_skin_manager()
                mgr.fetch_and_update_skin(uuid_str)
                avatar_path = mgr.get_avatar_path(uuid_str, self._size)
                if avatar_path.exists():
                    from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
                    QMetaObject.invokeMethod(
                        self, "_set_avatar_from_path",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, str(avatar_path))
                    )
            except Exception:
                pass
        t = threading.Thread(target=_do_refresh, daemon=True)
        t.start()

    def _on_avatar_loaded(self, uuid_str: str, path_str: str) -> None:
        if uuid_str != self._uuid:
            return
        self._set_pixmap_from_path(Path(path_str))

    def _set_pixmap_from_path(self, path: Path) -> None:
        pix = QPixmap(str(path))
        if not pix.isNull():
            scaled = pix.scaled(
                self._size, self._size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self._pixmap = scaled
        self._loading = False
        self.update()

    @pyqtSlot(str)
    def _set_avatar_from_path(self, path_str: str) -> None:
        self._set_pixmap_from_path(Path(path_str))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = self._size
        radius = size / 2

        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)

        if self._pixmap and not self._pixmap.isNull():
            painter.drawPixmap(0, 0, self._pixmap)
        else:
            painter.fillRect(0, 0, size, size, QBrush(self._placeholder_color))
            painter.setPen(QColor("#9CA3AF"))
            font = painter.font()
            font.setPointSize(int(size * 0.4))
            painter.setFont(font)
            painter.drawText(
                0, 0, size, size,
                Qt.AlignmentFlag.AlignCenter,
                "?"
            )

        painter.setClipping(False)
        pen = painter.pen()
        pen.setWidth(2)
        pen.setColor(QColor("rgba(255,255,255,30)"))
        painter.setPen(pen)
        painter.drawEllipse(1, 1, size - 2, size - 2)
        painter.end()
