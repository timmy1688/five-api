from tortoise import fields
from tortoise.models import Model


class APIKey(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=128)
    key_hash = fields.CharField(max_length=64, unique=True)
    key_prefix = fields.CharField(max_length=12)
    quota_total = fields.DecimalField(max_digits=16, decimal_places=6, default=-1)
    quota_used = fields.DecimalField(max_digits=16, decimal_places=6, default=0)
    concurrent_limit = fields.IntField(default=5)
    rpm_limit = fields.IntField(default=-1)
    tpm_limit = fields.IntField(default=-1)
    allowed_models = fields.JSONField(default=list)
    allowed_ips = fields.JSONField(default=list)
    model_group_id = fields.IntField(null=True, default=None)
    # Channels this key may be routed to; empty means every enabled channel.
    channel_ids = fields.JSONField(default=list)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="keys", on_delete=fields.RESTRICT)
    is_enabled = fields.BooleanField(default=True)
    is_revoked = fields.BooleanField(default=False)
    audit_enabled = fields.BooleanField(default=False)
    audit_policy = fields.CharField(max_length=16, default="on")
    quota_reset_day = fields.SmallIntField(null=True)
    quota_last_reset_at = fields.DatetimeField(null=True)
    # Rolling USD caps keyed by "5h", "1d", "7d". A missing key means no cap.
    window_limits = fields.JSONField(default=dict)
    expires_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "api_keys"
