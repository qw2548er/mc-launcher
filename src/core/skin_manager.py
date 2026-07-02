"""皮肤管理模块。

负责下载玩家皮肤、缓存皮肤文件、从皮肤纹理生成头像和2D全身预览。
支持从 Mojang API 获取正版皮肤，离线玩家的默认皮肤（Steve/Alex），
以及本地自定义皮肤文件和披风显示。
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False
    Image = None

from src.utils.config import get_config
from src.utils.file_utils import ensure_directory
from src.utils.http_utils import HttpClient, HttpError, get_http_client
from src.utils.logger import get_logger

logger = get_logger(__name__)

CACHE_BASE = Path("config/cache")
SKIN_CACHE_DIR = CACHE_BASE / "skins"
AVATAR_CACHE_DIR = CACHE_BASE / "avatars"
PREVIEW_CACHE_DIR = CACHE_BASE / "previews"
CAPE_CACHE_DIR = CACHE_BASE / "capes"
CUSTOM_SKINS_DIR = Path("config/custom_skins")

MOJANG_PROFILE_URL = "https://sessionserver.mojang.com/session/minecraft/profile/{uuid}"
MOJANG_SKIN_BASE = "https://textures.minecraft.net/texture/"

DEFAULT_SKINS = {}

DEFAULT_STEVE_COLORS = {
    "skin": (197, 138, 93, 255),
    "skin_shadow": (167, 113, 73, 255),
    "hair": (66, 43, 18, 255),
    "hair_shadow": (50, 32, 12, 255),
    "shirt": (0, 144, 0, 255),
    "shirt_shadow": (0, 114, 0, 255),
    "pants": (42, 42, 102, 255),
    "pants_shadow": (30, 30, 80, 255),
    "shoes": (50, 50, 50, 255),
}

DEFAULT_ALEX_COLORS = {
    "skin": (242, 180, 153, 255),
    "skin_shadow": (200, 145, 120, 255),
    "hair": (205, 127, 66, 255),
    "hair_shadow": (170, 100, 50, 255),
    "shirt": (68, 170, 204, 255),
    "shirt_shadow": (48, 140, 174, 255),
    "pants": (42, 42, 102, 255),
    "pants_shadow": (30, 30, 80, 255),
    "shoes": (50, 50, 50, 255),
}

OFFICIAL_CAPES = {
    "minecon2011": "953cac8b779fe41383e675ee2b86071a71f564ab13c5cde2885003f03a2a3562",
    "minecon2012": "a2e8d97ec79100e907d25cbb97c418a6c8c47fda93b3c04d9f7aa90fd24fec34",
    "minecon2013": "153b1a0dfcbae953cdeb6f2c2bf6bf79943239b137278079f27fdae774b4c2af",
    "minecon2015": "b0cc08840700447322d953a02bfe672554256ef34e20b70a10ad178327eafa0",
    "minecon2016": "702eee2a674b21e6d39ecb2c6c2bb5b812485d66bb55c0c9d3f0e2fb18930db",
    "migrator": "2340c0e03dd24a9bf6db7dbbd9f5496dab6edab59705ed04f63d42ef78f2f82",
    "vanilla": "f9a76539b0b806d6e57f21fe6d31077317b9501a39fdea1f293f9e67b0e6e2f",
}


class SkinModel:
    CLASSIC = "classic"
    SLIM = "slim"


@dataclass
class SkinTextures:
    skin_url: str = ""
    cape_url: str = ""
    skin_model: str = SkinModel.CLASSIC
    skin_hash: str = ""
    cape_hash: str = ""


class SkinManager:
    _instance: Optional["SkinManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "SkinManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._http: Optional[HttpClient] = None
        self._rw_lock = threading.RLock()
        self._custom_skin_paths: dict[str, Path] = {}
        for d in [SKIN_CACHE_DIR, AVATAR_CACHE_DIR, PREVIEW_CACHE_DIR,
                  CAPE_CACHE_DIR, CUSTOM_SKINS_DIR]:
            ensure_directory(d)
        self._load_custom_skins()
        self._initialized = True

    def _load_custom_skins(self) -> None:
        try:
            config = get_config()
            custom = config.get("custom_skins", {})
            if isinstance(custom, dict):
                for uuid_str, path_str in custom.items():
                    p = Path(path_str)
                    if p.exists():
                        self._custom_skin_paths[uuid_str] = p
        except Exception as e:
            logger.debug("加载自定义皮肤配置失败: %s", e)

    def _save_custom_skin_config(self) -> None:
        try:
            config = get_config()
            custom = {k: str(v) for k, v in self._custom_skin_paths.items()}
            config.set("custom_skins", custom)
            config.save()
        except Exception as e:
            logger.debug("保存自定义皮肤配置失败: %s", e)

    @property
    def http(self) -> HttpClient:
        if self._http is None:
            self._http = get_http_client()
        return self._http

    def get_default_skin_type(self, uuid_str: str) -> str:
        try:
            uuid_no_dash = uuid_str.replace("-", "")
            hash_bytes = bytes.fromhex(uuid_no_dash)
            return "alex" if hash_bytes[0] % 2 == 1 else "steve"
        except (ValueError, IndexError):
            return "steve"

    def get_skin_path(self, uuid_str: str) -> Path:
        return SKIN_CACHE_DIR / f"{uuid_str}.png"

    def get_cape_path(self, uuid_str: str) -> Path:
        return CAPE_CACHE_DIR / f"{uuid_str}.png"

    def get_avatar_path(self, uuid_str: str, size: int = 64) -> Path:
        return AVATAR_CACHE_DIR / f"{uuid_str}_{size}.png"

    def get_preview_path(self, uuid_str: str, size: int = 128) -> Path:
        return PREVIEW_CACHE_DIR / f"{uuid_str}_{size}.png"

    def get_custom_skin_path(self, uuid_str: str) -> Optional[Path]:
        return self._custom_skin_paths.get(uuid_str)

    def set_custom_skin(self, uuid_str: str, skin_file_path: Path) -> bool:
        skin_file_path = Path(skin_file_path)
        if not skin_file_path.exists():
            return False
        if not _HAS_PIL:
            return False
        try:
            img = Image.open(skin_file_path)
            w, h = img.size
            if w not in (64, 128) or h not in (32, 64):
                logger.warning("皮肤尺寸不标准: %dx%d", w, h)
            dest = CUSTOM_SKINS_DIR / f"{uuid_str}.png"
            img.convert("RGBA").save(dest, "PNG")
            self._custom_skin_paths[uuid_str] = dest
            self._save_custom_skin_config()
            self.clear_cache(uuid_str)
            return True
        except Exception as e:
            logger.error("设置自定义皮肤失败: %s", e)
            return False

    def clear_custom_skin(self, uuid_str: str) -> bool:
        if uuid_str in self._custom_skin_paths:
            del self._custom_skin_paths[uuid_str]
            custom_path = CUSTOM_SKINS_DIR / f"{uuid_str}.png"
            if custom_path.exists():
                custom_path.unlink(missing_ok=True)
            self._save_custom_skin_config()
            self.clear_cache(uuid_str)
            return True
        return False

    def fetch_mojang_textures(self, uuid_str: str) -> Optional[SkinTextures]:
        try:
            url = MOJANG_PROFILE_URL.format(uuid=uuid_str.replace("-", ""))
            data = self.http.get_json(url)
            if not data or "properties" not in data:
                return None

            textures_prop = None
            for prop in data.get("properties", []):
                if prop.get("name") == "textures":
                    textures_prop = prop.get("value", "")
                    break

            if not textures_prop:
                return None

            textures_json = base64.b64decode(textures_prop).decode("utf-8")
            textures_data = json.loads(textures_json)
            textures_info = textures_data.get("textures", {})

            result = SkinTextures()
            skin_data = textures_info.get("SKIN", {})
            if skin_data:
                result.skin_url = skin_data.get("url", "")
                metadata = skin_data.get("metadata", {})
                result.skin_model = metadata.get("model", SkinModel.CLASSIC)
                if result.skin_model == "slim":
                    result.skin_model = SkinModel.SLIM
                if result.skin_url:
                    result.skin_hash = result.skin_url.split("/")[-1]

            cape_data = textures_info.get("CAPE", {})
            if cape_data:
                result.cape_url = cape_data.get("url", "")
                if result.cape_url:
                    result.cape_hash = result.cape_url.split("/")[-1]

            return result
        except HttpError as e:
            logger.debug("获取Mojang皮肤信息失败 %s: %s", uuid_str, e)
            return None
        except Exception as e:
            logger.debug("解析Mojang皮肤信息失败 %s: %s", uuid_str, e)
            return None

    def download_skin(self, skin_url: str, uuid_str: str) -> Optional[Path]:
        with self._rw_lock:
            save_path = self.get_skin_path(uuid_str)
            if save_path.exists() and save_path.stat().st_size > 0:
                return save_path
            try:
                self.http.download_file(skin_url, save_path)
                logger.debug("皮肤下载成功: %s", uuid_str)
                return save_path
            except HttpError as e:
                logger.warning("下载皮肤失败 %s: %s", uuid_str, e)
                return None

    def download_cape(self, cape_url: str, uuid_str: str) -> Optional[Path]:
        with self._rw_lock:
            save_path = self.get_cape_path(uuid_str)
            if save_path.exists() and save_path.stat().st_size > 0:
                return save_path
            try:
                self.http.download_file(cape_url, save_path)
                logger.debug("披风下载成功: %s", uuid_str)
                return save_path
            except HttpError as e:
                logger.warning("下载披风失败 %s: %s", uuid_str, e)
                return None

    def _generate_default_skin(self, skin_type: str = "steve") -> Optional[Image.Image]:
        if not _HAS_PIL:
            return None
        colors = DEFAULT_STEVE_COLORS if skin_type == "steve" else DEFAULT_ALEX_COLORS
        arm_width = 4 if skin_type == "steve" else 3
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        pixels = img.load()

        def fill_rect(x, y, w, h, color):
            for px in range(x, x + w):
                for py in range(y, y + h):
                    if 0 <= px < 64 and 0 <= py < 64:
                        pixels[px, py] = color

        fill_rect(8, 8, 8, 8, colors["skin"])
        fill_rect(40, 8, 8, 8, colors["hair"])
        fill_rect(8, 0, 8, 8, colors["hair"])
        fill_rect(0, 8, 8, 8, colors["hair"])
        fill_rect(16, 8, 8, 8, colors["hair"])
        fill_rect(8, 16, 8, 8, colors["hair_shadow"])

        fill_rect(20, 20, 8, 12, colors["shirt"])
        fill_rect(20, 36, 8, 12, colors["shirt"])
        fill_rect(32, 20, 4, 12, colors["shirt_shadow"])
        fill_rect(16, 20, 4, 12, colors["shirt_shadow"])

        fill_rect(44, 20, arm_width, 12, colors["shirt"])
        fill_rect(36, 52, arm_width, 12, colors["shirt"])

        fill_rect(4, 20, 4, 12, colors["pants"])
        fill_rect(20, 52, 4, 12, colors["pants"])
        fill_rect(4, 36, 4, 4, colors["pants_shadow"])
        fill_rect(20, 36, 4, 4, colors["pants_shadow"])
        fill_rect(8, 20, 4, 12, colors["pants"])
        fill_rect(24, 52, 4, 12, colors["pants"])

        fill_rect(4, 0, 4, 4, colors["shoes"])
        fill_rect(8, 0, 4, 4, colors["shoes"])
        fill_rect(20, 0, 4, 4, colors["shoes"])
        fill_rect(24, 0, 4, 4, colors["shoes"])

        return img

    def download_default_skin(self, skin_type: str = "steve") -> Optional[Path]:
        cache_path = SKIN_CACHE_DIR / f"default_{skin_type}.png"
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path
        try:
            if _HAS_PIL:
                img = self._generate_default_skin(skin_type)
                if img:
                    img.save(cache_path, "PNG")
                    return cache_path
        except Exception as e:
            logger.debug("生成默认皮肤失败: %s", e)
        return None

    def get_default_skin_path(self, uuid_str: str) -> Path:
        skin_type = self.get_default_skin_type(uuid_str)
        skin_path = self.get_skin_path(uuid_str)

        custom = self.get_custom_skin_path(uuid_str)
        if custom and custom.exists():
            import shutil
            shutil.copy2(custom, skin_path)
            return skin_path

        if not skin_path.exists() or skin_path.stat().st_size == 0:
            default_path = self.download_default_skin(skin_type)
            if default_path and default_path.exists():
                import shutil
                shutil.copy2(default_path, skin_path)
            elif _HAS_PIL:
                try:
                    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                    img.save(skin_path, "PNG")
                except Exception:
                    pass

        return skin_path

    def extract_avatar(
        self,
        skin_path: Path,
        uuid_str: str,
        size: int = 64,
    ) -> Optional[Path]:
        if not _HAS_PIL:
            return None
        avatar_path = self.get_avatar_path(uuid_str, size)
        if avatar_path.exists() and avatar_path.stat().st_size > 0:
            return avatar_path
        try:
            skin_path = Path(skin_path)
            if not skin_path.exists():
                return None
            img = Image.open(skin_path).convert("RGBA")
            w, h = img.size
            if w < 64 or h < 32:
                return None

            face = img.crop((8, 8, 16, 16))
            if h >= 64:
                helmet = img.crop((40, 8, 48, 16))
                face = Image.alpha_composite(face.convert("RGBA"), helmet.convert("RGBA"))

            avatar = face.resize((size, size), Image.NEAREST)
            avatar.save(avatar_path, "PNG")
            return avatar_path
        except Exception as e:
            logger.error("提取头像失败 %s: %s", uuid_str, e)
            return None

    def render_preview(
        self,
        skin_path: Path,
        uuid_str: str,
        size: int = 128,
        cape_path: Optional[Path] = None,
        slim_model: bool = False,
    ) -> Optional[Path]:
        if not _HAS_PIL:
            return None
        preview_path = self.get_preview_path(uuid_str, size)
        if preview_path.exists() and preview_path.stat().st_size > 0:
            return preview_path
        try:
            skin_path = Path(skin_path)
            if not skin_path.exists():
                return None
            skin = Image.open(skin_path).convert("RGBA")
            sw, sh = skin.size
            if sw < 64 or sh < 32:
                return None

            scale = size // 32
            w, h = 16 * scale, 32 * scale
            preview = Image.new("RGBA", (w, h), (0, 0, 0, 0))

            def copy_region(src_img, sx, sy, sw_, sh_, dx, dy, layer_scale=1, overlay=False):
                region = src_img.crop((sx, sy, sx + sw_, sy + sh_))
                rw = sw_ * layer_scale
                rh = sh_ * layer_scale
                if rw != sw_ or rh != sh_:
                    region = region.resize((rw, rh), Image.NEAREST)
                if overlay:
                    preview.paste(region, (dx * layer_scale, dy * layer_scale), region)
                else:
                    preview.paste(region, (dx * layer_scale, dy * layer_scale))

            head_top = 4
            body_height = 12
            leg_height = 12
            arm_width = 4 if not slim_model else 3

            head_x = (w - 8 * scale) // 2
            head_y = 0
            copy_region(skin, 8, 8, 8, 8, head_x // scale, head_y // scale, scale)
            if sh >= 64:
                copy_region(skin, 40, 8, 8, 8, head_x // scale, head_y // scale, scale, overlay=True)

            body_x = (w - 8 * scale) // 2
            body_y = 8 * scale
            copy_region(skin, 20, 20, 8, 12, body_x // scale, body_y // scale + 8, scale)
            if sh >= 64:
                copy_region(skin, 20, 36, 8, 12, body_x // scale, body_y // scale + 8, scale, overlay=True)

            arm_y = 8 * scale
            left_arm_x = body_x - arm_width * scale
            right_arm_x = body_x + 8 * scale
            aw = 4 if not slim_model else 3
            copy_region(skin, 44, 20, aw, 12, left_arm_x // scale, arm_y // scale + 8, scale)
            copy_region(skin, 36, 52 if sh >= 64 else 20, aw, 12, right_arm_x // scale, arm_y // scale + 8, scale)
            if sh >= 64:
                copy_region(skin, 44, 36, aw, 12, left_arm_x // scale, arm_y // scale + 8, scale, overlay=True)
                copy_region(skin, 52, 52, aw, 12, right_arm_x // scale, arm_y // scale + 8, scale, overlay=True)

            leg_y = 20 * scale
            left_leg_x = body_x + 4 * scale
            right_leg_x = body_x
            copy_region(skin, 4, 20, 4, 12, right_leg_x // scale, leg_y // scale + 20, scale)
            copy_region(skin, 20, 52 if sh >= 64 else 20, 4, 12, left_leg_x // scale, leg_y // scale + 20, scale)
            if sh >= 64:
                copy_region(skin, 4, 36, 4, 12, right_leg_x // scale, leg_y // scale + 20, scale, overlay=True)
                copy_region(skin, 4, 52, 4, 12, left_leg_x // scale, leg_y // scale + 20, scale, overlay=True)

            if cape_path and Path(cape_path).exists():
                try:
                    cape = Image.open(cape_path).convert("RGBA")
                    cw, ch = cape.size
                    if cw >= 64 and ch >= 32:
                        cape_tex = cape.crop((1, 1, 11, 17))
                        cape_tex = cape_tex.resize((10 * scale, 16 * scale), Image.NEAREST)
                        cape_x = body_x - 1 * scale
                        cape_y = 8 * scale
                        preview.paste(cape_tex, (cape_x, cape_y), cape_tex)
                except Exception:
                    pass

            preview.save(preview_path, "PNG")
            return preview_path
        except Exception as e:
            logger.error("生成预览失败 %s: %s", uuid_str, e)
            return None

    def get_avatar(
        self,
        uuid_str: str,
        username: str = "",
        skin_url: Optional[str] = None,
        cape_url: Optional[str] = None,
        skin_model: str = SkinModel.CLASSIC,
        size: int = 64,
        callback: Optional[Callable[[Optional[Path]], None]] = None,
    ) -> Optional[Path]:
        with self._rw_lock:
            avatar_path = self.get_avatar_path(uuid_str, size)
            if avatar_path.exists() and avatar_path.stat().st_size > 0:
                if callback:
                    callback(avatar_path)
                return avatar_path

            skin_path = self._resolve_skin(uuid_str, skin_url)
            cape_p = None
            if cape_url:
                cape_p = self.download_cape(cape_url, uuid_str)

            if skin_path and skin_path.exists():
                result = self.extract_avatar(skin_path, uuid_str, size)
                if callback:
                    callback(result)
                return result

            default_path = self.get_default_skin_path(uuid_str)
            result = self.extract_avatar(default_path, uuid_str, size)
            if callback:
                callback(result)
            return result

    def get_preview(
        self,
        uuid_str: str,
        username: str = "",
        skin_url: Optional[str] = None,
        cape_url: Optional[str] = None,
        skin_model: str = SkinModel.CLASSIC,
        size: int = 128,
        callback: Optional[Callable[[Optional[Path]], None]] = None,
    ) -> Optional[Path]:
        with self._rw_lock:
            preview_path = self.get_preview_path(uuid_str, size)
            if preview_path.exists() and preview_path.stat().st_size > 0:
                if callback:
                    callback(preview_path)
                return preview_path

            skin_path = self._resolve_skin(uuid_str, skin_url)
            cape_p = None
            if cape_url:
                cape_p = self.download_cape(cape_url, uuid_str)

            slim = skin_model == SkinModel.SLIM
            if skin_path and skin_path.exists():
                result = self.render_preview(skin_path, uuid_str, size, cape_p, slim)
                if callback:
                    callback(result)
                return result

            default_path = self.get_default_skin_path(uuid_str)
            result = self.render_preview(default_path, uuid_str, size, cape_p, slim)
            if callback:
                callback(result)
            return result

    def _resolve_skin(self, uuid_str: str, skin_url: Optional[str]) -> Optional[Path]:
        skin_path = self.get_skin_path(uuid_str)
        custom = self.get_custom_skin_path(uuid_str)
        if custom and custom.exists():
            import shutil
            shutil.copy2(custom, skin_path)
            return skin_path
        if skin_path.exists() and skin_path.stat().st_size > 0:
            return skin_path
        if skin_url:
            downloaded = self.download_skin(skin_url, uuid_str)
            if downloaded:
                return downloaded
        return None

    def fetch_and_update_skin(
        self,
        uuid_str: str,
        callback: Optional[Callable[[Optional[Path], Optional[Path]], None]] = None,
    ) -> None:
        def _worker():
            textures = self.fetch_mojang_textures(uuid_str)
            skin_p = None
            cape_p = None
            if textures:
                if textures.skin_url:
                    self.clear_cache(uuid_str)
                    skin_p = self.download_skin(textures.skin_url, uuid_str)
                if textures.cape_url:
                    cape_p = self.download_cape(textures.cape_url, uuid_str)
                try:
                    from src.core.account import AccountManager
                    mgr = AccountManager()
                    acc = mgr.get_by_uuid(uuid_str)
                    if acc and textures.skin_url:
                        mgr.update_microsoft_account(
                            uuid_str,
                            skin_url=textures.skin_url,
                            skin_variant=textures.skin_model,
                        )
                except Exception:
                    pass
            if callback:
                callback(skin_p, cape_p)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def clear_cache(self, uuid_str: Optional[str] = None) -> None:
        import shutil
        with self._rw_lock:
            if uuid_str:
                for pattern in [f"{uuid_str}.png", f"{uuid_str}_*.png"]:
                    for d in [SKIN_CACHE_DIR, AVATAR_CACHE_DIR, PREVIEW_CACHE_DIR, CAPE_CACHE_DIR]:
                        for f in d.glob(pattern):
                            f.unlink(missing_ok=True)
                logger.info("已清除 %s 的皮肤缓存", uuid_str)
            else:
                for d in [SKIN_CACHE_DIR, AVATAR_CACHE_DIR, PREVIEW_CACHE_DIR, CAPE_CACHE_DIR]:
                    if d.exists():
                        shutil.rmtree(d)
                    ensure_directory(d)
                logger.info("已清除全部皮肤缓存")


def get_skin_manager() -> SkinManager:
    return SkinManager()
