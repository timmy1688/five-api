from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import User, APIKey, ModelGroup
from app.schemas.api_key import APIKeyCreate, APIKeyCreateResponse, APIKeyResponse, APIKeyUpdate
from app.services.auth import hash_api_key, require_permission
from app.utils.key_generator import generate_api_key

router = APIRouter(prefix="/api/keys", tags=["keys"])


async def _to_response(k: APIKey, group_name_map: dict[int, str] | None = None) -> APIKeyResponse:
    total = float(k.quota_total)
    used = float(k.quota_used)
    remaining = -1.0 if total == -1 else max(0.0, total - used)
    model_group_name = None
    if k.model_group_id:
        if group_name_map is not None:
            model_group_name = group_name_map.get(k.model_group_id)
        else:
            group = await ModelGroup.get_or_none(id=k.model_group_id)
            if group:
                model_group_name = group.name
    return APIKeyResponse(
        id=k.id,
        name=k.name,
        key_prefix=k.key_prefix,
        quota_total=total,
        quota_used=used,
        quota_remaining=remaining,
        concurrent_limit=k.concurrent_limit,
        rpm_limit=k.rpm_limit,
        allowed_models=k.allowed_models,
        allowed_ips=k.allowed_ips,
        model_group_id=k.model_group_id,
        model_group_name=model_group_name,
        is_enabled=k.is_enabled,
        quota_reset_day=k.quota_reset_day,
        quota_last_reset_at=k.quota_last_reset_at,
        expires_at=k.expires_at,
        created_at=k.created_at,
        updated_at=k.updated_at,
    )


async def _build_group_name_map(keys: list[APIKey]) -> dict[int, str]:
    group_ids = {k.model_group_id for k in keys if k.model_group_id}
    if not group_ids:
        return {}
    groups = await ModelGroup.filter(id__in=list(group_ids))
    return {g.id: g.name for g in groups}


@router.get("")
async def list_keys(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = require_permission("key:read"),
):
    total = await APIKey.all().count()
    keys = await APIKey.all().order_by("-id").offset((page - 1) * size).limit(size)
    group_name_map = await _build_group_name_map(keys)
    return {"total": total, "items": [await _to_response(k, group_name_map) for k in keys]}


@router.post("", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_key(body: APIKeyCreate, _: User = require_permission("key:write")):
    if body.model_group_id is not None:
        if not await ModelGroup.exists(id=body.model_group_id):
            raise HTTPException(status_code=404, detail="Model group not found")
    raw_key = generate_api_key()
    k = await APIKey.create(
        name=body.name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=body.quota_total,
        concurrent_limit=body.concurrent_limit,
        rpm_limit=body.rpm_limit,
        allowed_models=body.allowed_models,
        allowed_ips=body.allowed_ips,
        model_group_id=body.model_group_id,
        quota_reset_day=body.quota_reset_day,
        quota_last_reset_at=(
            datetime.now(timezone.utc) if body.quota_reset_day is not None else None
        ),
        expires_at=body.expires_at,
    )
    resp = await _to_response(k)
    return APIKeyCreateResponse(**resp.model_dump(), key=raw_key)


@router.get("/{key_id}", response_model=APIKeyResponse)
async def get_key(key_id: int, _: User = require_permission("key:read")):
    k = await APIKey.get_or_none(id=key_id)
    if k is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return await _to_response(k)


@router.put("/{key_id}", response_model=APIKeyResponse)
async def update_key(key_id: int, body: APIKeyUpdate, _: User = require_permission("key:write")):
    k = await APIKey.get_or_none(id=key_id)
    if k is None:
        raise HTTPException(status_code=404, detail="Key not found")
    update_data = body.model_dump(exclude_unset=True)
    if "model_group_id" in update_data and update_data["model_group_id"] is not None:
        if not await ModelGroup.exists(id=update_data["model_group_id"]):
            raise HTTPException(status_code=404, detail="Model group not found")
    if "quota_reset_day" in update_data:
        update_data["quota_last_reset_at"] = (
            datetime.now(timezone.utc)
            if update_data["quota_reset_day"] is not None
            else None
        )
    if update_data:
        await APIKey.filter(id=key_id).update(**update_data)
        k = await APIKey.get(id=key_id)
    return await _to_response(k)


@router.delete("/{key_id}")
async def delete_key(key_id: int, _: User = require_permission("key:write")):
    deleted = await APIKey.filter(id=key_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"message": "Deleted"}


@router.post("/{key_id}/reset-quota")
async def reset_quota(key_id: int, _: User = require_permission("key:write")):
    updated = await APIKey.filter(id=key_id).update(
        quota_used=0,
        quota_last_reset_at=datetime.now(timezone.utc),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"message": "Quota reset"}
