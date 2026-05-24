from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import Admin, APIKey
from app.schemas.api_key import APIKeyCreate, APIKeyCreateResponse, APIKeyResponse, APIKeyUpdate
from app.services.auth import get_current_admin, hash_api_key, require_admin_role
from app.utils.key_generator import generate_api_key

router = APIRouter(prefix="/api/admin/keys", tags=["admin-keys"])


def _to_response(k: APIKey) -> APIKeyResponse:
    total = float(k.quota_total)
    used = float(k.quota_used)
    remaining = -1.0 if total == -1 else max(0.0, total - used)
    return APIKeyResponse(
        id=k.id,
        name=k.name,
        key_prefix=k.key_prefix,
        key_raw=k.key_raw or "",
        quota_total=total,
        quota_used=used,
        quota_remaining=remaining,
        concurrent_limit=k.concurrent_limit,
        rpm_limit=k.rpm_limit,
        allowed_models=k.allowed_models,
        allowed_ips=k.allowed_ips,
        channel_group=k.channel_group,
        is_enabled=k.is_enabled,
        quota_reset_day=k.quota_reset_day,
        quota_last_reset_at=k.quota_last_reset_at,
        expires_at=k.expires_at,
        created_at=k.created_at,
        updated_at=k.updated_at,
    )


@router.get("")
async def list_keys(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: Admin = Depends(get_current_admin),
):
    total = await APIKey.all().count()
    keys = await APIKey.all().order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(k) for k in keys]}


@router.post("", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_key(body: APIKeyCreate, _: Admin = Depends(require_admin_role)):
    raw_key = generate_api_key()
    k = await APIKey.create(
        name=body.name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        key_raw=raw_key,
        quota_total=body.quota_total,
        concurrent_limit=body.concurrent_limit,
        rpm_limit=body.rpm_limit,
        allowed_models=body.allowed_models,
        allowed_ips=body.allowed_ips,
        channel_group=body.channel_group,
        quota_reset_day=body.quota_reset_day,
        expires_at=body.expires_at,
    )
    resp = _to_response(k)
    return APIKeyCreateResponse(**resp.model_dump(), key=raw_key)


@router.get("/{key_id}", response_model=APIKeyResponse)
async def get_key(key_id: int, _: Admin = Depends(get_current_admin)):
    k = await APIKey.get_or_none(id=key_id)
    if k is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return _to_response(k)


@router.put("/{key_id}", response_model=APIKeyResponse)
async def update_key(key_id: int, body: APIKeyUpdate, _: Admin = Depends(require_admin_role)):
    k = await APIKey.get_or_none(id=key_id)
    if k is None:
        raise HTTPException(status_code=404, detail="Key not found")
    update_data = body.model_dump(exclude_unset=True)
    if update_data:
        await APIKey.filter(id=key_id).update(**update_data)
        k = await APIKey.get(id=key_id)
    return _to_response(k)


@router.delete("/{key_id}")
async def delete_key(key_id: int, _: Admin = Depends(require_admin_role)):
    deleted = await APIKey.filter(id=key_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"message": "Deleted"}


@router.post("/{key_id}/reset-quota")
async def reset_quota(key_id: int, _: Admin = Depends(require_admin_role)):
    updated = await APIKey.filter(id=key_id).update(quota_used=0)
    if not updated:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"message": "Quota reset"}
