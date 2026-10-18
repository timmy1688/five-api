import pytest

from app.config import settings
from app.models import Channel, SystemSetting
from app.utils import secrets as secret_utils
from app.utils.secrets import SECRET_SETTING_KEY, decrypt_secret, encrypt_secret, load_secret_key


@pytest.fixture
def configured(monkeypatch):
    def set_value(value: str):
        monkeypatch.setattr(settings, "SECRET_KEY", value)
    return set_value


async def test_generates_and_reuses_stored_secret(configured):
    configured("")
    await load_secret_key()
    first = settings.SECRET_KEY
    assert len(first) >= 32
    assert (await SystemSetting.get(key=SECRET_SETTING_KEY)).value == {"secret": first}

    configured("")
    await load_secret_key()
    assert settings.SECRET_KEY == first


async def test_imports_configured_secret(configured):
    legacy = "legacy-secret-from-data-dir-0123456789abcdef"
    configured(legacy)
    encrypted = encrypt_secret("sk-upstream")

    await load_secret_key()
    configured("")
    await load_secret_key()

    assert settings.SECRET_KEY == legacy
    assert decrypt_secret(encrypted) == "sk-upstream"


async def test_rejects_secret_that_differs_from_stored(configured):
    await SystemSetting.create(key=SECRET_SETTING_KEY, value={"secret": "stored-secret-0123456789abcdef0123456789"})
    configured("another-secret-0123456789abcdef0123456789")
    with pytest.raises(RuntimeError, match="differs"):
        await load_secret_key()


async def test_refuses_to_generate_when_channel_keys_are_encrypted(configured):
    await Channel.create(
        name="legacy", provider="openai", base_url="https://example.com",
        api_key=f"{secret_utils.PREFIX}gAAAA-old-ciphertext", models=["m"],
    )
    configured("")
    with pytest.raises(RuntimeError, match="data/.secret_key"):
        await load_secret_key()
    assert not await SystemSetting.exists(key=SECRET_SETTING_KEY)
