from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from tortoise.functions import Count

from app.models import APIKey, Team, User
from app.schemas.team import TeamCreate, TeamResponse, TeamUpdate
from app.services.auth import require_permission
from app.services.spend_windows import normalize_limits, reset_windows, window_spend

router = APIRouter(prefix="/api/teams", tags=["teams"])


async def _to_response(t: Team, key_count: int = 0) -> TeamResponse:
    total = float(t.quota_total)
    used = float(t.quota_used)
    return TeamResponse(
        id=t.id,
        name=t.name,
        description=t.description,
        quota_total=total,
        quota_used=used,
        quota_remaining=-1.0 if total == -1 else max(0.0, total - used),
        quota_reset_day=t.quota_reset_day,
        quota_last_reset_at=t.quota_last_reset_at,
        window_limits=normalize_limits(t.window_limits),
        window_spend=await window_spend("team", t.id),
        is_enabled=t.is_enabled,
        key_count=key_count,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


async def _key_counts(team_ids: list[int]) -> dict[int, int]:
    if not team_ids:
        return {}
    rows = (
        await APIKey.filter(team_id__in=team_ids)
        .group_by("team_id")
        .annotate(n=Count("id"))
        .values("team_id", "n")
    )
    return {r["team_id"]: r["n"] for r in rows}


@router.get("")
async def list_teams(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = require_permission("team:read"),
):
    total = await Team.all().count()
    teams = await Team.all().order_by("-id").offset((page - 1) * size).limit(size)
    counts = await _key_counts([t.id for t in teams])
    return {"total": total, "items": [await _to_response(t, counts.get(t.id, 0)) for t in teams]}


@router.get("/all")
async def list_all_teams(_: User = require_permission("key:read")):
    teams = await Team.all().order_by("name")
    return [{"id": t.id, "name": t.name, "is_enabled": t.is_enabled} for t in teams]


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(body: TeamCreate, _: User = require_permission("team:write")):
    if await Team.exists(name=body.name):
        raise HTTPException(status_code=409, detail=f"Team '{body.name}' already exists")
    data = body.model_dump()
    if body.quota_reset_day is not None:
        data["quota_last_reset_at"] = datetime.now(timezone.utc)
    return await _to_response(await Team.create(**data))


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: int, _: User = require_permission("team:read")):
    t = await Team.get_or_none(id=team_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Team not found")
    counts = await _key_counts([t.id])
    return await _to_response(t, counts.get(t.id, 0))


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(team_id: int, body: TeamUpdate, _: User = require_permission("team:write")):
    t = await Team.get_or_none(id=team_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Team not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        dup = await Team.get_or_none(name=data["name"])
        if dup and dup.id != team_id:
            raise HTTPException(status_code=409, detail=f"Team '{data['name']}' already exists")
    if "quota_reset_day" in data:
        data["quota_last_reset_at"] = (
            datetime.now(timezone.utc) if data["quota_reset_day"] is not None else None
        )
    if data:
        await Team.filter(id=team_id).update(**data)
        t = await Team.get(id=team_id)
    counts = await _key_counts([t.id])
    return await _to_response(t, counts.get(t.id, 0))


@router.post("/{team_id}/reset-quota")
async def reset_team_quota(team_id: int, _: User = require_permission("team:write")):
    updated = await Team.filter(id=team_id).update(
        quota_used=0, quota_last_reset_at=datetime.now(timezone.utc),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Team not found")
    await reset_windows("team", team_id)
    return {"message": "Quota reset"}


@router.delete("/{team_id}")
async def delete_team(team_id: int, _: User = require_permission("team:write")):
    key_count = await APIKey.filter(team_id=team_id).count()
    if key_count:
        raise HTTPException(status_code=409, detail=f"Team has {key_count} API key(s)")
    deleted = await Team.filter(id=team_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"message": "Deleted"}
