"""Version API 模块单元测试。"""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.http_utils import HttpError
from src.version.api import VersionAPI, VersionManifest
from src.version.metadata import VersionEntry


class TestVersionManifest:
    """VersionManifest 测试。"""

    @pytest.fixture
    def manifest(self):
        m = VersionManifest()
        m.latest_release = "1.20.4"
        m.latest_snapshot = "24w10a"
        m.versions = [
            VersionEntry(id="1.20.4", type="release"),
            VersionEntry(id="1.16.5", type="release"),
            VersionEntry(id="24w10a", type="snapshot"),
            VersionEntry(id="b1.7.3", type="old_beta"),
            VersionEntry(id="a1.0.4", type="old_alpha"),
        ]
        return m

    def test_releases(self, manifest):
        releases = manifest.releases
        assert len(releases) == 2
        assert all(v.is_release for v in releases)

    def test_snapshots(self, manifest):
        snapshots = manifest.snapshots
        assert len(snapshots) == 1
        assert snapshots[0].id == "24w10a"

    def test_get_version_found(self, manifest):
        v = manifest.get_version("1.20.4")
        assert v is not None
        assert v.id == "1.20.4"

    def test_get_version_not_found(self, manifest):
        v = manifest.get_version("nonexistent")
        assert v is None


class TestVersionAPI:
    """VersionAPI 测试。"""

    @pytest.fixture
    def sample_manifest_data(self):
        return {
            "latest": {"release": "1.20.4", "snapshot": "24w10a"},
            "versions": [
                {
                    "id": "1.20.4",
                    "type": "release",
                    "url": "https://example.com/1.20.4.json",
                    "time": "2023-12-07T00:00:00Z",
                    "releaseTime": "2023-12-07T00:00:00Z",
                    "sha1": "abc",
                    "complianceLevel": 1,
                },
                {
                    "id": "1.16.5",
                    "type": "release",
                    "url": "https://example.com/1.16.5.json",
                    "time": "2021-01-01T00:00:00Z",
                    "releaseTime": "2021-01-01T00:00:00Z",
                    "sha1": "def",
                    "complianceLevel": 0,
                },
            ],
        }

    def test_fetch_manifest_from_api(self, sample_manifest_data):
        """测试从 API 获取版本清单。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_client = MagicMock()
            mock_client.get_json.return_value = sample_manifest_data

            api = VersionAPI(client=mock_client, cache_dir=Path(tmpdir))
            manifest = api.fetch_manifest(force_refresh=True)

            assert manifest.latest_release == "1.20.4"
            assert manifest.latest_snapshot == "24w10a"
            assert len(manifest.versions) == 2
            mock_client.get_json.assert_called_once()

    def test_fetch_manifest_uses_cache(self, sample_manifest_data):
        """测试使用缓存的版本清单。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache_dir.mkdir(exist_ok=True)

            cache_path = cache_dir / "version_manifest.json"
            cache_path.write_text(json.dumps(sample_manifest_data))

            mock_client = MagicMock()
            api = VersionAPI(client=mock_client, cache_dir=cache_dir)
            manifest = api.fetch_manifest()

            assert manifest.latest_release == "1.20.4"
            mock_client.get_json.assert_not_called()

    def test_fetch_manifest_cache_expired(self, sample_manifest_data):
        """测试缓存过期后刷新。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache_dir.mkdir(exist_ok=True)

            cache_path = cache_dir / "version_manifest.json"
            cache_path.write_text(json.dumps(sample_manifest_data))
            old_time = time.time() - 7200
            os.utime(cache_path, (old_time, old_time))

            mock_client = MagicMock()
            new_data = dict(sample_manifest_data)
            new_data["latest"] = {"release": "1.21", "snapshot": "24w20a"}
            mock_client.get_json.return_value = new_data

            api = VersionAPI(client=mock_client, cache_dir=cache_dir)
            manifest = api.fetch_manifest()

            assert manifest.latest_release == "1.21"
            mock_client.get_json.assert_called_once()

    def test_fetch_manifest_network_error_fallback_cache(self, sample_manifest_data):
        """测试网络错误时使用过期缓存。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache_dir.mkdir(exist_ok=True)

            cache_path = cache_dir / "version_manifest.json"
            cache_path.write_text(json.dumps(sample_manifest_data))

            mock_client = MagicMock()
            mock_client.get_json.side_effect = HttpError("Network error")

            api = VersionAPI(client=mock_client, cache_dir=cache_dir)
            manifest = api.fetch_manifest(force_refresh=True)

            assert manifest.latest_release == "1.20.4"

    def test_fetch_version_metadata(self):
        """测试获取版本元数据。"""
        version_data = {
            "id": "1.20.4",
            "type": "release",
            "mainClass": "net.minecraft.client.main.Main",
            "libraries": [],
            "downloads": {"client": {"url": "https://example.com/client.jar", "sha1": "abc", "size": 20000000}},
            "assetIndex": {"id": "5", "url": "https://example.com/5.json", "sha1": "a", "size": 10000},
            "javaVersion": {"component": "java-runtime-gamma", "majorVersion": 17},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_client = MagicMock()
            mock_client.get_json.return_value = version_data

            api = VersionAPI(client=mock_client, cache_dir=Path(tmpdir))
            meta = api.fetch_version_metadata(
                "https://example.com/1.20.4.json", "1.20.4"
            )

            assert meta.id == "1.20.4"
            assert meta.java_version == 17
            mock_client.get_json.assert_called_once()

    def test_parse_manifest(self):
        """测试解析 manifest JSON。"""
        mock_client = MagicMock()
        api = VersionAPI(client=mock_client, cache_dir=Path("/tmp"))
        data = {
            "latest": {"release": "1.20.4", "snapshot": "24w10a"},
            "versions": [
                {"id": "1.20.4", "type": "release", "url": "url1"},
                {"id": "24w10a", "type": "snapshot", "url": "url2"},
            ],
        }
        manifest = api._parse_manifest(data)
        assert len(manifest.versions) == 2
        assert manifest.latest_release == "1.20.4"
