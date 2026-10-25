from tortoise import fields
from tortoise.models import Model


class Settlement(Model):
    id = fields.BigIntField(primary_key=True)
    request_id = fields.CharField(max_length=36, unique=True)
    tenant_id = fields.IntField(index=True)
    api_key_id = fields.IntField(index=True)
    state = fields.CharField(max_length=16, default="reserved", index=True)
    occupied = fields.DecimalField(max_digits=18, decimal_places=6, default=0)
    cost = fields.DecimalField(max_digits=18, decimal_places=6, null=True)
    payload = fields.JSONField(null=True)
    quotes = fields.JSONField(default=dict)
    owner_id = fields.CharField(max_length=36, default="")
    dispatched = fields.BooleanField(default=False)
    attempts = fields.IntField(default=0)
    next_retry_at = fields.DatetimeField(null=True, index=True)
    last_error = fields.CharField(max_length=128, default="")
    windows_recorded = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "settlements"
        indexes = (("tenant_id", "state"), ("api_key_id", "state"))
