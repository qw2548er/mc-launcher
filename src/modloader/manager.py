"""模组加载器管理器。

统一管理 Forge、Fabric、Quilt 等加载器实例。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .forge import ForgeLoader
from .fabric import FabricLoader
from .quilt import QuiltLoader
from .mod_manager import ModManager

logger = logging.getLogger(__name__)


class ModLoaderManager:
    """模组加载器管理器，统一管理各个加载器和模组管理器。"""

    def __init__(self, game_dir: Optional[Path] = None):
        self._game_dir = game_dir or Path.home() / ".minecraft"
        self._versions_dir = self._game_dir / "versions"
        self._libraries_dir = self._game_dir / "libraries"
        self._mods_dir = self._game_dir / "mods"

        self.forge = ForgeLoader(game_dir=self._game_dir)
        self.fabric = FabricLoader(game_dir=self._game_dir)
        self.quilt = QuiltLoader(game_dir=self._game_dir)
        self.mod_manager = ModManager(mods_dir=self._mods_dir)

    @property
    def game_dir(self) -> Path:
        return self._game_dir

    @property
    def mods_dir(self) -> Path:
        return self._mods_dir

    def detect_loader_type(self, version_id: str) -> str:
        """检测版本使用的加载器类型。"""
        version_json = self._versions_dir / version_id / f"{version_id}.json"
        if not version_json.exists():
            return "unknown"

        try:
            import json
            with open(version_json, 'r', encoding='utf-8') as f:
                data = json.load(f)

            main_class = data.get("mainClass", "")
            if "forge" in main_class.lower() or "fml" in main_class.lower():
                return "forge"
            elif "fabric" in main_class.lower():
                return "fabric"
            elif "quilt" in main_class.lower():
                return "quilt"
            elif "neoforge" in main_class.lower():
                return "neoforge"
            else:
                return "vanilla"
        except Exception as e:
            logger.error("检测版本 %s 加载器类型失败: %s", version_id, e)
            return "unknown"

    def get_installed_modded_versions(self) -> list[tuple[str, str]]:
        """获取所有已安装的带加载器的版本列表。

        Returns:
            list[tuple[str, str]]: (version_id, loader_type) 列表
        """
        result = []
        if not self._versions_dir.exists():
            return result

        for version_dir in self._versions_dir.iterdir():
            if not version_dir.is_dir():
                continue
            version_id = version_dir.name
            loader_type = self.detect_loader_type(version_id)
            if loader_type in ("forge", "fabric", "quilt", "neoforge"):
                result.append((version_id, loader_type))

        return result
