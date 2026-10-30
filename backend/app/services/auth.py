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


def cached_tenant(api_key: APIKey) -> Tenant | None:
    """Tenant loaded when this request's key was authenticated.

    Read-only checks may reuse it; spending is enforced again under row lock in settlements.reserve.
    """
    return getattr(api_key, "_request_tenant", None)


async def key_tenant(api_key: APIKey) -> Tenant | None:
    return cached_tenant(api_key) or await Tenant.get_or_none(id=api_key.tenant_id, is_enabled=True)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _key_rejected(status_code: int, code: str, message: str) -> HTTPException:
    # protocol_errors renders this OpenAI shape as an Anthropic error under /v1/messages.
    return HTTPException(status_code=status_code, detail={"error": {
        "message": message, "type": "authentication_error", "code": code,
    }})


async def authenticate_api_key(request: Request, raw_key: str | None) -> APIKey:
    if not raw_key:
        raise _key_rejected(status.HTTP_401_UNAUTHORIZED, "invalid_api_key", "Missing API key")
    remember_credential(raw_key)
    api_key = await APIKey.get_or_none(key_hash=hash_api_key(raw_key))
    if api_key is None:
        raise _key_rejected(status.HTTP_401_UNAUTHORIZED, "invalid_api_key", "Invalid API key")
    if not api_key.is_enabled or api_key.is_revoked:
        raise _key_rejected(status.HTTP_401_UNAUTHORIZED, "key_disabled", "API key is disabled")
    if api_key.expires_at:
        exp = api_key.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise _key_rejected(status.HTTP_401_UNAUTHORIZED, "key_expired", "API key has expired")
    if not check_ip_allowed(api_key.allowed_ips, get_client_ip(request)):
        raise _key_rejected(status.HTTP_403_FORBIDDEN, "ip_not_allowed", "IP address not allowed")
    api_key._request_tenant = await check_key_tenant(api_key)
    return api_key


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> APIKey:
    return await authenticate_api_key(request, credentials.credentials if credentials else None)


async def verify_api_key_anthropic(request: Request) -> APIKey:
    raw_key = request.headers.get("x-api-key")
    if not raw_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_key = auth_header[7:].strip()
    return await authenticate_api_key(request, raw_key)
