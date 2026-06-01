from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.models import User, RequestLog
from app.services.auth import require_permission
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
    cost: float
    is_stream: bool
    status_code: int
    latency_ms: int
    error_message: str
    ip_address: str
    created_at: datetime


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
        cost=float(r.cost),
        is_stream=r.is_stream,
        status_code=r.status_code,
        latency_ms=r.latency_ms,
        error_message=r.error_message,
        ip_address=r.ip_address,
        created_at=r.created_at,
    )


@router.get("", response_model=LogListResponse)
async def list_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    api_key_id: int | None = None,
    model: str | None = None,
    status_code: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    _: User = require_permission("log:read"),
):
    qs = RequestLog.all()
    if api_key_id is not None:
        qs = qs.filter(api_key_id=api_key_id)
    if model:
        qs = qs.filter(model_requested=model)
    if status_code is not None:
        qs = qs.filter(status_code=status_code)
    if start_date:
        qs = qs.filter(created_at__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__lte=end_date)

    total = await qs.count()
    items = await qs.order_by("-id").offset((page - 1) * size).limit(size)
    return LogListResponse(total=total, items=[_to_log(r) for r in items])


@router.get("/{request_id}", response_model=LogResponse)
async def get_log(request_id: str, _: User = require_permission("log:read")):
    r = await RequestLog.get_or_none(request_id=request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return _to_log(r)


@router.post("/cleanup")
async def cleanup_logs(
    days: int = Query(None, ge=1),
    _: User = require_permission("log:write"),
):
    deleted = await cleanup_old_logs(days)
    return {"deleted": deleted}
