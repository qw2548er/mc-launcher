"""Microsoft OAuth 2.0 认证模块。

实现 Minecraft 正版登录的完整 OAuth 流程：
1. 设备码授权 (Device Code Flow) - 适合桌面应用
2. Xbox Live 认证
3. XSTS 认证
4. Minecraft Access Token 获取
5. 玩家 Profile 获取（皮肤、UUID）

注意：设备码流程需要一个已启用公共客户端流并经 Mojang 审批的 Azure 应用。
默认使用可配置的 client_id，用户可通过环境变量或配置覆盖。
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from typing import Callable, Optional

from src.utils.http_utils import HttpClient, HttpError, get_http_client
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── OAuth 配置 ──────────────────────────────────────────────
# Client ID 优先级：
# 1. 构造函数传入的 client_id 参数
# 2. 环境变量 MC_LAUNCHER_CLIENT_ID
# 3. 配置文件 auth.ms_client_id
# 正式使用时需要在 Azure Portal 注册应用并提交 Mojang 审批
def _get_default_client_id() -> str:
    env_id = os.environ.get("MC_LAUNCHER_CLIENT_ID", "")
    if env_id:
        return env_id
    try:
        from src.utils.config import get_config
        return get_config().get("auth.ms_client_id", "")
    except Exception:
        return ""

DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
XBL_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"

SCOPES = "XboxLive.signin offline_access"


@dataclass
class DeviceCodeInfo:
    """设备码信息。"""
    user_code: str
    device_code: str
    verification_uri: str
    expires_in: int
    interval: int
    message: str


@dataclass
class MSAuthTokens:
    """Microsoft 认证令牌。"""
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


@dataclass
class MinecraftProfile:
    """Minecraft 玩家信息。"""
    uuid: str
    username: str
    skin_url: Optional[str] = None
    skin_variant: str = "classic"
    cape_url: Optional[str] = None


@dataclass
class AuthResult:
    """认证结果。"""
    access_token: str
    refresh_token: str
    expires_in: int
    profile: MinecraftProfile


class MicrosoftAuth:
    """Microsoft 认证流程处理器。

    使用设备码授权流程，适合桌面应用场景：
    - 打开浏览器让用户登录
    - 轮询 token 端点直到用户完成授权
    """

    def __init__(self, http_client: Optional[HttpClient] = None, client_id: Optional[str] = None):
        self._http = http_client or get_http_client()
        self._cancel_event = threading.Event()
        self._device_code: Optional[DeviceCodeInfo] = None
        self._client_id = client_id or _get_default_client_id()

    @property
    def client_id(self) -> str:
        return self._client_id

    def cancel(self) -> None:
        """取消当前认证流程。"""
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def start_device_code_flow(self) -> DeviceCodeInfo:
        """启动设备码授权流程。

        Returns:
            设备码信息（包含用户码和验证 URL）

        Raises:
            AuthError: 未配置 client_id 或网络请求失败
        """
        self._cancel_event.clear()

        if not self._client_id:
            raise AuthError(
                "未配置 Microsoft 登录 Client ID。\n"
                "请通过环境变量 MC_LAUNCHER_CLIENT_ID 设置，"
                "或在初始化 MicrosoftAuth 时传入 client_id 参数。\n"
                "需要在 Azure Portal 注册应用并提交 Mojang 审批。"
            )

        data = {
            "client_id": self._client_id,
            "scope": SCOPES,
        }

        try:
            resp = self._http.post(DEVICE_CODE_URL, data=data)
            result = resp.json()
            self._device_code = DeviceCodeInfo(
                user_code=result["user_code"],
                device_code=result["device_code"],
                verification_uri=result["verification_uri"],
                expires_in=result.get("expires_in", 900),
                interval=result.get("interval", 5),
                message=result.get("message", ""),
            )
            logger.info("设备码流程已启动，用户码: %s", self._device_code.user_code)
            return self._device_code
        except (HttpError, KeyError, json.JSONDecodeError) as e:
            error_detail = ""
            if isinstance(e, HttpError) and e.original_error is not None:
                try:
                    err_resp = e.original_error.response.json()
                    error_detail = err_resp.get("error_description", str(e))
                except Exception:
                    error_detail = str(e)
            else:
                error_detail = str(e)
            logger.error("启动设备码流程失败: %s", error_detail)
            raise AuthError(f"启动登录失败: {error_detail}") from e

    def open_browser_for_login(self) -> bool:
        """打开浏览器进行登录。"""
        if self._device_code is None:
            return False
        try:
            webbrowser.open(self._device_code.verification_uri)
            return True
        except Exception as e:
            logger.warning("无法打开浏览器: %s", e)
            return False

    def poll_for_token(
        self,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> MSAuthTokens:
        """轮询等待用户完成授权并获取 Microsoft token。

        Args:
            progress_callback: 进度回调，接收状态消息

        Returns:
            Microsoft 令牌
        """
        if self._device_code is None:
            raise AuthError("请先调用 start_device_code_flow()")

        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self._client_id,
            "device_code": self._device_code.device_code,
        }

        interval = self._device_code.interval
        expires_at = time.time() + self._device_code.expires_in

        while time.time() < expires_at and not self._cancel_event.is_set():
            try:
                resp = self._http.post(TOKEN_URL, data=data)
                result = resp.json()
                tokens = MSAuthTokens(
                    access_token=result["access_token"],
                    refresh_token=result["refresh_token"],
                    expires_in=result.get("expires_in", 3600),
                    token_type=result.get("token_type", "Bearer"),
                )
                logger.info("成功获取 Microsoft access token")
                return tokens
            except HttpError as e:
                if e.status_code == 400:
                    try:
                        err_resp = e.original_error.response
                        error_data = err_resp.json()
                        error_code = error_data.get("error", "")
                        if error_code == "authorization_pending":
                            if progress_callback:
                                progress_callback("等待用户授权...")
                        elif error_code == "slow_down":
                            interval += 5
                            if progress_callback:
                                progress_callback("请求过于频繁，减慢轮询速度...")
                        elif error_code == "expired_token":
                            raise AuthError("设备码已过期，请重试")
                        elif error_code == "authorization_declined":
                            raise AuthError("用户拒绝了授权")
                        else:
                            error_desc = error_data.get("error_description", error_code)
                            raise AuthError(f"认证失败: {error_desc}")
                    except (json.JSONDecodeError, AttributeError):
                        if progress_callback:
                            progress_callback("等待用户授权...")
                else:
                    raise AuthError(f"网络错误: {e}") from e

            if self._cancel_event.is_set():
                raise AuthError("认证已取消")

            time.sleep(interval)

        if self._cancel_event.is_set():
            raise AuthError("认证已取消")
        raise AuthError("登录超时，请重试")

    def refresh_microsoft_token(self, refresh_token: str) -> MSAuthTokens:
        """使用 refresh_token 刷新 Microsoft access token。

        Args:
            refresh_token: 刷新令牌

        Returns:
            新的 Microsoft 令牌
        """
        data = {
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "refresh_token": refresh_token,
            "scope": SCOPES,
        }

        try:
            resp = self._http.post(TOKEN_URL, data=data)
            result = resp.json()
            tokens = MSAuthTokens(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", refresh_token),
                expires_in=result.get("expires_in", 3600),
                token_type=result.get("token_type", "Bearer"),
            )
            logger.info("Microsoft token 刷新成功")
            return tokens
        except HttpError as e:
            error_detail = str(e)
            if e.original_error is not None:
                try:
                    err_resp = e.original_error.response.json()
                    error_detail = err_resp.get("error_description", str(e))
                except Exception:
                    pass
            logger.error("刷新 Microsoft token 失败: %s", error_detail)
            raise AuthError(f"刷新 token 失败: {error_detail}") from e

    def authenticate_xbl(self, ms_access_token: str) -> tuple[str, str]:
        """Xbox Live 认证。

        Args:
            ms_access_token: Microsoft access token

        Returns:
            (xbl_token, user_hash)
        """
        payload = {
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": f"d={ms_access_token}",
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        }

        try:
            resp = self._http.post(
                XBL_AUTH_URL,
                json_data=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            result = resp.json()
            xbl_token = result["Token"]
            user_hash = ""
            for uhs in result.get("DisplayClaims", {}).get("xui", []):
                if "uhs" in uhs:
                    user_hash = uhs["uhs"]
                    break
            if not user_hash:
                raise AuthError("XBL 认证失败: 未获取到 user hash")
            logger.info("XBL 认证成功")
            return xbl_token, user_hash
        except (HttpError, KeyError) as e:
            logger.error("XBL 认证失败: %s", e)
            raise AuthError(f"Xbox Live 认证失败: {e}") from e

    def authenticate_xsts(self, xbl_token: str) -> tuple[str, str]:
        """XSTS (Xbox Secure Token Service) 认证。

        Args:
            xbl_token: XBL token

        Returns:
            (xsts_token, user_hash)
        """
        payload = {
            "Properties": {
                "SandboxId": "RETAIL",
                "UserTokens": [xbl_token],
            },
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        }

        try:
            resp = self._http.post(
                XSTS_AUTH_URL,
                json_data=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            result = resp.json()
            xsts_token = result["Token"]
            user_hash = ""
            for uhs in result.get("DisplayClaims", {}).get("xui", []):
                if "uhs" in uhs:
                    user_hash = uhs["uhs"]
                    break
            if not user_hash:
                raise AuthError("XSTS 认证失败: 未获取到 user hash")
            logger.info("XSTS 认证成功")
            return xsts_token, user_hash
        except HttpError as e:
            if e.status_code == 401:
                try:
                    error_data = e.original_error.response.json()
                    xerr = error_data.get("XErr", 0)
                    if xerr == 2148916233:
                        raise AuthError("该 Microsoft 账号没有 Xbox 档案，请在 Xbox 网站创建后重试")
                    elif xerr == 2148916235:
                        raise AuthError("Xbox Live 在您的地区不可用")
                    elif xerr == 2148916236 or xerr == 2148916237:
                        raise AuthError("账号需要成人验证")
                    elif xerr == 2148916238:
                        raise AuthError("子账号需要添加到家庭组才能登录")
                    else:
                        raise AuthError(f"XSTS 认证失败 (错误码: {xerr})，该账号可能未购买 Minecraft 或 Xbox 服务不可用")
                except (json.JSONDecodeError, AttributeError):
                    pass
            logger.error("XSTS 认证失败: %s", e)
            raise AuthError(f"XSTS 认证失败: {e}") from e

    def get_minecraft_token(self, xsts_token: str, user_hash: str) -> tuple[str, int]:
        """获取 Minecraft Access Token。

        Args:
            xsts_token: XSTS token
            user_hash: User Hash

        Returns:
            (mc_access_token, expires_in)
        """
        payload = {
            "identityToken": f"XBL3.0 x={user_hash};{xsts_token}",
            "ensureLegacyEnabled": True,
        }

        try:
            resp = self._http.post(
                MC_LOGIN_URL,
                json_data=payload,
                headers={"Content-Type": "application/json"},
            )
            result = resp.json()
            mc_token = result["access_token"]
            expires_in = result.get("expires_in", 86400)
            logger.info("成功获取 Minecraft access token")
            return mc_token, expires_in
        except (HttpError, KeyError) as e:
            logger.error("获取 Minecraft token 失败: %s", e)
            raise AuthError(f"获取 Minecraft token 失败: {e}") from e

    def get_minecraft_profile(self, mc_access_token: str) -> MinecraftProfile:
        """获取 Minecraft 玩家信息（UUID、用户名、皮肤）。

        Args:
            mc_access_token: Minecraft access token

        Returns:
            玩家 Profile
        """
        headers = {"Authorization": f"Bearer {mc_access_token}"}

        try:
            resp = self._http.get(MC_PROFILE_URL, headers=headers)
            result = resp.json()

            profile = MinecraftProfile(
                uuid=self._format_uuid(result["id"]),
                username=result["name"],
            )

            for skin in result.get("skins", []):
                if skin.get("state", "ACTIVE") == "ACTIVE":
                    profile.skin_url = skin.get("url")
                    profile.skin_variant = skin.get("variant", "classic").lower()
                    break

            for cape in result.get("capes", []):
                if cape.get("state", "INACTIVE") == "ACTIVE":
                    profile.cape_url = cape.get("url")
                    break

            logger.info("获取玩家信息成功: %s (%s)", profile.username, profile.uuid)
            return profile
        except HttpError as e:
            if e.status_code == 404:
                raise AuthError("该账号没有购买 Minecraft Java 版，请先购买后再试")
            if e.status_code == 401:
                raise AuthError("Minecraft token 无效，请重新登录")
            logger.error("获取玩家 Profile 失败: %s", e)
            raise AuthError(f"获取玩家信息失败: {e}") from e
        except (KeyError, json.JSONDecodeError) as e:
            logger.error("解析玩家 Profile 失败: %s", e)
            raise AuthError(f"解析玩家信息失败: {e}") from e

    def full_login(
        self,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> AuthResult:
        """执行完整的 Microsoft 登录流程（从设备码到获取 Profile）。

        需要先调用 start_device_code_flow() 获取设备码并打开浏览器。

        Args:
            progress_callback: 进度回调

        Returns:
            完整认证结果（包含 Minecraft token 和 Profile）
        """
        def _progress(msg: str):
            if progress_callback:
                progress_callback(msg)

        _progress("等待 Microsoft 授权...")
        ms_tokens = self.poll_for_token(_progress)

        _progress("正在进行 Xbox Live 认证...")
        xbl_token, uhs = self.authenticate_xbl(ms_tokens.access_token)

        _progress("正在获取 XSTS 令牌...")
        xsts_token, uhs = self.authenticate_xsts(xbl_token)

        _progress("正在获取 Minecraft 令牌...")
        mc_token, mc_expires = self.get_minecraft_token(xsts_token, uhs)

        _progress("正在获取玩家信息...")
        profile = self.get_minecraft_profile(mc_token)

        _progress("登录成功!")
        return AuthResult(
            access_token=mc_token,
            refresh_token=ms_tokens.refresh_token,
            expires_in=mc_expires,
            profile=profile,
        )

    def refresh_full_login(self, refresh_token: str) -> AuthResult:
        """使用 refresh_token 执行完整的 token 刷新流程。

        Args:
            refresh_token: Microsoft refresh token

        Returns:
            新的认证结果
        """
        ms_tokens = self.refresh_microsoft_token(refresh_token)
        xbl_token, uhs = self.authenticate_xbl(ms_tokens.access_token)
        xsts_token, uhs = self.authenticate_xsts(xbl_token)
        mc_token, mc_expires = self.get_minecraft_token(xsts_token, uhs)
        profile = self.get_minecraft_profile(mc_token)

        return AuthResult(
            access_token=mc_token,
            refresh_token=ms_tokens.refresh_token,
            expires_in=mc_expires,
            profile=profile,
        )

    @staticmethod
    def _format_uuid(uuid_str: str) -> str:
        """将无横线 UUID 格式化为标准格式。"""
        if len(uuid_str) == 32 and "-" not in uuid_str:
            return f"{uuid_str[:8]}-{uuid_str[8:12]}-{uuid_str[12:16]}-{uuid_str[16:20]}-{uuid_str[20:]}"
        return uuid_str


class AuthError(Exception):
    """认证异常。"""
    pass
