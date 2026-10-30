from datetime import datetime, timezone
from decimal import Decimal
from json import JSONDecodeError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from tortoise.transactions import in_transaction

from app.models import APIKey, Channel, ModelGroup, RequestLog, Tenant, User
from app import dependencies
from app.schemas.api_key import (
    APIKeyCreateResponse, APIKeyResponse, APIKeyUpdate, TenantKeyCreate, TenantKeyUpdate,
)
from app.services.auth import PLATFORM_ADMIN, hash_api_key, require_account
from app.services.billing_quotes import channel_override, public_selling_prices
from app.services.channel_health import get_health_status
from app.services.management_events import record_event
from app.services.quota import occupied_quota
from app.services.rate_limit import RPM_CHECK_SCRIPT
from app.services.spend_windows import normalize_limits, window_spend
from app.utils.key_generator import generate_api_key

router = APIRouter(prefix="/api", tags=["keys"])


def scoped_keys(actor: User):
    query = APIKey.all()
    return query if actor.role == PLATFORM_ADMIN else query.filter(tenant_id=actor.tenant_id)


async def find_key(key_id: int, actor: User) -> APIKey:
    key = await scoped_keys(actor).filter(id=key_id).first()
    if key is None:
        raise HTTPException(404, "Key not found")
    return key


async def _to_response(key: APIKey, actor: User) -> APIKeyResponse:
    occupied = await occupied_quota("key", key.id)
    remaining = -1 if key.quota_total == -1 else max(Decimal("0"), key.quota_total - key.quota_used - occupied)
    tenant = await Tenant.get_or_none(id=key.tenant_id)
    data = dict(
        id=key.id, name=key.name, key_prefix=key.key_prefix,
        quota_total=key.quota_total, quota_used=key.quota_used, quota_occupied=occupied,
        quota_remaining=remaining, concurrent_limit=key.concurrent_limit, rpm_limit=key.rpm_limit,
        tpm_limit=key.tpm_limit, allowed_models=key.allowed_models, allowed_ips=key.allowed_ips,
        channel_ids=key.channel_ids or [],
        tenant_id=key.tenant_id, tenant_name=tenant.name if tenant else None,
        tenant_is_system=tenant.is_system if tenant else False,
        is_enabled=key.is_enabled, is_revoked=key.is_revoked, expires_at=key.expires_at,
        created_at=key.created_at, updated_at=key.updated_at,
    )
    if actor.role == PLATFORM_ADMIN:
        group = await ModelGroup.get_or_none(id=key.model_group_id) if key.model_group_id else None
        data.update(model_group_id=key.model_group_id, model_group_name=group.name if group else None,
                    audit_policy=key.audit_policy, quota_reset_day=key.quota_reset_day,
                    quota_last_reset_at=key.quota_last_reset_at,
                    window_limits=normalize_limits(key.window_limits),
                    window_spend=await window_spend("key", key.id))
    return APIKeyResponse(**data)


async def validate_models(tenant: Tenant, data: dict):
    if data.get("model_group_id") is not None:
        group = await ModelGroup.get_or_none(id=data["model_group_id"])
        if group is None:
            raise HTTPException(404, "Model group not found")
    models = data.get("allowed_models", [])
    if tenant.allowed_models and not set(models).issubset(set(tenant.allowed_models)):
        raise HTTPException(403, "Models exceed tenant allowance")


async def selectable_channels(tenant: Tenant) -> list[tuple[Channel, list[str]]]:
    """Enabled channels serving at least one model the tenant may use, with those models."""
    allowed = set(tenant.allowed_models or [])
    result = []
    for channel in await Channel.filter(is_enabled=True).order_by("id"):
        models = [m for m in channel.models or [] if not allowed or m in allowed]
        if models:
            result.append((channel, models))
    return result


async def validate_channels(tenant: Tenant, data: dict):
    if not data.get("channel_ids"):
        return
    data["channel_ids"] = list(dict.fromkeys(data["channel_ids"]))
    visible = {channel.id for channel, _ in await selectable_channels(tenant)}
    unavailable = [cid for cid in data["channel_ids"] if cid not in visible]
    if unavailable:
        raise HTTPException(422, f"Channels unavailable for this tenant: {unavailable}")


async def _create(tenant_id: int, body: TenantKeyCreate, actor: User, response: Response):
    data = body.model_dump()
    redis = await dependencies.get_redis()
    if not await redis.eval(RPM_CHECK_SCRIPT, 1, f"five:management:key_create:{tenant_id}", 20, 60):
        raise HTTPException(429, "Key creation rate limit exceeded", headers={"Retry-After": "60"})
    async with in_transaction():
        tenant = await Tenant.filter(id=tenant_id).select_for_update().first()
        if tenant is None:
            raise HTTPException(404, "Tenant not found")
        if not tenant.is_enabled:
            raise HTTPException(403, "Tenant disabled")
        if await APIKey.filter(tenant_id=tenant_id, is_revoked=False).count() >= tenant.max_keys:
            raise HTTPException(409, "Tenant key limit reached; revoke unused keys first")
        await validate_models(tenant, data)
        await validate_channels(tenant, data)
        if data.get("quota_reset_day") is not None:
            data["quota_last_reset_at"] = datetime.now(timezone.utc)
        raw = generate_api_key()
        key = await APIKey.create(**data, tenant_id=tenant_id, key_hash=hash_api_key(raw), key_prefix=raw[:8])
        await record_event(actor, "key.create", key.id, tenant_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return APIKeyCreateResponse(**(await _to_response(key, actor)).model_dump(), key=raw)


@router.get("/keys")
async def list_keys(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                    tenant_id: int | None = None, actor: User = Depends(require_account)):
    if actor.role != PLATFORM_ADMIN and tenant_id is not None:
        raise HTTPException(403, "Tenant selection requires platform administrator")
    query = scoped_keys(actor)
    if tenant_id is not None:
        query = query.filter(tenant_id=tenant_id)
    keys = await query.order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": await query.count(), "items": [await _to_response(k, actor) for k in keys]}


@router.get("/keys/summary")
async def tenant_summary(actor: User = Depends(require_account)):
    if actor.role == PLATFORM_ADMIN:
        raise HTTPException(400, "Use /api/tenants/{tenant_id}")
    from app.routers.tenants import tenant_response
    tenant = await Tenant.get(id=actor.tenant_id)
    return await tenant_response(tenant)


@router.get("/keys/channels")
async def key_channels(tenant_id: int | None = None, actor: User = Depends(require_account)):
    """Channels a key may be bound to, with customer prices. Upstream URLs and secrets stay hidden."""
    if actor.role == PLATFORM_ADMIN:
        tenant = await Tenant.get_or_none(id=tenant_id) if tenant_id else Tenant(allowed_models=[])
    else:
        if tenant_id is not None and tenant_id != actor.tenant_id:
            raise HTTPException(403, "Tenant selection requires platform administrator")
        tenant = await Tenant.get_or_none(id=actor.tenant_id)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")
    channels = await selectable_channels(tenant)
    routes: dict[str, list[tuple]] = {}
    for channel, models in channels:
        for model in models:
            routes.setdefault(model, []).append((channel, (channel.model_mapping or {}).get(model, model)))
    prices = await public_selling_prices(routes)
    health = await get_health_status([channel.id for channel, _ in channels])

    def model_entry(channel: Channel, model: str) -> dict:
        actual = (channel.model_mapping or {}).get(model, model)
        channel_price = next((entry for entry in prices.get(model, {}).get("channels", [])
                              if entry["channel_id"] == channel.id), None)
        return {
            "model": model,
            "fixed_price": channel_override(channel, [model, actual]) is not None,
            "prices": {k: v for k, v in channel_price.items() if k not in ("channel_id", "channel_name")}
            if channel_price else None,
        }

    return [
        {
            "id": channel.id, "name": channel.name, "provider": channel.provider,
            "price_multiplier": float(channel.price_multiplier),
            "healthy": health[channel.id]["healthy"],
            "models": [model_entry(channel, model) for model in models],
        }
        for channel, models in channels
    ]


@router.post("/keys", response_model=APIKeyCreateResponse, status_code=201)
async def create_key(body: TenantKeyCreate, response: Response, actor: User = Depends(require_account)):
    if actor.role == PLATFORM_ADMIN:
        tenant, _ = await Tenant.get_or_create(name="__platform_internal__", defaults={
            "is_system": True, "quota_total": -1, "max_keys": 1000,
            "rpm_limit": -1, "tpm_limit": -1, "concurrent_limit": -1,
        })
        if not tenant.is_system:
            raise HTTPException(409, "Platform key namespace is unavailable")
        return await _create(tenant.id, body, actor, response)
    return await _create(actor.tenant_id, body, actor, response)


@router.get("/keys/{key_id}", response_model=APIKeyResponse)
async def get_key(key_id: int, actor: User = Depends(require_account)):
    return await _to_response(await find_key(key_id, actor), actor)


@router.put("/keys/{key_id}", response_model=APIKeyResponse, openapi_extra={
    "requestBody": {"required": True, "content": {"application/json": {
        "schema": {"anyOf": [TenantKeyUpdate.model_json_schema(), APIKeyUpdate.model_json_schema()]},
    }}},
})
async def update_key(key_id: int, request: Request, actor: User = Depends(require_account)):
    # Different allowlists avoid parsing tenant writes through the platform's schema.
    try:
        payload = await request.json()
    except JSONDecodeError:
        raise HTTPException(400, "Invalid JSON body")
    schema = APIKeyUpdate if actor.role == PLATFORM_ADMIN else TenantKeyUpdate
    try:
        body = schema.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_input=False, include_context=False))
    data = body.model_dump(exclude_unset=True)
    existing = await find_key(key_id, actor)
    async with in_transaction():
        # Same lock order as creation and quota adjustments: tenant, then key.
        tenant = await Tenant.filter(id=existing.tenant_id).select_for_update().first()
        key = await scoped_keys(actor).filter(id=key_id).select_for_update().first()
        if key is None or tenant is None:
            raise HTTPException(404, "Key not found")
        if key.is_revoked:
            raise HTTPException(409, "Revoked key cannot be modified")
        await validate_models(tenant, data)
        await validate_channels(tenant, data)
        if data.get("quota_total", -1) != -1:
            occupied = await occupied_quota("key", key_id)
            if data["quota_total"] < key.quota_used + occupied:
                raise HTTPException(409, "Quota cannot be below used plus occupied")
        if "quota_reset_day" in data:
            data["quota_last_reset_at"] = datetime.now(timezone.utc) if data["quota_reset_day"] else None
        if data:
            await APIKey.filter(id=key_id).update(**data)
            await record_event(actor, "key.update", key_id, key.tenant_id,
                               {"fields": sorted(data)})
        await key.refresh_from_db()
    return await _to_response(key, actor)


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: int, actor: User = Depends(require_account)):
    async with in_transaction():
        key = await find_key(key_id, actor)
        await APIKey.filter(id=key.id).update(is_enabled=False, is_revoked=True)
        await record_event(actor, "key.revoke", key.id, key.tenant_id)
    return {"message": "Key revoked"}


@router.get("/keys/{key_id}/usage")
async def key_usage(key_id: int, actor: User = Depends(require_account)):
    key = await find_key(key_id, actor)
    query = RequestLog.filter(api_key_id=key.id, tenant_id=key.tenant_id)
    rows = await query.order_by("-id").limit(50).values(
        "request_id", "created_at", "model_requested", "endpoint", "status_code",
        "total_tokens", "cost", "latency_ms",
    )
    return {"items": rows}
