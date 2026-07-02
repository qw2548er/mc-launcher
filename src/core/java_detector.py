"""Java 环境检测模块。

自动扫描系统中已安装的 Java 运行时，验证版本兼容性。
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Minecraft 版本与最低 Java 版本的映射
# 格式: (Minecraft 版本起点, Java 主版本号)
MC_JAVA_REQUIREMENTS: list[tuple[int, int, int, int]] = [
    # (主版本, 次版本, 所需 Java 主版本)
    (1, 21, 0, 21),  # 1.21+ 需要 Java 21
    (1, 20, 5, 21),  # 1.20.5+ 需要 Java 21
    (1, 18, 0, 17),  # 1.18+ 需要 Java 17
    (1, 17, 0, 17),  # 1.17+ 需要 Java 17
    (1, 0, 0, 8),  # 1.0+ 需要 Java 8
]

# Windows 下常见的 Java 搜索路径
_WINDOWS_SEARCH_PATHS: list[str] = [
    r"C:\Program Files\Java",
    r"C:\Program Files (x86)\Java",
    r"C:\Program Files\Eclipse Adoptium",
    r"C:\Program Files\Eclipse Foundation",
    r"C:\Program Files\Microsoft",
    r"C:\Program Files\Zulu",
    r"C:\Program Files\BellSoft",
]

# Linux 下常见的 Java 搜索路径
_LINUX_SEARCH_PATHS: list[str] = [
    "/usr/lib/jvm",
    "/usr/java",
    "/usr/local/java",
    "/usr/local/lib/jvm",
    "/opt/java",
]


class JavaInfo:
    """Java 运行时信息。"""

    def __init__(
        self,
        path: Path,
        version: str,
        major_version: int,
        is_64bit: bool = True,
    ) -> None:
        self.path: Path = path
        self.version: str = version
        self.major_version: int = major_version
        self.is_64bit: bool = is_64bit

    def __repr__(self) -> str:
        return (
            f"JavaInfo(path={self.path!r}, version={self.version!r}, "
            f"major={self.major_version}, 64bit={self.is_64bit})"
        )

    def __str__(self) -> str:
        arch = "64-bit" if self.is_64bit else "32-bit"
        return f"Java {self.version} ({arch}) - {self.path}"


class JavaDetector:
    """Java 运行时检测器。"""

    def __init__(self) -> None:
        self._java_list: list[JavaInfo] = []
        self._scanned: bool = False

    # ── 扫描接口 ──────────────────────────────────────────────

    def scan(self) -> list[JavaInfo]:
        """扫描系统中所有可用的 Java 运行时。

        Returns:
            JavaInfo 列表，按版本从高到低排序
        """
        self._java_list.clear()
        found_paths: set[Path] = set()

        # 1. 检查 PATH 中的 java
        path_java = self._find_in_path()
        if path_java and path_java not in found_paths:
            info = self._parse_java_info(path_java)
            if info:
                self._java_list.append(info)
                found_paths.add(path_java)

        # 2. 检查 JAVA_HOME 环境变量
        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            java_exe = self._get_java_executable(Path(java_home))
            if java_exe and java_exe not in found_paths:
                info = self._parse_java_info(java_exe)
                if info:
                    self._java_list.append(info)
                    found_paths.add(java_exe)

        # 3. 扫描常见安装目录
        search_paths = _WINDOWS_SEARCH_PATHS if sys.platform == "win32" else _LINUX_SEARCH_PATHS
        for search_dir in search_paths:
            sp = Path(search_dir)
            if not sp.is_dir():
                continue
            for java_exe in self._scan_directory(sp):
                if java_exe not in found_paths:
                    info = self._parse_java_info(java_exe)
                    if info:
                        self._java_list.append(info)
                        found_paths.add(java_exe)

        # 按版本降序排列
        self._java_list.sort(key=lambda j: j.major_version, reverse=True)
        self._scanned = True

        logger.info(
            "Java 扫描完成，找到 %d 个 Java 运行时",
            len(self._java_list),
        )
        for j in self._java_list:
            logger.debug("  %s", j)

        return self._java_list

    def get_all(self) -> list[JavaInfo]:
        """获取已扫描的所有 Java 运行时。"""
        if not self._scanned:
            self.scan()
        return self._java_list

    def get_best_match(self, mc_version: str) -> Optional[JavaInfo]:
        """获取与指定 Minecraft 版本最匹配的 Java 运行时。

        优先选择满足最低版本要求的最新 Java。

        Args:
            mc_version: Minecraft 版本号，如 "1.20.4"

        Returns:
            匹配的 JavaInfo，如果没有找到返回 None
        """
        min_java = self._get_min_java_version(mc_version)
        if not self._scanned:
            self.scan()

        for java in self._java_list:
            if java.major_version >= min_java:
                logger.info(
                    "为 MC %s 选择 Java %d: %s",
                    mc_version,
                    java.major_version,
                    java.path,
                )
                return java

        logger.warning("未找到满足 MC %s 要求的 Java (需要 >= %d)", mc_version, min_java)
        return None

    # ── 手动指定 ──────────────────────────────────────────────

    def check_java(self, java_path: Path) -> Optional[JavaInfo]:
        """检查手动指定的 Java 路径是否有效。

        Args:
            java_path: Java 可执行文件路径或 JAVA_HOME 目录

        Returns:
            JavaInfo 如果有效，否则 None
        """
        if java_path.is_dir():
            java_exe = self._get_java_executable(java_path)
        else:
            java_exe = java_path

        if java_exe is None or not java_exe.is_file():
            logger.error("指定的 Java 路径无效: %s", java_path)
            return None

        info = self._parse_java_info(java_exe)
        if info is None:
            logger.error("无法解析 Java 版本信息: %s", java_exe)
            return None

        return info

    def is_compatible(self, java_info: JavaInfo, mc_version: str) -> bool:
        """检查 Java 版本是否兼容指定的 Minecraft 版本。

        Args:
            java_info: Java 信息
            mc_version: Minecraft 版本号

        Returns:
            True 表示兼容
        """
        min_java = self._get_min_java_version(mc_version)
        compatible = java_info.major_version >= min_java
        if not compatible:
            logger.warning(
                "Java %d 不兼容 MC %s（需要 >= %d）",
                java_info.major_version,
                mc_version,
                min_java,
            )
        return compatible

    # ── 内部方法 ──────────────────────────────────────────────

    @staticmethod
    def _get_java_executable(java_home: Path) -> Optional[Path]:
        """从 JAVA_HOME 目录获取 Java 可执行文件路径。"""
        exe_name = "javaw.exe" if sys.platform == "win32" else "java"
        exe_path = java_home / "bin" / exe_name
        if exe_path.is_file():
            return exe_path
        # 某些发行版路径不同
        exe_path = java_home / "bin" / "java"
        if exe_path.is_file():
            return exe_path
        return None

    @staticmethod
    def _find_in_path() -> Optional[Path]:
        """在系统 PATH 中查找 java。"""
        exe_name = "javaw.exe" if sys.platform == "win32" else "java"
        found = shutil.which(exe_name)
        if found:
            return Path(found)
        # 回退到 java
        found = shutil.which("java")
        return Path(found) if found else None

    @staticmethod
    def _scan_directory(search_dir: Path) -> list[Path]:
        """递归扫描目录下的 Java 可执行文件。"""
        results: list[Path] = []
        exe_name = "javaw.exe" if sys.platform == "win32" else "java"
        try:
            for root, _dirs, files in os.walk(search_dir):
                if exe_name in files:
                    results.append(Path(root) / exe_name)
                elif "java" in files:
                    results.append(Path(root) / "java")
        except OSError:
            pass
        return results

    @staticmethod
    def _parse_java_info(java_exe: Path) -> Optional[JavaInfo]:
        """解析 Java 版本信息。

        Args:
            java_exe: Java 可执行文件路径

        Returns:
            JavaInfo，解析失败返回 None
        """
        try:
            result = subprocess.run(
                [str(java_exe), "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # java -version 输出到 stderr
            output = result.stderr or result.stdout

            # 解析版本字符串，格式如:
            # java version "1.8.0_401"
            # java version "17.0.10" 2024-01-16 LTS
            # openjdk version "21.0.2" 2024-01-16
            # openjdk version "21.0.6" 2025-01-21 LTS
            version_match = re.search(r'version\s+"([^"]+)"', output)
            if not version_match:
                logger.error("无法解析 Java 版本输出: %s", output[:200])
                return None

            version_str = version_match.group(1)

            # 解析主版本号
            major_version = JavaDetector._parse_major_version(version_str)

            # 检查是否为 64 位
            is_64bit = "64-Bit" in output or "64-bit" in output

            logger.debug(
                "检测到 Java: %s -> version=%s, major=%d, 64bit=%s",
                java_exe,
                version_str,
                major_version,
                is_64bit,
            )

            return JavaInfo(
                path=java_exe,
                version=version_str,
                major_version=major_version,
                is_64bit=is_64bit,
            )
        except subprocess.TimeoutExpired:
            logger.error("执行 %s -version 超时", java_exe)
            return None
        except OSError as e:
            logger.error("执行 %s 失败: %s", java_exe, e)
            return None

    @staticmethod
    def _parse_major_version(version_str: str) -> int:
        """从版本字符串解析主版本号。

        支持格式:
            "1.8.0_401" -> 8
            "17.0.10"   -> 17
            "21.0.2"    -> 21
        """
        parts = version_str.split(".")
        if parts[0] == "1":
            # Java 8 及以下
            return int(parts[1])
        return int(parts[0])

    @staticmethod
    def _get_min_java_version(mc_version: str) -> int:
        """根据 Minecraft 版本号获取最低 Java 主版本要求。

        Args:
            mc_version: Minecraft 版本号，如 "1.20.4"

        Returns:
            Java 主版本号
        """
        try:
            parts = mc_version.split(".")
            major = int(parts[0]) if len(parts) > 0 else 1
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            logger.warning("无法解析 MC 版本号: %s，默认要求 Java 8", mc_version)
            return 8

        for req_major, req_minor, req_patch, java_ver in MC_JAVA_REQUIREMENTS:
            if (major, minor, patch) >= (req_major, req_minor, req_patch):
                return java_ver

        return 8  # 默认最低 Java 8