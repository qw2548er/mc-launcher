"""网络请求工具模块。

基于 httpx 的同步 HTTP 客户端封装，提供统一的超时、重试、错误处理。
"""

import json
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from src.utils.file_utils import calculate_sha1, ensure_directory, format_file_size
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 默认请求配置
DEFAULT_TIMEOUT = 30  # 秒
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 1  # 秒
DEFAULT_USER_AGENT = "MinecraftLauncher/1.0 (Python)"
CHUNK_SIZE = 8192  # 8KB


class NetworkError(Exception):
    """网络请求异常。"""

    def __init__(self, message: str, status_code: int = 0, url: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class DownloadProgress:
    """下载进度回调参数。"""

    def __init__(
        self,
        url: str,
        total_size: int,
        downloaded: int,
        speed: float = 0.0,
    ) -> None:
        self.url = url
        self.total_size = total_size
        self.downloaded = downloaded
        self.speed = speed  # bytes/s

    @property
    def percent(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return (self.downloaded / self.total_size) * 100

    @property
    def speed_formatted(self) -> str:
        return format_file_size(self.speed) + "/s"


# 使用标准库 urllib 以减少外部依赖
import urllib.request
import urllib.error
import ssl
import time


class NetworkClient:
    """HTTP 客户端封装。

    提供 GET/POST 请求、JSON 请求、文件下载等功能。
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        user_agent: str = DEFAULT_USER_AGENT,
        proxy: Optional[str] = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.proxy = proxy
        self._opener: Optional[urllib.request.OpenerDirector] = None
        self._init_opener()

    def _init_opener(self) -> None:
        """初始化 URL opener。"""
        handlers: list[urllib.request.BaseHandler] = []

        # SSL 上下文（允许不验证证书，某些环境下需要）
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        https_handler = urllib.request.HTTPSHandler(context=ssl_context)
        handlers.append(https_handler)

        # 代理设置
        if self.proxy:
            proxy_handler = urllib.request.ProxyHandler({
                "http": self.proxy,
                "https": self.proxy,
            })
            handlers.append(proxy_handler)

        self._opener = urllib.request.build_opener(*handlers)
        self._opener.addheaders = [
            ("User-Agent", self.user_agent),
            ("Accept", "*/*"),
            ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
        ]

    def _request(
        self,
        url: str,
        method: str = "GET",
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> urllib.request.Request:
        """构建 Request 对象。"""
        req_headers = {}
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(
            url,
            data=data,
            headers=req_headers,
            method=method,
        )
        return req

    def get(
        self,
        url: str,
        params: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> bytes:
        """发送 GET 请求，返回响应体 bytes。

        Args:
            url: 请求 URL
            params: URL 查询参数
            headers: 额外请求头

        Returns:
            响应体 bytes

        Raises:
            NetworkError: 请求失败
        """
        if params:
            from urllib.parse import urlencode
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params)}"

        logger.debug("GET %s", url)

        last_error: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                req = self._request(url, "GET", headers=headers)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace") if e.fp else ""
                logger.error(
                    "HTTP %d: %s (attempt %d/%d)",
                    e.code, url, attempt + 1, self.retries,
                )
                if 400 <= e.code < 500:
                    raise NetworkError(
                        f"HTTP {e.code}: {body[:200]}",
                        status_code=e.code,
                        url=url,
                    )
                last_error = NetworkError(
                    f"HTTP {e.code}: {e.reason}",
                    status_code=e.code,
                    url=url,
                )
            except urllib.error.URLError as e:
                logger.warning(
                    "URL 错误: %s (attempt %d/%d)",
                    e.reason, attempt + 1, self.retries,
                )
                last_error = NetworkError(f"连接失败: {e.reason}", url=url)
            except Exception as e:
                logger.warning(
                    "请求异常: %s (attempt %d/%d)",
                    e, attempt + 1, self.retries,
                )
                last_error = NetworkError(f"请求异常: {e}", url=url)

            if attempt < self.retries - 1:
                time.sleep(DEFAULT_RETRY_DELAY * (attempt + 1))

        raise last_error or NetworkError("请求失败", url=url)

    def get_json(
        self,
        url: str,
        params: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        """发送 GET 请求，返回解析后的 JSON。

        Args:
            url: 请求 URL
            params: URL 查询参数
            headers: 额外请求头

        Returns:
            解析后的 JSON 对象

        Raises:
            NetworkError: 请求失败或 JSON 解析失败
        """
        if headers is None:
            headers = {}
        headers.setdefault("Accept", "application/json")

        data = self.get(url, params=params, headers=headers)
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise NetworkError(f"JSON 解析失败: {e}", url=url)

    def post(
        self,
        url: str,
        data: Optional[dict[str, Any]] = None,
        json_data: Optional[Any] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> bytes:
        """发送 POST 请求。

        Args:
            url: 请求 URL
            data: 表单数据（将被编码为 form-urlencoded）
            json_data: JSON 数据
            headers: 额外请求头

        Returns:
            响应体 bytes
        """
        if headers is None:
            headers = {}

        post_data: Optional[bytes] = None
        if json_data is not None:
            post_data = json.dumps(json_data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            from urllib.parse import urlencode
            post_data = urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        logger.debug("POST %s", url)

        last_error: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                req = self._request(url, "POST", data=post_data, headers=headers)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace") if e.fp else ""
                logger.error("HTTP %d: %s", e.code, url)
                if 400 <= e.code < 500:
                    raise NetworkError(
                        f"HTTP {e.code}: {body[:200]}",
                        status_code=e.code,
                        url=url,
                    )
                last_error = NetworkError(
                    f"HTTP {e.code}: {e.reason}",
                    status_code=e.code,
                    url=url,
                )
            except urllib.error.URLError as e:
                logger.warning("URL 错误: %s", e.reason)
                last_error = NetworkError(f"连接失败: {e.reason}", url=url)
            except Exception as e:
                last_error = NetworkError(f"请求异常: {e}", url=url)

            if attempt < self.retries - 1:
                time.sleep(DEFAULT_RETRY_DELAY * (attempt + 1))

        raise last_error or NetworkError("请求失败", url=url)

    def post_json(
        self,
        url: str,
        json_data: Optional[Any] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        """发送 POST JSON 请求，返回解析后的 JSON 响应。"""
        data = self.post(url, json_data=json_data, headers=headers)
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise NetworkError(f"JSON 解析失败: {e}", url=url)

    def download(
        self,
        url: str,
        save_path: Path,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
        expected_size: int = 0,
        expected_sha1: Optional[str] = None,
    ) -> bool:
        """下载文件到指定路径，支持进度回调和断点续传。

        Args:
            url: 文件 URL
            save_path: 保存路径
            progress_callback: 进度回调函数
            expected_size: 期望的文件大小（字节），用于校验
            expected_sha1: 期望的 SHA1 哈希值，用于校验

        Returns:
            True 表示下载成功

        Raises:
            NetworkError: 下载失败
        """
        save_path = Path(save_path)
        ensure_directory(save_path.parent)

        # 临时文件
        temp_path = save_path.with_suffix(save_path.suffix + ".part")

        # 断点续传：检查已下载的部分
        downloaded = 0
        if temp_path.exists():
            downloaded = temp_path.stat().st_size

        req_headers: dict[str, str] = {}
        if downloaded > 0:
            req_headers["Range"] = f"bytes={downloaded}-"

        logger.debug("下载: %s -> %s (已下载: %d)", url, save_path, downloaded)

        last_error: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                req = self._request(url, "GET", headers=req_headers)
                resp = self._opener.open(req, timeout=self.timeout)

                # 获取文件大小
                total_size = downloaded
                content_length = resp.headers.get("Content-Length")
                content_range = resp.headers.get("Content-Range")

                if content_range:
                    # 断点续传响应
                    try:
                        total_size = int(content_range.split("/")[-1])
                    except (ValueError, IndexError):
                        total_size = downloaded + (int(content_length) if content_length else 0)
                elif content_length:
                    total_size = int(content_length)

                if expected_size and total_size == 0:
                    total_size = expected_size

                mode = "ab" if downloaded > 0 and temp_path.exists() else "wb"
                start_time = time.time()
                bytes_since_last = 0

                with open(temp_path, mode) as f:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        bytes_since_last += len(chunk)

                        # 进度回调
                        if progress_callback and total_size > 0:
                            elapsed = time.time() - start_time
                            speed = bytes_since_last / max(elapsed, 0.001)
                            progress = DownloadProgress(
                                url=url,
                                total_size=total_size,
                                downloaded=downloaded,
                                speed=speed,
                            )
                            try:
                                progress_callback(progress)
                            except Exception as cb_err:
                                logger.debug("进度回调异常: %s", cb_err)

                resp.close()

                # 校验文件大小
                if expected_size > 0:
                    actual_size = temp_path.stat().st_size
                    if actual_size != expected_size:
                        logger.warning(
                            "文件大小不匹配: 期望 %d, 实际 %d",
                            expected_size, actual_size,
                        )
                        if attempt < self.retries - 1:
                            downloaded = 0
                            temp_path.unlink(missing_ok=True)
                            req_headers.pop("Range", None)
                            continue
                        raise NetworkError(
                            f"文件大小不匹配: 期望 {expected_size}, 实际 {actual_size}",
                            url=url,
                        )

                # 校验 SHA1
                if expected_sha1:
                    actual_sha1 = calculate_sha1(temp_path)
                    if actual_sha1.lower() != expected_sha1.lower():
                        logger.warning(
                            "SHA1 校验失败: 期望 %s, 实际 %s",
                            expected_sha1, actual_sha1,
                        )
                        if attempt < self.retries - 1:
                            downloaded = 0
                            temp_path.unlink(missing_ok=True)
                            req_headers.pop("Range", None)
                            continue
                        raise NetworkError(
                            f"SHA1 校验失败: {actual_sha1} != {expected_sha1}",
                            url=url,
                        )

                # 下载完成，重命名临时文件
                if save_path.exists():
                    save_path.unlink()
                temp_path.rename(save_path)
                logger.debug("下载完成: %s (%d bytes)", save_path, downloaded)
                return True

            except urllib.error.HTTPError as e:
                if e.code == 416:
                    # Range not satisfiable，文件可能已下载完成
                    if temp_path.exists() and expected_size > 0:
                        if temp_path.stat().st_size == expected_size:
                            temp_path.rename(save_path)
                            return True
                    downloaded = 0
                    temp_path.unlink(missing_ok=True)
                    req_headers.pop("Range", None)
                    continue
                logger.error("HTTP %d: %s", e.code, url)
                last_error = NetworkError(
                    f"HTTP {e.code}: {e.reason}",
                    status_code=e.code,
                    url=url,
                )
            except urllib.error.URLError as e:
                logger.warning("下载 URL 错误: %s", e.reason)
                last_error = NetworkError(f"连接失败: {e.reason}", url=url)
            except TimeoutError:
                logger.warning("下载超时")
                last_error = NetworkError("下载超时", url=url)
            except OSError as e:
                logger.warning("文件操作错误: %s", e)
                last_error = NetworkError(f"文件错误: {e}", url=url)

            if attempt < self.retries - 1:
                time.sleep(DEFAULT_RETRY_DELAY * (attempt + 1))

        # 清理临时文件
        if temp_path.exists() and not save_path.exists():
            temp_path.unlink(missing_ok=True)

        raise last_error or NetworkError("下载失败", url=url)


# ── 全局单例 ──────────────────────────────────────────────────

_default_client: Optional[NetworkClient] = None


def get_client() -> NetworkClient:
    """获取默认 NetworkClient 单例。"""
    global _default_client
    if _default_client is None:
        _default_client = NetworkClient()
    return _default_client