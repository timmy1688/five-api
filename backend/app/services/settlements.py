"""Durable reservations and idempotent accounting in the same SQL transaction."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from tortoise.exceptions import IntegrityError
from tortoise.expressions import F
from tortoise.functions import Sum
from tortoise.transactions import in_transaction

from app.models import APIKey, RequestLog, Settlement, Tenant
from app.services.logging_service import save_request_log, observe_request_log
from app.services.redaction import redact

logger = logging.getLogger(__name__)
OWNER_ID = str(uuid4())
OCCUPIED_STATES = ("reserved", "pending", "failed", "uncertain")
MAX_ATTEMPTS = 8
# Fields that older releases wrote into pending payloads and request logs no longer have.
LEGACY_PAYLOAD_FIELDS = frozenset({"upstream_cost"})
_unsaved: dict[str, tuple[dict, Decimal | None, str]] = {}


class BudgetDenied(Exception):
    def __init__(self, scope):
        self.scope = scope


async def occupied(scope: str, owner_id: int) -> Decimal:
    field = "tenant_id" if scope == "tenant" else "api_key_id"
    rows = await Settlement.filter(**{field: owner_id}, state__in=OCCUPIED_STATES).annotate(
        amount=Sum("occupied"),
    ).values("amount")
    return Decimal(str(rows[0]["amount"] or 0)) if rows else Decimal(0)


async def reserve(request_id: str, api_key: APIKey, amount: Decimal, quotes: dict) -> None:
    # Every path locks tenant -> key -> settlement. Multiple keys share the same tenant lock.
    try:
        async with in_transaction():
            tenant = await Tenant.filter(id=api_key.tenant_id).select_for_update().first()
            key = await APIKey.filter(id=api_key.id).select_for_update().first()
            if not tenant or not tenant.is_enabled:
                raise BudgetDenied("tenant_disabled")
            if not key or key.is_revoked or not key.is_enabled:
                raise BudgetDenied("key_disabled")
            for scope, owner in (("tenant", tenant), ("key", key)):
                if owner.quota_total != -1:
                    held = await occupied(scope, owner.id)
                    if owner.quota_used + held + amount > owner.quota_total or owner.quota_used + held >= owner.quota_total:
                        raise BudgetDenied(scope)
            # The unique request_id index rejects a replayed reservation without an extra lookup.
            await Settlement.create(request_id=request_id, tenant_id=tenant.id, api_key_id=key.id,
                                    occupied=amount, quotes=quotes, owner_id=OWNER_ID)
    except IntegrityError:
        raise BudgetDenied("duplicate_request") from None


async def mark_pending(request_id: str, payload: dict, cost: Decimal | None, error: str = "") -> None:
    updates = {"payload": redact(payload), "cost": cost, "state": "pending",
               "last_error": error[:128], "next_retry_at": None}
    if cost is not None:
        updates["occupied"] = cost
    updated = await Settlement.filter(request_id=request_id, state="reserved").update(**updates)
    if not updated and not await Settlement.exists(request_id=request_id, state__in=("pending", "settled", "failed")):
        raise RuntimeError("Reservation missing while persisting usage")


async def persist_usage(request_id: str, payload: dict, cost: Decimal | None, error: str = "") -> None:
    try:
        await mark_pending(request_id, payload, cost, error)
        _unsaved.pop(request_id, None)
    except Exception:
        # The durable reservation remains occupied. Retry saving actual usage in this process.
        _unsaved[request_id] = (redact(payload), cost, error)
        logger.critical("Usage persistence pending request_id=%s", request_id, exc_info=True)


async def release(request_id: str) -> None:
    # Pending/uncertain amounts remain occupied until a successful settlement or explicit operator resolution.
    await Settlement.filter(request_id=request_id, state="reserved").update(state="released", occupied=0)


async def mark_dispatched(request_id: str) -> None:
    if not await Settlement.filter(request_id=request_id, state="reserved").update(dispatched=True):
        raise RuntimeError("Reservation unavailable before upstream dispatch")


async def abandon(request_id: str) -> None:
    await Settlement.filter(request_id=request_id, state="reserved").update(
        state="uncertain", last_error="Upstream result unavailable; reconcile before release",
    )


async def apply(request_id: str, owners: tuple[int, int] | None = None) -> bool:
    """owners is (tenant_id, api_key_id) when the caller already knows them, saving one read."""
    if owners is None:
        record = await Settlement.get(request_id=request_id)
        owners = (record.tenant_id, record.api_key_id)
    tenant_id, api_key_id = owners
    log = None
    async with in_transaction():
        tenant = await Tenant.filter(id=tenant_id).select_for_update().first()
        key = await APIKey.filter(id=api_key_id).select_for_update().first()
        record = await Settlement.filter(request_id=request_id).select_for_update().get()
        if (record.tenant_id, record.api_key_id) != owners:
            raise RuntimeError("Settlement owner mismatch")
        if record.state == "settled":
            return False
        if record.state != "pending" or not record.payload or record.cost is None:
            return False
        if tenant is None or key is None:
            raise RuntimeError("Settlement owner missing")
        cost = record.cost
        await APIKey.filter(id=key.id).update(quota_used=F("quota_used") + cost)
        await Tenant.filter(id=tenant.id).update(quota_used=F("quota_used") + cost)
        payload = {key: value for key, value in record.payload.items() if key not in LEGACY_PAYLOAD_FIELDS}
        log = await save_request_log(**payload, observe=False)
        await Settlement.filter(id=record.id).update(state="settled", occupied=0, last_error="",
                                                   next_retry_at=None)
    if log:
        await observe_request_log(log)
    try:
        await record_windows(record)
    except Exception:
        logger.exception("Window observation pending request_id=%s", record.request_id)
    return True


async def record_windows(record: Settlement) -> None:
    if record.windows_recorded:
        return
    from app.services.spend_windows import record_settlement_spend
    await record_settlement_spend(record.request_id, record.api_key_id, record.tenant_id,
                                  record.cost or Decimal(0), record.created_at)
    await Settlement.filter(id=record.id).update(windows_recorded=True)


async def note_failure(request_id: str, exc: Exception) -> None:
    from app.services.metrics import SETTLEMENT_RETRIES
    SETTLEMENT_RETRIES.labels(error_type=type(exc).__name__).inc()
    record = await Settlement.get(request_id=request_id)
    if record.state != "pending":
        return
    attempts = record.attempts + 1
    await Settlement.filter(id=record.id, state="pending").update(
        attempts=attempts, state="failed" if attempts >= MAX_ATTEMPTS else "pending",
        next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** attempts)),
        last_error=type(exc).__name__,
    )
    logger.error("Settlement pending request_id=%s attempt=%d error=%s", request_id, attempts, type(exc).__name__)


async def recover_once() -> int:
    now = datetime.now(timezone.utc)
    for request_id, (payload, cost, error) in list(_unsaved.items()):
        await mark_pending(request_id, payload, cost, error)
        _unsaved.pop(request_id, None)
    rows = await Settlement.filter(state="pending").order_by("id").limit(100)
    completed = 0
    for record in rows:
        if record.next_retry_at and record.next_retry_at > now:
            continue
        try:
            if record.cost is None:
                # A saved quotation/calculation error requires review, never a silent zero charge.
                raise ValueError("Unpriced pending usage requires review")
            completed += int(await apply(record.request_id))
        except Exception as exc:
            await note_failure(record.request_id, exc)
    for record in await Settlement.filter(state="settled", windows_recorded=False).limit(100):
        try:
            await record_windows(record)
        except Exception:
            logger.exception("Window recovery failed request_id=%s", record.request_id)
    from app.services.metrics import SETTLEMENT_WAITING
    for state in ("pending", "failed", "uncertain"):
        SETTLEMENT_WAITING.labels(state=state).set(await Settlement.filter(state=state).count())
    return completed


async def recovery_loop():
    # A previous process may have called the upstream but crashed before saving usage.
    # Retain its estimate for manual reconciliation; do not expire it as free capacity.
    initialized = False
    while True:
        try:
            if not initialized:
                await Settlement.filter(state="reserved", dispatched=False).exclude(owner_id=OWNER_ID).update(state="released", occupied=0)
                await Settlement.filter(state="reserved", dispatched=True).exclude(owner_id=OWNER_ID).update(
                    state="uncertain", last_error="Process exited before usage was persisted")
                initialized = True
            await recover_once()
        except Exception:
            logger.exception("Settlement recovery unavailable")
        await asyncio.sleep(2)
