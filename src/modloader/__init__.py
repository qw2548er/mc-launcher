"""模组加载器模块。

提供 Forge、Fabric、Quilt 加载器的安装以及模组管理功能。
"""

from .base import (
    BaseModLoader, ModLoaderType, ModLoaderVersion, InstallResult, InstallProgress,
)
from .forge import ForgeLoader
from .fabric import FabricLoader
from .quilt import QuiltLoader
from .mod_manager import ModManager, ModInfo, ModState, ModConflict

__all__ = [
    "BaseModLoader",
    "ModLoaderType",
    "ModLoaderVersion",
    "InstallResult",
    "InstallProgress",
    "ForgeLoader",
    "FabricLoader",
    "QuiltLoader",
    "ModManager",
    "ModInfo",
    "ModState",
    "ModConflict",
]