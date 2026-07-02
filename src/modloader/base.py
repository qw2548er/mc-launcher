"""模组加载器基类模块。

定义所有加载器的统一接口和数据模型。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from src.utils.http_utils import HttpClient, get_http_client

logger = logging.getLogger(__name__)


class ModLoaderType(Enum):
    FORGE = "forge"
    FABRIC = "fabric"
    QUILT = "quilt"


@dataclass
class ModLoaderVersion:
    """加载器版本信息。"""

    version: str                # 加载器版本号，如 "47.2.0"
    mc_version: str             # 对应的 MC 版本，如 "1.20.1"
    loader_type: ModLoaderType  # 加载器类型
    is_recommended: bool = False  # 是否为推荐版本
    is_latest: bool = False       # 是否最新版本
    release_date: str = ""        # 发布日期
    changelog: str = ""           # 更新日志
    download_url: str = ""        # 下载地址
    size: int = 0                 # 文件大小
    sha1: str = ""                # SHA1 校验

    @property
    def display_name(self) -> str:
        tag = ""
        if self.is_recommended:
            tag = " (推荐)"
        elif self.is_latest:
            tag = " (最新)"
        return f"{self.loader_type.value}-{self.version}{tag}"


@dataclass
class InstallResult:
    """安装结果。"""

    success: bool
    loader_type: ModLoaderType
    mc_version: str
    loader_version: str
    new_version_id: str          # 新生成的版本ID
    message: str = ""
    downloaded_files: list[str] = field(default_factory=list)


@dataclass
class InstallProgress:
    """安装进度信息。"""

    stage: str = ""              # 当前阶段
    percent: float = 0.0         # 进度百分比
    message: str = ""            # 阶段描述
    error: Optional[str] = None  # 错误信息


class BaseModLoader(ABC):
    """模组加载器抽象基类。

    所有加载器（Forge、Fabric、Quilt）必须实现此接口。
    """

    def __init__(
        self,
        http_client: Optional[HttpClient] = None,
        game_dir: Optional[Path] = None,
    ):
        self._http = http_client or get_http_client()
        self._game_dir = game_dir or Path.home() / ".minecraft"
        self._versions_dir = self._game_dir / "versions"
        self._libraries_dir = self._game_dir / "libraries"
        self._cancel_flag = False

    @property
    @abstractmethod
    def loader_type(self) -> ModLoaderType:
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @property
    def game_dir(self) -> Path:
        return self._game_dir

    @game_dir.setter
    def game_dir(self, path: Path) -> None:
        self._game_dir = Path(path)
        self._versions_dir = self._game_dir / "versions"
        self._libraries_dir = self._game_dir / "libraries"

    def cancel(self) -> None:
        self._cancel_flag = True
        self._http.cancel()

    def reset(self) -> None:
        self._cancel_flag = False
        self._http.reset_state()

    @abstractmethod
    def get_versions(self, mc_version: str, force_refresh: bool = False) -> list[ModLoaderVersion]:
        """获取指定 MC 版本支持的加载器版本列表。

        Args:
            mc_version: Minecraft 版本号
            force_refresh: 是否强制刷新缓存

        Returns:
            加载器版本列表，按推荐优先排序
        """
        ...

    @abstractmethod
    def install(
        self,
        mc_version: str,
        loader_version: ModLoaderVersion,
        progress_callback: Optional[Callable[[InstallProgress], None]] = None,
    ) -> InstallResult:
        """安装加载器到指定 MC 版本。

        Args:
            mc_version: Minecraft 版本号
            loader_version: 加载器版本信息
            progress_callback: 进度回调

        Returns:
            安装结果
        """
        ...

    @abstractmethod
    def get_install_url(self, mc_version: str, loader_version: str) -> str:
        """获取加载器安装文件下载地址。

        Args:
            mc_version: Minecraft 版本号
            loader_version: 加载器版本号

        Returns:
            下载 URL
        """
        ...

    def is_installed(self, mc_version: str, loader_version: str = "") -> bool:
        """检查指定 MC 版本是否已安装此加载器。

        Args:
            mc_version: Minecraft 版本号
            loader_version: 加载器版本号（空则检查任意版本）

        Returns:
            True 表示已安装
        """
        version_id = self._make_version_id(mc_version, loader_version)
        json_path = self._versions_dir / version_id / f"{version_id}.json"
        return json_path.exists()

    def _make_version_id(self, mc_version: str, loader_version: str) -> str:
        return f"{mc_version}-{self.loader_type.value}-{loader_version}"

    def _report_progress(
        self,
        callback: Optional[Callable[[InstallProgress], None]],
        stage: str,
        percent: float,
        message: str = "",
        error: Optional[str] = None,
    ) -> None:
        if callback is None:
            return
        try:
            callback(InstallProgress(
                stage=stage,
                percent=percent,
                message=message,
                error=error,
            ))
        except Exception:
            pass

    def _check_cancelled(self) -> None:
        if self._cancel_flag:
            raise RuntimeError("安装已取消")