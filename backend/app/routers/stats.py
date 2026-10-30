from datetime import datetime, timedelta, timezone

from fastapi import Depends, APIRouter, Query
from tortoise import connections
from tortoise.functions import Sum

from app.models import User, APIKey, Channel, Tenant, UsageDaily
from app.schemas.stats import (
    ChannelUsage, ErrorRatePoint, KeyUsage, LatencyStats, LatencyTrendPoint,
    ModelUsage, StatsOverview, TenantUsage, ThroughputStats, UsagePoint,
)
from app.services.auth import require_platform_admin
from app.services.usage_stats import peak_rpm, start_day

router = APIRouter(prefix="/api/stats", tags=["stats"])

# Latency percentiles read individual requests. Cap the rows so a 90-day
# window on a busy gateway stays one bounded query.
LATENCY_SAMPLE = 20_000


def _sql_parts(conn):
    """聚合查询同时兼容生产 MySQL 与测试 SQLite。"""
    sqlite = conn.capabilities.dialect == "sqlite"
    return (
        "?" if sqlite else "%s",
        "strftime('%Y-%m-%d', created_at)" if sqlite
        else "DATE_FORMAT(created_at, '%%Y-%%m-%%d')",
    )


def _totals():
    return {
        "total_tokens": Sum("total_tokens"),
        "request_count": Sum("request_count"),
        "cost": Sum("cost"),
    }


@router.get("/overview", response_model=StatsOverview)
async def overview(_: User = Depends(require_platform_admin)):
    today = datetime.now(timezone.utc).date()
    fields = {**_totals()}
    all_time = await UsageDaily.all().annotate(**fields).values("total_tokens", "request_count", "cost")
    today_row = await UsageDaily.filter(day=today).annotate(**fields).values(
        "total_tokens", "request_count", "cost"
    )
    total = all_time[0] if all_time else {}
    current = today_row[0] if today_row else {}
    return StatsOverview(
        total_requests=int(total.get("request_count") or 0),
        total_tokens=int(total.get("total_tokens") or 0),
        total_cost=float(total.get("cost") or 0),
        active_keys=await APIKey.filter(is_enabled=True).count(),
        active_channels=await Channel.filter(is_enabled=True).count(),
        requests_today=int(current.get("request_count") or 0),
        tokens_today=int(current.get("total_tokens") or 0),
        cost_today=float(current.get("cost") or 0),
    )


@router.get("/usage", response_model=list[UsagePoint])
async def usage(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_platform_admin),
):
    rows = (
        await UsageDaily.filter(day__gte=start_day(days))
        .group_by("day")
        .annotate(
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            **_totals(),
        )
        .order_by("day")
        .values("day", "prompt_tokens", "completion_tokens", "total_tokens", "request_count", "cost")
    )
    return [
        UsagePoint(
            date=str(r["day"]),
            prompt_tokens=int(r["prompt_tokens"] or 0),
            completion_tokens=int(r["completion_tokens"] or 0),
            total_tokens=int(r["total_tokens"] or 0),
            request_count=int(r["request_count"] or 0),
            cost=float(r["cost"] or 0),
        )
        for r in rows
    ]


@router.get("/by-model", response_model=list[ModelUsage])
async def by_model(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_platform_admin),
):
    rows = (
        await UsageDaily.filter(day__gte=start_day(days))
        .group_by("model")
        .annotate(**_totals())
        .order_by("-total_tokens")
        .limit(20)
        .values("model", "total_tokens", "request_count", "cost")
    )
    return [
        ModelUsage(
            model=r["model"],
            total_tokens=int(r["total_tokens"] or 0),
            request_count=int(r["request_count"] or 0),
            cost=float(r["cost"] or 0),
        )
        for r in rows
    ]


@router.get("/by-key", response_model=list[KeyUsage])
async def by_key(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_platform_admin),
):
    rows = (
        await UsageDaily.filter(day__gte=start_day(days))
        .group_by("api_key_id")
        .annotate(**_totals())
        .order_by("-total_tokens")
        .limit(20)
        .values("api_key_id", "total_tokens", "request_count", "cost")
    )
    names = dict(await APIKey.filter(id__in=[r["api_key_id"] for r in rows]).values_list("id", "name"))
    return [
        KeyUsage(
            key_id=r["api_key_id"],
            key_name=names.get(r["api_key_id"], f"#{r['api_key_id']}"),
            total_tokens=int(r["total_tokens"] or 0),
            request_count=int(r["request_count"] or 0),
            cost=float(r["cost"] or 0),
        )
        for r in rows
    ]


@router.get("/by-tenant", response_model=list[TenantUsage])
async def by_team(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_platform_admin),
):
    internal = await Tenant.filter(is_system=True).values_list("id", flat=True)
    rows = (
        await UsageDaily.filter(day__gte=start_day(days), tenant_id__gt=0)
        .exclude(tenant_id__in=list(internal))
        .group_by("tenant_id")
        .annotate(**_totals())
        .order_by("-cost")
        .limit(20)
        .values("tenant_id", "total_tokens", "request_count", "cost")
    )
    names = dict(await Tenant.filter(id__in=[r["tenant_id"] for r in rows]).values_list("id", "name"))
    return [
        TenantUsage(
            tenant_id=r["tenant_id"],
            tenant_name=names.get(r["tenant_id"], f"#{r['tenant_id']}"),
            total_tokens=int(r["total_tokens"] or 0),
            request_count=int(r["request_count"] or 0),
            cost=float(r["cost"] or 0),
        )
        for r in rows
    ]


@router.get("/by-channel", response_model=list[ChannelUsage])
async def by_channel(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_platform_admin),
):
    """按渠道统计请求量、Token 和费用。"""
    rows = (
        await UsageDaily.filter(day__gte=start_day(days))
        .group_by("channel_id")
        .annotate(**_totals())
        .order_by("-cost")
        .limit(20)
        .values("channel_id", "total_tokens", "request_count", "cost")
    )
    names = dict(await Channel.filter(id__in=[r["channel_id"] for r in rows]).values_list("id", "name"))
    return [
        ChannelUsage(
            channel_id=r["channel_id"] or None,
            channel_name=names.get(r["channel_id"], "unknown"),
            total_tokens=int(r["total_tokens"] or 0),
            request_count=int(r["request_count"] or 0),
            cost=float(r["cost"] or 0),
        )
        for r in rows
    ]


@router.get("/error-rate", response_model=list[ErrorRatePoint])
async def error_rate(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_platform_admin),
):
    """每日错误率趋势。"""
    rows = (
        await UsageDaily.filter(day__gte=start_day(days))
        .group_by("day")
        .annotate(total=Sum("request_count"), errors=Sum("error_count"))
        .order_by("day")
        .values("day", "total", "errors")
    )
    points = []
    for r in rows:
        total = int(r["total"] or 0)
        errors = int(r["errors"] or 0)
        points.append(ErrorRatePoint(
            date=str(r["day"]), total=total, errors=errors,
            rate=round(errors / total * 100, 2) if total else 0,
        ))
    return points


def _percentiles(values: list[int]) -> tuple[int, int, int]:
    values.sort()
    n = len(values)
    return (
        values[int(n * 0.50)],
        values[int(n * 0.95)] if n >= 20 else values[-1],
        values[int(n * 0.99)] if n >= 100 else values[-1],
    )


@router.get("/latency", response_model=LatencyStats)
async def latency(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_platform_admin),
):
    """请求延迟 P50/P95/P99 + 按天趋势，取窗口内最近的请求作样本。"""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    conn = connections.get("default")
    ph, day_expr = _sql_parts(conn)
    rows = await conn.execute_query_dict(
        f"SELECT {day_expr} AS `date`, latency_ms FROM request_logs "
        f"WHERE created_at >= {ph} AND status_code > 0 "
        f"ORDER BY id DESC LIMIT {LATENCY_SAMPLE}",
        [start],
    )
    if not rows:
        return LatencyStats(p50=0, p95=0, p99=0, trend=[])

    p50, p95, p99 = _percentiles([r["latency_ms"] for r in rows])
    daily: dict[str, list[int]] = {}
    for r in rows:
        daily.setdefault(r["date"], []).append(r["latency_ms"])
    trend = []
    for date in sorted(daily):
        d50, d95, d99 = _percentiles(daily[date])
        trend.append(LatencyTrendPoint(date=date, p50=d50, p95=d95, p99=d99))
    return LatencyStats(p50=p50, p95=p95, p99=p99, trend=trend)


@router.get("/throughput", response_model=ThroughputStats)
async def throughput(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_platform_admin),
):
    """实时吞吐量：当前 QPS/RPM/TPM + 历史峰值。"""
    conn = connections.get("default")
    ph, _ = _sql_parts(conn)
    current = await conn.execute_query_dict(
        f"SELECT COUNT(*) as cnt, COALESCE(SUM(total_tokens), 0) as tokens "
        f"FROM request_logs WHERE created_at >= {ph}",
        [datetime.now(timezone.utc) - timedelta(seconds=60)],
    )
    current_cnt = current[0]["cnt"] if current else 0
    current_tokens = int(current[0]["tokens"]) if current else 0
    peak = max(await peak_rpm(days), current_cnt)
    return ThroughputStats(
        current_qps=round(current_cnt / 60, 2),
        current_rpm=current_cnt,
        current_tpm=current_tokens,
        peak_qps=round(peak / 60, 2),
        peak_rpm=peak,
    )
