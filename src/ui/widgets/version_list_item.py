"""版本列表项组件。

显示版本名称、类型标签（正式版/快照版等）和状态。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel


class VersionListItem(QWidget):
    def __init__(self, version_id: str, version_type: str = "release",
                 is_installed: bool = False, is_latest: bool = False, parent=None):
        super().__init__(parent)
        self._version_id = version_id
        self._version_type = version_type
        self._is_installed = is_installed
        self._is_latest = is_latest
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)

        self._name_label = QLabel(self._version_id)
        name_font = QFont()
        name_font.setPointSize(12)
        name_font.setWeight(QFont.Weight.DemiBold)
        self._name_label.setFont(name_font)
        name_row.addWidget(self._name_label)

        if self._is_latest:
            latest_tag = QLabel("最新")
            latest_tag.setObjectName("VersionTag")
            latest_tag.setStyleSheet("background-color: #7C3AED; color: white; font-size: 10px; "
                                    "font-weight: 700; padding: 2px 8px; border-radius: 6px;")
            name_row.addWidget(latest_tag)

        name_row.addStretch()
        info_layout.addLayout(name_row)

        tag_row = QHBoxLayout()
        tag_row.setSpacing(6)

        type_tag = QLabel(self._get_type_text())
        type_tag.setObjectName("VersionTag")
        type_tag.setProperty("type", self._version_type)
        tag_row.addWidget(type_tag)

        if self._is_installed:
            installed_tag = QLabel("已安装")
            installed_tag.setStyleSheet(
                "color: #10B981; font-size: 11px; font-weight: 600; padding: 2px 0;"
            )
            tag_row.addWidget(installed_tag)

        tag_row.addStretch()
        info_layout.addLayout(tag_row)

        layout.addLayout(info_layout, 1)

    @property
    def version_id(self) -> str:
        return self._version_id

    @property
    def version_type(self) -> str:
        return self._version_type

    @property
    def is_installed(self) -> bool:
        return self._is_installed

    def _get_type_text(self) -> str:
        type_map = {
            "release": "正式版",
            "snapshot": "快照版",
            "old_beta": "Beta",
            "old_alpha": "Alpha",
        }
        return type_map.get(self._version_type, self._version_type)
