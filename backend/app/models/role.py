from tortoise import fields
from tortoise.models import Model


class Role(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True)
    description = fields.CharField(max_length=256, default="")
    permissions = fields.JSONField(default=[])
    is_builtin = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "roles"
