from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `api_keys` ADD `audit_policy` VARCHAR(16) NOT NULL DEFAULT 'gateway';
        UPDATE `api_keys` SET `audit_policy` = 'record' WHERE `audit_enabled` = 1;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `api_keys` DROP COLUMN `audit_policy`;"""


MODELS_STATE = (
    "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"
    "EfM="
)
