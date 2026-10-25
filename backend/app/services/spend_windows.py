"""Rolling USD caps over 5 hours, a day and a week.

Spend lands in hourly Redis buckets, so a window covers the current hour plus
the previous N-1 full hours. The check uses settled spend: once a cap is
reached new requests stop, and requests already in flight still finish.
"""

import time
from datetime import datetime
from decimal import Decimal

from app import dependencies

WINDOWS: dict[str, int] = {"5h": 5, "1d": 24, "7d": 168}
BUCKET_PREFIX = "five:spend:"
BUCKET_TTL = 8 * 86400
MICRO = Decimal("1000000")

# One marker and both counters change atomically. Recovery can safely replay this operation.
SETTLEMENT_SPEND_SCRIPT = """
-- settlement_spend_v1
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('SET', KEYS[1], '1', 'EX', ARGV[2])
for i = 2, #KEYS do
    redis.call('INCRBY', KEYS[i], ARGV[1])
    redis.call('EXPIRE', KEYS[i], ARGV[2])
end
return 1
"""


async def record_settlement_spend(request_id: str, key_id: int, tenant_id: int, cost: Decimal, when: datetime):
    r = await dependencies.get_redis()
    hour = int(when.timestamp() // 3600)
    await r.eval(SETTLEMENT_SPEND_SCRIPT, 3, f"five:settled:{request_id}",
                 _bucket("key", key_id, hour), _bucket("team", tenant_id, hour),
                 max(0, int(cost * MICRO)), BUCKET_TTL)


def normalize_limits(value) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    limits: dict[str, float] = {}
    for window in WINDOWS:
        raw = value.get(window)
        if raw is None or raw == "":
            continue
        try:
            amount = round(float(raw), 6)
        except (TypeError, ValueError):
            continue
        if amount >= 0:
            limits[window] = amount
    return limits


def _hour() -> int:
    return int(time.time() // 3600)


def _bucket(scope: str, owner_id: int, hour: int) -> str:
    return f"{BUCKET_PREFIX}{scope}:{owner_id}:{hour}"


async def record_spend(scope: str, owner_id: int, cost: Decimal) -> None:
    micro = int(cost * MICRO)
    if micro <= 0:
        return
    r = await dependencies.get_redis()
    key = _bucket(scope, owner_id, _hour())
    await r.incrby(key, micro)
    await r.expire(key, BUCKET_TTL)


async def window_spend(scope: str, owner_id: int) -> dict[str, float]:
    now = _hour()
    longest = max(WINDOWS.values())
    r = await dependencies.get_redis()
    values = await r.mget([_bucket(scope, owner_id, now - offset) for offset in range(longest)])
    amounts = [int(v or 0) for v in values]
    return {
        window: float(Decimal(sum(amounts[:hours])) / MICRO)
        for window, hours in WINDOWS.items()
    }


async def exceeded_window(scope: str, owner_id: int, limits: dict | None) -> str | None:
    """The first window whose cap is already used up."""
    limits = normalize_limits(limits)
    if not limits:
        return None
    spent = await window_spend(scope, owner_id)
    for window, cap in limits.items():
        if spent[window] >= cap:
            return window
    return None


async def reset_windows(scope: str, owner_id: int) -> None:
    now = _hour()
    r = await dependencies.get_redis()
    await r.delete(*[_bucket(scope, owner_id, now - offset) for offset in range(max(WINDOWS.values()))])
