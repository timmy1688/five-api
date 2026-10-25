from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `settlements` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `request_id` VARCHAR(36) NOT NULL UNIQUE,
    `tenant_id` INT NOT NULL,
    `api_key_id` INT NOT NULL,
    `state` VARCHAR(16) NOT NULL,
    `occupied` DECIMAL(18,6) NOT NULL,
    `cost` DECIMAL(18,6),
    `payload` JSON,
    `quotes` JSON NOT NULL,
    `owner_id` VARCHAR(36) NOT NULL,
    `attempts` INT NOT NULL,
    `next_retry_at` DATETIME(6),
    `last_error` VARCHAR(128) NOT NULL,
    `windows_recorded` BOOL NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    KEY `idx_settlements_tenant__f77ede` (`tenant_id`),
    KEY `idx_settlements_api_key_817b3a` (`api_key_id`),
    KEY `idx_settlements_state_148909` (`state`),
    KEY `idx_settlements_next_re_d8d74d` (`next_retry_at`),
    KEY `idx_settlements_tenant__f2bbf9` (`tenant_id`, `state`),
    KEY `idx_settlements_api_key_db4839` (`api_key_id`, `state`)
) CHARACTER SET utf8mb4;
        ALTER TABLE `request_logs` ADD `client_request_id` VARCHAR(128) NOT NULL DEFAULT '';
        ALTER TABLE `request_logs` ADD `upstream_cost` DECIMAL(16,6) NOT NULL DEFAULT 0;
        ALTER TABLE `request_logs` ADD `usage_source` VARCHAR(16) NOT NULL DEFAULT 'upstream';
        ALTER TABLE `tenants` ADD `concurrent_limit` INT NOT NULL DEFAULT 10;
        ALTER TABLE `tenants` ADD `tpm_limit` INT NOT NULL DEFAULT 100000;
        ALTER TABLE `tenants` ADD `rpm_limit` INT NOT NULL DEFAULT 120;
        UPDATE `tenants` SET rpm_limit=-1, tpm_limit=-1, concurrent_limit=-1;
        ALTER TABLE `usage_daily` ADD `upstream_cost` DECIMAL(18,6) NOT NULL DEFAULT 0;
        UPDATE `request_logs` SET upstream_cost=cost, usage_source='legacy';
        UPDATE `usage_daily` SET upstream_cost=cost;
        ALTER TABLE `request_logs` ADD INDEX `idx_request_log_client__5602a6` (`client_request_id`);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` DROP INDEX `idx_request_log_client__5602a6`;
        ALTER TABLE `tenants` DROP COLUMN `concurrent_limit`;
        ALTER TABLE `tenants` DROP COLUMN `tpm_limit`;
        ALTER TABLE `tenants` DROP COLUMN `rpm_limit`;
        ALTER TABLE `request_logs` DROP COLUMN `client_request_id`;
        ALTER TABLE `request_logs` DROP COLUMN `upstream_cost`;
        ALTER TABLE `request_logs` DROP COLUMN `usage_source`;
        ALTER TABLE `usage_daily` DROP COLUMN `upstream_cost`;
        DROP TABLE IF EXISTS `settlements`;"""


MODELS_STATE = (
    "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"
    "EJFM00+ckIEhCVNFMy38CLuh5+/B8t9dXY"
)
