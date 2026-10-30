"""External secrets and authenticated encryption for upstream credentials."""
import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

PREFIX = "fernet:"
SECRET_SETTING_KEY = "app_secret"
# Public fallback for stateless containers; it hides keys from casual reads but not from anyone with the source.
DEFAULT_ENCRYPTION_KEY = "five-api-default-upstream-encryption-key"


def cipher(secret: str) -> Fernet:
    if len(secret) < 32:
        raise RuntimeError("Encryption key must contain at least 32 characters")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def read_external() -> dict | None:
    if not settings.SECRETS_FILE:
        return None
    path = Path(settings.SECRETS_FILE)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text())
        if not all(isinstance(value.get(name), str) and len(value[name]) >= 32
                   for name in ("jwt_secret", "encryption_key")):
            raise ValueError("Invalid secret lengths")
        if value["jwt_secret"] == value["encryption_key"]:
            raise ValueError("Signing and encryption secrets must differ")
        return value
    except (OSError, ValueError) as exc:
        raise RuntimeError("External secrets file is invalid; restore it instead of replacing encrypted data") from exc


def create_external(jwt_secret: str = "", encryption_key: str = "") -> dict:
    path = Path(settings.SECRETS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {"jwt_secret": jwt_secret or secrets.token_urlsafe(48),
              "encryption_key": encryption_key or secrets.token_urlsafe(48)}
    if values["jwt_secret"] == values["encryption_key"]:
        raise RuntimeError("Signing and encryption secrets must differ")
    # O_EXCL prevents overwriting an existing master key. A partial write is detected at load time.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(values, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Keep the file for explicit repair; never generate a different key over it.
        raise
    return values


def encrypted_values(value):
    if isinstance(value, str) and value.startswith(PREFIX):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from encrypted_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from encrypted_values(item)


async def load_secret_key() -> None:
    from app.models import Channel, SystemSetting
    if await SystemSetting.exists(key=SECRET_SETTING_KEY):
        raise RuntimeError("Legacy same-database secret found; run python -m app.migrate_secrets")
    if not settings.SECRETS_FILE:
        # Stateless container: a per-start signing key means logging in again after a restart.
        settings.SECRET_KEY = settings.SECRET_KEY or secrets.token_urlsafe(48)
        settings.ENCRYPTION_KEY = settings.ENCRYPTION_KEY or DEFAULT_ENCRYPTION_KEY
        if settings.SECRET_KEY == settings.ENCRYPTION_KEY:
            raise RuntimeError("Signing and encryption secrets must differ")
        await verify_stored_ciphertexts()
        return
    external = read_external()
    if settings.SECRET_KEY and settings.ENCRYPTION_KEY:
        if settings.SECRET_KEY == settings.ENCRYPTION_KEY:
            raise RuntimeError("Signing and encryption secrets must differ")
        pair = {"jwt_secret": settings.SECRET_KEY, "encryption_key": settings.ENCRYPTION_KEY}
        if external and pair != external:
            raise RuntimeError("Environment secrets differ from the external secrets file")
        external = pair
    elif external:
        if settings.SECRET_KEY and settings.SECRET_KEY != external["jwt_secret"]:
            raise RuntimeError("JWT signing secret differs from the external secrets file")
        if settings.ENCRYPTION_KEY and settings.ENCRYPTION_KEY != external["encryption_key"]:
            raise RuntimeError("Encryption key differs from the external secrets file")
    else:
        ciphertexts = [channel.api_key for channel in await Channel.all() if channel.api_key.startswith(PREFIX)]
        ciphertexts += [item for row in await SystemSetting.all() for item in encrypted_values(row.value)]
        if ciphertexts:
            raise RuntimeError("External encryption key missing; restore it or run python -m app.migrate_secrets --legacy-secret-file PATH")
        external = create_external(settings.SECRET_KEY, settings.ENCRYPTION_KEY)
    settings.SECRET_KEY = external["jwt_secret"]
    settings.ENCRYPTION_KEY = external["encryption_key"]
    await verify_stored_ciphertexts()


async def verify_stored_ciphertexts() -> None:
    from app.models import Channel, SystemSetting
    try:
        for channel in await Channel.all():
            if channel.api_key.startswith(PREFIX):
                decrypt_secret(channel.api_key)
        for row in await SystemSetting.all():
            for value in encrypted_values(row.value):
                decrypt_secret(value)
    except ValueError as exc:
        raise RuntimeError("Encryption key cannot decrypt stored credentials; restore the previous key or run "
                           "python -m app.migrate_secrets; startup refused") from exc


def _fernet() -> Fernet:
    return cipher(settings.ENCRYPTION_KEY)


def encrypt_secret(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt an upstream credential; restore the matching external master key") from exc


def split_keys(plain: str) -> list[str]:
    seen = []
    for part in plain.replace(",", "\n").splitlines():
        key = part.strip()
        if key and key not in seen:
            seen.append(key)
    return seen


def channel_keys(value: str) -> list[str]:
    from app.services.request_context import remember_credential
    keys = split_keys(decrypt_secret(value))
    for key in keys:
        remember_credential(key)
    return keys


def _mask_one(plain: str) -> str:
    return "••••••••" if len(plain) <= 8 else f"{plain[:4]}••••••••{plain[-4:]}"


def mask_secret(value: str) -> str:
    keys = channel_keys(value)
    return "" if not keys else _mask_one(keys[0]) if len(keys) == 1 else f"{_mask_one(keys[0])} (+{len(keys) - 1})"


async def encrypt_plaintext_channel_keys() -> int:
    from app.models import Channel
    changed = 0
    for channel in await Channel.all():
        if channel.api_key and not channel.api_key.startswith(PREFIX):
            channel.api_key = encrypt_secret(channel.api_key)
            await channel.save(update_fields=["api_key"])
            changed += 1
    return changed
