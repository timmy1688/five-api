from tortoise import fields
from tortoise.models import Model


class RequestLogAudit(Model):
    """推理正文单独存放，避免日志列表和统计扫描把大字段读进内存。"""

    id = fields.BigIntField(pk=True)
    request_log = fields.OneToOneField(
        "models.RequestLog",
        related_name="audit_body",
        on_delete=fields.CASCADE,
    )
    audit_request = fields.TextField(default="")

    class Meta:
        table = "request_log_audits"
