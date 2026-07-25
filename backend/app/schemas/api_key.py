import ipaddress
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _validate_ip_list(v):
    if v is None:
        return v
    for entry in v:
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            raise ValueError(f"Invalid IP address or CIDR: {entry}")
    return v


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    quota_total: float = Field(-1, allow_inf_nan=False)
    concurrent_limit: int = Field(5, ge=1, le=1000)
    rpm_limit: int = Field(-1, le=1_000_000)
    allowed_models: list[str] = Field(default_factory=list)
    allowed_ips: list[str] = Field(default_factory=list)
    model_group_id: int | None = None
    quota_reset_day: int | None = Field(None, ge=1, le=31)
    expires_at: datetime | None = None

    @field_validator("allowed_ips", mode="before")
    @classmethod
    def validate_ips(cls, v):
        return _validate_ip_list(v)

    @field_validator("quota_total")
    @classmethod
    def validate_quota(cls, v):
        if v != -1 and v < 0:
            raise ValueError("quota_total must be -1 or non-negative")
        return v

    @field_validator("rpm_limit")
    @classmethod
    def validate_rpm(cls, v):
        if v != -1 and v < 1:
            raise ValueError("rpm_limit must be -1 or at least 1")
        return v


class APIKeyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    quota_total: float | None = Field(None, allow_inf_nan=False)
    concurrent_limit: int | None = Field(None, ge=1, le=1000)
    rpm_limit: int | None = Field(None, le=1_000_000)
    allowed_models: list[str] | None = None
    allowed_ips: list[str] | None = None
    model_group_id: int | None = None
    is_enabled: bool | None = None
    quota_reset_day: int | None = Field(None, ge=1, le=31)
    expires_at: datetime | None = None

    @field_validator("allowed_ips", mode="before")
    @classmethod
    def validate_ips(cls, v):
        return _validate_ip_list(v)

    @field_validator("quota_total")
    @classmethod
    def validate_quota(cls, v):
        if v is not None and v != -1 and v < 0:
            raise ValueError("quota_total must be -1 or non-negative")
        return v

    @field_validator("rpm_limit")
    @classmethod
    def validate_rpm(cls, v):
        if v is not None and v != -1 and v < 1:
            raise ValueError("rpm_limit must be -1 or at least 1")
        return v


class APIKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    quota_total: float
    quota_used: float
    quota_remaining: float
    concurrent_limit: int
    rpm_limit: int
    allowed_models: list[str]
    allowed_ips: list[str]
    model_group_id: int | None
    model_group_name: str | None = None
    is_enabled: bool
    quota_reset_day: int | None
    quota_last_reset_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class APIKeyCreateResponse(APIKeyResponse):
    key: str
