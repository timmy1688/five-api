from tortoise import fields
from tortoise.models import Model


class ModelPrice(Model):
    id = fields.IntField(pk=True)
    model = fields.CharField(max_length=64, unique=True)
    prompt_price = fields.DecimalField(max_digits=16, decimal_places=6, default=0)
    completion_price = fields.DecimalField(max_digits=16, decimal_places=6, default=0)
    cached_price = fields.DecimalField(max_digits=16, decimal_places=6, default=0)
    currency = fields.CharField(max_length=8, default="USD")
    is_active = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "model_prices"
