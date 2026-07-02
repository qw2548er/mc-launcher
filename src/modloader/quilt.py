"""Quilt 加载器模块。

通过 Quilt Meta API 获取版本列表、安装 Quilt 加载器。
Quilt 是 Fabric 的分支，兼容 Fabric 模组，使用类似的安装流程。
"""

from __future__ import annotations

import logging
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

QUILT_META_URL = "https://meta.quiltmc.org"
QUILT_MAVEN_URL = "https://maven.quiltmc.org/repository/release/"


class QuiltLoader(BaseModLoader):
    """Quilt 加载器。

    通过 Quilt Meta API 获取版本和安装信息。
    Quilt 是 Fabric 的分支，兼容 Fabric 模组。
    """

    @property
    def loader_type(self) -> ModLoaderType:
        return ModLoaderType.QUILT

    @property
    def display_name(self) -> str:
        return "Quilt"

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
                logger.warning("获取 Quilt 版本列表失败，使用缓存")
                return cached
            raise

    def _fetch_versions(self, mc_version: str) -> list[ModLoaderVersion]:
        results: list[ModLoaderVersion] = []

        try:
            data = self._http.get_json(
                f"{QUILT_META_URL}/v3/versions/loader/{mc_version}"
            )

            if isinstance(data, list):
                beta_found = False
                for i, entry in enumerate(data):
                    if isinstance(entry, dict):
                        loader_info = entry.get("loader", {})
                        ver = loader_info.get("version", "")
                        build = loader_info.get("build", entry.get("build", {}))
                        is_beta = "beta" in ver.lower()
                        if not is_beta:
                            beta_found = True
                        is_recommended = (i == 0 and not is_beta) or (not beta_found and i == 0)
                        is_latest = (i == 0)
                        results.append(ModLoaderVersion(
                            version=ver,
                            mc_version=mc_version,
                            loader_type=ModLoaderType.QUILT,
                            is_recommended=is_recommended,
                            is_latest=is_latest,
                        ))
        except Exception as e:
            logger.error("获取 Quilt 版本列表失败: %s", e)
            raise HttpError(f"获取 Quilt 版本列表失败: {e}",
                            url=f"{QUILT_META_URL}/v3/versions/loader/{mc_version}")

        return results

    def get_install_url(self, mc_version: str, loader_version: str) -> str:
        return f"{QUILT_META_URL}/v3/versions/loader/{mc_version}/{loader_version}/profile/json"

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

            _progress("preparing", 0, f"准备安装 Quilt {loader_version.version}...")

            _progress("fetching_profile", 10, "获取 Quilt 安装配置...")
            profile_url = self.get_install_url(mc_version, loader_version.version)
            profile = self._http.get_json(profile_url)
            self._check_cancelled()

            if not isinstance(profile, dict):
                raise RuntimeError("Quilt Meta 返回无效的 profile 数据")

            profile["id"] = version_id
            profile["inheritsFrom"] = mc_version
            profile["type"] = "release"

            if "mainClass" not in profile:
                profile["mainClass"] = "org.quiltmc.loader.impl.launch.knot.KnotClient"

            _progress("downloading_libraries", 20, "下载 Quilt 依赖库...")
            libraries = profile.get("libraries", [])

            extra_repos = [QUILT_MAVEN_URL, "https://maven.fabricmc.net/"]

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
            logger.info("Quilt 库下载完成: 成功 %d, 失败 %d", success_count, failed_count)

            self._check_cancelled()

            _progress("saving_profile", 95, "保存版本配置文件...")
            version_json_path = version_dir / f"{version_id}.json"
            write_json(version_json_path, profile)

            _progress("completed", 100, f"Quilt {loader_version.version} 安装完成")
            logger.info("Quilt 安装完成: %s -> %s", mc_version, version_id)

            return InstallResult(
                success=True,
                loader_type=ModLoaderType.QUILT,
                mc_version=mc_version,
                loader_version=loader_version.version,
                new_version_id=version_id,
                message=f"Quilt {loader_version.version} 安装成功",
            )

        except (RuntimeError, HttpError, OSError) as e:
            error_msg = str(e)
            if "取消" in error_msg:
                _progress("cancelled", 0, err=error_msg)
                return InstallResult(
                    success=False, loader_type=ModLoaderType.QUILT,
                    mc_version=mc_version, loader_version=loader_version.version,
                    new_version_id="", message=error_msg,
                )
            logger.error("Quilt 安装失败: %s", e, exc_info=True)
            _progress("failed", 0, err=f"安装失败: {error_msg}")
            return InstallResult(
                success=False, loader_type=ModLoaderType.QUILT,
                mc_version=mc_version, loader_version=loader_version.version,
                new_version_id="", message=f"安装失败: {error_msg}",
            )
