"""Running totals for statistics, so dashboards do not scan request_logs."""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tortoise import connections

from app import dependencies

logger = logging.getLogger(__name__)

PEAK_PREFIX = "five:peak_rpm:"
MINUTE_PREFIX = "five:rpm_minute:"
PEAK_TTL = 92 * 86400

_COLUMNS = (
    "day", "api_key_id", "api_key_name", "tenant_id", "model", "channel_id",
    "channel_name", "request_count", "error_count", "prompt_tokens",
    "completion_tokens", "total_tokens", "cost", "cached_tokens",
    "cache_write_tokens", "cache_savings", "upstream_cost",
)
_SUMMED = (
    "request_count", "error_count", "prompt_tokens",
    "completion_tokens", "total_tokens", "cost", "cached_tokens",
    "cache_write_tokens", "cache_savings", "upstream_cost",
)


def _upsert_sql(dialect: str) -> str:
    cols = ", ".join(_COLUMNS)
    if dialect == "sqlite":
        values = ", ".join("?" for _ in _COLUMNS)
        sums = ", ".join(f"{c} = {c} + excluded.{c}" for c in _SUMMED)
        return (
            f"INSERT INTO usage_daily ({cols}) VALUES ({values}) "
            f"ON CONFLICT(day, api_key_id, model, channel_id) DO UPDATE SET {sums}, "
            "api_key_name = excluded.api_key_name, channel_name = excluded.channel_name, "
            "tenant_id = excluded.tenant_id"
        )
    values = ", ".join("%s" for _ in _COLUMNS)
    # Row alias needs MySQL 8.0.19+. VALUES(col) is deprecated and warns on every insert.
    sums = ", ".join(f"{c} = usage_daily.{c} + new.{c}" for c in _SUMMED)
    return (
        f"INSERT INTO usage_daily ({cols}) VALUES ({values}) AS new "
        f"ON DUPLICATE KEY UPDATE {sums}, api_key_name = new.api_key_name, "
        "channel_name = new.channel_name, tenant_id = new.tenant_id"
    )


async def record_daily_usage(
    *,
    api_key_id: int,
    api_key_name: str,
    tenant_id: int,
    model: str,
    channel_id: int | None,
    channel_name: str,
    status_code: int,
    prompt_tokens: int,
    completion_tokens: int,
    cost: Decimal,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_savings: Decimal = Decimal(0),
    when: datetime | None = None,
    upstream_cost: Decimal = Decimal(0),
    realtime: bool = True,
) -> None:
    when = when or datetime.now(timezone.utc)
    conn = connections.get("default")
    params = [
        when.date().isoformat(), api_key_id, api_key_name[:128], tenant_id or 0,
        model[:64], channel_id or 0, channel_name[:128], 1,
        1 if status_code >= 400 else 0,
        prompt_tokens, completion_tokens, prompt_tokens + completion_tokens,
        str(cost), cached_tokens, cache_write_tokens, str(cache_savings), str(upstream_cost),
    ]
    await conn.execute_query(_upsert_sql(conn.capabilities.dialect), params)
    if realtime:
        await _record_minute(when)


async def _record_minute(when: datetime) -> None:
    """Per-minute request count in Redis, keeping the busiest minute of each day."""
    r = await dependencies.get_redis()
    minute_key = f"{MINUTE_PREFIX}{when:%Y%m%d%H%M}"
    count = await r.incr(minute_key)
    if count == 1:
        await r.expire(minute_key, 7200)
    peak_key = f"{PEAK_PREFIX}{when:%Y%m%d}"
    current = await r.get(peak_key)
    if current is None or count > int(current):
        await r.set(peak_key, count, ex=PEAK_TTL)


async def peak_rpm(days: int) -> int:
    r = await dependencies.get_redis()
    today = datetime.now(timezone.utc).date()
    peak = 0
    for offset in range(days):
        value = await r.get(f"{PEAK_PREFIX}{today - timedelta(days=offset):%Y%m%d}")
        if value is not None:
            peak = max(peak, int(value))
    return peak


def start_day(days: int) -> date:
    """First day included in a `days`-long window ending today (UTC)."""
    return datetime.now(timezone.utc).date() - timedelta(days=days - 1)
