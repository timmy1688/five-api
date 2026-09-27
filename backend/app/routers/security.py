from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.models import SecurityKeyword, User
from app.services.auth import require_permission
from app.services.ai_audit import (
    CACHE_TTL,
    MAX_OUTPUT_TOKENS,
    MIN_CHARS,
    SYSTEM_CHARS,
    USER_CHARS,
)
from app.services.content_filter import clear_filter_cache
from app.services.settings_service import (
    ai_audit_config,
    inference_audit_enabled,
    keyword_filter_enabled,
    secret_scan_enabled,
    set_ai_audit_config,
    set_inference_audit_enabled,
    set_keyword_filter_enabled,
    set_secret_scan_enabled,
)

router = APIRouter(prefix="/api/security", tags=["security"])

MAX_KEYWORDS = 200
DIRECTIONS = {"request", "response", "both"}


class SecuritySettings(BaseModel):
    enabled: bool


class KeywordBody(BaseModel):
    keyword: str = Field(min_length=2, max_length=64)
    direction: str = "request"

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str) -> str:
        text = " ".join(value.split())
        if len(text) < 2:
            raise ValueError("keyword must be at least 2 characters")
        return text

    @field_validator("direction")
    @classmethod
    def normalize_direction(cls, value: str) -> str:
        if value not in DIRECTIONS:
            raise ValueError("direction must be request, response, or both")
        return value


class KeywordUpdate(BaseModel):
    direction: str | None = None
    is_enabled: bool | None = None

    @field_validator("direction")
    @classmethod
    def normalize_direction(cls, value: str | None) -> str | None:
        if value is not None and value not in DIRECTIONS:
            raise ValueError("direction must be request, response, or both")
        return value


class KeywordItem(BaseModel):
    id: int
    keyword: str
    direction: str
    is_enabled: bool


class SecretScanSettings(BaseModel):
    enabled: bool


class AiAuditSettings(BaseModel):
    enabled: bool
    model: str = Field(default="", max_length=64)
    fail_closed: bool = False

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        return " ".join(value.split())


class AiAuditView(AiAuditSettings):
    system_chars: int
    user_chars: int
    min_chars: int
    max_output_tokens: int
    cache_seconds: int


class InferenceAuditSettings(BaseModel):
    enabled: bool


class SecurityView(BaseModel):
    enabled: bool
    secret_scan_enabled: bool
    inference_audit_enabled: bool
    ai_audit: AiAuditView
    keywords: list[KeywordItem]


def _ai_view(config: dict) -> AiAuditView:
    return AiAuditView(
        enabled=config["enabled"],
        model=config["model"],
        fail_closed=config["fail_closed"],
        system_chars=SYSTEM_CHARS,
        user_chars=USER_CHARS,
        min_chars=MIN_CHARS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        cache_seconds=CACHE_TTL,
    )


def _item(row: SecurityKeyword) -> KeywordItem:
    return KeywordItem(
        id=row.id,
        keyword=row.keyword,
        direction=row.direction,
        is_enabled=row.is_enabled,
    )


@router.get("", response_model=SecurityView)
async def get_security(_: User = require_permission("security:read")):
    rows = await SecurityKeyword.all().order_by("id")
    return SecurityView(
        enabled=await keyword_filter_enabled(),
        secret_scan_enabled=await secret_scan_enabled(),
        inference_audit_enabled=await inference_audit_enabled(),
        ai_audit=_ai_view(await ai_audit_config()),
        keywords=[_item(row) for row in rows],
    )


@router.put("/secret-scan", response_model=SecretScanSettings)
async def update_secret_scan(body: SecretScanSettings, _: User = require_permission("security:write")):
    enabled = await set_secret_scan_enabled(body.enabled)
    return SecretScanSettings(enabled=enabled)


@router.put("/inference-audit", response_model=InferenceAuditSettings)
async def update_inference_audit(
    body: InferenceAuditSettings,
    _: User = require_permission("security:write"),
):
    enabled = await set_inference_audit_enabled(body.enabled)
    return InferenceAuditSettings(enabled=enabled)


@router.put("/ai-audit", response_model=AiAuditView)
async def update_ai_audit(body: AiAuditSettings, _: User = require_permission("security:write")):
    config = await set_ai_audit_config(
        enabled=body.enabled,
        model=body.model,
        fail_closed=body.fail_closed,
    )
    return _ai_view(config)


@router.put("", response_model=SecuritySettings)
async def update_security(body: SecuritySettings, _: User = require_permission("security:write")):
    enabled = await set_keyword_filter_enabled(body.enabled)
    clear_filter_cache()
    return SecuritySettings(enabled=enabled)


@router.post("/keywords", response_model=KeywordItem, status_code=201)
async def create_keyword(body: KeywordBody, _: User = require_permission("security:write")):
    if await SecurityKeyword.all().count() >= MAX_KEYWORDS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_KEYWORDS} keywords")
    keyword_key = body.keyword.casefold()
    if await SecurityKeyword.get_or_none(keyword_key=keyword_key):
        raise HTTPException(status_code=400, detail="Keyword already exists")
    row = await SecurityKeyword.create(
        keyword=body.keyword,
        keyword_key=keyword_key,
        direction=body.direction,
    )
    clear_filter_cache()
    return _item(row)


@router.put("/keywords/{keyword_id}", response_model=KeywordItem)
async def update_keyword(
    keyword_id: int,
    body: KeywordUpdate,
    _: User = require_permission("security:write"),
):
    row = await SecurityKeyword.get_or_none(id=keyword_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Keyword not found")
    if body.direction is not None:
        row.direction = body.direction
    if body.is_enabled is not None:
        row.is_enabled = body.is_enabled
    await row.save()
    clear_filter_cache()
    return _item(row)


@router.delete("/keywords/{keyword_id}")
async def delete_keyword(keyword_id: int, _: User = require_permission("security:write")):
    deleted = await SecurityKeyword.filter(id=keyword_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Keyword not found")
    clear_filter_cache()
    return {"deleted": True}
