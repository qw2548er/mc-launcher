"""OpenGL 渲染器适配模块。

提供多种 OpenGL 渲染器选项，根据 MC 版本自动筛选兼容的渲染器，
生成对应的 JVM 启动参数。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RendererInfo:
    """渲染器信息。"""
    renderer_id: str
    display_name: str
    opengl_version: str
    description: str
    min_mc: Optional[tuple] = None
    max_mc: Optional[tuple] = None
    gpu_restriction: Optional[str] = None
    jvm_args: list[str] = None
    is_default: bool = False

    def __post_init__(self):
        if self.jvm_args is None:
            self.jvm_args = []

    def is_compatible_with_mc(self, mc_version: str) -> tuple[bool, str]:
        """检查是否兼容指定 MC 版本。返回 (是否兼容, 不兼容原因)。"""
        try:
            parts = mc_version.split("-")[0].split("+")[0].split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            ver_tuple = (major, minor, patch)
        except (ValueError, IndexError):
            return True, ""

        if self.min_mc is not None and ver_tuple < self.min_mc:
            return False, f"需要 MC {'.'.join(str(v) for v in self.min_mc)}+"
        if self.max_mc is not None and ver_tuple > self.max_mc:
            return False, f"仅支持 MC ≤ {'.'.join(str(v) for v in self.max_mc)}"
        return True, ""

    def is_compatible_with_gpu(self, gpu_model: str = "") -> tuple[bool, str]:
        """检查是否兼容指定 GPU。返回 (是否兼容, 不兼容原因)。"""
        if self.gpu_restriction is None:
            return True, ""
        if not gpu_model:
            return True, ""
        if self.gpu_restriction == "a6xx":
            a6xx_models = [f"a{i}" for i in range(616, 661)]
            if any(model in gpu_model.lower() for model in a6xx_models):
                return True, ""
            return False, "仅支持 Adreno a616-a660 GPU"
        return True, ""


RENDERERS: list[RendererInfo] = [
    RendererInfo(
        renderer_id="krypton",
        display_name="Krypton Wrapper",
        opengl_version="OpenGL 3.1+",
        description="内置的渲染包装器，兼容性好",
        jvm_args=["-Dorg.lwjgl.opengl.libname=libkrypton.so"],
    ),
    RendererInfo(
        renderer_id="holygl4es",
        display_name="Holy GL4ES",
        opengl_version="OpenGL 2.1",
        description="仅支持 MC ≤ 1.21.4",
        max_mc=(1, 21, 4),
        jvm_args=["-Dorg.lwjgl.opengl.libname=libgl4es.so"],
    ),
    RendererInfo(
        renderer_id="virgl",
        display_name="VirGLRenderer",
        opengl_version="OpenGL 4.3",
        description="VirGL 虚拟渲染器",
        jvm_args=["-Dorg.lwjgl.opengl.libname=libvirglrenderer.so"],
    ),
    RendererInfo(
        renderer_id="vgpu",
        display_name="VGPU",
        opengl_version="OpenGL 2.1+",
        description="仅支持 MC ≤ 1.16.5",
        max_mc=(1, 16, 5),
        jvm_args=["-Dorg.lwjgl.opengl.libname=libvgpu.so"],
    ),
    RendererInfo(
        renderer_id="kopper_zink",
        display_name="Kopper Zink",
        opengl_version="OpenGL 4.6",
        description="默认推荐，基于 Zink 的 Vulkan→OpenGL 转译",
        jvm_args=["-Dorg.lwjgl.opengl.libname=libkopper_zink.so"],
        is_default=True,
    ),
    RendererInfo(
        renderer_id="freedreno",
        display_name="Freedreno",
        opengl_version="OpenGL 4.6",
        description="仅支持 Adreno a616-a660 GPU",
        gpu_restriction="a6xx",
        jvm_args=["-Dorg.lwjgl.opengl.libname=libfreedreno.so"],
    ),
    RendererInfo(
        renderer_id="mobileglues",
        display_name="MobileGlues",
        opengl_version="OpenGL 4.0",
        description="仅支持 MC ≥ 1.17",
        min_mc=(1, 17, 0),
        jvm_args=["-Dorg.lwjgl.opengl.libname=libmobileglues.so"],
    ),
]

GRAPHICS_BACKENDS: list[dict] = [
    {
        "backend_id": "gl4es",
        "display_name": "GL4ES (默认)",
        "description": "OpenGL ES 2.0 转译层",
        "min_version": (0, 0, 0),
    },
    {
        "backend_id": "vulkan",
        "display_name": "Vulkan (实验性)",
        "description": "使用 Vulkan 后端，需要 MC 26.X+",
        "min_version": (1, 26, 0),
    },
    {
        "backend_id": "zink",
        "display_name": "Zink",
        "description": "基于 Vulkan 的 OpenGL 实现",
        "min_version": (0, 0, 0),
    },
]

VULKAN_DRIVERS: list[dict] = [
    {
        "driver_id": "turnip",
        "display_name": "Turnip (Adreno)",
        "description": "Qualcomm Adreno GPU 的开源 Vulkan 驱动",
    },
    {
        "driver_id": "system",
        "display_name": "系统 Vulkan 驱动",
        "description": "使用系统自带的 Vulkan 驱动",
    },
]


def get_all_renderers() -> list[RendererInfo]:
    """获取所有渲染器列表。"""
    return RENDERERS


def get_compatible_renderers(mc_version: str, gpu_model: str = "") -> list[tuple[RendererInfo, bool, str]]:
    """获取兼容指定 MC 版本的渲染器列表。

    Returns:
        list of (RendererInfo, is_compatible, reason)
    """
    result = []
    for renderer in RENDERERS:
        mc_compat, mc_reason = renderer.is_compatible_with_mc(mc_version)
        gpu_compat, gpu_reason = renderer.is_compatible_with_gpu(gpu_model)
        is_compat = mc_compat and gpu_compat
        reason = mc_reason if not mc_compat else gpu_reason
        result.append((renderer, is_compat, reason))
    return result


def get_default_renderer_id() -> str:
    """获取默认渲染器 ID。"""
    for r in RENDERERS:
        if r.is_default:
            return r.renderer_id
    return RENDERERS[0].renderer_id if RENDERERS else ""


def get_renderer_by_id(renderer_id: str) -> Optional[RendererInfo]:
    """根据 ID 获取渲染器信息。"""
    for r in RENDERERS:
        if r.renderer_id == renderer_id:
            return r
    return None


def generate_renderer_jvm_args(
    renderer_id: str,
    big_core: bool = False,
    use_system_vulkan: bool = False,
    graphics_backend: str = "gl4es",
    vulkan_driver: str = "turnip",
) -> list[str]:
    """生成渲染器相关的 JVM 参数。

    Args:
        renderer_id: 渲染器 ID
        big_core: 是否强制在大核运行
        use_system_vulkan: 是否使用系统 Vulkan 驱动
        graphics_backend: 图形后端 ID
        vulkan_driver: Vulkan 驱动 ID

    Returns:
        JVM 参数列表
    """
    args: list[str] = []

    renderer = get_renderer_by_id(renderer_id)
    if renderer:
        args.extend(renderer.jvm_args)

    if big_core:
        args.append("-Dminecraft.renderer.bigcore=true")

    if graphics_backend == "vulkan":
        args.append("-Dorg.lwjgl.vulkan.enable=true")
        if vulkan_driver == "system" or use_system_vulkan:
            args.append("-Dvulkan.driver=system")
        elif vulkan_driver == "turnip":
            args.append("-Dvulkan.driver=turnip")
    else:
        args.append("-Dorg.lwjgl.vulkan.enable=false")

    if use_system_vulkan and graphics_backend != "vulkan":
        args.append("-Dvulkan.override=true")

    logger.debug("渲染器 JVM 参数: %s", args)
    return args


def is_version_supports_vulkan(mc_version: str) -> bool:
    """检查指定 MC 版本是否支持 Vulkan 后端。"""
    try:
        parts = mc_version.split("-")[0].split("+")[0].split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor) >= (1, 26)
    except (ValueError, IndexError):
        return False
