"""文件工具模块单元测试。"""

import json
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

from src.utils.file_utils import (
    calculate_sha1,
    calculate_sha256,
    clean_directory,
    ensure_directory,
    extract_zip,
    file_exists,
    format_file_size,
    get_directory_size,
    get_file_size,
    get_relative_path,
    list_files,
    read_json,
    safe_copy,
    safe_delete,
    safe_move,
    verify_sha1,
    write_json,
)


class TestFileUtils:
    """文件工具测试。"""

    def test_ensure_directory(self):
        """测试确保目录存在。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "a" / "b" / "c"
            result = ensure_directory(new_dir)
            assert result.is_dir()
            assert new_dir.is_dir()

    def test_calculate_sha1(self):
        """测试计算 SHA1。"""
        with tempfile.NamedTemporaryFile(delete=False, mode="wb") as f:
            f.write(b"hello world")
            f.flush()
            sha = calculate_sha1(Path(f.name))
            os.unlink(f.name)
        assert sha == "2aae6c35c94fcfb415dbe95f408b9ce91ee846ed"

    def test_calculate_sha256(self):
        """测试计算 SHA256。"""
        with tempfile.NamedTemporaryFile(delete=False, mode="wb") as f:
            f.write(b"hello world")
            f.flush()
            sha = calculate_sha256(Path(f.name))
            os.unlink(f.name)
        assert len(sha) == 64

    def test_verify_sha1_match(self):
        """测试 SHA1 校验通过。"""
        with tempfile.NamedTemporaryFile(delete=False, mode="wb") as f:
            f.write(b"hello world")
            path = Path(f.name)
        assert verify_sha1(path, "2aae6c35c94fcfb415dbe95f408b9ce91ee846ed") is True
        os.unlink(path)

    def test_verify_sha1_mismatch(self):
        """测试 SHA1 校验不通过。"""
        with tempfile.NamedTemporaryFile(delete=False, mode="wb") as f:
            f.write(b"hello world")
            path = Path(f.name)
        assert verify_sha1(path, "0000000000000000000000000000000000000000") is False
        os.unlink(path)

    def test_verify_sha1_nonexistent(self):
        """测试不存在文件的 SHA1 校验。"""
        assert verify_sha1(Path("/nonexistent"), "anything") is False

    def test_safe_copy(self):
        """测试安全复制。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src.txt"
            src.write_text("test")
            dst = Path(tmpdir) / "sub" / "dst.txt"
            assert safe_copy(src, dst) is True
            assert dst.exists()
            assert dst.read_text() == "test"

    def test_safe_delete_file(self):
        """测试安全删除文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("test")
            assert safe_delete(f) is True
            assert not f.exists()

    def test_safe_delete_directory(self):
        """测试安全删除目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "subdir"
            d.mkdir()
            (d / "file.txt").write_text("test")
            assert safe_delete(d) is True
            assert not d.exists()

    def test_safe_delete_nonexistent(self):
        """测试删除不存在的路径。"""
        assert safe_delete(Path("/nonexistent/path")) is False

    def test_safe_move(self):
        """测试安全移动。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src.txt"
            src.write_text("moved")
            dst = Path(tmpdir) / "dst.txt"
            assert safe_move(src, dst) is True
            assert not src.exists()
            assert dst.read_text() == "moved"

    def test_get_file_size(self):
        """测试获取文件大小。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("hello")
            assert get_file_size(f) == 5

    def test_get_file_size_nonexistent(self):
        """测试获取不存在文件大小。"""
        assert get_file_size(Path("/nonexistent")) == 0

    def test_get_directory_size(self):
        """测试获取目录大小。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "a.txt").write_text("hello")  # 5 bytes
            (d / "b.txt").write_text("world")  # 5 bytes
            sub = d / "sub"
            sub.mkdir()
            (sub / "c.txt").write_text("!")  # 1 byte
            size = get_directory_size(d)
            assert size == 11

    def test_clean_directory(self):
        """测试清空目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            keep = d / "keep.txt"
            keep.write_text("keep")
            (d / "delete.txt").write_text("delete")
            deleted = clean_directory(d, keep_files={"keep.txt"})
            assert deleted == 1
            assert keep.exists()
            assert not (d / "delete.txt").exists()

    def test_extract_zip(self):
        """测试解压 zip 文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "test.zip"
            extract_to = Path(tmpdir) / "extracted"

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("hello.txt", "hello world")
                zf.writestr("sub/nested.txt", "nested")

            extracted = extract_zip(zip_path, extract_to)
            assert len(extracted) == 2
            assert (extract_to / "hello.txt").exists()
            assert (extract_to / "hello.txt").read_text() == "hello world"
            assert (extract_to / "sub" / "nested.txt").exists()

    def test_extract_zip_with_filter(self):
        """测试带过滤的解压。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "test.zip"
            extract_to = Path(tmpdir) / "extracted"

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("hello.txt", "hello")
                zf.writestr("META-INF/test.txt", "meta")

            extracted = extract_zip(
                zip_path, extract_to,
                filter_func=lambda name: not name.startswith("META-INF/"),
            )
            assert len(extracted) == 1
            assert (extract_to / "hello.txt").exists()
            assert not (extract_to / "META-INF").exists()

    def test_read_json(self):
        """测试读取 JSON。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.json"
            f.write_text(json.dumps({"key": "value", "num": 42}))
            data = read_json(f)
            assert data == {"key": "value", "num": 42}

    def test_read_json_invalid(self):
        """测试读取无效 JSON。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "bad.json"
            f.write_text("not json")
            assert read_json(f) is None

    def test_read_json_nonexistent(self):
        """测试读取不存在的 JSON。"""
        assert read_json(Path("/nonexistent.json")) is None

    def test_write_json(self):
        """测试写入 JSON。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.json"
            assert write_json(f, {"key": "value"}) is True
            data = json.loads(f.read_text())
            assert data["key"] == "value"

    def test_write_json_creates_directory(self):
        """测试写入 JSON 自动创建目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "a" / "b" / "test.json"
            assert write_json(f, {"x": 1}) is True
            assert f.exists()

    def test_list_files(self):
        """测试列出文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "a.txt").write_text("a")
            (d / "b.txt").write_text("b")
            (d / "c.md").write_text("c")
            sub = d / "sub"
            sub.mkdir()
            (sub / "d.txt").write_text("d")

            all_txt = list_files(d, "*.txt")
            assert len(all_txt) == 2

            all_txt_recursive = list_files(d, "*.txt", recursive=True)
            assert len(all_txt_recursive) == 3

    def test_list_files_nonexistent_dir(self):
        """测试列出不存在目录的文件。"""
        assert list_files(Path("/nonexistent")) == []

    def test_file_exists(self):
        """测试文件存在检查。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("hello")
            assert file_exists(f) is True
            assert file_exists(f, min_size=5) is True
            assert file_exists(f, min_size=10) is False
            assert file_exists(Path(tmpdir) / "nope.txt") is False

    def test_get_relative_path(self):
        """测试获取相对路径。"""
        base = Path("/a/b/c")
        target = Path("/a/b/c/d/e.txt")
        assert get_relative_path(target, base) == "d/e.txt"

    def test_format_file_size(self):
        """测试格式化文件大小。"""
        assert format_file_size(0) == "0 B"
        assert format_file_size(500) == "500 B"
        assert format_file_size(1024) == "1.00 KB"
        assert format_file_size(1048576) == "1.00 MB"
        assert format_file_size(1073741824) == "1.00 GB"
        assert format_file_size(-1) == "0 B"