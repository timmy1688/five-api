"""Move legacy encrypted credentials to independent external secrets, without printing them."""
import argparse
import asyncio
import secrets
from pathlib import Path

from tortoise import Tortoise
from tortoise.transactions import in_transaction

from app.config import TORTOISE_ORM, settings
from app.models import Channel, ManagementEvent, SystemSetting
from app.utils.secrets import (
    DEFAULT_ENCRYPTION_KEY, PREFIX, SECRET_SETTING_KEY, cipher, create_external, read_external, load_secret_key,
)
from uuid import uuid4


async def migrate(legacy_secret_file: str | None = None, from_default: bool = False):
    legacy = await SystemSetting.get_or_none(key=SECRET_SETTING_KEY)
    previous = legacy.value["secret"] if legacy else ""
    if not previous and legacy_secret_file:
        previous = Path(legacy_secret_file).read_text().strip()
    if not previous and from_default:
        if not settings.ENCRYPTION_KEY or settings.ENCRYPTION_KEY == DEFAULT_ENCRYPTION_KEY:
            raise RuntimeError("Set a new ENCRYPTION_KEY before re-encrypting from the default key")
        previous = DEFAULT_ENCRYPTION_KEY
    if not previous:
        await load_secret_key()
        return {"channels": 0, "settings": 0}
    if settings.SECRET_KEY == previous:
        raise RuntimeError("Remove the legacy SECRET_KEY setting or supply a new JWT signing secret before migration")
    external = read_external()
    if external is None:
        if not settings.SECRETS_FILE:
            external = {"jwt_secret": settings.SECRET_KEY or secrets.token_urlsafe(48),
                        "encryption_key": settings.ENCRYPTION_KEY or DEFAULT_ENCRYPTION_KEY}
        elif settings.SECRET_KEY and settings.ENCRYPTION_KEY:
            external = {"jwt_secret": settings.SECRET_KEY, "encryption_key": settings.ENCRYPTION_KEY}
        else:
            external = create_external(settings.SECRET_KEY, settings.ENCRYPTION_KEY)
    old, new = cipher(previous), cipher(external["encryption_key"])

    def rewrap(value):
        if isinstance(value, str) and value.startswith(PREFIX):
            plain = old.decrypt(value[len(PREFIX):].encode())
            return PREFIX + new.encrypt(plain).decode()
        if isinstance(value, dict):
            return {key: rewrap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrap(item) for item in value]
        return value

    counts = {"channels": 0, "settings": 0}
    async with in_transaction():
        for channel in await Channel.all().select_for_update():
            if channel.api_key:
                value = rewrap(channel.api_key) if channel.api_key.startswith(PREFIX) else PREFIX + new.encrypt(channel.api_key.encode()).decode()
                await Channel.filter(id=channel.id).update(api_key=value)
                counts["channels"] += 1
        for row in await SystemSetting.exclude(key=SECRET_SETTING_KEY).select_for_update():
            value = rewrap(row.value)
            if value != row.value:
                await SystemSetting.filter(id=row.id).update(value=value)
                counts["settings"] += 1
        await SystemSetting.filter(key=SECRET_SETTING_KEY).delete()
        await ManagementEvent.create(operation_id=str(uuid4()), actor_id=0, tenant_id=0,
                                     action="secrets.externalize", target_id=0, detail=counts)
    settings.SECRET_KEY = external["jwt_secret"]
    settings.ENCRYPTION_KEY = external["encryption_key"]
    await load_secret_key()
    return counts


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-secret-file", help="Only for installations using the old data/.secret_key file")
    parser.add_argument("--from-default", action="store_true",
                        help="Re-encrypt credentials saved under the built-in container key with ENCRYPTION_KEY")
    args = parser.parse_args()
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        result = await migrate(args.legacy_secret_file, args.from_default)
        print(f"External secrets ready; migrated channels={result['channels']}, settings={result['settings']}. Legacy database root removed.")
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
