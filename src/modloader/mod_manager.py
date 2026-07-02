"""模组管理器模块。

提供模组扫描、元数据解析、启用/禁用、删除、冲突检测和配置文件管理功能。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import tomllib

from src.utils.file_utils import ensure_directory, calculate_sha1

logger = logging.getLogger(__name__)


class ModLoaderType(str, Enum):
    FORGE = "forge"
    FABRIC = "fabric"
    QUILT = "quilt"
    UNKNOWN = "unknown"


class ModState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    INCOMPATIBLE = "incompatible"
    ERROR = "error"


@dataclass
class ModInfo:
    """模组信息。"""

    file_path: Path
    filename: str
    mod_id: str = ""
    name: str = ""
    version: str = ""
    author: str = ""
    description: str = ""
    loader_type: ModLoaderType = ModLoaderType.UNKNOWN
    state: ModState = ModState.ENABLED
    game_versions: list[str] = field(default_factory=list)
    dependencies: dict[str, str] = field(default_factory=dict)
    file_size: int = 0
    sha1: str = ""
    icon_path: str = ""

    @property
    def is_enabled(self) -> bool:
        return self.state == ModState.ENABLED

    @property
    def is_disabled(self) -> bool:
        return self.state == ModState.DISABLED


@dataclass
class ModConflict:
    """模组冲突信息。"""

    mod_a: ModInfo
    mod_b: ModInfo
    reason: str
    severity: str = "warning"  # "warning" | "error" | "info"


class ModManager:
    """模组管理器。

    负责模组文件的扫描、信息提取、启用/禁用、删除和冲突检测。
    """

    DISABLED_SUFFIX = ".disabled"

    def __init__(self, game_dir: Optional[Path] = None):
        self._game_dir = game_dir or Path.home() / ".minecraft"
        self._mods: list[ModInfo] = []
        self._conflicts: list[ModConflict] = []

    @property
    def game_dir(self) -> Path:
        return self._game_dir

    @game_dir.setter
    def game_dir(self, path: Path) -> None:
        self._game_dir = Path(path)

    @property
    def mods_dir(self) -> Path:
        return self._game_dir / "mods"

    @property
    def config_dir(self) -> Path:
        return self._game_dir / "config"

    def get_mods(self) -> list[ModInfo]:
        return list(self._mods)

    def get_enabled_mods(self) -> list[ModInfo]:
        return [m for m in self._mods if m.is_enabled]

    def get_disabled_mods(self) -> list[ModInfo]:
        return [m for m in self._mods if m.is_disabled]

    def get_mod_by_id(self, mod_id: str) -> Optional[ModInfo]:
        for mod in self._mods:
            if mod.mod_id == mod_id:
                return mod
        return None

    def scan_mods(self, version_dir: Optional[Path] = None) -> list[ModInfo]:
        """扫描 mods 目录，获取所有模组信息。

        Args:
            version_dir: 特定版本的 mods 子目录（如 mods/1.20.1），可选

        Returns:
            扫描到的模组信息列表
        """
        scan_dir = self.mods_dir
        if version_dir:
            scan_dir = scan_dir / version_dir

        self._mods = []
        if not scan_dir.exists():
            return self._mods

        for file_path in sorted(scan_dir.iterdir()):
            if not file_path.is_file():
                continue

            mod_info = self._parse_mod_file(file_path)
            if mod_info is not None:
                self._mods.append(mod_info)
            else:
                logger.debug("跳过非模组文件: %s", file_path.name)

        self._detect_conflicts()
        return self._mods

    def _parse_mod_file(self, file_path: Path) -> Optional[ModInfo]:
        """解析模组文件，提取元数据。"""
        name = file_path.name
        is_disabled = name.endswith(self.DISABLED_SUFFIX)

        if not (name.endswith(".jar") or name.endswith(".zip") or
                (is_disabled and name.endswith(f".jar{self.DISABLED_SUFFIX}")) or
                (is_disabled and name.endswith(f".zip{self.DISABLED_SUFFIX}"))):
            return None

        try:
            file_size = file_path.stat().st_size
        except OSError:
            file_size = 0

        sha1 = calculate_sha1(file_path) if file_path.exists() else ""

        real_name = name
        if is_disabled:
            real_name = name[: -len(self.DISABLED_SUFFIX)]

        mod_info = ModInfo(
            file_path=file_path,
            filename=name,
            name=real_name.replace(".jar", "").replace(".zip", ""),
            file_size=file_size,
            sha1=sha1,
            state=ModState.DISABLED if is_disabled else ModState.ENABLED,
        )

        try:
            self._extract_metadata(mod_info)
        except Exception as e:
            logger.debug("解析模组元数据失败 (%s): %s", name, e)

        return mod_info

    def _extract_metadata(self, mod_info: ModInfo) -> None:
        """从 jar/zip 文件中提取模组元数据。"""
        try:
            with zipfile.ZipFile(mod_info.file_path, "r") as zf:
                namelist = zf.namelist()

                if "fabric.mod.json" in namelist:
                    self._parse_fabric_metadata(mod_info, zf)
                elif "quilt.mod.json" in namelist:
                    self._parse_quilt_metadata(mod_info, zf)
                elif "META-INF/mods.toml" in namelist:
                    self._parse_forge_metadata(mod_info, zf)
                elif "mcmod.info" in namelist:
                    self._parse_mcmod_info(mod_info, zf)
                else:
                    self._parse_universal_metadata(mod_info, zf)
        except (zipfile.BadZipFile, OSError) as e:
            logger.warning("无法打开模组文件 %s: %s", mod_info.filename, e)

    def _parse_fabric_metadata(self, mod_info: ModInfo, zf: zipfile.ZipFile) -> None:
        try:
            data = json.loads(zf.read("fabric.mod.json"))
            mod_info.loader_type = ModLoaderType.FABRIC
            mod_info.mod_id = data.get("id", "")
            mod_info.name = data.get("name", mod_info.name)
            mod_info.version = data.get("version", "")
            mod_info.description = data.get("description", "")
            mod_info.author = self._extract_author(data)

            if "depends" in data:
                mod_info.dependencies = data["depends"]
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("解析 fabric.mod.json 失败: %s", e)

    def _parse_quilt_metadata(self, mod_info: ModInfo, zf: zipfile.ZipFile) -> None:
        try:
            fabric_data = None
            if "fabric.mod.json" in zf.namelist():
                try:
                    fabric_data = json.loads(zf.read("fabric.mod.json"))
                except Exception:
                    pass

            data = json.loads(zf.read("quilt.mod.json"))
            quilt_loader = data.get("quilt_loader", data)
            mod_info.loader_type = ModLoaderType.QUILT
            mod_info.mod_id = quilt_loader.get("id", "")
            mod_info.name = quilt_loader.get("metadata", {}).get("name", "") or quilt_loader.get("name", mod_info.name)
            mod_info.version = quilt_loader.get("version", "")
            mod_info.description = quilt_loader.get("metadata", {}).get("description", "")

            if fabric_data:
                mod_info.name = fabric_data.get("name", mod_info.name)
                mod_info.description = fabric_data.get("description", mod_info.description)
                if "depends" in fabric_data:
                    mod_info.dependencies = fabric_data["depends"]

            authors = quilt_loader.get("metadata", {}).get("contributors", {})
            if isinstance(authors, dict):
                mod_info.author = ", ".join(authors.keys())
            elif isinstance(authors, list):
                mod_info.author = ", ".join(authors)

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("解析 quilt.mod.json 失败: %s", e)

    def _parse_forge_metadata(self, mod_info: ModInfo, zf: zipfile.ZipFile) -> None:
        try:
            content = zf.read("META-INF/mods.toml").decode("utf-8")
            data = tomllib.loads(content)
            mod_info.loader_type = ModLoaderType.FORGE

            mods_list = data.get("mods", [])
            if mods_list:
                mod = mods_list[0]
                mod_info.mod_id = mod.get("modId", "")
                mod_info.name = mod.get("displayName", mod_info.name)
                mod_info.version = mod.get("version", "")
                mod_info.description = mod.get("description", "")
                mod_info.author = mod.get("authors", "")

            dependencies = data.get("dependencies", {})
            for dep_id, dep_info in dependencies.items():
                if isinstance(dep_info, dict):
                    mod_info.dependencies[dep_id] = dep_info.get("versionRange", "*")

        except (tomllib.TOMLDecodeError, KeyError, UnicodeDecodeError) as e:
            logger.debug("解析 mods.toml 失败: %s", e)

    def _parse_mcmod_info(self, mod_info: ModInfo, zf: zipfile.ZipFile) -> None:
        try:
            data = json.loads(zf.read("mcmod.info"))
            mod_info.loader_type = ModLoaderType.FORGE

            if isinstance(data, list) and data:
                entry = data[0]
            elif isinstance(data, dict):
                entry = data
            else:
                return

            mod_info.mod_id = entry.get("modid", "")
            mod_info.name = entry.get("name", mod_info.name)
            mod_info.version = entry.get("version", "")
            mod_info.description = entry.get("description", "")
            authors = entry.get("authorList", entry.get("authors", []))
            if isinstance(authors, list):
                mod_info.author = ", ".join(authors)
            elif isinstance(authors, str):
                mod_info.author = authors

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("解析 mcmod.info 失败: %s", e)

    def _parse_universal_metadata(self, mod_info: ModInfo, zf: zipfile.ZipFile) -> None:
        """通用元数据解析，通过文件名和 MANIFEST.MF 推断。"""
        mod_info.loader_type = ModLoaderType.UNKNOWN

        if "META-INF/MANIFEST.MF" in zf.namelist():
            try:
                manifest = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
                for line in manifest.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip()
                        value = value.strip()
                        if key == "Implementation-Title":
                            mod_info.name = value
                        elif key == "Implementation-Version":
                            mod_info.version = value
                        elif key == "Implementation-Vendor":
                            mod_info.author = value
            except Exception:
                pass

    @staticmethod
    def _extract_author(data: dict) -> str:
        authors = data.get("authors", [])
        if isinstance(authors, list):
            names = []
            for a in authors:
                if isinstance(a, dict):
                    names.append(a.get("name", ""))
                elif isinstance(a, str):
                    names.append(a)
            return ", ".join(filter(None, names))
        if isinstance(authors, str):
            return authors
        author = data.get("author", "")
        return author if isinstance(author, str) else ""

    def enable_mod(self, mod_id: str) -> bool:
        """启用模组（移除 .disabled 后缀）。

        Args:
            mod_id: 模组 ID

        Returns:
            True 表示成功
        """
        mod = self.get_mod_by_id(mod_id)
        if mod is None or not mod.is_disabled:
            return False

        new_path = mod.file_path.with_name(mod.file_path.name[: -len(self.DISABLED_SUFFIX)])
        try:
            mod.file_path.rename(new_path)
            mod.file_path = new_path
            mod.filename = new_path.name
            mod.state = ModState.ENABLED
            logger.info("启用模组: %s", mod.name)
            return True
        except OSError as e:
            logger.error("启用模组失败 (%s): %s", mod.name, e)
            return False

    def disable_mod(self, mod_id: str) -> bool:
        """禁用模组（添加 .disabled 后缀）。

        Args:
            mod_id: 模组 ID

        Returns:
            True 表示成功
        """
        mod = self.get_mod_by_id(mod_id)
        if mod is None or not mod.is_enabled:
            return False

        new_path = mod.file_path.with_name(mod.file_path.name + self.DISABLED_SUFFIX)
        try:
            mod.file_path.rename(new_path)
            mod.file_path = new_path
            mod.filename = new_path.name
            mod.state = ModState.DISABLED
            logger.info("禁用模组: %s", mod.name)
            return True
        except OSError as e:
            logger.error("禁用模组失败 (%s): %s", mod.name, e)
            return False

    def delete_mod(self, mod_id: str) -> bool:
        """删除模组文件。

        Args:
            mod_id: 模组 ID

        Returns:
            True 表示成功
        """
        mod = self.get_mod_by_id(mod_id)
        if mod is None:
            return False

        try:
            mod.file_path.unlink()
            self._mods.remove(mod)
            logger.info("删除模组: %s", mod.name)
            return True
        except OSError as e:
            logger.error("删除模组失败 (%s): %s", mod.name, e)
            return False

    def delete_mods(self, mod_ids: list[str]) -> int:
        """批量删除模组。

        Args:
            mod_ids: 模组 ID 列表

        Returns:
            成功删除的数量
        """
        count = 0
        for mod_id in mod_ids:
            if self.delete_mod(mod_id):
                count += 1
        return count

    def enable_all(self) -> int:
        """启用所有已禁用的模组。"""
        count = 0
        disabled = self.get_disabled_mods()
        for mod in disabled:
            if self.enable_mod(mod.mod_id):
                count += 1
        return count

    def disable_all(self) -> int:
        """禁用所有已启用的模组。"""
        count = 0
        enabled = self.get_enabled_mods()
        for mod in enabled:
            if self.disable_mod(mod.mod_id):
                count += 1
        return count

    def _detect_conflicts(self) -> list[ModConflict]:
        """检测模组冲突。"""
        self._conflicts = []

        mods_by_id: dict[str, list[ModInfo]] = {}
        for mod in self._mods:
            if not mod.mod_id or not mod.is_enabled:
                continue
            mods_by_id.setdefault(mod.mod_id, []).append(mod)

        for mod_id, mods in mods_by_id.items():
            if len(mods) > 1:
                self._conflicts.append(ModConflict(
                    mod_a=mods[0],
                    mod_b=mods[1],
                    reason=f"模组 {mod_id} 存在多个副本",
                    severity="error",
                ))

        for i, mod_a in enumerate(self._mods):
            if not mod_a.is_enabled or not mod_a.dependencies:
                continue
            for dep_id, version_range in mod_a.dependencies.items():
                if dep_id.startswith("minecraft") or dep_id.startswith("java"):
                    continue
                dep_mod = self.get_mod_by_id(dep_id)
                if dep_mod is None:
                    self._conflicts.append(ModConflict(
                        mod_a=mod_a,
                        mod_b=ModInfo(file_path=Path(), filename="", mod_id=dep_id),
                        reason=f"缺少依赖模组: {dep_id}",
                        severity="error",
                    ))
                elif dep_mod.is_disabled:
                    self._conflicts.append(ModConflict(
                        mod_a=mod_a,
                        mod_b=dep_mod,
                        reason=f"依赖模组 {dep_id} 已被禁用",
                        severity="warning",
                    ))

        return self._conflicts

    def get_conflicts(self) -> list[ModConflict]:
        """获取当前模组冲突列表。"""
        return list(self._conflicts)

    def get_config_files(self) -> list[Path]:
        """获取模组相关的配置文件列表。

        Returns:
            配置文件路径列表
        """
        config_files: list[Path] = []
        if not self.config_dir.exists():
            return config_files

        supported_extensions = {".cfg", ".toml", ".json", ".json5", ".properties",
                                ".txt", ".yml", ".yaml", ".ini", ".conf"}

        for file_path in sorted(self.config_dir.rglob("*")):
            if file_path.is_file() and file_path.suffix in supported_extensions:
                config_files.append(file_path)

        return config_files

    def read_config_file(self, file_path: Path) -> dict[str, Any]:
        """读取配置文件内容。

        Args:
            file_path: 配置文件路径

        Returns:
            配置内容字典
        """
        if not file_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {file_path}")

        suffix = file_path.suffix.lower()
        content = file_path.read_text(encoding="utf-8", errors="replace")

        if suffix == ".json" or suffix == ".json5":
            return json.loads(content)
        elif suffix == ".toml":
            return tomllib.loads(content)
        elif suffix in (".properties", ".cfg", ".conf", ".ini"):
            return self._parse_properties(content)
        elif suffix in (".yml", ".yaml"):
            return self._parse_simple_yaml(content)
        else:
            return {"_raw": content}

    def write_config_file(self, file_path: Path, data: dict[str, Any]) -> None:
        """写入配置文件。

        Args:
            file_path: 配置文件路径
            data: 配置数据
        """
        ensure_directory(file_path.parent)

        suffix = file_path.suffix.lower()
        if suffix == ".json":
            content = json.dumps(data, indent=2, ensure_ascii=False)
        elif suffix == ".toml":
            content = self._format_toml(data)
        elif suffix in (".properties", ".cfg", ".conf", ".ini"):
            content = self._format_properties(data)
        else:
            content = data.get("_raw", json.dumps(data, indent=2))

        file_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _parse_properties(content: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
            elif ":" in line:
                key, value = line.split(":", 1)
                result[key.strip()] = value.strip()
        return result

    @staticmethod
    def _parse_simple_yaml(content: str) -> dict[str, Any]:
        """简易 YAML 解析（不依赖 PyYAML）。"""
        result: dict[str, Any] = {}
        for line in content.split("\n"):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().lstrip("- ")
                value = value.strip().strip("'\"")
                result[key] = value
        return result

    @staticmethod
    def _format_properties(data: dict[str, Any]) -> str:
        lines = []
        for key, value in data.items():
            lines.append(f"{key}={value}")
        return "\n".join(lines)

    @staticmethod
    def _format_toml(data: dict[str, Any]) -> str:
        """简易 TOML 格式化（不依赖外部库）。"""
        lines = []
        for key, value in data.items():
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            elif isinstance(value, list):
                items = ", ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in value)
                lines.append(f"{key} = [{items}]")
            elif isinstance(value, dict):
                lines.append(f"\n[{key}]")
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, str):
                        lines.append(f'{sub_key} = "{sub_value}"')
                    else:
                        lines.append(f"{sub_key} = {sub_value}")
        return "\n".join(lines)

    def copy_mod(self, mod_id: str, dest_dir: Path) -> bool:
        """复制模组文件到指定目录。

        Args:
            mod_id: 模组 ID
            dest_dir: 目标目录

        Returns:
            True 表示成功
        """
        mod = self.get_mod_by_id(mod_id)
        if mod is None:
            return False
        try:
            ensure_directory(dest_dir)
            shutil.copy2(mod.file_path, dest_dir / mod.filename)
            return True
        except OSError as e:
            logger.error("复制模组失败 (%s): %s", mod.name, e)
            return False

    def get_mod_count(self) -> int:
        return len(self._mods)

    def get_enabled_count(self) -> int:
        return len(self.get_enabled_mods())

    def get_disabled_count(self) -> int:
        return len(self.get_disabled_mods())

    def get_size_stats(self) -> dict[str, int]:
        """获取模组大小统计。"""
        total = sum(m.file_size for m in self._mods)
        enabled = sum(m.file_size for m in self._mods if m.is_enabled)
        disabled = sum(m.file_size for m in self._mods if m.is_disabled)
        return {"total": total, "enabled": enabled, "disabled": disabled}

    def get_loader_stats(self) -> dict[str, int]:
        """获取各加载器模组数量统计。"""
        stats: dict[str, int] = {}
        for mod in self._mods:
            key = mod.loader_type.value if mod.loader_type else "unknown"
            stats[key] = stats.get(key, 0) + 1
        return stats