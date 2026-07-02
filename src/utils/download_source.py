"""下载源管理模块。

提供多下载源支持、URL重写、测速和自动选择功能。
支持官方源、BMCLAPI镜像等国内加速源，以及自定义源。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from src.utils.config import get_config
from src.utils.file_utils import format_file_size
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SourceType(Enum):
    OFFICIAL = "official"
    MIRROR = "mirror"
    CUSTOM = "custom"


@dataclass
class DownloadSource:
    """下载源配置。"""

    id: str
    name: str
    source_type: SourceType
    description: str = ""
    is_default: bool = False

    version_manifest: str = ""
    version_meta: str = ""
    resources: str = ""
    libraries_maven: str = ""
    forge_maven: str = ""
    forge_promotions: str = ""
    fabric_meta: str = ""
    fabric_maven: str = ""
    quilt_meta: str = ""
    quilt_maven: str = ""

    speed_test_url: str = ""
    last_speed: float = 0.0
    last_test_time: float = 0.0

    def rewrite_url(self, original_url: str) -> str:
        if self.source_type == SourceType.OFFICIAL:
            return original_url
        return self._rewrite(original_url)

    def _rewrite(self, url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path
        query = parsed.query

        try:
            if host in ("piston-meta.mojang.com", "launchermeta.mojang.com"):
                if "version_manifest_v2.json" in path and self.version_manifest:
                    return self.version_manifest
                if path.startswith("/v1/packages/") and self.version_meta:
                    version_id = path.rstrip("/").split("/")[-1].removesuffix(".json")
                    if "/{version}" in self.version_meta:
                        return self.version_meta.replace("{version}", version_id)
                    return self.version_meta.rstrip("/") + path

            if host == "resources.download.minecraft.net" and self.resources:
                resource_path = path.lstrip("/")
                return self.resources.rstrip("/") + "/" + resource_path

            if host == "libraries.minecraft.net" and self.libraries_maven:
                return self.libraries_maven.rstrip("/") + path

            if host in ("maven.minecraftforge.net", "files.minecraftforge.net"):
                if "promotions_slim.json" in path and self.forge_promotions:
                    return self.forge_promotions
                if self.forge_maven:
                    return self.forge_maven.rstrip("/") + path

            if host == "meta.fabricmc.net" and self.fabric_meta:
                return self.fabric_meta.rstrip("/") + path

            if host == "maven.fabricmc.net" and self.fabric_maven:
                return self.fabric_maven.rstrip("/") + path

            if host == "meta.quiltmc.org" and self.quilt_meta:
                return self.quilt_meta.rstrip("/") + path

            if host == "maven.quiltmc.org" and self.quilt_maven:
                quilt_path = path
                if "/repository/release/" in quilt_path:
                    quilt_path = quilt_path[quilt_path.find("/repository/release/") + len("/repository/release"):]
                elif quilt_path.startswith("/repository/release/"):
                    quilt_path = quilt_path[len("/repository/release"):]
                return self.quilt_maven.rstrip("/") + quilt_path

            if host == "repo1.maven.org" and self.libraries_maven:
                maven2_idx = path.find("/maven2/")
                if maven2_idx >= 0:
                    return self.libraries_maven.rstrip("/") + path[maven2_idx + 7:]
                if path.startswith("/maven2/"):
                    return self.libraries_maven.rstrip("/") + path[7:]

            if host == "piston-data.mojang.com" and self.libraries_maven:
                return self.libraries_maven.rstrip("/") + path

        except Exception as e:
            logger.debug("URL重写失败 %s: %s", url, e)
            return url

        return url


_BUILTIN_SOURCES: list[DownloadSource] = []


def _init_builtin_sources() -> None:
    global _BUILTIN_SOURCES
    if _BUILTIN_SOURCES:
        return

    _BUILTIN_SOURCES = [
        DownloadSource(
            id="official",
            name="官方源 (Mojang)",
            source_type=SourceType.OFFICIAL,
            description="Mojang官方服务器，海外访问速度较快",
            is_default=True,
            version_manifest="https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
            version_meta="https://piston-meta.mojang.com",
            resources="https://resources.download.minecraft.net",
            libraries_maven="https://libraries.minecraft.net",
            forge_maven="https://maven.minecraftforge.net",
            forge_promotions="https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json",
            fabric_meta="https://meta.fabricmc.net",
            fabric_maven="https://maven.fabricmc.net",
            quilt_meta="https://meta.quiltmc.org",
            quilt_maven="https://maven.quiltmc.org/repository/release",
            speed_test_url="https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
        ),
        DownloadSource(
            id="bmclapi",
            name="BMCLAPI 镜像",
            source_type=SourceType.MIRROR,
            description="BMCLAPI国内镜像，访问速度快，稳定可靠",
            version_manifest="https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json",
            version_meta="https://bmclapi2.bangbang93.com",
            resources="https://bmclapi2.bangbang93.com/assets",
            libraries_maven="https://bmclapi2.bangbang93.com/maven",
            forge_maven="https://bmclapi2.bangbang93.com/maven",
            forge_promotions="https://bmclapi2.bangbang93.com/maven/net/minecraftforge/forge/promotions_slim.json",
            fabric_meta="https://bmclapi2.bangbang93.com/fabric-meta",
            fabric_maven="https://bmclapi2.bangbang93.com/maven",
            quilt_meta="https://bmclapi2.bangbang93.com/quilt-meta",
            quilt_maven="https://bmclapi2.bangbang93.com/maven",
            speed_test_url="https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json",
        ),
        DownloadSource(
            id="mcbbs",
            name="MCBBS 镜像",
            source_type=SourceType.MIRROR,
            description="MCBBS镜像源（备用）",
            version_manifest="https://download.mcbbs.net/mc/game/version_manifest_v2.json",
            version_meta="https://download.mcbbs.net",
            resources="https://download.mcbbs.net/assets",
            libraries_maven="https://download.mcbbs.net/maven",
            forge_maven="https://download.mcbbs.net/maven",
            forge_promotions="https://download.mcbbs.net/maven/net/minecraftforge/forge/promotions_slim.json",
            fabric_meta="https://download.mcbbs.net/fabric-meta",
            fabric_maven="https://download.mcbbs.net/maven",
            quilt_meta="https://download.mcbbs.net/quilt-meta",
            quilt_maven="https://download.mcbbs.net/maven",
            speed_test_url="https://download.mcbbs.net/mc/game/version_manifest_v2.json",
        ),
    ]


_init_builtin_sources()


class SpeedTestResult:
    def __init__(self, source_id: str, success: bool, speed: float = 0.0,
                 elapsed: float = 0.0, error: str = ""):
        self.source_id = source_id
        self.success = success
        self.speed = speed
        self.elapsed = elapsed
        self.error = error

    @property
    def speed_formatted(self) -> str:
        return f"{format_file_size(self.speed)}/s"


class _SpeedTestThread(threading.Thread):
    def __init__(self, source: DownloadSource, callback: Callable[[SpeedTestResult], None],
                 test_size: int = 256 * 1024, timeout: float = 10.0):
        super().__init__(daemon=True)
        self._source = source
        self._callback = callback
        self._test_size = test_size
        self._timeout = timeout

    def run(self):
        result = self._do_test()
        try:
            self._callback(result)
        except Exception as e:
            logger.debug("测速回调异常: %s", e)

    def _do_test(self) -> SpeedTestResult:
        import requests

        url = self._source.speed_test_url
        if not url:
            return SpeedTestResult(self._source.id, False, error="无测速URL")

        try:
            rewritten_url = self._source.rewrite_url(url)
            start = time.monotonic()
            downloaded = 0

            resp = requests.get(
                rewritten_url,
                stream=True,
                timeout=self._timeout,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Encoding": "identity",
                },
            )
            resp.raise_for_status()

            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                downloaded += len(chunk)
                elapsed = time.monotonic() - start
                if elapsed >= self._timeout or downloaded >= self._test_size:
                    break

            elapsed = time.monotonic() - start
            resp.close()

            if elapsed > 0 and downloaded > 0:
                speed = downloaded / elapsed
                return SpeedTestResult(
                    self._source.id, True, speed=speed, elapsed=elapsed
                )
            return SpeedTestResult(self._source.id, False, error="下载数据过小")

        except Exception as e:
            return SpeedTestResult(self._source.id, False, error=str(e))


class DownloadSourceManager:
    _instance: Optional[DownloadSourceManager] = None
    _lock = threading.Lock()

    def __init__(self):
        self._sources: dict[str, DownloadSource] = {}
        self._current_source_id: str = "official"
        self._custom_sources: list[DownloadSource] = []
        self._speed_test_results: dict[str, SpeedTestResult] = {}
        self._testing = False
        self._load_builtin_sources()
        self._load_config()

    @classmethod
    def instance(cls) -> DownloadSourceManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load_builtin_sources(self):
        for src in _BUILTIN_SOURCES:
            self._sources[src.id] = src

    def _load_config(self):
        try:
            config = get_config()
            saved_id = config.get("download.source_id", "")
            if saved_id and saved_id in self._sources:
                self._current_source_id = saved_id
            else:
                source_idx = config.get("download.source", 0)
                ids = list(self._sources.keys())
                if 0 <= source_idx < len(ids):
                    self._current_source_id = ids[source_idx]

            custom_url = config.get("download.custom_mirror_url", "")
            custom_name = config.get("download.custom_mirror_name", "自定义镜像")
            if custom_url:
                self.add_custom_source(custom_url, custom_name)
                if config.get("download.use_custom", False):
                    custom_id = f"custom_{custom_name}"
                    if custom_id in self._sources:
                        self._current_source_id = custom_id
        except Exception as e:
            logger.debug("加载下载源配置失败: %s", e)

    @property
    def current_source(self) -> DownloadSource:
        src = self._sources.get(self._current_source_id)
        if src is None:
            src = self._sources["official"]
        return src

    @property
    def sources(self) -> list[DownloadSource]:
        result = list(self._sources.values())
        result.sort(key=lambda s: (
            0 if s.source_type == SourceType.OFFICIAL else 1,
            s.name
        ))
        return result

    def get_source(self, source_id: str) -> Optional[DownloadSource]:
        return self._sources.get(source_id)

    def set_current(self, source_id: str) -> bool:
        if source_id not in self._sources:
            return False
        old_id = self._current_source_id
        self._current_source_id = source_id
        try:
            config = get_config()
            config.set("download.source_id", source_id)
            config.save()
        except Exception as e:
            logger.debug("保存下载源配置失败: %s", e)
        logger.info("切换下载源: %s -> %s", old_id, source_id)
        return True

    def rewrite_url(self, url: str) -> str:
        if not url:
            return url
        return self.current_source.rewrite_url(url)

    def add_custom_source(self, base_url: str, name: str = "自定义镜像") -> str:
        base_url = base_url.rstrip("/")
        source_id = f"custom_{name}"

        custom = DownloadSource(
            id=source_id,
            name=name,
            source_type=SourceType.CUSTOM,
            description=f"自定义镜像: {base_url}",
            version_manifest=f"{base_url}/mc/game/version_manifest_v2.json",
            version_meta=base_url,
            resources=f"{base_url}/assets",
            libraries_maven=f"{base_url}/maven",
            forge_maven=f"{base_url}/maven",
            forge_promotions=f"{base_url}/maven/net/minecraftforge/forge/promotions_slim.json",
            fabric_meta=f"{base_url}/fabric-meta",
            fabric_maven=f"{base_url}/maven",
            quilt_meta=f"{base_url}/quilt-meta",
            quilt_maven=f"{base_url}/maven",
            speed_test_url=f"{base_url}/mc/game/version_manifest_v2.json",
        )

        self._sources[source_id] = custom
        self._custom_sources.append(custom)

        try:
            config = get_config()
            config.set("download.custom_mirror_url", base_url)
            config.set("download.custom_mirror_name", name)
            config.save()
        except Exception as e:
            logger.debug("保存自定义镜像配置失败: %s", e)

        return source_id

    def remove_custom_source(self, source_id: str) -> bool:
        if source_id not in self._sources:
            return False
        src = self._sources[source_id]
        if src.source_type != SourceType.CUSTOM:
            return False
        del self._sources[source_id]
        self._custom_sources = [s for s in self._custom_sources if s.id != source_id]
        if self._current_source_id == source_id:
            self.set_current("official")
        return True

    def speed_test(self, source_id: str, callback: Callable[[SpeedTestResult], None]) -> None:
        src = self._sources.get(source_id)
        if not src:
            callback(SpeedTestResult(source_id, False, error="未知下载源"))
            return
        thread = _SpeedTestThread(src, callback)
        thread.start()

    def speed_test_all(self, callback: Callable[[str, SpeedTestResult], None],
                       complete_callback: Optional[Callable[[], None]] = None) -> None:
        self._testing = True
        sources_to_test = [s for s in self.sources if s.source_type != SourceType.CUSTOM]

        completed = {"count": 0, "total": len(sources_to_test)}

        def on_single_result(result: SpeedTestResult):
            self._speed_test_results[result.source_id] = result
            src = self._sources.get(result.source_id)
            if src and result.success:
                src.last_speed = result.speed
                src.last_test_time = time.time()
            completed["count"] += 1
            try:
                callback(result.source_id, result)
            except Exception as e:
                logger.debug("测速进度回调异常: %s", e)
            if completed["count"] >= completed["total"]:
                self._testing = False
                self._auto_select_fastest()
                if complete_callback:
                    try:
                        complete_callback()
                    except Exception as e:
                        logger.debug("测速完成回调异常: %s", e)

        for src in sources_to_test:
            self.speed_test(src.id, on_single_result)

    def _auto_select_fastest(self):
        valid_results = [
            r for r in self._speed_test_results.values()
            if r.success and r.speed > 0
        ]
        if not valid_results:
            return

        valid_results.sort(key=lambda r: -r.speed)
        fastest = valid_results[0]
        logger.info(
            "自动测速完成，最快源: %s (%.2f KB/s)",
            fastest.source_id, fastest.speed / 1024
        )

    @property
    def is_testing(self) -> bool:
        return self._testing

    def get_speed_result(self, source_id: str) -> Optional[SpeedTestResult]:
        return self._speed_test_results.get(source_id)

    def auto_select_fastest(self) -> Optional[str]:
        valid = [
            (sid, r) for sid, r in self._speed_test_results.items()
            if r.success and r.speed > 0
        ]
        if not valid:
            return None
        valid.sort(key=lambda x: -x[1].speed)
        fastest_id = valid[0][0]
        self.set_current(fastest_id)
        return fastest_id


def get_download_source_manager() -> DownloadSourceManager:
    return DownloadSourceManager.instance()


def rewrite_url(url: str) -> str:
    return get_download_source_manager().rewrite_url(url)
