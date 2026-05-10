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
    allowed_models = fields.JSONField(default=list)
    is_enabled = fields.BooleanField(default=True)
    quota_reset_day = fields.SmallIntField(null=True)
    quota_last_reset_at = fields.DatetimeField(null=True)
    expires_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "api_keys"
