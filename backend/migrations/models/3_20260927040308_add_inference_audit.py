from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `api_keys` ADD `audit_enabled` BOOL NOT NULL DEFAULT 0;
        ALTER TABLE `request_logs` ADD `audit_request` LONGTEXT NOT NULL;
        ALTER TABLE `request_logs` ADD `audit_response` LONGTEXT NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `api_keys` DROP COLUMN `audit_enabled`;
        ALTER TABLE `request_logs` DROP COLUMN `audit_request`;
        ALTER TABLE `request_logs` DROP COLUMN `audit_response`;"""


MODELS_STATE = (
    "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"
)
