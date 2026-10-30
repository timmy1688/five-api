from tortoise import fields
from tortoise.models import Model


class Channel(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=128)
    provider = fields.CharField(max_length=32)  # 协议：openai | anthropic
    base_url = fields.CharField(max_length=512)
    # Encrypted. Several keys are stored one per line.
    api_key = fields.TextField()
    models = fields.JSONField(default=list)
    model_mapping = fields.JSONField(default=dict)
    # Customer price = model selling price x price_multiplier, unless price_overrides fixes the model's price.
    price_multiplier = fields.DecimalField(max_digits=8, decimal_places=4, default=1)
    price_overrides = fields.JSONField(default=dict)
    priority = fields.IntField(default=0)
    weight = fields.IntField(default=1)
    is_enabled = fields.BooleanField(default=True)
    max_retries = fields.IntField(default=1)
    timeout = fields.IntField(default=120)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "channels"
