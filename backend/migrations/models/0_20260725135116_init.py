from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `api_keys` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(128) NOT NULL,
    `key_hash` VARCHAR(64) NOT NULL UNIQUE,
    `key_prefix` VARCHAR(12) NOT NULL,
    `quota_total` DECIMAL(16,6) NOT NULL,
    `quota_used` DECIMAL(16,6) NOT NULL,
    `concurrent_limit` INT NOT NULL,
    `rpm_limit` INT NOT NULL,
    `allowed_models` JSON NOT NULL,
    `allowed_ips` JSON NOT NULL,
    `model_group_id` INT,
    `is_enabled` BOOL NOT NULL,
    `quota_reset_day` SMALLINT,
    `quota_last_reset_at` DATETIME(6),
    `expires_at` DATETIME(6),
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `channels` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(128) NOT NULL,
    `provider` VARCHAR(32) NOT NULL,
    `base_url` VARCHAR(512) NOT NULL,
    `api_key` VARCHAR(512) NOT NULL,
    `models` JSON NOT NULL,
    `model_mapping` JSON NOT NULL,
    `model_pricing` JSON NOT NULL,
    `priority` INT NOT NULL,
    `weight` INT NOT NULL,
    `is_enabled` BOOL NOT NULL,
    `max_retries` INT NOT NULL,
    `timeout` INT NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `model_groups` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(128) NOT NULL UNIQUE,
    `models` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `model_prices` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `model` VARCHAR(64) NOT NULL UNIQUE,
    `prompt_price` DECIMAL(16,6) NOT NULL,
    `completion_price` DECIMAL(16,6) NOT NULL,
    `cached_price` DECIMAL(16,6) NOT NULL,
    `currency` VARCHAR(8) NOT NULL,
    `is_active` BOOL NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `request_logs` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `request_id` VARCHAR(36) NOT NULL,
    `api_key_id` INT NOT NULL,
    `api_key_name` VARCHAR(128) NOT NULL,
    `channel_id` INT,
    `channel_name` VARCHAR(128) NOT NULL,
    `model_requested` VARCHAR(64) NOT NULL,
    `model_actual` VARCHAR(64) NOT NULL,
    `provider` VARCHAR(32) NOT NULL,
    `endpoint` VARCHAR(64) NOT NULL,
    `prompt_tokens` INT NOT NULL,
    `completion_tokens` INT NOT NULL,
    `total_tokens` INT NOT NULL,
    `cached_tokens` INT NOT NULL,
    `cost` DECIMAL(16,6) NOT NULL,
    `is_stream` BOOL NOT NULL,
    `status_code` INT NOT NULL,
    `latency_ms` INT NOT NULL,
    `error_message` LONGTEXT NOT NULL,
    `ip_address` VARCHAR(45) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    KEY `idx_request_log_request_d49a97` (`request_id`),
    KEY `idx_request_log_api_key_625618` (`api_key_id`),
    KEY `idx_request_log_model_r_17cdd6` (`model_requested`),
    KEY `idx_request_log_created_bf0c26` (`created_at`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `roles` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(64) NOT NULL UNIQUE,
    `description` VARCHAR(256) NOT NULL,
    `permissions` JSON NOT NULL,
    `is_builtin` BOOL NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `admins` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `username` VARCHAR(64) NOT NULL UNIQUE,
    `hashed_password` VARCHAR(255) NOT NULL,
    `is_active` BOOL NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `role_id` INT NOT NULL,
    CONSTRAINT `fk_admins_roles_539b3f68` FOREIGN KEY (`role_id`) REFERENCES `roles` (`id`) ON DELETE CASCADE
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `aerich` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `version` VARCHAR(255) NOT NULL,
    `app` VARCHAR(100) NOT NULL,
    `content` JSON NOT NULL
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
    "TIFqxikP2LVeW/oEoVq150/8XT/0RvmjA="
)
