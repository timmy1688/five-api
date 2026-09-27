from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.models import User, RequestLog, RequestLogAudit
from app.services.auth import require_permission
from app.services.content_filter import keyword_was_hit
from app.services.logging_service import cleanup_old_logs

router = APIRouter(prefix="/api/logs", tags=["logs"])


class LogResponse(BaseModel):
    id: int
    request_id: str
    api_key_id: int
    api_key_name: str
    channel_id: int | None
    channel_name: str
    model_requested: str
    model_actual: str
    provider: str
    endpoint: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int
    cache_write_tokens: int
    cost: float
    is_stream: bool
    status_code: int
    latency_ms: int
    error_message: str
    error_origin: str
    upstream_status_code: int
    upstream_error: str
    ip_address: str
    failed_over: bool
    has_audit: bool
    ai_review: str
    keyword_hit: bool
    created_at: datetime


class LogAuditResponse(BaseModel):
    request_id: str
    audit_request: str


class LogListResponse(BaseModel):
    total: int
    items: list[LogResponse]


def _to_log(r: RequestLog) -> LogResponse:
    return LogResponse(
        id=r.id,
        request_id=r.request_id,
        api_key_id=r.api_key_id,
        api_key_name=r.api_key_name,
        channel_id=r.channel_id,
        channel_name=r.channel_name,
        model_requested=r.model_requested,
        model_actual=r.model_actual,
        provider=r.provider,
        endpoint=r.endpoint,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
        total_tokens=r.total_tokens,
        cached_tokens=r.cached_tokens,
        cache_write_tokens=r.cache_write_tokens,
        cost=float(r.cost),
        is_stream=r.is_stream,
        status_code=r.status_code,
        latency_ms=r.latency_ms,
        error_message=r.error_message,
        error_origin=r.error_origin,
        upstream_status_code=r.upstream_status_code,
        upstream_error=r.upstream_error,
        ip_address=r.ip_address,
        failed_over=r.failed_over,
        has_audit=r.has_audit,
        ai_review=r.ai_review,
        keyword_hit=keyword_was_hit(r.security_hit),
        created_at=r.created_at,
    )


@router.get("", response_model=LogListResponse)
async def list_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    api_key_id: int | None = None,
    api_key_name: str | None = Query(None, max_length=100),
    model: str | None = None,
    status_code: int | None = None,
    error_origin: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    _: User = require_permission("log:read"),
):
    qs = RequestLog.all()
    if api_key_id is not None:
        qs = qs.filter(api_key_id=api_key_id)
    if api_key_name and (key_name := api_key_name.strip()):
        qs = qs.filter(api_key_name__icontains=key_name)
    if model:
        qs = qs.filter(model_requested=model)
    if status_code is not None:
        qs = qs.filter(status_code=status_code)
    if error_origin:
        qs = qs.filter(error_origin=error_origin)
    if start_date:
        qs = qs.filter(created_at__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__lte=end_date)

    total = await qs.count()
    items = await (
        qs.order_by("-id")
        .offset((page - 1) * size)
        .limit(size)
        .only(
            "id", "request_id", "api_key_id", "api_key_name", "channel_id", "channel_name",
            "model_requested", "model_actual", "provider", "endpoint",
            "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens",
            "cache_write_tokens", "cost",
            "is_stream", "status_code", "latency_ms", "error_message", "error_origin",
            "upstream_status_code", "upstream_error", "ip_address", "failed_over",
            "has_audit", "ai_review", "security_hit", "created_at",
        )
    )
    return LogListResponse(total=total, items=[_to_log(r) for r in items])


@router.get("/{request_id}", response_model=LogResponse)
async def get_log(request_id: str, _: User = require_permission("log:read")):
    r = await RequestLog.get_or_none(request_id=request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return _to_log(r)


@router.get("/{request_id}/audit", response_model=LogAuditResponse)
async def get_log_audit(request_id: str, _: User = require_permission("log:read")):
    """请求正文单独取。打开日志详情不读这段，避免每次点开都拉一大片内容。"""
    r = await RequestLog.get_or_none(request_id=request_id)
    if r is None or not r.has_audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    audit = await RequestLogAudit.get_or_none(request_log_id=r.id)
    if audit is None or not audit.audit_request:
        raise HTTPException(status_code=404, detail="Audit not found")
    return LogAuditResponse(request_id=r.request_id, audit_request=audit.audit_request)


@router.post("/cleanup")
async def cleanup_logs(
    days: int = Query(None, ge=1),
    _: User = require_permission("log:write"),
):
    deleted = await cleanup_old_logs(days)
    return {"deleted": deleted}
