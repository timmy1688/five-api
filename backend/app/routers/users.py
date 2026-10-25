from fastapi import APIRouter, Depends, HTTPException, Query
from tortoise.exceptions import IntegrityError
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from app.models import User
from app.schemas.user import UserCreate, UserInfo, UserUpdate
from app.services.auth import PLATFORM_ADMIN, hash_password, require_platform_admin
from app.services.management_events import record_event

router = APIRouter(prefix="/api/users", tags=["platform accounts"])


def user_info(user: User) -> UserInfo:
    return UserInfo.model_validate(user, from_attributes=True)


@router.get("")
async def list_admins(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                      _: User = Depends(require_platform_admin)):
    query = User.filter(role=PLATFORM_ADMIN)
    users = await query.order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": await query.count(), "items": [user_info(u) for u in users]}


@router.post("", response_model=UserInfo, status_code=201)
async def create_admin(body: UserCreate, actor: User = Depends(require_platform_admin)):
    try:
        async with in_transaction():
            user = await User.create(username=body.username, hashed_password=hash_password(body.password),
                                     role=PLATFORM_ADMIN, must_change_password=True)
            await record_event(actor, "admin.create", user.id)
    except IntegrityError:
        raise HTTPException(409, "Username already exists")
    return user_info(user)


@router.put("/{admin_id}", response_model=UserInfo)
async def update_admin(admin_id: int, body: UserUpdate, actor: User = Depends(require_platform_admin)):
    async with in_transaction():
        admins = await User.filter(role=PLATFORM_ADMIN).order_by("id").select_for_update()
        user = next((u for u in admins if u.id == admin_id), None)
        if user is None:
            raise HTTPException(404, "Platform account not found")
        data = body.model_dump(exclude_unset=True, exclude_none=True)
        if data.get("is_active") is False:
            if user.id == actor.id:
                raise HTTPException(400, "Cannot disable yourself")
            if user.is_active and sum(u.is_active for u in admins) <= 1:
                raise HTTPException(409, "At least one active platform administrator is required")
        password = data.pop("password", None)
        if password:
            data.update(hashed_password=hash_password(password), must_change_password=True)
        if password or data.get("is_active") is False:
            data["token_version"] = F("token_version") + 1
        if data:
            await User.filter(id=user.id).update(**data)
            await record_event(actor, "admin.update", user.id, detail={"password_reset": bool(password),
                                "is_active": data.get("is_active", user.is_active)})
        await user.refresh_from_db()
    return user_info(user)


@router.delete("/{admin_id}")
async def delete_admin(admin_id: int, actor: User = Depends(require_platform_admin)):
    if admin_id == actor.id:
        raise HTTPException(400, "Cannot delete yourself")
    async with in_transaction():
        admins = await User.filter(role=PLATFORM_ADMIN).order_by("id").select_for_update()
        user = next((u for u in admins if u.id == admin_id), None)
        if user is None:
            raise HTTPException(404, "Platform account not found")
        if user.is_active and sum(u.is_active for u in admins) <= 1:
            raise HTTPException(409, "At least one active platform administrator is required")
        await user.delete()
        await record_event(actor, "admin.delete", admin_id)
    return {"message": "Deleted"}
