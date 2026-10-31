"""Coordination between Uvicorn workers that share one MySQL and Redis.

Each worker publishes a heartbeat so recovery only takes over reservations of workers
that have exited. Periodic jobs claim a Redis token per period, so one worker runs each
period and another takes over when it stops.
"""
import asyncio
import logging
import os
from uuid import uuid4

from app import dependencies
from app.config import settings

logger = logging.getLogger(__name__)
OWNER_ID = str(uuid4())
PROCESS_KEY_PREFIX = "five:process:"
CLAIM_KEY_PREFIX = "five:claim:"


def heartbeat_interval() -> float:
    return max(1.0, settings.PROCESS_STALE_SECONDS / 6)


async def beat() -> None:
    redis = await dependencies.get_redis()
    await redis.set(PROCESS_KEY_PREFIX + OWNER_ID, str(os.getpid()), ex=max(1, settings.PROCESS_STALE_SECONDS))


async def heartbeat_loop() -> None:
    while True:
        await asyncio.sleep(heartbeat_interval())
        try:
            await beat()
        except Exception:
            logger.exception("Worker heartbeat unavailable")


async def leave() -> None:
    redis = await dependencies.get_redis()
    await redis.delete(PROCESS_KEY_PREFIX + OWNER_ID)


async def live_owners(owners: list[str]) -> set[str]:
    """Raises when Redis is unavailable; callers must then treat every owner as alive."""
    if not owners:
        return set()
    redis = await dependencies.get_redis()
    values = await redis.mget([PROCESS_KEY_PREFIX + owner for owner in owners])
    return {owner for owner, value in zip(owners, values) if value is not None}


async def claim(name: str, seconds: float) -> bool:
    """True for exactly one caller per period across all workers."""
    redis = await dependencies.get_redis()
    return bool(await redis.set(CLAIM_KEY_PREFIX + name, OWNER_ID, nx=True, ex=max(1, int(seconds))))
