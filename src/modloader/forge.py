"""Forge 加载器模块。

通过 MinecraftForge 官方 Maven 和 API 获取版本列表、安装 Forge 加载器。
"""

from __future__ import annotations

import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

from src.utils.file_utils import ensure_directory, read_json, write_json, calculate_sha1
from src.utils.http_utils import HttpClient, HttpError, get_http_client, DownloadProgressInfo

from .base import (
    BaseModLoader, ModLoaderType, ModLoaderVersion, InstallResult, InstallProgress,
)

logger = logging.getLogger(__name__)

FORGE_PROMOTIONS_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN_BASE = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_MAVEN_METADATA = f"{FORGE_MAVEN_BASE}/maven-metadata.xml"


class ForgeLoader(BaseModLoader):
    """Forge 加载器。

    支持通过 Forge Maven 仓库安装 Forge。
    """

    @property
    def loader_type(self) -> ModLoaderType:
        return ModLoaderType.FORGE

    @property
    def display_name(self) -> str:
        return "Forge"

    def __init__(
        self,
        http_client: Optional[HttpClient] = None,
        game_dir: Optional[Path] = None,
    ):
        super().__init__(http_client, game_dir)
        self._versions_cache: dict[str, list[ModLoaderVersion]] = {}
        self._cache_timestamp: dict[str, float] = {}
        self._cache_ttl = 3600  # 1 小时

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
                logger.warning("获取 Forge 版本列表失败，使用缓存")
                return cached
            raise

    def _fetch_versions(self, mc_version: str) -> list[ModLoaderVersion]:
        results: list[ModLoaderVersion] = []

        try:
            xml_text = self._http.get(FORGE_MAVEN_METADATA).text
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_text)
            versioning = root.find("versioning")
            if versioning is None:
                return results

            versions_elem = versioning.find("versions")
            if versions_elem is None:
                return results

            all_versions = []
            for v_elem in versions_elem.findall("version"):
                text = v_elem.text
                if text:
                    all_versions.append(text)

            filtered = [v for v in all_versions if v.startswith(f"{mc_version}-")]

            for i, ver in enumerate(filtered):
                clean_ver = ver[len(mc_version) + 1:] if ver.startswith(f"{mc_version}-") else ver
                results.append(ModLoaderVersion(
                    version=clean_ver,
                    mc_version=mc_version,
                    loader_type=ModLoaderType.FORGE,
                    is_recommended=False,
                    is_latest=(i == len(filtered) - 1),
                    download_url=f"{FORGE_MAVEN_BASE}/{ver}/forge-{ver}-installer.jar",
                ))

            if results:
                results[-1].is_latest = True
                results[-1].is_recommended = True
        except Exception as e:
            logger.warning("解析 Forge Maven 元数据失败: %s", e)

        try:
            promotions = self._http.get_json(FORGE_PROMOTIONS_URL)
            promos = promotions.get("promos", {})
            latest_key = f"{mc_version}-latest"
            recommended_key = f"{mc_version}-recommended"

            recommended_ver = promos.get(recommended_key, "")
            latest_ver = promos.get(latest_key, "")

            for r in results:
                if r.version == recommended_ver:
                    r.is_recommended = True
                if r.version == latest_ver:
                    r.is_latest = True
        except Exception:
            pass

        results.sort(key=lambda v: (not v.is_recommended, not v.is_latest, v.version))
        return results

    def get_install_url(self, mc_version: str, loader_version: str) -> str:
        full_version = f"{mc_version}-{loader_version}"
        return f"{FORGE_MAVEN_BASE}/{full_version}/forge-{full_version}-installer.jar"

    def install(
        self,
        mc_version: str,
        loader_version: ModLoaderVersion,
        progress_callback: Optional[Callable[[InstallProgress], None]] = None,
    ) -> InstallResult:
        self.reset()
        self._report_progress(progress_callback, "preparing", 0, "准备安装 Forge...")

        try:
            full_forge = f"{mc_version}-{loader_version.version}"
            version_id = self._make_version_id(mc_version, loader_version.version)
            version_dir = self._versions_dir / version_id
            ensure_directory(version_dir)

            self._check_cancelled()

            installer_url = self.get_install_url(mc_version, loader_version.version)
            installer_path = self._libraries_dir / "net" / "minecraftforge" / "forge" / full_forge / f"forge-{full_forge}-installer.jar"

            if not installer_path.exists():
                self._report_progress(progress_callback, "downloading_installer", 10,
                                      f"下载 Forge 安装器: {loader_version.version}")
                ensure_directory(installer_path.parent)
                self._http.download_file(
                    url=installer_url,
                    save_path=installer_path,
                    progress_callback=None,
                    resume=True,
                )
                self._check_cancelled()

            self._report_progress(progress_callback, "extracting", 40,
                                  "提取版本配置文件...")
            version_json = self._extract_version_json(installer_path, full_forge, mc_version)

            self._report_progress(progress_callback, "saving_profile", 60,
                                  "保存版本配置文件...")
            version_json_path = version_dir / f"{version_id}.json"
            write_json(version_json_path, version_json)
            self._check_cancelled()

            self._report_progress(progress_callback, "downloading_libraries", 70,
                                  "下载 Forge 库文件...")
            lib_count = self._download_libraries(version_json, version_dir, progress_callback)
            self._check_cancelled()

            self._report_progress(progress_callback, "completed", 100,
                                  f"Forge {loader_version.version} 安装完成")
            logger.info("Forge 安装完成: %s -> %s", mc_version, version_id)

            return InstallResult(
                success=True,
                loader_type=ModLoaderType.FORGE,
                mc_version=mc_version,
                loader_version=loader_version.version,
                new_version_id=version_id,
                message=f"Forge {loader_version.version} 安装成功",
                downloaded_files=[str(installer_path)],
            )

        except (RuntimeError, HttpError, OSError) as e:
            error_msg = str(e)
            if "取消" in error_msg:
                self._report_progress(progress_callback, "cancelled", 0, error=error_msg)
                return InstallResult(
                    success=False,
                    loader_type=ModLoaderType.FORGE,
                    mc_version=mc_version,
                    loader_version=loader_version.version,
                    new_version_id="",
                    message=error_msg,
                )
            logger.error("Forge 安装失败: %s", e)
            self._report_progress(progress_callback, "failed", 0, error=error_msg)
            return InstallResult(
                success=False,
                loader_type=ModLoaderType.FORGE,
                mc_version=mc_version,
                loader_version=loader_version.version,
                new_version_id="",
                message=f"安装失败: {error_msg}",
            )

    def _extract_version_json(self, installer_path: Path, forge_version: str, mc_version: str) -> dict:
        try:
            with zipfile.ZipFile(installer_path, "r") as zf:
                if "version.json" in zf.namelist():
                    return json.loads(zf.read("version.json"))
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
            logger.warning("从安装器中提取 version.json 失败: %s，尝试构建", e)

        return self._build_version_json(forge_version, mc_version)

    def _build_version_json(self, forge_version: str, mc_version: str) -> dict:
        """构建 Forge 版本 JSON 配置文件。

        当无法从 installer jar 中提取时，手动构建基本配置。
        """
        version_id = self._make_version_id(mc_version, forge_version.split("-")[-1] if "-" in forge_version else forge_version)

        return {
            "id": version_id,
            "inheritsFrom": mc_version,
            "type": "release",
            "time": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "releaseTime": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "mainClass": "cpw.mods.modlauncher.Launcher",
            "arguments": {
                "game": [],
                "jvm": [
                    "-Djava.net.preferIPv6Addresses=system",
                    "-DignoreList=forge-,forge_",
                    "-DmergeModules=jna-5.13.0.jar,jna-platform-5.13.0.jar",
                    "-DlibraryDirectory=${library_directory}",
                    "-p",
                    "${classpath}",
                ],
            },
            "libraries": [
                {
                    "name": f"net.minecraftforge:forge:{forge_version}",
                    "downloads": {
                        "artifact": {
                            "path": f"net/minecraftforge/forge/{forge_version}/forge-{forge_version}.jar",
                            "url": f"https://maven.minecraftforge.net/net/minecraftforge/forge/{forge_version}/forge-{forge_version}.jar",
                            "sha1": "",
                            "size": 0,
                        }
                    },
                },
            ],
        }

    def _download_libraries(
        self,
        version_json: dict,
        version_dir: Path,
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

            percent = 70 + (i + 1) / max(total, 1) * 25
            self._report_progress(progress_callback, "downloading_libraries", percent,
                                  f"下载库文件: {i + 1}/{total}")

        return total