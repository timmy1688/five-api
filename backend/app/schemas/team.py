from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WindowLimits


def _check_quota(v):
    if v is not None and v != -1 and v < 0:
        raise ValueError("quota_total must be -1 or non-negative")
    return v


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field("", max_length=256)
    quota_total: float = Field(-1, allow_inf_nan=False)
    quota_reset_day: int | None = Field(None, ge=1, le=31)
    window_limits: WindowLimits = Field(default_factory=dict)
    is_enabled: bool = True

    @field_validator("quota_total")
    @classmethod
    def validate_quota(cls, v):
        return _check_quota(v)


class TeamUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=256)
    quota_total: float | None = Field(None, allow_inf_nan=False)
    quota_reset_day: int | None = Field(None, ge=1, le=31)
    window_limits: WindowLimits | None = None
    is_enabled: bool | None = None

    @field_validator("quota_total")
    @classmethod
    def validate_quota(cls, v):
        return _check_quota(v)


class TeamResponse(BaseModel):
    id: int
    name: str
    description: str
    quota_total: float
    quota_used: float
    quota_remaining: float
    quota_reset_day: int | None
    quota_last_reset_at: datetime | None
    window_limits: dict[str, float] = Field(default_factory=dict)
    window_spend: dict[str, float] = Field(default_factory=dict)
    is_enabled: bool
    key_count: int = 0
    created_at: datetime
    updated_at: datetime
