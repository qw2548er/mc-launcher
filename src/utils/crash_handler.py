"""全局异常处理和崩溃日志模块。

提供未捕获异常的拦截、崩溃日志保存和错误对话框显示。
"""

from __future__ import annotations

import logging
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class CrashReporter:
    """崩溃日志报告器。

    捕获未处理异常，生成崩溃日志，并提供用户友好的错误诊断。
    """

    _instance: Optional["CrashReporter"] = None
    _crash_dir: Path = Path("logs/crashes")
    _dialog_callback: Optional[Callable[[str, str], None]] = None
    _initialized = False

    def __init__(self):
        self._excepthook_installed = False

    @classmethod
    def instance(cls) -> "CrashReporter":
        if cls._instance is None:
            cls._instance = CrashReporter()
        return cls._instance

    def init(self, crash_dir: Optional[Path] = None,
             dialog_callback: Optional[Callable[[str, str], None]] = None) -> None:
        if self._initialized:
            return

        if crash_dir:
            self._crash_dir = crash_dir
        self._dialog_callback = dialog_callback

        self._crash_dir.mkdir(parents=True, exist_ok=True)

        sys.excepthook = self._handle_exception

        if hasattr(sys, "unraisablehook"):
            sys.unraisablehook = self._handle_unraisable

        self._excepthook_installed = True
        self._initialized = True
        logger.info("崩溃报告器已初始化，崩溃日志目录: %s", self._crash_dir)

    def _handle_exception(self, exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        crash_info = self._collect_crash_info(exc_type, exc_value, exc_tb)
        crash_file = self._save_crash_log(crash_info)
        logger.error("未捕获异常！崩溃日志已保存至: %s", crash_file)
        logger.error("异常信息:\n%s", crash_info)

        diagnosis = self._diagnose_error(exc_type, exc_value)

        if self._dialog_callback is not None:
            try:
                self._dialog_callback(crash_info, diagnosis)
            except Exception:
                pass

    def _handle_unraisable(self, unraisable):
        exc_type = type(unraisable.exc_value) if unraisable.exc_value else Exception
        exc_value = unraisable.exc_value
        exc_tb = unraisable.exc_value.__traceback__ if unraisable.exc_value else None
        self._handle_exception(exc_type, exc_value, exc_tb)

    def _collect_crash_info(self, exc_type, exc_value, exc_tb) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append(f"Minecraft Launcher 崩溃报告")
        lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 70)
        lines.append("")

        lines.append("[系统信息]")
        lines.append(f"  操作系统: {platform.system()} {platform.release()} ({platform.version()})")
        lines.append(f"  平台: {platform.platform()}")
        lines.append(f"  Python 版本: {sys.version}")
        lines.append(f"  架构: {platform.machine()}")
        lines.append(f"  处理器: {platform.processor()}")
        lines.append("")

        lines.append("[启动器信息]")
        lines.append(f"  版本: {get_launcher_version()}")
        lines.append(f"  工作目录: {Path.cwd()}")
        lines.append("")

        lines.append("[异常信息]")
        lines.append(f"  类型: {exc_type.__name__}")
        lines.append(f"  信息: {exc_value}")
        lines.append("")

        lines.append("[调用栈]")
        if exc_tb:
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            for line in tb_lines:
                lines.append(f"  {line.rstrip()}")
        else:
            lines.append("  <无调用栈信息>")
        lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)

    def _save_crash_log(self, crash_info: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        crash_file = self._crash_dir / f"crash_{timestamp}.log"
        try:
            crash_file.write_text(crash_info, encoding="utf-8")
        except OSError as e:
            logger.error("保存崩溃日志失败: %s", e)
            fallback = Path(f"crash_{timestamp}.log")
            fallback.write_text(crash_info, encoding="utf-8")
            return fallback
        return crash_file

    def _diagnose_error(self, exc_type, exc_value) -> str:
        error_msg = str(exc_value).lower()
        error_type = exc_type.__name__
        suggestions = []

        java_keywords = ["java", "javahome", "jvm", "no java", "java not found"]
        if any(kw in error_msg for kw in java_keywords):
            suggestions.append("🔴 Java 环境问题")
            suggestions.append("   解决方案：")
            suggestions.append("   1. 请确保已安装对应版本的 Java")
            suggestions.append("   2. Minecraft 1.17+ 需要 Java 17")
            suggestions.append("   3. Minecraft 1.20.5+ 需要 Java 21")
            suggestions.append("   4. 请在设置中手动指定 Java 路径")

        mem_keywords = ["memory", "outofmemory", "oom", "heap space", "内存", "memoryerror"]
        if any(kw in error_msg for kw in mem_keywords):
            suggestions.append("🔴 内存不足")
            suggestions.append("   解决方案：")
            suggestions.append("   1. 请减少分配给 Minecraft 的最大内存")
            suggestions.append("   2. 关闭其他占用内存的程序")
            suggestions.append("   3. 建议最大内存不超过物理内存的一半")

        net_keywords = ["connection", "timeout", "network", "dns", "ssl", "connectionreset",
                        "httperror", "requests", "proxy", "连接"]
        if any(kw in error_msg for kw in net_keywords):
            suggestions.append("🟡 网络连接问题")
            suggestions.append("   解决方案：")
            suggestions.append("   1. 请检查网络连接是否正常")
            suggestions.append("   2. 尝试切换下载源")
            suggestions.append("   3. 检查代理设置")
            suggestions.append("   4. 稍后重试")

        file_keywords = ["permission", "access", "file not found", "not a directory",
                         "no such file", "disk", "空间", "权限"]
        if any(kw in error_msg for kw in file_keywords):
            suggestions.append("🟡 文件访问问题")
            suggestions.append("   解决方案：")
            suggestions.append("   1. 检查磁盘空间是否充足")
            suggestions.append("   2. 以管理员身份运行启动器")
            suggestions.append("   3. 检查游戏目录权限")

        mod_keywords = ["mod", "forge", "fabric", "loader", "modload", "mods"]
        if any(kw in error_msg.lower() for kw in mod_keywords):
            suggestions.append("🟡 模组/加载器问题")
            suggestions.append("   解决方案：")
            suggestions.append("   1. 检查模组版本是否与游戏版本匹配")
            suggestions.append("   2. 尝试移除最近添加的模组")
            suggestions.append("   3. 检查模组依赖是否完整")

        if error_type == "HttpError":
            suggestions.append("🟡 网络请求失败")
            suggestions.append("   解决方案：")
            suggestions.append("   1. 检查网络连接")
            suggestions.append("   2. 尝试切换下载源（镜像）")

        if error_type in ("FileNotFoundError", "FileNotFoundError"):
            if "file" not in error_msg and "path" not in error_msg:
                suggestions.append("🟡 文件不存在")
                suggestions.append("   解决方案：")
                suggestions.append("   1. 检查版本是否完整安装")
                suggestions.append("   2. 尝试重新下载/修复版本")

        if not suggestions:
            suggestions.append("❓ 未知错误")
            suggestions.append(f"   错误类型: {error_type}")
            suggestions.append(f"   错误信息: {exc_value}")
            suggestions.append("   建议：")
            suggestions.append("   1. 查看崩溃日志获取详细信息")
            suggestions.append("   2. 重启启动器后重试")
            suggestions.append("   3. 检查启动器更新")

        return "\n".join(suggestions)


def install_exception_hook(
    crash_dir: Optional[Path] = None,
    dialog_callback: Optional[Callable[[str, str], None]] = None,
) -> None:
    CrashReporter.instance().init(crash_dir=crash_dir, dialog_callback=dialog_callback)


def get_launcher_version() -> str:
    try:
        from importlib.metadata import version
        return version("mc-launcher")
    except Exception:
        return "1.0.0"


def generate_diagnostic_report(extra_info: Optional[dict] = None) -> str:
    """生成完整的诊断报告。

    Args:
        extra_info: 额外的诊断信息字典

    Returns:
        诊断报告字符串
    """
    lines = []
    lines.append("=" * 70)
    lines.append("Minecraft Launcher 诊断报告")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)
    lines.append("")

    lines.append("[系统环境]")
    lines.append(f"  OS: {platform.system()} {platform.release()} ({platform.version()})")
    lines.append(f"  架构: {platform.machine()}")
    lines.append(f"  Python: {sys.version.split()[0]}")
    lines.append("")

    try:
        import psutil
        mem = psutil.virtual_memory()
        lines.append("[内存信息]")
        lines.append(f"  总内存: {mem.total / (1024**3):.1f} GB")
        lines.append(f"  可用内存: {mem.available / (1024**3):.1f} GB")
        lines.append(f"  使用率: {mem.percent}%")
        lines.append("")

        disk = psutil.disk_usage(str(Path.home()))
        lines.append("[磁盘信息]")
        lines.append(f"  总空间: {disk.total / (1024**3):.1f} GB")
        lines.append(f"  可用空间: {disk.free / (1024**3):.1f} GB")
        lines.append(f"  使用率: {disk.percent}%")
        lines.append("")
    except ImportError:
        lines.append("[系统资源] (安装 psutil 可获取详细信息)")
        lines.append("")

    lines.append("[启动器版本]")
    lines.append(f"  版本: {get_launcher_version()}")
    lines.append(f"  工作目录: {Path.cwd()}")
    lines.append("")

    try:
        from src.core.java_detector import JavaDetector
        detector = JavaDetector()
        javas = detector.find_java_installations()
        lines.append("[Java 环境]")
        if javas:
            for j in javas:
                lines.append(f"  路径: {j.path}")
                lines.append(f"  版本: {j.version_string}")
                lines.append(f"  架构: {j.arch}")
                lines.append("")
        else:
            lines.append("  未检测到 Java 安装")
            lines.append("")
    except Exception as e:
        lines.append(f"[Java 检测失败] {e}")
        lines.append("")

    if extra_info:
        lines.append("[额外信息]")
        for k, v in extra_info.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def export_diagnostic_report(save_path: Optional[Path] = None,
                             extra_info: Optional[dict] = None) -> Path:
    """导出诊断报告到文件。

    Args:
        save_path: 保存路径，默认保存到 logs/diagnostic_{timestamp}.txt
        extra_info: 额外诊断信息

    Returns:
        保存的文件路径
    """
    report = generate_diagnostic_report(extra_info=extra_info)

    if save_path is None:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = log_dir / f"diagnostic_{ts}.txt"
    else:
        save_path.parent.mkdir(parents=True, exist_ok=True)

    save_path.write_text(report, encoding="utf-8")
    logger.info("诊断报告已导出至: %s", save_path)
    return save_path