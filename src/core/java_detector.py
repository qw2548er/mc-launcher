"""Java 环境检测模块。

自动扫描系统中已安装的 Java 运行时，验证版本兼容性，支持缓存检测结果。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

CACHE_FILE = Path.home() / ".minecraft_launcher" / "java_cache.json"
CACHE_TTL = 3600

MC_JAVA_REQUIREMENTS: list[tuple[int, int, int, int]] = [
    (1, 21, 0, 21),
    (1, 20, 5, 21),
    (1, 17, 0, 17),
    (1, 0, 0, 8),
]

_WINDOWS_SEARCH_PATHS: list[str] = [
    r"C:\Program Files\Java",
    r"C:\Program Files (x86)\Java",
    r"C:\Program Files\Eclipse Adoptium",
    r"C:\Program Files\Eclipse Foundation",
    r"C:\Program Files\Microsoft",
    r"C:\Program Files\Zulu",
    r"C:\Program Files\BellSoft",
    r"C:\Program Files\Amazon Corretto",
    r"C:\Program Files\ojdkbuild",
    r"C:\Program Files\SapMachine",
    str(Path.home() / "AppData" / "Local" / "Programs" / "Eclipse Adoptium"),
    str(Path.home() / "AppData" / "Local" / "Programs" / "Java"),
    str(Path.home() / ".jdks"),
    str(Path.home() / "scoop" / "apps"),
]

_LINUX_SEARCH_PATHS: list[str] = [
    "/usr/lib/jvm",
    "/usr/java",
    "/usr/local/java",
    "/usr/local/lib/jvm",
    "/opt/java",
    "/opt/jdk",
    str(Path.home() / ".jdks"),
    str(Path.home() / ".sdkman" / "candidates" / "java"),
]

_MACOS_SEARCH_PATHS: list[str] = [
    "/Library/Java/JavaVirtualMachines",
    str(Path.home() / "Library" / "Java" / "JavaVirtualMachines"),
    "/opt/homebrew/opt/openjdk/bin",
    str(Path.home() / ".jdks"),
    str(Path.home() / ".sdkman" / "candidates" / "java"),
]

_JAVA_VENDORS = {
    "adoptium": "Eclipse Adoptium (Temurin)",
    "temurin": "Eclipse Adoptium (Temurin)",
    "hotspot": "HotSpot",
    "openjdk": "OpenJDK",
    "oracle": "Oracle",
    "corretto": "Amazon Corretto",
    "zulu": "Azul Zulu",
    "microsoft": "Microsoft",
    "bellsoft": "BellSoft Liberica",
    "sapmachine": "SapMachine",
    "graalvm": "GraalVM",
    "jetbrains": "JetBrains Runtime",
    "ibm": "IBM",
}


@dataclass
class JavaInfo:
    path: Path
    version: str
    major_version: int
    is_64bit: bool = True
    vendor: str = "Unknown"
    arch: str = "x86_64"
    is_valid: bool = True
    java_home: Path = field(default=None)

    def __post_init__(self):
        if self.java_home is None:
            self.java_home = self.path.parent.parent

    def __repr__(self) -> str:
        return (
            f"JavaInfo(path={self.path!r}, version={self.version!r}, "
            f"major={self.major_version}, vendor={self.vendor}, 64bit={self.is_64bit})"
        )

    def __str__(self) -> str:
        arch = "64-bit" if self.is_64bit else "32-bit"
        return f"Java {self.major_version} ({self.version}) - {self.vendor} {arch}"

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "version": self.version,
            "major_version": self.major_version,
            "is_64bit": self.is_64bit,
            "vendor": self.vendor,
            "arch": self.arch,
            "is_valid": self.is_valid,
            "java_home": str(self.java_home),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JavaInfo":
        return cls(
            path=Path(data["path"]),
            version=data["version"],
            major_version=data["major_version"],
            is_64bit=data.get("is_64bit", True),
            vendor=data.get("vendor", "Unknown"),
            arch=data.get("arch", "x86_64"),
            is_valid=data.get("is_valid", True),
            java_home=Path(data["java_home"]) if data.get("java_home") else None,
        )


class JavaDetector:
    def __init__(self) -> None:
        self._java_list: list[JavaInfo] = []
        self._custom_java_paths: list[Path] = []
        self._scanned: bool = False
        self._last_scan_time: float = 0

    def scan(self, force: bool = False) -> list[JavaInfo]:
        if not force and self._scanned and (time.time() - self._last_scan_time) < 300:
            return self._java_list

        cached = self._load_cache()
        if not force and cached:
            self._java_list = cached
            self._scanned = True
            self._last_scan_time = time.time()
            logger.info("从缓存加载 %d 个 Java 运行时", len(self._java_list))
            return self._java_list

        self._java_list.clear()
        found_paths: set[Path] = set()

        self._scan_bundled_jres(found_paths)

        path_java = self._find_in_path()
        if path_java and path_java not in found_paths:
            info = self._parse_java_info(path_java)
            if info and info.is_valid:
                self._java_list.append(info)
                found_paths.add(path_java)

        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            java_exe = self._get_java_executable(Path(java_home))
            if java_exe and java_exe not in found_paths:
                info = self._parse_java_info(java_exe)
                if info and info.is_valid:
                    self._java_list.append(info)
                    found_paths.add(java_exe)

        if sys.platform == "win32":
            for java_exe in self._scan_windows_registry():
                if java_exe not in found_paths:
                    info = self._parse_java_info(java_exe)
                    if info and info.is_valid:
                        self._java_list.append(info)
                        found_paths.add(java_exe)

        search_paths = self._get_search_paths()
        for search_dir in search_paths:
            sp = Path(search_dir)
            if not sp.is_dir():
                continue
            for java_exe in self._scan_directory(sp):
                if java_exe not in found_paths:
                    info = self._parse_java_info(java_exe)
                    if info and info.is_valid:
                        self._java_list.append(info)
                        found_paths.add(java_exe)

        for custom_path in self._custom_java_paths:
            if custom_path not in found_paths:
                info = self._parse_java_info(custom_path)
                if info and info.is_valid:
                    self._java_list.append(info)
                    found_paths.add(custom_path)

        self._java_list.sort(key=lambda j: j.major_version, reverse=True)
        self._scanned = True
        self._last_scan_time = time.time()
        self._save_cache()

        logger.info(
            "Java 扫描完成，找到 %d 个 Java 运行时",
            len(self._java_list),
        )
        for j in self._java_list:
            logger.debug("  %s", j)

        return self._java_list

    def get_all(self) -> list[JavaInfo]:
        if not self._scanned:
            self.scan()
        return self._java_list

    def add_custom_java(self, java_path: Path) -> Optional[JavaInfo]:
        info = self.check_java(java_path)
        if info and info.is_valid:
            if not any(j.path == info.path for j in self._java_list):
                self._java_list.append(info)
                self._java_list.sort(key=lambda j: j.major_version, reverse=True)
                self._save_cache()
            return info
        return None

    def remove_java(self, java_path: Path) -> bool:
        for i, j in enumerate(self._java_list):
            if j.path == java_path:
                self._java_list.pop(i)
                self._save_cache()
                return True
        return False

    def get_best_match(self, mc_version: str) -> Optional[JavaInfo]:
        min_java = self._get_min_java_version(mc_version)
        if not self._scanned:
            self.scan()

        bundled = self._get_best_bundled_jre(mc_version)
        if bundled:
            return bundled

        for java in self._java_list:
            if java.major_version >= min_java and java.is_64bit and not self._is_bundled_path(java.path):
                logger.info(
                    "为 MC %s 选择 Java %d (%s): %s",
                    mc_version,
                    java.major_version,
                    java.vendor,
                    java.path,
                )
                return java

        for java in self._java_list:
            if java.major_version >= min_java and not self._is_bundled_path(java.path):
                logger.info(
                    "为 MC %s 选择 Java %d (%s): %s",
                    mc_version,
                    java.major_version,
                    java.vendor,
                    java.path,
                )
                return java

        for java in self._java_list:
            if java.major_version >= min_java and java.is_64bit:
                return java

        for java in self._java_list:
            if java.major_version >= min_java:
                return java

        logger.warning("未找到满足 MC %s 要求的 Java (需要 >= %d)", mc_version, min_java)
        return None

    def check_java(self, java_path: Path) -> Optional[JavaInfo]:
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
        compatible, _ = self.check_compatibility(java_info, mc_version)
        return compatible

    def check_compatibility(self, java_info: JavaInfo, mc_version: str) -> tuple[bool, str]:
        min_java = self._get_min_java_version(mc_version)
        compatible = True
        reasons: list[str] = []

        if java_info.major_version < min_java:
            compatible = False
            reasons.append(f"需要 Java {min_java} 或更高版本")

        if not java_info.is_64bit:
            compatible = False
            reasons.append("需要 64 位 Java")

        return compatible, "; ".join(reasons) if reasons else "兼容"

    @staticmethod
    def get_java_download_url(major_version: int) -> str:
        if sys.platform == "win32":
            os_name = "win"
            ext = ".msi"
        elif sys.platform == "darwin":
            os_name = "mac"
            ext = ".pkg"
        else:
            os_name = "linux"
            ext = ".tar.gz"

        arch = "x64"
        if sys.platform == "darwin" and "arm64" in os.uname().machine:
            arch = "aarch64"
        elif sys.platform == "win32" and "ARM64" in os.environ.get("PROCESSOR_ARCHITECTURE", ""):
            arch = "aarch64"
        elif "aarch64" in os.uname().machine or "arm64" in os.uname().machine:
            arch = "aarch64"

        base_url = f"https://adoptium.net/temurin/releases/?version={major_version}&os={os_name}&arch={arch}&package=jdk"
        return base_url

    @staticmethod
    def get_required_java_version(mc_version: str) -> int:
        return JavaDetector._get_min_java_version(mc_version)

    def _scan_bundled_jres(self, found_paths: set[Path]) -> None:
        try:
            from src.core.bundled_jre import get_bundled_jre_manager
            mgr = get_bundled_jre_manager()
            for jre_info in mgr.get_installed_jres():
                if jre_info.java_exe and jre_info.java_exe not in found_paths:
                    info = self._parse_java_info(jre_info.java_exe)
                    if info and info.is_valid:
                        info.vendor = "内置 JRE"
                        self._java_list.append(info)
                        found_paths.add(jre_info.java_exe)
                        logger.debug("内置 JRE 已加载: %s -> %s", jre_info.jre_id, jre_info.java_exe)
        except Exception as e:
            logger.debug("扫描内置 JRE 失败: %s", e)

    def _get_best_bundled_jre(self, mc_version: str) -> Optional[JavaInfo]:
        try:
            from src.core.bundled_jre import get_bundled_jre_manager
            mgr = get_bundled_jre_manager()
            best = mgr.get_best_jre_for_version(mc_version)
            if best and best.java_exe:
                for java in self._java_list:
                    if java.path == best.java_exe:
                        logger.info(
                            "为 MC %s 优先选择内置 JRE %d: %s",
                            mc_version, best.major_version, best.java_exe,
                        )
                        return java
                info = self.check_java(best.java_exe)
                if info:
                    info.vendor = "内置 JRE"
                    return info
        except Exception as e:
            logger.debug("获取最佳内置 JRE 失败: %s", e)
        return None

    @staticmethod
    def _is_bundled_path(path: Path) -> bool:
        try:
            from src.core.bundled_jre import get_bundle_jre_dir
            jre_dir = get_bundle_jre_dir()
            try:
                path.resolve().relative_to(jre_dir.resolve())
                return True
            except ValueError:
                return False
        except Exception:
            return False

    def _get_search_paths(self) -> list[str]:
        if sys.platform == "win32":
            return _WINDOWS_SEARCH_PATHS
        elif sys.platform == "darwin":
            return _MACOS_SEARCH_PATHS
        else:
            return _LINUX_SEARCH_PATHS

    @staticmethod
    def _get_java_executable(java_home: Path) -> Optional[Path]:
        if sys.platform == "win32":
            exe_names = ["java.exe", "javaw.exe"]
        else:
            exe_names = ["java"]

        bin_dir = java_home / "Contents" / "Home" / "bin" if sys.platform == "darwin" else java_home / "bin"

        for exe_name in exe_names:
            exe_path = bin_dir / exe_name
            if exe_path.is_file():
                return exe_path

        return None

    @staticmethod
    def _find_in_path() -> Optional[Path]:
        exe_names = ["java.exe", "javaw.exe"] if sys.platform == "win32" else ["java"]
        for exe_name in exe_names:
            found = shutil.which(exe_name)
            if found:
                return Path(found)
        return None

    @staticmethod
    def _scan_directory(search_dir: Path) -> list[Path]:
        results: list[Path] = []
        exe_names = ["java.exe", "javaw.exe"] if sys.platform == "win32" else ["java"]
        max_depth = 5

        def _scan(current: Path, depth: int):
            if depth > max_depth:
                return
            try:
                for item in current.iterdir():
                    if item.is_dir():
                        if item.name in ["bin", "jre"]:
                            for exe_name in exe_names:
                                exe_path = item / exe_name
                                if exe_path.is_file():
                                    results.append(exe_path)
                                    break
                            else:
                                _scan(item, depth + 1)
                        else:
                            _scan(item, depth + 1)
            except OSError:
                pass

        _scan(search_dir, 0)
        return results

    @staticmethod
    def _scan_windows_registry() -> list[Path]:
        results: list[Path] = []
        if sys.platform != "win32":
            return results

        try:
            import winreg
        except ImportError:
            return results

        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\Java Runtime Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\Java Development Kit"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eclipse Adoptium\JDK"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eclipse Foundation\JDK"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\JDK"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Azul Systems\Zulu"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BellSoft\Liberica"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Amazon Corretto"),
        ]

        for hkey, reg_path in reg_paths:
            try:
                with winreg.OpenKey(hkey, reg_path) as key:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                try:
                                    java_home, _ = winreg.QueryValueEx(subkey, "JavaHome")
                                    java_home = winreg.QueryValueEx(subkey, "Path")[0] if "Path" in [winreg.EnumValue(subkey, j)[0] for j in range(winreg.QueryInfoKey(subkey)[1])] else java_home
                                    java_exe = Path(java_home) / "bin" / "java.exe"
                                    if java_exe.is_file():
                                        results.append(java_exe)
                                except OSError:
                                    pass
                            i += 1
                        except OSError:
                            break
            except OSError:
                continue

        for env_java in [os.environ.get("JAVA_HOME"), os.environ.get("JRE_HOME"), os.environ.get("JDK_HOME")]:
            if env_java:
                java_exe = Path(env_java) / "bin" / "java.exe"
                if java_exe.is_file() and java_exe not in results:
                    results.append(java_exe)

        return results

    @staticmethod
    def _parse_java_info(java_exe: Path) -> Optional[JavaInfo]:
        try:
            result = subprocess.run(
                [str(java_exe), "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                errors="replace",
            )
            output = result.stderr or result.stdout or result.stdout
            if result.returncode != 0 and not output:
                return None

            version_match = re.search(r'version\s+"([^"]+)"', output)
            if not version_match:
                logger.error("无法解析 Java 版本输出: %s", output[:200])
                return None

            version_str = version_match.group(1)
            major_version = JavaDetector._parse_major_version(version_str)

            is_64bit = "64-Bit" in output or "64-bit" in output or "x86_64" in output or "amd64" in output
            arch = "x86_64" if is_64bit else "x86"
            if "aarch64" in output or "arm64" in output or "ARM" in output:
                arch = "aarch64"
                is_64bit = True

            vendor = JavaDetector._detect_vendor(output, java_exe)

            logger.debug(
                "检测到 Java: %s -> version=%s, major=%d, vendor=%s, arch=%s",
                java_exe,
                version_str,
                major_version,
                vendor,
                arch,
            )

            java_home = java_exe.parent.parent
            if sys.platform == "darwin" and "Contents/Home" in str(java_exe):
                java_home = java_exe.parents[2]

            return JavaInfo(
                path=java_exe,
                version=version_str,
                major_version=major_version,
                is_64bit=is_64bit,
                vendor=vendor,
                arch=arch,
                is_valid=True,
                java_home=java_home,
            )
        except subprocess.TimeoutExpired:
            logger.error("执行 %s -version 超时", java_exe)
            return None
        except OSError as e:
            logger.error("执行 %s 失败: %s", java_exe, e)
            return None

    @staticmethod
    def _detect_vendor(output: str, java_path: Path) -> str:
        output_lower = output.lower()
        path_lower = str(java_path).lower()

        for keyword, vendor_name in _JAVA_VENDORS.items():
            if keyword in output_lower or keyword in path_lower:
                return vendor_name

        vm_match = re.search(r'(HotSpot|OpenJ9|GraalVM|Dalvik|JET)', output, re.IGNORECASE)
        if vm_match:
            return vm_match.group(1)

        if "openjdk" in output_lower:
            return "OpenJDK"

        return "Unknown"

    @staticmethod
    def _parse_major_version(version_str: str) -> int:
        if version_str.startswith("1."):
            parts = version_str.split(".")
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    pass

        parts = version_str.split(".")
        try:
            return int(parts[0])
        except (ValueError, IndexError):
            pass

        match = re.match(r'^(\d+)', version_str)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

        logger.warning("无法解析主版本号: %s，默认返回 8", version_str)
        return 8

    @staticmethod
    def _get_min_java_version(mc_version: str) -> int:
        try:
            clean_ver = mc_version.split("-")[0].split("+")[0]
            parts = clean_ver.split(".")
            major = int(parts[0]) if len(parts) > 0 else 1
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            logger.warning("无法解析 MC 版本号: %s，默认要求 Java 8", mc_version)
            return 8

        for req_major, req_minor, req_patch, java_ver in MC_JAVA_REQUIREMENTS:
            if (major, minor, patch) >= (req_major, req_minor, req_patch):
                return java_ver

        return 8

    def _load_cache(self) -> Optional[list[JavaInfo]]:
        try:
            if not CACHE_FILE.exists():
                return None

            cache_age = time.time() - CACHE_FILE.stat().st_mtime
            if cache_age > CACHE_TTL:
                return None

            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            java_list = []
            for item in data.get("java_list", []):
                try:
                    java_info = JavaInfo.from_dict(item)
                    if java_info.path.is_file():
                        java_list.append(java_info)
                except Exception:
                    continue

            if not java_list:
                return None

            return java_list
        except Exception as e:
            logger.debug("加载 Java 缓存失败: %s", e)
            return None

    def _save_cache(self) -> None:
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_scan": time.time(),
                "java_list": [j.to_dict() for j in self._java_list],
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug("保存 Java 缓存失败: %s", e)

    def clear_cache(self) -> None:
        self._scanned = False
        self._java_list.clear()
        try:
            if CACHE_FILE.exists():
                CACHE_FILE.unlink()
        except Exception:
            pass
