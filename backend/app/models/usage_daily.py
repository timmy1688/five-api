from tortoise import fields
from tortoise.models import Model


class UsageDaily(Model):
    """Per-day totals by key, model and channel, so statistics never scan request_logs.

    Written on every request log. Rows outlive log retention, so all-time totals
    stay correct after old logs are cleaned up. 0 stands for "no channel".
    """

    id = fields.BigIntField(pk=True)
    day = fields.DateField()
    api_key_id = fields.IntField(default=0)
    api_key_name = fields.CharField(max_length=128, default="")
    team_id = fields.IntField(default=0, index=True)
    model = fields.CharField(max_length=64, default="")
    channel_id = fields.IntField(default=0)
    channel_name = fields.CharField(max_length=128, default="")
    request_count = fields.BigIntField(default=0)
    error_count = fields.BigIntField(default=0)
    prompt_tokens = fields.BigIntField(default=0)
    completion_tokens = fields.BigIntField(default=0)
    total_tokens = fields.BigIntField(default=0)
    cost = fields.DecimalField(max_digits=18, decimal_places=6, default=0)

    class Meta:
        table = "usage_daily"
        unique_together = (("day", "api_key_id", "model", "channel_id"),)
