from fastapi import APIRouter, Depends, HTTPException, status

from app.models import User
from app.schemas.user import UserInfo, ChangePasswordRequest, LoginRequest, TokenResponse
from app.services.auth import (
    create_access_token,
    get_current_admin,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    admin = await User.get_or_none(username=body.username, is_active=True).select_related("role")
    if admin is None or not verify_password(body.password, admin.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": str(admin.id)})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserInfo)
async def me(admin: User = Depends(get_current_admin)):
    return UserInfo(
        id=admin.id,
        username=admin.username,
        role_id=admin.role_id,
        role_name=admin.role.name,
        permissions=admin.role.permissions or [],
        is_active=admin.is_active,
        created_at=admin.created_at,
    )


@router.put("/password")
async def change_password(body: ChangePasswordRequest, admin: User = Depends(get_current_admin)):
    if not verify_password(body.old_password, admin.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wrong old password")
    admin.hashed_password = hash_password(body.new_password)
    await admin.save()
    return {"message": "Password changed"}
