"""账号管理模块单元测试。"""

import tempfile
from pathlib import Path

import pytest

from src.core.account import AccountInfo, AccountManager


class TestAccountInfo:
    """AccountInfo 数据类测试。"""

    def test_create_offline_account(self):
        """测试创建离线账号。"""
        acc = AccountInfo(
            uuid="test-uuid",
            type="offline",
            username="TestPlayer",
        )
        assert acc.is_offline is True
        assert acc.is_microsoft is False
        assert acc.access_token is None
        assert acc.is_token_expired is False

    def test_create_microsoft_account(self):
        """测试创建正版账号。"""
        acc = AccountInfo(
            uuid="test-uuid-ms",
            type="microsoft",
            username="Steve",
            access_token="token123",
            refresh_token="refresh456",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        assert acc.is_microsoft is True
        assert acc.is_offline is False
        assert acc.is_token_expired is False

    def test_token_expired(self):
        """测试 token 过期检测。"""
        acc = AccountInfo(
            uuid="test",
            type="microsoft",
            username="Steve",
            access_token="token",
            expires_at="2020-01-01T00:00:00+00:00",
        )
        assert acc.is_token_expired is True

    def test_microsoft_no_expiry_is_expired(self):
        """测试正版账号无过期时间视为过期。"""
        acc = AccountInfo(
            uuid="test",
            type="microsoft",
            username="Steve",
            access_token="token",
        )
        assert acc.is_token_expired is True

    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化。"""
        acc = AccountInfo(
            uuid="test-uuid",
            type="microsoft",
            username="Steve",
            access_token="token",
            refresh_token="refresh",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        data = acc.to_dict()
        restored = AccountInfo.from_dict(data)
        assert restored.uuid == acc.uuid
        assert restored.username == acc.username
        assert restored.access_token == acc.access_token

    def test_is_selected_default(self):
        """测试 is_selected 默认为 False。"""
        acc = AccountInfo(uuid="test", type="offline", username="Player")
        assert acc.is_selected is False


class TestAccountManager:
    """账号管理器测试。"""

    @pytest.fixture
    def manager(self):
        """创建独立的 AccountManager 实例用于测试。"""
        # 重置单例
        AccountManager._instance = None
        mgr = AccountManager()
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr._accounts_path = Path(tmpdir) / "accounts.json"
            mgr._accounts = []
            yield mgr

    def test_add_offline_account(self, manager):
        """测试添加离线账号。"""
        acc = manager.add_offline_account("TestPlayer")
        assert acc is not None
        assert acc.type == "offline"
        assert acc.username == "TestPlayer"
        assert acc.is_offline is True

    def test_add_offline_account_duplicate(self, manager):
        """测试添加重复离线账号返回已有账号。"""
        acc1 = manager.add_offline_account("TestPlayer")
        acc2 = manager.add_offline_account("TestPlayer")
        assert acc1.uuid == acc2.uuid

    def test_add_offline_empty_username(self, manager):
        """测试空用户名抛出异常。"""
        with pytest.raises(ValueError, match="玩家名不能为空"):
            manager.add_offline_account("")

    def test_add_offline_username_too_long(self, manager):
        """测试用户名过长抛出异常。"""
        with pytest.raises(ValueError, match="不能超过 16 个字符"):
            manager.add_offline_account("a" * 20)

    def test_add_offline_invalid_chars(self, manager):
        """测试非法字符用户名抛出异常。"""
        with pytest.raises(ValueError, match="字母、数字和下划线"):
            manager.add_offline_account("Player@Name")

    def test_add_microsoft_account(self, manager):
        """测试添加正版账号。"""
        acc = manager.add_microsoft_account(
            username="Steve",
            access_token="acc_token",
            refresh_token="ref_token",
            expires_in=3600,
        )
        assert acc.type == "microsoft"
        assert acc.username == "Steve"
        assert acc.access_token == "acc_token"
        assert acc.refresh_token == "ref_token"

    def test_add_microsoft_replaces_old(self, manager):
        """测试添加正版账号会替换同名旧账号。"""
        manager.add_microsoft_account("Steve", "token1", "refresh1")
        manager.add_microsoft_account("Steve", "token2", "refresh2")
        all_accounts = manager.get_all()
        steve_accounts = [a for a in all_accounts if a.username == "Steve"]
        assert len(steve_accounts) == 1
        assert steve_accounts[0].access_token == "token2"

    def test_remove_account(self, manager):
        """测试删除账号。"""
        acc = manager.add_offline_account("Player1")
        assert manager.remove_account(acc.uuid) is True
        assert manager.get_by_uuid(acc.uuid) is None

    def test_remove_nonexistent_account(self, manager):
        """测试删除不存在的账号。"""
        assert manager.remove_account("nonexistent-uuid") is False

    def test_switch_account(self, manager):
        """测试切换账号。"""
        acc1 = manager.add_offline_account("Player1")
        acc2 = manager.add_offline_account("Player2")

        manager.switch_account(acc1.uuid)
        selected = manager.get_selected()
        assert selected is not None
        assert selected.uuid == acc1.uuid

        manager.switch_account(acc2.uuid)
        selected = manager.get_selected()
        assert selected is not None
        assert selected.uuid == acc2.uuid

    def test_switch_nonexistent_account(self, manager):
        """测试切换不存在的账号。"""
        assert manager.switch_account("nonexistent") is None

    def test_get_by_uuid(self, manager):
        """测试按 UUID 查找。"""
        acc = manager.add_offline_account("Player")
        found = manager.get_by_uuid(acc.uuid)
        assert found is not None
        assert found.username == "Player"

    def test_get_by_username(self, manager):
        """测试按用户名查找。"""
        manager.add_offline_account("Player")
        found = manager.get_by_username("Player")
        assert found is not None
        assert found.username == "Player"

    def test_get_all(self, manager):
        """测试获取所有账号。"""
        manager.add_offline_account("Player1")
        manager.add_offline_account("Player2")
        assert manager.get_count() == 2
        assert len(manager.get_all()) == 2

    def test_update_token(self, manager):
        """测试刷新 token。"""
        acc = manager.add_microsoft_account("Steve", "old_token", "old_refresh")
        assert manager.update_token(acc.uuid, "new_token", "new_refresh", 7200)
        updated = manager.get_by_uuid(acc.uuid)
        assert updated.access_token == "new_token"
        assert updated.refresh_token == "new_refresh"

    def test_update_token_nonexistent(self, manager):
        """测试刷新不存在的账号 token。"""
        assert manager.update_token("nonexistent", "t", "r") is False

    def test_save_and_load(self, manager):
        """测试保存和加载账号。"""
        acc1 = manager.add_offline_account("Player1")
        acc2 = manager.add_microsoft_account("Steve", "acc_token", "ref_token")
        manager.save()

        # 新实例加载
        AccountManager._instance = None
        mgr2 = AccountManager()
        mgr2._accounts_path = manager._accounts_path
        mgr2.load()

        assert mgr2.get_count() == 2
        loaded = mgr2.get_by_uuid(acc1.uuid)
        assert loaded is not None
        assert loaded.username == "Player1"

        loaded_ms = mgr2.get_by_uuid(acc2.uuid)
        assert loaded_ms is not None
        assert loaded_ms.access_token == "acc_token"

    def test_load_nonexistent_file(self, manager):
        """测试加载不存在的文件。"""
        manager._accounts_path = Path("/tmp/nonexistent_accounts.json")
        manager.load()
        assert manager.get_count() == 0

    def test_clear(self, manager):
        """测试清空所有账号。"""
        manager.add_offline_account("Player1")
        manager.add_offline_account("Player2")
        manager.clear()
        assert manager.get_count() == 0

    def test_encrypt_decrypt(self):
        """测试加密和解密。"""
        original = "my_secret_token_12345"
        encrypted = AccountManager._encrypt(original)
        assert encrypted != original
        assert encrypted != ""
        decrypted = AccountManager._decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_empty_string(self):
        """测试加密空字符串。"""
        assert AccountManager._encrypt("") == ""
        assert AccountManager._decrypt("") == ""

    def test_encrypt_sensitive_fields(self):
        """测试加密字典中的敏感字段。"""
        acc_dict = {
            "access_token": "secret_token",
            "refresh_token": "secret_refresh",
            "username": "Player",
        }
        encrypted = AccountManager._encrypt_sensitive_fields(acc_dict)
        assert encrypted["access_token"] != "secret_token"
        assert encrypted["refresh_token"] != "secret_refresh"
        assert encrypted["username"] == "Player"

        decrypted = AccountManager._decrypt_sensitive_fields(encrypted)
        assert decrypted["access_token"] == "secret_token"
        assert decrypted["refresh_token"] == "secret_refresh"