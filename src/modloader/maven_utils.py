"""Maven 库解析工具模块。

提供 Maven 坐标解析、库文件路径构建、库下载计划生成等通用功能，
供 Forge、Fabric、Quilt 等安装器共享使用。
"""

from __future__ import annotations

import logging
import platform
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from src.utils.file_utils import (
    calculate_sha1,
    ensure_directory,
    file_exists,
    verify_sha1,
)
from src.utils.http_utils import HttpClient, HttpError, get_http_client
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAVEN_REPOS = [
    "https://libraries.minecraft.net/",
    "https://maven.minecraftforge.net/",
    "https://maven.fabricmc.net/",
    "https://maven.quiltmc.org/repository/release/",
    "https://repo1.maven.org/maven2/",
]


@dataclass
class LibraryArtifact:
    """解析后的库构件信息。"""

    group_id: str
    artifact_id: str
    version: str
    classifier: str = ""
    extension: str = "jar"
    url: str = ""
    path: str = ""
    sha1: str = ""
    size: int = 0

    @property
    def maven_coordinate(self) -> str:
        base = f"{self.group_id}:{self.artifact_id}:{self.version}"
        if self.classifier:
            return f"{base}:{self.classifier}"
        return base

    @property
    def filename(self) -> str:
        if self.classifier:
            return f"{self.artifact_id}-{self.version}-{self.classifier}.{self.extension}"
        return f"{self.artifact_id}-{self.version}.{self.extension}"

    @property
    def directory_path(self) -> str:
        group_path = self.group_id.replace(".", "/")
        return f"{group_path}/{self.artifact_id}/{self.version}"

    @property
    def full_path(self) -> str:
        return f"{self.directory_path}/{self.filename}"


@dataclass
class LibraryDownloadPlan:
    """库下载计划项。"""

    artifact: LibraryArtifact
    url: str
    save_path: Path
    sha1: str = ""
    size: int = 0
    skip: bool = False
    skip_reason: str = ""


def parse_maven_coordinate(coordinate: str) -> Optional[LibraryArtifact]:
    """解析 Maven 坐标字符串。

    支持格式：
    - group:artifact:version
    - group:artifact:version:classifier
    - group:artifact:version:classifier@extension

    Args:
        coordinate: Maven 坐标字符串

    Returns:
        LibraryArtifact 或 None
    """
    if not coordinate or not isinstance(coordinate, str):
        return None

    ext = "jar"
    if "@" in coordinate:
        coordinate, ext = coordinate.split("@", 1)

    parts = coordinate.split(":")
    if len(parts) < 3 or len(parts) > 4:
        logger.debug("无效的 Maven 坐标: %s", coordinate)
        return None

    group_id = parts[0]
    artifact_id = parts[1]
    version = parts[2]
    classifier = parts[3] if len(parts) == 4 else ""

    artifact = LibraryArtifact(
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        classifier=classifier,
        extension=ext,
        path=f"{group_id.replace('.', '/')}/{artifact_id}/{version}/"
             + (f"{artifact_id}-{version}-{classifier}.{ext}" if classifier
                else f"{artifact_id}-{version}.{ext}"),
    )
    return artifact


def get_os_name() -> str:
    """获取当前操作系统名称（Mojang 格式）。"""
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "osx"
    return "linux"


def get_os_arch() -> str:
    """获取系统架构。"""
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        return "64"
    elif machine in ("arm64", "aarch64"):
        return "arm64"
    elif "32" in machine or machine == "i386":
        return "32"
    return "64"


def check_library_rules(rules: list[dict]) -> bool:
    """检查库的 OS 规则是否匹配当前系统。

    Args:
        rules: 规则列表，如 [{"action": "allow", "os": {"name": "windows"}}]

    Returns:
        True 表示应该下载此库
    """
    if not rules:
        return True

    os_name = get_os_name()
    allowed = False

    for rule in rules:
        action = rule.get("action", "allow")
        os_rule = rule.get("os")

        if os_rule is None:
            if action == "allow":
                allowed = True
            elif action == "disallow":
                allowed = False
        else:
            rule_os = os_rule.get("name", "")
            arch_match = True
            if "arch" in os_rule:
                arch_match = get_os_arch() == os_rule["arch"]
            os_match = (rule_os == "" or rule_os == os_name) and arch_match
            if os_match:
                if action == "allow":
                    allowed = True
                elif action == "disallow":
                    allowed = False

    return allowed


def resolve_library_artifact(
    lib_entry: dict,
    libraries_dir: Path,
    extra_repos: Optional[list[str]] = None,
) -> list[LibraryDownloadPlan]:
    """解析单个库条目，生成下载计划。

    处理逻辑（优先级）：
    1. 从 downloads.artifact 获取下载信息
    2. 从 downloads.classifiers 获取 natives
    3. 没有 downloads 时从 name (Maven 坐标) 推导路径和 URL

    Args:
        lib_entry: version.json 中的 library 条目
        libraries_dir: 全局 libraries 目录
        extra_repos: 额外的 Maven 仓库 URL 列表

    Returns:
        下载计划列表（可能包含 natives 的多个条目）
    """
    plans: list[LibraryDownloadPlan] = []
    name = lib_entry.get("name", "")
    rules = lib_entry.get("rules", [])

    if not check_library_rules(rules):
        return plans

    downloads = lib_entry.get("downloads", {})
    repos = list(DEFAULT_MAVEN_REPOS)
    if extra_repos:
        repos = extra_repos + repos
    repo_url = lib_entry.get("url", "")
    if repo_url:
        repos.insert(0, repo_url.rstrip("/") + "/")

    artifact = downloads.get("artifact") if isinstance(downloads, dict) else None
    if artifact and isinstance(artifact, dict):
        url = artifact.get("url", "")
        path_str = artifact.get("path", "")
        sha1 = artifact.get("sha1", "")
        size = artifact.get("size", 0)

        if path_str:
            save_path = libraries_dir / path_str
        else:
            parsed = parse_maven_coordinate(name)
            if parsed is None:
                return plans
            save_path = libraries_dir / parsed.full_path
            path_str = parsed.full_path

        if url:
            plans.append(LibraryDownloadPlan(
                artifact=parse_maven_coordinate(name) or LibraryArtifact(
                    group_id="", artifact_id="", version="", path=path_str
                ),
                url=url,
                save_path=save_path,
                sha1=sha1,
                size=size,
            ))
        else:
            parsed = parse_maven_coordinate(name)
            if parsed:
                for repo in repos:
                    maven_url = repo.rstrip("/") + "/" + parsed.full_path
                    plans.append(LibraryDownloadPlan(
                        artifact=parsed,
                        url=maven_url,
                        save_path=save_path,
                        sha1=sha1,
                        size=size,
                    ))
    else:
        parsed = parse_maven_coordinate(name)
        if parsed is None:
            return plans
        save_path = libraries_dir / parsed.full_path
        for repo in repos:
            maven_url = repo.rstrip("/") + "/" + parsed.full_path
            plans.append(LibraryDownloadPlan(
                artifact=parsed,
                url=maven_url,
                save_path=save_path,
            ))

    classifiers = downloads.get("classifiers", {}) if isinstance(downloads, dict) else {}
    natives_map = lib_entry.get("natives", {})
    os_name = get_os_name()
    arch = get_os_arch()

    if natives_map and os_name in natives_map:
        classifier_template = natives_map[os_name]
        classifier_name = classifier_template.replace("${arch}", arch)

        cls_dl = classifiers.get(classifier_name, {}) if isinstance(classifiers, dict) else {}
        if cls_dl:
            url = cls_dl.get("url", "")
            path_str = cls_dl.get("path", "")
            sha1 = cls_dl.get("sha1", "")
            size = cls_dl.get("size", 0)
            if path_str:
                save_path = libraries_dir / path_str
            else:
                parsed = parse_maven_coordinate(f"{name}:{classifier_name}")
                if parsed:
                    save_path = libraries_dir / parsed.full_path
                    path_str = parsed.full_path
                else:
                    save_path = libraries_dir
            if url:
                plans.append(LibraryDownloadPlan(
                    artifact=parse_maven_coordinate(f"{name}:{classifier_name}") or LibraryArtifact(
                        group_id="", artifact_id="", version="", classifier=classifier_name
                    ),
                    url=url,
                    save_path=save_path,
                    sha1=sha1,
                    size=size,
                ))
        else:
            parsed_cls = parse_maven_coordinate(f"{name}:{classifier_name}")
            if parsed_cls:
                save_path = libraries_dir / parsed_cls.full_path
                for repo in repos:
                    maven_url = repo.rstrip("/") + "/" + parsed_cls.full_path
                    plans.append(LibraryDownloadPlan(
                        artifact=parsed_cls,
                        url=maven_url,
                        save_path=save_path,
                    ))
    elif classifiers:
        for cls_name, cls_dl in classifiers.items():
            if not isinstance(cls_dl, dict):
                continue
            if cls_name.endswith("-natives-linux") and os_name != "linux":
                continue
            if cls_name.endswith("-natives-windows") and os_name != "windows":
                continue
            if cls_name.endswith("-natives-macos") and os_name != "osx":
                continue
            if "natives" in cls_name and not any(
                cls_name.endswith(f"-natives-{os_name}"),
            ):
                continue
            url = cls_dl.get("url", "")
            path_str = cls_dl.get("path", "")
            sha1 = cls_dl.get("sha1", "")
            size = cls_dl.get("size", 0)
            if path_str:
                save_path = libraries_dir / path_str
            else:
                parsed_cls = parse_maven_coordinate(f"{name}:{cls_name}")
                if parsed_cls:
                    save_path = libraries_dir / parsed_cls.full_path
                else:
                    continue
            if url:
                plans.append(LibraryDownloadPlan(
                    artifact=parse_maven_coordinate(f"{name}:{cls_name}") or LibraryArtifact(
                        group_id="", artifact_id="", version="", classifier=cls_name
                    ),
                    url=url,
                    save_path=save_path,
                    sha1=sha1,
                    size=size,
                ))

    return plans


def download_libraries(
    libraries: list[dict],
    libraries_dir: Path,
    http_client: Optional[HttpClient] = None,
    progress_callback: Optional[Any] = None,
    extra_repos: Optional[list[str]] = None,
    cancel_check: Optional[Any] = None,
    start_percent: float = 0.0,
    end_percent: float = 100.0,
) -> tuple[int, int]:
    """下载版本所需的所有库文件。

    Args:
        libraries: version.json 中的 libraries 数组
        libraries_dir: 全局 libraries 目录
        http_client: HTTP 客户端
        progress_callback: 进度回调 callback(current, total, filename)
        extra_repos: 额外 Maven 仓库
        cancel_check: 取消检查函数
        start_percent: 起始进度百分比
        end_percent: 结束进度百分比

    Returns:
        (下载成功数, 失败数)
    """
    client = http_client or get_http_client()
    ensure_directory(libraries_dir)

    all_plans: list[LibraryDownloadPlan] = []
    seen_paths: set[str] = set()

    for lib in libraries:
        plans = resolve_library_artifact(lib, libraries_dir, extra_repos)
        for plan in plans:
            path_key = str(plan.save_path)
            if path_key not in seen_paths:
                seen_paths.add(path_key)
                all_plans.append(plan)

    total = len(all_plans)
    success = 0
    failed = 0

    for idx, plan in enumerate(all_plans):
        if cancel_check and cancel_check():
            break

        if plan.save_path.exists():
            if plan.sha1:
                if verify_sha1(plan.save_path, plan.sha1):
                    success += 1
                    continue
            else:
                if file_exists(plan.save_path, min_size=100):
                    success += 1
                    continue

        try:
            ensure_directory(plan.save_path.parent)
            downloaded = False

            urls_to_try = [plan.url]
            parsed = plan.artifact
            if parsed.group_id and parsed.artifact_id:
                repos = list(DEFAULT_MAVEN_REPOS)
                if extra_repos:
                    repos = extra_repos + repos
                for repo in repos:
                    maven_url = repo.rstrip("/") + "/" + parsed.full_path
                    if maven_url not in urls_to_try:
                        urls_to_try.append(maven_url)

            for url in urls_to_try:
                try:
                    client.download_file(
                        url=url,
                        save_path=plan.save_path,
                        expected_sha1=plan.sha1 if plan.sha1 else None,
                        resume=True,
                        progress_callback=None,
                    )
                    downloaded = True
                    break
                except HttpError:
                    continue

            if downloaded:
                success += 1
            else:
                failed += 1
                logger.warning("下载库失败: %s", plan.artifact.maven_coordinate or plan.save_path.name)

        except Exception as e:
            failed += 1
            logger.warning("下载库异常 (%s): %s", plan.save_path.name, e)

        if progress_callback:
            pct = start_percent + (idx + 1) / max(total, 1) * (end_percent - start_percent)
            try:
                progress_callback(idx + 1, total, pct, plan.save_path.name)
            except Exception:
                pass

    return success, failed


def extract_maven_from_installer(
    installer_path: Path,
    libraries_dir: Path,
) -> int:
    """从 Forge 安装器 jar 中提取 maven/ 目录的本地库到全局 libraries 目录。

    Args:
        installer_path: installer jar 路径
        libraries_dir: 全局 libraries 目录

    Returns:
        提取的文件数量
    """
    import zipfile

    count = 0
    try:
        with zipfile.ZipFile(installer_path, "r") as zf:
            maven_files = [n for n in zf.namelist() if n.startswith("maven/")]
            for member in maven_files:
                if member.endswith("/"):
                    continue
                target = libraries_dir / member[len("maven/"):]
                ensure_directory(target.parent)
                try:
                    with zf.open(member) as src, open(target, "wb") as dst:
                        import shutil
                        shutil.copyfileobj(src, dst)
                    count += 1
                except Exception as e:
                    logger.debug("提取 maven 文件失败 %s: %s", member, e)
    except (zipfile.BadZipFile, OSError) as e:
        logger.warning("从安装器提取 maven 库失败: %s", e)

    logger.info("从安装器提取了 %d 个 maven 库文件", count)
    return count
