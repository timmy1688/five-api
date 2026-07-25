from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx

from app.models import User, Channel
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate
from app.services.auth import get_current_admin, require_permission
from app.services.channel_health import force_recover, get_health_status, record_failure, record_success
from app.utils.secrets import decrypt_secret, encrypt_secret, mask_secret
from app.utils.upstream_url import upstream_url

router = APIRouter(prefix="/api/channels", tags=["channels"])


def _to_response(ch: Channel) -> ChannelResponse:
    return ChannelResponse(
        id=ch.id,
        name=ch.name,
        provider=ch.provider,
        base_url=ch.base_url,
        api_key=mask_secret(ch.api_key),
        models=ch.models,
        model_mapping=ch.model_mapping,
        model_pricing=ch.model_pricing or {},
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
    _: User = require_permission("channel:read"),
):
    total = await Channel.all().count()
    channels = await Channel.all().order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(ch) for ch in channels]}


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(body: ChannelCreate, _: User = require_permission("channel:write")):
    data = body.model_dump()
    data["api_key"] = encrypt_secret(data["api_key"])
    ch = await Channel.create(**data)
    return _to_response(ch)


# ── 静态路径必须在 /{channel_id} 之前注册 ──────────────────────────────────────

@router.get("/health/status")
async def channels_health(_: User = require_permission("channel:read")):
    channels = await Channel.filter(is_enabled=True)
    channel_ids = [ch.id for ch in channels]
    return await get_health_status(channel_ids)


@router.post("/fetch-models-preview")
async def fetch_models_preview(
    body: dict,
    _: User = require_permission("channel:write"),
):
    provider = body.get("provider", "")
    base_url = body.get("base_url", "")
    api_key = body.get("api_key", "")
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")
    return await _fetch_models_from_upstream(provider, base_url, api_key)


# ── 参数化路径 /{channel_id} ────────────────────────────────────────────────────

@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: int, _: User = require_permission("channel:read")):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _to_response(ch)


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(channel_id: int, body: ChannelUpdate, _: User = require_permission("channel:write")):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    update_data = body.model_dump(exclude_unset=True)
    if update_data.get("api_key"):
        update_data["api_key"] = encrypt_secret(update_data["api_key"])
    else:
        update_data.pop("api_key", None)
    if update_data:
        await Channel.filter(id=channel_id).update(**update_data)
        ch = await Channel.get(id=channel_id)
    return _to_response(ch)


@router.delete("/{channel_id}")
async def delete_channel(channel_id: int, _: User = require_permission("channel:write")):
    deleted = await Channel.filter(id=channel_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"message": "Deleted"}


@router.post("/{channel_id}/test")
async def test_channel(channel_id: int, _: User = require_permission("channel:read")):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if ch.provider == "anthropic":
                url = upstream_url(ch.base_url, "/v1/messages")
                api_key = decrypt_secret(ch.api_key)
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
                api_key = decrypt_secret(ch.api_key)
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
        return {"success": False, "error": str(e)}


@router.post("/{channel_id}/recover")
async def recover_channel(channel_id: int, _: User = require_permission("channel:write")):
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
async def fetch_models(channel_id: int, _: User = require_permission("channel:read")):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return await _fetch_models_from_upstream(
        ch.provider, ch.base_url, decrypt_secret(ch.api_key)
    )


async def _fetch_models_from_upstream(provider: str, base_url: str, api_key: str):
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
        raise HTTPException(status_code=502, detail=f"Failed to fetch models: {e}")
