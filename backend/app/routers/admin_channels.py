from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx

from app.models import Admin, Channel
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate
from app.services.auth import get_current_admin, require_admin_role
from app.services.channel_health import force_recover, get_health_status, record_failure, record_success

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
        group=ch.group,
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
async def create_channel(body: ChannelCreate, _: Admin = Depends(require_admin_role)):
    ch = await Channel.create(**body.model_dump())
    return _to_response(ch)


# ── 静态路径必须在 /{channel_id} 之前注册 ──────────────────────────────────────

@router.get("/health/status")
async def channels_health(_: Admin = Depends(get_current_admin)):
    """获取所有渠道的健康状态。"""
    channels = await Channel.filter(is_enabled=True)
    channel_ids = [ch.id for ch in channels]
    return await get_health_status(channel_ids)


@router.post("/fetch-models-preview")
async def fetch_models_preview(
    provider: str = "",
    base_url: str = "",
    api_key: str = "",
    _: Admin = Depends(get_current_admin),
):
    """无需先保存渠道，直接传参拉取上游模型列表。"""
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="base_url and api_key are required")
    return await _fetch_models_from_upstream(provider, base_url, api_key)


# ── 参数化路径 /{channel_id} ────────────────────────────────────────────────────

@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: int, _: Admin = Depends(get_current_admin)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _to_response(ch)


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(channel_id: int, body: ChannelUpdate, _: Admin = Depends(require_admin_role)):
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    update_data = body.model_dump(exclude_unset=True)
    if update_data:
        await Channel.filter(id=channel_id).update(**update_data)
        ch = await Channel.get(id=channel_id)
    return _to_response(ch)


@router.delete("/{channel_id}")
async def delete_channel(channel_id: int, _: Admin = Depends(require_admin_role)):
    deleted = await Channel.filter(id=channel_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"message": "Deleted"}


@router.post("/{channel_id}/test")
async def test_channel(channel_id: int, _: Admin = Depends(get_current_admin)):
    """测试渠道连通性，同时更新健康状态。"""
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
            elif ch.provider == "azure":
                url = f"{ch.base_url.rstrip('/')}/openai/models?api-version=2024-12-01-preview"
                headers = {"api-key": ch.api_key}
                resp = await client.get(url, headers=headers)
            else:
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
async def recover_channel(channel_id: int, _: Admin = Depends(require_admin_role)):
    """强制恢复被熔断的渠道。"""
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    await force_recover(channel_id)
    return {"message": "Channel recovered"}


ANTHROPIC_MODELS = [
    "claude-opus-4-7", "claude-opus-4-7-20260416",
    "claude-opus-4-6", "claude-opus-4-6-20250610",
    "claude-sonnet-4-6", "claude-sonnet-4-6-20250819",
    "claude-haiku-4-5", "claude-haiku-4-5-20251001",
    # legacy（deprecated，第三方中转可能仍可用）
    "claude-opus-4-20250514", "claude-sonnet-4-20250514",
    "claude-3.5-sonnet-20241022", "claude-3.5-haiku-20241022",
    "claude-3-opus-20240229",
]


@router.post("/{channel_id}/fetch-models")
async def fetch_models(channel_id: int, _: Admin = Depends(get_current_admin)):
    """从上游拉取可用模型列表。"""
    ch = await Channel.get_or_none(id=channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return await _fetch_models_from_upstream(ch.provider, ch.base_url, ch.api_key)


async def _fetch_models_from_upstream(provider: str, base_url: str, api_key: str):
    """从上游拉取模型列表的公共逻辑。"""
    if provider == "anthropic":
        return {"models": ANTHROPIC_MODELS}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = f"{base_url.rstrip('/')}/v1/models"
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if provider == "azure":
                url = f"{base_url.rstrip('/')}/openai/models?api-version=2024-12-01-preview"
                headers["api-key"] = api_key
            else:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models = sorted([m["id"] for m in data.get("data", []) if m.get("id")])
            return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch models: {e}")
