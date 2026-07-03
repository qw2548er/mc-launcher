"""账号管理模块。

支持 Microsoft 正版登录和离线模式，多账号管理，凭据加密存储。
"""

import base64
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_ACCOUNTS_PATH = Path("config/accounts.json")

_ENCRYPTION_KEY: bytes = hashlib.sha256(b"minecraft-launcher-salt").digest()


@dataclass
class AccountInfo:
    """账号信息数据类。"""

    uuid: str
    type: str
    username: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None
    skin_url: Optional[str] = None
    skin_variant: str = "classic"
    is_selected: bool = False
    last_used: float = 0.0

    @property
    def is_offline(self) -> bool:
        return self.type == "offline"

    @property
    def is_microsoft(self) -> bool:
        return self.type == "microsoft"

    @property
    def is_token_expired(self) -> bool:
        """检查 access token 是否已过期（提前5分钟判定过期以避免边界问题）。"""
        if self.expires_at is None:
            return self.is_microsoft
        try:
            expire_time = datetime.fromisoformat(self.expires_at)
            now = datetime.now(timezone.utc)
            return now.timestamp() > expire_time.timestamp() - 300
        except (ValueError, TypeError):
            return True

    @property
    def type_label(self) -> str:
        return "正版" if self.is_microsoft else "离线"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AccountInfo":
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class AccountManager:
    """账号管理器。

    管理多账号的增删改查，持久化到 accounts.json，支持 token 加密存储。
    """

    _instance: Optional["AccountManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "AccountManager":
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
        self._accounts: list[AccountInfo] = []
        self._accounts_path: Path = DEFAULT_ACCOUNTS_PATH
        self._rw_lock = threading.RLock()
        self._initialized = True

    def load(self, accounts_path: Optional[Path] = None) -> None:
        if accounts_path is not None:
            self._accounts_path = Path(accounts_path)

        with self._rw_lock:
            if not self._accounts_path.exists():
                logger.info("账号文件不存在，将创建新文件: %s", self._accounts_path)
                self._accounts = []
                return

            try:
                with open(self._accounts_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                accounts_data = data.get("accounts", [])
                self._accounts = []
                selected_uuid = data.get("selected_account", "")

                for acc_data in accounts_data:
                    acc_data = self._decrypt_sensitive_fields(acc_data)
                    acc = AccountInfo.from_dict(acc_data)
                    self._accounts.append(acc)

                for acc in self._accounts:
                    acc.is_selected = False

                selected_acc = self.get_by_uuid(selected_uuid) if selected_uuid else None
                if selected_acc:
                    selected_acc.is_selected = True
                elif self._accounts:
                    self._accounts[0].is_selected = True

                logger.info("已加载 %d 个账号", len(self._accounts))
            except (json.JSONDecodeError, OSError, KeyError) as e:
                logger.error("加载账号文件失败: %s", e)
                self._accounts = []

    def save(self) -> None:
        with self._rw_lock:
            try:
                self._accounts_path.parent.mkdir(parents=True, exist_ok=True)

                accounts_data = []
                for acc in self._accounts:
                    acc_dict = acc.to_dict()
                    acc_dict = self._encrypt_sensitive_fields(acc_dict)
                    accounts_data.append(acc_dict)

                selected = self.get_selected()
                data = {
                    "accounts": accounts_data,
                    "selected_account": selected.uuid if selected else "",
                }

                with open(self._accounts_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.debug("账号数据已保存: %d 个账号", len(self._accounts))
            except OSError as e:
                logger.error("保存账号文件失败: %s", e)

    def add_offline_account(self, username: str) -> AccountInfo:
        username = username.strip()
        if not username:
            raise ValueError("玩家名不能为空")
        if len(username) > 16:
            raise ValueError("玩家名不能超过 16 个字符")
        if not username.replace("_", "").isalnum():
            raise ValueError("玩家名只能包含字母、数字和下划线")

        existing = self.get_by_username_and_type(username, "offline")
        if existing:
            logger.info("离线账号 %s 已存在", username)
            return existing

        account_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"offline:{username}"))

        is_first = len(self._accounts) == 0
        account = AccountInfo(
            uuid=account_uuid,
            type="offline",
            username=username,
            is_selected=is_first,
            last_used=time.time(),
        )

        with self._rw_lock:
            if is_first:
                for acc in self._accounts:
                    acc.is_selected = False
            self._accounts.append(account)
            logger.info("添加离线账号: %s (UUID: %s)", username, account_uuid)

        self.save()
        return account

    def add_microsoft_account(
        self,
        account_uuid: str,
        username: str,
        access_token: str,
        refresh_token: str,
        expires_in: int = 86400,
        skin_url: Optional[str] = None,
        skin_variant: str = "classic",
    ) -> AccountInfo:
        expire_time = datetime.now(timezone.utc).timestamp() + expires_in
        expires_at = datetime.fromtimestamp(expire_time, tz=timezone.utc).isoformat()

        with self._rw_lock:
            existing = None
            for acc in self._accounts:
                if acc.uuid == account_uuid or (acc.is_microsoft and acc.username == username):
                    existing = acc
                    break

            if existing:
                existing.username = username
                existing.access_token = access_token
                existing.refresh_token = refresh_token
                existing.expires_at = expires_at
                existing.skin_url = skin_url
                existing.skin_variant = skin_variant
                existing.last_used = time.time()
                if not self.get_selected():
                    existing.is_selected = True
                self.save()
                logger.info("更新正版账号: %s", username)
                return existing

            is_first = len(self._accounts) == 0
            account = AccountInfo(
                uuid=account_uuid,
                type="microsoft",
                username=username,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                skin_url=skin_url,
                skin_variant=skin_variant,
                is_selected=is_first,
                last_used=time.time(),
            )

            if is_first:
                for acc in self._accounts:
                    acc.is_selected = False
            self._accounts.append(account)
            logger.info("添加正版账号: %s (UUID: %s)", username, account_uuid)

        self.save()
        return account

    def update_microsoft_account(
        self,
        account_uuid: str,
        *,
        username: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
        skin_url: Optional[str] = None,
        skin_variant: Optional[str] = None,
    ) -> bool:
        with self._rw_lock:
            acc = self.get_by_uuid(account_uuid)
            if acc is None:
                return False

            if username is not None:
                acc.username = username
            if access_token is not None:
                acc.access_token = access_token
            if refresh_token is not None:
                acc.refresh_token = refresh_token
            if expires_in is not None:
                expire_time = datetime.now(timezone.utc).timestamp() + expires_in
                acc.expires_at = datetime.fromtimestamp(expire_time, tz=timezone.utc).isoformat()
            if skin_url is not None:
                acc.skin_url = skin_url
            if skin_variant is not None:
                acc.skin_variant = skin_variant
            acc.last_used = time.time()

            self.save()
            return True

    def update_token(
        self,
        account_uuid: str,
        access_token: str,
        refresh_token: str,
        expires_in: int = 86400,
    ) -> bool:
        return self.update_microsoft_account(
            account_uuid,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

    def remove_account(self, account_uuid: str) -> bool:
        with self._rw_lock:
            for i, acc in enumerate(self._accounts):
                if acc.uuid == account_uuid:
                    was_selected = acc.is_selected
                    removed = self._accounts.pop(i)

                    if was_selected and self._accounts:
                        self._accounts[0].is_selected = True

                    try:
                        from src.core.skin_manager import get_skin_manager
                        get_skin_manager().clear_cache(account_uuid)
                    except Exception:
                        pass

                    self.save()
                    logger.info("删除账号: %s (%s)", removed.username, removed.type)
                    return True

        logger.warning("未找到要删除的账号: %s", account_uuid)
        return False

    def switch_account(self, account_uuid: str) -> Optional[AccountInfo]:
        with self._rw_lock:
            found = False
            for acc in self._accounts:
                if acc.uuid == account_uuid:
                    acc.is_selected = True
                    acc.last_used = time.time()
                    found = True
                else:
                    acc.is_selected = False

            if not found:
                logger.warning("未找到账号: %s", account_uuid)
                return None

            self.save()
            logger.info("已切换到账号: %s", account_uuid)
            return self.get_selected()

    def get_selected(self) -> Optional[AccountInfo]:
        with self._rw_lock:
            for acc in self._accounts:
                if acc.is_selected:
                    return acc
            if self._accounts:
                return self._accounts[0]
        return None

    def get_by_uuid(self, account_uuid: str) -> Optional[AccountInfo]:
        with self._rw_lock:
            for acc in self._accounts:
                if acc.uuid == account_uuid:
                    return acc
        return None

    def get_by_username(self, username: str) -> Optional[AccountInfo]:
        with self._rw_lock:
            for acc in self._accounts:
                if acc.username == username:
                    return acc
        return None

    def get_by_username_and_type(self, username: str, account_type: str) -> Optional[AccountInfo]:
        with self._rw_lock:
            for acc in self._accounts:
                if acc.username == username and acc.type == account_type:
                    return acc
        return None

    def get_all(self) -> list[AccountInfo]:
        with self._rw_lock:
            return list(self._accounts)

    def get_count(self) -> int:
        with self._rw_lock:
            return len(self._accounts)

    def ensure_valid_token(self, account: AccountInfo) -> Optional[AccountInfo]:
        """确保账号 token 有效，过期则自动刷新。

        Args:
            account: 要检查的账号

        Returns:
            更新后的账号（如果刷新成功），None 表示需要重新登录
        """
        from src.core.auth import MicrosoftAuth, AuthError

        if account.is_offline:
            return account

        if not account.is_token_expired:
            return account

        if not account.refresh_token:
            logger.warning("账号 %s token 过期且无 refresh token，需要重新登录", account.username)
            return None

        try:
            auth = MicrosoftAuth()
            result = auth.refresh_full_login(account.refresh_token)

            self.update_microsoft_account(
                account.uuid,
                username=result.profile.username,
                access_token=result.access_token,
                refresh_token=result.refresh_token,
                expires_in=result.expires_in,
                skin_url=result.profile.skin_url,
                skin_variant=result.profile.skin_variant,
            )
            logger.info("账号 %s token 自动刷新成功", account.username)
            return self.get_by_uuid(account.uuid)
        except AuthError as e:
            logger.error("自动刷新 token 失败: %s", e)
            return None

    def clear(self) -> None:
        with self._rw_lock:
            self._accounts.clear()
            logger.info("所有账号已清空")
        self.save()

    @staticmethod
    def _encrypt(data: str) -> str:
        if not data:
            return ""
        data_bytes = data.encode("utf-8")
        encrypted = bytes(
            b ^ _ENCRYPTION_KEY[i % len(_ENCRYPTION_KEY)]
            for i, b in enumerate(data_bytes)
        )
        return base64.b64encode(encrypted).decode("ascii")

    @staticmethod
    def _decrypt(encrypted: str) -> str:
        if not encrypted:
            return ""
        try:
            encrypted_bytes = base64.b64decode(encrypted)
            decrypted = bytes(
                b ^ _ENCRYPTION_KEY[i % len(_ENCRYPTION_KEY)]
                for i, b in enumerate(encrypted_bytes)
            )
            return decrypted.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as e:
            logger.error("解密失败: %s", e)
            return ""

    @staticmethod
    def _encrypt_sensitive_fields(acc_dict: dict) -> dict:
        result = dict(acc_dict)
        if result.get("access_token"):
            result["access_token"] = AccountManager._encrypt(result["access_token"])
        if result.get("refresh_token"):
            result["refresh_token"] = AccountManager._encrypt(result["refresh_token"])
        return result

    @staticmethod
    def _decrypt_sensitive_fields(acc_dict: dict) -> dict:
        result = dict(acc_dict)
        if result.get("access_token"):
            result["access_token"] = AccountManager._decrypt(result["access_token"])
        if result.get("refresh_token"):
            result["refresh_token"] = AccountManager._decrypt(result["refresh_token"])
        return result
