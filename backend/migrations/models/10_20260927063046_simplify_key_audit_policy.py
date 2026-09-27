from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        UPDATE `api_keys` SET `audit_policy` = 'on' WHERE `audit_policy` IN ('gateway', 'record');
        ALTER TABLE `api_keys` ALTER COLUMN `audit_policy` SET DEFAULT 'on';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `api_keys` ALTER COLUMN `audit_policy` SET DEFAULT 'gateway';"""


MODELS_STATE = (
    "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"
)
