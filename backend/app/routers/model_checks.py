import anyio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from app import dependencies
from app.models import Channel, ModelProbe, User
from app.schemas.user import StrictModel
from app.services.auth import require_platform_admin
from app.services.concurrency import ConcurrencyExceeded
from app.services.management_events import record_event
from app.services.model_checks import run_probe, probe_response, supports_capability
from app.services.rate_limit import RPM_CHECK_SCRIPT
from app.services.model_monitor import probe_slot, supports_health, runtime
from app.services.settings_service import gateway_config, patch_gateway_config

router = APIRouter(prefix="/api/models", tags=["model checks"])


class ProbeRequest(StrictModel):
    channel_id: int = Field(gt=0)
    model: str = Field(min_length=1, max_length=64)
    kind: Literal["health", "capability"] = "health"


@router.post("/probe")
async def check_model(body: ProbeRequest, actor: User = Depends(require_platform_admin)):
    channel = await Channel.get_or_none(id=body.channel_id)
    if channel is None or body.model not in (channel.models or []):
        raise HTTPException(404, "Channel model not found")
    actual = (channel.model_mapping or {}).get(body.model, body.model)
    if body.kind == "capability" and not supports_capability(actual):
        raise HTTPException(422, "Capability checks currently support GPT and Claude text models")
    if not supports_health(actual):
        raise HTTPException(422, "Synthetic probes currently support text generation models")
    redis = await dependencies.get_redis()
    if not await redis.eval(RPM_CHECK_SCRIPT, 1, f"five:model_probe:actor:{actor.id}", 6, 60):
        raise HTTPException(429, "Probe rate limit reached", headers={"Retry-After": "60"})
    try:
        async with probe_slot(channel.id, body.model, body.kind) as acquired:
            if not acquired:
                raise HTTPException(409, "This model check is already running")
            record = await run_probe(channel, body.model, body.kind, actor)
            await record_event(actor, "model.probe", record.id, 0,
                               {"channel_id": channel.id, "model": body.model, "kind": body.kind, "status": record.status})
            return probe_response(record)
    except ConcurrencyExceeded:
        raise HTTPException(429, "Two model checks are already running", headers={"Retry-After": "10"})


@router.get("/probes")
async def history(channel_id: int = Query(gt=0), model: str = Query(min_length=1, max_length=64),
                  kind: Literal["health", "capability"] | None = None,
                  page: int = Query(1, ge=1, le=1000), size: int = Query(10, ge=1, le=50),
                  _: User = Depends(require_platform_admin)):
    query = ModelProbe.filter(channel_id=channel_id, model=model)
    if kind:
        query = query.filter(kind=kind)
    records = await query.order_by("-created_at", "-id").offset((page - 1) * size).limit(size)
    return {"total": await query.count(), "items": [probe_response(record) for record in records]}


class CheckSettings(StrictModel):
    health_enabled: bool = True
    health_interval_seconds: int = Field(900, ge=60, le=86400)
    capability_enabled: bool = True
    capability_interval_seconds: int = Field(86400, ge=3600, le=604800)


@router.get("/check-settings")
async def check_settings(_: User = Depends(require_platform_admin)):
    return {"config": (await gateway_config())["model_checks"], "scheduler": runtime}


@router.put("/check-settings")
async def save_check_settings(body: CheckSettings, actor: User = Depends(require_platform_admin)):
    from tortoise.transactions import in_transaction
    async with in_transaction():
        config = await patch_gateway_config({"model_checks": body.model_dump()})
        await record_event(actor, "model.check_settings", 0, 0, body.model_dump())
    return {"config": config["model_checks"], "scheduler": runtime}
