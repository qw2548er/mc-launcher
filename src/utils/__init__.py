"""工具模块。"""

from .logger import setup_logging, get_logger
from .config import ConfigManager
from .file_utils import (
    ensure_directory, read_json, write_json, calculate_sha1,
    safe_copy as copy_file, safe_delete as safe_remove,
    get_file_size, format_file_size as format_size,
)
from .crash_handler import (
    CrashReporter, install_exception_hook, generate_diagnostic_report,
    export_diagnostic_report, get_launcher_version,
)
from .updater import UpdateChecker, UpdateInfo
from .backup import BackupManager

__all__ = [
    "setup_logging",
    "get_logger",
    "ConfigManager",
    "ensure_directory",
    "read_json",
    "write_json",
    "calculate_sha1",
    "copy_file",
    "safe_remove",
    "get_file_size",
    "format_size",
    "CrashReporter",
    "install_exception_hook",
    "generate_diagnostic_report",
    "export_diagnostic_report",
    "get_launcher_version",
    "UpdateChecker",
    "UpdateInfo",
    "BackupManager",
]
