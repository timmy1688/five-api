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


class TPMExceeded(Exception):
    def __init__(self, key_id: int, limit: int):
        self.key_id = key_id
        self.limit = limit
        super().__init__(f"TPM limit {limit} exceeded for key {key_id}")


TPM_KEY = "five:tpm:"

TPM_RESERVE_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local amount = tonumber(ARGV[2])
local window = tonumber(ARGV[3])
local next = redis.call('INCRBY', key, amount)
if next == amount then
    redis.call('EXPIRE', key, window)
end
if next > limit then
    redis.call('DECRBY', key, amount)
    return 0
end
return 1
"""

TPM_ADJUST_SCRIPT = """
local key = KEYS[1]
local delta = tonumber(ARGV[1])
if redis.call('EXISTS', key) == 0 or delta == 0 then
    return 1
end
local next = redis.call('INCRBY', key, delta)
if next <= 0 then
    redis.call('DEL', key)
end
return 1
"""


class RateLimiter:
    async def check_rpm(self, key_id: int, limit: int) -> None:
        if limit == -1:
            return
        r = await get_redis()
        result = await r.eval(RPM_CHECK_SCRIPT, 1, f"{RPM_KEY}{key_id}", limit, WINDOW)
        if result == 0:
            raise RPMExceeded(key_id, limit)

    async def reserve_tpm(self, key_id: int, limit: int, tokens: int) -> None:
        if limit == -1 or tokens <= 0:
            return
        r = await get_redis()
        result = await r.eval(
            TPM_RESERVE_SCRIPT, 1, f"{TPM_KEY}{key_id}", limit, tokens, WINDOW
        )
        if result == 0:
            raise TPMExceeded(key_id, limit)

    async def adjust_tpm(self, key_id: int, limit: int, delta: int) -> None:
        if limit == -1 or delta == 0:
            return
        r = await get_redis()
        await r.eval(TPM_ADJUST_SCRIPT, 1, f"{TPM_KEY}{key_id}", delta)


rate_limiter = RateLimiter()
