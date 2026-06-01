import ipaddress
from datetime import datetime

from pydantic import BaseModel, field_validator


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
    name: str
    quota_total: float = -1
    concurrent_limit: int = 5
    rpm_limit: int = -1
    allowed_models: list[str] = []
    allowed_ips: list[str] = []
    model_group_id: int | None = None
    quota_reset_day: int | None = None
    expires_at: datetime | None = None

    @field_validator("allowed_ips", mode="before")
    @classmethod
    def validate_ips(cls, v):
        return _validate_ip_list(v)


class APIKeyUpdate(BaseModel):
    name: str | None = None
    quota_total: float | None = None
    concurrent_limit: int | None = None
    rpm_limit: int | None = None
    allowed_models: list[str] | None = None
    allowed_ips: list[str] | None = None
    model_group_id: int | None = None
    is_enabled: bool | None = None
    quota_reset_day: int | None = None
    expires_at: datetime | None = None

    @field_validator("allowed_ips", mode="before")
    @classmethod
    def validate_ips(cls, v):
        return _validate_ip_list(v)


class APIKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    key_raw: str
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
