import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext

from app.config import settings
from app.models import User, APIKey, Tenant
from app.utils.ip_check import check_ip_allowed, get_client_ip
from app.services.request_context import remember_credential

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=True)
bearer_scheme = HTTPBearer(auto_error=False)

PLATFORM_ADMIN = "platform_admin"
TENANT = "tenant"


DEFAULT_ADMIN_PASSWORD = "admin123"
PASSWORD_CHANGE_REQUIRED = "Password change required"


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    to_encode["aud"] = "five-api-management"
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing management token")
    remember_credential(credentials.credentials)
    try:
        payload = jwt.decode(
            credentials.credentials, settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM], audience="five-api-management",
            options={"require": ["exp", "sub", "aud"]},
        )
        admin_id = int(payload["sub"])
        version = int(payload.get("ver", 0))
    except (InvalidTokenError, ValueError, TypeError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid management token")
    admin = await User.get_or_none(id=admin_id, is_active=True)
    if admin is None or version != admin.token_version:
        raise HTTPException(status_code=401, detail="Token revoked or account unavailable")
    if admin.role not in {PLATFORM_ADMIN, TENANT}:
        raise HTTPException(status_code=403, detail="Account has no assigned role")
    if admin.role == TENANT:
        tenant = await Tenant.get_or_none(id=admin.tenant_id, is_enabled=True)
        if tenant is None:
            raise HTTPException(status_code=403, detail="Tenant unavailable")
    elif admin.tenant_id is not None:
        raise HTTPException(status_code=403, detail="Invalid administrator binding")
    return admin


async def require_account(admin: User = Depends(get_current_admin)) -> User:
    if admin.must_change_password:
        raise HTTPException(status_code=403, detail=PASSWORD_CHANGE_REQUIRED)
    return admin


async def require_platform_admin(admin: User = Depends(require_account)) -> User:
    if admin.role != PLATFORM_ADMIN:
        raise HTTPException(status_code=403, detail="Platform administrator required")
    return admin


async def check_key_tenant(api_key: APIKey) -> Tenant:
    tenant = await Tenant.get_or_none(id=api_key.tenant_id, is_enabled=True)
    if tenant is None:
        raise HTTPException(status_code=403, detail={"error": {
            "message": "Tenant unavailable", "type": "permission_error", "code": "tenant_disabled",
        }})
    from app.services.rate_limit import rate_limiter, RPMExceeded
    try:
        await rate_limiter.check_rpm(api_key.id, api_key.rpm_limit)
        await rate_limiter.check_rpm(tenant.id, tenant.rpm_limit, scope="tenant")
    except RPMExceeded as exc:
        raise HTTPException(429, {"error": {"message": "Requests per minute limit exceeded",
            "type": "rate_limit_error", "code": "tenant_rpm_limit" if exc.scope == "tenant" else "rpm_limit"}})
    return tenant


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> APIKey:
    if credentials is None:
        raise HTTPException(status_code=401, detail={"error": {"message": "Missing API key", "type": "authentication_error", "code": "invalid_api_key"}})
    raw_key = credentials.credentials
    remember_credential(raw_key)
    key_hash = hash_api_key(raw_key)
    api_key = await APIKey.get_or_none(key_hash=key_hash)

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "Invalid API key", "type": "authentication_error", "code": "invalid_api_key"}},
        )
    if not api_key.is_enabled or api_key.is_revoked:
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
    await check_key_tenant(api_key)
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

    remember_credential(raw_key)
    key_hash = hash_api_key(raw_key)
    api_key = await APIKey.get_or_none(key_hash=key_hash)

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"type": "error", "error": {"type": "authentication_error", "message": "Invalid API key"}},
        )
    if not api_key.is_enabled or api_key.is_revoked:
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
    await check_key_tenant(api_key)
    return api_key
