from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import APIKey, User, ModelGroup
from app.schemas.model_group import ModelGroupCreate, ModelGroupResponse, ModelGroupUpdate
from app.services.auth import require_permission

router = APIRouter(prefix="/api/model-groups", tags=["model-groups"])


def _to_response(g: ModelGroup) -> ModelGroupResponse:
    return ModelGroupResponse(
        id=g.id,
        name=g.name,
        models=g.models or [],
        created_at=g.created_at,
        updated_at=g.updated_at,
    )


@router.get("")
async def list_model_groups(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = require_permission("model_group:read"),
):
    total = await ModelGroup.all().count()
    items = await ModelGroup.all().order_by("-id").offset((page - 1) * size).limit(size)
    return {"total": total, "items": [_to_response(g) for g in items]}


@router.get("/all")
async def list_all_model_groups(_: User = require_permission("model_group:read")):
    groups = await ModelGroup.all().order_by("name")
    return [{"id": g.id, "name": g.name, "models": g.models or []} for g in groups]


@router.post("", response_model=ModelGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_model_group(body: ModelGroupCreate, _: User = require_permission("model_group:write")):
    existing = await ModelGroup.get_or_none(name=body.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Model group '{body.name}' already exists")
    g = await ModelGroup.create(**body.model_dump())
    return _to_response(g)


@router.get("/{group_id}", response_model=ModelGroupResponse)
async def get_model_group(group_id: int, _: User = require_permission("model_group:read")):
    g = await ModelGroup.get_or_none(id=group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Model group not found")
    return _to_response(g)


@router.put("/{group_id}", response_model=ModelGroupResponse)
async def update_model_group(group_id: int, body: ModelGroupUpdate, _: User = require_permission("model_group:write")):
    g = await ModelGroup.get_or_none(id=group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Model group not found")
    update_data = body.model_dump(exclude_unset=True)
    if "name" in update_data:
        dup = await ModelGroup.get_or_none(name=update_data["name"])
        if dup and dup.id != group_id:
            raise HTTPException(status_code=409, detail=f"Model group '{update_data['name']}' already exists")
    if update_data:
        await ModelGroup.filter(id=group_id).update(**update_data)
        g = await ModelGroup.get(id=group_id)
    return _to_response(g)


@router.delete("/{group_id}")
async def delete_model_group(group_id: int, _: User = require_permission("model_group:write")):
    key_count = await APIKey.filter(model_group_id=group_id).count()
    if key_count:
        raise HTTPException(
            status_code=409,
            detail=f"Model group is assigned to {key_count} API key(s)",
        )
    deleted = await ModelGroup.filter(id=group_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Model group not found")
    return {"message": "Deleted"}
