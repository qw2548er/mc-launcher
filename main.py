"""Minecraft Launcher 应用程序入口点。

提供延迟加载、全局异常捕获、首次启动向导、自动更新检查等功能。
集成真实的 Mojang 版本列表获取和版本下载功能。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LAUNCHER_VERSION = "1.1.0"


def get_app_dir() -> Path:
    """获取应用程序数据目录。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    app_dir = base / "MCLauncher"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def setup_environment() -> None:
    """配置运行环境。"""
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(Path(__file__).parent)

    sys.path.insert(0, str(Path(__file__).parent / "src"))


def init_logging() -> None:
    """初始化日志系统。"""
    from src.utils.logger import setup_logging
    app_dir = get_app_dir()
    log_dir = app_dir / "logs"
    setup_logging(log_dir=log_dir, log_level=logging.DEBUG, console_level=logging.INFO)
    logger.info("Minecraft Launcher v%s 启动中...", LAUNCHER_VERSION)
    logger.info("应用数据目录: %s", app_dir)
    logger.info("Python: %s", sys.version)
    logger.info("平台: %s %s", sys.platform, os.name)


def init_crash_handler(app) -> None:
    """初始化全局异常处理。"""
    from src.utils.crash_handler import install_exception_hook, CrashReporter
    app_dir = get_app_dir()
    crash_dir = app_dir / "logs" / "crashes"

    def on_crash(crash_info: str, diagnosis: str) -> None:
        try:
            from PyQt6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("启动器崩溃")
            msg.setText("启动器遇到了一个错误，已自动保存崩溃日志。")
            msg.setDetailedText(crash_info + "\n\n[诊断建议]\n" + diagnosis)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        except Exception:
            print("崩溃:\n", crash_info, "\n诊断:\n", diagnosis, file=sys.stderr)

    install_exception_hook(crash_dir=crash_dir, dialog_callback=on_crash)


def check_first_run() -> dict | None:
    """检查是否首次运行，如果是则显示向导。

    Returns:
        配置结果字典，如果不是首次运行返回 None
    """
    from src.utils.config import ConfigManager
    config = ConfigManager()
    if config.get("first_run_completed", False):
        return None

    logger.info("首次启动，显示配置向导...")

    try:
        from PyQt6.QtWidgets import QApplication
        from src.ui.first_run_wizard import FirstRunWizard

        wizard = FirstRunWizard()
        if wizard.exec() == FirstRunWizard.DialogCode.Accepted:
            result = wizard.get_result()
            config.set("first_run_completed", True)
            config.set("java_path", result["java_path"])
            config.set("game_directory", result["game_dir"])
            config.set("max_memory_mb", result["max_memory_mb"])
            config.set("min_memory_mb", result["min_memory_mb"])
            config.save()
            return result
    except Exception as e:
        logger.error("运行首次启动向导失败: %s", e)

    return None


def detect_java() -> str | None:
    """自动检测 Java 安装。"""
    try:
        from src.core.java_detector import JavaDetector
        detector = JavaDetector()
        javas = detector.scan()
        if javas:
            best = None
            for j in javas:
                if j.major_version >= 17:
                    best = j
                    break
            if best is None:
                best = javas[0]
            logger.info("检测到 Java: %s (版本 %s)", best.path, best.version)
            return str(best.path)
    except Exception as e:
        logger.debug("Java 检测失败: %s", e)
    return None


def check_for_updates() -> None:
    """后台检查更新。"""
    try:
        from src.utils.updater import UpdateChecker
        checker = UpdateChecker(current_version=LAUNCHER_VERSION)
        update = checker.check_for_updates()
        if update:
            logger.info("发现新版本: %s", update.version)
    except Exception as e:
        logger.debug("检查更新失败（非致命）: %s", e)


def auto_backup_config() -> None:
    """自动备份配置文件。"""
    try:
        from src.utils.backup import BackupManager
        from src.utils.config import ConfigManager
        config = ConfigManager()
        game_dir = Path(config.get("game_directory", str(Path.home() / ".minecraft")))
        mgr = BackupManager(game_dir=game_dir)
        mgr.backup_config()
    except Exception as e:
        logger.debug("自动备份配置失败（非致命）: %s", e)


def main() -> int:
    setup_environment()
    init_logging()

    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer
    except ImportError as e:
        print(f"错误: 无法导入 PyQt6，请先安装依赖: pip install -r requirements.txt\n{e}", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("Minecraft Launcher")
    app.setApplicationVersion(LAUNCHER_VERSION)
    app.setOrganizationName("MCLauncher")

    init_crash_handler(app)

    from src.ui import ThemeManager, Theme, MainWindow
    from src.ui.widgets import Toast
    from src.utils.config import ConfigManager

    config = ConfigManager()
    theme_name = config.get("theme", "dark")
    ThemeManager.instance().set_theme(Theme.DARK if theme_name == "dark" else Theme.LIGHT)

    first_run_result = check_first_run()

    window = MainWindow()

    java_path = config.get("java_path", "")
    game_dir = config.get("game_directory", str(Path.home() / ".minecraft"))
    max_mem = config.get("max_memory_mb", 4096)

    if first_run_result:
        java_path = first_run_result["java_path"]
        game_dir = first_run_result["game_dir"]
        max_mem = first_run_result["max_memory_mb"]
        window.set_java_path(java_path)
        window.set_game_dir(game_dir)
        window.set_memory_allocation(max_mem // 1024)
        Toast.success("配置完成，欢迎使用 Minecraft Launcher！")
    else:
        if not java_path:
            detected = detect_java()
            if detected:
                java_path = detected
                config.set("java_path", java_path)
                config.save()
        if java_path:
            window.set_java_path(java_path)
            java_version = None
            try:
                from src.core.java_detector import JavaDetector
                from pathlib import Path
                detector = JavaDetector()
                java_info = detector.check_java(Path(java_path))
                if java_info:
                    java_version = java_info.version
            except Exception:
                pass
            if java_version:
                window.set_java_status(java_version)
            else:
                window.set_java_status("已配置")
        else:
            Toast.warning("未检测到 Java，请在设置中手动配置 Java 路径")

        window.set_game_dir(game_dir)
        window.set_memory_allocation(max(1, max_mem // 1024))

    from src.utils.config import get_config
    config = get_config()
    config.load()

    saved_username = config.get("offline_username", "Steve")
    window.set_account_info(saved_username, is_microsoft=False)

    window.version_selected.connect(
        lambda v: logger.info("选择版本: %s", v)
    )

    window.show()

    QTimer.singleShot(2000, check_for_updates)
    QTimer.singleShot(5000, auto_backup_config)

    logger.info("启动器界面已显示")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
