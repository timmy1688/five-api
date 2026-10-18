"""Where the money goes: prompt cache efficiency and spend per client session."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from tortoise.functions import Count, Max, Min, Sum

from app.models import RequestLog, UsageDaily, User
from app.services.auth import require_permission
from app.services.usage_stats import start_day

router = APIRouter(prefix="/api/stats", tags=["stats"])

_CACHE_FIELDS = {
    "prompt_tokens": Sum("prompt_tokens"),
    "cached_tokens": Sum("cached_tokens"),
    "cache_write_tokens": Sum("cache_write_tokens"),
    "cache_savings": Sum("cache_savings"),
    "cost": Sum("cost"),
    "request_count": Sum("request_count"),
}


def _cache_row(row: dict, **extra) -> dict:
    prompt = int(row.get("prompt_tokens") or 0)
    cached = int(row.get("cached_tokens") or 0)
    return {
        **extra,
        "requests": int(row.get("request_count") or 0),
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "cache_write_tokens": int(row.get("cache_write_tokens") or 0),
        "hit_rate": round(cached / prompt, 4) if prompt else 0.0,
        "cache_savings": float(row.get("cache_savings") or 0),
        "cost": float(row.get("cost") or 0),
    }


@router.get("/cache")
async def cache_stats(
    days: int = Query(7, ge=1, le=90),
    _: User = require_permission("stat:read"),
):
    """Hit rate is cache reads over all input tokens, the share billed at the cache price."""
    base = UsageDaily.filter(day__gte=start_day(days))
    total = await base.annotate(**_CACHE_FIELDS).values(*_CACHE_FIELDS)
    trend = await base.group_by("day").annotate(**_CACHE_FIELDS).order_by("day").values("day", *_CACHE_FIELDS)
    by_model = await base.group_by("model").annotate(**_CACHE_FIELDS).order_by("-prompt_tokens").limit(20).values(
        "model", *_CACHE_FIELDS
    )
    by_key = await base.group_by("api_key_id", "api_key_name").annotate(**_CACHE_FIELDS).order_by(
        "-prompt_tokens"
    ).limit(20).values("api_key_id", "api_key_name", *_CACHE_FIELDS)
    by_channel = await base.exclude(channel_id=0).group_by("channel_id", "channel_name").annotate(
        **_CACHE_FIELDS
    ).order_by("-prompt_tokens").limit(20).values("channel_id", "channel_name", *_CACHE_FIELDS)
    return {
        "total": _cache_row(total[0] if total else {}),
        "trend": [_cache_row(r, date=str(r["day"])) for r in trend],
        "by_model": [_cache_row(r, model=r["model"]) for r in by_model],
        "by_key": [_cache_row(r, api_key_id=r["api_key_id"], api_key_name=r["api_key_name"]) for r in by_key],
        "by_channel": [
            _cache_row(r, channel_id=r["channel_id"], channel_name=r["channel_name"]) for r in by_channel
        ],
    }


@router.get("/sessions")
async def sessions(
    days: int = Query(7, ge=1, le=90),
    api_key_id: int | None = None,
    sort: Literal["cost", "recent", "requests"] = "cost",
    size: int = Query(50, ge=1, le=200),
    _: User = require_permission("stat:read"),
):
    """Sessions come from request logs, so log retention bounds how far back they go."""
    query = RequestLog.filter(created_at__gte=start_day(days)).exclude(session_id="")
    if api_key_id:
        query = query.filter(api_key_id=api_key_id)
    order = {"cost": "-cost_sum", "recent": "-last_at", "requests": "-requests"}[sort]
    rows = await (
        query.group_by("session_id")
        .annotate(
            requests=Count("id"),
            cost_sum=Sum("cost"),
            prompt_sum=Sum("prompt_tokens"),
            cached_sum=Sum("cached_tokens"),
            write_sum=Sum("cache_write_tokens"),
            completion_sum=Sum("completion_tokens"),
            savings_sum=Sum("cache_savings"),
            first_at=Min("created_at"),
            last_at=Max("created_at"),
            key_name=Max("api_key_name"),
            model=Max("model_requested"),
        )
        .order_by(order)
        .limit(size)
        .values(
            "session_id", "requests", "cost_sum", "prompt_sum", "cached_sum", "write_sum",
            "completion_sum", "savings_sum", "first_at", "last_at", "key_name", "model",
        )
    )
    items = []
    for r in rows:
        prompt = int(r["prompt_sum"] or 0)
        cached = int(r["cached_sum"] or 0)
        items.append({
            "session_id": r["session_id"],
            "api_key_name": r["key_name"] or "",
            "model": r["model"] or "",
            "requests": int(r["requests"] or 0),
            "cost": float(r["cost_sum"] or 0),
            "prompt_tokens": prompt,
            "cached_tokens": cached,
            "cache_write_tokens": int(r["write_sum"] or 0),
            "completion_tokens": int(r["completion_sum"] or 0),
            "hit_rate": round(cached / prompt, 4) if prompt else 0.0,
            "cache_savings": float(r["savings_sum"] or 0),
            "first_at": r["first_at"],
            "last_at": r["last_at"],
        })
    return {"total": len(items), "items": items}


@router.get("/sessions/{session_id}")
async def session_detail(
    session_id: str,
    _: User = require_permission("stat:read"),
):
    logs = await RequestLog.filter(session_id=session_id).order_by("created_at").limit(500)
    if not logs:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "items": [
            {
                "request_id": log.request_id,
                "created_at": log.created_at,
                "model_requested": log.model_requested,
                "model_actual": log.model_actual,
                "channel_name": log.channel_name,
                "status_code": log.status_code,
                "prompt_tokens": log.prompt_tokens,
                "cached_tokens": log.cached_tokens,
                "cache_write_tokens": log.cache_write_tokens,
                "completion_tokens": log.completion_tokens,
                "cost": float(log.cost),
                "cache_savings": float(log.cache_savings),
                "latency_ms": log.latency_ms,
            }
            for log in logs
        ],
    }
