from tortoise import fields
from tortoise.models import Model


class ModelGroup(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=128, unique=True)
    models = fields.JSONField(default=list)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "model_groups"
