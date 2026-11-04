from app.services.management_events import audit_mutation
from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx

from app import dependencies
from app.models import APIKey, User, Channel
from app.providers.registry import clear_channel_cache
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate, ChannelTestRequest, ChannelTestResponse
from app.services.auth import require_platform_admin
from app.services.channel_health import force_recover, get_health_status
from app.services.channel_checks import run_channel_checks
from app.services.concurrency import ConcurrencyExceeded
from app.services.model_monitor import probe_slot, supports_health
from app.services.rate_limit import RPM_CHECK_SCRIPT
from app.services.key_pool import pool_status
from app.utils.secrets import channel_keys, encrypt_secret, mask_secret, split_keys
from app.utils.upstream_url import upstream_url
from app.utils.upstream_security import validate_upstream_base_url
from app.services.redaction import redact
from app.services.request_context import remember_credential

router = APIRouter(prefix="/api/channels", tags=["channels"])


def _to_response(ch: Channel) -> ChannelResponse:
    return ChannelResponse(
        id=ch.id,
        name=ch.name,
        provider=ch.provider,
        base_url=ch.base_url,
        api_key=mask_secret(ch.api_key),
        key_count=len(channel_keys(ch.api_key)),
        models=ch.models,
        model_mapping=ch.model_mapping,
        price_multiplier=float(ch.price_multiplier),
        price_overrides=ch.price_overrides or {},
        priority=ch.priority,
        weight=ch.weight,
        is_enabled=ch.is_enabled,
        max_retries=ch.max_retries,
        timeout=ch.timeout,
        created_at=ch.created_at,
        updated_at=ch.updated_at,
    )


@router.get("")
async def list_channels(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_platform_admin),
):
    total = await Channel.all().count()
    channels = await Channel.all().order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(ch) for ch in channels]}


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
@audit_mutation("channel.create")
async def create_channel(body: ChannelCreate, _: User = Depends(require_platform_admin)):
    data = body.model_dump()
    data["api_key"] = encrypt_secret("\n".join(split_keys(data["api_key"])))
    ch = await Channel.create(**data)
    clear_channel_cache()
    return _to_response(ch)


# ── 静态路径必须在 /{channel_id} 之前注册 ──────────────────────────────────────

@router.get("/health/status")
async def channels_health(_: User = Depends(require_platform_admin)):
    channels = await Channel.filter(is_enabled=True)
    status_map = await get_health_status([ch.id for ch in channels])
    for ch in channels:
        status_map[ch.id].update(await pool_status(ch.id, channel_keys(ch.api_key)))
    return status_map


@router.post("/fetch-models-preview")
async def fetch_models_preview(
    body: dict,
    _: User = Depends(require_platform_admin),
):
    provider = body.get("provider", "")
    base_url = body.get("base_url", "")
    api_key = (split_keys(body.get("api_key", "")) or [""])[0]
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    return await _fetch_models_from_upstream(provider, base_url, api_key)


# ── 参数化路径 /{channel_id} ────────────────────────────────────────────────────

@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: int, _: User = Depends(require_platform_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _to_response(ch)


@router.put("/{channel_id}", response_model=ChannelResponse)
@audit_mutation("channel.update")
async def update_channel(channel_id: int, body: ChannelUpdate, _: User = Depends(require_platform_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    update_data = body.model_dump(exclude_unset=True, exclude_none=True)
    if update_data.get("api_key"):
        update_data["api_key"] = encrypt_secret("\n".join(split_keys(update_data["api_key"])))
    else:
        update_data.pop("api_key", None)
    if update_data:
        await Channel.filter(id=channel_id).update(**update_data)
        clear_channel_cache()
        ch = await Channel.get(id=channel_id)
    return _to_response(ch)


@router.delete("/{channel_id}")
@audit_mutation("channel.delete")
async def delete_channel(channel_id: int, _: User = Depends(require_platform_admin)):
    bound = [
        name for name, ids in await APIKey.filter(is_revoked=False).values_list("name", "channel_ids")
        if channel_id in (ids or [])
    ]
    if bound:
        raise HTTPException(409, f"Channel is selected by {len(bound)} API key(s): {', '.join(bound[:5])}")
    deleted = await Channel.filter(id=channel_id).delete()
    clear_channel_cache()
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"message": "Deleted"}


@router.post("/{channel_id}/test", response_model=ChannelTestResponse)
async def test_channel(channel_id: int, body: ChannelTestRequest | None = None,
                       actor: User = Depends(require_platform_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    model = body.model if body else next(iter(ch.models or []), "")
    if model not in (ch.models or []):
        raise HTTPException(422, "Choose a model configured on this channel")
    actual = (ch.model_mapping or {}).get(model, model)
    if not supports_health(actual):
        raise HTTPException(422, "Connection checks currently support text generation models")
    redis = await dependencies.get_redis()
    if not await redis.eval(RPM_CHECK_SCRIPT, 1, f"five:model_probe:actor:{actor.id}", 6, 60):
        raise HTTPException(429, "Probe rate limit reached", headers={"Retry-After": "60"})
    try:
        async with probe_slot(ch.id, model, "connection") as acquired:
            if not acquired:
                raise HTTPException(409, "This channel model is already being checked")
            checks = await run_channel_checks(ch, model)
    except ConcurrencyExceeded:
        raise HTTPException(429, "Two model checks are already running", headers={"Retry-After": "10"})
    failed = next((check for check in checks if check.status != "passed"), None)
    return ChannelTestResponse(
        success=failed is None, model=model, actual_model=actual, checks=checks,
        status_code=failed.status_code if failed else 200, error=failed.error if failed else "",
    )


@router.post("/{channel_id}/recover")
async def recover_channel(channel_id: int, _: User = Depends(require_platform_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    await force_recover(channel_id)
    return {"message": "Channel recovered"}


ANTHROPIC_MODELS = [
    "claude-fable-5", "claude-opus-5", "claude-sonnet-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-6", "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5", "claude-haiku-4-5-20251001",
]


@router.post("/{channel_id}/fetch-models")
async def fetch_models(channel_id: int, _: User = Depends(require_platform_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return await _fetch_models_from_upstream(
        ch.provider, ch.base_url, (channel_keys(ch.api_key) or [""])[0]
    )


async def _fetch_models_from_upstream(provider: str, base_url: str, api_key: str):
    remember_credential(api_key)
    try:
        base_url = validate_upstream_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if provider == "anthropic":
        return {"models": ANTHROPIC_MODELS}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = upstream_url(base_url, "/v1/models")
            headers: dict[str, str] = {
                "Content-Type": "application/json",
            }
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models = sorted([m["id"] for m in data.get("data", []) if m.get("id")])
            return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=502, detail=redact(f"Failed to fetch models: {e}"))
