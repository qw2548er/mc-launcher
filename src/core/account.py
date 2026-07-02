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
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 账号数据文件路径
DEFAULT_ACCOUNTS_PATH = Path("config/accounts.json")

# 加密密钥（简单混淆，生产环境应使用更安全的方案）
_ENCRYPTION_KEY: bytes = hashlib.sha256(b"minecraft-launcher-salt").digest()


@dataclass
class AccountInfo:
    """账号信息数据类。"""

    uuid: str  # 账号唯一标识
    type: str  # 账号类型: "microsoft" 或 "offline"
    username: str  # 玩家名
    access_token: Optional[str] = None  # 正版 access token
    refresh_token: Optional[str] = None  # 正版 refresh token
    expires_at: Optional[str] = None  # token 过期时间 (ISO 8601)
    is_selected: bool = False  # 是否为当前选中账号

    @property
    def is_offline(self) -> bool:
        return self.type == "offline"

    @property
    def is_microsoft(self) -> bool:
        return self.type == "microsoft"

    @property
    def is_token_expired(self) -> bool:
        """检查 access token 是否已过期。"""
        if self.expires_at is None:
            return self.is_microsoft
        try:
            expire_time = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > expire_time
        except (ValueError, TypeError):
            return True

    def to_dict(self) -> dict:
        """转换为字典（用于序列化）。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AccountInfo":
        """从字典创建实例。"""
        return cls(**data)


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

    # ── 文件操作 ──────────────────────────────────────────────

    def load(self, accounts_path: Optional[Path] = None) -> None:
        """从文件加载账号数据。

        Args:
            accounts_path: 账号文件路径
        """
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

                for acc_data in accounts_data:
                    # 解密敏感字段
                    acc_data = self._decrypt_sensitive_fields(acc_data)
                    self._accounts.append(AccountInfo.from_dict(acc_data))

                logger.info("已加载 %d 个账号", len(self._accounts))
            except (json.JSONDecodeError, OSError, KeyError) as e:
                logger.error("加载账号文件失败: %s", e)
                self._accounts = []

    def save(self) -> None:
        """保存账号数据到文件。"""
        with self._rw_lock:
            try:
                self._accounts_path.parent.mkdir(parents=True, exist_ok=True)

                accounts_data = []
                for acc in self._accounts:
                    acc_dict = acc.to_dict()
                    # 加密敏感字段
                    acc_dict = self._encrypt_sensitive_fields(acc_dict)
                    accounts_data.append(acc_dict)

                data = {
                    "accounts": accounts_data,
                    "selected_account": self.get_selected().uuid if self.get_selected() else "",
                }

                with open(self._accounts_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.debug("账号数据已保存: %d 个账号", len(self._accounts))
            except OSError as e:
                logger.error("保存账号文件失败: %s", e)

    # ── 账号管理 ──────────────────────────────────────────────

    def add_offline_account(self, username: str) -> AccountInfo:
        """添加离线模式账号。

        Args:
            username: 玩家名

        Returns:
            创建的 AccountInfo

        Raises:
            ValueError: 用户名为空
        """
        username = username.strip()
        if not username:
            raise ValueError("玩家名不能为空")
        if len(username) > 16:
            raise ValueError("玩家名不能超过 16 个字符")
        if not username.replace("_", "").isalnum():
            raise ValueError("玩家名只能包含字母、数字和下划线")

        # 检查是否已存在同名离线账号
        existing = self.get_by_username(username)
        if existing and existing.is_offline:
            logger.info("离线账号 %s 已存在，返回已有账号", username)
            return existing

        # 基于用户名生成 UUID（使用 UUID v3）
        account_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"offline:{username}"))

        account = AccountInfo(
            uuid=account_uuid,
            type="offline",
            username=username,
        )

        with self._rw_lock:
            self._accounts.append(account)
            logger.info("添加离线账号: %s (UUID: %s)", username, account_uuid)

        self.save()
        return account

    def add_microsoft_account(
        self,
        username: str,
        access_token: str,
        refresh_token: str,
        expires_in: int = 3600,
    ) -> AccountInfo:
        """添加 Microsoft 正版账号。

        Args:
            username: 玩家名
            access_token: 访问令牌
            refresh_token: 刷新令牌
            expires_in: token 有效期（秒）

        Returns:
            创建的 AccountInfo
        """
        # 计算过期时间
        expire_time = datetime.now(timezone.utc).timestamp() + expires_in
        expires_at = datetime.fromtimestamp(expire_time, tz=timezone.utc).isoformat()

        account_uuid = str(uuid.uuid4())

        account = AccountInfo(
            uuid=account_uuid,
            type="microsoft",
            username=username,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )

        with self._rw_lock:
            # 移除同名的旧正版账号
            self._accounts = [
                a for a in self._accounts
                if not (a.is_microsoft and a.username == username)
            ]
            self._accounts.append(account)
            logger.info("添加正版账号: %s (UUID: %s)", username, account_uuid)

        self.save()
        return account

    def remove_account(self, account_uuid: str) -> bool:
        """删除指定账号。

        Args:
            account_uuid: 账号 UUID

        Returns:
            True 表示删除成功
        """
        with self._rw_lock:
            for i, acc in enumerate(self._accounts):
                if acc.uuid == account_uuid:
                    removed = self._accounts.pop(i)
                    logger.info("删除账号: %s (%s)", removed.username, removed.type)
                    self.save()
                    return True

        logger.warning("未找到要删除的账号: %s", account_uuid)
        return False

    def switch_account(self, account_uuid: str) -> Optional[AccountInfo]:
        """切换到指定账号。

        Args:
            account_uuid: 账号 UUID

        Returns:
            切换后的 AccountInfo，如果未找到返回 None
        """
        with self._rw_lock:
            found = False
            for acc in self._accounts:
                if acc.uuid == account_uuid:
                    acc.is_selected = True
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
        """获取当前选中的账号。"""
        with self._rw_lock:
            for acc in self._accounts:
                if acc.is_selected:
                    return acc
        return None

    def get_by_uuid(self, account_uuid: str) -> Optional[AccountInfo]:
        """根据 UUID 获取账号。"""
        with self._rw_lock:
            for acc in self._accounts:
                if acc.uuid == account_uuid:
                    return acc
        return None

    def get_by_username(self, username: str) -> Optional[AccountInfo]:
        """根据用户名获取账号。"""
        with self._rw_lock:
            for acc in self._accounts:
                if acc.username == username:
                    return acc
        return None

    def get_all(self) -> list[AccountInfo]:
        """获取所有账号列表。"""
        with self._rw_lock:
            return list(self._accounts)

    def get_count(self) -> int:
        """获取账号数量。"""
        with self._rw_lock:
            return len(self._accounts)

    def update_token(
        self,
        account_uuid: str,
        access_token: str,
        refresh_token: str,
        expires_in: int = 3600,
    ) -> bool:
        """刷新账号 token。

        Args:
            account_uuid: 账号 UUID
            access_token: 新的访问令牌
            refresh_token: 新的刷新令牌
            expires_in: 有效期（秒）

        Returns:
            True 表示更新成功
        """
        with self._rw_lock:
            acc = self.get_by_uuid(account_uuid)
            if acc is None:
                logger.warning("刷新 token 失败，未找到账号: %s", account_uuid)
                return False

            expire_time = datetime.now(timezone.utc).timestamp() + expires_in
            acc.access_token = access_token
            acc.refresh_token = refresh_token
            acc.expires_at = datetime.fromtimestamp(
                expire_time, tz=timezone.utc
            ).isoformat()
            self.save()
            logger.info("Token 已刷新: %s", acc.username)
            return True

    def clear(self) -> None:
        """清空所有账号。"""
        with self._rw_lock:
            self._accounts.clear()
            logger.info("所有账号已清空")
        self.save()

    # ── 加密/解密 ──────────────────────────────────────────────

    @staticmethod
    def _encrypt(data: str) -> str:
        """简单 XOR 加密 + Base64 编码。"""
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
        """Base64 解码 + XOR 解密。"""
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
        """加密账号字典中的敏感字段。"""
        result = dict(acc_dict)
        if result.get("access_token"):
            result["access_token"] = AccountManager._encrypt(result["access_token"])
        if result.get("refresh_token"):
            result["refresh_token"] = AccountManager._encrypt(result["refresh_token"])
        return result

    @staticmethod
    def _decrypt_sensitive_fields(acc_dict: dict) -> dict:
        """解密账号字典中的敏感字段。"""
        result = dict(acc_dict)
        if result.get("access_token"):
            result["access_token"] = AccountManager._decrypt(result["access_token"])
        if result.get("refresh_token"):
            result["refresh_token"] = AccountManager._decrypt(result["refresh_token"])
        return result