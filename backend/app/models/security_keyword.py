from tortoise import fields
from tortoise.models import Model


class SecurityKeyword(Model):
    id = fields.IntField(pk=True)
    keyword = fields.CharField(max_length=64)
    keyword_key = fields.CharField(max_length=64, unique=True)
    direction = fields.CharField(max_length=16, default="both")
    is_enabled = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "security_keywords"
