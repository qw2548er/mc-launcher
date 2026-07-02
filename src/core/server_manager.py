"""服务器列表管理模块。

负责服务器列表的增删改查、持久化存储、状态刷新等功能。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable

from src.core.server_ping import (
    ServerStatus, ping_server, save_favicon, DEFAULT_PORT,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

SERVERS_FILE = Path("config/servers.json")
FAVICON_CACHE_DIR = Path("config/cache/favicons")
REFRESH_INTERVAL_SEC = 30


@dataclass
class ServerInfo:
    name: str = ""
    address: str = ""
    port: int = DEFAULT_PORT
    hidden: bool = False
    accept_textures: bool = True
    icon_path: str = ""
    added_at: float = field(default_factory=time.time)
    last_ping: float = 0.0


class ServerManager:
    """服务器列表管理器。

    管理服务器列表，支持增删改、持久化、异步状态刷新等功能。
    """

    _instance: Optional["ServerManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._servers: dict[str, ServerInfo] = {}
        self._status_cache: dict[str, ServerStatus] = {}
        self._rw_lock = threading.RLock()
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._on_status_updated: Optional[Callable[[str, ServerStatus], None]] = None
        self._auto_refresh = False
        self.load()

    @classmethod
    def instance(cls) -> "ServerManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def auto_refresh(self) -> bool:
        return self._auto_refresh

    @auto_refresh.setter
    def auto_refresh(self, value: bool) -> None:
        self._auto_refresh = value
        if value and self._refresh_thread is None:
            self._start_refresh_thread()
        elif not value and self._refresh_thread is not None:
            self._stop_refresh_thread()

    def set_status_callback(self, cb: Optional[Callable[[str, ServerStatus], None]]) -> None:
        self._on_status_updated = cb

    def load(self) -> None:
        with self._rw_lock:
            self._servers.clear()
            if SERVERS_FILE.exists():
                try:
                    with open(SERVERS_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    servers_list = data.get("servers", [])
                    for s in servers_list:
                        info = ServerInfo(
                            name=s.get("name", ""),
                            address=s.get("address", ""),
                            port=s.get("port", DEFAULT_PORT),
                            hidden=s.get("hidden", False),
                            accept_textures=s.get("accept_textures", True),
                            icon_path=s.get("icon_path", ""),
                            added_at=s.get("added_at", time.time()),
                        )
                        key = self._make_key(info.address, info.port)
                        self._servers[key] = info
                    logger.info("已加载 %d 个服务器", len(self._servers))
                except (json.JSONDecodeError, OSError) as e:
                    logger.error("加载服务器列表失败: %s", e)

    def save(self) -> None:
        with self._rw_lock:
            try:
                SERVERS_FILE.parent.mkdir(parents=True, exist_ok=True)
                servers_list = []
                for info in self._servers.values():
                    servers_list.append(asdict(info))
                data = {"servers": servers_list}
                with open(SERVERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except OSError as e:
                logger.error("保存服务器列表失败: %s", e)

    def get_all(self) -> list[ServerInfo]:
        with self._rw_lock:
            return list(self._servers.values())

    def get(self, address: str, port: int = DEFAULT_PORT) -> Optional[ServerInfo]:
        key = self._make_key(address, port)
        with self._rw_lock:
            return self._servers.get(key)

    def add(self, name: str, address: str, port: int = DEFAULT_PORT) -> ServerInfo:
        info = ServerInfo(name=name, address=address, port=port)
        key = self._make_key(address, port)
        with self._rw_lock:
            self._servers[key] = info
            self.save()
        self.ping_server_async(address, port)
        return info

    def update(self, old_address: str, old_port: int,
               name: str, address: str, port: int) -> Optional[ServerInfo]:
        old_key = self._make_key(old_address, old_port)
        new_key = self._make_key(address, port)
        with self._rw_lock:
            if old_key not in self._servers:
                return None
            if old_key != new_key:
                del self._servers[old_key]
                self._status_cache.pop(old_key, None)
            info = ServerInfo(name=name, address=address, port=port)
            self._servers[new_key] = info
            self.save()
        self.ping_server_async(address, port)
        return info

    def remove(self, address: str, port: int = DEFAULT_PORT) -> bool:
        key = self._make_key(address, port)
        with self._rw_lock:
            if key in self._servers:
                del self._servers[key]
                self._status_cache.pop(key, None)
                self.save()
                return True
        return False

    def get_status(self, address: str, port: int = DEFAULT_PORT) -> ServerStatus:
        key = self._make_key(address, port)
        with self._rw_lock:
            if key in self._status_cache:
                return self._status_cache[key]
        return ServerStatus(host=address, port=port)

    def ping_server_sync(self, address: str, port: int = DEFAULT_PORT) -> ServerStatus:
        status = ping_server(address, port)
        key = self._make_key(address, port)
        if status.favicon_data:
            fav_path = save_favicon(status.favicon_data, key, FAVICON_CACHE_DIR)
            if fav_path:
                status.favicon_path = fav_path
                with self._rw_lock:
                    if key in self._servers:
                        self._servers[key].icon_path = str(fav_path)
                        self.save()
                status.favicon_data = None
        with self._rw_lock:
            self._status_cache[key] = status
        if self._on_status_updated:
            try:
                self._on_status_updated(key, status)
            except Exception:
                pass
        return status

    def ping_server_async(self, address: str, port: int = DEFAULT_PORT) -> None:
        def _do_ping():
            try:
                self.ping_server_sync(address, port)
            except Exception as e:
                logger.debug("异步ping %s:%d 失败: %s", address, port, e)
        t = threading.Thread(target=_do_ping, daemon=True)
        t.start()

    def refresh_all(self) -> None:
        servers = self.get_all()
        for s in servers:
            self.ping_server_async(s.address, s.port)

    @staticmethod
    def _make_key(address: str, port: int) -> str:
        return f"{address.lower()}:{port}"

    def _start_refresh_thread(self) -> None:
        if self._refresh_thread is not None:
            return
        self._stop_event.clear()

        def _refresh_loop():
            while not self._stop_event.is_set():
                try:
                    servers = self.get_all()
                    for s in servers:
                        if self._stop_event.is_set():
                            break
                        self.ping_server_sync(s.address, s.port)
                        time.sleep(0.5)
                except Exception as e:
                    logger.debug("刷新循环异常: %s", e)
                for _ in range(int(REFRESH_INTERVAL_SEC * 2)):
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.5)

        self._refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
        self._refresh_thread.start()
        logger.debug("服务器自动刷新线程已启动")

    def _stop_refresh_thread(self) -> None:
        self._stop_event.set()
        self._refresh_thread = None
        logger.debug("服务器自动刷新线程已停止")


def get_server_manager() -> ServerManager:
    return ServerManager.instance()
