"""配置管理模块单元测试。"""

import json
import tempfile
from pathlib import Path

import pytest

from src.utils.config import ConfigManager, get_config


class TestConfigManager:
    """配置管理器测试。"""

    def test_singleton(self):
        """测试单例模式。"""
        c1 = ConfigManager()
        c2 = ConfigManager()
        assert c1 is c2

    def test_get_default_value(self):
        """测试获取默认配置值。"""
        config = ConfigManager()
        assert config.get("java_args.min_memory_mb") == 512
        assert config.get("java_args.max_memory_mb") == 2048
        assert config.get("launch.window_width") == 854
        assert config.get("appearance.theme") == "dark"

    def test_get_nonexistent_key(self):
        """测试获取不存在的 key 返回默认值。"""
        config = ConfigManager()
        assert config.get("nonexistent.key", "default") == "default"
        assert config.get("nonexistent") is None

    def test_set_and_get(self):
        """测试设置和获取配置项。"""
        config = ConfigManager()
        config.set("test_key", "test_value")
        assert config.get("test_key") == "test_value"

    def test_set_nested_key(self):
        """测试设置嵌套配置项。"""
        config = ConfigManager()
        config.set("test.section.key", 42)
        assert config.get("test.section.key") == 42

    def test_set_nested_creates_intermediate(self):
        """测试设置嵌套 key 会自动创建中间字典。"""
        config = ConfigManager()
        config.set("a.b.c", "hello")
        assert config.get("a.b.c") == "hello"
        assert isinstance(config.get("a"), dict)

    def test_update_batch(self):
        """测试批量更新。"""
        config = ConfigManager()
        config.update({"a": 1, "b": 2})
        assert config.get("a") == 1
        assert config.get("b") == 2

    def test_save_and_load(self):
        """测试保存和加载配置。"""
        config = ConfigManager()
        config.set("custom_key", "custom_value")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "settings.json"
            config._config_path = config_path
            config.save()

            assert config_path.exists()

            # 加载到新实例
            config2 = ConfigManager()
            config2._config_path = config_path
            config2.load()
            assert config2.get("custom_key") == "custom_value"

    def test_load_nonexistent_file(self):
        """测试加载不存在的文件使用默认配置。"""
        config = ConfigManager()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "does_not_exist.json"
            config.load(config_path)
            assert config.get("java_args.min_memory_mb") == 512

    def test_load_invalid_json(self):
        """测试加载无效 JSON 文件使用默认配置。"""
        config = ConfigManager()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "invalid.json"
            config_path.write_text("this is not json")
            config.load(config_path)
            assert config.get("java_args.min_memory_mb") == 512

    def test_reset(self):
        """测试重置为默认配置。"""
        config = ConfigManager()
        config.set("custom_key", "custom_value")
        config.reset()
        assert config.get("custom_key") is None
        assert config.get("java_args.min_memory_mb") == 512

    def test_get_all(self):
        """测试获取全部配置。"""
        config = ConfigManager()
        all_config = config.get_all()
        assert isinstance(all_config, dict)
        assert all_config["java_args"]["min_memory_mb"] == 512

    def test_get_all_is_deep_copy(self):
        """测试 get_all 返回的是深拷贝，修改不影响原配置。"""
        config = ConfigManager()
        all_config = config.get_all()
        all_config["java_args"]["min_memory_mb"] = 999
        assert config.get("java_args.min_memory_mb") == 512

    def test_get_config_convenience(self):
        """测试便捷函数 get_config。"""
        config = get_config()
        assert isinstance(config, ConfigManager)