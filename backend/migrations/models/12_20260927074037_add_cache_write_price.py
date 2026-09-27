from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `model_prices` ADD `cache_write_price` DECIMAL(16,6) NOT NULL DEFAULT 0;
        UPDATE `model_prices` SET `cache_write_price` = `prompt_price`;
        ALTER TABLE `request_logs` ADD `cache_write_tokens` INT NOT NULL DEFAULT 0;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `model_prices` DROP COLUMN `cache_write_price`;
        ALTER TABLE `request_logs` DROP COLUMN `cache_write_tokens`;"""


MODELS_STATE = (
    "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"
)
