from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx

from app.models import Admin, Channel
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate
from app.services.auth import get_current_admin

router = APIRouter(prefix="/api/admin/channels", tags=["admin-channels"])


def _to_response(ch: Channel) -> ChannelResponse:
    return ChannelResponse(
        id=ch.id,
        name=ch.name,
        provider=ch.provider,
        base_url=ch.base_url,
        api_key=ch.api_key,
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
    _: Admin = Depends(get_current_admin),
):
    total = await Channel.all().count()
    channels = await Channel.all().order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(ch) for ch in channels]}


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(body: ChannelCreate, _: Admin = Depends(get_current_admin)):
    ch = await Channel.create(**body.model_dump())
    return _to_response(ch)


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: int, _: Admin = Depends(get_current_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _to_response(ch)


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(channel_id: int, body: ChannelUpdate, _: Admin = Depends(get_current_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    update_data = body.model_dump(exclude_unset=True)
    if update_data:
        await Channel.filter(id=channel_id).update(**update_data)
        ch = await Channel.get(id=channel_id)
    return _to_response(ch)


@router.delete("/{channel_id}")
async def delete_channel(channel_id: int, _: Admin = Depends(get_current_admin)):
    deleted = await Channel.filter(id=channel_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"message": "Deleted"}


@router.post("/{channel_id}/test")
async def test_channel(channel_id: int, _: Admin = Depends(get_current_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{ch.base_url.rstrip('/')}/v1/models"
            headers = {"Authorization": f"Bearer {ch.api_key}"}
            if ch.provider == "anthropic":
                url = f"{ch.base_url.rstrip('/')}/v1/messages"
                headers = {
                    "x-api-key": ch.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                resp = await client.post(
                    url,
                    headers=headers,
                    json={"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
                )
            else:
                resp = await client.get(url, headers=headers)
        return {"success": resp.status_code < 400, "status_code": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}
