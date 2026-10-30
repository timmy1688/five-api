from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    # The old cost_multiplier and model_pricing were upstream costs, so they are dropped, never renamed.
    # The model multiplier is folded into the unit prices first so every customer charge stays the same.
    return """
        UPDATE `model_prices` SET
            `prompt_price` = ROUND(`prompt_price` * `multiplier`, 6),
            `completion_price` = ROUND(`completion_price` * `multiplier`, 6),
            `cached_price` = ROUND(`cached_price` * `multiplier`, 6),
            `cache_write_price` = ROUND(`cache_write_price` * `multiplier`, 6),
            `request_price` = ROUND(`request_price` * `multiplier`, 6)
        WHERE `multiplier` <> 1;
        ALTER TABLE `model_prices` DROP COLUMN `multiplier`;
        ALTER TABLE `api_keys` ADD `channel_ids` JSON NOT NULL;
        UPDATE `api_keys` SET `channel_ids` = JSON_ARRAY();
        ALTER TABLE `channels` ADD `price_multiplier` DECIMAL(8,4) NOT NULL DEFAULT 1;
        ALTER TABLE `channels` ADD `price_overrides` JSON NOT NULL;
        UPDATE `channels` SET `price_overrides` = JSON_OBJECT();
        ALTER TABLE `channels` DROP COLUMN `model_pricing`;
        ALTER TABLE `channels` DROP COLUMN `cost_multiplier`;
        ALTER TABLE `request_logs` DROP COLUMN `upstream_cost`;
        ALTER TABLE `usage_daily` DROP COLUMN `upstream_cost`;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # Upstream costs and the split between base price and multiplier cannot be recovered; prices keep
    # their folded values with multiplier 1. Channel price multipliers, overrides and key bindings are lost.
    return """
        ALTER TABLE `api_keys` DROP COLUMN `channel_ids`;
        ALTER TABLE `channels` ADD `model_pricing` JSON NOT NULL;
        UPDATE `channels` SET `model_pricing` = JSON_OBJECT();
        ALTER TABLE `channels` ADD `cost_multiplier` DECIMAL(8,4) NOT NULL DEFAULT 1;
        ALTER TABLE `channels` DROP COLUMN `price_multiplier`;
        ALTER TABLE `channels` DROP COLUMN `price_overrides`;
        ALTER TABLE `model_prices` ADD `multiplier` DECIMAL(8,4) NOT NULL DEFAULT 1;
        ALTER TABLE `request_logs` ADD `upstream_cost` DECIMAL(16,6) NOT NULL DEFAULT 0;
        ALTER TABLE `usage_daily` ADD `upstream_cost` DECIMAL(18,6) NOT NULL DEFAULT 0;"""


MODELS_STATE = (
    "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"
)
