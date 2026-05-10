import asyncio
import calendar
import logging
from datetime import datetime, timezone
from decimal import Decimal

from tortoise.expressions import F

from app.models import APIKey

logger = logging.getLogger(__name__)


async def check_quota(api_key: APIKey) -> bool:
    if api_key.quota_total == Decimal("-1"):
        return True
    return api_key.quota_used < api_key.quota_total


async def deduct_quota(api_key_id: int, cost: Decimal) -> None:
    if cost <= 0:
        return
    await APIKey.filter(id=api_key_id).update(quota_used=F("quota_used") + cost)


async def reset_expired_quotas() -> int:
    now = datetime.now(timezone.utc)
    today = now.day
    last_day_of_month = calendar.monthrange(now.year, now.month)[1]

    keys = await APIKey.filter(quota_reset_day__isnull=False)
    reset_count = 0

    for key in keys:
        reset_day = key.quota_reset_day
        effective_day = min(reset_day, last_day_of_month)

        if today < effective_day:
            continue

        if key.quota_last_reset_at is not None:
            last_reset = key.quota_last_reset_at
            if last_reset.tzinfo is None:
                last_reset = last_reset.replace(tzinfo=timezone.utc)
            target = last_reset.replace(
                year=now.year, month=now.month, day=effective_day,
                hour=0, minute=0, second=0, microsecond=0,
            )
            if last_reset >= target:
                continue

        await APIKey.filter(id=key.id).update(
            quota_used=Decimal(0),
            quota_last_reset_at=now,
        )
        reset_count += 1

    if reset_count:
        logger.info("Reset quota for %d key(s)", reset_count)
    return reset_count


async def quota_reset_loop() -> None:
    while True:
        try:
            await reset_expired_quotas()
        except Exception:
            logger.exception("Error in quota reset loop")
        await asyncio.sleep(3600)
