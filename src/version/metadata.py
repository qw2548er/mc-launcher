"""版本元数据模型模块。

定义 Minecraft 版本元数据的数据类，解析 version.json 文件。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.utils.file_utils import read_json, write_json
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class VersionDownload:
    """文件下载信息。"""

    url: str = ""
    sha1: str = ""
    size: int = 0
    path: str = ""


@dataclass
class LibraryDownload:
    """库文件下载信息。"""

    artifact: Optional[VersionDownload] = None
    classifiers: dict[str, VersionDownload] = field(default_factory=dict)


@dataclass
class LibraryRule:
    """库文件条件规则。"""

    action: str = "allow"  # "allow" 或 "disallow"
    os_name: Optional[str] = None  # "windows", "osx", "linux"
    os_arch: Optional[str] = None


@dataclass
class LibraryInfo:
    """库文件信息。"""

    name: str = ""
    downloads: LibraryDownload = field(default_factory=LibraryDownload)
    natives: dict[str, str] = field(default_factory=dict)
    rules: list[LibraryRule] = field(default_factory=list)
    extract_exclude: list[str] = field(default_factory=list)

    @property
    def group_id(self) -> str:
        """获取 group ID。"""
        parts = self.name.split(":")
        return parts[0] if len(parts) > 0 else ""

    @property
    def artifact_id(self) -> str:
        """获取 artifact ID。"""
        parts = self.name.split(":")
        return parts[1] if len(parts) > 1 else ""

    @property
    def version(self) -> str:
        """获取版本号。"""
        parts = self.name.split(":")
        return parts[2] if len(parts) > 2 else ""

    def is_native(self) -> bool:
        """是否为 native 库。"""
        return bool(self.natives)

    def matches_os(self, os_name: str) -> bool:
        """检查是否匹配当前操作系统。

        Minecraft 规则处理逻辑：
        - 无规则时默认允许
        - 有规则时默认禁止，只有匹配到 allow 规则才允许
        - 规则按顺序处理，最后一个匹配的规则生效
        """
        if not self.rules:
            return True

        allowed = False
        for rule in self.rules:
            matches = True
            if rule.os_name and rule.os_name != os_name:
                matches = False
            if rule.os_arch:
                import platform
                arch = platform.machine().lower()
                if rule.os_arch not in arch:
                    matches = False
            if matches:
                allowed = rule.action == "allow"
        return allowed


@dataclass
class VersionMetadata:
    """Minecraft 版本元数据。

    对应 version.json 文件的解析结果。
    """

    id: str = ""
    type: str = "release"  # release, snapshot, old_beta, old_alpha
    time: str = ""
    release_time: str = ""
    url: str = ""  # version.json 下载 URL
    main_class: str = "net.minecraft.client.main.Main"
    jar: str = ""  # 继承的版本 jar
    inherits_from: str = ""  # 继承的版本 ID
    minimum_launcher_version: int = 21

    # 下载信息
    client_download: VersionDownload = field(default_factory=VersionDownload)
    server_download: Optional[VersionDownload] = None

    # 资源文件
    asset_index: VersionDownload = field(default_factory=VersionDownload)
    assets: str = ""  # assets index 名称

    # Java 版本
    java_version: int = 8
    java_component: str = "jre-legacy"

    # 库文件
    libraries: list[LibraryInfo] = field(default_factory=list)

    # 启动参数
    game_arguments: list[Any] = field(default_factory=list)
    jvm_arguments: list[Any] = field(default_factory=list)
    minecraft_arguments: str = ""  # 旧版参数格式

    # 原始 JSON（保留未解析的字段）
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "VersionMetadata":
        """从 JSON 字典创建 VersionMetadata。

        Args:
            data: version.json 解析后的字典

        Returns:
            VersionMetadata 实例
        """
        meta = cls()
        meta.raw = data

        meta.id = data.get("id", "")
        meta.type = data.get("type", "release")
        meta.time = data.get("time", "")
        meta.release_time = data.get("releaseTime", "")
        meta.url = data.get("url", "")
        meta.main_class = data.get("mainClass", "net.minecraft.client.main.Main")
        meta.jar = data.get("jar", meta.id)
        meta.inherits_from = data.get("inheritsFrom", "")
        meta.minimum_launcher_version = data.get("minimumLauncherVersion", 21)

        # 解析下载信息
        downloads = data.get("downloads", {})
        client_dl = downloads.get("client", {})
        meta.client_download = VersionDownload(
            url=client_dl.get("url", ""),
            sha1=client_dl.get("sha1", ""),
            size=client_dl.get("size", 0),
            path=client_dl.get("path", ""),
        )
        server_dl = downloads.get("server")
        if server_dl:
            meta.server_download = VersionDownload(
                url=server_dl.get("url", ""),
                sha1=server_dl.get("sha1", ""),
                size=server_dl.get("size", 0),
            )

        # asset index
        asset_idx = data.get("assetIndex", {})
        meta.asset_index = VersionDownload(
            url=asset_idx.get("url", ""),
            sha1=asset_idx.get("sha1", ""),
            size=asset_idx.get("size", 0),
            path=asset_idx.get("id", "") + ".json",
        )
        meta.assets = data.get("assets", "")

        # Java 版本
        java_ver = data.get("javaVersion", {})
        meta.java_component = java_ver.get("component", "jre-legacy")
        meta.java_version = java_ver.get("majorVersion", 8)

        # 解析库文件
        meta.libraries = []
        for lib_data in data.get("libraries", []):
            lib = cls._parse_library(lib_data)
            meta.libraries.append(lib)

        # 启动参数
        arguments = data.get("arguments", {})
        meta.game_arguments = arguments.get("game", [])
        meta.jvm_arguments = arguments.get("jvm", [])
        meta.minecraft_arguments = data.get("minecraftArguments", "")

        return meta

    @classmethod
    def from_file(cls, file_path: Path) -> Optional["VersionMetadata"]:
        """从 version.json 文件创建 VersionMetadata。

        Args:
            file_path: version.json 文件路径

        Returns:
            VersionMetadata，解析失败返回 None
        """
        data = read_json(file_path)
        if data is None or not isinstance(data, dict):
            logger.error("无法解析版本文件: %s", file_path)
            return None
        return cls.from_json(data)

    def to_json(self) -> dict[str, Any]:
        """转换为 JSON 字典（保留原始数据）。"""
        return self.raw

    def save(self, file_path: Path) -> bool:
        """保存 version.json。

        Args:
            file_path: 保存路径

        Returns:
            True 表示保存成功
        """
        return write_json(file_path, self.raw)

    @staticmethod
    def _parse_library(lib_data: dict[str, Any]) -> LibraryInfo:
        """解析单个库文件信息。"""
        lib = LibraryInfo()
        lib.name = lib_data.get("name", "")

        # 下载信息
        downloads = lib_data.get("downloads", {})
        artifact_dl = downloads.get("artifact")
        if artifact_dl:
            lib.downloads.artifact = VersionDownload(
                url=artifact_dl.get("url", ""),
                sha1=artifact_dl.get("sha1", ""),
                size=artifact_dl.get("size", 0),
                path=artifact_dl.get("path", ""),
            )

        # classifiers (natives)
        classifiers = downloads.get("classifiers", {})
        for cls_name, cls_data in classifiers.items():
            lib.downloads.classifiers[cls_name] = VersionDownload(
                url=cls_data.get("url", ""),
                sha1=cls_data.get("sha1", ""),
                size=cls_data.get("size", 0),
                path=cls_data.get("path", ""),
            )

        # natives
        lib.natives = lib_data.get("natives", {})

        # extract 排除列表
        extract = lib_data.get("extract", {})
        lib.extract_exclude = extract.get("exclude", [])

        # 规则
        for rule_data in lib_data.get("rules", []):
            rule = LibraryRule(
                action=rule_data.get("action", "allow"),
            )
            os_info = rule_data.get("os", {})
            rule.os_name = os_info.get("name")
            rule.os_arch = os_info.get("arch")
            lib.rules.append(rule)

        return lib


@dataclass
class VersionEntry:
    """版本清单中的版本条目（来自 version_manifest.json）。"""

    id: str = ""
    type: str = "release"
    url: str = ""
    time: str = ""
    release_time: str = ""
    sha1: str = ""
    compliance_level: int = 0

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "VersionEntry":
        return cls(
            id=data.get("id", ""),
            type=data.get("type", "release"),
            url=data.get("url", ""),
            time=data.get("time", ""),
            release_time=data.get("releaseTime", ""),
            sha1=data.get("sha1", ""),
            compliance_level=data.get("complianceLevel", 0),
        )

    @property
    def is_release(self) -> bool:
        return self.type == "release"

    @property
    def is_snapshot(self) -> bool:
        return self.type == "snapshot"

    @property
    def is_old_beta(self) -> bool:
        return self.type == "old_beta"

    @property
    def is_old_alpha(self) -> bool:
        return self.type == "old_alpha"