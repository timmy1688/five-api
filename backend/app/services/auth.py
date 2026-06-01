import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.models import User, APIKey
from app.utils.ip_check import check_ip_allowed, get_client_ip

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

ALL_PERMISSIONS = [
    "channel:read", "channel:write",
    "key:read", "key:write",
    "model_group:read", "model_group:write",
    "model_price:read", "model_price:write",
    "log:read", "log:write",
    "stat:read",
    "user:read", "user:write",
    "role:read", "role:write",
]

BUILTIN_ROLES = [
    {
        "name": "Super Admin",
        "description": "Full access to all resources",
        "permissions": ALL_PERMISSIONS,
    },
    {
        "name": "Viewer",
        "description": "Read-only access to all resources",
        "permissions": [p for p in ALL_PERMISSIONS if p.endswith(":read")],
    },
]


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> User:
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        raw_id = payload.get("sub")
        if raw_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        admin_id = int(raw_id)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    admin = await User.get_or_none(id=admin_id, is_active=True).select_related("role")
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not found")
    return admin


def require_permission(*required: str):
    """权限检查依赖工厂。用法: admin = require_permission("channel:write")"""
    async def checker(admin: User = Depends(get_current_admin)) -> User:
        user_perms = set(admin.role.permissions or [])
        if not set(required).issubset(user_perms):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )
        return admin
    return Depends(checker)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> APIKey:
    raw_key = credentials.credentials
    key_hash = hash_api_key(raw_key)
    api_key = await APIKey.get_or_none(key_hash=key_hash)

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "Invalid API key", "type": "authentication_error", "code": "invalid_api_key"}},
        )
    if not api_key.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "API key is disabled", "type": "authentication_error", "code": "key_disabled"}},
        )
    if api_key.expires_at:
        exp = api_key.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "API key has expired", "type": "authentication_error", "code": "key_expired"}},
        )
    if not check_ip_allowed(api_key.allowed_ips, get_client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"message": "IP address not allowed", "type": "authentication_error", "code": "ip_not_allowed"}},
        )
    return api_key


async def verify_api_key_anthropic(request: Request) -> APIKey:
    raw_key = request.headers.get("x-api-key")
    if not raw_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_key = auth_header[7:].strip()

    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"type": "error", "error": {"type": "authentication_error", "message": "Missing API key"}},
        )

    key_hash = hash_api_key(raw_key)
    api_key = await APIKey.get_or_none(key_hash=key_hash)

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"type": "error", "error": {"type": "authentication_error", "message": "Invalid API key"}},
        )
    if not api_key.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"type": "error", "error": {"type": "authentication_error", "message": "API key is disabled"}},
        )
    if api_key.expires_at:
        exp = api_key.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"type": "error", "error": {"type": "authentication_error", "message": "API key has expired"}},
            )
    if not check_ip_allowed(api_key.allowed_ips, get_client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"type": "error", "error": {"type": "authentication_error", "message": "IP address not allowed"}},
        )
    return api_key
