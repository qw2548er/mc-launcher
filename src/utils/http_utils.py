"""HTTP 网络工具模块。

基于 requests 的 HTTP 客户端封装，提供会话管理、自动重试、
流式下载、速度限制等功能。
"""

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.file_utils import calculate_sha1, ensure_directory, format_file_size
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_CHUNK_SIZE = 64 * 1024  # 64KB
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class HttpError(Exception):
    """HTTP 请求异常。"""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        url: str = "",
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.original_error = original_error


class DownloadProgressInfo:
    """下载进度信息。"""

    def __init__(
        self,
        url: str = "",
        total_size: int = 0,
        downloaded: int = 0,
        speed: float = 0.0,
        elapsed: float = 0.0,
        filename: str = "",
    ) -> None:
        self.url = url
        self.total_size = total_size
        self.downloaded = downloaded
        self.speed = speed
        self.elapsed = elapsed
        self.filename = filename

    @property
    def percent(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return (self.downloaded / self.total_size) * 100

    @property
    def remaining_time(self) -> float:
        if self.speed <= 0:
            return 0.0
        return max(0, (self.total_size - self.downloaded) / self.speed)

    @property
    def speed_formatted(self) -> str:
        return f"{format_file_size(self.speed)}/s"

    @property
    def total_formatted(self) -> str:
        return format_file_size(self.total_size)

    @property
    def downloaded_formatted(self) -> str:
        return format_file_size(self.downloaded)


class RateLimiter:
    """下载速度限制器。"""

    def __init__(self, max_bytes_per_second: float = 0):
        self._max_speed = max_bytes_per_second
        self._lock = threading.Lock()
        self._bytes_in_window = 0
        self._window_start = time.monotonic()

    @property
    def max_speed(self) -> float:
        return self._max_speed

    def set_limit(self, max_bytes_per_second: float) -> None:
        """设置速度限制（字节/秒），0 表示不限速。"""
        with self._lock:
            self._max_speed = max_bytes_per_second
            self._bytes_in_window = 0
            self._window_start = time.monotonic()

    def wait(self, bytes_downloaded: int) -> None:
        """根据已下载字节数计算并等待以保持速度限制。

        Args:
            bytes_downloaded: 本次下载的字节数
        """
        if self._max_speed <= 0:
            return

        with self._lock:
            self._bytes_in_window += bytes_downloaded
            elapsed = time.monotonic() - self._window_start

            if elapsed < 0.01:
                return

            expected_time = self._bytes_in_window / self._max_speed
            wait_time = expected_time - elapsed

            if wait_time > 0:
                time.sleep(wait_time)

            if elapsed >= 1.0:
                self._bytes_in_window = 0
                self._window_start = time.monotonic()


class HttpClient:
    """HTTP 客户端。

    封装 requests.Session，提供统一的请求配置、重试、
    流式下载、进度回调和速度限制。
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        user_agent: str = DEFAULT_USER_AGENT,
        proxy: Optional[str] = None,
        max_speed: float = 0,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.proxy = proxy
        self._rate_limiter = RateLimiter(max_speed)
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # 默认不暂停
        self._session: Optional[requests.Session] = None

    @property
    def session(self) -> requests.Session:
        """获取或创建 requests Session。"""
        if self._session is None:
            self._session = self._create_session()
        return self._session

    def _create_session(self) -> requests.Session:
        """创建配置好的 requests Session。"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        retry_strategy = Retry(
            total=self.retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "HEAD"],
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=32,
            pool_maxsize=64,
            pool_block=False,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        if self.proxy:
            session.proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }

        return session

    def set_speed_limit(self, bytes_per_second: float) -> None:
        """设置下载速度限制。"""
        self._rate_limiter.set_limit(bytes_per_second)

    def cancel(self) -> None:
        """取消所有请求。"""
        self._cancel_event.set()
        self._pause_event.set()  # 解除暂停以避免死锁

    def pause(self) -> None:
        """暂停下载。"""
        self._pause_event.clear()

    def resume(self) -> None:
        """恢复下载。"""
        self._pause_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def reset_state(self) -> None:
        """重置取消/暂停状态。"""
        self._cancel_event.clear()
        self._pause_event.set()

    # ── HTTP 方法 ────────────────────────────────────────────

    def get(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None, **kwargs) -> requests.Response:
        """发送 GET 请求。"""
        try:
            resp = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            raise HttpError(
                f"GET 请求失败: {e}",
                status_code=getattr(e.response, "status_code", 0) if e.response else 0,
                url=url,
                original_error=e,
            )

    def get_json(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Any:
        """发送 GET 请求并返回 JSON。"""
        resp = self.get(url, params=params, headers=headers)
        try:
            return resp.json()
        except ValueError as e:
            raise HttpError(f"JSON 解析失败: {e}", url=url, original_error=e)

    def post(self, url: str, data: Any = None, json_data: Any = None,
             headers: Optional[dict] = None, **kwargs) -> requests.Response:
        """发送 POST 请求。"""
        try:
            resp = self.session.post(
                url,
                data=data,
                json=json_data,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            raise HttpError(
                f"POST 请求失败: {e}",
                status_code=getattr(e.response, "status_code", 0) if e.response else 0,
                url=url,
                original_error=e,
            )

    def head(self, url: str, headers: Optional[dict] = None) -> requests.Response:
        """发送 HEAD 请求获取文件信息。"""
        try:
            resp = self.session.head(url, headers=headers, timeout=self.timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            raise HttpError(
                f"HEAD 请求失败: {e}",
                status_code=getattr(e.response, "status_code", 0) if e.response else 0,
                url=url,
                original_error=e,
            )

    # ── 文件下载 ─────────────────────────────────────────────

    def download_file(
        self,
        url: str,
        save_path: Path,
        progress_callback: Optional[Callable[[DownloadProgressInfo], None]] = None,
        expected_size: int = 0,
        expected_sha1: Optional[str] = None,
        resume: bool = True,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_retries: int = 3,
    ) -> bool:
        """下载文件到指定路径。

        支持断点续传、进度回调、SHA1 校验、暂停/取消、速度限制、自动重试。

        Args:
            url: 文件 URL
            save_path: 保存路径
            progress_callback: 进度回调
            expected_size: 期望文件大小
            expected_sha1: 期望 SHA1
            resume: 是否启用断点续传
            chunk_size: 下载块大小
            max_retries: 最大重试次数

        Returns:
            True 表示下载成功

        Raises:
            HttpError: 下载失败（重试次数耗尽后）
        """
        save_path = Path(save_path)
        ensure_directory(save_path.parent)

        temp_path = save_path.with_suffix(save_path.suffix + ".part")
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            if self._cancel_event.is_set():
                raise HttpError("下载已取消", url=url)

            try:
                return self._download_file_internal(
                    url=url,
                    save_path=save_path,
                    temp_path=temp_path,
                    progress_callback=progress_callback,
                    expected_size=expected_size,
                    expected_sha1=expected_sha1,
                    resume=resume and attempt == 0,
                    chunk_size=chunk_size,
                )
            except HttpError as e:
                last_error = e
                if self._cancel_event.is_set():
                    raise
                if attempt < max_retries:
                    wait_time = min(2 ** attempt, 10)
                    logger.warning(
                        "下载失败（第 %d/%d 次尝试），%d 秒后重试: %s - %s",
                        attempt + 1,
                        max_retries + 1,
                        wait_time,
                        save_path.name,
                        e,
                    )
                    time.sleep(wait_time)
                else:
                    logger.error("下载失败，已达到最大重试次数: %s - %s", save_path.name, e)
                    temp_path.unlink(missing_ok=True)
                    raise

        if last_error:
            raise last_error
        return False

    def _download_file_internal(
        self,
        url: str,
        save_path: Path,
        temp_path: Path,
        progress_callback: Optional[Callable[[DownloadProgressInfo], None]] = None,
        expected_size: int = 0,
        expected_sha1: Optional[str] = None,
        resume: bool = True,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> bool:
        """单次下载尝试的内部实现。"""
        downloaded = 0
        mode = "wb"
        headers: dict[str, str] = {}

        if resume and temp_path.exists():
            downloaded = temp_path.stat().st_size
            if expected_size > 0 and downloaded >= expected_size:
                if expected_sha1:
                    if calculate_sha1(temp_path).lower() == expected_sha1.lower():
                        if save_path.exists():
                            save_path.unlink()
                        temp_path.rename(save_path)
                        return True
                else:
                    if save_path.exists():
                        save_path.unlink()
                    temp_path.rename(save_path)
                    return True
            headers["Range"] = f"bytes={downloaded}-"
            mode = "ab"

        resp = self.session.get(
            url,
            headers=headers,
            stream=True,
            timeout=self.timeout,
        )

        if resp.status_code == 416:
            if temp_path.exists() and expected_size > 0:
                if temp_path.stat().st_size == expected_size:
                    if expected_sha1 is None or calculate_sha1(temp_path).lower() == expected_sha1.lower():
                        if save_path.exists():
                            save_path.unlink()
                        temp_path.rename(save_path)
                        return True
            temp_path.unlink(missing_ok=True)
            return self._download_file_internal(
                url, save_path, temp_path, progress_callback,
                expected_size, expected_sha1, resume=False, chunk_size=chunk_size,
            )

        resp.raise_for_status()

        total_size = downloaded
        content_length = resp.headers.get("Content-Length")
        content_range = resp.headers.get("Content-Range")

        if content_range:
            try:
                total_size = int(content_range.split("/")[-1])
            except (ValueError, IndexError):
                total_size = downloaded + (int(content_length) if content_length else 0)
        elif content_length:
            if downloaded > 0 and resp.status_code == 206:
                total_size = downloaded + int(content_length)
            else:
                total_size = int(content_length)

        if expected_size and total_size == 0:
            total_size = expected_size

        start_time = time.monotonic()
        last_report_time = start_time
        bytes_since_report = 0

        try:
            with open(temp_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if self._cancel_event.is_set():
                        resp.close()
                        raise HttpError("下载已取消", url=url)

                    self._pause_event.wait()
                    if self._cancel_event.is_set():
                        resp.close()
                        raise HttpError("下载已取消", url=url)

                    if not chunk:
                        continue

                    f.write(chunk)
                    downloaded += len(chunk)
                    bytes_since_report += len(chunk)
                    self._rate_limiter.wait(len(chunk))

                    now = time.monotonic()
                    if progress_callback and (now - last_report_time >= 0.1):
                        elapsed = now - start_time
                        speed = bytes_since_report / (now - last_report_time) if (now - last_report_time) > 0 else 0
                        info = DownloadProgressInfo(
                            url=url,
                            total_size=total_size,
                            downloaded=downloaded,
                            speed=speed,
                            elapsed=elapsed,
                            filename=save_path.name,
                        )
                        try:
                            progress_callback(info)
                        except Exception as cb_err:
                            logger.debug("进度回调异常: %s", cb_err)
                        last_report_time = now
                        bytes_since_report = 0
        finally:
            resp.close()

        if expected_size > 0 and temp_path.stat().st_size != expected_size:
            raise HttpError(
                f"文件大小不匹配: 期望 {expected_size}, 实际 {temp_path.stat().st_size}",
                url=url,
            )

        if expected_sha1:
            actual_sha1 = calculate_sha1(temp_path)
            if actual_sha1.lower() != expected_sha1.lower():
                temp_path.unlink(missing_ok=True)
                raise HttpError(f"SHA1 校验失败: {actual_sha1} != {expected_sha1}", url=url)

        if save_path.exists():
            save_path.unlink()
        temp_path.rename(save_path)

        if progress_callback:
            progress_callback(DownloadProgressInfo(
                url=url,
                total_size=total_size,
                downloaded=downloaded,
                speed=0,
                elapsed=time.monotonic() - start_time,
                filename=save_path.name,
            ))

        logger.debug("下载完成: %s (%d bytes)", save_path.name, downloaded)
        return True

    def close(self) -> None:
        """关闭 Session。"""
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# ── 全局单例 ──────────────────────────────────────────────────

_default_client: Optional[HttpClient] = None
_client_lock = threading.Lock()


def get_http_client() -> HttpClient:
    """获取默认 HttpClient 单例。"""
    global _default_client
    if _default_client is None:
        with _client_lock:
            if _default_client is None:
                _default_client = HttpClient()
    return _default_client


def reset_http_client() -> None:
    """重置全局 HTTP 客户端（主要用于测试）。"""
    global _default_client
    with _client_lock:
        if _default_client is not None:
            _default_client.close()
        _default_client = None