"""版本管理器模块。

管理本地已安装版本和远程版本清单，提供：
- 版本清单获取与缓存
- 版本下载与安装
- 本地版本扫描与完整性校验
- 版本删除、重命名、复制
- 资源文件集成管理
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from src.utils.config import get_config
from src.utils.file_utils import (
    calculate_sha1,
    ensure_directory,
    file_exists,
    format_file_size,
    get_directory_size,
    read_json,
    safe_copy,
    safe_delete,
    verify_sha1,
    write_json,
)
from src.utils.http_utils import HttpClient, HttpError, get_http_client
from src.utils.logger import get_logger
from src.version.api import RESOURCES_URL, VersionAPI, VersionManifest
from src.version.asset_manager import AssetIndex, AssetManager
from src.version.downloader import (
    DownloadReport,
    DownloadStatus,
    VersionDownloader,
)
from src.version.metadata import (
    LibraryInfo,
    VersionDownload,
    VersionEntry,
    VersionMetadata,
)

logger = get_logger(__name__)


@dataclass
class VersionValidationResult:
    """版本完整性校验结果。"""

    version_id: str = ""
    is_valid: bool = False
    json_exists: bool = False
    jar_exists: bool = False
    jar_valid: bool = False
    asset_index_exists: bool = False
    libraries_missing: list[str] = field(default_factory=list)
    natives_missing: list[str] = field(default_factory=list)
    assets_missing: int = 0

    @property
    def issues(self) -> list[str]:
        issues: list[str] = []
        if not self.json_exists:
            issues.append("version.json 缺失")
        if not self.jar_exists:
            issues.append("客户端 jar 缺失")
        elif not self.jar_valid:
            issues.append("客户端 jar 校验失败")
        if not self.asset_index_exists:
            issues.append("资源索引缺失")
        if self.libraries_missing:
            issues.append(f"{len(self.libraries_missing)} 个库文件缺失")
        if self.natives_missing:
            issues.append(f"{len(self.natives_missing)} 个 native 库缺失")
        if self.assets_missing > 0:
            issues.append(f"{self.assets_missing} 个资源文件缺失")
        return issues


class VersionManager:
    """Minecraft 版本管理器。

    负责版本的获取、安装、卸载、查询、重命名、复制、完整性校验等操作。
    """

    def __init__(
        self,
        game_dir: Optional[Path] = None,
        client: Optional[HttpClient] = None,
    ) -> None:
        self._config = get_config()
        self._game_dir = game_dir or Path(
            self._config.get("game_directory", ".minecraft")
        )
        self._versions_dir = self._game_dir / "versions"
        self._libraries_dir = self._game_dir / "libraries"
        self._assets_dir = self._game_dir / "assets"
        self._client = client or get_http_client()
        self._api = VersionAPI(
            client=self._client,
            cache_dir=self._game_dir / "cache",
        )
        self._downloader: Optional[VersionDownloader] = None
        self._asset_manager = AssetManager(
            game_dir=self._game_dir,
            client=self._client,
        )

    @property
    def game_dir(self) -> Path:
        return self._game_dir

    @property
    def versions_dir(self) -> Path:
        return self._versions_dir

    @property
    def api(self) -> VersionAPI:
        return self._api

    @property
    def asset_manager(self) -> AssetManager:
        return self._asset_manager

    @property
    def downloader(self) -> Optional[VersionDownloader]:
        return self._downloader

    # ── 远程版本清单 ─────────────────────────────────────────

    def fetch_remote_versions(
        self,
        force_refresh: bool = False,
    ) -> VersionManifest:
        """获取远程版本清单。

        Args:
            force_refresh: 是否强制刷新（忽略缓存）

        Returns:
            VersionManifest 实例
        """
        return self._api.fetch_manifest(force_refresh=force_refresh)

    def get_available_versions(
        self,
        show_snapshots: bool = False,
        show_beta: bool = False,
        show_alpha: bool = False,
    ) -> list[VersionEntry]:
        """获取可用的版本列表（按发布时间降序）。

        Args:
            show_snapshots: 是否显示快照版
            show_beta: 是否显示旧 Beta 版
            show_alpha: 是否显示旧 Alpha 版

        Returns:
            过滤后的版本条目列表
        """
        manifest = self.fetch_remote_versions()
        result: list[VersionEntry] = []

        for ver in manifest.versions:
            if ver.is_release:
                result.append(ver)
            elif ver.is_snapshot and show_snapshots:
                result.append(ver)
            elif ver.is_old_beta and show_beta:
                result.append(ver)
            elif ver.is_old_alpha and show_alpha:
                result.append(ver)

        return result

    # ── 本地版本管理 ─────────────────────────────────────────

    def get_installed_versions(self) -> list[VersionMetadata]:
        """获取本地已安装的版本列表。

        Returns:
            本地已安装的版本元数据列表
        """
        result: list[VersionMetadata] = []
        if not self._versions_dir.is_dir():
            return result

        for version_dir in sorted(self._versions_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            meta = self._load_local_version(version_dir.name)
            if meta is not None:
                result.append(meta)

        return result

    def get_local_version(self, version_id: str) -> Optional[VersionMetadata]:
        """获取本地指定版本的元数据。"""
        return self._load_local_version(version_id)

    def is_installed(self, version_id: str) -> bool:
        """检查指定版本是否已安装。"""
        version_dir = self._versions_dir / version_id
        if not version_dir.is_dir():
            return False
        jar_path = version_dir / f"{version_id}.jar"
        json_path = version_dir / f"{version_id}.json"
        return jar_path.is_file() and json_path.is_file()

    def validate_version(self, version_id: str, check_assets: bool = False) -> VersionValidationResult:
        """校验本地版本完整性。

        Args:
            version_id: 版本 ID
            check_assets: 是否也校验资源文件

        Returns:
            VersionValidationResult 校验结果
        """
        result = VersionValidationResult(version_id=version_id)
        version_dir = self._versions_dir / version_id
        os_name = _get_os_name()

        json_path = version_dir / f"{version_id}.json"
        result.json_exists = json_path.is_file()

        meta = self._load_local_version(version_id)
        if meta is None:
            return result

        jar_path = version_dir / f"{version_id}.jar"
        result.jar_exists = jar_path.is_file()
        if result.jar_exists and meta.client_download.sha1:
            result.jar_valid = verify_sha1(jar_path, meta.client_download.sha1)

        if meta.asset_index.url:
            index_path = self._assets_dir / "indexes" / f"{meta.assets}.json"
            result.asset_index_exists = index_path.is_file()

        libraries_dir = self._libraries_dir
        for lib in meta.libraries:
            if not lib.matches_os(os_name):
                continue

            if lib.natives and os_name in lib.natives:
                classifier_name = lib.natives[os_name].replace("${arch}", _get_arch())
                cls_dl = lib.downloads.classifiers.get(classifier_name)
                if cls_dl and cls_dl.url:
                    path = libraries_dir / (cls_dl.path or _build_maven_path(lib, classifier_name))
                    if not path.is_file():
                        result.natives_missing.append(str(path))
                    elif cls_dl.sha1 and not verify_sha1(path, cls_dl.sha1):
                        result.natives_missing.append(str(path))
            elif not lib.natives:
                artifact = lib.downloads.artifact
                if artifact and artifact.url:
                    path = libraries_dir / (artifact.path or _build_maven_path(lib))
                    if not path.is_file():
                        result.libraries_missing.append(str(path))
                    elif artifact.sha1 and not verify_sha1(path, artifact.sha1):
                        result.libraries_missing.append(str(path))

        if check_assets and meta.assets:
            index = self._asset_manager.load_asset_index(meta.assets)
            if index:
                result.assets_missing = len(self._asset_manager.get_missing_assets(index))

        result.is_valid = (
            result.json_exists
            and result.jar_exists
            and result.jar_valid
            and not result.libraries_missing
            and not result.natives_missing
            and (not check_assets or result.assets_missing == 0)
        )
        return result

    def install_version(
        self,
        version_id: str,
        progress_callback: Optional[Callable[[DownloadReport], None]] = None,
        include_assets: bool = True,
        include_server: bool = False,
    ) -> bool:
        """安装指定版本。

        下载版本元数据、客户端 jar、库文件、资源文件等。

        Args:
            version_id: 版本 ID
            progress_callback: 下载进度回调
            include_assets: 是否同时下载资源文件
            include_server: 是否同时下载服务端 jar

        Returns:
            True 表示安装成功
        """
        manifest = self.fetch_remote_versions()
        entry = manifest.get_version(version_id)
        if entry is None:
            logger.error("版本不存在: %s", version_id)
            return False

        logger.info("开始安装版本: %s", version_id)
        try:
            meta = self._api.fetch_version_metadata(entry.url, version_id)
        except HttpError as e:
            logger.error("获取版本元数据失败: %s", e)
            return False

        version_dir = self._versions_dir / version_id
        ensure_directory(version_dir)
        meta_path = version_dir / f"{version_id}.json"
        write_json(meta_path, meta.raw)
        logger.debug("已保存 version.json: %s", meta_path)

        downloader = VersionDownloader(
            client=self._client,
            game_dir=self._game_dir,
        )
        self._downloader = downloader
        if progress_callback:
            downloader.set_progress_callback(progress_callback)

        success = downloader.download_version(
            meta,
            include_client=True,
            include_server=include_server,
            include_libraries=True,
            include_natives=True,
            include_assets=include_assets,
        )

        self._downloader = None

        if success:
            self._config.set("default_version", version_id)
            self._config.save()
            logger.info("版本 %s 安装完成", version_id)
        else:
            logger.error("版本 %s 安装失败", version_id)

        return success

    def repair_version(
        self,
        version_id: str,
        progress_callback: Optional[Callable[[DownloadReport], None]] = None,
    ) -> bool:
        """修复版本（重新下载缺失/损坏的文件）。

        Args:
            version_id: 版本 ID
            progress_callback: 下载进度回调

        Returns:
            True 表示修复成功
        """
        meta = self._load_local_version(version_id)
        if meta is None:
            logger.error("版本未安装: %s", version_id)
            return False

        logger.info("开始修复版本: %s", version_id)
        downloader = VersionDownloader(
            client=self._client,
            game_dir=self._game_dir,
        )
        self._downloader = downloader
        if progress_callback:
            downloader.set_progress_callback(progress_callback)

        success = downloader.download_version(meta)
        self._downloader = None

        if success:
            logger.info("版本 %s 修复完成", version_id)
        else:
            logger.error("版本 %s 修复失败", version_id)

        return success

    def uninstall_version(self, version_id: str, delete_assets: bool = False) -> bool:
        """卸载指定版本。

        Args:
            version_id: 版本 ID
            delete_assets: 是否同时删除关联的资源文件（谨慎使用）

        Returns:
            True 表示卸载成功
        """
        version_dir = self._versions_dir / version_id
        if not version_dir.is_dir():
            logger.warning("版本未安装: %s", version_id)
            return False

        default_ver = self._config.get("default_version", "")
        if default_ver == version_id:
            self._config.set("default_version", "")
            self._config.save()

        if safe_delete(version_dir):
            logger.info("版本 %s 已卸载", version_id)

            if delete_assets:
                meta = self.get_local_version(version_id)
                if meta and meta.assets:
                    index = self._asset_manager.load_asset_index(meta.assets)
                    if index:
                        installed = self.get_installed_versions()
                        used_indexes = {m.assets for m in installed if m.assets and m.id != version_id}
                        self._asset_manager.clean_unused_objects(list(used_indexes))
                        index_path = self._assets_dir / "indexes" / f"{meta.assets}.json"
                        safe_delete(index_path)

            return True
        return False

    def rename_version(self, old_id: str, new_id: str) -> bool:
        """重命名版本。

        Args:
            old_id: 原版本 ID
            new_id: 新版本 ID

        Returns:
            True 表示重命名成功
        """
        old_dir = self._versions_dir / old_id
        new_dir = self._versions_dir / new_id

        if not old_dir.is_dir():
            logger.error("版本未安装: %s", old_id)
            return False
        if new_dir.exists():
            logger.error("目标版本已存在: %s", new_id)
            return False

        old_json = old_dir / f"{old_id}.json"
        old_jar = old_dir / f"{old_id}.jar"
        new_json = new_dir / f"{new_id}.json"
        new_jar = new_dir / f"{new_id}.jar"

        try:
            ensure_directory(new_dir)

            meta_data = read_json(old_json)
            if meta_data and isinstance(meta_data, dict):
                meta_data["id"] = new_id
                if meta_data.get("jar") == old_id:
                    meta_data["jar"] = new_id
                write_json(new_json, meta_data)

            if old_jar.is_file():
                shutil.move(str(old_jar), str(new_jar))

            for item in old_dir.iterdir():
                if item.name not in (f"{old_id}.json", f"{old_id}.jar"):
                    dest = new_dir / item.name
                    if item.is_dir():
                        shutil.move(str(item), str(dest))
                    else:
                        shutil.move(str(item), str(dest))

            safe_delete(old_dir)

            default_ver = self._config.get("default_version", "")
            if default_ver == old_id:
                self._config.set("default_version", new_id)
                self._config.save()

            logger.info("版本已重命名: %s -> %s", old_id, new_id)
            return True
        except OSError as e:
            logger.error("重命名版本失败: %s", e)
            safe_delete(new_dir)
            return False

    def copy_version(self, source_id: str, target_id: str) -> bool:
        """复制版本。

        Args:
            source_id: 源版本 ID
            target_id: 目标版本 ID

        Returns:
            True 表示复制成功
        """
        source_dir = self._versions_dir / source_id
        target_dir = self._versions_dir / target_id

        if not source_dir.is_dir():
            logger.error("源版本未安装: %s", source_id)
            return False
        if target_dir.exists():
            logger.error("目标版本已存在: %s", target_id)
            return False

        source_json = source_dir / f"{source_id}.json"
        target_json = target_dir / f"{target_id}.json"

        try:
            ensure_directory(target_dir)

            meta_data = read_json(source_json)
            if meta_data and isinstance(meta_data, dict):
                meta_data["id"] = target_id
                if meta_data.get("jar") == source_id:
                    meta_data["jar"] = source_id
                write_json(target_json, meta_data)

            for item in source_dir.iterdir():
                if item.name == f"{source_id}.json":
                    continue
                dest = target_dir / (item.name if item.name != f"{source_id}.jar" else f"{target_id}.jar")
                if item.is_dir():
                    shutil.copytree(str(item), str(dest))
                else:
                    shutil.copy2(str(item), str(dest))

            logger.info("版本已复制: %s -> %s", source_id, target_id)
            return True
        except OSError as e:
            logger.error("复制版本失败: %s", e)
            safe_delete(target_dir)
            return False

    def get_version_size(self, version_id: str) -> int:
        """获取版本目录的总大小（字节）。"""
        version_dir = self._versions_dir / version_id
        return get_directory_size(version_dir)

    def cancel_install(self) -> None:
        """取消正在进行的安装。"""
        if self._downloader:
            self._downloader.cancel()

    def refresh_manifest(self) -> None:
        """强制刷新版本清单缓存。"""
        self._api.fetch_manifest(force_refresh=True)

    # ── 内部方法 ──────────────────────────────────────────────

    def _load_local_version(self, version_id: str) -> Optional[VersionMetadata]:
        """从本地加载版本元数据。"""
        version_dir = self._versions_dir / version_id
        if not version_dir.is_dir():
            return None

        for name in [f"{version_id}.json", "version.json"]:
            meta_path = version_dir / name
            if meta_path.is_file():
                meta = VersionMetadata.from_file(meta_path)
                if meta is not None:
                    return meta
        return None


# ── 工具函数 ──────────────────────────────────────────────────

def _get_os_name() -> str:
    """获取当前操作系统名称（Mojang 格式）。"""
    import sys
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "osx"
    return "linux"


def _get_arch() -> str:
    """获取系统架构。"""
    import platform
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        return "64"
    elif machine in ("arm64", "aarch64"):
        return "arm64"
    elif "32" in machine or machine == "i386":
        return "32"
    return "64"


def _build_maven_path(lib: LibraryInfo, classifier: str = "") -> str:
    """根据 Maven 坐标构建库文件相对路径。"""
    group = lib.group_id.replace(".", "/")
    artifact = lib.artifact_id
    version = lib.version
    if classifier:
        return f"{group}/{artifact}/{version}/{artifact}-{version}-{classifier}.jar"
    return f"{group}/{artifact}/{version}/{artifact}-{version}.jar"
