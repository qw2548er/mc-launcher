"""Fabric 加载器模块。

通过 Fabric Meta API 获取版本列表、安装 Fabric 加载器。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

from src.utils.file_utils import ensure_directory, write_json, calculate_sha1
from src.utils.http_utils import HttpClient, HttpError, get_http_client

from .base import (
    BaseModLoader, ModLoaderType, ModLoaderVersion, InstallResult, InstallProgress,
)

logger = logging.getLogger(__name__)

FABRIC_META_URL = "https://meta.fabricmc.net"


class FabricLoader(BaseModLoader):
    """Fabric 加载器。

    通过 Fabric Meta API 获取版本和安装信息。
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
                for i, entry in enumerate(data):
                    if isinstance(entry, dict):
                        ver = entry.get("version", "")
                        stable = entry.get("stable", False)
                        results.append(ModLoaderVersion(
                            version=ver,
                            mc_version=mc_version,
                            loader_type=ModLoaderType.FABRIC,
                            is_recommended=stable,
                            is_latest=(i == len(data) - 1),
                        ))
            elif isinstance(data, dict):
                loader_versions = data.get("loader", {}).get("versions", [])
                for i, ver in enumerate(loader_versions):
                    results.append(ModLoaderVersion(
                        version=ver,
                        mc_version=mc_version,
                        loader_type=ModLoaderType.FABRIC,
                        is_recommended=False,
                        is_latest=(i == len(loader_versions) - 1),
                    ))

        except Exception as e:
            logger.error("获取 Fabric 版本列表失败: %s", e)
            raise HttpError(f"获取 Fabric 版本列表失败: {e}", url=f"{FABRIC_META_URL}/v2/versions/loader/{mc_version}")

        results.sort(key=lambda v: (not v.is_recommended, not v.is_latest, v.version))
        return results

    def get_install_url(self, mc_version: str, loader_version: str) -> str:
        return f"{FABRIC_META_URL}/v2/versions/loader/{mc_version}/{loader_version}/profile/json"

    def install(
        self,
        mc_version: str,
        loader_version: ModLoaderVersion,
        progress_callback: Optional[Callable[[InstallProgress], None]] = None,
    ) -> InstallResult:
        self.reset()
        self._report_progress(progress_callback, "preparing", 0, "准备安装 Fabric...")

        try:
            version_id = self._make_version_id(mc_version, loader_version.version)
            version_dir = self._versions_dir / version_id
            ensure_directory(version_dir)

            self._check_cancelled()

            self._report_progress(progress_callback, "fetching_profile", 15,
                                  "获取 Fabric 安装配置...")
            profile_url = self.get_install_url(mc_version, loader_version.version)
            profile = self._http.get_json(profile_url)
            self._check_cancelled()

            if isinstance(profile, dict) and "id" in profile:
                profile["id"] = version_id

            if isinstance(profile, dict) and "inheritsFrom" in profile:
                profile["inheritsFrom"] = mc_version

            self._report_progress(progress_callback, "saving_profile", 50,
                                  "保存版本配置文件...")
            version_json_path = version_dir / f"{version_id}.json"
            write_json(version_json_path, profile)
            self._check_cancelled()

            self._report_progress(progress_callback, "downloading_libraries", 60,
                                  "下载 Fabric 库文件...")
            lib_count = self._download_libraries(profile, progress_callback)
            self._check_cancelled()

            self._report_progress(progress_callback, "completed", 100,
                                  f"Fabric {loader_version.version} 安装完成")
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
                self._report_progress(progress_callback, "cancelled", 0, error=error_msg)
                return InstallResult(
                    success=False,
                    loader_type=ModLoaderType.FABRIC,
                    mc_version=mc_version,
                    loader_version=loader_version.version,
                    new_version_id="",
                    message=error_msg,
                )
            logger.error("Fabric 安装失败: %s", e)
            self._report_progress(progress_callback, "failed", 0, error=error_msg)
            return InstallResult(
                success=False,
                loader_type=ModLoaderType.FABRIC,
                mc_version=mc_version,
                loader_version=loader_version.version,
                new_version_id="",
                message=f"安装失败: {error_msg}",
            )

    def _download_libraries(
        self,
        version_json: dict,
        progress_callback: Optional[Callable[[InstallProgress], None]],
    ) -> int:
        libraries = version_json.get("libraries", [])
        if not libraries:
            return 0

        total = len(libraries)
        for i, lib in enumerate(libraries):
            self._check_cancelled()
            name = lib.get("name", "unknown")
            downloads = lib.get("downloads", {})
            artifact = downloads.get("artifact", {})
            url = artifact.get("url", "")
            path_str = artifact.get("path", "")
            sha1 = artifact.get("sha1", "")

            if not url or not path_str:
                continue

            lib_path = self._libraries_dir / path_str
            if lib_path.exists():
                if sha1 and calculate_sha1(lib_path).lower() == sha1.lower():
                    continue

            try:
                ensure_directory(lib_path.parent)
                self._http.download_file(
                    url=url,
                    save_path=lib_path,
                    expected_sha1=sha1 if sha1 else None,
                    resume=True,
                )
            except HttpError as e:
                logger.warning("下载库文件失败 (%s): %s", name, e)

            percent = 60 + (i + 1) / max(total, 1) * 35
            self._report_progress(progress_callback, "downloading_libraries", percent,
                                  f"下载库文件: {i + 1}/{total}")

        return total