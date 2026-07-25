from importlib import import_module

from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True
MODELS_STATE = import_module(
    "migrations.models.0_20260725135116_init"
).MODELS_STATE


async def _columns(db: BaseDBAsyncClient, table: str) -> set[str]:
    rows = await db.execute_query_dict(f"SHOW COLUMNS FROM `{table}`")
    return {row["Field"] for row in rows}


async def upgrade(db: BaseDBAsyncClient) -> str:
    api_key_columns = await _columns(db, "api_keys")
    channel_columns = await _columns(db, "channels")
    statements = []
    for column in ("key_raw", "channel_group"):
        if column in api_key_columns:
            statements.append(f"ALTER TABLE `api_keys` DROP COLUMN `{column}`;")
    if "group" in channel_columns:
        statements.append("ALTER TABLE `channels` DROP COLUMN `group`;")
    return "\n".join(statements)


async def downgrade(db: BaseDBAsyncClient) -> str:
    api_key_columns = await _columns(db, "api_keys")
    channel_columns = await _columns(db, "channels")
    statements = []
    if "key_raw" not in api_key_columns:
        statements.append(
            "ALTER TABLE `api_keys` ADD COLUMN `key_raw` VARCHAR(128) NOT NULL DEFAULT '';"
        )
    if "channel_group" not in api_key_columns:
        statements.append(
            "ALTER TABLE `api_keys` ADD COLUMN `channel_group` VARCHAR(64) NOT NULL DEFAULT '';"
        )
    if "group" not in channel_columns:
        statements.append(
            "ALTER TABLE `channels` ADD COLUMN `group` VARCHAR(64) NOT NULL DEFAULT '';"
        )
    return "\n".join(statements)
