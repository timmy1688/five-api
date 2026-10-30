"""Apply the same tenant/key throughput limits to free upstream operations."""
from contextlib import asynccontextmanager

from fastapi import HTTPException

from app.services.auth import key_tenant
from app.services.concurrency import concurrency_limiter, ConcurrencyExceeded
from app.services.rate_limit import rate_limiter, TPMExceeded


@asynccontextmanager
async def guard_unbilled(api_key, input_tokens=0):
    tenant = await key_tenant(api_key)
    if tenant is None:
        raise HTTPException(403, {"error": {"type": "permission_error", "code": "tenant_disabled",
                                            "message": "Tenant unavailable"}})
    leases = []
    tokens = []
    admitted = False
    try:
        for scope, owner in (("tenant", tenant), ("key", api_key)):
            await rate_limiter.reserve_tpm(owner.id, owner.tpm_limit, input_tokens, scope=scope)
            if owner.tpm_limit != -1 and input_tokens:
                tokens.append((scope, owner))
            lease = await concurrency_limiter.acquire(owner.id, owner.concurrent_limit, scope=scope)
            leases.append((scope, owner.id, lease))
        admitted = True
        yield
    except (ConcurrencyExceeded, TPMExceeded) as exc:
        code = "concurrent_limit" if isinstance(exc, ConcurrencyExceeded) else "tpm_limit"
        raise HTTPException(429, {"error": {"type": "rate_limit_error",
            "code": f"tenant_{code}" if exc.scope == "tenant" else code,
            "message": "Tenant or key throughput limit exceeded"}})
    finally:
        if not admitted:
            for scope, owner in tokens:
                await rate_limiter.adjust_tpm(owner.id, owner.tpm_limit, -input_tokens, scope=scope)
        for scope, owner_id, lease in reversed(leases):
            await concurrency_limiter.release(owner_id, lease, scope=scope)
