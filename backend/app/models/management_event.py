from tortoise import fields
from tortoise.models import Model


class ManagementEvent(Model):
    id = fields.BigIntField(pk=True)
    operation_id = fields.CharField(max_length=64, unique=True)
    actor_id = fields.IntField()
    tenant_id = fields.IntField(default=0, index=True)
    action = fields.CharField(max_length=64)
    target_id = fields.IntField(default=0)
    detail = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "management_events"
