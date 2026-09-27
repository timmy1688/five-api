import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models import APIKey, RequestLog, RequestLogAudit, User
from app.services.ai_audit import MIN_CHARS, _mark, _verdict, build_excerpt
from app.services.audit import saved_transcript
from app.services.content_filter import keyword_was_hit
from app.services.auth import require_permission
from app.services.settings_service import ai_audit_config

router = APIRouter(prefix="/api/audit", tags=["audit"])

MAX_REVIEW = 20
_SCAN_LIMIT = 1000


class AuditPerson(BaseModel):
    api_key_id: int
    api_key_name: str
    request_count: int
    latest_at: str = ""


class AuditRequestItem(BaseModel):
    request_id: str
    created_at: str
    model_requested: str
    status_code: int
    error_origin: str
    error_message: str
    ai_review: str
    keyword_hit: bool
    excerpt: str
    saved: str


class AuditReviewBody(BaseModel):
    request_ids: list[str] = Field(min_length=1, max_length=MAX_REVIEW)


class AuditReviewItem(BaseModel):
    request_id: str
    ai_review: str
    excerpt: str


def _excerpt(stored: str) -> str:
    try:
        body = json.loads(stored)
    except json.JSONDecodeError:
        return ""
    if not isinstance(body, dict):
        return ""
    return build_excerpt(body)


@router.get("/keys")
async def list_people(_: User = require_permission("security:read")):
    """Every key can be opened. Counts only include requests whose body was saved."""
    keys = await APIKey.all().order_by("name").values("id", "name")
    rows = await RequestLog.filter(has_audit=True).order_by("-id").limit(_SCAN_LIMIT).values(
        "api_key_id", "created_at",
    )
    stats: dict[int, dict] = {}
    for row in rows:
        item = stats.get(row["api_key_id"])
        if item is None:
            stats[row["api_key_id"]] = {"request_count": 1, "latest_at": row["created_at"]}
            continue
        item["request_count"] += 1
    items = [
        AuditPerson(
            api_key_id=key["id"],
            api_key_name=key["name"],
            request_count=stats.get(key["id"], {}).get("request_count", 0),
            latest_at=stats[key["id"]]["latest_at"].isoformat() if key["id"] in stats else "",
        )
        for key in keys
    ]
    items.sort(key=lambda item: (item.request_count == 0, item.api_key_name.lower()))
    return {"items": items}


@router.get("/keys/{key_id}/requests")
async def list_requests(
    key_id: int,
    page: int = Query(1, ge=1),
    _: User = require_permission("security:read"),
):
    size = MAX_REVIEW
    query = RequestLog.filter(api_key_id=key_id, has_audit=True)
    total = await query.count()
    logs = await query.order_by("-id").offset((page - 1) * size).limit(size)
    audits = {
        row.request_log_id: row.audit_request
        for row in await RequestLogAudit.filter(request_log_id__in=[log.id for log in logs])
    }
    items = [
        AuditRequestItem(
            request_id=log.request_id,
            created_at=log.created_at.isoformat(),
            model_requested=log.model_requested,
            status_code=log.status_code,
            error_origin=log.error_origin,
            error_message=log.error_message,
            ai_review=log.ai_review,
            keyword_hit=keyword_was_hit(log.security_hit),
            excerpt=_excerpt(audits.get(log.id, "")),
            saved=saved_transcript(audits.get(log.id, "")),
        )
        for log in logs
    ]
    return {"total": total, "items": items}


@router.post("/review")
async def review_requests(body: AuditReviewBody, _: User = require_permission("security:write")):
    config = await ai_audit_config()
    if not config["enabled"] or not config["model"]:
        raise HTTPException(status_code=400, detail="AI audit is off")
    logs = await RequestLog.filter(request_id__in=body.request_ids, has_audit=True)
    by_id = {log.request_id: log for log in logs}
    audits = {
        row.request_log_id: row.audit_request
        for row in await RequestLogAudit.filter(request_log_id__in=[log.id for log in logs])
    }
    items: list[AuditReviewItem] = []
    for request_id in body.request_ids:
        log = by_id.get(request_id)
        if log is None:
            continue
        excerpt = _excerpt(audits.get(log.id, ""))
        if len(excerpt) < MIN_CHARS:
            await _mark(request_id, "skipped")
            items.append(AuditReviewItem(request_id=request_id, ai_review="skipped", excerpt=excerpt))
            continue
        try:
            verdict = await _verdict(config["model"], excerpt)
        except Exception:
            verdict = "unavailable"
        await _mark(request_id, verdict)
        items.append(AuditReviewItem(request_id=request_id, ai_review=verdict, excerpt=excerpt))
    return {"items": items}
