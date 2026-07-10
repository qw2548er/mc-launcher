"""游戏日志窗口模块。

实时显示 Minecraft 游戏的输出日志，支持按日志级别着色、自动滚动、复制日志等功能。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QFont, QTextCharFormat, QColor, QTextCursor, QIcon, QAction
)
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QComboBox, QLabel, QCheckBox, QFileDialog, QMessageBox,
    QApplication, QToolBar
)

from .widgets.dialog_title_bar import DialogTitleBar


class GameLogWindow(QDialog):
    """游戏日志窗口。"""

    game_closed = pyqtSignal(int)
    kill_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_game_running = False
        self._exit_code = None
        self._log_count = 0
        self._max_lines = 1000
        self._setup_colors()
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.tr("游戏日志"))
        self.setMinimumSize(800, 500)
        self.resize(900, 600)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._title_bar = DialogTitleBar(self, title=self.tr("游戏日志"))
        self._title_bar.close_clicked.connect(self.hide)
        root_layout.addWidget(self._title_bar)

        content = QWidget()
        content.setObjectName("LogContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._status_label = QLabel(self.tr("游戏未启动"))
        self._status_label.setStyleSheet("font-weight: 600; color: #9CA3AF;")
        toolbar.addWidget(self._status_label)

        toolbar.addStretch()

        self._auto_scroll = QCheckBox(self.tr("自动滚动"))
        self._auto_scroll.setChecked(True)
        toolbar.addWidget(self._auto_scroll)

        filter_label = QLabel(self.tr("日志级别:"))
        toolbar.addWidget(filter_label)

        self._level_filter = QComboBox()
        self._level_filter.addItems([
            self.tr("全部"),
            self.tr("INFO+"),
            self.tr("WARN+"),
            self.tr("ERROR"),
        ])
        self._level_filter.setCurrentIndex(0)
        toolbar.addWidget(self._level_filter)

        self._clear_btn = QPushButton(self.tr("清空"))
        self._clear_btn.setObjectName("SecondaryButton")
        self._clear_btn.clicked.connect(self.clear_log)
        toolbar.addWidget(self._clear_btn)

        self._save_btn = QPushButton(self.tr("保存日志"))
        self._save_btn.setObjectName("SecondaryButton")
        self._save_btn.clicked.connect(self.save_log)
        toolbar.addWidget(self._save_btn)

        content_layout.addLayout(toolbar)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        font = QFont("Consolas, 'Courier New', monospace", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._log_view.setFont(font)
        self._log_view.setMaximumBlockCount(self._max_lines)
        self._log_view.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1a1a2e;
                color: #e0e0e0;
                border: 1px solid #2d2d44;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #7C3AED;
            }
        """)
        content_layout.addWidget(self._log_view, 1)

        bottom_row = QHBoxLayout()
        self._count_label = QLabel("0 lines")
        self._count_label.setStyleSheet("color: #6B7280; font-size: 12px;")
        bottom_row.addWidget(self._count_label)
        bottom_row.addStretch()

        self._close_btn = QPushButton(self.tr("关闭窗口"))
        self._close_btn.setObjectName("SecondaryButton")
        self._close_btn.clicked.connect(self.hide)
        bottom_row.addWidget(self._close_btn)

        self._kill_btn = QPushButton(self.tr("强制终止游戏"))
        self._kill_btn.setObjectName("DangerButton")
        self._kill_btn.clicked.connect(self._on_kill_clicked)
        self._kill_btn.setEnabled(False)
        bottom_row.addWidget(self._kill_btn)

        content_layout.addLayout(bottom_row)

        root_layout.addWidget(content, 1)

    def _setup_colors(self) -> None:
        self._colors = {
            "DEBUG": QColor("#6B7280"),
            "INFO": QColor("#10B981"),
            "WARN": QColor("#F59E0B"),
            "ERROR": QColor("#EF4444"),
            "FATAL": QColor("#DC2626"),
            "default": QColor("#E5E7EB"),
        }

    def append_log(self, line: str, level: str = "INFO") -> None:
        filter_idx = self._level_filter.currentIndex()
        if filter_idx > 0:
            level_order = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3, "FATAL": 4}
            min_level = ["DEBUG", "INFO", "WARN", "ERROR"][filter_idx]
            if level_order.get(level, 0) < level_order.get(min_level, 0):
                return

        self._log_count += 1

        fmt = QTextCharFormat()
        fmt.setForeground(self._colors.get(level, self._colors["default"]))

        if level in ("ERROR", "FATAL"):
            fmt.setFontWeight(QFont.Weight.Bold)

        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(line + "\n", fmt)

        if self._auto_scroll.isChecked():
            self._log_view.setTextCursor(cursor)
            self._log_view.ensureCursorVisible()

        self._count_label.setText(f"{self._log_count} lines")

    def clear_log(self) -> None:
        self._log_view.clear()
        self._log_count = 0
        self._count_label.setText("0 lines")

    def save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("保存日志"),
            "minecraft_log.txt",
            "Text files (*.txt);;Log files (*.log);;All files (*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._log_view.toPlainText())
                QMessageBox.information(self, self.tr("保存成功"), self.tr("日志已保存到:\n") + path)
            except OSError as e:
                QMessageBox.critical(self, self.tr("保存失败"), str(e))

    def set_game_running(self, running: bool, version_id: str = "") -> None:
        self._is_game_running = running
        self._kill_btn.setEnabled(running)

        if running:
            self._status_label.setText(
                self.tr("游戏运行中: ") + version_id
            )
            self._status_label.setStyleSheet("font-weight: 600; color: #10B981;")
        else:
            if self._exit_code == 0:
                status_text = self.tr("游戏已正常退出")
                color = "#9CA3AF"
            elif self._exit_code is not None:
                status_text = self.tr(f"游戏异常退出 (退出码: {self._exit_code})")
                color = "#EF4444"
            else:
                status_text = self.tr("游戏未启动")
                color = "#9CA3AF"
            self._status_label.setText(status_text)
            self._status_label.setStyleSheet(f"font-weight: 600; color: {color};")

    def on_game_exit(self, exit_code: int) -> None:
        self._exit_code = exit_code
        self.set_game_running(False)

        if exit_code != 0:
            self.append_log(
                f"\n[Launcher] 游戏进程异常退出，退出码: {exit_code}",
                "ERROR"
            )
            self._show_error_dialog(exit_code)
        else:
            self.append_log("\n[Launcher] 游戏进程已正常退出", "INFO")

    def _show_error_dialog(self, exit_code: int) -> None:
        crash_reason = self._scan_log_for_crash_reason()
        suggestions = []

        if crash_reason:
            suggestions.append(crash_reason["suggestion"])

        if exit_code == 1:
            if not crash_reason:
                suggestions.append(self.tr("游戏崩溃，请检查日志获取详细信息"))
        elif exit_code == -1073740791 or exit_code == 0xC0000409:
            suggestions.append(self.tr("可能是内存不足，请尝试减少内存分配"))
        elif exit_code == -1073741515 or exit_code == 0xC0000135:
            suggestions.append(self.tr("缺少 DLL 文件，请检查 Java 安装是否完整"))
        elif exit_code == -1073741819 or exit_code == 0xC0000005:
            suggestions.append(self.tr("内存访问错误，可能是显卡驱动问题"))
        elif exit_code == 137 or exit_code == -9:
            suggestions.append(self.tr("进程被强制终止"))
        else:
            if not crash_reason:
                suggestions.append(self.tr("请检查游戏日志获取详细错误信息"))
                suggestions.append(self.tr("确保已安装正确版本的 Java"))
                suggestions.append(self.tr("尝试增加/减少内存分配"))

        msg = self.tr("游戏异常退出！") + "\n\n" + self.tr("退出码: ") + str(exit_code) + "\n\n"
        if crash_reason:
            msg += self.tr("崩溃原因: ") + crash_reason["title"] + "\n\n"
        msg += self.tr("建议解决方案:") + "\n"
        for i, s in enumerate(suggestions, 1):
            msg += f"  {i}. {s}\n"

        self.append_log(msg, "ERROR")

    _CRASH_PATTERNS = [
        {
            "pattern": "JsonSyntaxException.*Expected BEGIN_OBJECT but was STRING",
            "title": "版本配置文件 JSON 损坏",
            "suggestion": (
                "版本配置文件（如 versions/1.7.10/1.7.10.json）已损坏或为空。\n"
                "请点击「修复版本」重新下载，或手动删除该JSON文件后重新安装版本。"
            ),
        },
        {
            "pattern": "JsonSyntaxException",
            "title": "JSON 配置文件解析失败",
            "suggestion": (
                "游戏依赖的某个 JSON 配置文件损坏。\n"
                "请尝试点击「修复版本」重新下载，或检查 .minecraft 目录下相关 JSON 文件。"
            ),
        },
        {
            "pattern": "UnsupportedClassVersionError",
            "title": "Java 版本不兼容",
            "suggestion": (
                "Java 版本不兼容当前 Minecraft 版本。\n"
                "例如 Minecraft 1.17+ 需要 Java 17+，1.21+ 需要 Java 21+。\n"
                "请在设置中切换为兼容的 Java 版本。"
            ),
        },
        {
            "pattern": "OutOfMemoryError",
            "title": "内存不足",
            "suggestion": (
                "游戏内存不足导致崩溃。\n"
                "请尝试在设置中增加内存分配，或关闭其他占用内存的程序。"
            ),
        },
        {
            "pattern": "ClassNotFoundException|NoClassDefFoundError",
            "title": "游戏文件缺失",
            "suggestion": (
                "缺少必要游戏类文件，可能是版本下载不完整。\n"
                "请点击「修复版本」重新下载完整版本文件。"
            ),
        },
        {
            "pattern": "UnsatisfiedLinkError.*lwjgl",
            "title": "LWJGL 原生库加载失败",
            "suggestion": (
                "LWJGL 原生库加载失败，可能是显卡驱动不兼容或渲染器配置错误。\n"
                "请尝试在设置中切换 OpenGL 渲染器为 Krypton Wrapper。"
            ),
        },
        {
            "pattern": r"java\.lang\.NullPointerException",
            "title": "游戏空指针异常",
            "suggestion": (
                "游戏内部空指针异常，可能是模组兼容性问题或版本文件不完整。\n"
                "请检查模组兼容性，或尝试修复版本。"
            ),
        },
    ]

    def _scan_log_for_crash_reason(self) -> Optional[dict]:
        """扫描游戏日志，识别已知崩溃原因。

        Returns:
            dict with 'title' and 'suggestion' keys, or None
        """
        log_text = self._log_view.toPlainText()
        if not log_text:
            return None

        for pattern_def in self._CRASH_PATTERNS:
            import re
            if re.search(pattern_def["pattern"], log_text, re.IGNORECASE):
                return {
                    "title": pattern_def["title"],
                    "suggestion": pattern_def["suggestion"],
                }

        return None

    def _on_kill_clicked(self) -> None:
        reply = QMessageBox.warning(
            self,
            self.tr("强制终止"),
            self.tr("确定要强制终止游戏进程吗？\n未保存的进度将会丢失！"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.kill_requested.emit()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
