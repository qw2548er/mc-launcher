"""游戏启动器核心模块。

负责组装启动参数、校验版本文件、启动 Minecraft 游戏进程。
支持日志捕获、进度回调、启动前检查等功能。
"""

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from src.core.account import AccountInfo
from src.core.java_detector import JavaDetector, JavaInfo
from src.utils.config import ConfigManager, get_config
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_JVM_ARGS: list[str] = [
    "-XX:+UseG1GC",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:G1NewSizePercent=20",
    "-XX:G1ReservePercent=20",
    "-XX:MaxGCPauseMillis=50",
    "-XX:G1HeapRegionSize=32M",
]

MAIN_CLASS = "net.minecraft.client.main.Main"
AUTH_SERVER = "https://authserver.mojang.com"


class LaunchError(Exception):
    """启动异常。"""
    pass


class LaunchCheckResult:
    """启动前检查结果。"""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def can_launch(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def get_error_message(self) -> str:
        return "\n".join(self.errors)

    def get_warning_message(self) -> str:
        return "\n".join(self.warnings)


class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"

    _PATTERN = re.compile(r"^\[(?P<time>[^\]]+)\]\s*\[(?P<thread>[^\]]+)/(?P<level>[A-Z]+)\]\s*(?P<message>.*)$")

    @classmethod
    def parse(cls, line: str) -> tuple[str, str, str, str]:
        match = cls._PATTERN.match(line)
        if match:
            return (
                match.group("time"),
                match.group("thread"),
                match.group("level"),
                match.group("message")
            )
        return ("", "", cls.INFO, line)


class GameLauncher:
    """Minecraft 游戏启动器。

    负责组装启动参数并启动游戏进程。
    支持日志捕获、进度回调、启动前检查等功能。
    """

    def __init__(self) -> None:
        self._config: ConfigManager = get_config()
        self._java_detector: JavaDetector = JavaDetector()
        self._process: Optional[subprocess.Popen] = None
        self._log_thread: Optional[threading.Thread] = None
        self._log_file: Optional[Path] = None
        self._log_queue: queue.Queue = queue.Queue()
        self._is_running: bool = False
        self._exit_code: Optional[int] = None
        self._version_id: str = ""
        self._on_log: Optional[Callable[[str, str], None]] = None
        self._on_exit: Optional[Callable[[int], None]] = None
        self._on_progress: Optional[Callable[[str], None]] = None
        self._stop_event = threading.Event()

    def launch(
        self,
        version_id: str,
        account: AccountInfo,
        java_path: Optional[Path] = None,
        min_memory_mb: Optional[int] = None,
        max_memory_mb: Optional[int] = None,
        extra_jvm_args: Optional[str] = None,
        window_width: Optional[int] = None,
        window_height: Optional[int] = None,
        fullscreen: Optional[bool] = None,
        game_dir: Optional[Path] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
        on_exit: Optional[Callable[[int], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        demo_mode: bool = False,
        server_address: Optional[str] = None,
        server_port: Optional[int] = None,
    ) -> subprocess.Popen:
        """启动 Minecraft 游戏。

        Args:
            version_id: 版本 ID
            account: 账号信息
            java_path: 手动指定 Java 路径
            min_memory_mb: 最小内存（MB）
            max_memory_mb: 最大内存（MB）
            extra_jvm_args: 额外 JVM 参数
            window_width: 窗口宽度
            window_height: 窗口高度
            fullscreen: 全屏模式
            game_dir: 游戏目录
            on_log: 日志回调 (line, level)
            on_exit: 进程退出回调 (exit_code)
            on_progress: 进度状态回调 (status_message)
            demo_mode: 演示模式
            server_address: 快速连接服务器地址
            server_port: 快速连接服务器端口

        Returns:
            游戏进程的 Popen 对象

        Raises:
            LaunchError: 启动失败
        """
        self._on_log = on_log
        self._on_exit = on_exit
        self._on_progress = on_progress
        self._version_id = version_id
        self._exit_code = None

        if game_dir is None:
            game_dir = Path(self._config.get("game_directory", str(Path.home() / ".minecraft")))
        game_dir = game_dir.resolve()

        if on_progress:
            on_progress("正在检查启动环境...")

        check_result = self.pre_check(version_id, game_dir, java_path, max_memory_mb)
        if not check_result.can_launch:
            raise LaunchError(check_result.get_error_message())

        if on_progress:
            on_progress("正在准备启动参数...")

        java_info = self._resolve_java(java_path, version_id)
        version_dir = game_dir / "versions" / version_id
        version_json = self._load_version_json(version_dir)
        if version_json is None:
            raise LaunchError(f"无法读取版本配置文件: {version_dir}")

        if on_progress:
            on_progress("正在验证版本文件...")

        self._verify_version_files(version_dir, version_json)

        if on_progress:
            on_progress("正在构建类路径...")

        classpath = self._build_classpath(game_dir, version_json)

        if on_progress:
            on_progress("正在准备 natives 库...")

        natives_dir = self._prepare_natives(game_dir, version_json)

        if on_progress:
            on_progress("正在组装 JVM 参数...")

        jvm_args = self._build_jvm_args(
            java_info=java_info,
            version_dir=version_dir,
            game_dir=game_dir,
            natives_dir=natives_dir,
            classpath=classpath,
            version_json=version_json,
            min_memory_mb=min_memory_mb,
            max_memory_mb=max_memory_mb,
            extra_jvm_args=extra_jvm_args,
        )

        if on_progress:
            on_progress("正在组装游戏参数...")

        mc_args = self._build_minecraft_args(
            account=account,
            version_json=version_json,
            game_dir=game_dir,
            window_width=window_width,
            window_height=window_height,
            fullscreen=fullscreen,
            demo_mode=demo_mode,
            server_address=server_address,
            server_port=server_port,
        )

        main_class = version_json.get("mainClass", MAIN_CLASS)
        command = [str(java_info.path)] + jvm_args + [main_class] + mc_args

        logger.info("启动 Minecraft %s", version_id)
        logger.debug("Java 路径: %s (版本 %d)", java_info.path, java_info.major_version)
        logger.debug("游戏目录: %s", game_dir)
        logger.debug("命令行长度: %d 个参数", len(command))

        if on_progress:
            on_progress("正在启动游戏进程...")

        self._setup_logging(game_dir, version_id)
        self._process = self._start_process(command, game_dir)
        self._is_running = True
        self._start_log_thread()
        self._start_monitor_thread()

        self._record_launch(version_id)

        if on_progress:
            on_progress("游戏已启动！")

        return self._process

    def pre_check(
        self,
        version_id: str,
        game_dir: Optional[Path] = None,
        java_path: Optional[Path] = None,
        max_memory_mb: Optional[int] = None,
    ) -> LaunchCheckResult:
        """启动前检查。

        Args:
            version_id: 版本 ID
            game_dir: 游戏目录
            java_path: Java 路径
            max_memory_mb: 最大内存设置

        Returns:
            LaunchCheckResult
        """
        result = LaunchCheckResult()

        if game_dir is None:
            game_dir = Path(self._config.get("game_directory", str(Path.home() / ".minecraft")))
        game_dir = game_dir.resolve()

        version_dir = game_dir / "versions" / version_id
        json_path = version_dir / f"{version_id}.json"
        jar_path = version_dir / f"{version_id}.jar"

        if not game_dir.exists():
            result.add_warning(f"游戏目录不存在，将自动创建: {game_dir}")
            try:
                game_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                result.add_error(f"无法创建游戏目录: {e}")

        if not version_dir.exists():
            result.add_error(f"版本目录不存在: {version_dir}\n请先下载该版本。")
            return result

        if not json_path.exists():
            result.add_error(f"无法读取版本配置文件: {json_path}")
        else:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    version_json = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                result.add_error(f"无法读取版本配置文件: {e}")
                version_json = None
        if not jar_path.exists():
            result.add_error(f"版本 jar 文件不存在: {jar_path}")

        java_info = None
        if java_path:
            java_info = self._java_detector.check_java(java_path)
            if java_info is None:
                result.add_error(f"指定的 Java 路径无效: {java_path}")
        else:
            config_java = self._config.get("java_path", "")
            if config_java:
                java_info = self._java_detector.check_java(Path(config_java))
            if java_info is None:
                java_info = self._java_detector.get_best_match(version_id)

        if java_info is None:
            result.add_error(
                "未找到可用的 Java 运行环境。\n"
                "请安装 Java 或在设置中手动指定 Java 路径。"
            )
        else:
            if not self._java_detector.is_compatible(java_info, version_id):
                min_java = self._java_detector._get_min_java_version(version_id)
                result.add_error(
                    f"Java {java_info.major_version} 不兼容 Minecraft {version_id}。\n"
                    f"该版本需要 Java {min_java} 或更高版本。"
                )
            if not java_info.is_64bit:
                result.add_warning("检测到 32 位 Java，建议使用 64 位 Java 以获得更好性能。")

        if max_memory_mb is None:
            max_memory_mb = self._config.get("java_args.max_memory_mb", 2048)

        total_memory_gb = self._get_total_memory_gb()
        if total_memory_gb > 0:
            if max_memory_mb > total_memory_gb * 1024 * 0.9:
                result.add_warning(
                    f"分配的内存 ({max_memory_mb}MB) 接近系统总内存，可能导致系统卡顿。"
                )
            if max_memory_mb < 1024:
                result.add_warning("分配的内存较小，游戏可能运行不流畅。建议至少分配 2GB。")
        else:
            if max_memory_mb < 1024:
                result.add_warning("分配的内存较小，建议至少分配 2GB。")

        assets_dir = game_dir / "assets"
        if not assets_dir.exists():
            result.add_warning("资源目录不存在，游戏可能无法正常加载纹理资源。")

        return result

    def get_running_process(self) -> Optional[subprocess.Popen]:
        return self._process

    def is_running(self) -> bool:
        return self._is_running and self._process is not None and self._process.poll() is None

    def wait_for_exit(self) -> int:
        if self._process is None:
            raise LaunchError("没有正在运行的游戏进程")
        exit_code = self._process.wait()
        self._is_running = False
        self._exit_code = exit_code
        logger.info("游戏进程已退出，退出码: %d", exit_code)
        return exit_code

    def kill(self) -> None:
        if self._process is not None and self._process.poll() is None:
            logger.info("正在终止游戏进程 (PID: %d)", self._process.pid)
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("进程未响应，强制终止")
                self._process.kill()
            self._is_running = False
            self._exit_code = -1

    def get_log_file_path(self) -> Optional[Path]:
        return self._log_file

    @staticmethod
    def _get_total_memory_gb() -> float:
        try:
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                c_ulonglong = ctypes.c_ulonglong

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", c_ulonglong),
                        ("ullAvailPhys", c_ulonglong),
                        ("ullTotalPageFile", c_ulonglong),
                        ("ullAvailPageFile", c_ulonglong),
                        ("ullTotalVirtual", c_ulonglong),
                        ("ullAvailVirtual", c_ulonglong),
                        ("ullAvailExtendedVirtual", c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(stat)
                kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                return stat.ullTotalPhys / (1024 ** 3)
            else:
                if sys.platform == "darwin":
                    cmd = ["sysctl", "-n", "hw.memsize"]
                else:
                    cmd = ["free", "-b"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if sys.platform == "darwin":
                    return int(result.stdout.strip()) / (1024 ** 3)
                else:
                    for line in result.stdout.split("\n"):
                        if line.startswith("Mem:"):
                            parts = line.split()
                            return int(parts[1]) / (1024 ** 3)
        except Exception:
            pass
        return 0.0

    def _resolve_java(self, java_path: Optional[Path], version_id: str) -> JavaInfo:
        if java_path:
            java_info = self._java_detector.check_java(java_path)
            if java_info is None:
                raise LaunchError(f"指定的 Java 路径无效: {java_path}")
        else:
            config_java = self._config.get("java_path", "")
            if config_java:
                java_info = self._java_detector.check_java(Path(config_java))
                if java_info is not None:
                    return java_info
            java_info = self._java_detector.get_best_match(version_id)

        if java_info is None:
            raise LaunchError(
                "未找到可用的 Java 运行环境。请安装 Java 或在设置中手动指定路径。"
            )

        if not self._java_detector.is_compatible(java_info, version_id):
            min_java = self._java_detector._get_min_java_version(version_id)
            raise LaunchError(
                f"Java {java_info.major_version} 不兼容 Minecraft {version_id}。"
                f"请安装 Java {min_java} 或更高版本。"
            )

        return java_info

    @staticmethod
    def _load_version_json(version_dir: Path) -> Optional[dict]:
        json_path = version_dir / f"{version_dir.name}.json"
        if not json_path.exists():
            json_path = version_dir / "version.json"

        if not json_path.exists():
            logger.error("version.json 不存在: %s", json_path)
            return None

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("解析 version.json 失败: %s", e)
            return None

    @staticmethod
    def _verify_version_files(version_dir: Path, version_json: dict) -> None:
        jar_name = version_json.get("id", version_dir.name)
        jar_path = version_dir / f"{jar_name}.jar"

        if not jar_path.exists():
            raise LaunchError(f"版本 jar 文件不存在: {jar_path}")

        logger.debug("版本文件校验通过: %s", jar_path)

    @staticmethod
    def _build_classpath(game_dir: Path, version_json: dict) -> str:
        libraries_dir = game_dir / "libraries"
        cp_parts: list[str] = []

        version_id = version_json.get("id", "")
        version_jar = game_dir / "versions" / version_id / f"{version_id}.jar"
        if version_jar.exists():
            cp_parts.append(str(version_jar.resolve()))

        for lib in version_json.get("libraries", []):
            lib_path = GameLauncher._resolve_library_path(libraries_dir, lib)
            if lib_path and lib_path.exists():
                cp_parts.append(str(lib_path.resolve()))
            else:
                lib_name = lib.get("name", "unknown")
                logger.debug("库文件不存在（跳过）: %s", lib_name)

        separator = ";" if sys.platform == "win32" else ":"
        return separator.join(cp_parts)

    @staticmethod
    def _resolve_library_path(libraries_dir: Path, lib: dict) -> Optional[Path]:
        name_parts = lib.get("name", "").split(":")
        if len(name_parts) < 3:
            return None

        group, artifact, version = name_parts[0], name_parts[1], name_parts[2]
        group_path = group.replace(".", "/")

        base = libraries_dir / group_path / artifact / version

        if "natives" in lib:
            os_name = _get_native_os_name()
            natives_key = lib["natives"].get(os_name, "")
            if natives_key:
                arch = platform.machine().lower()
                if arch in ("amd64", "x86_64"):
                    arch_replace = "64"
                elif arch in ("i386", "i686", "x86"):
                    arch_replace = "32"
                elif arch in ("aarch64", "arm64"):
                    arch_replace = "arm64"
                else:
                    arch_replace = "64"
                classifier = natives_key.replace("${arch}", arch_replace)
                jar_name = f"{artifact}-{version}-{classifier}.jar"
                return base / jar_name

        jar_name = f"{artifact}-{version}.jar"
        path = base / jar_name
        if not path.exists():
            downloads = lib.get("downloads", {})
            artifact_info = downloads.get("artifact", {})
            if artifact_info.get("path"):
                return libraries_dir / artifact_info["path"]

        return path

    @staticmethod
    def _prepare_natives(game_dir: Path, version_json: dict) -> Path:
        version_id = version_json.get("id", "")
        native_dir = game_dir / "versions" / version_id / "natives"
        native_dir.mkdir(parents=True, exist_ok=True)

        libraries_dir = game_dir / "libraries"
        for lib in version_json.get("libraries", []):
            if "natives" not in lib:
                continue

            lib_path = GameLauncher._resolve_library_path(libraries_dir, lib)
            if lib_path and lib_path.exists():
                try:
                    _extract_zip(lib_path, native_dir)
                except Exception as e:
                    logger.warning("提取 natives 失败: %s -> %s", lib_path, e)

        return native_dir

    @staticmethod
    def _build_jvm_args(
        java_info: JavaInfo,
        version_dir: Path,
        game_dir: Path,
        natives_dir: Path,
        classpath: str,
        version_json: dict,
        min_memory_mb: Optional[int] = None,
        max_memory_mb: Optional[int] = None,
        extra_jvm_args: Optional[str] = None,
    ) -> list[str]:
        config = get_config()

        if min_memory_mb is None:
            min_memory_mb = config.get("java_args.min_memory_mb", 512)
        if max_memory_mb is None:
            max_memory_mb = config.get("java_args.max_memory_mb", 2048)

        args: list[str] = [
            f"-Xms{min_memory_mb}M",
            f"-Xmx{max_memory_mb}M",
        ]

        args.extend(DEFAULT_JVM_ARGS)

        if extra_jvm_args is None:
            extra_jvm_args = config.get("java_args.extra_args", "")
        if extra_jvm_args:
            args.extend(extra_jvm_args.split())

        if sys.platform == "darwin":
            args.append("-XstartOnFirstThread")

        args.extend(["-cp", classpath])
        args.append(f"-Djava.library.path={natives_dir}")
        args.append(f"-Dminecraft.launcher.brand=PythonLauncher")
        args.append(f"-Dminecraft.launcher.version=1.0")
        args.append(f"-Dminecraft.launcher.name=PythonLauncher")
        args.append(f"-Duser.dir={game_dir}")

        arguments = version_json.get("arguments", {})
        jvm_args = arguments.get("jvm", [])
        for arg in jvm_args:
            if isinstance(arg, str):
                arg = arg.replace("${natives_directory}", str(natives_dir))
                arg = arg.replace("${launcher_name}", "PythonLauncher")
                arg = arg.replace("${launcher_version}", "1.0")
                arg = arg.replace("${classpath}", classpath)
                arg = arg.replace("${library_directory}", str(game_dir / "libraries"))
                arg = arg.replace("${classpath_separator}", ";" if sys.platform == "win32" else ":")
                arg = arg.replace("${version_name}", version_json.get("id", ""))
                arg = arg.replace("${game_directory}", str(game_dir))
                args.append(arg)
            elif isinstance(arg, dict):
                if _check_rules(arg.get("rules", [])):
                    value = arg.get("value", "")
                    if isinstance(value, list):
                        for v in value:
                            v = v.replace("${natives_directory}", str(natives_dir))
                            v = v.replace("${classpath}", classpath)
                            v = v.replace("${library_directory}", str(game_dir / "libraries"))
                            args.append(v)
                    elif isinstance(value, str):
                        value = value.replace("${natives_directory}", str(natives_dir))
                        value = value.replace("${classpath}", classpath)
                        args.append(value)

        return args

    @staticmethod
    def _build_minecraft_args(
        account: AccountInfo,
        version_json: dict,
        game_dir: Path,
        window_width: Optional[int] = None,
        window_height: Optional[int] = None,
        fullscreen: Optional[bool] = None,
        demo_mode: bool = False,
        server_address: Optional[str] = None,
        server_port: Optional[int] = None,
    ) -> list[str]:
        config = get_config()

        if window_width is None:
            window_width = config.get("launch.window_width", 854)
        if window_height is None:
            window_height = config.get("launch.window_height", 480)
        if fullscreen is None:
            fullscreen = config.get("launch.fullscreen", False)

        args_dict = {
            "auth_player_name": account.username,
            "version_name": version_json.get("id", ""),
            "game_directory": str(game_dir.resolve()),
            "assets_root": str((game_dir / "assets").resolve()),
            "assets_index_name": version_json.get("assets", version_json.get("id", "")),
            "auth_uuid": account.uuid.replace("-", ""),
            "auth_access_token": account.access_token or "0",
            "user_type": "msa" if account.is_microsoft else "legacy",
            "version_type": version_json.get("type", "release"),
            "resolution_width": str(window_width),
            "resolution_height": str(window_height),
        }

        args: list[str] = [
            "--username", account.username,
            "--version", version_json.get("id", ""),
            "--gameDir", str(game_dir.resolve()),
            "--assetsDir", str((game_dir / "assets").resolve()),
            "--assetIndex", version_json.get("assets", version_json.get("id", "")),
            "--uuid", account.uuid.replace("-", ""),
            "--accessToken", account.access_token or "0",
            "--userType", "msa" if account.is_microsoft else "legacy",
            "--versionType", version_json.get("type", "release"),
            "--width", str(window_width),
            "--height", str(window_height),
        ]

        if fullscreen:
            args.append("--fullscreen")

        if demo_mode:
            args.append("--demo")

        if server_address:
            args.extend(["--server", server_address])
            if server_port:
                args.extend(["--port", str(server_port)])

        arguments = version_json.get("arguments", {})
        game_args = arguments.get("game", [])
        for arg in game_args:
            if isinstance(arg, str):
                for key, value in args_dict.items():
                    arg = arg.replace("${" + key + "}", value)
                args.append(arg)
            elif isinstance(arg, dict):
                if _check_rules(arg.get("rules", [])):
                    value = arg.get("value", "")
                    if isinstance(value, list):
                        for v in value:
                            for key, val in args_dict.items():
                                v = v.replace("${" + key + "}", val)
                            args.append(v)
                    elif isinstance(value, str):
                        for key, val in args_dict.items():
                            value = value.replace("${" + key + "}", val)
                        args.append(value)

        if "minecraftArguments" in version_json:
            mc_args_str = version_json["minecraftArguments"]
            for key, value in args_dict.items():
                mc_args_str = mc_args_str.replace("${" + key + "}", value)
            for old_arg in ["--username", "--version", "--gameDir", "--assetsDir",
                           "--assetIndex", "--uuid", "--accessToken", "--userType",
                           "--versionType", "--width", "--height"]:
                mc_args_str = mc_args_str.replace(old_arg + " ", "__SKIP__")
            extra_parts = []
            parts = mc_args_str.split()
            skip_next = False
            for p in parts:
                if p == "__SKIP__":
                    skip_next = True
                    continue
                if skip_next:
                    skip_next = False
                    continue
                extra_parts.append(p)
            args.extend(extra_parts)

        return args

    def _setup_logging(self, game_dir: Path, version_id: str) -> None:
        log_dir = game_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._log_file = log_dir / f"launcher_{timestamp}.log"

        logger.info("游戏日志将保存到: %s", self._log_file)

    def _start_process(
        self,
        command: list[str],
        game_dir: Path,
    ) -> subprocess.Popen:
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(
                command,
                cwd=str(game_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            logger.info("游戏进程已启动，PID: %d", process.pid)
            return process
        except OSError as e:
            raise LaunchError(f"启动游戏进程失败: {e}") from e

    def _start_log_thread(self) -> None:
        self._stop_event.clear()

        def log_reader():
            log_fp = None
            try:
                if self._log_file:
                    try:
                        log_fp = open(self._log_file, "w", encoding="utf-8")
                    except OSError as e:
                        logger.error("无法打开日志文件: %s", e)

                while self._process and self._process.poll() is None:
                    if self._stop_event.is_set():
                        break
                    try:
                        line = self._process.stdout.readline()
                        if not isinstance(line, str):
                            break
                        if not line:
                            time.sleep(0.1)
                            continue
                        line = line.rstrip("\n\r")
                        if not line:
                            continue

                        if log_fp:
                            try:
                                log_fp.write(line + "\n")
                                log_fp.flush()
                            except Exception:
                                pass

                        _, _, level, message = LogLevel.parse(line)

                        try:
                            self._log_queue.put((line, level), block=False)
                        except Exception:
                            pass

                        if self._on_log:
                            try:
                                self._on_log(line, level)
                            except Exception:
                                pass

                    except Exception as e:
                        logger.debug("读取日志行异常: %s", e)
                        break

                try:
                    if self._process and hasattr(self._process.stdout, 'read'):
                        remaining = self._process.stdout.read()
                        if isinstance(remaining, str) and remaining and log_fp:
                            log_fp.write(remaining)
                except Exception:
                    pass

            except Exception as e:
                logger.error("日志线程异常: %s", e, exc_info=True)
            finally:
                if log_fp:
                    try:
                        log_fp.close()
                    except Exception:
                        pass

        self._log_thread = threading.Thread(target=log_reader, daemon=True)
        self._log_thread.start()

    def _start_monitor_thread(self) -> None:
        def monitor():
            try:
                while self._process and self._process.poll() is None:
                    time.sleep(0.5)

                if self._process:
                    exit_code = self._process.poll()
                    if exit_code is None:
                        exit_code = self._process.wait()
                else:
                    exit_code = -1

                self._is_running = False
                self._exit_code = exit_code
                if isinstance(exit_code, int):
                    logger.info("游戏进程退出，退出码: %d", exit_code)
                else:
                    logger.info("游戏进程已退出")

                if self._on_exit:
                    try:
                        if isinstance(exit_code, int):
                            self._on_exit(exit_code)
                        else:
                            self._on_exit(-1)
                    except Exception:
                        pass

            except Exception as e:
                logger.error("监控线程异常: %s", e, exc_info=True)
                self._is_running = False

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

    @staticmethod
    def _record_launch(version_id: str) -> None:
        try:
            config = get_config()
            config.set("last_launch.version", version_id)
            config.set("last_launch.time", datetime.now().isoformat())
            config.set("last_launch.launch_count", config.get("last_launch.launch_count", 0) + 1)
            config.save()
        except Exception as e:
            logger.debug("记录启动信息失败: %s", e)


def _get_native_os_name() -> str:
    system = sys.platform
    if system == "win32":
        return "windows"
    elif system == "darwin":
        return "osx"
    else:
        return "linux"


def _check_rules(rules: list[dict]) -> bool:
    if not rules:
        return True

    should_include = False
    for rule in rules:
        action = rule.get("action", "allow")
        os_info = rule.get("os", {})
        rule_os_name = os_info.get("name", "")
        rule_os_arch = os_info.get("arch", "")
        current_os = _get_native_os_name()
        current_arch = platform.machine().lower()

        matches_os = (rule_os_name == "" or rule_os_name == current_os)
        matches_arch = (rule_os_arch == "" or rule_os_arch in current_arch)

        if "features" in rule:
            if action == "allow":
                should_include = True
        elif matches_os and matches_arch:
            should_include = (action == "allow")
        elif not matches_os and action == "disallow":
            pass

    return should_include


def _extract_zip(zip_path: Path, extract_to: Path) -> None:
    import zipfile

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.startswith("META-INF/"):
                continue
            if member.endswith("/"):
                continue

            target = extract_to / member
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                continue

            try:
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            except Exception:
                pass
