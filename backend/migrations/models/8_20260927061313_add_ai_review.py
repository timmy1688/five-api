from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` ADD `ai_review` VARCHAR(32) NOT NULL DEFAULT '';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` DROP COLUMN `ai_review`;"""


MODELS_STATE = (
    "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"
)
