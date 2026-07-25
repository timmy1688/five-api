"""Secret encryption helpers.

The database stores upstream credentials encrypted with the application's
persistent secret. Existing plaintext channel keys are encrypted on startup.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

PREFIX = "fernet:"


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
            "Unable to decrypt an upstream API key; check data/.secret_key"
        ) from exc


def mask_secret(value: str) -> str:
    plain = decrypt_secret(value)
    if not plain:
        return ""
    if len(plain) <= 8:
        return "••••••••"
    return f"{plain[:4]}••••••••{plain[-4:]}"


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
