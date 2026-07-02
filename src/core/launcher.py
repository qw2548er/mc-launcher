"""游戏启动器核心模块。

负责组装启动参数、校验版本文件、启动 Minecraft 游戏进程。
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from src.core.account import AccountInfo
from src.core.java_detector import JavaDetector, JavaInfo
from src.utils.config import ConfigManager, get_config
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 默认 JVM 参数
DEFAULT_JVM_ARGS: list[str] = [
    "-XX:+UseG1GC",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:G1NewSizePercent=20",
    "-XX:G1ReservePercent=20",
    "-XX:MaxGCPauseMillis=50",
    "-XX:G1HeapRegionSize=32M",
]

# 游戏主类
MAIN_CLASS = "net.minecraft.client.main.Main"

# 正版认证服务器 URL
AUTH_SERVER = "https://authserver.mojang.com"


class LaunchError(Exception):
    """启动异常。"""

    pass


class GameLauncher:
    """Minecraft 游戏启动器。

    负责组装启动参数并启动游戏进程。
    """

    def __init__(self) -> None:
        self._config: ConfigManager = get_config()
        self._java_detector: JavaDetector = JavaDetector()
        self._process: Optional[subprocess.Popen] = None

    # ── 公共接口 ──────────────────────────────────────────────

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
    ) -> subprocess.Popen:
        """启动 Minecraft 游戏。

        Args:
            version_id: 版本 ID，如 "1.20.4"
            account: 账号信息
            java_path: 手动指定 Java 路径，None 则自动检测
            min_memory_mb: 最小内存（MB）
            max_memory_mb: 最大内存（MB）
            extra_jvm_args: 额外 JVM 参数
            window_width: 窗口宽度
            window_height: 窗口高度
            fullscreen: 全屏模式

        Returns:
            游戏进程的 Popen 对象

        Raises:
            LaunchError: 启动失败
        """
        game_dir = Path(self._config.get("game_directory", ".minecraft"))

        # 1. 获取 Java 路径
        java_info = self._resolve_java(java_path, version_id)

        # 2. 获取版本目录
        version_dir = game_dir / "versions" / version_id
        if not version_dir.exists():
            raise LaunchError(f"版本目录不存在: {version_dir}")

        # 3. 读取 version.json
        version_json = self._load_version_json(version_dir)
        if version_json is None:
            raise LaunchError(f"无法读取版本配置文件: {version_dir}/version.json")

        # 4. 校验版本文件完整性
        self._verify_version_files(version_dir, version_json)

        # 5. 构建 classpath
        classpath = self._build_classpath(game_dir, version_json)

        # 6. 准备 natives
        natives_dir = self._prepare_natives(game_dir, version_json)

        # 7. 组装 JVM 参数
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

        # 8. 组装 Minecraft 参数
        mc_args = self._build_minecraft_args(
            account=account,
            version_json=version_json,
            game_dir=game_dir,
            window_width=window_width,
            window_height=window_height,
            fullscreen=fullscreen,
        )

        # 9. 构建完整命令行
        command = [str(java_info.path)] + jvm_args + [MAIN_CLASS] + mc_args

        logger.info("启动 Minecraft %s", version_id)
        logger.debug("Java 路径: %s (版本 %d)", java_info.path, java_info.major_version)
        logger.debug("游戏目录: %s", game_dir)
        logger.debug("命令行: %s", " ".join(command))

        # 10. 启动进程
        self._process = self._start_process(command, game_dir)

        # 11. 是否关闭启动器
        if self._config.get("launch.close_launcher", True):
            logger.info("启动器将在游戏启动后关闭")

        return self._process

    def get_running_process(self) -> Optional[subprocess.Popen]:
        """获取当前正在运行的游戏进程。"""
        return self._process

    def is_running(self) -> bool:
        """检查游戏是否正在运行。"""
        return self._process is not None and self._process.poll() is None

    def wait_for_exit(self) -> int:
        """等待游戏进程退出并返回退出码。

        Returns:
            进程退出码

        Raises:
            LaunchError: 没有正在运行的进程
        """
        if self._process is None:
            raise LaunchError("没有正在运行的游戏进程")
        exit_code = self._process.wait()
        logger.info("游戏进程已退出，退出码: %d", exit_code)
        self._process = None
        return exit_code

    # ── 内部方法 ──────────────────────────────────────────────

    def _resolve_java(self, java_path: Optional[Path], version_id: str) -> JavaInfo:
        """解析 Java 路径。

        Args:
            java_path: 手动指定的 Java 路径
            version_id: Minecraft 版本 ID

        Returns:
            JavaInfo

        Raises:
            LaunchError: 未找到合适的 Java
        """
        if java_path:
            java_info = self._java_detector.check_java(java_path)
            if java_info is None:
                raise LaunchError(f"指定的 Java 路径无效: {java_path}")
        else:
            # 从配置中获取
            config_java = self._config.get("java_path", "")
            if config_java:
                java_info = self._java_detector.check_java(Path(config_java))
                if java_info is not None:
                    return java_info

            # 自动检测
            java_info = self._java_detector.get_best_match(version_id)

        if java_info is None:
            raise LaunchError(
                "未找到可用的 Java 运行环境。请安装 Java 或在设置中手动指定路径。"
            )

        # 验证兼容性
        if not self._java_detector.is_compatible(java_info, version_id):
            raise LaunchError(
                f"Java {java_info.major_version} 不兼容 Minecraft {version_id}。"
                f"请安装更高版本的 Java。"
            )

        return java_info

    @staticmethod
    def _load_version_json(version_dir: Path) -> Optional[dict]:
        """读取版本的 version.json 文件。"""
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
        """校验版本文件完整性。

        检查 jar 文件是否存在。

        Args:
            version_dir: 版本目录
            version_json: 版本元数据

        Raises:
            LaunchError: 文件校验失败
        """
        jar_name = version_json.get("id", version_dir.name)
        jar_path = version_dir / f"{jar_name}.jar"

        if not jar_path.exists():
            raise LaunchError(
                f"版本 jar 文件不存在: {jar_path}"
            )

        logger.debug("版本文件校验通过: %s", jar_path)

    @staticmethod
    def _build_classpath(game_dir: Path, version_json: dict) -> str:
        """构建 classpath 字符串。

        Args:
            game_dir: .minecraft 目录
            version_json: 版本元数据

        Returns:
            系统分隔符分隔的 classpath 字符串
        """
        libraries_dir = game_dir / "libraries"
        cp_parts: list[str] = []

        # 版本 jar
        version_id = version_json.get("id", "")
        version_jar = game_dir / "versions" / version_id / f"{version_id}.jar"
        cp_parts.append(str(version_jar.resolve()))

        # libraries
        for lib in version_json.get("libraries", []):
            lib_path = GameLauncher._resolve_library_path(libraries_dir, lib)
            if lib_path and lib_path.exists():
                cp_parts.append(str(lib_path.resolve()))
            else:
                logger.warning("库文件不存在: %s", lib_path)

        separator = ";" if sys.platform == "win32" else ":"
        return separator.join(cp_parts)

    @staticmethod
    def _resolve_library_path(libraries_dir: Path, lib: dict) -> Optional[Path]:
        """解析 library 的本地文件路径。

        Args:
            libraries_dir: libraries 目录
            lib: library 字典

        Returns:
            本地文件路径
        """
        name_parts = lib.get("name", "").split(":")
        if len(name_parts) < 3:
            return None

        group, artifact, version = name_parts[0], name_parts[1], name_parts[2]
        group_path = group.replace(".", "/")

        # 构建基础路径
        base = libraries_dir / group_path / artifact / version

        # 检查 natives 规则
        if "natives" in lib:
            os_name = _get_native_os_name()
            natives_key = lib["natives"].get(os_name, "")
            if natives_key:
                # 替换 natives 占位符
                classifier = natives_key.replace(
                    "${arch}", str(platform.architecture()[0]).replace("bit", "")
                )
                jar_name = f"{artifact}-{version}-{classifier}.jar"
                return base / jar_name

        # 普通 library
        jar_name = f"{artifact}-{version}.jar"
        path = base / jar_name
        if not path.exists():
            # 检查子目录（某些 library 有不同结构）
            downloads = lib.get("downloads", {})
            artifact_info = downloads.get("artifact", {})
            if artifact_info.get("path"):
                return libraries_dir / artifact_info["path"]

        return path

    @staticmethod
    def _prepare_natives(game_dir: Path, version_json: dict) -> Path:
        """准备 natives 库。

        提取 natives 到临时目录。

        Args:
            game_dir: .minecraft 目录
            version_json: 版本元数据

        Returns:
            natives 目录路径
        """
        version_id = version_json.get("id", "")
        native_dir = game_dir / "versions" / version_id / "natives"
        native_dir.mkdir(parents=True, exist_ok=True)

        # 提取 natives
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
        """构建 JVM 启动参数。

        Args:
            java_info: Java 信息
            version_dir: 版本目录
            game_dir: 游戏目录
            natives_dir: natives 目录
            classpath: classpath 字符串
            version_json: 版本元数据
            min_memory_mb: 最小内存
            max_memory_mb: 最大内存
            extra_jvm_args: 额外 JVM 参数

        Returns:
            JVM 参数列表
        """
        config = get_config()

        # 内存设置
        if min_memory_mb is None:
            min_memory_mb = config.get("java_args.min_memory_mb", 512)
        if max_memory_mb is None:
            max_memory_mb = config.get("java_args.max_memory_mb", 2048)

        args: list[str] = [
            f"-Xms{min_memory_mb}M",
            f"-Xmx{max_memory_mb}M",
        ]

        # 默认 JVM 参数
        args.extend(DEFAULT_JVM_ARGS)

        # 额外 JVM 参数
        if extra_jvm_args is None:
            extra_jvm_args = config.get("java_args.extra_args", "")
        if extra_jvm_args:
            args.extend(extra_jvm_args.split())

        # classpath
        args.extend(["-cp", classpath])

        # natives 路径
        args.append(f"-Djava.library.path={natives_dir}")

        # 游戏目录
        args.append(f"-Dminecraft.launcher.brand=PythonLauncher")
        args.append(f"-Dminecraft.launcher.version=1.0")

        # 版本元数据中的 JVM 参数
        arguments = version_json.get("arguments", {})
        jvm_args = arguments.get("jvm", [])
        for arg in jvm_args:
            if isinstance(arg, str):
                # 替换占位符
                arg = arg.replace("${natives_directory}", str(natives_dir))
                arg = arg.replace("${launcher_name}", "PythonLauncher")
                arg = arg.replace("${launcher_version}", "1.0")
                arg = arg.replace("${classpath}", classpath)
                arg = arg.replace("${library_directory}", str(game_dir / "libraries"))
                arg = arg.replace("${version_name}", version_json.get("id", ""))
                args.append(arg)
            elif isinstance(arg, dict):
                # 条件参数（需要检查规则）
                if _check_rules(arg.get("rules", [])):
                    value = arg.get("value", "")
                    if isinstance(value, list):
                        args.extend(value)
                    elif isinstance(value, str):
                        args.append(value)

        # 版本元数据中的旧版 minecraftArguments
        if "minecraftArguments" in version_json:
            mc_args = version_json["minecraftArguments"]
            args.append(mc_args)

        return args

    @staticmethod
    def _build_minecraft_args(
        account: AccountInfo,
        version_json: dict,
        game_dir: Path,
        window_width: Optional[int] = None,
        window_height: Optional[int] = None,
        fullscreen: Optional[bool] = None,
    ) -> list[str]:
        """构建 Minecraft 游戏参数。

        Args:
            account: 账号信息
            version_json: 版本元数据
            game_dir: 游戏目录
            window_width: 窗口宽度
            window_height: 窗口高度
            fullscreen: 全屏模式

        Returns:
            Minecraft 参数列表
        """
        config = get_config()

        if window_width is None:
            window_width = config.get("launch.window_width", 854)
        if window_height is None:
            window_height = config.get("launch.window_height", 480)
        if fullscreen is None:
            fullscreen = config.get("launch.fullscreen", False)

        args: list[str] = [
            "--username", account.username,
            "--version", version_json.get("id", ""),
            "--gameDir", str(game_dir.resolve()),
            "--assetsDir", str((game_dir / "assets").resolve()),
            "--assetIndex", version_json.get("assets", version_json.get("id", "")),
            "--uuid", account.uuid,
            "--accessToken", account.access_token or "0",
            "--userType", "mojang" if account.is_microsoft else "legacy",
            "--versionType", version_json.get("type", "release"),
            "--width", str(window_width),
            "--height", str(window_height),
        ]

        if fullscreen:
            args.append("--fullscreen")

        # 游戏参数（新版格式）
        arguments = version_json.get("arguments", {})
        game_args = arguments.get("game", [])
        for arg in game_args:
            if isinstance(arg, str):
                args.append(arg)
            elif isinstance(arg, dict):
                if _check_rules(arg.get("rules", [])):
                    value = arg.get("value", "")
                    if isinstance(value, list):
                        args.extend(value)
                    elif isinstance(value, str):
                        args.append(value)

        return args

    @staticmethod
    def _start_process(
        command: list[str],
        game_dir: Path,
    ) -> subprocess.Popen:
        """启动游戏进程。

        Args:
            command: 命令行
            game_dir: 游戏目录（工作目录）

        Returns:
            Popen 对象

        Raises:
            LaunchError: 启动失败
        """
        try:
            process = subprocess.Popen(
                command,
                cwd=str(game_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            logger.info("游戏进程已启动，PID: %d", process.pid)
            return process
        except OSError as e:
            raise LaunchError(f"启动游戏进程失败: {e}") from e


# ── 工具函数 ──────────────────────────────────────────────────

def _get_native_os_name() -> str:
    """获取当前操作系统对应的 natives 名称。"""
    system = sys.platform
    if system == "win32":
        return "windows"
    elif system == "darwin":
        return "osx"
    else:
        return "linux"


def _check_rules(rules: list[dict]) -> bool:
    """检查条件规则是否匹配当前系统。

    Args:
        rules: 规则列表

    Returns:
        True 表示规则匹配，应该包含该参数
    """
    if not rules:
        return True

    should_include = False
    for rule in rules:
        action = rule.get("action", "allow")
        os_info = rule.get("os", {})
        rule_os_name = os_info.get("name", "")
        current_os = _get_native_os_name()

        matches_os = (rule_os_name == current_os)

        if "features" in rule:
            # 特性规则，默认包含
            if action == "allow":
                should_include = True
        elif matches_os:
            should_include = (action == "allow")
        elif not matches_os and action == "disallow":
            # 只在不匹配当前 OS 时生效
            pass

    return should_include


def _extract_zip(zip_path: Path, extract_to: Path) -> None:
    """提取 zip 文件到目标目录。

    跳过 META-INF 目录和已存在的文件。

    Args:
        zip_path: zip 文件路径
        extract_to: 目标目录
    """
    import zipfile

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            # 跳过 META-INF
            if member.startswith("META-INF/"):
                continue

            target = extract_to / member
            if target.exists():
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            except Exception:
                pass  # 跳过无法提取的文件