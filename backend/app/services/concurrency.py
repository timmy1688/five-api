from app.dependencies import get_redis

ACQUIRE_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, ttl)
end
if current > limit then
    redis.call('DECR', key)
    return 0
end
return 1
"""

RELEASE_SCRIPT = """
local key = KEYS[1]
local val = redis.call('DECR', key)
if val < 0 then
    redis.call('SET', key, 0, 'EX', tonumber(ARGV[1]))
end
return val
"""


class ConcurrencyLimiter:
    KEY_PREFIX = "five:concurrency:"
    TTL = 120

    async def acquire(self, key_id: int, limit: int) -> None:
        r = await get_redis()
        rk = f"{self.KEY_PREFIX}{key_id}"
        result = await r.eval(ACQUIRE_SCRIPT, 1, rk, limit, self.TTL)
        if result == 0:
            raise ConcurrencyExceeded(key_id, limit)

    async def release(self, key_id: int) -> None:
        r = await get_redis()
        rk = f"{self.KEY_PREFIX}{key_id}"
        await r.eval(RELEASE_SCRIPT, 1, rk, self.TTL)


class ConcurrencyExceeded(Exception):
    def __init__(self, key_id: int, limit: int):
        self.key_id = key_id
        self.limit = limit
        super().__init__(f"Key {key_id} concurrent limit {limit} exceeded")


concurrency_limiter = ConcurrencyLimiter()
