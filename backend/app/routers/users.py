from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import User, Role
from app.schemas.user import UserCreate, UserInfo, UserUpdate
from app.services.auth import hash_password, require_permission

router = APIRouter(prefix="/api/users", tags=["users"])


def _to_response(a: User) -> UserInfo:
    return UserInfo(
        id=a.id,
        username=a.username,
        role_id=a.role_id,
        role_name=a.role.name if a.role else "",
        permissions=a.role.permissions if a.role else [],
        is_active=a.is_active,
        created_at=a.created_at,
    )


@router.get("")
async def list_admins(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = require_permission("user:read"),
):
    total = await User.all().count()
    admins = await User.all().select_related("role").order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(a) for a in admins]}


@router.post("", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
async def create_admin(body: UserCreate, _: User = require_permission("user:write")):
    if not await Role.exists(id=body.role_id):
        raise HTTPException(status_code=404, detail="Role not found")
    existing = await User.get_or_none(username=body.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    a = await User.create(
        username=body.username,
        hashed_password=hash_password(body.password),
        role_id=body.role_id,
    )
    await a.fetch_related("role")
    return _to_response(a)


@router.put("/{admin_id}", response_model=UserInfo)
async def update_admin(admin_id: int, body: UserUpdate, current: User = require_permission("user:write")):
    a = await User.get_or_none(id=admin_id).select_related("role")
    if a is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    update_data = body.model_dump(exclude_unset=True)
    if "role_id" in update_data and update_data["role_id"] is not None:
        if not await Role.exists(id=update_data["role_id"]):
            raise HTTPException(status_code=404, detail="Role not found")
    if "password" in update_data:
        pw = update_data.pop("password")
        if pw:
            update_data["hashed_password"] = hash_password(pw)
    if update_data:
        await User.filter(id=admin_id).update(**update_data)
        a = await User.get(id=admin_id).select_related("role")
    return _to_response(a)


@router.delete("/{admin_id}")
async def delete_admin(admin_id: int, current: User = require_permission("user:write")):
    if admin_id == current.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    deleted = await User.filter(id=admin_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Admin not found")
    return {"message": "Deleted"}
