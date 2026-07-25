from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` ADD `failed_over` BOOL NOT NULL DEFAULT 0;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` DROP COLUMN `failed_over`;"""


MODELS_STATE = (
    "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"
)
