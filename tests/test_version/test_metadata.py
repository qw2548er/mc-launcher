"""版本元数据模块单元测试。"""

import json
import tempfile
from pathlib import Path

import pytest

from src.version.metadata import (
    LibraryInfo,
    LibraryRule,
    VersionDownload,
    VersionEntry,
    VersionMetadata,
)


class TestVersionEntry:
    """VersionEntry 测试。"""

    def test_from_json(self):
        """测试从 JSON 创建版本条目。"""
        data = {
            "id": "1.20.4",
            "type": "release",
            "url": "https://example.com/1.20.4.json",
            "time": "2023-12-07T00:00:00Z",
            "releaseTime": "2023-12-07T00:00:00Z",
            "sha1": "abc123",
            "complianceLevel": 1,
        }
        entry = VersionEntry.from_json(data)
        assert entry.id == "1.20.4"
        assert entry.type == "release"
        assert entry.is_release is True
        assert entry.is_snapshot is False
        assert entry.is_old_beta is False
        assert entry.is_old_alpha is False

    def test_snapshot_type(self):
        """测试快照版本类型。"""
        entry = VersionEntry(id="24w10a", type="snapshot")
        assert entry.is_snapshot is True
        assert entry.is_release is False


class TestVersionDownload:
    """VersionDownload 测试。"""

    def test_create(self):
        dl = VersionDownload(
            url="https://example.com/client.jar",
            sha1="abc123",
            size=12345,
            path="com/example/test.jar",
        )
        assert dl.size == 12345
        assert dl.sha1 == "abc123"


class TestLibraryInfo:
    """LibraryInfo 测试。"""

    def test_parse_name(self):
        """测试解析 Maven 坐标。"""
        lib = LibraryInfo(name="com.google.code.gson:gson:2.10.1")
        assert lib.group_id == "com.google.code.gson"
        assert lib.artifact_id == "gson"
        assert lib.version == "2.10.1"
        assert lib.is_native() is False

    def test_matches_os_no_rules(self):
        """测试无规则时匹配所有 OS。"""
        lib = LibraryInfo(name="com.example:lib:1.0")
        assert lib.matches_os("windows") is True
        assert lib.matches_os("linux") is True
        assert lib.matches_os("osx") is True

    def test_matches_os_allow_windows(self):
        """测试只允许 Windows 的规则。"""
        lib = LibraryInfo(name="com.example:lib:1.0")
        lib.rules = [LibraryRule(action="allow", os_name="windows")]
        assert lib.matches_os("windows") is True
        assert lib.matches_os("linux") is False

    def test_matches_os_disallow_linux(self):
        """测试禁止 Linux 的规则。"""
        lib = LibraryInfo(name="com.example:lib:1.0")
        lib.rules = [
            LibraryRule(action="allow"),
            LibraryRule(action="disallow", os_name="linux"),
        ]
        assert lib.matches_os("windows") is True
        assert lib.matches_os("linux") is False

    def test_is_native(self):
        """测试 native 库判断。"""
        lib = LibraryInfo(
            name="org.lwjgl:lwjgl:3.3.1",
            natives={"windows": "natives-windows", "linux": "natives-linux"},
        )
        assert lib.is_native() is True


class TestVersionMetadata:
    """VersionMetadata 测试。"""

    @pytest.fixture
    def sample_version_json(self):
        """示例 version.json 数据。"""
        return {
            "id": "1.20.4",
            "type": "release",
            "time": "2023-12-07T00:00:00Z",
            "releaseTime": "2023-12-07T00:00:00Z",
            "mainClass": "net.minecraft.client.main.Main",
            "minimumLauncherVersion": 21,
            "downloads": {
                "client": {
                    "url": "https://example.com/client.jar",
                    "sha1": "abcdef123456",
                    "size": 23456789,
                },
            },
            "assetIndex": {
                "id": "5",
                "url": "https://example.com/5.json",
                "sha1": "assetsha1",
                "size": 500000,
            },
            "assets": "5",
            "javaVersion": {
                "component": "java-runtime-gamma",
                "majorVersion": 17,
            },
            "libraries": [
                {
                    "name": "com.google.code.gson:gson:2.10.1",
                    "downloads": {
                        "artifact": {
                            "path": "com/google/code/gson/gson/2.10.1/gson-2.10.1.jar",
                            "url": "https://libraries.example.com/gson-2.10.1.jar",
                            "sha1": "gsonsha1",
                            "size": 280000,
                        }
                    }
                },
            ],
            "arguments": {
                "game": ["--demo"],
                "jvm": ["-Xmx2G"],
            },
        }

    def test_from_json(self, sample_version_json):
        """测试从 JSON 解析版本元数据。"""
        meta = VersionMetadata.from_json(sample_version_json)
        assert meta.id == "1.20.4"
        assert meta.type == "release"
        assert meta.main_class == "net.minecraft.client.main.Main"
        assert meta.java_version == 17
        assert meta.assets == "5"
        assert meta.client_download.url == "https://example.com/client.jar"
        assert meta.client_download.size == 23456789
        assert meta.client_download.sha1 == "abcdef123456"
        assert meta.asset_index.url == "https://example.com/5.json"
        assert len(meta.libraries) == 1
        assert meta.game_arguments == ["--demo"]
        assert meta.jvm_arguments == ["-Xmx2G"]

    def test_from_json_old_format(self):
        """测试解析旧版格式（minecraftArguments）。"""
        data = {
            "id": "1.12.2",
            "type": "release",
            "mainClass": "net.minecraft.launchwrapper.Launch",
            "minecraftArguments": "--username ${auth_player_name} --version ${version_name}",
            "libraries": [],
            "downloads": {},
        }
        meta = VersionMetadata.from_json(data)
        assert meta.id == "1.12.2"
        assert meta.minecraft_arguments.startswith("--username")
        assert meta.java_version == 8  # 默认值

    def test_from_file(self, sample_version_json):
        """测试从文件加载版本元数据。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "1.20.4.json"
            f.write_text(json.dumps(sample_version_json))
            meta = VersionMetadata.from_file(f)
            assert meta is not None
            assert meta.id == "1.20.4"

    def test_from_file_invalid(self):
        """测试加载无效文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "bad.json"
            f.write_text("not json")
            assert VersionMetadata.from_file(f) is None

    def test_to_json_preserves_raw(self, sample_version_json):
        """测试转换回 JSON 保留原始数据。"""
        meta = VersionMetadata.from_json(sample_version_json)
        result = meta.to_json()
        assert result["id"] == "1.20.4"
        assert "downloads" in result

    def test_save_and_load(self, sample_version_json):
        """测试保存和加载。"""
        meta = VersionMetadata.from_json(sample_version_json)
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "version.json"
            assert meta.save(f) is True
            assert f.exists()
            loaded = VersionMetadata.from_file(f)
            assert loaded is not None
            assert loaded.id == "1.20.4"

    def test_inherits_from(self):
        """测试版本继承。"""
        data = {
            "id": "1.20.4-forge-49.0.30",
            "inheritsFrom": "1.20.4",
            "jar": "1.20.4",
            "type": "modified",
            "mainClass": "cpw.mods.bootstraplauncher.BootstrapLauncher",
            "libraries": [],
            "downloads": {},
        }
        meta = VersionMetadata.from_json(data)
        assert meta.inherits_from == "1.20.4"
        assert meta.jar == "1.20.4"

    def test_library_parsing_natives(self):
        """测试带 natives 的库解析。"""
        data = {
            "id": "1.20.4",
            "type": "release",
            "libraries": [
                {
                    "name": "org.lwjgl:lwjgl:3.3.1",
                    "natives": {
                        "windows": "natives-windows",
                        "linux": "natives-linux",
                    },
                    "downloads": {
                        "classifiers": {
                            "natives-windows": {
                                "url": "https://example.com/lwjgl-natives-windows.jar",
                                "sha1": "winsha1",
                                "size": 1000,
                                "path": "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar",
                            }
                        }
                    },
                    "extract": {"exclude": ["META-INF/"]},
                    "rules": [
                        {"action": "allow", "os": {"name": "windows"}},
                    ],
                },
            ],
        }
        meta = VersionMetadata.from_json(data)
        assert len(meta.libraries) == 1
        lib = meta.libraries[0]
        assert lib.is_native() is True
        assert "windows" in lib.natives
        assert "META-INF/" in lib.extract_exclude
        assert len(lib.rules) == 1
        assert lib.rules[0].action == "allow"