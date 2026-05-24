from app.dependencies import get_redis

RPM_KEY = "five:rpm:"
WINDOW = 60

RPM_CHECK_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, tonumber(ARGV[2]))
end
if current > limit then
    redis.call('DECR', key)
    return 0
end
return 1
"""


class RPMExceeded(Exception):
    def __init__(self, key_id: int, limit: int):
        self.key_id = key_id
        self.limit = limit
        super().__init__(f"RPM limit {limit} exceeded for key {key_id}")


class RateLimiter:
    async def check_rpm(self, key_id: int, limit: int) -> None:
        if limit == -1:
            return
        r = await get_redis()
        result = await r.eval(RPM_CHECK_SCRIPT, 1, f"{RPM_KEY}{key_id}", limit, WINDOW)
        if result == 0:
            raise RPMExceeded(key_id, limit)


rate_limiter = RateLimiter()
