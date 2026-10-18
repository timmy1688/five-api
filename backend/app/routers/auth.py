from fastapi import APIRouter, Depends, HTTPException, Request, status
from tortoise.expressions import F

from app import dependencies
from app.models import User
from app.schemas.user import UserInfo, ChangePasswordRequest, LoginRequest, TokenResponse
from app.services.auth import (
    DEFAULT_ADMIN_PASSWORD,
    create_access_token,
    get_current_admin,
    hash_password,
    verify_password,
)
from app.utils.ip_check import get_client_ip

router = APIRouter(prefix="/api", tags=["auth"])

# Failures allowed per client IP and per username within the window.
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SECONDS = 900
LOGIN_FAIL_PREFIX = "five:login_fail:"


def admin_token(admin: User, must_change: bool = False) -> str:
    claims = {"sub": str(admin.id), "ver": admin.token_version}
    if must_change:
        claims["pwd"] = True
    return create_access_token(claims)


def _failure_keys(request: Request, username: str) -> list[str]:
    return [
        f"{LOGIN_FAIL_PREFIX}ip:{get_client_ip(request)}",
        f"{LOGIN_FAIL_PREFIX}user:{username.lower()}",
    ]


async def _too_many_failures(keys: list[str]) -> bool:
    r = await dependencies.get_redis()
    for key in keys:
        count = await r.get(key)
        if count is not None and int(count) >= LOGIN_MAX_FAILURES:
            return True
    return False


async def _record_failure(keys: list[str]) -> None:
    r = await dependencies.get_redis()
    for key in keys:
        if await r.incr(key) == 1:
            await r.expire(key, LOGIN_WINDOW_SECONDS)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    keys = _failure_keys(request, body.username)
    if await _too_many_failures(keys):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed logins, try again later",
        )
    admin = await User.get_or_none(username=body.username, is_active=True).select_related("role")
    if admin is None or not verify_password(body.password, admin.hashed_password):
        await _record_failure(keys)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    await (await dependencies.get_redis()).delete(keys[1])
    must_change = body.password == DEFAULT_ADMIN_PASSWORD
    return TokenResponse(
        access_token=admin_token(admin, must_change),
        must_change_password=must_change,
    )


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
        must_change_password=admin.must_change_password,
    )


@router.put("/password", response_model=TokenResponse)
async def change_password(body: ChangePasswordRequest, admin: User = Depends(get_current_admin)):
    if not verify_password(body.old_password, admin.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wrong old password")
    if body.new_password == DEFAULT_ADMIN_PASSWORD or body.new_password == body.old_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose a different password")
    # Every token issued before this point stops working.
    await User.filter(id=admin.id).update(
        hashed_password=hash_password(body.new_password),
        token_version=F("token_version") + 1,
    )
    await admin.refresh_from_db(fields=["token_version"])
    return TokenResponse(access_token=admin_token(admin))
