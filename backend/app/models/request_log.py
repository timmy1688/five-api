from tortoise import fields
from tortoise.models import Model


class RequestLog(Model):
    id = fields.BigIntField(pk=True)
    request_id = fields.CharField(max_length=36, index=True)
    api_key_id = fields.IntField(index=True)
    api_key_name = fields.CharField(max_length=128, default="")
    channel_id = fields.IntField(null=True)
    channel_name = fields.CharField(max_length=128, default="")
    model_requested = fields.CharField(max_length=64, index=True)
    model_actual = fields.CharField(max_length=64, default="")
    provider = fields.CharField(max_length=32, default="")
    endpoint = fields.CharField(max_length=64, default="")
    prompt_tokens = fields.IntField(default=0)
    completion_tokens = fields.IntField(default=0)
    total_tokens = fields.IntField(default=0)
    cached_tokens = fields.IntField(default=0)
    cost = fields.DecimalField(max_digits=16, decimal_places=6, default=0)
    is_stream = fields.BooleanField(default=False)
    status_code = fields.IntField(default=0)
    latency_ms = fields.IntField(default=0)
    error_message = fields.TextField(default="")
    ip_address = fields.CharField(max_length=45, default="")
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = "request_logs"
