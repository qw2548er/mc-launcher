"""主题管理器模块。

提供明暗主题切换、QSS 样式管理、主题色配置功能。
"""

from enum import Enum
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


class Theme(Enum):
    LIGHT = "light"
    DARK = "dark"


class ThemeColor:
    PURPLE = {"primary": "#7C3AED", "primary_light": "#8B5CF6", "primary_dark": "#6D28D9"}
    BLUE = {"primary": "#3B82F6", "primary_light": "#60A5FA", "primary_dark": "#2563EB"}
    INDIGO = {"primary": "#6366F1", "primary_light": "#818CF8", "primary_dark": "#4F46E5"}


class ThemeManager(QObject):
    theme_changed = pyqtSignal(Theme)

    _instance: Optional["ThemeManager"] = None

    def __init__(self):
        super().__init__()
        self._current_theme = Theme.DARK
        self._accent_color = ThemeColor.PURPLE
        self._style_sheet = ""

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    @property
    def current_theme(self) -> Theme:
        return self._current_theme

    @property
    def accent_color(self) -> dict:
        return self._accent_color

    def set_theme(self, theme: Theme) -> None:
        self._current_theme = theme
        self._apply_theme()
        self.theme_changed.emit(theme)

    def toggle_theme(self) -> None:
        new_theme = Theme.LIGHT if self._current_theme == Theme.DARK else Theme.DARK
        self.set_theme(new_theme)

    def set_accent_color(self, color_dict: dict) -> None:
        self._accent_color = color_dict
        self._apply_theme()

    def get_stylesheet(self) -> str:
        return self._style_sheet

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        self._style_sheet = self._build_stylesheet()
        app.setStyleSheet(self._style_sheet)

    def _build_stylesheet(self) -> str:
        is_dark = self._current_theme == Theme.DARK
        p = self._accent_color["primary"]
        pl = self._accent_color["primary_light"]
        pd = self._accent_color["primary_dark"]

        if is_dark:
            bg = "#1A1A2E"
            bg_card = "#16213E"
            bg_elevated = "#0F3460"
            bg_input = "#1F2937"
            bg_hover = "#252F4A"
            text = "#E5E7EB"
            text_secondary = "#9CA3AF"
            text_muted = "#6B7280"
            border = "#374151"
            border_focus = p
            success = "#10B981"
            warning = "#F59E0B"
            error = "#EF4444"
            progress_bg = "#374151"
        else:
            bg = "#F3F4F6"
            bg_card = "#FFFFFF"
            bg_elevated = "#F9FAFB"
            bg_input = "#F3F4F6"
            bg_hover = "#E5E7EB"
            text = "#111827"
            text_secondary = "#4B5563"
            text_muted = "#9CA3AF"
            border = "#D1D5DB"
            border_focus = p
            success = "#059669"
            warning = "#D97706"
            error = "#DC2626"
            progress_bg = "#E5E7EB"

        return f"""
        * {{
            font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
            font-size: 13px;
            color: {text};
        }}

        QMainWindow, QDialog {{
            background-color: {bg};
        }}

        /* ====== 标题栏 ====== */
        #TitleBar {{
            background-color: {bg_card};
            border-bottom: 1px solid {border};
            min-height: 48px;
            max-height: 48px;
        }}
        #TitleBar QLabel {{
            color: {text};
            font-size: 14px;
            font-weight: 600;
        }}
        #TitleBarButton {{
            background-color: transparent;
            border: none;
            min-width: 46px;
            max-width: 46px;
            min-height: 32px;
            max-height: 32px;
            border-radius: 6px;
            color: {text_secondary};
            font-size: 14px;
        }}
        #TitleBarButton:hover {{
            background-color: {bg_hover};
            color: {text};
        }}
        #CloseButton:hover {{
            background-color: {error};
            color: white;
        }}

        /* ====== 卡片 ====== */
        #CardWidget {{
            background-color: {bg_card};
            border-radius: 12px;
            border: 1px solid {border};
        }}
        #CardWidget:hover {{
            border-color: {p}60;
        }}

        /* ====== 按钮 ====== */
        QPushButton {{
            background-color: {bg_elevated};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 8px 20px;
            color: {text};
            font-weight: 500;
            min-height: 20px;
        }}
        QPushButton:hover {{
            background-color: {bg_hover};
            border-color: {p}80;
        }}
        QPushButton:pressed {{
            background-color: {border};
        }}
        QPushButton:disabled {{
            color: {text_muted};
            background-color: {bg_input};
            border-color: {border};
        }}

        #PrimaryButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {pd}, stop:1 {p});
            border: none;
            color: white;
            font-weight: 700;
            font-size: 15px;
            padding: 14px 40px;
            border-radius: 12px;
            min-height: 24px;
        }}
        #PrimaryButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {p}, stop:1 {pl});
        }}
        #PrimaryButton:pressed {{
            background: {pd};
        }}
        #PrimaryButton:disabled {{
            background: {text_muted};
            color: {bg};
        }}

        #LaunchButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {pd}, stop:0.5 {p}, stop:1 {pl});
            border: none;
            color: white;
            font-weight: 800;
            font-size: 20px;
            padding: 20px 60px;
            border-radius: 16px;
            min-height: 40px;
        }}
        #LaunchButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {p}, stop:0.5 {pl}, stop:1 #A78BFA);
        }}
        #LaunchButton:pressed {{
            background: {pd};
        }}

        #IconButton {{
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 8px;
            min-width: 36px;
            max-width: 36px;
            min-height: 36px;
            max-height: 36px;
        }}
        #IconButton:hover {{
            background-color: {bg_hover};
            border-color: {border};
        }}

        /* ====== 输入框 ====== */
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
            background-color: {bg_input};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 8px 12px;
            color: {text};
            min-height: 20px;
            selection-background-color: {p};
            selection-color: white;
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
        QSpinBox:focus, QComboBox:focus {{
            border-color: {border_focus};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 30px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {text_secondary};
            margin-right: 10px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {bg_card};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 4px;
            selection-background-color: {p};
            selection-color: white;
            outline: none;
        }}

        /* ====== 列表 ====== */
        QListWidget, QTreeWidget, QTableWidget {{
            background-color: {bg_card};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 4px;
            outline: none;
        }}
        QListWidget::item, QTreeWidget::item {{
            padding: 10px;
            border-radius: 8px;
            margin: 2px 4px;
        }}
        QListWidget::item:selected, QTreeWidget::item:selected {{
            background-color: {p}30;
            color: {text};
        }}
        QListWidget::item:hover, QTreeWidget::item:hover {{
            background-color: {bg_hover};
        }}

        #VersionList {{
            background-color: {bg_card};
            border: none;
            border-right: 1px solid {border};
            border-radius: 0;
            padding: 8px;
        }}
        #VersionList::item {{
            padding: 12px 16px;
            border-radius: 10px;
            margin: 3px 0;
        }}
        #VersionList::item:selected {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {pd}40, stop:1 {p}20);
            border-left: 3px solid {p};
            padding-left: 13px;
        }}
        #VersionList::item:hover {{
            background-color: {bg_hover};
        }}

        /* ====== 滚动条 ====== */
        QScrollBar:vertical {{
            background-color: transparent;
            width: 8px;
            margin: 4px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {border};
            border-radius: 4px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {text_muted};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            background-color: transparent;
            height: 8px;
            margin: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {border};
            border-radius: 4px;
            min-width: 30px;
        }}

        /* ====== 进度条 ====== */
        QProgressBar {{
            background-color: {progress_bg};
            border: none;
            border-radius: 6px;
            height: 12px;
            text-align: center;
            color: transparent;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {pd}, stop:1 {pl});
            border-radius: 6px;
        }}
        #LargeProgressBar {{
            height: 24px;
            border-radius: 12px;
        }}
        #LargeProgressBar::chunk {{
            border-radius: 12px;
        }}

        /* ====== 滑块 ====== */
        QSlider::groove:horizontal {{
            background-color: {progress_bg};
            height: 6px;
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            background-color: {p};
            width: 18px;
            height: 18px;
            margin: -6px 0;
            border-radius: 9px;
        }}
        QSlider::handle:horizontal:hover {{
            background-color: {pl};
        }}
        QSlider::sub-page:horizontal {{
            background-color: {p};
            border-radius: 3px;
        }}

        /* ====== 复选框/单选框 ====== */
        QCheckBox, QRadioButton {{
            spacing: 8px;
            color: {text};
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {border};
            border-radius: 4px;
            background-color: {bg_input};
        }}
        QRadioButton::indicator {{
            border-radius: 9px;
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background-color: {p};
            border-color: {p};
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
            border-color: {p};
        }}

        /* ====== 标签页 ====== */
        QTabWidget::pane {{
            border: 1px solid {border};
            border-radius: 10px;
            background-color: {bg_card};
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: transparent;
            border: none;
            padding: 10px 20px;
            color: {text_secondary};
            border-radius: 8px;
            margin: 4px 2px;
        }}
        QTabBar::tab:selected {{
            color: {text};
            background-color: {p}20;
        }}
        QTabBar::tab:hover {{
            color: {text};
            background-color: {bg_hover};
        }}

        /* ====== 分组框 ====== */
        QGroupBox {{
            border: 1px solid {border};
            border-radius: 10px;
            margin-top: 16px;
            padding: 16px 12px 12px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 16px;
            padding: 0 8px;
            color: {text_secondary};
        }}

        /* ====== 状态栏 ====== */
        QStatusBar {{
            background-color: {bg_card};
            border-top: 1px solid {border};
            color: {text_secondary};
            min-height: 32px;
            max-height: 32px;
        }}
        QStatusBar QLabel {{
            color: {text_secondary};
            padding: 0 8px;
        }}

        /* ====== 菜单 ====== */
        QMenu {{
            background-color: {bg_card};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 8px 24px;
            border-radius: 6px;
        }}
        QMenu::item:selected {{
            background-color: {p}30;
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {border};
            margin: 4px 8px;
        }}

        /* ====== ToolTip ====== */
        QToolTip {{
            background-color: {bg_elevated};
            color: {text};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px 10px;
        }}

        /* ====== 侧边栏导航项 ====== */
        #NavItem {{
            background-color: transparent;
            border: none;
            border-radius: 10px;
            padding: 12px 20px;
            text-align: left;
            color: {text_secondary};
            font-size: 14px;
            font-weight: 500;
            min-height: 20px;
        }}
        #NavItem:hover {{
            background-color: {bg_hover};
            color: {text};
        }}
        #NavItem[active="true"] {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {pd}40, stop:1 {p}20);
            color: {text};
            border-left: 3px solid {p};
            padding-left: 17px;
        }}

        /* ====== 版本类型标签 ====== */
        #VersionTag {{
            color: white;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 6px;
        }}
        #VersionTag[type="release"] {{
            background-color: {success};
        }}
        #VersionTag[type="snapshot"] {{
            background-color: {warning};
        }}
        #VersionTag[type="old_beta"], #VersionTag[type="old_alpha"] {{
            background-color: {text_muted};
        }}

        /* ====== 分隔线 ====== */
        #Separator {{
            background-color: {border};
            max-height: 1px;
            min-height: 1px;
        }}

        /* ====== 头像 ====== */
        #AvatarLabel {{
            border-radius: 20px;
            background-color: {bg_hover};
            border: 2px solid {border};
        }}

        /* ====== Toast ====== */
        #ToastWidget {{
            background-color: {bg_elevated};
            border: 1px solid {border};
            border-radius: 10px;
            padding: 12px 20px;
        }}
        #ToastWidget QLabel {{
            color: {text};
            font-size: 13px;
        }}
        """
