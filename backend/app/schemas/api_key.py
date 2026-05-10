from datetime import datetime

from pydantic import BaseModel


class APIKeyCreate(BaseModel):
    name: str
    quota_total: float = -1
    concurrent_limit: int = 5
    allowed_models: list[str] = []
    quota_reset_day: int | None = None
    expires_at: datetime | None = None


class APIKeyUpdate(BaseModel):
    name: str | None = None
    quota_total: float | None = None
    concurrent_limit: int | None = None
    allowed_models: list[str] | None = None
    is_enabled: bool | None = None
    quota_reset_day: int | None = None
    expires_at: datetime | None = None


class APIKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    quota_total: float
    quota_used: float
    quota_remaining: float
    concurrent_limit: int
    allowed_models: list[str]
    is_enabled: bool
    quota_reset_day: int | None
    quota_last_reset_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class APIKeyCreateResponse(APIKeyResponse):
    key: str
