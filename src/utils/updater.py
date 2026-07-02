"""自动更新模块。

启动时检查更新、展示更新日志、下载并应用增量更新。
"""

from __future__ import annotations

import json
import logging
import platform
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.utils.http_utils import HttpClient, get_http_client
from src.utils.crash_handler import get_launcher_version

logger = logging.getLogger(__name__)

UPDATE_API_URL = "https://api.github.com/repos/mc-launcher/releases/latest"


@dataclass
class UpdateInfo:
    """更新信息。"""

    version: str                 # 新版本号
    changelog: str               # 更新日志
    download_url: str            # 下载地址
    filename: str                # 文件名
    file_size: int = 0           # 文件大小
    sha256: str = ""             # SHA256 校验
    is_incremental: bool = False  # 是否增量更新
    published_at: str = ""       # 发布时间
    assets: list[dict] = field(default_factory=list)


class UpdateChecker:
    """更新检查器。

    检查新版本、下载更新包、应用更新。
    """

    def __init__(self, http_client: Optional[HttpClient] = None,
                 update_url: str = UPDATE_API_URL,
                 current_version: Optional[str] = None):
        self._http = http_client or get_http_client()
        self._update_url = update_url
        self._current_version = current_version or get_launcher_version()
        self._cancel_flag = False

    @property
    def current_version(self) -> str:
        return self._current_version

    def cancel(self) -> None:
        self._cancel_flag = True

    def check_for_updates(self, force: bool = False) -> Optional[UpdateInfo]:
        """检查是否有新版本。

        Args:
            force: 是否强制检查（忽略缓存）

        Returns:
            有新版本返回 UpdateInfo，否则返回 None
        """
        try:
            data = self._http.get_json(self._update_url, timeout=10)
            if not isinstance(data, dict):
                return None

            tag = data.get("tag_name", "").lstrip("v")
            if not tag:
                return None

            if not self._is_newer(tag):
                logger.info("当前已是最新版本: %s", self._current_version)
                return None

            changelog = data.get("body", "")
            published_at = data.get("published_at", "")

            download_url, filename, file_size, sha = self._get_download_asset(data)

            update = UpdateInfo(
                version=tag,
                changelog=changelog,
                download_url=download_url,
                filename=filename,
                file_size=file_size,
                sha256=sha,
                published_at=published_at,
                assets=data.get("assets", []),
            )

            logger.info("发现新版本: %s -> %s", self._current_version, tag)
            return update

        except Exception as e:
            logger.warning("检查更新失败: %s", e)
            return None

    def _is_newer(self, remote_version: str) -> bool:
        try:
            current = self._parse_version(self._current_version)
            remote = self._parse_version(remote_version)
            return remote > current
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _parse_version(version_str: str) -> tuple[int, ...]:
        parts = []
        for part in version_str.split("."):
            digit_chars = ""
            for ch in part:
                if ch.isdigit():
                    digit_chars += ch
                else:
                    break
            if digit_chars:
                parts.append(int(digit_chars))
            else:
                parts.append(0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])

    def _get_download_asset(self, data: dict) -> tuple[str, str, int, str]:
        assets = data.get("assets", [])
        system = platform.system().lower()
        arch = platform.machine().lower()

        targets = {
            "windows": [".exe", "-win", "windows"],
            "darwin": [".dmg", ".app", "-mac", "darwin", "macos"],
            "linux": [".appimage", "-linux", "linux"],
        }

        prefixes = targets.get(system, [])
        if "64" in arch or arch in ("x86_64", "amd64", "aarch64", "arm64"):
            arch_suffix = ("64", "amd64", "x86_64")
        else:
            arch_suffix = ("32", "x86")

        for asset in assets:
            name = asset.get("name", "").lower()
            url = asset.get("browser_download_url", "")
            size = asset.get("size", 0)
            if not url:
                continue
            is_match = any(p in name for p in prefixes)
            if is_match and any(a in name for a in arch_suffix):
                return url, asset.get("name", ""), size, ""

        if assets:
            a = assets[0]
            return a.get("browser_download_url", ""), a.get("name", ""), a.get("size", 0), ""

        tarball = data.get("tarball_url", "")
        return tarball, f"source-{data.get('tag_name', '')}.tar.gz", 0, ""

    def download_update(
        self,
        update: UpdateInfo,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> Optional[Path]:
        """下载更新包。

        Args:
            update: 更新信息
            progress_callback: 进度回调（已下载字节、总字节、速度 B/s）

        Returns:
            下载文件路径，失败返回 None
        """
        try:
            save_dir = Path(tempfile.gettempdir()) / "mc_launcher_updates"
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / update.filename

            self._http.download_file(
                url=update.download_url,
                save_path=save_path,
                progress_callback=progress_callback,
                resume=True,
            )

            logger.info("更新包下载完成: %s", save_path)
            return save_path

        except Exception as e:
            logger.error("下载更新失败: %s", e)
            return None

    def apply_update(self, update_file: Path) -> bool:
        """应用更新。

        下载完成后重启启动器并替换自身。

        Args:
            update_file: 更新文件路径

        Returns:
            True 表示已触发更新（程序即将重启）
        """
        try:
            import os
            import subprocess

            current_exe = Path(sys.executable)

            if platform.system() == "Windows":
                bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
copy /Y "{update_file}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
                bat_path = save_dir = Path(tempfile.gettempdir()) / "mc_updater.bat"
                bat_path.write_text(bat_content, encoding="gbk")
                subprocess.Popen(["cmd", "/c", str(bat_path)], shell=False)
            elif platform.system() == "Linux":
                sh_content = f"""#!/bin/bash
sleep 2
cp "{update_file}" "{current_exe}"
chmod +x "{current_exe}"
"{current_exe}" &
rm "$0"
"""
                sh_path = Path(tempfile.gettempdir()) / "mc_updater.sh"
                sh_path.write_text(sh_content)
                sh_path.chmod(0o755)
                subprocess.Popen(["/bin/bash", str(sh_path)])
            else:
                logger.warning("不支持在 %s 上自动更新", platform.system())
                return False

            logger.info("更新脚本已启动，即将重启...")
            return True

        except Exception as e:
            logger.error("应用更新失败: %s", e)
            return False

    def get_release_notes(self, version: str) -> str:
        """获取指定版本的更新日志。

        Args:
            version: 版本号

        Returns:
            更新日志 Markdown 文本
        """
        try:
            url = f"https://api.github.com/repos/mc-launcher/releases/tags/v{version}"
            data = self._http.get_json(url, timeout=10)
            return data.get("body", self.tr("无更新日志"))
        except Exception:
            return self.tr("无法获取更新日志")

    @staticmethod
    def tr(text: str) -> str:
        return text