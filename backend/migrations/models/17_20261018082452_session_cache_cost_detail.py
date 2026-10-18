from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` ADD `cache_savings` DECIMAL(16,6) NOT NULL DEFAULT 0;
        ALTER TABLE `request_logs` ADD `cost_detail` JSON;
        ALTER TABLE `request_logs` ADD `session_id` VARCHAR(32) NOT NULL DEFAULT '';
        ALTER TABLE `usage_daily` ADD `cache_savings` DECIMAL(18,6) NOT NULL DEFAULT 0;
        ALTER TABLE `usage_daily` ADD `cache_write_tokens` BIGINT NOT NULL DEFAULT 0;
        ALTER TABLE `usage_daily` ADD `cached_tokens` BIGINT NOT NULL DEFAULT 0;
        ALTER TABLE `request_logs` ADD INDEX `idx_request_log_session_07b81c` (`session_id`);
        UPDATE `usage_daily` u JOIN (
            SELECT DATE(`created_at`) d, `api_key_id` k, `model_requested` m,
                COALESCE(`channel_id`, 0) c,
                SUM(`cached_tokens`) ct, SUM(`cache_write_tokens`) cw
            FROM `request_logs`
            GROUP BY DATE(`created_at`), `api_key_id`, `model_requested`, COALESCE(`channel_id`, 0)
        ) r ON u.`day` = r.d AND u.`api_key_id` = r.k AND u.`model` = r.m AND u.`channel_id` = r.c
        SET u.`cached_tokens` = r.ct, u.`cache_write_tokens` = r.cw;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` DROP INDEX `idx_request_log_session_07b81c`;
        ALTER TABLE `request_logs` DROP COLUMN `cache_savings`;
        ALTER TABLE `request_logs` DROP COLUMN `cost_detail`;
        ALTER TABLE `request_logs` DROP COLUMN `session_id`;
        ALTER TABLE `usage_daily` DROP COLUMN `cache_savings`;
        ALTER TABLE `usage_daily` DROP COLUMN `cache_write_tokens`;
        ALTER TABLE `usage_daily` DROP COLUMN `cached_tokens`;"""


MODELS_STATE = (
    "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"
    "FO6ryA=="
)
