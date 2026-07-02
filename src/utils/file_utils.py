"""文件操作工具模块。

提供文件哈希校验、目录管理、安全删除等常用文件操作。
"""

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


def ensure_directory(path: Path) -> Path:
    """确保目录存在，不存在则创建。

    Args:
        path: 目录路径

    Returns:
        目录路径
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def calculate_sha1(file_path: Path, chunk_size: int = 8192) -> str:
    """计算文件的 SHA1 哈希值。

    Args:
        file_path: 文件路径
        chunk_size: 读取块大小

    Returns:
        SHA1 十六进制字符串
    """
    sha1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha1.update(chunk)
    return sha1.hexdigest()


def calculate_sha256(file_path: Path, chunk_size: int = 8192) -> str:
    """计算文件的 SHA256 哈希值。"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_sha1(file_path: Path, expected_sha1: str) -> bool:
    """校验文件 SHA1 是否匹配。

    Args:
        file_path: 文件路径
        expected_sha1: 期望的 SHA1 值

    Returns:
        True 表示校验通过
    """
    if not file_path.exists():
        return False
    actual = calculate_sha1(file_path)
    return actual.lower() == expected_sha1.lower()


def safe_copy(src: Path, dst: Path) -> bool:
    """安全复制文件，目标目录不存在时自动创建。

    Args:
        src: 源文件路径
        dst: 目标文件路径

    Returns:
        True 表示复制成功
    """
    try:
        ensure_directory(dst.parent)
        shutil.copy2(src, dst)
        logger.debug("复制: %s -> %s", src, dst)
        return True
    except OSError as e:
        logger.error("复制失败: %s -> %s: %s", src, dst, e)
        return False


def safe_delete(path: Path) -> bool:
    """安全删除文件或目录。

    Args:
        path: 文件或目录路径

    Returns:
        True 表示删除成功
    """
    try:
        if not path.exists() and not path.is_symlink():
            return False
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        logger.debug("删除: %s", path)
        return True
    except OSError as e:
        logger.error("删除失败: %s: %s", path, e)
        return False


def safe_move(src: Path, dst: Path) -> bool:
    """安全移动文件。

    Args:
        src: 源路径
        dst: 目标路径

    Returns:
        True 表示移动成功
    """
    try:
        ensure_directory(dst.parent)
        shutil.move(str(src), str(dst))
        return True
    except OSError as e:
        logger.error("移动失败: %s -> %s: %s", src, dst, e)
        return False


def get_file_size(path: Path) -> int:
    """获取文件大小（字节），文件不存在返回 0。"""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def get_directory_size(path: Path) -> int:
    """递归计算目录总大小（字节）。"""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except OSError:
        pass
    return total


def clean_directory(path: Path, keep_files: Optional[set[str]] = None) -> int:
    """清空目录内容，保留指定文件。

    Args:
        path: 目录路径
        keep_files: 需要保留的文件名集合

    Returns:
        删除的文件/目录数量
    """
    keep_files = keep_files or set()
    deleted = 0
    if not path.is_dir():
        return deleted

    for item in path.iterdir():
        if item.name in keep_files:
            continue
        if safe_delete(item):
            deleted += 1
    return deleted


def extract_zip(
    zip_path: Path,
    extract_to: Path,
    filter_func: Optional[Callable[[str], bool]] = None,
    overwrite: bool = False,
) -> list[Path]:
    """解压 zip 文件。

    Args:
        zip_path: zip 文件路径
        extract_to: 目标目录
        filter_func: 文件名过滤函数，返回 True 的文件才会被提取
        overwrite: 是否覆盖已存在的文件

    Returns:
        提取的文件路径列表
    """
    ensure_directory(extract_to)
    extracted: list[Path] = []

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if filter_func and not filter_func(member):
                    continue

                target = extract_to / member
                if target.exists() and not overwrite:
                    continue

                # 安全检查：防止 zip slip 攻击
                target_resolved = target.resolve()
                extract_to_resolved = extract_to.resolve()
                if not str(target_resolved).startswith(str(extract_to_resolved)):
                    logger.warning("跳过不安全的 zip 成员: %s", member)
                    continue

                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                ensure_directory(target.parent)
                try:
                    with zf.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted.append(target)
                except Exception as e:
                    logger.warning("提取文件失败: %s: %s", member, e)

    except (zipfile.BadZipFile, OSError) as e:
        logger.error("解压失败: %s: %s", zip_path, e)

    return extracted


def read_json(file_path: Path) -> Optional[dict | list]:
    """读取 JSON 文件。

    Args:
        file_path: JSON 文件路径

    Returns:
        解析后的对象，失败返回 None
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.error("读取 JSON 失败: %s: %s", file_path, e)
        return None


def write_json(
    file_path: Path,
    data: dict | list,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> bool:
    """写入 JSON 文件。

    Args:
        file_path: 文件路径
        data: 要写入的数据
        indent: 缩进
        ensure_ascii: 是否确保 ASCII 编码

    Returns:
        True 表示写入成功
    """
    try:
        ensure_directory(file_path.parent)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        return True
    except (OSError, TypeError) as e:
        logger.error("写入 JSON 失败: %s: %s", file_path, e)
        return False


def list_files(
    directory: Path,
    pattern: str = "*",
    recursive: bool = False,
) -> list[Path]:
    """列出目录中的文件。

    Args:
        directory: 目录路径
        pattern: glob 匹配模式
        recursive: 是否递归

    Returns:
        文件路径列表
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []

    if recursive:
        return [p for p in directory.rglob(pattern) if p.is_file()]
    return [p for p in directory.glob(pattern) if p.is_file()]


def file_exists(path: Path, min_size: int = 0) -> bool:
    """检查文件是否存在且有效。

    Args:
        path: 文件路径
        min_size: 最小文件大小（字节），0 表示不检查

    Returns:
        True 表示文件存在且有效
    """
    return path.is_file() and path.stat().st_size >= min_size


def get_relative_path(path: Path, base: Path) -> str:
    """获取相对路径字符串。"""
    try:
        return str(Path(path).relative_to(base))
    except ValueError:
        return str(path)


def format_file_size(size_bytes: float) -> str:
    """格式化文件大小为可读字符串。

    Args:
        size_bytes: 文件大小（字节）

    Returns:
        格式化后的大小字符串，如 "1.50 MB"
    """
    if size_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(size_bytes)
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"