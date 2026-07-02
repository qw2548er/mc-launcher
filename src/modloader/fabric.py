"""Fabric 加载器模块。

通过 Fabric Meta API 获取版本列表、安装 Fabric 加载器。
实现正确的安装流程：
1. 从 Fabric Meta 获取 profile/json（包含完整 library 列表）
2. 使用 maven_utils 解析所有库（包括没有 downloads.url 的库）
3. 从 Fabric Maven 或 Maven Central 下载所有依赖
4. 包含 intermediary mappings 和 fabric-loader 自身
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Callable, Optional

from src.utils.file_utils import ensure_directory, write_json
from src.utils.http_utils import HttpClient, HttpError, get_http_client

from .base import (
    BaseModLoader, ModLoaderType, ModLoaderVersion, InstallResult, InstallProgress,
)
from .maven_utils import download_libraries

logger = logging.getLogger(__name__)

FABRIC_META_URL = "https://meta.fabricmc.net"
FABRIC_MAVEN_URL = "https://maven.fabricmc.net/"


class FabricLoader(BaseModLoader):
    """Fabric 加载器。

    通过 Fabric Meta API 获取版本和安装信息。
    使用统一的 Maven 库解析器下载所有依赖。
    """

    @property
    def loader_type(self) -> ModLoaderType:
        return ModLoaderType.FABRIC

    @property
    def display_name(self) -> str:
        return "Fabric"

    def __init__(
        self,
        http_client: Optional[HttpClient] = None,
        game_dir: Optional[Path] = None,
    ):
        super().__init__(http_client, game_dir)
        self._versions_cache: dict[str, list[ModLoaderVersion]] = {}
        self._cache_timestamp: dict[str, float] = {}
        self._cache_ttl = 3600

    def get_versions(self, mc_version: str, force_refresh: bool = False) -> list[ModLoaderVersion]:
        self._check_cancelled()

        cache_key = mc_version
        now = time.time()
        if not force_refresh and cache_key in self._versions_cache:
            if now - self._cache_timestamp.get(cache_key, 0) < self._cache_ttl:
                return self._versions_cache[cache_key]

        try:
            versions = self._fetch_versions(mc_version)
            self._versions_cache[cache_key] = versions
            self._cache_timestamp[cache_key] = now
            return versions
        except HttpError:
            cached = self._versions_cache.get(cache_key)
            if cached:
                logger.warning("获取 Fabric 版本列表失败，使用缓存")
                return cached
            raise

    def _fetch_versions(self, mc_version: str) -> list[ModLoaderVersion]:
        results: list[ModLoaderVersion] = []

        try:
            data = self._http.get_json(
                f"{FABRIC_META_URL}/v2/versions/loader/{mc_version}"
            )

            if isinstance(data, list):
                stable_count = 0
                for i, entry in enumerate(data):
                    if isinstance(entry, dict):
                        loader_info = entry.get("loader", {})
                        ver = loader_info.get("version", "")
                        stable = loader_info.get("stable", False)
                        if stable:
                            stable_count += 1
                        is_recommended = stable and stable_count == 1
                        is_latest = (i == 0)
                        results.append(ModLoaderVersion(
                            version=ver,
                            mc_version=mc_version,
                            loader_type=ModLoaderType.FABRIC,
                            is_recommended=is_recommended,
                            is_latest=is_latest,
                        ))
        except Exception as e:
            logger.error("获取 Fabric 版本列表失败: %s", e)
            raise HttpError(f"获取 Fabric 版本列表失败: {e}",
                            url=f"{FABRIC_META_URL}/v2/versions/loader/{mc_version}")

        return results

    def get_install_url(self, mc_version: str, loader_version: str) -> str:
        return f"{FABRIC_META_URL}/v2/versions/loader/{mc_version}/{loader_version}/profile/json"

    def get_loader_version_url(self, mc_version: str, loader_version: str) -> str:
        return f"{FABRIC_META_URL}/v2/versions/loader/{mc_version}/{loader_version}"

    def install(
        self,
        mc_version: str,
        loader_version: ModLoaderVersion,
        progress_callback: Optional[Callable[[InstallProgress], None]] = None,
    ) -> InstallResult:
        self.reset()

        def _progress(stage: str, pct: float, msg: str, err: Optional[str] = None):
            self._report_progress(progress_callback, stage, pct, msg, err)

        try:
            version_id = self._make_version_id(mc_version, loader_version.version)
            version_dir = self._versions_dir / version_id
            ensure_directory(version_dir)
            self._check_cancelled()

            _progress("preparing", 0, f"准备安装 Fabric {loader_version.version}...")

            _progress("fetching_profile", 10, "获取 Fabric 安装配置...")
            profile_url = self.get_install_url(mc_version, loader_version.version)
            profile = self._http.get_json(profile_url)
            self._check_cancelled()

            if not isinstance(profile, dict):
                raise RuntimeError("Fabric Meta 返回无效的 profile 数据")

            profile["id"] = version_id
            profile["inheritsFrom"] = mc_version
            profile["type"] = "release"

            if "mainClass" not in profile:
                profile["mainClass"] = "net.fabricmc.loader.impl.launch.knot.KnotClient"

            _progress("downloading_libraries", 20, "下载 Fabric 依赖库...")
            libraries = profile.get("libraries", [])

            extra_repos = [FABRIC_MAVEN_URL]

            def _lib_progress(cur: int, total: int, pct: float, fname: str):
                overall = 20 + (pct / 100) * 70
                _progress("downloading_libraries", overall, f"下载库文件: {cur}/{total} - {fname}")

            success_count, failed_count = download_libraries(
                libraries=libraries,
                libraries_dir=self._libraries_dir,
                http_client=self._http,
                progress_callback=_lib_progress,
                extra_repos=extra_repos,
                cancel_check=lambda: self._cancel_flag,
            )
            logger.info("Fabric 库下载完成: 成功 %d, 失败 %d", success_count, failed_count)

            self._check_cancelled()

            _progress("saving_profile", 95, "保存版本配置文件...")
            version_json_path = version_dir / f"{version_id}.json"
            write_json(version_json_path, profile)

            _progress("completed", 100, f"Fabric {loader_version.version} 安装完成")
            logger.info("Fabric 安装完成: %s -> %s", mc_version, version_id)

            return InstallResult(
                success=True,
                loader_type=ModLoaderType.FABRIC,
                mc_version=mc_version,
                loader_version=loader_version.version,
                new_version_id=version_id,
                message=f"Fabric {loader_version.version} 安装成功",
            )

        except (RuntimeError, HttpError, OSError) as e:
            error_msg = str(e)
            if "取消" in error_msg:
                _progress("cancelled", 0, err=error_msg)
                return InstallResult(
                    success=False, loader_type=ModLoaderType.FABRIC,
                    mc_version=mc_version, loader_version=loader_version.version,
                    new_version_id="", message=error_msg,
                )
            logger.error("Fabric 安装失败: %s", e, exc_info=True)
            _progress("failed", 0, err=f"安装失败: {error_msg}")
            return InstallResult(
                success=False, loader_type=ModLoaderType.FABRIC,
                mc_version=mc_version, loader_version=loader_version.version,
                new_version_id="", message=f"安装失败: {error_msg}",
            )
