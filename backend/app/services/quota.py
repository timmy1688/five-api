import asyncio
import calendar
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING

from tortoise.expressions import F

from app.dependencies import get_redis
from app.models import APIKey, Team
from app.services.pricing import estimate_request_tokens, estimate_upper_cost
from app.services.rate_limit import rate_limiter

logger = logging.getLogger(__name__)

MICRO = Decimal("1000000")
HOLD_TTL = 600
HOLD_PREFIX = "five:quota:hold:"
TEAM_HOLD_PREFIX = "five:quota:team_hold:"

QUOTA_RESERVE_SCRIPT = """
local key = KEYS[1]
local request_id = ARGV[1]
local estimate = tonumber(ARGV[2])
local used = tonumber(ARGV[3])
local total = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
if redis.call('HEXISTS', key, request_id) == 1 then
    return 1
end
local sum = 0
local vals = redis.call('HVALS', key)
for _, value in ipairs(vals) do
    sum = sum + tonumber(value)
end
if used >= total or used + sum + estimate > total then
    return 0
end
redis.call('HSET', key, request_id, estimate)
redis.call('EXPIRE', key, ttl)
return 1
"""

QUOTA_RELEASE_SCRIPT = """
local key = KEYS[1]
redis.call('HDEL', key, ARGV[1])
if redis.call('HLEN', key) == 0 then
    redis.call('DEL', key)
end
return 1
"""


class QuotaExceeded(Exception):
    def __init__(self, key_id: int, scope: str = "key"):
        self.key_id = key_id
        self.scope = scope
        super().__init__(f"Quota exceeded for {scope} of key {key_id}")

    _DETAILS = {
        "key": (429, "quota_exceeded", "Spending quota exceeded"),
        "team": (429, "team_quota_exceeded", "Team spending quota exceeded"),
        "team_disabled": (403, "team_disabled", "Team is disabled"),
    }

    @property
    def status(self) -> int:
        return self._DETAILS[self.scope][0]

    @property
    def code(self) -> str:
        return self._DETAILS[self.scope][1]

    @property
    def message(self) -> str:
        return self._DETAILS[self.scope][2]


def _micro(amount: Decimal) -> int:
    if amount <= 0:
        return 0
    return int((amount * MICRO).to_integral_value(rounding=ROUND_CEILING))


async def check_quota(api_key: APIKey) -> bool:
    if api_key.quota_total == Decimal("-1"):
        return True
    return api_key.quota_used < api_key.quota_total


async def deduct_quota(api_key_id: int, cost: Decimal) -> None:
    if cost <= 0:
        return
    await APIKey.filter(id=api_key_id).update(quota_used=F("quota_used") + cost)


async def deduct_team_quota(team_id: int, cost: Decimal) -> None:
    if cost <= 0:
        return
    await Team.filter(id=team_id).update(quota_used=F("quota_used") + cost)


async def _hold(hold_key: str, request_id: str, estimate: Decimal, used: Decimal, total: Decimal) -> bool:
    r = await get_redis()
    result = await r.eval(
        QUOTA_RESERVE_SCRIPT,
        1,
        hold_key,
        request_id,
        _micro(estimate),
        _micro(used),
        _micro(total),
        HOLD_TTL,
    )
    return result != 0


async def reserve_quota(api_key: APIKey, request_id: str, estimate: Decimal) -> bool:
    """Hold an estimated cost until the request settles. Unlimited keys hold nothing."""
    if api_key.quota_total == Decimal("-1"):
        return False
    fresh = await APIKey.get(id=api_key.id)
    if not await _hold(
        f"{HOLD_PREFIX}{api_key.id}", request_id, estimate, fresh.quota_used, fresh.quota_total,
    ):
        raise QuotaExceeded(api_key.id)
    return True


async def reserve_team_quota(api_key: APIKey, team: Team, request_id: str, estimate: Decimal) -> bool:
    """Same hold against the team's shared budget. Holds from every key in the team add up."""
    if team.quota_total == Decimal("-1"):
        return False
    if not await _hold(
        f"{TEAM_HOLD_PREFIX}{team.id}", request_id, estimate, team.quota_used, team.quota_total,
    ):
        raise QuotaExceeded(api_key.id, scope="team")
    return True


async def release_quota(api_key_id: int, request_id: str) -> None:
    r = await get_redis()
    await r.eval(QUOTA_RELEASE_SCRIPT, 1, f"{HOLD_PREFIX}{api_key_id}", request_id)


async def release_team_quota(team_id: int, request_id: str) -> None:
    r = await get_redis()
    await r.eval(QUOTA_RELEASE_SCRIPT, 1, f"{TEAM_HOLD_PREFIX}{team_id}", request_id)


class RequestLease:
    """Quota hold and TPM reservation for one request. Release is idempotent."""

    def __init__(self, api_key_id: int, request_id: str, tpm_limit: int, team_id: int = 0):
        self.api_key_id = api_key_id
        self.request_id = request_id
        self.tpm_limit = tpm_limit
        self.team_id = team_id
        self.quota_held = False
        self.team_held = False
        self.tpm_reserved = 0
        self.estimated_input = 0
        self.closed = False

    async def settle(self, cost: Decimal, actual_tokens: int) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if cost > 0:
                await deduct_quota(self.api_key_id, cost)
                if self.team_id:
                    await deduct_team_quota(self.team_id, cost)
        finally:
            await self._clear(actual_tokens)

    async def release(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self._clear(None)

    async def _clear(self, actual_tokens: int | None) -> None:
        if self.quota_held:
            self.quota_held = False
            try:
                await release_quota(self.api_key_id, self.request_id)
            except Exception:
                logger.exception("quota release failed for key %s", self.api_key_id)
        if self.team_held:
            self.team_held = False
            try:
                await release_team_quota(self.team_id, self.request_id)
            except Exception:
                logger.exception("quota release failed for team %s", self.team_id)
        if self.tpm_reserved:
            reserved = self.tpm_reserved
            self.tpm_reserved = 0
            delta = -reserved if actual_tokens is None else actual_tokens - reserved
            try:
                await rate_limiter.adjust_tpm(self.api_key_id, self.tpm_limit, delta)
            except Exception:
                logger.exception("tpm adjust failed for key %s", self.api_key_id)


async def begin_request_budget(
    api_key: APIKey,
    request_id: str,
    body: dict | None,
    *,
    default_output: int | None = None,
    request_units: int = 0,
) -> RequestLease:
    """Reserve TPM and an estimated quota hold before the upstream call."""
    team = None
    if api_key.team_id:
        team = await Team.get_or_none(id=api_key.team_id)
    lease = RequestLease(
        api_key.id,
        request_id or uuid.uuid4().hex,
        api_key.tpm_limit,
        team.id if team else 0,
    )
    input_tokens, output_tokens = estimate_request_tokens(body, default_output)
    lease.estimated_input = input_tokens
    try:
        if team and not team.is_enabled:
            raise QuotaExceeded(api_key.id, scope="team_disabled")
        await rate_limiter.reserve_tpm(
            api_key.id, api_key.tpm_limit, input_tokens + output_tokens
        )
        if api_key.tpm_limit != -1:
            lease.tpm_reserved = input_tokens + output_tokens
        model = ""
        if isinstance(body, dict):
            model = str(body.get("model") or "")
        estimate = await estimate_upper_cost(
            model, body, default_output=default_output, request_units=request_units,
        )
        lease.quota_held = await reserve_quota(api_key, lease.request_id, estimate)
        if team:
            lease.team_held = await reserve_team_quota(api_key, team, lease.request_id, estimate)
    except Exception:
        await lease.release()
        raise
    return lease


async def reset_expired_quotas() -> int:
    """Monthly reset for keys and teams that set a reset day."""
    return await _reset_monthly(APIKey) + await _reset_monthly(Team)


async def _reset_monthly(model) -> int:
    now = datetime.now(timezone.utc)
    today = now.day
    last_day_of_month = calendar.monthrange(now.year, now.month)[1]

    keys = await model.filter(quota_reset_day__isnull=False)
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

        await model.filter(id=key.id).update(
            quota_used=Decimal(0),
            quota_last_reset_at=now,
        )
        reset_count += 1

    if reset_count:
        logger.info("Reset quota for %d %s row(s)", reset_count, model.__name__)
    return reset_count


async def quota_reset_loop() -> None:
    while True:
        try:
            await reset_expired_quotas()
        except Exception:
            logger.exception("Error in quota reset loop")
        await asyncio.sleep(3600)
