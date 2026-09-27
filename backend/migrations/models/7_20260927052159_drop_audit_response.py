from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_log_audits` DROP COLUMN `audit_response`;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_log_audits` ADD `audit_response` LONGTEXT NOT NULL DEFAULT ('');"""


MODELS_STATE = (
    "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"
    "REiTmjxK8aL3z+PzdlKkY="
)
