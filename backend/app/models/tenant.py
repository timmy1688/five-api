from tortoise import fields
from tortoise.models import Model


class Tenant(Model):
    """A shared USD budget. Every key in the team spends from it as well as its own quota."""

    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=128, unique=True)
    description = fields.CharField(max_length=256, default="")
    quota_total = fields.DecimalField(max_digits=16, decimal_places=6, default=0)
    quota_used = fields.DecimalField(max_digits=16, decimal_places=6, default=0)
    quota_reset_day = fields.SmallIntField(null=True)
    quota_last_reset_at = fields.DatetimeField(null=True)
    # Rolling USD caps keyed by "5h", "1d", "7d". A missing key means no cap.
    window_limits = fields.JSONField(default=dict)
    is_enabled = fields.BooleanField(default=True)
    is_system = fields.BooleanField(default=False)
    allowed_models = fields.JSONField(default=list)
    max_keys = fields.IntField(default=100)
    rpm_limit = fields.IntField(default=120)
    tpm_limit = fields.IntField(default=100000)
    concurrent_limit = fields.IntField(default=10)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "tenants"
