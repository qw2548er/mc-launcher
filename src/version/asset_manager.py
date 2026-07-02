"""资源文件管理器模块。

负责 Minecraft 资源文件（assets）的索引解析、下载、缓存和管理。
支持资源替换（材质包/资源包）。
"""

import json
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
    read_json,
    safe_delete,
    verify_sha1,
    write_json,
)
from src.utils.http_utils import (
    DownloadProgressInfo,
    HttpClient,
    HttpError,
    get_http_client,
)
from src.utils.logger import get_logger
from src.version.api import RESOURCES_URL
from src.version.downloader import (
    DownloadItem,
    DownloadQueue,
    DownloadReport,
    DownloadStatus,
)

logger = get_logger(__name__)


@dataclass
class AssetObject:
    """单个资源对象信息。"""

    hash: str = ""
    size: int = 0

    @property
    def hash_prefix(self) -> str:
        return self.hash[:2] if len(self.hash) >= 2 else ""

    @property
    def object_path(self) -> str:
        return f"{self.hash_prefix}/{self.hash}"

    @property
    def url(self) -> str:
        return f"{RESOURCES_URL}{self.object_path}"


@dataclass
class AssetIndex:
    """资源索引数据。"""

    id: str = ""
    objects: dict[str, AssetObject] = field(default_factory=dict)
    map_to_resources: bool = False
    virtual: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any], index_id: str = "") -> "AssetIndex":
        idx = cls()
        idx.id = index_id
        idx.raw = data
        idx.map_to_resources = data.get("map_to_resources", False)
        idx.virtual = data.get("virtual", False)

        objects_data = data.get("objects", {})
        for path, obj_data in objects_data.items():
            obj = AssetObject(
                hash=obj_data.get("hash", ""),
                size=obj_data.get("size", 0),
            )
            idx.objects[path] = obj

        return idx

    @classmethod
    def from_file(cls, file_path: Path, index_id: str = "") -> Optional["AssetIndex"]:
        data = read_json(file_path)
        if data is None or not isinstance(data, dict):
            return None
        if not index_id:
            index_id = file_path.stem
        return cls.from_json(data, index_id)

    @property
    def total_size(self) -> int:
        return sum(obj.size for obj in self.objects.values())

    @property
    def total_count(self) -> int:
        return len(self.objects)


class AssetManager:
    """Minecraft 资源管理器。

    负责资源索引解析、资源文件下载、缓存管理、资源包替换等。
    """

    def __init__(
        self,
        game_dir: Optional[Path] = None,
        client: Optional[HttpClient] = None,
        max_workers: Optional[int] = None,
        max_speed: float = 0,
    ) -> None:
        self._config = get_config()
        self._game_dir = game_dir or Path(self._config.get("game_directory", ".minecraft"))
        self._assets_dir = self._game_dir / "assets"
        self._indexes_dir = self._assets_dir / "indexes"
        self._objects_dir = self._assets_dir / "objects"
        self._resourcepacks_dir = self._game_dir / "resourcepacks"
        self._client = client or HttpClient(max_speed=max_speed)
        self._max_workers = max_workers or self._config.get("download.max_threads", 4)
        self._queue = DownloadQueue(
            max_workers=self._max_workers,
            client=self._client,
            max_speed=max_speed,
        )

    @property
    def assets_dir(self) -> Path:
        return self._assets_dir

    @property
    def indexes_dir(self) -> Path:
        return self._indexes_dir

    @property
    def objects_dir(self) -> Path:
        return self._objects_dir

    @property
    def resourcepacks_dir(self) -> Path:
        return self._resourcepacks_dir

    @property
    def queue(self) -> DownloadQueue:
        return self._queue

    def set_progress_callback(self, callback: Callable[[DownloadReport], None]) -> None:
        self._queue.set_progress_callback(callback)

    def set_speed_limit(self, bytes_per_second: float) -> None:
        self._queue.set_speed_limit(bytes_per_second)

    def get_asset_index_path(self, index_id: str) -> Path:
        """获取资源索引文件路径。"""
        return self._indexes_dir / f"{index_id}.json"

    def get_object_path(self, asset_hash: str) -> Path:
        """根据哈希获取资源对象文件路径。"""
        prefix = asset_hash[:2]
        return self._objects_dir / prefix / asset_hash

    def load_asset_index(self, index_id: str) -> Optional[AssetIndex]:
        """加载资源索引。

        Args:
            index_id: 资源索引 ID（如 "1.20", "3" 等）

        Returns:
            AssetIndex 实例，不存在返回 None
        """
        index_path = self.get_asset_index_path(index_id)
        if not index_path.is_file():
            return None
        return AssetIndex.from_file(index_path, index_id)

    def download_asset_index(
        self,
        index_url: str,
        index_id: str,
        expected_sha1: str = "",
        expected_size: int = 0,
    ) -> Optional[AssetIndex]:
        """下载并保存资源索引。

        Args:
            index_url: 索引文件 URL
            index_id: 索引 ID
            expected_sha1: 期望 SHA1
            expected_size: 期望大小

        Returns:
            AssetIndex 实例，失败返回 None
        """
        ensure_directory(self._indexes_dir)
        index_path = self.get_asset_index_path(index_id)

        if file_exists(index_path) and expected_sha1:
            if verify_sha1(index_path, expected_sha1):
                logger.debug("资源索引已存在: %s", index_path)
                return self.load_asset_index(index_id)

        item = DownloadItem(
            url=index_url,
            path=index_path,
            sha1=expected_sha1,
            size=expected_size,
            tag="asset_index",
            priority=100,
        )
        self._queue.add_item(item)
        self._queue.start()
        self._queue.wait_completion()

        if item.status == DownloadStatus.COMPLETED:
            logger.info("资源索引下载完成: %s", index_id)
            return self.load_asset_index(index_id)
        logger.error("资源索引下载失败: %s", index_id)
        return None

    def get_missing_assets(self, index: AssetIndex) -> list[tuple[str, AssetObject]]:
        """获取缺失的资源文件列表。

        Args:
            index: 资源索引

        Returns:
            (资源路径, AssetObject) 列表
        """
        missing: list[tuple[str, AssetObject]] = []
        for path, obj in index.objects.items():
            obj_path = self.get_object_path(obj.hash)
            if not obj_path.is_file():
                missing.append((path, obj))
            elif obj.size > 0 and obj_path.stat().st_size != obj.size:
                missing.append((path, obj))
        return missing

    def is_asset_complete(self, index: AssetIndex) -> bool:
        """检查资源文件是否完整。

        Args:
            index: 资源索引

        Returns:
            True 表示所有资源都存在
        """
        return len(self.get_missing_assets(index)) == 0

    def get_asset_completion_stats(self, index: AssetIndex) -> tuple[int, int]:
        """获取资源完成统计。

        Returns:
            (已存在数量, 总数量)
        """
        total = index.total_count
        missing = len(self.get_missing_assets(index))
        return total - missing, total

    def download_assets(
        self,
        index: AssetIndex,
        only_missing: bool = True,
    ) -> bool:
        """下载资源文件。

        Args:
            index: 资源索引
            only_missing: 是否只下载缺失的资源

        Returns:
            True 表示全部下载成功
        """
        tasks: list[DownloadItem] = []

        for path, obj in index.objects.items():
            obj_path = self.get_object_path(obj.hash)
            if only_missing and obj_path.is_file():
                if obj.size <= 0 or obj_path.stat().st_size == obj.size:
                    continue

            tasks.append(DownloadItem(
                url=obj.url,
                path=obj_path,
                sha1=obj.hash,
                size=obj.size,
                tag=f"asset:{path}",
                priority=10,
            ))

        if not tasks:
            logger.info("所有资源文件已就绪")
            return True

        logger.info("需要下载 %d 个资源文件，总大小约 %s", len(tasks), format_file_size(sum(t.size for t in tasks)))
        self._queue.add_items(tasks)
        self._queue.start()
        self._queue.wait_completion()

        success = self._queue.report.failed_files == 0
        if success:
            logger.info("资源文件下载完成")
        else:
            logger.error(
                "资源文件下载完成，失败 %d 个",
                self._queue.report.failed_files,
            )
        return success

    def ensure_assets(
        self,
        index_id: str,
        index_url: str = "",
        index_sha1: str = "",
        index_size: int = 0,
        progress_callback: Optional[Callable[[DownloadReport], None]] = None,
    ) -> bool:
        """确保资源文件完整（一站式方法）。

        如果索引不存在则下载索引，如果资源缺失则下载资源。

        Args:
            index_id: 资源索引 ID
            index_url: 索引文件 URL（本地不存在时需要）
            index_sha1: 索引期望 SHA1
            index_size: 索引期望大小
            progress_callback: 进度回调

        Returns:
            True 表示资源完整
        """
        if progress_callback:
            self.set_progress_callback(progress_callback)

        index = self.load_asset_index(index_id)
        if index is None and index_url:
            index = self.download_asset_index(index_url, index_id, index_sha1, index_size)

        if index is None:
            logger.error("无法加载资源索引: %s", index_id)
            return False

        if self.is_asset_complete(index):
            logger.debug("资源文件完整: %s", index_id)
            return True

        return self.download_assets(index, only_missing=True)

    def apply_resource_pack(
        self,
        pack_path: Path,
        index: AssetIndex,
    ) -> int:
        """应用资源包（替换资源文件）。

        将资源包中的文件复制到 objects 目录，替换原有资源。
        注意：这会修改原始资源缓存，请谨慎使用。

        Args:
            pack_path: 资源包路径（zip 或目录）
            index: 当前资源索引

        Returns:
            替换的文件数量
        """
        import zipfile

        replaced = 0

        if pack_path.is_dir():
            for asset_path in pack_path.rglob("*"):
                if not asset_path.is_file():
                    continue
                rel_path = asset_path.relative_to(pack_path)
                rel_str = str(rel_path).replace("\\", "/")

                if rel_str.startswith("assets/"):
                    parts = rel_str.split("/", 2)
                    if len(parts) >= 3:
                        game_path = parts[2]
                        if game_path in index.objects:
                            obj = index.objects[game_path]
                            dest = self.get_object_path(obj.hash)
                            ensure_directory(dest.parent)
                            shutil.copy2(asset_path, dest)
                            replaced += 1
        elif pack_path.is_file() and pack_path.suffix == ".zip":
            with zipfile.ZipFile(pack_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith("/"):
                        continue
                    if member.startswith("assets/"):
                        parts = member.split("/", 2)
                        if len(parts) >= 3:
                            game_path = parts[2]
                            if game_path in index.objects:
                                obj = index.objects[game_path]
                                dest = self.get_object_path(obj.hash)
                                ensure_directory(dest.parent)
                                with zf.open(member) as src, open(dest, "wb") as dst:
                                    shutil.copyfileobj(src, dst)
                                replaced += 1

        logger.info("应用资源包 %s，替换了 %d 个文件", pack_path.name, replaced)
        return replaced

    def list_resource_packs(self) -> list[Path]:
        """列出可用的资源包。

        Returns:
            资源包路径列表
        """
        ensure_directory(self._resourcepacks_dir)
        packs: list[Path] = []
        for item in self._resourcepacks_dir.iterdir():
            if item.is_dir():
                packs.append(item)
            elif item.suffix.lower() == ".zip":
                packs.append(item)
        return sorted(packs)

    def delete_object(self, asset_hash: str) -> bool:
        """删除指定资源对象。"""
        obj_path = self.get_object_path(asset_hash)
        return safe_delete(obj_path)

    def get_object_size(self, asset_hash: str) -> int:
        """获取资源对象大小。"""
        obj_path = self.get_object_path(asset_hash)
        if obj_path.is_file():
            return obj_path.stat().st_size
        return 0

    def get_total_cache_size(self) -> int:
        """获取资源缓存总大小。"""
        total = 0
        if self._objects_dir.is_dir():
            for f in self._objects_dir.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        return total

    def clean_unused_objects(self, used_indexes: list[str]) -> int:
        """清理未使用的资源对象。

        Args:
            used_indexes: 正在使用的资源索引 ID 列表

        Returns:
            清理的文件数量
        """
        used_hashes: set[str] = set()
        for idx_id in used_indexes:
            idx = self.load_asset_index(idx_id)
            if idx:
                for obj in idx.objects.values():
                    used_hashes.add(obj.hash)

        cleaned = 0
        if self._objects_dir.is_dir():
            for prefix_dir in self._objects_dir.iterdir():
                if not prefix_dir.is_dir():
                    continue
                for obj_file in prefix_dir.iterdir():
                    if obj_file.is_file() and obj_file.name not in used_hashes:
                        if safe_delete(obj_file):
                            cleaned += 1

        logger.info("清理了 %d 个未使用的资源文件", cleaned)
        return cleaned

    def pause(self) -> None:
        self._queue.pause()

    def resume(self) -> None:
        self._queue.resume()

    def cancel(self) -> None:
        self._queue.cancel()

    def is_running(self) -> bool:
        return self._queue.is_running
