"""数据备份模块。

提供配置文件自动备份、存档备份功能。
"""

from __future__ import annotations

import logging
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_BACKUP_COUNT = 10


class BackupManager:
    """备份管理器。

    自动备份配置文件，支持世界存档备份和恢复。
    """

    def __init__(self, game_dir: Optional[Path] = None,
                 backup_dir: Optional[Path] = None):
        self._game_dir = game_dir or Path.home() / ".minecraft"
        self._backup_dir = backup_dir or self._game_dir / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    @property
    def game_dir(self) -> Path:
        return self._game_dir

    @game_dir.setter
    def game_dir(self, path: Path) -> None:
        self._game_dir = Path(path)
        self._backup_dir = self._game_dir / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    @property
    def backup_dir(self) -> Path:
        return self._backup_dir

    def backup_config(self) -> Optional[Path]:
        """备份配置文件。

        Returns:
            备份文件路径，失败返回 None
        """
        config_dir = self._game_dir
        if not config_dir.exists():
            logger.warning("游戏目录不存在: %s", config_dir)
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"config_backup_{timestamp}.zip"
        backup_path = self._backup_dir / backup_name

        try:
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
                config_files = [
                    "options.txt",
                    "optionsof.txt",
                    "servers.dat",
                    "servers.dat_old",
                    "launcher_profiles.json",
                    "launcher_accounts.json",
                ]
                config_dirs = ["config", "resourcepacks"]

                for name in config_files:
                    fp = config_dir / name
                    if fp.exists() and fp.is_file():
                        zf.write(fp, fp.name)

                for dirname in config_dirs:
                    dp = config_dir / dirname
                    if dp.exists() and dp.is_dir():
                        for f in dp.rglob("*"):
                            if f.is_file():
                                try:
                                    zf.write(f, f"{dirname}/{f.relative_to(dp)}")
                                except (OSError, ValueError):
                                    continue

            self._rotate_backups("config_backup", MAX_BACKUP_COUNT)
            logger.info("配置已备份至: %s", backup_path)
            return backup_path

        except (OSError, zipfile.BadZipFile) as e:
            logger.error("备份配置失败: %s", e)
            if backup_path.exists():
                try:
                    backup_path.unlink()
                except OSError:
                    pass
            return None

    def backup_world(self, world_name: str) -> Optional[Path]:
        """备份指定世界存档。

        Args:
            world_name: 世界文件夹名

        Returns:
            备份文件路径，失败返回 None
        """
        saves_dir = self._game_dir / "saves"
        world_dir = saves_dir / world_name
        if not world_dir.exists():
            logger.error("世界不存在: %s", world_dir)
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"world_{world_name}_{timestamp}.zip"
        backup_path = self._backup_dir / backup_name

        try:
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in world_dir.rglob("*"):
                    if f.is_file():
                        try:
                            zf.write(f, f.relative_to(world_dir.parent))
                        except (OSError, ValueError):
                            continue

            self._rotate_backups(f"world_{world_name}", MAX_BACKUP_COUNT)
            logger.info("世界 %s 已备份至: %s", world_name, backup_path)
            return backup_path

        except (OSError, zipfile.BadZipFile) as e:
            logger.error("备份世界失败: %s", e)
            if backup_path.exists():
                try:
                    backup_path.unlink()
                except OSError:
                    pass
            return None

    def backup_all_worlds(self, progress_callback: Optional[Callable[[str, int, int], None]] = None) -> list[Path]:
        """备份所有世界存档。

        Args:
            progress_callback: 进度回调（当前世界名, 当前索引, 总数）

        Returns:
            成功备份的文件路径列表
        """
        saves_dir = self._game_dir / "saves"
        if not saves_dir.exists():
            logger.warning("saves 目录不存在: %s", saves_dir)
            return []

        worlds = [d for d in saves_dir.iterdir() if d.is_dir()]
        results = []

        for i, world in enumerate(worlds):
            if progress_callback:
                progress_callback(world.name, i, len(worlds))
            path = self.backup_world(world.name)
            if path:
                results.append(path)

        return results

    def restore_backup(self, backup_path: Path, overwrite: bool = False) -> bool:
        """从备份文件恢复。

        Args:
            backup_path: 备份 zip 文件路径
            overwrite: 是否覆盖现有文件

        Returns:
            True 表示恢复成功
        """
        if not backup_path.exists():
            logger.error("备份文件不存在: %s", backup_path)
            return False

        try:
            temp_dir = self._backup_dir / "restore_temp"
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(temp_dir)

            self._merge_directory(temp_dir, self._game_dir, overwrite=overwrite)

            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info("已从备份恢复: %s", backup_path)
            return True

        except (OSError, zipfile.BadZipFile) as e:
            logger.error("恢复备份失败: %s", e)
            return False

    def list_backups(self, prefix: Optional[str] = None) -> list[dict]:
        """列出所有备份文件。

        Args:
            prefix: 文件名前缀过滤（如 "config"、"world_MyWorld"）

        Returns:
            备份信息列表 [{"path": Path, "name": str, "size": int, "date": str}]
        """
        backups = []
        if not self._backup_dir.exists():
            return backups

        for f in sorted(self._backup_dir.iterdir(), reverse=True):
            if not f.is_file() or not f.suffix == ".zip":
                continue
            if prefix and not f.name.startswith(prefix):
                continue
            try:
                stat = f.stat()
                backups.append({
                    "path": f,
                    "name": f.stem,
                    "size": stat.st_size,
                    "date": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
            except OSError:
                continue

        return backups

    def delete_backup(self, backup_path: Path) -> bool:
        try:
            if backup_path.exists():
                backup_path.unlink()
                return True
            return False
        except OSError as e:
            logger.error("删除备份失败: %s", e)
            return False

    def _rotate_backups(self, prefix: str, max_count: int) -> None:
        backups = self.list_backups(prefix=prefix)
        if len(backups) <= max_count:
            return
        for b in backups[max_count:]:
            self.delete_backup(b["path"])

    @staticmethod
    def _merge_directory(src: Path, dst: Path, overwrite: bool = False) -> None:
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                BackupManager._merge_directory(item, target, overwrite)
            else:
                if target.exists() and not overwrite:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)