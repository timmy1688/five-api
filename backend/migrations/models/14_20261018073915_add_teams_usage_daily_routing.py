from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `teams` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(128) NOT NULL UNIQUE,
    `description` VARCHAR(256) NOT NULL,
    `quota_total` DECIMAL(16,6) NOT NULL,
    `quota_used` DECIMAL(16,6) NOT NULL,
    `quota_reset_day` SMALLINT,
    `quota_last_reset_at` DATETIME(6),
    `is_enabled` BOOL NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4 COMMENT='A shared USD budget. Every key in the team spends from it as well as its own quota.';
        CREATE TABLE IF NOT EXISTS `usage_daily` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `day` DATE NOT NULL,
    `api_key_id` INT NOT NULL,
    `api_key_name` VARCHAR(128) NOT NULL,
    `team_id` INT NOT NULL,
    `model` VARCHAR(64) NOT NULL,
    `channel_id` INT NOT NULL,
    `channel_name` VARCHAR(128) NOT NULL,
    `request_count` BIGINT NOT NULL,
    `error_count` BIGINT NOT NULL,
    `prompt_tokens` BIGINT NOT NULL,
    `completion_tokens` BIGINT NOT NULL,
    `total_tokens` BIGINT NOT NULL,
    `cost` DECIMAL(18,6) NOT NULL,
    UNIQUE KEY `uid_usage_daily_day_027604` (`day`, `api_key_id`, `model`, `channel_id`),
    KEY `idx_usage_daily_team_id_2cce8b` (`team_id`)
) CHARACTER SET utf8mb4 COMMENT='Per-day totals by key, model and channel, so statistics never scan request_logs.';
        ALTER TABLE `api_keys` ADD `team_id` INT;
        ALTER TABLE `model_prices` ADD `request_price` DECIMAL(16,6) NOT NULL DEFAULT 0;
        ALTER TABLE `admins` ADD `token_version` INT NOT NULL DEFAULT 0;
        ALTER TABLE `api_keys` ADD INDEX `idx_api_keys_team_id_c72d4f` (`team_id`);
        INSERT INTO `usage_daily` (
            `day`, `api_key_id`, `api_key_name`, `team_id`, `model`, `channel_id`, `channel_name`,
            `request_count`, `error_count`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`
        )
        SELECT DATE(`created_at`), `api_key_id`, MAX(`api_key_name`), 0, `model_requested`,
            COALESCE(`channel_id`, 0), MAX(`channel_name`), COUNT(*), SUM(`status_code` >= 400),
            SUM(`prompt_tokens`), SUM(`completion_tokens`), SUM(`total_tokens`), SUM(`cost`)
        FROM `request_logs`
        GROUP BY DATE(`created_at`), `api_key_id`, `model_requested`, COALESCE(`channel_id`, 0);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `api_keys` DROP INDEX `idx_api_keys_team_id_c72d4f`;
        ALTER TABLE `admins` DROP COLUMN `token_version`;
        ALTER TABLE `api_keys` DROP COLUMN `team_id`;
        ALTER TABLE `model_prices` DROP COLUMN `request_price`;
        DROP TABLE IF EXISTS `teams`;
        DROP TABLE IF EXISTS `usage_daily`;"""


MODELS_STATE = (
    "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"
    "3ckVvIrkFttwM4e27XGfViNjFfKVSLeqjL26QoVsnQrJqdcIfaaQPvMENIcRDsl2IO8A9b"
    "uOq7eja3MdC4dW26baEhxaVU61C7oUmDHDLvwlwtkTq01qFEy5m0mYiGSoSt/mF9LSUcnk"
    "eSJdPkFrKxGJLCFdIpOpRG8oYRPqKpZWlrGRkC0BLD1DTaO/kY0l41mXfjqGDU46iTFT1T"
    "PEhH9cE76I0leZRS8C9fUF6l0ZI7tb4DDm+rwdMhLI19ko431V52eXvVOGx5aDWQ6jAjQH"
    "QLEdyX6SiUYEbVkFDJtsTkjSMmc/BrxFu6YO+pPxbh6k/+RNgXPC/XXaB+cxpAFs+zTxWw"
    "gZtyjBVDgy2ptrGaQzHIS7W7i7j+fLaqgNLlKJ3mKvH7nn5RvdYukCIJfWlP8lcrWb54Vx"
    "aD2iMwUV9/pivkDrPVGxJNd8wNLSdY90JffWEtBVyd9ivSthQ6L74iBsIwVLOnyCloQVoE"
    "vRQ1TSjpiyH3Cv3+u/W8i2oS4ZugRdl45fQyI1TqSvxjOWDMfW0BOkJeQqqUxf2H0GUTzf"
    "0y/Pb9E9XWyzlRTDosF3Caxs8lhDUykSS8CCkkJnVahKjnki9WgTXW+RYUn3Hd0Imn/fyf"
    "IPfe/4Kmz8LIvdQbKR0wF+iIWQx7Loq5vjdGJaNHRSyHCHMC2Y2EzQwFkgz2Qkkrw5h7/U"
    "Z2WLo1+avKUIjRXwjd8IoraTi5oydl/74PUjGq3lR+tf65SiVktbcUZRndI20PkVw2EdNF"
    "Jku4MdtDVjuRa9N7lz7QE9kAAK/g/jf88hMHk90N5zYGrugwKnxeT1Q7sPjKm5L/KPlcnr"
    "htaeLFP71yDO7ygcMJ/uCZgfjePZ9VMyXM7eUtdsZzNQN0gXKfTtyqiji6R5TZwopnWZde"
    "Wb5w8A09O4TIAx74JXBrSFC1/7oyJ7uZNaOQl2qd3cEaYHqaInxsjelzkR4kTiRPHECVfd"
    "kp+ghZn5oznKWgLXGm2tPF+UyElpWXaCyEl5i72elZMS84SSuYnPkx9B1Cc6j1zlTRlbcY"
    "LT7H40LIjW+me4dUkusCerf5uGkfsSjJ59+7GGg6rARqy1Wa8zaCHlocOwX/0r3VwLNqwj"
    "LNgmfc7dHAs2U+PMNquylU1hTmWYU/Sj4mDYr95Cdk97vSLhz14vO/zZSy2gIU+kOYtphr"
    "NX3EcgYs0955r7V3XFvvwf0fnVaw=="
)
