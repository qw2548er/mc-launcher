"""Modrinth API 客户端模块。

提供与 Modrinth API v2 对接的功能：
- 搜索模组
- 获取模组详情、版本列表
- 下载模组文件
- 依赖解析
- 游戏版本和加载器列表获取
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from src.utils.file_utils import ensure_directory
from src.utils.http_utils import HttpClient, HttpError, get_http_client

logger = logging.getLogger(__name__)

MODRINTH_API_BASE = "https://api.modrinth.com/v2"
MODRINTH_CDN = "https://cdn.modrinth.com"


@dataclass
class ModrinthProject:
    """Modrinth 项目（模组/资源包/整合包）。"""

    project_id: str
    slug: str
    title: str
    description: str
    author: str
    icon_url: str = ""
    categories: list[str] = field(default_factory=list)
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    downloads: int = 0
    follows: int = 0
    project_type: str = "mod"
    date_created: str = ""
    date_modified: str = ""
    license_name: str = ""
    body: str = ""
    source_url: str = ""
    issues_url: str = ""
    wiki_url: str = ""
    discord_url: str = ""
    gallery: list[dict] = field(default_factory=list)

    @property
    def page_url(self) -> str:
        return f"https://modrinth.com/mod/{self.slug}" if self.slug else ""


@dataclass
class ModrinthVersion:
    """Modrinth 模组版本。"""

    version_id: str
    project_id: str
    name: str
    version_number: str
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    version_type: str = "release"
    date_published: str = ""
    downloads: int = 0
    changelog: str = ""
    dependencies: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)

    @property
    def primary_file(self) -> Optional[dict]:
        for f in self.files:
            if f.get("primary", False):
                return f
        return self.files[0] if self.files else None


@dataclass
class ModrinthSearchResult:
    """搜索结果。"""

    total_hits: int = 0
    projects: list[ModrinthProject] = field(default_factory=list)
    offset: int = 0
    limit: int = 0


class ModrinthAPI:
    """Modrinth API 客户端。"""

    def __init__(self, http_client: Optional[HttpClient] = None):
        self._http = http_client or get_http_client()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = 300

    def _get_cached(self, key: str) -> Optional[Any]:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        self._cache[key] = (time.time(), data)

    def search_mods(
        self,
        query: str,
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
        categories: Optional[list[str]] = None,
        offset: int = 0,
        limit: int = 20,
        project_type: str = "mod",
    ) -> ModrinthSearchResult:
        """搜索模组。

        Args:
            query: 搜索关键词
            game_version: MC 版本过滤
            loader: 加载器过滤（forge/fabric/quilt）
            categories: 分类过滤
            offset: 分页偏移
            limit: 每页数量
            project_type: 项目类型（mod/modpack/resourcepack/shader）

        Returns:
            搜索结果
        """
        facets: list[list[str]] = []
        facets.append([f'project_type:{project_type}'])

        if game_version:
            facets.append([f'versions:{game_version}'])
        if loader:
            facets.append([f'categories:{loader.lower()}'])
        if categories:
            for cat in categories:
                facets.append([f'categories:{cat}'])

        params = [
            f"query={quote(query)}",
            f"offset={offset}",
            f"limit={limit}",
        ]
        import json
        facets_str = json.dumps(facets)
        params.append(f"facets={quote(facets_str)}")

        url = f"{MODRINTH_API_BASE}/search?{'&'.join(params)}"

        try:
            data = self._http.get_json(url)
        except HttpError as e:
            logger.error("Modrinth 搜索失败: %s", e)
            return ModrinthSearchResult()

        result = ModrinthSearchResult(
            total_hits=data.get("total_hits", 0),
            offset=data.get("offset", offset),
            limit=data.get("limit", limit),
        )

        for hit in data.get("hits", []):
            proj = self._parse_search_hit(hit)
            result.projects.append(proj)

        self._set_cache(f"search:{query}:{game_version}:{loader}:{offset}", result)
        return result

    def get_project(self, project_id_or_slug: str) -> Optional[ModrinthProject]:
        """获取项目详情。"""
        cache_key = f"project:{project_id_or_slug}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{MODRINTH_API_BASE}/project/{quote(project_id_or_slug)}"
        try:
            data = self._http.get_json(url)
        except HttpError as e:
            logger.error("获取 Modrinth 项目失败: %s", e)
            return None

        proj = self._parse_project(data)
        self._set_cache(cache_key, proj)
        return proj

    def get_project_versions(
        self,
        project_id_or_slug: str,
        game_version: Optional[str] = None,
        loader: Optional[list[str]] = None,
        version_type: Optional[str] = None,
    ) -> list[ModrinthVersion]:
        """获取项目的版本列表。"""
        params = []
        if game_version:
            params.append(f"game_versions=[\"{quote(game_version)}\"]")
        if loader:
            loaders_str = ",".join(f'"{l}"' for l in loader)
            params.append(f"loaders=[{loaders_str}]")

        url = f"{MODRINTH_API_BASE}/project/{quote(project_id_or_slug)}/version"
        if params:
            url += "?" + "&".join(params)

        try:
            data = self._http.get_json(url)
        except HttpError as e:
            logger.error("获取 Modrinth 版本列表失败: %s", e)
            return []

        versions = []
        for v in data:
            if version_type and v.get("version_type") != version_type:
                continue
            versions.append(self._parse_version(v))
        return versions

    def get_version(self, version_id: str) -> Optional[ModrinthVersion]:
        """获取单个版本详情。"""
        cache_key = f"version:{version_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{MODRINTH_API_BASE}/version/{quote(version_id)}"
        try:
            data = self._http.get_json(url)
        except HttpError as e:
            logger.error("获取 Modrinth 版本失败: %s", e)
            return None

        ver = self._parse_version(data)
        self._set_cache(cache_key, ver)
        return ver

    def get_game_versions(self) -> list[dict]:
        """获取支持的游戏版本列表。"""
        cached = self._get_cached("game_versions")
        if cached is not None:
            return cached

        try:
            data = self._http.get_json(f"{MODRINTH_API_BASE}/tag/game_version")
        except HttpError as e:
            logger.error("获取游戏版本列表失败: %s", e)
            return []

        self._set_cache("game_versions", data)
        return data

    def get_loaders(self) -> list[dict]:
        """获取支持的加载器列表。"""
        cached = self._get_cached("loaders")
        if cached is not None:
            return cached

        try:
            data = self._http.get_json(f"{MODRINTH_API_BASE}/tag/loader")
        except HttpError as e:
            logger.error("获取加载器列表失败: %s", e)
            return []

        self._set_cache("loaders", data)
        return data

    def get_categories(self) -> list[dict]:
        """获取分类列表。"""
        cached = self._get_cached("categories")
        if cached is not None:
            return cached

        try:
            data = self._http.get_json(f"{MODRINTH_API_BASE}/tag/category")
        except HttpError as e:
            logger.error("获取分类列表失败: %s", e)
            return []

        self._set_cache("categories", data)
        return data

    def download_mod_file(
        self,
        version: ModrinthVersion,
        mods_dir: Path,
        file_index: int = 0,
        progress_callback: Optional[Any] = None,
    ) -> Optional[Path]:
        """下载模组文件到 mods 目录。

        Args:
            version: 版本信息
            mods_dir: mods 目录
            file_index: 文件索引（0 = 主文件）
            progress_callback: 进度回调

        Returns:
            下载后的文件路径，失败返回 None
        """
        files = version.files
        if not files or file_index >= len(files):
            return None

        file_info = files[file_index]
        filename = file_info.get("filename", "")
        url = file_info.get("url", "")

        if not filename or not url:
            return None

        ensure_directory(mods_dir)
        save_path = mods_dir / filename

        if save_path.exists() and file_info.get("size", 0) > 0:
            existing_size = save_path.stat().st_size
            if existing_size == file_info.get("size", 0):
                hashes = file_info.get("hashes", {})
                sha1 = hashes.get("sha1", "")
                if sha1:
                    from src.utils.file_utils import verify_sha1
                    if verify_sha1(save_path, sha1):
                        return save_path
                else:
                    return save_path

        try:
            self._http.download_file(
                url=url,
                save_path=save_path,
                progress_callback=progress_callback,
                resume=True,
                expected_size=file_info.get("size"),
                expected_sha1=file_info.get("hashes", {}).get("sha1"),
            )
            logger.info("模组下载完成: %s", filename)
            return save_path
        except HttpError as e:
            logger.error("下载模组失败: %s", e)
            return None

    def get_dependencies(
        self,
        version: ModrinthVersion,
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
    ) -> list[ModrinthVersion]:
        """解析版本依赖，返回所需的依赖版本列表。

        Args:
            version: 版本信息
            game_version: 目标 MC 版本
            loader: 目标加载器

        Returns:
            需要下载的依赖版本列表
        """
        required_versions: list[ModrinthVersion] = []
        processed: set[str] = set()

        def _resolve_deps(v: ModrinthVersion) -> None:
            for dep in v.dependencies:
                dep_type = dep.get("dependency_type", "")
                project_id = dep.get("project_id", "")
                dep_version_id = dep.get("version_id", "")

                if dep_type != "required":
                    continue
                if project_id in processed:
                    continue
                processed.add(project_id)

                dep_version = None
                if dep_version_id:
                    dep_version = self.get_version(dep_version_id)
                elif project_id:
                    versions = self.get_project_versions(project_id, game_version=game_version, loader=[loader] if loader else None)
                    dep_version = versions[0] if versions else None

                if dep_version:
                    required_versions.append(dep_version)
                    _resolve_deps(dep_version)

        _resolve_deps(version)
        return required_versions

    def _parse_search_hit(self, hit: dict) -> ModrinthProject:
        return ModrinthProject(
            project_id=hit.get("project_id", ""),
            slug=hit.get("slug", ""),
            title=hit.get("title", ""),
            description=hit.get("description", ""),
            author=hit.get("author", hit.get("organization", "")),
            icon_url=hit.get("icon_url", ""),
            categories=hit.get("categories", []),
            game_versions=hit.get("versions", []),
            loaders=[c for c in hit.get("categories", []) if c in ("forge", "fabric", "quilt", "neoforge")],
            downloads=hit.get("downloads", 0),
            follows=hit.get("follows", 0),
            project_type=hit.get("project_type", "mod"),
            date_created=hit.get("date_created", ""),
            date_modified=hit.get("date_modified", ""),
            license_name=hit.get("license", ""),
        )

    def _parse_project(self, data: dict) -> ModrinthProject:
        loaders = []
        for cat in data.get("categories", []):
            if cat.lower() in ("forge", "fabric", "quilt", "neoforge"):
                loaders.append(cat.lower())

        return ModrinthProject(
            project_id=data.get("id", ""),
            slug=data.get("slug", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            author="",
            icon_url=data.get("icon_url", ""),
            categories=data.get("categories", []),
            game_versions=data.get("game_versions", []),
            loaders=loaders,
            downloads=data.get("downloads", 0),
            follows=data.get("followers", 0),
            project_type=data.get("project_type", "mod"),
            date_created=data.get("published", ""),
            date_modified=data.get("updated", ""),
            license_name=data.get("license", {}).get("name", "") if isinstance(data.get("license"), dict) else data.get("license", ""),
            body=data.get("body", ""),
            source_url=data.get("source_url", ""),
            issues_url=data.get("issues_url", ""),
            wiki_url=data.get("wiki_url", ""),
            discord_url=data.get("discord_url", ""),
            gallery=data.get("gallery", []),
        )

    def _parse_version(self, data: dict) -> ModrinthVersion:
        return ModrinthVersion(
            version_id=data.get("id", ""),
            project_id=data.get("project_id", ""),
            name=data.get("name", ""),
            version_number=data.get("version_number", ""),
            game_versions=data.get("game_versions", []),
            loaders=data.get("loaders", []),
            version_type=data.get("version_type", "release"),
            date_published=data.get("date_published", ""),
            downloads=data.get("downloads", 0),
            changelog=data.get("changelog", ""),
            dependencies=data.get("dependencies", []),
            files=data.get("files", []),
        )
