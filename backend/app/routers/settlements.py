from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from tortoise.transactions import in_transaction

from app.models import APIKey, ManagementEvent, Settlement, Tenant, User
from app.schemas.user import StrictModel
from app.services.auth import require_platform_admin
from app.services.management_events import record_event
from app.services import settlements

router = APIRouter(prefix="/api/settlements", tags=["accounting recovery"])


class Resolution(StrictModel):
    action: Literal["release", "charge_estimate"]
    reason: str = Field(min_length=1, max_length=256)


@router.get("")
async def list_settlements(
    state: Literal["reserved", "pending", "failed", "uncertain", "settled", "released"] | None = None,
    tenant_id: int | None = None, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_platform_admin),
):
    query = Settlement.all()
    if state:
        query = query.filter(state=state)
    if tenant_id is not None:
        query = query.filter(tenant_id=tenant_id)
    rows = await query.order_by("-id").offset((page - 1) * size).limit(size).values(
        "id", "request_id", "tenant_id", "api_key_id", "state", "occupied", "cost",
        "attempts", "next_retry_at", "last_error", "created_at",
    )
    counts = {}
    for status in ("pending", "failed", "uncertain"):
        counts[status] = await Settlement.filter(state=status).count()
    return {"total": await query.count(), "items": rows, "counts": counts}


@router.post("/{record_id}/retry")
async def retry(record_id: int, actor: User = Depends(require_platform_admin)):
    async with in_transaction():
        record = await Settlement.filter(id=record_id).select_for_update().first()
        if record is None:
            raise HTTPException(404, "Settlement not found")
        if record.state not in {"failed", "pending"} or record.cost is None or not record.payload:
            raise HTTPException(409, "This record requires manual reconciliation")
        await Settlement.filter(id=record.id).update(state="pending", attempts=0, next_retry_at=None)
        await record_event(actor, "settlement.retry", record.id, record.tenant_id)
    return {"message": "Retry scheduled"}


@router.post("/{record_id}/resolve")
async def resolve(record_id: int, body: Resolution, actor: User = Depends(require_platform_admin)):
    original = await Settlement.get_or_none(id=record_id)
    if original is None:
        raise HTTPException(404, "Settlement not found")
    async with in_transaction():
        tenant = await Tenant.filter(id=original.tenant_id).select_for_update().first()
        key = await APIKey.filter(id=original.api_key_id).select_for_update().first()
        record = await Settlement.filter(id=record_id).select_for_update().get()
        if record.state not in {"uncertain", "failed"}:
            raise HTTPException(409, "Only failed or uncertain records can be resolved")
        if body.action == "release":
            await Settlement.filter(id=record.id).update(state="released", occupied=0, last_error=body.reason)
        else:
            if not key or not tenant:
                raise HTTPException(409, "Accounting owner no longer exists")
            if record.cost is not None:
                raise HTTPException(409, "Known actual usage must use retry")
            quote = next(iter(record.quotes.values()), {}).get("selling", {})
            model = quote.get("model", "")
            payload = record.payload or dict(
                request_id=record.request_id, api_key_id=key.id, api_key_name=key.name, tenant_id=tenant.id,
                channel_id=None, channel_name="", model_requested=model, model_actual=model, provider="",
                endpoint="", prompt_tokens=0, completion_tokens=0, status_code=499,
            )
            payload.update(cost=str(record.occupied), usage_source="estimated",
                           cost_detail={"manual_resolution": "charge_estimate", "reason": body.reason})
            await Settlement.filter(id=record.id).update(
                state="pending", cost=record.occupied, payload=payload, attempts=0, next_retry_at=None,
            )
        await record_event(actor, "settlement.resolve", record.id, record.tenant_id,
                           {"action": body.action, "reason": body.reason, "occupied": str(record.occupied)})
    return {"message": "Resolution recorded"}
