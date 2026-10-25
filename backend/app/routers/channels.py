from app.services.management_events import audit_mutation
from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx

from app.models import User, Channel
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate
from app.services.auth import require_platform_admin
from app.services.channel_health import force_recover, get_health_status, record_failure, record_success
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
        model_pricing=ch.model_pricing or {},
        cost_multiplier=float(ch.cost_multiplier),
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
        ch = await Channel.get(id=channel_id)
    return _to_response(ch)


@router.delete("/{channel_id}")
@audit_mutation("channel.delete")
async def delete_channel(channel_id: int, _: User = Depends(require_platform_admin)):
    deleted = await Channel.filter(id=channel_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"message": "Deleted"}


@router.post("/{channel_id}/test")
async def test_channel(channel_id: int, _: User = Depends(require_platform_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    try:
        validate_upstream_base_url(ch.base_url)
        async with httpx.AsyncClient(timeout=10.0) as client:
            if ch.provider == "anthropic":
                url = upstream_url(ch.base_url, "/v1/messages")
                api_key = (channel_keys(ch.api_key) or [""])[0]
                headers = {
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                if api_key:
                    headers["x-api-key"] = api_key
                resp = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": ch.model_mapping.get(
                            (ch.models or [""])[0], (ch.models or [""])[0]
                        ),
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
            else:
                url = upstream_url(ch.base_url, "/v1/models")
                api_key = (channel_keys(ch.api_key) or [""])[0]
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get(url, headers=headers)
        success = resp.status_code < 400
        if success:
            await record_success(ch.id)
        else:
            await record_failure(ch.id)
        return {"success": success, "status_code": resp.status_code}
    except Exception as e:
        await record_failure(ch.id)
        return {"success": False, "error": redact(str(e))}


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
