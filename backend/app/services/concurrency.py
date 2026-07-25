import asyncio
import logging
import time
import uuid
from contextlib import suppress

from app.dependencies import get_redis

logger = logging.getLogger(__name__)

ACQUIRE_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local member = ARGV[3]
local now = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) >= limit then
    return 0
end
redis.call('ZADD', key, now + ttl, member)
redis.call('EXPIRE', key, ttl + 60)
return 1
"""

REFRESH_SCRIPT = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local member = ARGV[2]
local now = tonumber(ARGV[3])
if redis.call('ZSCORE', key, member) == false then
    return 0
end
redis.call('ZADD', key, now + ttl, member)
redis.call('EXPIRE', key, ttl + 60)
return 1
"""

RELEASE_SCRIPT = """
local key = KEYS[1]
local removed = redis.call('ZREM', key, ARGV[1])
if redis.call('ZCARD', key) == 0 then
    redis.call('DEL', key)
end
return removed
"""


class ConcurrencyLimiter:
    KEY_PREFIX = "five:concurrency:"
    LEASE_TTL = 180
    REFRESH_INTERVAL = 60

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}

    async def acquire(self, key_id: int, limit: int) -> str:
        r = await get_redis()
        rk = f"{self.KEY_PREFIX}{key_id}"
        lease_id = uuid.uuid4().hex
        now = int(time.time())
        result = await r.eval(
            ACQUIRE_SCRIPT, 1, rk, limit, self.LEASE_TTL, lease_id, now
        )
        if result == 0:
            raise ConcurrencyExceeded(key_id, limit)
        self._tasks[lease_id] = asyncio.create_task(
            self._keepalive(key_id, lease_id)
        )
        return lease_id

    async def _keepalive(self, key_id: int, lease_id: str) -> None:
        rk = f"{self.KEY_PREFIX}{key_id}"
        try:
            while True:
                await asyncio.sleep(self.REFRESH_INTERVAL)
                r = await get_redis()
                now = int(time.time())
                refreshed = await r.eval(
                    REFRESH_SCRIPT, 1, rk, self.LEASE_TTL, lease_id, now
                )
                if refreshed == 0:
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Failed to refresh concurrency lease for key %s", key_id)

    async def release(self, key_id: int, lease_id: str) -> None:
        task = self._tasks.pop(lease_id, None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        r = await get_redis()
        rk = f"{self.KEY_PREFIX}{key_id}"
        await r.eval(RELEASE_SCRIPT, 1, rk, lease_id)


class ConcurrencyExceeded(Exception):
    def __init__(self, key_id: int, limit: int):
        self.key_id = key_id
        self.limit = limit
        super().__init__(f"Key {key_id} concurrent limit {limit} exceeded")


concurrency_limiter = ConcurrencyLimiter()
