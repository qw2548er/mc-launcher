"""模组加载器模块。

提供 Forge、Fabric、Quilt 加载器的安装以及模组管理功能。
"""

from .base import (
    BaseModLoader, ModLoaderType, ModLoaderVersion, InstallResult, InstallProgress,
)
from .forge import ForgeLoader
from .fabric import FabricLoader
from .quilt import QuiltLoader
from .manager import ModLoaderManager
from .mod_manager import ModManager, ModInfo, ModState, ModConflict
from .maven_utils import (
    LibraryArtifact, LibraryDownloadPlan,
    parse_maven_coordinate, resolve_library_artifact, download_libraries,
    extract_maven_from_installer, get_os_name, get_os_arch,
)
from .modrinth import ModrinthAPI, ModrinthProject, ModrinthVersion, ModrinthSearchResult

__all__ = [
    "BaseModLoader",
    "ModLoaderType",
    "ModLoaderVersion",
    "InstallResult",
    "InstallProgress",
    "ForgeLoader",
    "FabricLoader",
    "QuiltLoader",
    "ModLoaderManager",
    "ModManager",
    "ModInfo",
    "ModState",
    "ModConflict",
    "LibraryArtifact",
    "LibraryDownloadPlan",
    "parse_maven_coordinate",
    "resolve_library_artifact",
    "download_libraries",
    "extract_maven_from_installer",
    "get_os_name",
    "get_os_arch",
    "ModrinthAPI",
    "ModrinthProject",
    "ModrinthVersion",
    "ModrinthSearchResult",
]
