import asyncio
import calendar
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException

from tortoise.expressions import F

from app.models import APIKey, Tenant
from app.services import settlements
from app.services.billing_quotes import snapshot_quotes, estimate_quotes
from app.services.concurrency import concurrency_limiter
from app.services.pricing import estimate_request_tokens
from app.services.rate_limit import rate_limiter
from app.services.spend_windows import exceeded_window

logger = logging.getLogger(__name__)


class QuotaExceeded(Exception):
    _DETAILS = {
        "key": (429, "quota_exceeded", "Key spending quota exceeded"),
        "tenant": (429, "tenant_quota_exceeded", "Tenant spending quota exceeded"),
        "tenant_disabled": (403, "tenant_disabled", "Tenant is disabled"),
        "key_disabled": (401, "key_disabled", "API key is unavailable"),
        "duplicate_request": (409, "duplicate_request", "Internal request already reserved"),
        "key_window": (429, "window_limit", "Key {window} spending limit reached"),
        "tenant_window": (429, "tenant_window_limit", "Tenant {window} spending limit reached"),
    }

    def __init__(self, key_id: int, scope: str = "key", window: str = ""):
        self.key_id, self.scope, self.window = key_id, scope, window
        super().__init__(f"Quota exceeded for {scope} of key {key_id}")

    @property
    def status(self): return self._DETAILS[self.scope][0]

    @property
    def code(self): return self._DETAILS[self.scope][1]

    @property
    def message(self): return self._DETAILS[self.scope][2].format(window=self.window)


async def check_quota(api_key: APIKey) -> bool:
    return api_key.quota_total == -1 or api_key.quota_used < api_key.quota_total


async def deduct_quota(api_key_id: int, cost: Decimal) -> None:
    # Administrative/unit-use helper. Production billing uses settlements.apply().
    if cost > 0:
        await APIKey.filter(id=api_key_id).update(quota_used=F("quota_used") + cost)


async def occupied_quota(scope: str, owner_id: int) -> Decimal:
    return await settlements.occupied(scope, owner_id)


class RequestLease:
    """SQL reservation plus tenant concurrency and both token reservations."""
    def __init__(self, api_key_id: int, request_id: str, tpm_limit: int, tenant_id: int = 0):
        self.api_key_id, self.request_id = api_key_id, request_id
        self.tpm_limit, self.tenant_id = tpm_limit, tenant_id
        self.tenant_tpm_limit = -1
        self.tpm_reserved = self.tenant_tpm_reserved = 0
        self.tenant_lease_id = ""
        self.estimated_input = 0
        self.quotes = {}
        self.reserved = False
        self.dispatched = False
        self.estimated_tokens = 0
        self.closed = False

    async def finish(self, actual_tokens: int) -> None:
        if not self.closed:
            self.closed = True
            await self._clear(actual_tokens)

    async def release(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.reserved:
                if self.dispatched:
                    await settlements.abandon(self.request_id)
                else:
                    await settlements.release(self.request_id)
        finally:
            await self._clear(self.estimated_tokens if self.dispatched else None)

    async def before_send(self):
        if not self.dispatched:
            try:
                await settlements.mark_dispatched(self.request_id)
            except Exception:
                raise HTTPException(503, {"error": {"type": "api_error", "code": "accounting_unavailable",
                                                    "message": "Accounting unavailable; upstream was not called"}}) from None
            self.dispatched = True

    async def _clear(self, actual_tokens):
        for owner, limit, amount, scope in (
            (self.api_key_id, self.tpm_limit, self.tpm_reserved, "key"),
            (self.tenant_id, self.tenant_tpm_limit, self.tenant_tpm_reserved, "tenant"),
        ):
            if amount:
                delta = -amount if actual_tokens is None else actual_tokens - amount
                try:
                    await rate_limiter.adjust_tpm(owner, limit, delta, scope=scope)
                except Exception:
                    logger.exception("TPM reconciliation failed owner=%s scope=%s", owner, scope)
        if self.tenant_lease_id:
            try:
                await concurrency_limiter.release(self.tenant_id, self.tenant_lease_id, scope="tenant")
            except Exception:
                logger.exception("Tenant concurrency release failed tenant=%s", self.tenant_id)


async def begin_request_budget(api_key: APIKey, request_id: str, body: dict | None, *,
                               default_output: int | None = None, request_units: int = 0,
                               candidates: list | None = None, input_tokens_override: int | None = None) -> RequestLease:
    tenant = await Tenant.get_or_none(id=api_key.tenant_id, is_enabled=True)
    if tenant is None:
        raise QuotaExceeded(api_key.id, "tenant_disabled")
    lease = RequestLease(api_key.id, request_id or str(uuid.uuid4()), api_key.tpm_limit, tenant.id)
    lease.tenant_tpm_limit = tenant.tpm_limit
    input_tokens, output_tokens = estimate_request_tokens(body, default_output)
    if input_tokens_override is not None:
        input_tokens = input_tokens_override
    lease.estimated_input = input_tokens
    try:
        for scope, owner in (("key", api_key), ("tenant", tenant)):
            # Preserve the existing Redis namespace when evolving Team into Tenant.
            window = await exceeded_window("team" if scope == "tenant" else scope, owner.id, owner.window_limits)
            if window:
                raise QuotaExceeded(api_key.id, f"{scope}_window", window)
        lease.quotes = await snapshot_quotes(str((body or {}).get("model") or ""), candidates)
        estimate = estimate_quotes(lease.quotes, input_tokens, output_tokens, request_units)
        tokens = input_tokens + output_tokens
        lease.estimated_tokens = tokens
        await rate_limiter.reserve_tpm(api_key.id, api_key.tpm_limit, tokens)
        if api_key.tpm_limit != -1:
            lease.tpm_reserved = tokens
        await rate_limiter.reserve_tpm(tenant.id, tenant.tpm_limit, tokens, scope="tenant")
        if tenant.tpm_limit != -1:
            lease.tenant_tpm_reserved = tokens
        try:
            await settlements.reserve(lease.request_id, api_key, estimate, lease.quotes)
        except settlements.BudgetDenied as exc:
            raise QuotaExceeded(api_key.id, exc.scope)
        lease.reserved = True
        lease.tenant_lease_id = await concurrency_limiter.acquire(tenant.id, tenant.concurrent_limit, scope="tenant")
    except BaseException:
        await lease.release()
        raise
    return lease


async def reset_expired_quotas() -> int:
    return await _reset_monthly(APIKey) + await _reset_monthly(Tenant)


async def _reset_monthly(model) -> int:
    now = datetime.now(timezone.utc)
    last_day = calendar.monthrange(now.year, now.month)[1]
    changed = 0
    for owner in await model.filter(quota_reset_day__isnull=False):
        day = min(owner.quota_reset_day, last_day)
        target = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
        if now < target or (owner.quota_last_reset_at and owner.quota_last_reset_at >= target):
            continue
        # Do not reset across reservations or pending usage. Conditional update avoids a lost debit.
        scope = "tenant" if model is Tenant else "key"
        if await settlements.occupied(scope, owner.id) > 0:
            continue
        changed += await model.filter(id=owner.id, quota_last_reset_at=owner.quota_last_reset_at,
                                      quota_used=owner.quota_used).update(
            quota_used=0, quota_last_reset_at=now,
        )
    return changed


async def quota_reset_loop():
    while True:
        try:
            await reset_expired_quotas()
        except Exception:
            logger.exception("Quota reset unavailable")
        await asyncio.sleep(3600)
