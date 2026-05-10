from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from tortoise.functions import Count, Sum

from app.models import Admin, APIKey, Channel, RequestLog
from app.schemas.stats import KeyUsage, ModelUsage, StatsOverview, UsagePoint
from app.services.auth import get_current_admin

router = APIRouter(prefix="/api/admin/stats", tags=["admin-stats"])


@router.get("/overview", response_model=StatsOverview)
async def overview(_: Admin = Depends(get_current_admin)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_requests = await RequestLog.all().count()
    agg = await RequestLog.all().annotate(s=Sum("total_tokens"), c=Sum("cost")).values("s", "c")
    total_tokens = agg[0]["s"] or 0
    total_cost = float(agg[0]["c"] or 0)

    active_keys = await APIKey.filter(is_enabled=True).count()
    active_channels = await Channel.filter(is_enabled=True).count()

    requests_today = await RequestLog.filter(created_at__gte=today_start).count()
    agg_today = await RequestLog.filter(created_at__gte=today_start).annotate(s=Sum("total_tokens"), c=Sum("cost")).values("s", "c")
    tokens_today = agg_today[0]["s"] or 0
    cost_today = float(agg_today[0]["c"] or 0)

    return StatsOverview(
        total_requests=total_requests,
        total_tokens=total_tokens,
        total_cost=total_cost,
        active_keys=active_keys,
        active_channels=active_channels,
        requests_today=requests_today,
        tokens_today=tokens_today,
        cost_today=cost_today,
    )


@router.get("/usage", response_model=list[UsagePoint])
async def usage(
    days: int = Query(7, ge=1, le=90),
    _: Admin = Depends(get_current_admin),
):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    from tortoise import connections

    conn = connections.get("default")
    rows = await conn.execute_query_dict(
        """
        SELECT
            DATE_FORMAT(created_at, '%%Y-%%m-%%d') as `date`,
            COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) as completion_tokens,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COUNT(*) as request_count,
            COALESCE(SUM(cost), 0) as cost
        FROM request_logs
        WHERE created_at >= %s
        GROUP BY DATE_FORMAT(created_at, '%%Y-%%m-%%d')
        ORDER BY `date`
        """,
        [start],
    )
    return [UsagePoint(**{**row, "cost": float(row["cost"])}) for row in rows]


@router.get("/by-model", response_model=list[ModelUsage])
async def by_model(
    days: int = Query(7, ge=1, le=90),
    _: Admin = Depends(get_current_admin),
):
    start = datetime.now(timezone.utc) - timedelta(days=days)
    results = (
        await RequestLog.filter(created_at__gte=start)
        .group_by("model_requested")
        .annotate(total_tokens=Sum("total_tokens"), request_count=Count("id"), cost=Sum("cost"))
        .order_by("-total_tokens")
        .limit(20)
        .values("model_requested", "total_tokens", "request_count", "cost")
    )
    return [ModelUsage(model=r["model_requested"], total_tokens=r["total_tokens"] or 0, request_count=r["request_count"], cost=float(r["cost"] or 0)) for r in results]


@router.get("/by-key", response_model=list[KeyUsage])
async def by_key(
    days: int = Query(7, ge=1, le=90),
    _: Admin = Depends(get_current_admin),
):
    start = datetime.now(timezone.utc) - timedelta(days=days)
    results = (
        await RequestLog.filter(created_at__gte=start)
        .group_by("api_key_id", "api_key_name")
        .annotate(total_tokens=Sum("total_tokens"), request_count=Count("id"), cost=Sum("cost"))
        .order_by("-total_tokens")
        .limit(20)
        .values("api_key_id", "api_key_name", "total_tokens", "request_count", "cost")
    )
    return [KeyUsage(key_id=r["api_key_id"], key_name=r["api_key_name"], total_tokens=r["total_tokens"] or 0, request_count=r["request_count"], cost=float(r["cost"] or 0)) for r in results]
