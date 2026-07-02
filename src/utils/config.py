"""配置管理模块。

提供全局配置的读写接口，基于 JSON 文件存储，线程安全。
"""

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

def _get_default_game_dir() -> str:
    return str(Path.home() / ".minecraft")


# 默认配置
DEFAULT_SETTINGS: dict[str, Any] = {
    "game_directory": _get_default_game_dir(),
    "java_path": "",
    "offline_username": "Steve",
    "java_args": {
        "min_memory_mb": 512,
        "max_memory_mb": 4096,
        "extra_args": "-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions",
    },
    "launch": {
        "window_width": 854,
        "window_height": 480,
        "fullscreen": False,
        "close_launcher": True,
    },
    "download": {
        "max_threads": 4,
        "max_retries": 3,
    },
    "appearance": {
        "theme": "dark",
        "language": "zh_CN",
        "font_size": 12,
    },
    "advanced": {
        "auto_update_versions": True,
        "keep_old_versions": False,
        "show_snapshots": False,
        "show_beta": False,
        "show_alpha": False,
    },
    "default_version": "",
    "default_account": "",
    "last_launch": {
        "version": "",
        "time": "",
        "launch_count": 0,
    },
    "auth": {
        "ms_client_id": "",
    },
}


class ConfigManager:
    """配置管理器（单例模式）。

    负责读写 config/settings.json 文件，提供线程安全的配置存取接口。
    """

    _instance: Optional["ConfigManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._config: dict[str, Any] = deepcopy(DEFAULT_SETTINGS)
        self._config_path: Path = Path("config/settings.json")
        self._rw_lock = threading.RLock()
        self._initialized = True
        self.load()

    # ── 文件操作 ──────────────────────────────────────────────

    def load(self, config_path: Optional[Path] = None) -> None:
        """从 JSON 文件加载配置。

        如果文件不存在，则使用默认配置并自动创建文件。

        Args:
            config_path: 配置文件路径，默认使用初始化时的路径
        """
        if config_path is not None:
            self._config_path = Path(config_path)

        with self._rw_lock:
            if self._config_path.exists():
                try:
                    with open(self._config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # 深度合并：用文件中的值覆盖默认值，保留新增的默认 key
                    self._config = self._deep_merge(
                        deepcopy(DEFAULT_SETTINGS), data
                    )
                    logger.info("配置已加载: %s", self._config_path)
                except (json.JSONDecodeError, OSError) as e:
                    logger.error("加载配置文件失败: %s，使用默认配置", e)
                    self._config = deepcopy(DEFAULT_SETTINGS)
            else:
                logger.info("配置文件不存在，使用默认配置并创建: %s", self._config_path)
                self.save()

    def save(self) -> None:
        """保存当前配置到 JSON 文件。"""
        with self._rw_lock:
            try:
                self._config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._config_path, "w", encoding="utf-8") as f:
                    json.dump(self._config, f, ensure_ascii=False, indent=2)
                logger.debug("配置已保存: %s", self._config_path)
            except OSError as e:
                logger.error("保存配置文件失败: %s", e)

    # ── 读取接口 ──────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项。

        支持点号分隔的嵌套 key，例如 "java_args.max_memory_mb"。

        Args:
            key: 配置键，支持点号分隔
            default: 默认值

        Returns:
            配置值
        """
        with self._rw_lock:
            keys = key.split(".")
            value: Any = self._config
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            return value

    def get_all(self) -> dict[str, Any]:
        """获取全部配置的深拷贝。"""
        with self._rw_lock:
            return deepcopy(self._config)

    # ── 写入接口 ──────────────────────────────────────────────

    def set(self, key: str, value: Any) -> None:
        """设置配置项。

        支持点号分隔的嵌套 key，会自动创建中间字典。

        Args:
            key: 配置键，支持点号分隔
            value: 配置值
        """
        with self._rw_lock:
            keys = key.split(".")
            target: dict[str, Any] = self._config
            for k in keys[:-1]:
                if k not in target or not isinstance(target[k], dict):
                    target[k] = {}
                target = target[k]
            target[keys[-1]] = value
            logger.debug("配置变更: %s = %s", key, value)

    def update(self, updates: dict[str, Any]) -> None:
        """批量更新配置。

        Args:
            updates: 要更新的配置字典，支持嵌套 key
        """
        with self._rw_lock:
            for key, value in updates.items():
                self.set(key, value)

    def reset(self) -> None:
        """重置为默认配置。"""
        with self._rw_lock:
            self._config = deepcopy(DEFAULT_SETTINGS)
            logger.info("配置已重置为默认值")

    # ── 内部方法 ──────────────────────────────────────────────

    @staticmethod
    def _deep_merge(
        base: dict[str, Any], override: dict[str, Any]
    ) -> dict[str, Any]:
        """深度合并两个字典，override 中的值覆盖 base 中的值。

        Args:
            base: 基础字典
            override: 覆盖字典

        Returns:
            合并后的字典
        """
        result = deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result


# 便捷函数
def get_config() -> ConfigManager:
    """获取 ConfigManager 单例。"""
    return ConfigManager()