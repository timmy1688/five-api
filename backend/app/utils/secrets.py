"""Secret encryption helpers.

The database stores upstream credentials encrypted with SECRET_KEY. Existing plaintext channel keys are encrypted on startup.
"""

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken
from tortoise.exceptions import IntegrityError

from app.config import settings

PREFIX = "fernet:"
SECRET_SETTING_KEY = "app_secret"


async def load_secret_key() -> None:
    """Use the secret stored in the database, creating it on first startup.

    A SECRET_KEY setting is imported once, so upgrades from data/.secret_key
    keep their encrypted channel keys. Must run before anything encrypts,
    decrypts or signs.
    """
    from app.models import Channel, SystemSetting

    row = await SystemSetting.get_or_none(key=SECRET_SETTING_KEY)
    if row is not None:
        stored = row.value["secret"]
        if settings.SECRET_KEY and settings.SECRET_KEY != stored:
            raise RuntimeError(
                "SECRET_KEY differs from the secret stored in the database; remove the setting"
            )
        settings.SECRET_KEY = stored
        return

    value = settings.SECRET_KEY
    if not value:
        if await Channel.filter(api_key__startswith=PREFIX).exists():
            raise RuntimeError(
                "Channel keys are encrypted but no secret is stored; import data/.secret_key with "
                '`docker compose run --rm -e SECRET_KEY="$(cat data/.secret_key)" gateway python -m app.import_secret`'
            )
        value = secrets.token_urlsafe(48)
    try:
        await SystemSetting.create(key=SECRET_SETTING_KEY, value={"secret": value})
    except IntegrityError:
        row = await SystemSetting.get(key=SECRET_SETTING_KEY)
        value = row.value["secret"]
    settings.SECRET_KEY = value


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    token = _fernet().encrypt(value.encode()).decode()
    return f"{PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Unable to decrypt an upstream API key; the stored secret differs from the one that encrypted it"
        ) from exc


def split_keys(plain: str) -> list[str]:
    """One key per line. Commas also separate, since keys never contain them."""
    seen: list[str] = []
    for part in plain.replace(",", "\n").splitlines():
        key = part.strip()
        if key and key not in seen:
            seen.append(key)
    return seen


def channel_keys(value: str) -> list[str]:
    return split_keys(decrypt_secret(value))


def _mask_one(plain: str) -> str:
    if len(plain) <= 8:
        return "••••••••"
    return f"{plain[:4]}••••••••{plain[-4:]}"


def mask_secret(value: str) -> str:
    keys = channel_keys(value)
    if not keys:
        return ""
    if len(keys) == 1:
        return _mask_one(keys[0])
    return f"{_mask_one(keys[0])} (+{len(keys) - 1})"


async def encrypt_plaintext_channel_keys() -> int:
    """Encrypt legacy plaintext channel credentials in place."""
    from app.models import Channel

    changed = 0
    for channel in await Channel.all():
        if channel.api_key and not channel.api_key.startswith(PREFIX):
            channel.api_key = encrypt_secret(channel.api_key)
            await channel.save(update_fields=["api_key"])
            changed += 1
    return changed
