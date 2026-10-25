from tortoise import fields
from tortoise.models import Model


class ModelProbe(Model):
    id = fields.BigIntField(pk=True)
    channel_id = fields.IntField(index=True)
    model = fields.CharField(max_length=64)
    actual_model = fields.CharField(max_length=64)
    kind = fields.CharField(max_length=16)
    run_source = fields.CharField(max_length=16, default="manual")
    status = fields.CharField(max_length=16)
    suite_version = fields.CharField(max_length=32, default="mvp-v1")
    latency_ms = fields.IntField(default=0)
    score = fields.IntField(null=True)
    checks = fields.JSONField(default=list)
    error = fields.CharField(max_length=512, default="")
    actor_id = fields.IntField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "model_probes"
        indexes = (("channel_id", "model", "kind", "created_at"),)
