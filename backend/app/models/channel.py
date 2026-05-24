from tortoise import fields
from tortoise.models import Model


class Channel(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=128)
    provider = fields.CharField(max_length=32)
    base_url = fields.CharField(max_length=512)
    api_key = fields.CharField(max_length=512)
    models = fields.JSONField(default=list)
    model_mapping = fields.JSONField(default=dict)
    model_pricing = fields.JSONField(default=dict)
    group = fields.CharField(max_length=64, default="")
    priority = fields.IntField(default=0)
    weight = fields.IntField(default=1)
    is_enabled = fields.BooleanField(default=True)
    max_retries = fields.IntField(default=1)
    timeout = fields.IntField(default=120)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "channels"
