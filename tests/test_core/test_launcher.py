"""启动器核心模块单元测试。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.account import AccountInfo
from src.core.launcher import (
    GameLauncher,
    LaunchError,
    _check_rules,
    _get_native_os_name,
)
from src.core.java_detector import JavaInfo


class TestGameLauncher:
    """游戏启动器测试。"""

    @pytest.fixture
    def launcher(self):
        return GameLauncher()

    @pytest.fixture
    def account(self):
        return AccountInfo(
            uuid="test-uuid",
            type="offline",
            username="TestPlayer",
        )

    def test_get_running_process_none(self, launcher):
        """测试初始状态无运行进程。"""
        assert launcher.get_running_process() is None
        assert launcher.is_running() is False

    def test_launch_missing_version_dir(self, launcher, account):
        """测试版本目录不存在时抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher._config.set("game_directory", tmpdir)
            with pytest.raises(LaunchError, match="版本目录不存在"):
                launcher.launch("nonexistent-version", account)

    def test_launch_missing_version_json(self, launcher, account):
        """测试 version.json 不存在时抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir)
            version_dir = game_dir / "versions" / "1.20.4"
            version_dir.mkdir(parents=True)

            launcher._config.set("game_directory", str(game_dir))
            with pytest.raises(LaunchError, match="版本配置文件"):
                launcher.launch("1.20.4", account)

    def test_launch_missing_jar(self, launcher, account):
        """测试版本 jar 文件不存在时抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir)
            version_dir = game_dir / "versions" / "1.20.4"
            version_dir.mkdir(parents=True)

            # 创建空的 version.json
            version_json = {"id": "1.20.4", "type": "release"}
            with open(version_dir / "1.20.4.json", "w") as f:
                json.dump(version_json, f)

            launcher._config.set("game_directory", str(game_dir))
            with pytest.raises(LaunchError, match="版本 jar 文件不存在"):
                launcher.launch("1.20.4", account)

    def test_launch_no_java(self, launcher, account):
        """测试未找到 Java 时抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir)
            version_dir = game_dir / "versions" / "1.20.4"
            version_dir.mkdir(parents=True)

            # 创建 version.json 和 jar 文件
            version_json = {"id": "1.20.4", "type": "release"}
            with open(version_dir / "1.20.4.json", "w") as f:
                json.dump(version_json, f)
            (version_dir / "1.20.4.jar").touch()

            launcher._config.set("game_directory", str(game_dir))
            launcher._config.set("java_path", "")

            with patch.object(
                launcher._java_detector,
                "get_best_match",
                return_value=None,
            ):
                with pytest.raises(LaunchError, match="未找到可用的 Java"):
                    launcher.launch("1.20.4", account)

    def test_launch_incompatible_java(self, launcher, account):
        """测试 Java 版本不兼容时抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir)
            version_dir = game_dir / "versions" / "1.21"
            version_dir.mkdir(parents=True)

            version_json = {"id": "1.21", "type": "release"}
            with open(version_dir / "1.21.json", "w") as f:
                json.dump(version_json, f)
            (version_dir / "1.21.jar").touch()

            launcher._config.set("game_directory", str(game_dir))
            launcher._config.set("java_path", "")

            java8 = JavaInfo(Path("/usr/bin/java"), "1.8.0_401", 8)
            with patch.object(
                launcher._java_detector,
                "get_best_match",
                return_value=java8,
            ):
                with pytest.raises(LaunchError, match="不兼容"):
                    launcher.launch("1.21", account)

    def test_launch_successful(self, launcher, account):
        """测试成功启动游戏。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir)
            version_dir = game_dir / "versions" / "1.20.4"
            version_dir.mkdir(parents=True)

            version_json = {
                "id": "1.20.4",
                "type": "release",
                "mainClass": "net.minecraft.client.main.Main",
                "libraries": [],
                "arguments": {
                    "game": [],
                    "jvm": [],
                },
            }
            with open(version_dir / "1.20.4.json", "w") as f:
                json.dump(version_json, f)
            (version_dir / "1.20.4.jar").touch()

            launcher._config.set("game_directory", str(game_dir))
            launcher._config.set("java_path", "")

            java17 = JavaInfo(Path("/usr/bin/java"), "17.0.10", 17)
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None

            with patch.object(
                launcher._java_detector,
                "get_best_match",
                return_value=java17,
            ):
                with patch.object(
                    launcher._java_detector,
                    "is_compatible",
                    return_value=True,
                ):
                    with patch("subprocess.Popen", return_value=mock_process):
                        process = launcher.launch("1.20.4", account)
                        assert process is not None
                        assert launcher.is_running() is True

    def test_wait_for_exit_no_process(self, launcher):
        """测试无进程时 wait_for_exit 抛异常。"""
        with pytest.raises(LaunchError, match="没有正在运行的游戏进程"):
            launcher.wait_for_exit()

    def test_load_version_json(self, launcher):
        """测试加载 version.json。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            version_dir = Path(tmpdir) / "1.20.4"
            version_dir.mkdir()
            version_data = {"id": "1.20.4", "type": "release"}
            with open(version_dir / "1.20.4.json", "w") as f:
                json.dump(version_data, f)

            result = GameLauncher._load_version_json(version_dir)
            assert result is not None
            assert result["id"] == "1.20.4"

    def test_load_version_json_invalid(self, launcher):
        """测试加载无效 JSON 应抛出 LaunchError。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            version_dir = Path(tmpdir)
            with open(version_dir / "version.json", "w") as f:
                f.write("invalid json")

            with pytest.raises(LaunchError, match="版本配置文件"):
                GameLauncher._load_version_json(version_dir)

    def test_validate_version_json_structure_valid(self, launcher):
        """测试校验有效的版本 JSON。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "1.20.4.json"
            data = {"id": "1.20.4", "mainClass": "net.minecraft.client.main.Main", "libraries": []}
            json_path.write_text(json.dumps(data))

            valid, msg = GameLauncher._validate_version_json_structure(json_path)
            assert valid is True
            assert msg == ""

    def test_validate_version_json_structure_empty(self, launcher):
        """测试校验空文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "empty.json"
            json_path.write_text("")

            valid, msg = GameLauncher._validate_version_json_structure(json_path)
            assert valid is False
            assert "为空" in msg

    def test_validate_version_json_structure_html(self, launcher):
        """测试校验 HTML 内容（下载失败场景）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "1.7.10.json"
            json_path.write_text("<!DOCTYPE html><html><body>404 Not Found</body></html>")

            valid, msg = GameLauncher._validate_version_json_structure(json_path)
            assert valid is False
            assert "HTML" in msg

    def test_validate_version_json_structure_not_json(self, launcher):
        """测试校验非 JSON 对象内容。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            json_path.write_text("hello world this is not json")

            valid, msg = GameLauncher._validate_version_json_structure(json_path)
            assert valid is False
            assert "格式错误" in msg

    def test_validate_version_json_structure_minimal_valid(self, launcher):
        """测试校验仅包含 id 字段的最小有效 JSON。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            json_path.write_text('{"id": "1.20.4"}')

            valid, msg = GameLauncher._validate_version_json_structure(json_path)
            assert valid is True
            assert msg == ""

    def test_validate_version_json_structure_missing_id(self, launcher):
        """测试校验缺少 id 字段的 JSON。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            json_path.write_text('{"mainClass": "net.minecraft.client.main.Main"}')

            valid, msg = GameLauncher._validate_version_json_structure(json_path)
            assert valid is False
            assert "缺少必要字段" in msg

    def test_validate_version_json_string_value(self, launcher):
        """测试 JSON 字符串值（Gson 错误场景）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "1.7.10.json"
            json_path.write_text('"some invalid string value"')

            valid, msg = GameLauncher._validate_version_json_structure(json_path)
            assert valid is False
            assert "Expected BEGIN_OBJECT" in msg or "字符串" in msg

    def test_validate_version_json_method(self, launcher):
        """测试 validate_version_json 公共方法返回数据。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "valid.json"
            test_data = {"id": "1.20.4", "mainClass": "net.minecraft.client.main.Main"}
            json_path.write_text(json.dumps(test_data))

            is_valid, data, error = GameLauncher.validate_version_json(json_path)
            assert is_valid is True
            assert data is not None
            assert data["id"] == "1.20.4"
            assert error == ""

    def test_validate_version_json_method_invalid(self, launcher):
        """测试 validate_version_json 方法检测无效文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "invalid.json"
            json_path.write_text('"corrupted string"')

            is_valid, data, error = GameLauncher.validate_version_json(json_path)
            assert is_valid is False
            assert data is None
            assert error != ""

    def test_repair_version_json(self, launcher):
        """测试修复损坏的版本 JSON。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir) / ".minecraft"
            version_dir = game_dir / "versions" / "1.7.10"
            version_dir.mkdir(parents=True)
            json_path = version_dir / "1.7.10.json"
            json_path.write_text("corrupted data")

            assert json_path.exists()
            result = GameLauncher.repair_version_json("1.7.10", game_dir)
            assert result is True
            assert not json_path.exists()
            assert json_path.with_suffix(".json.corrupted").exists()

    def test_repair_version_json_nonexistent(self, launcher):
        """测试修复不存在的版本 JSON。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir) / ".minecraft"
            game_dir.mkdir()
            result = GameLauncher.repair_version_json("nonexistent", game_dir)
            assert result is False

    def test_build_jvm_args(self, launcher):
        """测试构建 JVM 参数。"""
        java_info = JavaInfo(Path("/usr/bin/java"), "17.0.10", 17)
        version_dir = Path("/tmp/test")
        game_dir = Path("/tmp/game")
        natives_dir = Path("/tmp/natives")
        classpath = "/tmp/game.jar"
        version_json = {"id": "1.20.4", "arguments": {"jvm": [], "game": []}}

        launcher._config.set("java_args.min_memory_mb", 512)
        launcher._config.set("java_args.max_memory_mb", 2048)

        args = GameLauncher._build_jvm_args(
            java_info=java_info,
            version_dir=version_dir,
            game_dir=game_dir,
            natives_dir=natives_dir,
            classpath=classpath,
            version_json=version_json,
        )

        assert "-Xms512M" in args
        assert "-Xmx2048M" in args
        assert "-cp" in args
        assert classpath in args

    def test_build_minecraft_args(self, launcher):
        """测试构建 Minecraft 参数。"""
        account = AccountInfo(
            uuid="test-uuid",
            type="offline",
            username="TestPlayer",
        )
        version_json = {"id": "1.20.4", "type": "release", "arguments": {"game": []}}
        game_dir = Path("/tmp/game")

        launcher._config.set("launch.window_width", 854)
        launcher._config.set("launch.window_height", 480)

        args = GameLauncher._build_minecraft_args(
            account=account,
            version_json=version_json,
            game_dir=game_dir,
        )

        assert "--username" in args
        assert "TestPlayer" in args
        assert "--version" in args
        assert "1.20.4" in args

    def test_build_classpath(self, launcher):
        """测试构建 classpath。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir)
            version_dir = game_dir / "versions" / "1.20.4"
            version_dir.mkdir(parents=True)
            (version_dir / "1.20.4.jar").touch()

            (game_dir / "libraries").mkdir(parents=True)

            version_json = {
                "id": "1.20.4",
                "libraries": [
                    {
                        "name": "com.example:test-lib:1.0.0",
                        "downloads": {
                            "artifact": {
                                "path": "com/example/test-lib/1.0.0/test-lib-1.0.0.jar"
                            }
                        },
                    },
                ],
            }

            classpath = GameLauncher._build_classpath(game_dir, version_json)
            assert "1.20.4.jar" in classpath


class TestUtilityFunctions:
    """工具函数测试。"""

    def test_get_native_os_name(self):
        """测试获取操作系统名称。"""
        import sys
        name = _get_native_os_name()
        assert name in ("windows", "osx", "linux")

    def test_check_rules_empty(self):
        """测试空规则返回 True。"""
        assert _check_rules([]) is True

    def test_check_rules_allow(self):
        """测试 allow 规则。"""
        current_os = _get_native_os_name()
        rules = [
            {"action": "allow", "os": {"name": current_os}},
        ]
        assert _check_rules(rules) is True

    def test_check_rules_disallow(self):
        """测试 disallow 规则。"""
        current_os = _get_native_os_name()
        rules = [
            {"action": "disallow", "os": {"name": current_os}},
        ]
        assert _check_rules(rules) is False

    def test_check_rules_allow_other_os(self):
        """测试其他 OS 的 allow 规则。"""
        current_os = _get_native_os_name()
        other_os = "windows" if current_os != "windows" else "osx"
        rules = [
            {"action": "allow", "os": {"name": other_os}},
        ]
        assert _check_rules(rules) is False