from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from tortoise.exceptions import IntegrityError
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from app.models import APIKey, ManagementEvent, Tenant, User
from app.schemas.tenant import (
    TenantCreate, TenantPasswordReset, TenantQuotaUpdate, TenantResponse, TenantUpdate,
)
from app.services.auth import hash_password, require_platform_admin
from app.services.management_events import record_event
from app.services.quota import occupied_quota
from app.services.spend_windows import normalize_limits, window_spend

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


async def tenant_response(tenant: Tenant) -> TenantResponse:
    account = await User.get_or_none(tenant_id=tenant.id)
    occupied = await occupied_quota("tenant", tenant.id)
    return TenantResponse(
        id=tenant.id, name=tenant.name, description=tenant.description,
        username=account.username if account else None, account_id=account.id if account else None,
        quota_total=tenant.quota_total, quota_used=tenant.quota_used, quota_occupied=occupied,
        quota_remaining=Decimal("-1") if tenant.quota_total == -1 else max(
            Decimal("0"), tenant.quota_total - tenant.quota_used - occupied),
        quota_reset_day=tenant.quota_reset_day, is_enabled=tenant.is_enabled,
        window_limits=normalize_limits(tenant.window_limits), window_spend=await window_spend("team", tenant.id),
        allowed_models=tenant.allowed_models, max_keys=tenant.max_keys,
        rpm_limit=tenant.rpm_limit, tpm_limit=tenant.tpm_limit, concurrent_limit=tenant.concurrent_limit,
        key_count=await APIKey.filter(tenant_id=tenant.id, is_revoked=False).count(),
        created_at=tenant.created_at, updated_at=tenant.updated_at,
    )


async def find_tenant(tenant_id: int) -> Tenant:
    tenant = await Tenant.get_or_none(id=tenant_id, is_system=False)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")
    return tenant


@router.get("")
async def list_tenants(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                       _: User = Depends(require_platform_admin)):
    rows = await Tenant.filter(is_system=False).order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": await Tenant.filter(is_system=False).count(),
            "items": [await tenant_response(t) for t in rows]}


@router.get("/all")
async def list_all_tenants(_: User = Depends(require_platform_admin)):
    return await Tenant.filter(is_system=False).order_by("name").values("id", "name", "is_enabled")


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(body: TenantCreate, actor: User = Depends(require_platform_admin)):
    try:
        async with in_transaction():
            tenant = await Tenant.create(**body.model_dump(exclude={"username", "password"}))
            account = await User.create(username=body.username, hashed_password=hash_password(body.password),
                                        role="tenant", tenant_id=tenant.id, must_change_password=True)
            await record_event(actor, "tenant.create", tenant.id, tenant.id,
                               {"account_id": account.id, "quota_total": str(tenant.quota_total)})
    except IntegrityError:
        raise HTTPException(409, "Tenant name or username already exists")
    return await tenant_response(tenant)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: int, _: User = Depends(require_platform_admin)):
    return await tenant_response(await find_tenant(tenant_id))


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: int, body: TenantUpdate,
                        actor: User = Depends(require_platform_admin)):
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    try:
        async with in_transaction():
            tenant = await Tenant.filter(id=tenant_id, is_system=False).select_for_update().first()
            if tenant is None:
                raise HTTPException(404, "Tenant not found")
            if data:
                await Tenant.filter(id=tenant_id).update(**data)
                await record_event(actor, "tenant.update", tenant_id, tenant_id, data)
            await tenant.refresh_from_db()
    except IntegrityError:
        raise HTTPException(409, "Tenant name already exists")
    return await tenant_response(tenant)


@router.put("/{tenant_id}/quota", response_model=TenantResponse)
async def adjust_quota(tenant_id: int, body: TenantQuotaUpdate,
                        actor: User = Depends(require_platform_admin)):
    async with in_transaction():
        tenant = await Tenant.filter(id=tenant_id, is_system=False).select_for_update().first()
        if tenant is None:
            raise HTTPException(404, "Tenant not found")
        operation_id = str(body.operation_id)
        amount = body.quota_total.quantize(Decimal("0.000001"))
        previous = await ManagementEvent.get_or_none(operation_id=operation_id)
        if previous:
            if (previous.action != "tenant.quota" or previous.tenant_id != tenant_id or
                    previous.detail["after"] != str(amount) or
                    previous.detail["reason"] != body.reason):
                raise HTTPException(409, "operation_id already used for a different change")
        else:
            occupied = await occupied_quota("tenant", tenant_id)
            if amount < tenant.quota_used + occupied:
                raise HTTPException(409, "Quota cannot be below used plus occupied; disable tenant to freeze")
            await record_event(actor, "tenant.quota", tenant_id, tenant_id,
                               {"before": str(tenant.quota_total), "after": str(amount),
                                "reason": body.reason}, operation_id=operation_id)
            tenant.quota_total = amount
            await tenant.save(update_fields=["quota_total", "updated_at"])
    return await tenant_response(tenant)


@router.put("/{tenant_id}/password")
async def reset_password(tenant_id: int, body: TenantPasswordReset,
                         actor: User = Depends(require_platform_admin)):
    async with in_transaction():
        await find_tenant(tenant_id)
        count = await User.filter(tenant_id=tenant_id, role="tenant").update(
            hashed_password=hash_password(body.password), must_change_password=True,
            token_version=F("token_version") + 1,
        )
        if not count:
            raise HTTPException(404, "Tenant has no login account")
        await record_event(actor, "tenant.password_reset", tenant_id, tenant_id)
    return {"message": "Temporary password set; password change required at next login"}
