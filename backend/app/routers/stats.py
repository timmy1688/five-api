from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from tortoise.functions import Count, Sum

from app.models import User, APIKey, Channel, RequestLog
from app.schemas.stats import (
    ChannelUsage, ErrorRatePoint, KeyUsage, LatencyStats, LatencyTrendPoint,
    ModelUsage, StatsOverview, ThroughputStats, UsagePoint,
)
from app.services.auth import require_permission

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview", response_model=StatsOverview)
async def overview(_: User = require_permission("stat:read")):
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
    _: User = require_permission("stat:read"),
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
    _: User = require_permission("stat:read"),
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
    _: User = require_permission("stat:read"),
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


@router.get("/by-channel", response_model=list[ChannelUsage])
async def by_channel(
    days: int = Query(7, ge=1, le=90),
    _: User = require_permission("stat:read"),
):
    """按渠道统计请求量、Token 和费用。"""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    results = (
        await RequestLog.filter(created_at__gte=start)
        .group_by("channel_id", "channel_name")
        .annotate(total_tokens=Sum("total_tokens"), request_count=Count("id"), cost=Sum("cost"))
        .order_by("-cost")
        .limit(20)
        .values("channel_id", "channel_name", "total_tokens", "request_count", "cost")
    )
    return [ChannelUsage(channel_id=r["channel_id"], channel_name=r["channel_name"] or "unknown", total_tokens=r["total_tokens"] or 0, request_count=r["request_count"], cost=float(r["cost"] or 0)) for r in results]


@router.get("/error-rate", response_model=list[ErrorRatePoint])
async def error_rate(
    days: int = Query(7, ge=1, le=90),
    _: User = require_permission("stat:read"),
):
    """每日错误率趋势。"""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    from tortoise import connections

    conn = connections.get("default")
    rows = await conn.execute_query_dict(
        """
        SELECT
            DATE_FORMAT(created_at, '%%Y-%%m-%%d') as `date`,
            COUNT(*) as total,
            SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) as errors
        FROM request_logs
        WHERE created_at >= %s
        GROUP BY DATE_FORMAT(created_at, '%%Y-%%m-%%d')
        ORDER BY `date`
        """,
        [start],
    )
    return [ErrorRatePoint(date=r["date"], total=r["total"], errors=int(r["errors"] or 0), rate=round(int(r["errors"] or 0) / r["total"] * 100, 2) if r["total"] > 0 else 0) for r in rows]


@router.get("/latency", response_model=LatencyStats)
async def latency(
    days: int = Query(7, ge=1, le=90),
    _: User = require_permission("stat:read"),
):
    """请求延迟 P50/P95/P99 + 按天趋势。"""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    from tortoise import connections

    conn = connections.get("default")

    # 整体百分位
    rows = await conn.execute_query_dict(
        "SELECT latency_ms FROM request_logs WHERE created_at >= %s AND status_code > 0 ORDER BY latency_ms",
        [start],
    )
    if not rows:
        return LatencyStats(p50=0, p95=0, p99=0, trend=[])

    latencies = [r["latency_ms"] for r in rows]
    n = len(latencies)
    p50 = latencies[int(n * 0.50)]
    p95 = latencies[int(n * 0.95)] if n >= 20 else latencies[-1]
    p99 = latencies[int(n * 0.99)] if n >= 100 else latencies[-1]

    # 按天趋势
    daily_rows = await conn.execute_query_dict(
        """
        SELECT DATE_FORMAT(created_at, '%%Y-%%m-%%d') as `date`, latency_ms
        FROM request_logs
        WHERE created_at >= %s AND status_code > 0
        ORDER BY `date`, latency_ms
        """,
        [start],
    )
    daily: dict[str, list[int]] = {}
    for r in daily_rows:
        daily.setdefault(r["date"], []).append(r["latency_ms"])

    trend = []
    for date in sorted(daily):
        vals = daily[date]
        dn = len(vals)
        trend.append(LatencyTrendPoint(
            date=date,
            p50=vals[int(dn * 0.50)],
            p95=vals[int(dn * 0.95)] if dn >= 20 else vals[-1],
            p99=vals[int(dn * 0.99)] if dn >= 100 else vals[-1],
        ))

    return LatencyStats(p50=p50, p95=p95, p99=p99, trend=trend)


@router.get("/throughput", response_model=ThroughputStats)
async def throughput(
    days: int = Query(7, ge=1, le=90),
    _: User = require_permission("stat:read"),
):
    """实时吞吐量：当前 QPS/RPM/TPM + 历史峰值。"""
    from tortoise import connections

    conn = connections.get("default")

    # 最近 60 秒的请求数和 Token 总量
    current = await conn.execute_query_dict(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(total_tokens), 0) as tokens FROM request_logs WHERE created_at >= NOW() - INTERVAL 60 SECOND"
    )
    current_cnt = current[0]["cnt"] if current else 0
    current_tokens = int(current[0]["tokens"]) if current else 0

    # 选定天数内按分钟聚合的峰值
    start = datetime.now(timezone.utc) - timedelta(days=days)
    peak = await conn.execute_query_dict(
        """
        SELECT MAX(cnt) as peak_rpm FROM (
            SELECT COUNT(*) as cnt
            FROM request_logs
            WHERE created_at >= %s
            GROUP BY DATE_FORMAT(created_at, '%%Y-%%m-%%d %%H:%%i')
        ) sub
        """,
        [start],
    )
    peak_rpm = int(peak[0]["peak_rpm"] or 0) if peak else 0

    return ThroughputStats(
        current_qps=round(current_cnt / 60, 2),
        current_rpm=current_cnt,
        current_tpm=current_tokens,
        peak_qps=round(peak_rpm / 60, 2),
        peak_rpm=peak_rpm,
    )
