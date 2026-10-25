from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `model_probes` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channel_id` INT NOT NULL,
    `model` VARCHAR(64) NOT NULL,
    `actual_model` VARCHAR(64) NOT NULL,
    `kind` VARCHAR(16) NOT NULL,
    `status` VARCHAR(16) NOT NULL,
    `suite_version` VARCHAR(32) NOT NULL,
    `latency_ms` INT NOT NULL,
    `score` INT,
    `checks` JSON NOT NULL,
    `error` VARCHAR(512) NOT NULL,
    `actor_id` INT NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    KEY `idx_model_probe_channel_9737f1` (`channel_id`),
    KEY `idx_model_probe_channel_77d504` (`channel_id`, `model`, `kind`, `created_at`)
) CHARACTER SET utf8mb4;
        ALTER TABLE `channels` ADD `cost_multiplier` DECIMAL(8,4) NOT NULL DEFAULT 1;
        ALTER TABLE `model_prices` ADD `multiplier` DECIMAL(8,4) NOT NULL DEFAULT 1;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `channels` DROP COLUMN `cost_multiplier`;
        ALTER TABLE `model_prices` DROP COLUMN `multiplier`;
        DROP TABLE IF EXISTS `model_probes`;"""


MODELS_STATE = (
    "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"
    "iKSZnPkGntX08OP/dGeUng=="
)
