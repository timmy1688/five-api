import json
import os

import pytest
from cryptography.fernet import InvalidToken

from app.config import settings
from app.models import Channel, SystemSetting
from app.migrate_secrets import migrate
from app.utils.secrets import (
    DEFAULT_ENCRYPTION_KEY, PREFIX, SECRET_SETTING_KEY, cipher, create_external, decrypt_secret,
    encrypt_secret, load_secret_key,
)


@pytest.fixture
def configured(monkeypatch, tmp_path):
    path = tmp_path / "secrets.json"
    monkeypatch.setattr(settings, "SECRETS_FILE", str(path))
    monkeypatch.setattr(settings, "SECRET_KEY", "")
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "")
    return path


async def test_generates_and_reuses_external_separate_secrets(configured):
    await load_secret_key()
    first = json.loads(configured.read_text())
    assert first["jwt_secret"] != first["encryption_key"]
    assert len(first["jwt_secret"]) >= 32
    assert os.stat(configured).st_mode & 0o777 == 0o600
    assert not await SystemSetting.exists(key=SECRET_SETTING_KEY)
    settings.SECRET_KEY = settings.ENCRYPTION_KEY = ""
    await load_secret_key()
    assert settings.SECRET_KEY == first["jwt_secret"]
    assert settings.ENCRYPTION_KEY == first["encryption_key"]


async def test_accepts_independent_environment_secrets_without_database_copy(configured):
    settings.SECRET_KEY = "jwt-signing-secret-value-0123456789abcdef"
    settings.ENCRYPTION_KEY = "upstream-encryption-secret-0123456789abcdef"
    await load_secret_key()
    assert not configured.exists()
    assert not await SystemSetting.exists(key=SECRET_SETTING_KEY)


async def test_refuses_to_generate_over_ciphertext_without_external_key(configured):
    await Channel.create(name="legacy", provider="openai", base_url="https://example.test",
                         api_key=PREFIX + "old-ciphertext", models=["m"])
    with pytest.raises(RuntimeError, match="missing"):
        await load_secret_key()
    assert not configured.exists()


async def test_rejects_environment_file_mismatch_without_overwriting(configured):
    create_external()
    previous = configured.read_bytes()
    settings.SECRET_KEY = "different-jwt-secret-0123456789abcdef0123"
    with pytest.raises(RuntimeError, match="differs"):
        await load_secret_key()
    assert configured.read_bytes() == previous


async def test_wrong_external_master_refuses_startup(configured):
    await load_secret_key()
    wrong = cipher("old-encryption-master-0123456789abcdef")
    await Channel.create(name="old", provider="openai", base_url="https://example.test",
                         api_key=PREFIX + wrong.encrypt(b"old-upstream").decode(), models=["m"])
    original = configured.read_bytes()
    with pytest.raises(RuntimeError, match="cannot decrypt"):
        await load_secret_key()
    assert configured.read_bytes() == original


async def test_migrates_legacy_channel_and_encrypted_settings_atomically(configured):
    legacy = "legacy-database-root-0123456789abcdef0123"
    old = cipher(legacy)
    await SystemSetting.create(key=SECRET_SETTING_KEY, value={"secret": legacy})
    await Channel.create(name="old", provider="openai", base_url="https://example.test",
                         api_key=PREFIX + old.encrypt(b"upstream-private-key").decode(), models=["m"])
    await SystemSetting.create(key="alerts", value={"hooks": [{"url": PREFIX + old.encrypt(b"https://example.test/hook").decode()}]})
    with pytest.raises(RuntimeError, match="migrate_secrets"):
        await load_secret_key()
    counts = await migrate()
    assert counts == {"channels": 1, "settings": 1}
    assert decrypt_secret((await Channel.get()).api_key) == "upstream-private-key"
    hook = (await SystemSetting.get(key="alerts")).value["hooks"][0]["url"]
    assert decrypt_secret(hook) == "https://example.test/hook"
    assert not await SystemSetting.exists(key=SECRET_SETTING_KEY)
    assert legacy not in json.dumps(await SystemSetting.all().values("value"))
    first = configured.read_bytes()
    assert await migrate() == {"channels": 0, "settings": 0}
    assert configured.read_bytes() == first


async def test_failed_migration_retains_old_data_and_reuses_external_file_on_retry(configured):
    legacy = "legacy-database-root-0123456789abcdef0123"
    await SystemSetting.create(key=SECRET_SETTING_KEY, value={"secret": legacy})
    channel = await Channel.create(name="broken", provider="openai", base_url="https://example.test",
                                    api_key=PREFIX + "invalid", models=["m"])
    with pytest.raises(InvalidToken):
        await migrate()
    assert await SystemSetting.exists(key=SECRET_SETTING_KEY)
    assert (await Channel.get(id=channel.id)).api_key == PREFIX + "invalid"
    first = configured.read_bytes()
    await Channel.filter(id=channel.id).update(api_key=PREFIX + cipher(legacy).encrypt(b"repaired").decode())
    await migrate()
    assert configured.read_bytes() == first
    assert decrypt_secret((await Channel.get()).api_key) == "repaired"


async def test_legacy_file_migration(configured, tmp_path):
    old_root = "old-file-key-0123456789abcdef0123456789"
    legacy_file = tmp_path / ".secret_key"
    legacy_file.write_text(old_root)
    await Channel.create(name="old-file", provider="openai", base_url="https://example.test",
                         api_key=PREFIX + cipher(old_root).encrypt(b"old-file-upstream").decode(), models=["m"])
    await migrate(str(legacy_file))
    assert decrypt_secret((await Channel.get()).api_key) == "old-file-upstream"


async def test_stateless_container_uses_per_start_signing_key_and_default_encryption(configured, monkeypatch):
    monkeypatch.setattr(settings, "SECRETS_FILE", "")
    await load_secret_key()
    first_signing = settings.SECRET_KEY
    assert len(first_signing) >= 32
    assert settings.ENCRYPTION_KEY == DEFAULT_ENCRYPTION_KEY
    await Channel.create(name="c", provider="openai", base_url="https://example.test",
                         api_key=encrypt_secret("upstream-key"), models=["m"])
    settings.SECRET_KEY = settings.ENCRYPTION_KEY = ""
    await load_secret_key()
    assert settings.SECRET_KEY != first_signing
    assert decrypt_secret((await Channel.get()).api_key) == "upstream-key"
    assert not configured.exists()


async def test_custom_container_key_reencrypts_from_default(configured, monkeypatch):
    monkeypatch.setattr(settings, "SECRETS_FILE", "")
    await load_secret_key()
    await Channel.create(name="c", provider="openai", base_url="https://example.test",
                         api_key=encrypt_secret("upstream-key"), models=["m"])
    settings.SECRET_KEY = ""
    settings.ENCRYPTION_KEY = "operator-chosen-encryption-key-0123456789"
    with pytest.raises(RuntimeError, match="cannot decrypt"):
        await load_secret_key()
    assert await migrate(from_default=True) == {"channels": 1, "settings": 0}
    assert settings.ENCRYPTION_KEY == "operator-chosen-encryption-key-0123456789"
    assert decrypt_secret((await Channel.get()).api_key) == "upstream-key"
    assert not configured.exists()


async def test_same_signing_and_encryption_keys_are_rejected(configured):
    settings.SECRET_KEY = settings.ENCRYPTION_KEY = "same-secret-0123456789abcdef0123456789"
    with pytest.raises(RuntimeError, match="must differ"):
        await load_secret_key()
