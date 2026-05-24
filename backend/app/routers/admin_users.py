from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import Admin
from app.schemas.admin import AdminCreate, AdminInfo, AdminUpdate
from app.services.auth import get_current_admin, hash_password, require_admin_role

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


def _to_response(a: Admin) -> AdminInfo:
    return AdminInfo(id=a.id, username=a.username, role=a.role, is_active=a.is_active, created_at=a.created_at)


@router.get("")
async def list_admins(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: Admin = Depends(require_admin_role),
):
    total = await Admin.all().count()
    admins = await Admin.all().order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(a) for a in admins]}


@router.post("", response_model=AdminInfo, status_code=status.HTTP_201_CREATED)
async def create_admin(body: AdminCreate, _: Admin = Depends(require_admin_role)):
    if body.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'viewer'")
    existing = await Admin.get_or_none(username=body.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    a = await Admin.create(
        username=body.username,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    return _to_response(a)


@router.put("/{admin_id}", response_model=AdminInfo)
async def update_admin(admin_id: int, body: AdminUpdate, current: Admin = Depends(require_admin_role)):
    a = await Admin.get_or_none(id=admin_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    if body.role is not None and body.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'viewer'")
    update_data = body.model_dump(exclude_unset=True)
    if "password" in update_data:
        pw = update_data.pop("password")
        if pw:
            update_data["hashed_password"] = hash_password(pw)
    if update_data:
        await Admin.filter(id=admin_id).update(**update_data)
        a = await Admin.get(id=admin_id)
    return _to_response(a)


@router.delete("/{admin_id}")
async def delete_admin(admin_id: int, current: Admin = Depends(require_admin_role)):
    if admin_id == current.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    deleted = await Admin.filter(id=admin_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Admin not found")
    return {"message": "Deleted"}
