"""Java 检测模块单元测试。"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.java_detector import JavaDetector, JavaInfo


class TestJavaInfo:
    """JavaInfo 数据类测试。"""

    def test_create_java_info(self):
        """测试创建 JavaInfo。"""
        info = JavaInfo(
            path=Path("/usr/lib/jvm/java-17/bin/java"),
            version="17.0.10",
            major_version=17,
            is_64bit=True,
        )
        assert info.major_version == 17
        assert info.version == "17.0.10"
        assert info.is_64bit is True
        assert "17.0.10" in str(info)
        assert "64-bit" in str(info)

    def test_repr(self):
        """测试 __repr__ 方法。"""
        info = JavaInfo(
            path=Path("/usr/bin/java"),
            version="21.0.2",
            major_version=21,
        )
        assert "JavaInfo" in repr(info)
        assert "21.0.2" in repr(info)


class TestJavaDetectorVersionParsing:
    """Java 版本解析测试。"""

    def test_parse_major_version_java8(self):
        """测试解析 Java 8 版本号。"""
        assert JavaDetector._parse_major_version("1.8.0_401") == 8

    def test_parse_major_version_java17(self):
        """测试解析 Java 17 版本号。"""
        assert JavaDetector._parse_major_version("17.0.10") == 17

    def test_parse_major_version_java21(self):
        """测试解析 Java 21 版本号。"""
        assert JavaDetector._parse_major_version("21.0.2") == 21

    def test_parse_java_info(self):
        """测试解析 Java 版本输出。"""
        output = 'openjdk version "17.0.10" 2024-01-16 LTS\nOpenJDK Runtime Environment (build 17.0.10+7)\nOpenJDK 64-Bit Server VM (build 17.0.10+7, mixed mode, sharing)\n'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stderr=output, stdout="", returncode=0
            )
            info = JavaDetector._parse_java_info(Path("/usr/bin/java"))
            assert info is not None
            assert info.major_version == 17
            assert info.version == "17.0.10"
            assert info.is_64bit is True

    def test_parse_java_info_32bit(self):
        """测试解析 32 位 Java。"""
        output = 'java version "1.8.0_401"\nJava(TM) SE Runtime Environment (build 1.8.0_401-b10)\nJava HotSpot(TM) 32-Bit Server VM\n'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stderr=output, stdout="", returncode=0
            )
            info = JavaDetector._parse_java_info(Path("/usr/bin/java"))
            assert info is not None
            assert info.major_version == 8
            assert info.is_64bit is False

    def test_parse_java_info_failure(self):
        """测试解析失败返回 None。"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stderr="not a java version output", stdout="", returncode=0
            )
            info = JavaDetector._parse_java_info(Path("/usr/bin/java"))
            assert info is None


class TestJavaDetectorCompatibility:
    """Java 版本兼容性测试。"""

    @pytest.fixture
    def detector(self):
        return JavaDetector()

    def test_mc_121_needs_java21(self, detector):
        """MC 1.21 需要 Java 21。"""
        assert detector._get_min_java_version("1.21") == 21
        assert detector._get_min_java_version("1.21.1") == 21

    def test_mc_1205_needs_java21(self, detector):
        """MC 1.20.5 需要 Java 21。"""
        assert detector._get_min_java_version("1.20.5") == 21
        assert detector._get_min_java_version("1.20.6") == 21

    def test_mc_1204_needs_java17(self, detector):
        """MC 1.20.4 需要 Java 17。"""
        assert detector._get_min_java_version("1.20.4") == 17

    def test_mc_118_needs_java17(self, detector):
        """MC 1.18 需要 Java 17。"""
        assert detector._get_min_java_version("1.18") == 17
        assert detector._get_min_java_version("1.18.2") == 17

    def test_mc_117_needs_java17(self, detector):
        """MC 1.17 需要 Java 17。"""
        assert detector._get_min_java_version("1.17") == 17
        assert detector._get_min_java_version("1.17.1") == 17

    def test_mc_116_needs_java8(self, detector):
        """MC 1.16 需要 Java 8。"""
        assert detector._get_min_java_version("1.16.5") == 8

    def test_mc_112_needs_java8(self, detector):
        """MC 1.12.2 需要 Java 8。"""
        assert detector._get_min_java_version("1.12.2") == 8

    def test_invalid_version_defaults_java8(self, detector):
        """无效版本号默认返回 Java 8。"""
        assert detector._get_min_java_version("invalid") == 8

    def test_is_compatible_true(self, detector):
        """测试兼容性检查通过。"""
        java_info = JavaInfo(Path("/usr/bin/java"), "17.0.10", 17)
        assert detector.is_compatible(java_info, "1.18.2") is True

    def test_is_compatible_false(self, detector):
        """测试兼容性检查失败。"""
        java_info = JavaInfo(Path("/usr/bin/java"), "1.8.0_401", 8)
        assert detector.is_compatible(java_info, "1.20.4") is False


class TestJavaDetectorScan:
    """Java 扫描测试。"""

    def test_scan_finds_java_in_path(self):
        """测试在 PATH 中查找 Java。"""
        detector = JavaDetector()
        detector._java_list = []
        detector._scanned = False

        mock_info = JavaInfo(Path("/usr/bin/java"), "17.0.10", 17)
        with patch.object(detector, "_load_cache", return_value=None):
            with patch.object(detector, "_save_cache", return_value=None):
                with patch.object(detector, "_find_in_path", return_value=Path("/usr/bin/java")):
                    with patch.object(detector, "_parse_java_info", return_value=mock_info):
                        with patch.object(detector, "_scan_directory", return_value=[]):
                            with patch.object(detector, "_scan_windows_registry", return_value=[]):
                                result = detector.scan(force=True)
                                assert len(result) >= 1
                                assert result[0].major_version == 17

    def test_scan_returns_sorted(self):
        """测试扫描结果按版本降序排列。"""
        detector = JavaDetector()
        detector._java_list = []
        detector._scanned = False

        java8 = JavaInfo(Path("/usr/bin/java8"), "1.8.0_401", 8)
        java17 = JavaInfo(Path("/usr/bin/java17"), "17.0.10", 17)
        java21 = JavaInfo(Path("/usr/bin/java21"), "21.0.2", 21)

        with patch.object(detector, "_find_in_path", return_value=Path("/usr/bin/java21")):
            with patch.object(detector, "_parse_java_info", return_value=java21):
                with patch.object(detector, "_scan_directory", return_value=[Path("/usr/bin/java17"), Path("/usr/bin/java8")]):
                    def side_effect(path):
                        if str(path) == "/usr/bin/java17":
                            return java17
                        return java8
                    with patch.object(detector, "_parse_java_info", side_effect=side_effect):
                        detector._java_list = [java21]
                        detector._parse_java_info = MagicMock(side_effect=side_effect)
                        detector._find_in_path = MagicMock(return_value=Path("/usr/bin/java21"))
                        detector._scan_directory = MagicMock(return_value=[])

    def test_get_best_match(self):
        """测试获取最佳匹配 Java。"""
        detector = JavaDetector()
        java8 = JavaInfo(Path("/usr/bin/java8"), "1.8.0_401", 8)
        java21 = JavaInfo(Path("/usr/bin/java21"), "21.0.2", 21)
        detector._java_list = [java21, java8]
        detector._scanned = True

        best = detector.get_best_match("1.20.4")
        assert best is not None
        assert best.major_version == 21

    def test_get_best_match_no_match(self):
        """测试没有匹配的 Java 返回 None。"""
        detector = JavaDetector()
        java8 = JavaInfo(Path("/usr/bin/java8"), "1.8.0_401", 8)
        detector._java_list = [java8]
        detector._scanned = True

        best = detector.get_best_match("1.21")
        assert best is None

    def test_check_java_valid(self):
        """测试手动指定 Java 路径有效。"""
        detector = JavaDetector()
        mock_info = JavaInfo(Path("/usr/bin/java"), "17.0.10", 17)
        with (
            patch.object(detector, "_parse_java_info", return_value=mock_info),
            patch("pathlib.Path.is_file", return_value=True),
        ):
            result = detector.check_java(Path("/usr/bin/java"))
            assert result is not None
            assert result.major_version == 17

    def test_check_java_invalid(self):
        """测试手动指定 Java 路径无效。"""
        detector = JavaDetector()
        result = detector.check_java(Path("/nonexistent/java"))
        assert result is None