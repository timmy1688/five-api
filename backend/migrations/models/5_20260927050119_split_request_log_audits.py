from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `request_log_audits` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `audit_request` LONGTEXT NOT NULL,
    `audit_response` LONGTEXT NOT NULL,
    `request_log_id` BIGINT NOT NULL UNIQUE,
    CONSTRAINT `fk_request__request__cbe8d4dd` FOREIGN KEY (`request_log_id`) REFERENCES `request_logs` (`id`) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COMMENT='推理正文单独存放，避免日志列表和统计扫描把大字段读进内存。';
        ALTER TABLE `request_logs` ADD `has_audit` BOOL NOT NULL DEFAULT 0;
        INSERT INTO `request_log_audits` (`audit_request`, `audit_response`, `request_log_id`)
        SELECT `audit_request`, `audit_response`, `id`
        FROM `request_logs`
        WHERE `audit_request` <> '' OR `audit_response` <> '';
        UPDATE `request_logs`
        SET `has_audit` = 1
        WHERE `id` IN (SELECT `request_log_id` FROM `request_log_audits`);
        ALTER TABLE `request_logs` DROP COLUMN `audit_request`;
        ALTER TABLE `request_logs` DROP COLUMN `audit_response`;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `request_logs` ADD `audit_request` LONGTEXT NOT NULL;
        ALTER TABLE `request_logs` ADD `audit_response` LONGTEXT NOT NULL;
        UPDATE `request_logs` AS `log`
        JOIN `request_log_audits` AS `audit` ON `audit`.`request_log_id` = `log`.`id`
        SET `log`.`audit_request` = `audit`.`audit_request`,
            `log`.`audit_response` = `audit`.`audit_response`;
        ALTER TABLE `request_logs` DROP COLUMN `has_audit`;
        DROP TABLE IF EXISTS `request_log_audits`;"""


MODELS_STATE = (
    "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"
)
