from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import User, Role
from app.schemas.role import RoleCreate, RoleInfo, RoleUpdate
from app.services.auth import ALL_PERMISSIONS, get_current_admin, require_permission

router = APIRouter(prefix="/api/roles", tags=["roles"])


def _to_response(r: Role) -> RoleInfo:
    return RoleInfo(
        id=r.id,
        name=r.name,
        description=r.description,
        permissions=r.permissions or [],
        is_builtin=r.is_builtin,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


@router.get("/all")
async def list_all_roles(_: User = Depends(get_current_admin)):
    roles = await Role.all().order_by("id")
    return [{"id": r.id, "name": r.name, "description": r.description} for r in roles]


@router.get("/permissions")
async def list_permissions(_: User = Depends(get_current_admin)):
    groups: dict[str, list[dict]] = {}
    for perm in ALL_PERMISSIONS:
        resource, action = perm.split(":")
        groups.setdefault(resource, []).append({"permission": perm, "action": action})
    return [{"resource": k, "actions": v} for k, v in groups.items()]


@router.get("")
async def list_roles(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = require_permission("role:read"),
):
    total = await Role.all().count()
    items = await Role.all().order_by("id").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(r) for r in items]}


@router.post("", response_model=RoleInfo, status_code=status.HTTP_201_CREATED)
async def create_role(body: RoleCreate, _: User = require_permission("role:write")):
    invalid = set(body.permissions) - set(ALL_PERMISSIONS)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid permissions: {', '.join(invalid)}")
    existing = await Role.get_or_none(name=body.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Role '{body.name}' already exists")
    r = await Role.create(**body.model_dump())
    return _to_response(r)


@router.get("/{role_id}", response_model=RoleInfo)
async def get_role(role_id: int, _: User = require_permission("role:read")):
    r = await Role.get_or_none(id=role_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return _to_response(r)


@router.put("/{role_id}", response_model=RoleInfo)
async def update_role(role_id: int, body: RoleUpdate, _: User = require_permission("role:write")):
    r = await Role.get_or_none(id=role_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if r.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot modify builtin role")
    update_data = body.model_dump(exclude_unset=True)
    if "permissions" in update_data:
        invalid = set(update_data["permissions"]) - set(ALL_PERMISSIONS)
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid permissions: {', '.join(invalid)}")
    if "name" in update_data:
        dup = await Role.get_or_none(name=update_data["name"])
        if dup and dup.id != role_id:
            raise HTTPException(status_code=409, detail=f"Role '{update_data['name']}' already exists")
    if update_data:
        await Role.filter(id=role_id).update(**update_data)
        r = await Role.get(id=role_id)
    return _to_response(r)


@router.delete("/{role_id}")
async def delete_role(role_id: int, _: User = require_permission("role:write")):
    r = await Role.get_or_none(id=role_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if r.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot delete builtin role")
    admin_count = await User.filter(role_id=role_id).count()
    if admin_count > 0:
        raise HTTPException(status_code=409, detail=f"Role is assigned to {admin_count} admin(s)")
    await r.delete()
    return {"message": "Deleted"}
