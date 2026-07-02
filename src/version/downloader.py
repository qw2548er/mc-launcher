"""版本文件下载器模块。

负责下载 Minecraft 客户端 jar、libraries、assets 等文件。
基于 requests + ThreadPoolExecutor，支持：
- 多线程并行下载
- 断点续传
- SHA1 校验
- 下载队列管理
- 暂停/继续/取消
- 速度限制
- 进度回调（含速度、剩余时间估计）
"""

import platform
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from src.utils.config import get_config
from src.utils.file_utils import (
    calculate_sha1,
    ensure_directory,
    file_exists,
    format_file_size,
    verify_sha1,
    write_json,
)
from src.utils.http_utils import (
    DownloadProgressInfo,
    HttpClient,
    HttpError,
    RateLimiter,
    get_http_client,
)
from src.utils.logger import get_logger
from src.version.metadata import (
    LibraryInfo,
    VersionMetadata,
)

logger = get_logger(__name__)


class DownloadStatus(Enum):
    """下载任务状态。"""

    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


MAX_RETRIES = 3


@dataclass
class DownloadItem:
    """单个下载项。"""

    url: str
    path: Path
    sha1: str = ""
    size: int = 0
    tag: str = ""  # 用于标识文件类型（client/lib/asset等）
    priority: int = 0  # 优先级，数字越大越优先
    status: DownloadStatus = DownloadStatus.PENDING
    error: str = ""
    downloaded: int = 0
    speed: float = 0.0
    retry_count: int = 0
    _future: Optional[Future] = field(default=None, repr=False)

    @property
    def is_done(self) -> bool:
        return self.status in (
            DownloadStatus.COMPLETED,
            DownloadStatus.SKIPPED,
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
        )

    @property
    def percent(self) -> float:
        if self.size <= 0:
            return 0.0
        return (self.downloaded / self.size) * 100


@dataclass
class DownloadReport:
    """下载总体进度报告。"""

    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    cancelled_files: int = 0
    total_size: int = 0
    downloaded_size: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    current_speed: float = 0.0
    active_items: int = 0
    current_item: Optional[DownloadItem] = None

    @property
    def elapsed(self) -> float:
        if self.start_time == 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.monotonic()
        return end - self.start_time

    @property
    def average_speed(self) -> float:
        if self.elapsed <= 0:
            return 0.0
        return self.downloaded_size / self.elapsed

    @property
    def progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return (self.downloaded_size / self.total_size) * 100

    @property
    def remaining_time(self) -> float:
        if self.current_speed <= 0:
            if self.average_speed > 0:
                return max(0, (self.total_size - self.downloaded_size) / self.average_speed)
            return 0.0
        return max(0, (self.total_size - self.downloaded_size) / self.current_speed)

    @property
    def speed_formatted(self) -> str:
        return f"{format_file_size(self.current_speed)}/s"


class DownloadQueue:
    """下载队列管理器。

    管理下载任务队列，支持：
    - 添加/移除任务
    - 设置并发数
    - 暂停/继续/取消
    - 速度限制
    - 进度回调
    """

    def __init__(
        self,
        max_workers: int = 4,
        client: Optional[HttpClient] = None,
        max_speed: float = 0,
        item_completed_callback: Optional[Callable[[DownloadItem], None]] = None,
    ) -> None:
        self._client = client or HttpClient(max_speed=max_speed)
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._items: list[DownloadItem] = []
        self._report = DownloadReport()
        self._progress_callback: Optional[Callable[[DownloadReport], None]] = None
        self._item_completed_callback = item_completed_callback
        self._lock = threading.RLock()
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._new_items_event = threading.Event()
        self._running = False
        self._completed_count = 0
        self._total_speed = 0.0
        self._speed_lock = threading.Lock()
        self._active_speeds: dict[str, float] = {}

    @property
    def report(self) -> DownloadReport:
        return self._report

    @property
    def items(self) -> list[DownloadItem]:
        with self._lock:
            return list(self._items)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def set_progress_callback(self, callback: Callable[[DownloadReport], None]) -> None:
        """设置进度回调。"""
        self._progress_callback = callback

    def set_max_workers(self, max_workers: int) -> None:
        """设置最大并发线程数。"""
        self._max_workers = max(1, max_workers)
        if self._executor:
            self._executor._max_workers = self._max_workers

    def set_speed_limit(self, bytes_per_second: float) -> None:
        """设置速度限制（字节/秒），0 表示不限速。"""
        self._client.set_speed_limit(bytes_per_second)

    def add_item(self, item: DownloadItem) -> None:
        """添加下载项到队列。"""
        with self._lock:
            self._items.append(item)
            self._report.total_files += 1
            self._report.total_size += item.size
            self._new_items_event.set()

    def add_items(self, items: list[DownloadItem]) -> None:
        """批量添加下载项。"""
        with self._lock:
            self._items.extend(items)
            self._report.total_files += len(items)
            self._report.total_size += sum(i.size for i in items)
            self._new_items_event.set()

    def clear_completed(self) -> None:
        """清除已完成的任务记录。"""
        with self._lock:
            self._items = [i for i in self._items if not i.is_done]

    def start(self) -> None:
        """开始下载队列。"""
        if self._running:
            return
        self._running = True
        self._pause_event.set()
        self._cancel_event.clear()
        self._new_items_event.clear()
        self._client.reset_state()
        self._report = DownloadReport()
        self._report.start_time = time.monotonic()
        self._completed_count = 0
        self._active_speeds.clear()

        with self._lock:
            pending = [i for i in self._items if i.status in (DownloadStatus.PENDING, DownloadStatus.QUEUED, DownloadStatus.FAILED)]
            for i in pending:
                i.status = DownloadStatus.QUEUED
                i.error = ""
                i.downloaded = 0
            self._report.total_files = len(self._items)
            self._report.total_size = sum(i.size for i in self._items)

        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        self._dispatch_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._dispatch_thread.start()
        logger.info("下载队列已启动，并发数: %d", self._max_workers)

    def pause(self) -> None:
        """暂停下载。"""
        self._pause_event.clear()
        self._client.pause()
        logger.info("下载已暂停")

    def resume(self) -> None:
        """继续下载。"""
        self._pause_event.set()
        self._client.resume()
        logger.info("下载已继续")

    def cancel(self) -> None:
        """取消所有下载。"""
        self._cancel_event.set()
        self._pause_event.set()
        self._client.cancel()
        logger.info("下载已取消")

    def wait_completion(self, timeout: Optional[float] = None) -> bool:
        """等待所有下载完成。

        Args:
            timeout: 超时时间（秒），None 表示一直等待

        Returns:
            True 表示全部完成，False 表示超时或取消
        """
        start = time.monotonic()
        while self._running:
            if timeout is not None and time.monotonic() - start > timeout:
                return False
            if self._cancel_event.is_set():
                return False
            time.sleep(0.1)
        return True

    def _run_loop(self) -> None:
        """下载调度循环，支持失败自动重试和动态添加任务。"""
        try:
            futures: dict[Future, DownloadItem] = {}
            retry_queue: list[DownloadItem] = []
            processed_items: set[int] = set()

            def get_pending_items():
                with self._lock:
                    return [
                        i for i in self._items
                        if i.status in (DownloadStatus.QUEUED, DownloadStatus.PENDING, DownloadStatus.FAILED)
                        and id(i) not in processed_items
                    ]

            all_items = get_pending_items()
            all_items.sort(key=lambda x: -x.priority)
            item_index = 0

            while True:
                if self._cancel_event.is_set():
                    break

                new_items = get_pending_items()
                if new_items:
                    for item in new_items:
                        if id(item) not in processed_items:
                            all_items.append(item)
                            processed_items.add(id(item))
                    all_items.sort(key=lambda x: -x.priority)

                while item_index < len(all_items) and all_items[item_index].status not in (
                    DownloadStatus.QUEUED, DownloadStatus.PENDING, DownloadStatus.FAILED
                ):
                    item_index += 1

                self._pause_event.wait()
                if self._cancel_event.is_set():
                    break

                done_futures = [f for f in futures if f.done()]
                for f in done_futures:
                    item = futures.pop(f)
                    should_retry = self._handle_completed(f, item)
                    if should_retry:
                        retry_queue.append(item)
                    elif self._item_completed_callback and item.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED):
                        try:
                            self._item_completed_callback(item)
                        except Exception as e:
                            logger.debug("任务完成回调异常: %s", e)

                while len(futures) < self._max_workers:
                    next_item = None
                    if retry_queue:
                        next_item = retry_queue.pop(0)
                    elif item_index < len(all_items):
                        candidate = all_items[item_index]
                        item_index += 1
                        if candidate.status in (DownloadStatus.QUEUED, DownloadStatus.PENDING, DownloadStatus.FAILED):
                            next_item = candidate

                    if next_item is None:
                        break

                    if next_item.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED) and next_item.retry_count >= MAX_RETRIES:
                        continue

                    next_item.status = DownloadStatus.DOWNLOADING
                    next_item.downloaded = 0
                    with self._lock:
                        self._report.active_items += 1
                    future = self._executor.submit(self._download_single, next_item)
                    futures[future] = next_item
                    next_item._future = future

                no_more_work = (
                    not futures
                    and not retry_queue
                    and item_index >= len(all_items)
                    and not self._new_items_event.is_set()
                )

                if no_more_work:
                    recent_done = [f for f in futures if f.done()]
                    if not recent_done and not futures:
                        break

                self._new_items_event.wait(timeout=0.05)
                self._new_items_event.clear()

        except Exception as e:
            logger.error("下载队列异常: %s", e)
        finally:
            self._report.end_time = time.monotonic()
            self._running = False
            if self._executor:
                self._executor.shutdown(wait=False)
                self._executor = None
            logger.info(
                "下载队列结束: 完成 %d, 失败 %d, 跳过 %d, 取消 %d",
                self._report.completed_files,
                self._report.failed_files,
                self._report.skipped_files,
                self._report.cancelled_files,
            )
            if self._progress_callback:
                self._progress_callback(self._report)

    def _download_single(self, item: DownloadItem) -> None:
        """下载单个文件。"""
        try:
            self._pause_event.wait()
            if self._cancel_event.is_set():
                item.status = DownloadStatus.CANCELLED
                return

            ensure_directory(item.path.parent)

            def on_progress(info: DownloadProgressInfo) -> None:
                item.downloaded = info.downloaded
                with self._speed_lock:
                    self._active_speeds[item.url] = info.speed
                    self._report.current_speed = sum(self._active_speeds.values())
                    self._report.downloaded_size = self._calc_total_downloaded()
                    self._report.current_item = item
                if self._progress_callback:
                    self._progress_callback(self._report)

            self._client.download_file(
                url=item.url,
                save_path=item.path,
                progress_callback=on_progress,
                expected_size=item.size,
                expected_sha1=item.sha1,
            )
            item.status = DownloadStatus.COMPLETED

        except HttpError as e:
            if self._cancel_event.is_set():
                item.status = DownloadStatus.CANCELLED
            else:
                item.status = DownloadStatus.FAILED
                item.error = str(e)
                logger.error("下载失败 [%s]: %s", item.tag or item.path.name, e)
        except Exception as e:
            item.status = DownloadStatus.FAILED
            item.error = str(e)
            logger.error("下载异常 [%s]: %s", item.tag or item.path.name, e)
        finally:
            with self._speed_lock:
                self._active_speeds.pop(item.url, None)
                self._report.current_speed = sum(self._active_speeds.values())
            with self._lock:
                self._report.active_items = max(0, self._report.active_items - 1)

    def _handle_completed(self, future: Future, item: DownloadItem) -> bool:
        """处理单个下载完成。

        Returns:
            True 表示需要重试
        """
        try:
            future.result()
        except Exception:
            pass

        should_retry = False
        with self._lock:
            if item.status == DownloadStatus.COMPLETED:
                self._report.completed_files += 1
                self._report.downloaded_size += item.size
            elif item.status == DownloadStatus.SKIPPED:
                self._report.skipped_files += 1
                self._report.downloaded_size += item.size
            elif item.status == DownloadStatus.FAILED:
                if item.retry_count < MAX_RETRIES:
                    item.retry_count += 1
                    item.status = DownloadStatus.QUEUED
                    should_retry = True
                    logger.warning(
                        "下载失败，正在重试 (%d/%d): %s - %s",
                        item.retry_count, MAX_RETRIES,
                        item.tag or item.path.name, item.error
                    )
                    time.sleep(1)
                else:
                    self._report.failed_files += 1
                    logger.error(
                        "下载失败，已达最大重试次数 (%d): %s - %s",
                        MAX_RETRIES, item.tag or item.path.name, item.error
                    )
            elif item.status == DownloadStatus.CANCELLED:
                self._report.cancelled_files += 1

        if self._progress_callback:
            self._progress_callback(self._report)

        return should_retry

    def _calc_total_downloaded(self) -> int:
        """计算总已下载字节数。"""
        total = 0
        with self._lock:
            for item in self._items:
                if item.status == DownloadStatus.COMPLETED or item.status == DownloadStatus.SKIPPED:
                    total += item.size
                elif item.status == DownloadStatus.DOWNLOADING:
                    total += item.downloaded
        return total


class VersionDownloader:
    """版本文件下载器。

    封装下载队列，提供 Minecraft 版本特定的下载接口。
    """

    def __init__(
        self,
        client: Optional[HttpClient] = None,
        game_dir: Optional[Path] = None,
        max_workers: Optional[int] = None,
        max_speed: float = 0,
    ) -> None:
        self._config = get_config()
        self._game_dir = game_dir or Path(self._config.get("game_directory", ".minecraft"))
        self._max_workers = max_workers or self._config.get("download.max_threads", 4)
        self._pending_assets_meta: Optional[VersionMetadata] = None
        self._assets_added = False
        self._queue = DownloadQueue(
            max_workers=self._max_workers,
            client=client,
            max_speed=max_speed,
            item_completed_callback=self._on_item_completed,
        )

    def _on_item_completed(self, item: DownloadItem) -> None:
        """单个下载项完成时的回调，用于在 asset_index 下载完成后添加资源任务。"""
        if item.tag == "asset_index" and item.status == DownloadStatus.COMPLETED:
            if self._pending_assets_meta and not self._assets_added:
                self._assets_added = True
                logger.info("资源索引下载完成，正在添加资源文件任务...")
                try:
                    self.add_asset_tasks(item.path)
                except Exception as e:
                    logger.error("添加资源任务失败: %s", e)

    @property
    def queue(self) -> DownloadQueue:
        return self._queue

    def set_progress_callback(self, callback: Callable[[DownloadReport], None]) -> None:
        self._queue.set_progress_callback(callback)

    def set_speed_limit(self, bytes_per_second: float) -> None:
        self._queue.set_speed_limit(bytes_per_second)

    def add_version_tasks(
        self,
        meta: VersionMetadata,
        include_client: bool = True,
        include_server: bool = False,
        include_libraries: bool = True,
        include_natives: bool = True,
        include_asset_index: bool = True,
    ) -> list[DownloadItem]:
        """添加版本所需的下载任务到队列，但不启动。

        Args:
            meta: 版本元数据
            include_client: 是否下载客户端 jar
            include_server: 是否下载服务端 jar
            include_libraries: 是否下载库文件
            include_natives: 是否下载 native 库
            include_asset_index: 是否下载资源索引

        Returns:
            添加的任务列表
        """
        tasks = self._collect_tasks(
            meta,
            include_client=include_client,
            include_server=include_server,
            include_libraries=include_libraries,
            include_natives=include_natives,
            include_asset_index=include_asset_index,
        )
        self._queue.add_items(tasks)
        return tasks

    def add_asset_tasks(self, asset_index_path: Path) -> list[DownloadItem]:
        """根据已下载的资源索引添加资源文件下载任务。

        Args:
            asset_index_path: 资源索引文件路径

        Returns:
            添加的任务列表
        """
        import json
        tasks: list[DownloadItem] = []

        try:
            from src.version.asset_manager import AssetIndex, RESOURCES_URL
            index = AssetIndex.from_file(asset_index_path)
            if index is None:
                return tasks

            objects_dir = self._game_dir / "assets" / "objects"
            for path_str, obj in index.objects.items():
                obj_path = objects_dir / obj.hash_prefix / obj.hash
                if not (file_exists(obj_path) and obj.size > 0 and obj_path.stat().st_size == obj.size):
                    url = f"{RESOURCES_URL}{obj.object_path}"
                    tasks.append(DownloadItem(
                        url=url,
                        path=obj_path,
                        sha1=obj.hash,
                        size=obj.size,
                        tag=f"asset:{path_str}",
                        priority=10,
                    ))

            logger.info("添加了 %d 个资源文件下载任务", len(tasks))
            self._queue.add_items(tasks)
        except Exception as e:
            logger.error("添加资源下载任务失败: %s", e)

        return tasks

    def start_and_wait(self) -> bool:
        """启动队列并等待完成。

        Returns:
            True 表示全部成功
        """
        if not self._queue.is_running:
            self._queue.start()
        self._queue.wait_completion()
        return self._queue.report.failed_files == 0 and not self._queue.is_paused

    def download_version(
        self,
        meta: VersionMetadata,
        include_client: bool = True,
        include_server: bool = False,
        include_libraries: bool = True,
        include_natives: bool = True,
        include_assets: bool = True,
    ) -> bool:
        """下载版本所需的全部文件（一站式）。

        Args:
            meta: 版本元数据
            include_client: 是否下载客户端 jar
            include_server: 是否下载服务端 jar
            include_libraries: 是否下载库文件
            include_natives: 是否下载 native 库
            include_assets: 是否下载资源文件

        Returns:
            True 表示全部成功
        """
        self._pending_assets_meta = meta if include_assets else None
        self._assets_added = False

        self.add_version_tasks(
            meta,
            include_client=include_client,
            include_server=include_server,
            include_libraries=include_libraries,
            include_natives=include_natives,
            include_asset_index=include_assets,
        )

        if include_assets and meta.assets and meta.asset_index.url:
            index_path = self._game_dir / "assets" / "indexes" / f"{meta.assets}.json"
            if file_exists(index_path) and meta.asset_index.sha1 and verify_sha1(index_path, meta.asset_index.sha1):
                logger.debug("资源索引已存在，直接添加资源任务: %s", index_path)
                self._assets_added = True
                self.add_asset_tasks(index_path)

        return self.start_and_wait()

    def _ensure_asset_index(self, meta: VersionMetadata) -> Optional[Path]:
        """确保资源索引文件存在，必要时下载。"""
        import json
        assets_dir = self._game_dir / "assets" / "indexes"
        ensure_directory(assets_dir)
        index_path = assets_dir / f"{meta.assets}.json"

        if file_exists(index_path) and meta.asset_index.sha1:
            if verify_sha1(index_path, meta.asset_index.sha1):
                return index_path

        logger.info("下载资源索引: %s", meta.assets)
        try:
            data = self._queue._client.get_json(meta.asset_index.url)
            write_json(index_path, data)
            if meta.asset_index.sha1:
                if not verify_sha1(index_path, meta.asset_index.sha1):
                    logger.warning("资源索引校验失败")
            return index_path
        except Exception as e:
            logger.error("下载资源索引失败: %s", e)
            return None

    def download_client_jar(self, meta: VersionMetadata) -> bool:
        """仅下载客户端 jar。"""
        tasks = self._collect_tasks(meta, include_client=True, include_libraries=False, include_natives=False)
        if not tasks:
            logger.debug("客户端 jar 已存在")
            return True
        self._queue.add_items(tasks)
        return self.start_and_wait()

    def download_asset_index(self, meta: VersionMetadata) -> Optional[Path]:
        """下载资源索引文件。

        Returns:
            索引文件路径，失败返回 None
        """
        tasks = self._collect_tasks(meta, include_client=False, include_libraries=False,
                                     include_natives=False, include_asset_index=True)
        if not tasks:
            assets_dir = self._game_dir / "assets" / "indexes"
            index_path = assets_dir / f"{meta.assets}.json"
            if file_exists(index_path):
                return index_path
            return None

        self._queue.add_items(tasks)
        if self.start_and_wait():
            assets_dir = self._game_dir / "assets" / "indexes"
            return assets_dir / f"{meta.assets}.json"
        return None

    def _collect_tasks(
        self,
        meta: VersionMetadata,
        include_client: bool = True,
        include_server: bool = False,
        include_libraries: bool = True,
        include_natives: bool = True,
        include_asset_index: bool = True,
    ) -> list[DownloadItem]:
        """收集下载任务列表。"""
        tasks: list[DownloadItem] = []
        libraries_dir = self._game_dir / "libraries"
        os_name = _get_os_name()

        version_dir = self._game_dir / "versions" / meta.id
        ensure_directory(version_dir)

        if include_client and meta.client_download.url:
            jar_path = version_dir / f"{meta.id}.jar"
            if not (file_exists(jar_path) and meta.client_download.sha1 and verify_sha1(jar_path, meta.client_download.sha1)):
                tasks.append(DownloadItem(
                    url=meta.client_download.url,
                    path=jar_path,
                    sha1=meta.client_download.sha1,
                    size=meta.client_download.size,
                    tag="client",
                    priority=100,
                ))

        if include_server and meta.server_download and meta.server_download.url:
            server_path = version_dir / f"{meta.id}-server.jar"
            if not (file_exists(server_path) and meta.server_download.sha1 and
                    verify_sha1(server_path, meta.server_download.sha1)):
                tasks.append(DownloadItem(
                    url=meta.server_download.url,
                    path=server_path,
                    sha1=meta.server_download.sha1,
                    size=meta.server_download.size,
                    tag="server",
                    priority=95,
                ))

        if include_asset_index and meta.asset_index.url and meta.assets:
            assets_dir = self._game_dir / "assets" / "indexes"
            ensure_directory(assets_dir)
            index_path = assets_dir / f"{meta.assets}.json"
            if not (file_exists(index_path) and meta.asset_index.sha1 and
                    verify_sha1(index_path, meta.asset_index.sha1)):
                tasks.append(DownloadItem(
                    url=meta.asset_index.url,
                    path=index_path,
                    sha1=meta.asset_index.sha1,
                    size=meta.asset_index.size,
                    tag="asset_index",
                    priority=90,
                ))

        if include_libraries:
            for lib in meta.libraries:
                if not lib.matches_os(os_name):
                    continue

                if lib.natives and os_name in lib.natives and include_natives:
                    classifier_name = lib.natives[os_name].replace("${arch}", _get_arch())
                    cls_dl = lib.downloads.classifiers.get(classifier_name)
                    if cls_dl and cls_dl.url:
                        path = libraries_dir / (cls_dl.path or _build_maven_path(lib, classifier_name))
                        ensure_directory(path.parent)
                        if not (file_exists(path) and cls_dl.sha1 and verify_sha1(path, cls_dl.sha1)):
                            tasks.append(DownloadItem(
                                url=cls_dl.url,
                                path=path,
                                sha1=cls_dl.sha1,
                                size=cls_dl.size,
                                tag="native",
                                priority=50,
                            ))
                elif not lib.natives:
                    artifact = lib.downloads.artifact
                    if artifact and artifact.url:
                        path = libraries_dir / (artifact.path or _build_maven_path(lib))
                        ensure_directory(path.parent)
                        if not (file_exists(path) and artifact.sha1 and verify_sha1(path, artifact.sha1)):
                            tasks.append(DownloadItem(
                                url=artifact.url,
                                path=path,
                                sha1=artifact.sha1,
                                size=artifact.size,
                                tag="library",
                                priority=40,
                            ))

        return tasks

    def pause(self) -> None:
        self._queue.pause()

    def resume(self) -> None:
        self._queue.resume()

    def cancel(self) -> None:
        self._queue.cancel()

    def is_running(self) -> bool:
        return self._queue.is_running


# ── 工具函数 ──────────────────────────────────────────────────

def _get_os_name() -> str:
    """获取当前操作系统名称（Mojang 格式）。"""
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "osx"
    return "linux"


def _get_arch() -> str:
    """获取系统架构。"""
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