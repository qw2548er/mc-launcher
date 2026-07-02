"""Mojang API 客户端模块。

负责从 Mojang API 获取版本清单和版本元数据。
"""

import time
from pathlib import Path
from typing import Optional

from src.utils.file_utils import ensure_directory, read_json, write_json
from src.utils.http_utils import HttpClient, HttpError, get_http_client
from src.utils.logger import get_logger
from src.version.metadata import VersionEntry, VersionMetadata

logger = get_logger(__name__)

VERSION_MANIFEST_URL = (
    "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
)
RESOURCES_URL = "https://resources.download.minecraft.net/"

MANIFEST_CACHE_TTL = 3600


class VersionManifest:
    """版本清单数据。"""

    def __init__(self) -> None:
        self.latest_release: str = ""
        self.latest_snapshot: str = ""
        self.versions: list[VersionEntry] = []

    @property
    def releases(self) -> list[VersionEntry]:
        return [v for v in self.versions if v.is_release]

    @property
    def snapshots(self) -> list[VersionEntry]:
        return [v for v in self.versions if v.is_snapshot]

    @property
    def old_betas(self) -> list[VersionEntry]:
        return [v for v in self.versions if v.is_old_beta]

    @property
    def old_alphas(self) -> list[VersionEntry]:
        return [v for v in self.versions if v.is_old_alpha]

    def get_version(self, version_id: str) -> Optional[VersionEntry]:
        for v in self.versions:
            if v.id == version_id:
                return v
        return None


class VersionAPI:
    """Mojang 版本 API 客户端。"""

    def __init__(
        self,
        client: Optional[HttpClient] = None,
        cache_dir: Optional[Path] = None,
    ) -> None:
        self._client = client or get_http_client()
        self._cache_dir = cache_dir or Path(".minecraft/cache")
        self._manifest_cache_path = self._cache_dir / "version_manifest.json"
        self._manifest: Optional[VersionManifest] = None

    def fetch_manifest(
        self,
        force_refresh: bool = False,
        use_cache: bool = True,
    ) -> VersionManifest:
        """获取版本清单。

        Args:
            force_refresh: 是否强制刷新
            use_cache: 是否使用缓存

        Returns:
            VersionManifest 实例

        Raises:
            HttpError: 网络请求失败且无可用缓存
        """
        if use_cache and not force_refresh and self._is_manifest_cache_valid():
            cached = self._load_manifest_cache()
            if cached is not None:
                self._manifest = cached
                logger.debug("使用缓存的版本清单（共 %d 个版本）", len(cached.versions))
                return cached

        try:
            logger.info("从 Mojang API 获取版本清单...")
            data = self._client.get_json(VERSION_MANIFEST_URL)
            manifest = self._parse_manifest(data)
            self._manifest = manifest
            self._save_manifest_cache(data)
            logger.info(
                "版本清单获取成功: %d 个版本，最新正式版: %s，最新快照: %s",
                len(manifest.versions),
                manifest.latest_release,
                manifest.latest_snapshot,
            )
            return manifest
        except HttpError as e:
            logger.error("获取版本清单失败: %s", e)
            if self._manifest_cache_path.exists():
                cached = self._load_manifest_cache()
                if cached is not None:
                    logger.warning("使用过期缓存的版本清单")
                    self._manifest = cached
                    return cached
            raise

    def fetch_version_metadata(
        self,
        version_url: str,
        version_id: str = "",
    ) -> VersionMetadata:
        """获取指定版本的详细元数据。

        Args:
            version_url: 版本 metadata 的 URL
            version_id: 版本 ID

        Returns:
            VersionMetadata 实例

        Raises:
            HttpError: 网络请求失败
        """
        if version_id:
            local_meta = self._load_local_metadata(version_id)
            if local_meta is not None:
                return local_meta

        if version_id:
            cached_meta = self._load_metadata_cache(version_id)
            if cached_meta is not None:
                return cached_meta

        logger.info("获取版本元数据: %s", version_id or version_url)
        data = self._client.get_json(version_url)
        meta = VersionMetadata.from_json(data)

        if version_id:
            self._save_metadata_cache(version_id, data)

        return meta

    def get_manifest(self) -> Optional[VersionManifest]:
        return self._manifest

    def _parse_manifest(self, data: dict) -> VersionManifest:
        manifest = VersionManifest()
        latest = data.get("latest", {})
        manifest.latest_release = latest.get("release", "")
        manifest.latest_snapshot = latest.get("snapshot", "")

        for ver_data in data.get("versions", []):
            entry = VersionEntry.from_json(ver_data)
            manifest.versions.append(entry)

        return manifest

    def _is_manifest_cache_valid(self) -> bool:
        if not self._manifest_cache_path.exists():
            return False
        try:
            mtime = self._manifest_cache_path.stat().st_mtime
            return (time.time() - mtime) < MANIFEST_CACHE_TTL
        except OSError:
            return False

    def _load_manifest_cache(self) -> Optional[VersionManifest]:
        try:
            data = read_json(self._manifest_cache_path)
            if data and isinstance(data, dict):
                return self._parse_manifest(data)
        except Exception as e:
            logger.debug("加载版本清单缓存失败: %s", e)
        return None

    def _save_manifest_cache(self, data: dict) -> None:
        try:
            ensure_directory(self._cache_dir)
            write_json(self._manifest_cache_path, data)
        except Exception as e:
            logger.debug("保存版本清单缓存失败: %s", e)

    def _load_metadata_cache(self, version_id: str) -> Optional[VersionMetadata]:
        cache_path = self._cache_dir / "versions" / f"{version_id}.json"
        if not cache_path.exists():
            return None
        return VersionMetadata.from_file(cache_path)

    def _save_metadata_cache(self, version_id: str, data: dict) -> None:
        try:
            cache_path = self._cache_dir / "versions" / f"{version_id}.json"
            ensure_directory(cache_path.parent)
            write_json(cache_path, data)
        except Exception as e:
            logger.debug("保存版本元数据缓存失败: %s", e)

    def _load_local_metadata(self, version_id: str) -> Optional[VersionMetadata]:
        from src.utils.config import get_config
        config = get_config()
        game_dir = Path(config.get("game_directory", ".minecraft"))
        version_dir = game_dir / "versions" / version_id

        for name in [f"{version_id}.json", "version.json"]:
            meta_path = version_dir / name
            if meta_path.exists():
                meta = VersionMetadata.from_file(meta_path)
                if meta is not None:
                    logger.debug("从本地加载版本元数据: %s", version_id)
                    return meta
        return None
