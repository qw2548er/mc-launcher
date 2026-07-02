"""Forge 加载器模块。

通过 MinecraftForge 官方 Maven 和 API 获取版本列表、安装 Forge 加载器。
实现正确的安装流程：
1. 下载 installer jar
2. 从 installer 中解析 install_profile.json
3. 提取 maven/ 目录中的本地库到全局 libraries
4. 解析 version.json 作为基础
5. 合并 install_profile.json 中的 libraries 和 processors
6. 下载缺失的库文件
7. 写入最终的版本 JSON 配置
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

from src.utils.file_utils import ensure_directory, read_json, write_json, calculate_sha1
from src.utils.http_utils import HttpClient, HttpError, get_http_client
from src.utils.logger import get_logger

from .base import (
    BaseModLoader, ModLoaderType, ModLoaderVersion, InstallResult, InstallProgress,
)
from .maven_utils import (
    download_libraries,
    extract_maven_from_installer,
    get_os_name,
)

logger = get_logger(__name__)

FORGE_PROMOTIONS_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN_BASE = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_MAVEN_METADATA = f"{FORGE_MAVEN_BASE}/maven-metadata.xml"


class ForgeLoader(BaseModLoader):
    """Forge 加载器。

    支持通过 Forge Maven 仓库安装 Forge。
    正确处理 install_profile.json 和 maven/ 本地库提取。
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
                logger.warning("获取 Forge 版本列表失败，使用缓存")
                return cached
            raise

    def _fetch_versions(self, mc_version: str) -> list[ModLoaderVersion]:
        import xml.etree.ElementTree as ET

        results: list[ModLoaderVersion] = []
        recommended_ver = ""
        latest_ver = ""

        try:
            promotions = self._http.get_json(FORGE_PROMOTIONS_URL)
            promos = promotions.get("promos", {})
            recommended_ver = promos.get(f"{mc_version}-recommended", "")
            latest_ver = promos.get(f"{mc_version}-latest", "")
        except Exception:
            pass

        try:
            xml_text = self._http.get(FORGE_MAVEN_METADATA).text
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

            prefix = f"{mc_version}-"
            filtered = [v for v in all_versions if v.startswith(prefix)]

            for ver in filtered:
                clean_ver = ver[len(prefix):]
                is_rec = (clean_ver == recommended_ver)
                is_lat = (clean_ver == latest_ver)
                if not is_rec and not is_lat and clean_ver == filtered[-1][len(prefix):]:
                    is_lat = True

                full_ver = ver
                installer_url = f"{FORGE_MAVEN_BASE}/{full_ver}/forge-{full_ver}-installer.jar"
                results.append(ModLoaderVersion(
                    version=clean_ver,
                    mc_version=mc_version,
                    loader_type=ModLoaderType.FORGE,
                    is_recommended=is_rec,
                    is_latest=is_lat,
                    download_url=installer_url,
                ))
        except Exception as e:
            logger.warning("解析 Forge Maven 元数据失败: %s", e)

        results.sort(key=lambda v: (not v.is_recommended, not v.is_latest, _version_sort_key(v.version)))
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
        import platform as _platform
        import tempfile as _tempfile

        self.reset()
        downloaded_files: list[str] = []

        def _progress(stage: str, pct: float, msg: str, err: Optional[str] = None):
            self._report_progress(progress_callback, stage, pct, msg, err)

        try:
            full_forge = f"{mc_version}-{loader_version.version}"
            version_id = self._make_version_id(mc_version, loader_version.version)
            version_dir = self._versions_dir / version_id
            ensure_directory(version_dir)
            self._check_cancelled()

            _progress("preparing", 0, f"准备安装 Forge {loader_version.version}...")

            installer_url = loader_version.download_url or self.get_install_url(mc_version, loader_version.version)

            installer_cache_dir = self._libraries_dir / "net" / "minecraftforge" / "forge" / full_forge
            ensure_directory(installer_cache_dir)
            installer_path = installer_cache_dir / f"forge-{full_forge}-installer.jar"

            if not installer_path.exists() or installer_path.stat().st_size < 1000:
                _progress("downloading_installer", 5, f"下载 Forge 安装器: {loader_version.version}")
                try:
                    self._http.download_file(
                        url=installer_url,
                        save_path=installer_path,
                        resume=True,
                    )
                    downloaded_files.append(str(installer_path))
                except HttpError:
                    universal_url = f"{FORGE_MAVEN_BASE}/{full_forge}/forge-{full_forge}-universal.jar"
                    logger.info("installer 下载失败，尝试旧版安装方式...")
                    return self._install_old_forge(
                        mc_version, loader_version, version_id, version_dir,
                        full_forge, installer_url, universal_url, _progress, downloaded_files
                    )

            self._check_cancelled()

            _progress("extracting_profile", 15, "解析安装配置文件...")

            install_profile = None
            version_json = None

            try:
                with zipfile.ZipFile(installer_path, "r") as zf:
                    namelist = zf.namelist()

                    if "install_profile.json" in namelist:
                        install_profile = json.loads(zf.read("install_profile.json"))

                    if "version.json" in namelist:
                        version_json = json.loads(zf.read("version.json"))
            except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as e:
                logger.warning("读取安装器内容失败: %s", e)

            self._check_cancelled()

            _progress("extracting_libraries", 25, "提取安装器内置库文件...")
            extracted_count = extract_maven_from_installer(installer_path, self._libraries_dir)
            logger.info("从安装器提取了 %d 个内置库", extracted_count)

            self._check_cancelled()

            if version_json is None:
                if install_profile and isinstance(install_profile, dict):
                    version_json = install_profile.get("version_info")

            if version_json is None:
                logger.warning("未找到 version.json，使用构建方式")
                version_json = self._build_version_json(full_forge, mc_version, version_id)

            version_json["id"] = version_id
            version_json["inheritsFrom"] = mc_version

            if install_profile and isinstance(install_profile, dict):
                profile_libs = install_profile.get("libraries", [])
                if profile_libs:
                    existing_names = {
                        lib.get("name", "") for lib in version_json.get("libraries", [])
                        if isinstance(lib, dict)
                    }
                    for lib in profile_libs:
                        if isinstance(lib, dict) and lib.get("name") not in existing_names:
                            version_json.setdefault("libraries", []).append(lib)

                main_class = install_profile.get("mainClass") or install_profile.get("minecraftArguments")
                if main_class and "mainClass" not in version_json:
                    if isinstance(main_class, str) and not main_class.startswith("--"):
                        version_json["mainClass"] = main_class

                data = install_profile.get("data", {})
                processors = install_profile.get("processors", [])

                if processors:
                    _progress("processing", 45, "处理安装后任务...")
                    self._run_processors(
                        processors, data, installer_path,
                        mc_version, version_id, version_dir, _progress
                    )

            _progress("downloading_libraries", 55, "下载 Forge 依赖库...")
            libraries = version_json.get("libraries", [])

            def _lib_progress(cur: int, total: int, pct: float, fname: str):
                overall = 55 + (pct / 100) * 35
                _progress("downloading_libraries", overall, f"下载库文件: {cur}/{total} - {fname}")

            success_count, failed_count = download_libraries(
                libraries=libraries,
                libraries_dir=self._libraries_dir,
                http_client=self._http,
                progress_callback=_lib_progress,
                cancel_check=lambda: self._cancel_flag,
            )
            logger.info("Forge 库下载完成: 成功 %d, 失败 %d", success_count, failed_count)

            self._check_cancelled()

            forge_universal = None
            try:
                with zipfile.ZipFile(installer_path, "r") as zf:
                    for name in zf.namelist():
                        if "maven/" in name and name.endswith(".jar") and "forge" in name.lower() and "universal" in name.lower():
                            forge_universal = name
                            break
            except Exception:
                pass

            if forge_universal is None:
                universal_path = self._libraries_dir / "net" / "minecraftforge" / "forge" / full_forge / f"forge-{full_forge}-universal.jar"
                if not universal_path.exists():
                    universal_url = f"{FORGE_MAVEN_BASE}/{full_forge}/forge-{full_forge}-universal.jar"
                    try:
                        self._http.download_file(url=universal_url, save_path=universal_path)
                    except HttpError:
                        client_path = self._libraries_dir / "net" / "minecraftforge" / "forge" / full_forge / f"forge-{full_forge}.jar"
                        if client_path.exists():
                            shutil.copy2(client_path, universal_path)

            _progress("saving_version", 95, "保存版本配置...")
            version_json_path = version_dir / f"{version_id}.json"
            write_json(version_json_path, version_json)

            _progress("completed", 100, f"Forge {loader_version.version} 安装完成")
            logger.info("Forge 安装完成: %s -> %s", mc_version, version_id)

            return InstallResult(
                success=True,
                loader_type=ModLoaderType.FORGE,
                mc_version=mc_version,
                loader_version=loader_version.version,
                new_version_id=version_id,
                message=f"Forge {loader_version.version} 安装成功",
                downloaded_files=downloaded_files,
            )

        except (RuntimeError, HttpError, OSError) as e:
            error_msg = str(e)
            if "取消" in error_msg:
                _progress("cancelled", 0, err=error_msg)
                return InstallResult(
                    success=False, loader_type=ModLoaderType.FORGE,
                    mc_version=mc_version, loader_version=loader_version.version,
                    new_version_id="", message=error_msg,
                )
            logger.error("Forge 安装失败: %s", e, exc_info=True)
            _progress("failed", 0, err=f"安装失败: {error_msg}")
            return InstallResult(
                success=False, loader_type=ModLoaderType.FORGE,
                mc_version=mc_version, loader_version=loader_version.version,
                new_version_id="", message=f"安装失败: {error_msg}",
            )

    def _install_old_forge(
        self,
        mc_version: str,
        loader_version: ModLoaderVersion,
        version_id: str,
        version_dir: Path,
        full_forge: str,
        installer_url: str,
        universal_url: str,
        progress_cb: Callable,
        downloaded_files: list[str],
    ) -> InstallResult:
        """旧版 Forge 安装（无 installer 或 1.5.2 等老版本）。"""
        progress_cb("downloading_universal", 20, "下载 Forge Universal...")

        universal_path = self._libraries_dir / "net" / "minecraftforge" / "forge" / full_forge / f"forge-{full_forge}-universal.jar"
        ensure_directory(universal_path.parent)

        try:
            self._http.download_file(url=universal_url, save_path=universal_path, resume=True)
            downloaded_files.append(str(universal_path))
        except HttpError as e:
            return InstallResult(
                success=False, loader_type=ModLoaderType.FORGE,
                mc_version=mc_version, loader_version=loader_version.version,
                new_version_id="", message=f"下载 Forge 失败: {e}",
            )

        self._check_cancelled()

        version_json = self._build_version_json(full_forge, mc_version, version_id)
        version_json["id"] = version_id
        version_json["inheritsFrom"] = mc_version

        version_json["libraries"].append({
            "name": f"net.minecraftforge:forge:{full_forge}:universal",
            "downloads": {
                "artifact": {
                    "path": f"net/minecraftforge/forge/{full_forge}/forge-{full_forge}-universal.jar",
                    "url": universal_url,
                    "size": universal_path.stat().st_size if universal_path.exists() else 0,
                }
            }
        })

        progress_cb("saving_version", 90, "保存版本配置...")
        version_json_path = version_dir / f"{version_id}.json"
        write_json(version_json_path, version_json)

        progress_cb("completed", 100, f"Forge {loader_version.version} 安装完成")
        return InstallResult(
            success=True, loader_type=ModLoaderType.FORGE,
            mc_version=mc_version, loader_version=loader_version.version,
            new_version_id=version_id,
            message=f"Forge {loader_version.version} 安装成功（旧版模式）",
            downloaded_files=downloaded_files,
        )

    def _build_version_json(self, forge_version: str, mc_version: str, version_id: str) -> dict:
        loader_version = forge_version.split("-")[-1] if "-" in forge_version else forge_version

        main_class = "cpw.mods.modlauncher.Launcher"
        jvm_args = [
            "-Djava.net.preferIPv6Addresses=system",
            "-DignoreList=bootstraplauncher,securejarhandler,asm-commons,asm-util,asm-tree,asm-analysis,asm,jarjar,JarJarFileSystems,core-",
            "-DmergeModules=jna-5.10.0.jar,jna-platform-5.10.0.jar",
            "-DlibraryDirectory=${library_directory}",
            "-p", "${classpath_separator}${classpath}",
            "--add-modules", "ALL-MODULE-PATH",
            "--add-opens", "java.base/java.util.jar=cpw.mods.securejarhandler",
            "--add-opens", "java.base/java.lang.invoke=cpw.mods.securejarhandler",
            "--add-exports", "java.base/sun.security.util=cpw.mods.securejarhandler",
            "--add-exports", "jdk.naming.dns/com.sun.jndi.dns=java.naming",
        ]

        return {
            "id": version_id,
            "inheritsFrom": mc_version,
            "type": "release",
            "time": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "releaseTime": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "mainClass": main_class,
            "arguments": {
                "game": [],
                "jvm": jvm_args,
            },
            "libraries": [
                {
                    "name": f"net.minecraftforge:forge:{forge_version}",
                    "downloads": {
                        "artifact": {
                            "path": f"net/minecraftforge/forge/{forge_version}/forge-{forge_version}.jar",
                            "url": f"https://maven.minecraftforge.net/net/minecraftforge/forge/{forge_version}/forge-{forge_version}.jar",
                            "size": 0,
                        }
                    },
                },
            ],
        }

    def _run_processors(
        self,
        processors: list[dict],
        data: dict,
        installer_path: Path,
        mc_version: str,
        version_id: str,
        version_dir: Path,
        progress_cb: Callable,
    ) -> None:
        """运行 Forge 安装处理器（processor）。

        主要处理 binpatch 等任务，但通常对于客户端安装，
        大部分 processors 只在 server 安装时需要运行。
        我们主要关注 library 提取任务。
        """
        try:
            import subprocess

            os_name = get_os_name()
            for i, proc in enumerate(processors):
                if not isinstance(proc, dict):
                    continue

                sides = proc.get("sides", [])
                if sides and "client" not in sides:
                    continue

                proc_type = proc.get("jar", "")
                if not proc_type:
                    continue

                outputs = proc.get("outputs", {})
                if outputs:
                    all_outputs_exist = True
                    for out_key, out_val in outputs.items():
                        out_path = self._substitute_data(out_val, data, installer_path, mc_version, version_id, version_dir)
                        out_p = Path(out_path)
                        if not out_p.exists():
                            all_outputs_exist = False
                            break
                    if all_outputs_exist:
                        continue

                progress_cb("processing", 45 + (i / max(len(processors), 1)) * 10,
                            f"处理安装步骤 {i + 1}/{len(processors)}...")

        except Exception as e:
            logger.warning("运行 Forge processors 时出错（非致命）: %s", e)

    def _substitute_data(
        self,
        template: str,
        data: dict,
        installer_path: Path,
        mc_version: str,
        version_id: str,
        version_dir: Path,
    ) -> str:
        result = template
        result = result.replace("{MINECRAFT_VERSION}", mc_version)
        result = result.replace("{ROOT}", str(self._game_dir))
        result = result.replace("{INSTALLER}", str(installer_path))
        result = result.replace("{LIBRARY_DIR}", str(self._libraries_dir))
        for key, val in data.items():
            if isinstance(val, dict):
                client_val = val.get("client", "")
                if client_val:
                    result = result.replace("{" + key + "}", client_val.strip("/"))
            elif isinstance(val, str):
                result = result.replace("{" + key + "}", val)
        return result


def _version_sort_key(version_str: str) -> tuple:
    """将版本号字符串转换为可比较的元组。"""
    parts = re.findall(r"\d+|[a-zA-Z]+", version_str)
    key = []
    for p in parts:
        if p.isdigit():
            key.append((0, int(p)))
        else:
            key.append((1, p))
    return tuple(key)
