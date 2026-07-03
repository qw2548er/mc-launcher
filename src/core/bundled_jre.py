"""内置 JRE (Bundle JRE) 管理模块。

管理启动器内置的 JRE 运行时，支持版本匹配、自动检测、下载状态跟踪。
内置 JRE 版本：jre8(1.8.0_442)、jre11(11.0.23)、jre17(17.0.10)、jre21(21.0.1)、jre25(25.0.3)
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.file_utils import ensure_directory

logger = logging.getLogger(__name__)


BUNDLED_JRES: list[dict] = [
    {
        "id": "jre8",
        "major_version": 8,
        "version_str": "1.8.0_442",
        "display_name": "JRE 8 (内置)",
        "description": "适用于 Minecraft 1.16.5 及以下版本",
        "min_mc": (1, 0, 0),
        "max_mc": (1, 16, 5),
        "folder_name": "jre8",
    },
    {
        "id": "jre11",
        "major_version": 11,
        "version_str": "11.0.23",
        "display_name": "JRE 11 (内置)",
        "description": "适用于 Minecraft 1.17",
        "min_mc": (1, 17, 0),
        "max_mc": (1, 17, 1),
        "folder_name": "jre11",
    },
    {
        "id": "jre17",
        "major_version": 17,
        "version_str": "17.0.10",
        "display_name": "JRE 17 (内置)",
        "description": "适用于 Minecraft 1.17.1 - 1.20.4",
        "min_mc": (1, 17, 1),
        "max_mc": (1, 20, 4),
        "folder_name": "jre17",
    },
    {
        "id": "jre21",
        "major_version": 21,
        "version_str": "21.0.1",
        "display_name": "JRE 21 (内置)",
        "description": "适用于 Minecraft 1.20.5 - 1.21.4",
        "min_mc": (1, 20, 5),
        "max_mc": (1, 21, 4),
        "folder_name": "jre21",
    },
    {
        "id": "jre25",
        "major_version": 25,
        "version_str": "25.0.3",
        "display_name": "JRE 25 (内置)",
        "description": "适用于 Minecraft 1.21.5+",
        "min_mc": (1, 21, 5),
        "max_mc": (99, 99, 99),
        "folder_name": "jre25",
    },
]


def _get_app_base_dir() -> Path:
    """获取应用程序基础目录（exe或脚本所在目录）。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def get_bundle_jre_dir() -> Path:
    """获取内置 JRE 存储目录。"""
    base = _get_app_base_dir()
    jre_dir = base / "jre"
    ensure_directory(jre_dir)
    return jre_dir


@dataclass
class BundledJreInfo:
    """内置 JRE 信息。"""
    jre_id: str
    major_version: int
    version_str: str
    display_name: str
    description: str
    folder_name: str
    min_mc: tuple
    max_mc: tuple
    is_installed: bool = False
    java_exe: Optional[Path] = None

    @property
    def is_bundled(self) -> bool:
        return True

    def is_compatible_with_mc(self, mc_version: str) -> bool:
        """检查是否兼容指定 MC 版本。"""
        try:
            parts = mc_version.split("-")[0].split("+")[0].split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            ver_tuple = (major, minor, patch)
            return self.min_mc <= ver_tuple <= self.max_mc
        except (ValueError, IndexError):
            return self.major_version >= 17

    def to_java_info_path(self) -> Optional[Path]:
        """返回可用于 JavaDetector.check_java() 的路径。"""
        return self.java_exe


class BundledJreManager:
    """内置 JRE 管理器。"""

    def __init__(self) -> None:
        self._jre_dir = get_bundle_jre_dir()
        self._installed: dict[str, BundledJreInfo] = {}
        self._scan()

    def _scan(self) -> None:
        """扫描内置 JRE 目录，检测已安装的 JRE。"""
        self._installed.clear()

        for jre_def in BUNDLED_JRES:
            info = BundledJreInfo(
                jre_id=jre_def["id"],
                major_version=jre_def["major_version"],
                version_str=jre_def["version_str"],
                display_name=jre_def["display_name"],
                description=jre_def["description"],
                folder_name=jre_def["folder_name"],
                min_mc=jre_def["min_mc"],
                max_mc=jre_def["max_mc"],
            )

            jre_path = self._jre_dir / jre_def["folder_name"]
            java_exe = self._find_java_exe(jre_path)
            if java_exe and java_exe.is_file():
                info.is_installed = True
                info.java_exe = java_exe
                self._installed[jre_def["id"]] = info
                logger.debug("检测到内置 JRE: %s -> %s", jre_def["id"], java_exe)
            else:
                self._installed[jre_def["id"]] = info

    @staticmethod
    def _find_java_exe(jre_home: Path) -> Optional[Path]:
        """在 JRE 目录中查找 java 可执行文件。"""
        if sys.platform == "win32":
            exe_name = "java.exe"
        else:
            exe_name = "java"

        candidates = [
            jre_home / "bin" / exe_name,
            jre_home / "jre" / "bin" / exe_name,
        ]

        if sys.platform == "darwin":
            candidates.insert(0, jre_home / "Contents" / "Home" / "bin" / exe_name)

        for candidate in candidates:
            if candidate.is_file():
                return candidate

        if jre_home.is_dir():
            try:
                for sub in jre_home.iterdir():
                    if sub.is_dir():
                        found = BundledJreManager._find_java_exe(sub)
                        if found:
                            return found
            except OSError:
                pass

        return None

    def get_all_jres(self) -> list[BundledJreInfo]:
        """获取所有内置 JRE 列表（含未安装的）。"""
        result = []
        for jre_def in BUNDLED_JRES:
            jre_id = jre_def["id"]
            if jre_id in self._installed:
                result.append(self._installed[jre_id])
            else:
                result.append(BundledJreInfo(
                    jre_id=jre_def["id"],
                    major_version=jre_def["major_version"],
                    version_str=jre_def["version_str"],
                    display_name=jre_def["display_name"],
                    description=jre_def["description"],
                    folder_name=jre_def["folder_name"],
                    min_mc=jre_def["min_mc"],
                    max_mc=jre_def["max_mc"],
                ))
        return result

    def get_installed_jres(self) -> list[BundledJreInfo]:
        """获取已安装的内置 JRE 列表。"""
        return [j for j in self._installed.values() if j.is_installed]

    def get_jre_by_id(self, jre_id: str) -> Optional[BundledJreInfo]:
        """根据 ID 获取 JRE 信息。"""
        return self._installed.get(jre_id)

    def get_best_jre_for_version(self, mc_version: str) -> Optional[BundledJreInfo]:
        """根据 MC 版本获取最佳匹配的已安装内置 JRE。"""
        candidates = []
        for jre in self._installed.values():
            if jre.is_installed and jre.is_compatible_with_mc(mc_version):
                candidates.append(jre)

        if not candidates:
            for jre in self._installed.values():
                if jre.is_installed:
                    try:
                        parts = mc_version.split("-")[0].split("+")[0].split(".")
                        major = int(parts[0])
                        minor = int(parts[1]) if len(parts) > 1 else 0
                        ver_tuple = (major, minor, 0)
                        if ver_tuple >= (1, 21) and jre.major_version >= 21:
                            candidates.append(jre)
                        elif ver_tuple >= (1, 17) and jre.major_version >= 17:
                            candidates.append(jre)
                    except (ValueError, IndexError):
                        pass

        if not candidates:
            installed = self.get_installed_jres()
            if installed:
                candidates = [max(installed, key=lambda j: j.major_version)]

        if candidates:
            preferred = [j for j in candidates if j.major_version >= 21]
            if preferred:
                return max(preferred, key=lambda j: j.major_version)
            return max(candidates, key=lambda j: j.major_version)
        return None

    def get_jre_dir(self) -> Path:
        """获取 JRE 存储目录。"""
        return self._jre_dir

    def is_jre_installed(self, jre_id: str) -> bool:
        """检查指定 JRE 是否已安装。"""
        jre = self._installed.get(jre_id)
        return jre is not None and jre.is_installed

    def rescan(self) -> None:
        """重新扫描 JRE 目录。"""
        self._scan()


_bundle_manager_instance: Optional[BundledJreManager] = None


def get_bundled_jre_manager() -> BundledJreManager:
    """获取 BundledJreManager 单例。"""
    global _bundle_manager_instance
    if _bundle_manager_instance is None:
        _bundle_manager_instance = BundledJreManager()
    return _bundle_manager_instance
