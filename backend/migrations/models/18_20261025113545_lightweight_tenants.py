from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    # MySQL DDL commits implicitly. Stop the gateway and back up before upgrading.
    # Roles and the nullable legacy role_id are retained for recovery, never read by the app.
    return """
        RENAME TABLE `teams` TO `tenants`;
        ALTER TABLE `tenants` ADD `allowed_models` JSON;
        UPDATE `tenants` SET `allowed_models` = JSON_ARRAY();
        ALTER TABLE `tenants` MODIFY `allowed_models` JSON NOT NULL;
        ALTER TABLE `tenants` ADD `max_keys` INT NOT NULL DEFAULT 100;
        ALTER TABLE `api_keys` CHANGE `team_id` `tenant_id` INT NULL;
        INSERT INTO `tenants` (
            name, description, quota_total, quota_used, window_limits, is_enabled,
            allowed_models, max_keys, created_at, updated_at
        ) SELECT '__legacy_unassigned__', 'Existing unassigned keys; platform managed', -1, 0,
            JSON_OBJECT(), 1, JSON_ARRAY(), 1000, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
          WHERE EXISTS (
            SELECT 1 FROM api_keys k LEFT JOIN tenants t ON t.id=k.tenant_id WHERE t.id IS NULL
          );
        UPDATE api_keys k LEFT JOIN tenants t ON t.id=k.tenant_id
          SET k.tenant_id=(SELECT id FROM tenants WHERE name='__legacy_unassigned__')
          WHERE t.id IS NULL;
        UPDATE tenants SET quota_used=(
            SELECT COALESCE(SUM(k.quota_used),0) FROM api_keys k WHERE k.tenant_id=tenants.id
        ) WHERE name='__legacy_unassigned__';
        ALTER TABLE `api_keys` MODIFY `tenant_id` INT NOT NULL;
        ALTER TABLE `api_keys` ADD `is_revoked` BOOL NOT NULL DEFAULT 0;
        ALTER TABLE `api_keys` ADD CONSTRAINT `fk_api_keys_tenants_f5dbd7fd`
          FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE RESTRICT;
        ALTER TABLE `request_logs` ADD `tenant_id` INT NOT NULL DEFAULT 0;
        ALTER TABLE `request_logs` ADD INDEX `idx_request_log_tenant__c0743f` (`tenant_id`);
        UPDATE request_logs l JOIN api_keys k ON k.id=l.api_key_id SET l.tenant_id=k.tenant_id;
        ALTER TABLE `usage_daily` RENAME COLUMN `team_id` TO `tenant_id`;
        UPDATE usage_daily d JOIN api_keys k ON k.id=d.api_key_id
          SET d.tenant_id=k.tenant_id WHERE d.tenant_id=0;
        ALTER TABLE `admins` DROP FOREIGN KEY `fk_admins_roles_539b3f68`;
        ALTER TABLE `admins` MODIFY `role_id` INT NULL;
        ALTER TABLE `admins` ADD `role_code` VARCHAR(24) NOT NULL DEFAULT 'tenant';
        ALTER TABLE `admins` ADD `tenant_id` INT UNIQUE;
        ALTER TABLE `admins` ADD `must_change_password` BOOL NOT NULL DEFAULT 0;
        UPDATE admins a JOIN roles r ON r.id=a.role_id SET a.role_code='platform_admin'
          WHERE r.name='Super Admin';
        INSERT INTO tenants (
            name, description, quota_total, quota_used, window_limits, is_enabled,
            allowed_models, max_keys, created_at, updated_at
        ) SELECT CONCAT('__legacy_account_',a.id,'__'),
            'Unmapped legacy account; manual review required', 0, 0,
            JSON_OBJECT(), 0, JSON_ARRAY(), 100, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
          FROM admins a WHERE a.role_code<>'platform_admin';
        UPDATE admins a JOIN tenants t ON t.name=CONCAT('__legacy_account_',a.id,'__')
          SET a.tenant_id=t.id, a.must_change_password=1
          WHERE a.role_code<>'platform_admin';
        UPDATE admins SET is_active=1 WHERE role_code='tenant';
        ALTER TABLE `admins` ADD CONSTRAINT `fk_admins_tenants_a1d8df34`
          FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE;
        CREATE TABLE `management_events` (
          `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
          `operation_id` VARCHAR(64) NOT NULL UNIQUE,
          `actor_id` INT NOT NULL, `tenant_id` INT NOT NULL,
          `action` VARCHAR(64) NOT NULL, `target_id` INT NOT NULL,
          `detail` JSON NOT NULL, `created_at` DATETIME(6) NOT NULL,
          KEY `idx_management__tenant__c53f79` (`tenant_id`)
        ) CHARACTER SET utf8mb4;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    raise RuntimeError(
        "Tenant/account mappings cannot be safely reversed. Stop the gateway and restore the pre-upgrade backup."
    )

MODELS_STATE = (
    "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"
)
