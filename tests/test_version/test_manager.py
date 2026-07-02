"""Version Manager 模块单元测试。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.version.api import VersionManifest
from src.version.version_manager import VersionManager
from src.version.metadata import VersionEntry, VersionMetadata


class TestVersionManager:
    """版本管理器测试。"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir) / ".minecraft"
            game_dir.mkdir()
            config_patcher = patch("src.version.version_manager.get_config")
            mock_config = MagicMock()
            mock_config.get.side_effect = lambda key, default=None: {
                "game_directory": str(game_dir),
                "download.max_threads": 2,
                "default_version": "",
                "advanced.show_snapshots": False,
                "advanced.show_beta": False,
                "advanced.show_alpha": False,
            }.get(key, default)
            mock_config.set = MagicMock()
            mock_config.save = MagicMock()
            mock_config_patch = config_patcher.start()
            mock_config_patch.return_value = mock_config

            from src.utils.http_utils import HttpClient
            mock_client = MagicMock(spec=HttpClient)
            mgr = VersionManager(game_dir=game_dir, client=mock_client)
            yield mgr
            config_patcher.stop()

    def test_get_installed_empty(self, manager):
        """测试空的已安装列表。"""
        assert manager.get_installed_versions() == []

    def test_is_installed_false(self, manager):
        """测试未安装版本。"""
        assert manager.is_installed("1.20.4") is False

    def test_get_installed_versions(self, manager):
        """测试获取已安装版本。"""
        version_dir = manager._versions_dir / "1.20.4"
        version_dir.mkdir(parents=True)
        (version_dir / "1.20.4.jar").write_bytes(b"fake jar")
        version_json = {
            "id": "1.20.4",
            "type": "release",
            "mainClass": "net.minecraft.client.main.Main",
            "libraries": [],
            "downloads": {},
        }
        (version_dir / "1.20.4.json").write_text(json.dumps(version_json))

        installed = manager.get_installed_versions()
        assert len(installed) == 1
        assert installed[0].id == "1.20.4"

    def test_is_installed_true(self, manager):
        """测试已安装版本。"""
        version_dir = manager._versions_dir / "1.20.4"
        version_dir.mkdir(parents=True)
        (version_dir / "1.20.4.jar").write_bytes(b"jar")
        (version_dir / "1.20.4.json").write_text(json.dumps({"id": "1.20.4"}))
        assert manager.is_installed("1.20.4") is True

    def test_uninstall_version(self, manager):
        """测试卸载版本。"""
        version_dir = manager._versions_dir / "1.20.4"
        version_dir.mkdir(parents=True)
        (version_dir / "1.20.4.jar").write_bytes(b"jar")
        (version_dir / "1.20.4.json").write_text(json.dumps({"id": "1.20.4"}))

        assert manager.is_installed("1.20.4") is True
        assert manager.uninstall_version("1.20.4") is True
        assert manager.is_installed("1.20.4") is False

    def test_uninstall_nonexistent(self, manager):
        """测试卸载不存在的版本。"""
        assert manager.uninstall_version("nonexistent") is False

    def test_get_available_versions(self, manager):
        """测试获取可用版本列表。"""
        manifest = VersionManifest()
        manifest.latest_release = "1.20.4"
        manifest.versions = [
            VersionEntry(id="1.20.4", type="release"),
            VersionEntry(id="1.16.5", type="release"),
            VersionEntry(id="24w10a", type="snapshot"),
            VersionEntry(id="b1.7.3", type="old_beta"),
        ]

        with patch.object(manager, "fetch_remote_versions", return_value=manifest):
            versions = manager.get_available_versions()
            assert len(versions) == 2
            assert all(v.is_release for v in versions)

    def test_get_available_versions_with_snapshots(self, manager):
        """测试包含快照版本的可用列表。"""
        manifest = VersionManifest()
        manifest.versions = [
            VersionEntry(id="1.20.4", type="release"),
            VersionEntry(id="24w10a", type="snapshot"),
        ]

        with patch.object(manager, "fetch_remote_versions", return_value=manifest):
            versions = manager.get_available_versions(show_snapshots=True)
            assert len(versions) == 2

    def test_get_version_size(self, manager):
        """测试获取版本大小。"""
        version_dir = manager._versions_dir / "1.20.4"
        version_dir.mkdir(parents=True)
        (version_dir / "1.20.4.jar").write_bytes(b"hello")
        size = manager.get_version_size("1.20.4")
        assert size == 5

    def test_cancel_install(self, manager):
        """测试取消安装（无正在进行的安装时不报错）。"""
        manager.cancel_install()

    def test_rename_version(self, manager):
        """测试重命名版本。"""
        version_dir = manager._versions_dir / "1.20.4"
        version_dir.mkdir(parents=True)
        (version_dir / "1.20.4.jar").write_bytes(b"jar content")
        (version_dir / "1.20.4.json").write_text(json.dumps({"id": "1.20.4"}))

        assert manager.rename_version("1.20.4", "1.20.5") is True
        assert not (manager._versions_dir / "1.20.4").exists()
        assert (manager._versions_dir / "1.20.5").exists()
        assert (manager._versions_dir / "1.20.5" / "1.20.5.jar").is_file()
        assert (manager._versions_dir / "1.20.5" / "1.20.5.json").is_file()

    def test_copy_version(self, manager):
        """测试复制版本。"""
        version_dir = manager._versions_dir / "1.20.4"
        version_dir.mkdir(parents=True)
        (version_dir / "1.20.4.jar").write_bytes(b"jar content")
        (version_dir / "1.20.4.json").write_text(json.dumps({"id": "1.20.4"}))

        assert manager.copy_version("1.20.4", "1.20.4-copy") is True
        assert (manager._versions_dir / "1.20.4").exists()
        assert (manager._versions_dir / "1.20.4-copy").exists()
        assert (manager._versions_dir / "1.20.4-copy" / "1.20.4-copy.jar").is_file()
