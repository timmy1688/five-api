from tortoise import fields
from tortoise.models import Model


class SystemSetting(Model):
    id = fields.IntField(pk=True)
    key = fields.CharField(max_length=64, unique=True)
    value = fields.JSONField()
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "system_settings"
