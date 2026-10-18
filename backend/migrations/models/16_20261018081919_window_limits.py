from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `api_keys` ADD `window_limits` JSON NOT NULL;
        ALTER TABLE `teams` ADD `window_limits` JSON NOT NULL;
        UPDATE `api_keys` SET `window_limits` = JSON_OBJECT();
        UPDATE `teams` SET `window_limits` = JSON_OBJECT();"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `teams` DROP COLUMN `window_limits`;
        ALTER TABLE `api_keys` DROP COLUMN `window_limits`;"""


MODELS_STATE = (
    "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"
    "mMUkw+nbL0IQcSAC5xaLV3XFvvwf36rjNg=="
)
