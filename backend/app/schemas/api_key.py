import ipaddress
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import WindowLimits
from app.schemas.user import StrictModel


class KeyValidation(StrictModel):
    @field_validator("allowed_ips", check_fields=False)
    @classmethod
    def validate_ips(cls, value):
        for entry in value or []:
            ipaddress.ip_network(entry, strict=False)
        return value

    @field_validator("quota_total", check_fields=False)
    @classmethod
    def validate_quota(cls, value):
        if value is not None and value != -1 and value < 0:
            raise ValueError("quota_total must be -1 or non-negative")
        return value

    @field_validator("rpm_limit", "tpm_limit", check_fields=False)
    @classmethod
    def validate_rate(cls, value):
        if value is not None and value != -1 and value < 1:
            raise ValueError("rate limit must be -1 or positive")
        return value

    @model_validator(mode="after")
    def reject_null_fields(self):
        nullable = {"expires_at", "model_group_id", "quota_reset_day"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TenantKeyCreate(KeyValidation):
    name: str = Field(min_length=1, max_length=128)
    quota_total: Decimal = Field(Decimal("-1"), max_digits=16, decimal_places=6)
    concurrent_limit: int = Field(5, ge=1, le=1000)
    rpm_limit: int = Field(-1, le=1_000_000)
    tpm_limit: int = Field(-1, le=100_000_000)
    allowed_models: list[str] = Field(default_factory=list)
    allowed_ips: list[str] = Field(default_factory=list)
    channel_ids: list[int] = Field(default_factory=list, max_length=100)
    expires_at: datetime | None = None


class TenantKeyUpdate(KeyValidation):
    name: str | None = Field(None, min_length=1, max_length=128)
    quota_total: Decimal | None = Field(None, max_digits=16, decimal_places=6)
    concurrent_limit: int | None = Field(None, ge=1, le=1000)
    rpm_limit: int | None = Field(None, le=1_000_000)
    tpm_limit: int | None = Field(None, le=100_000_000)
    allowed_models: list[str] | None = None
    allowed_ips: list[str] | None = None
    channel_ids: list[int] | None = Field(None, max_length=100)
    expires_at: datetime | None = None
    is_enabled: bool | None = None


class APIKeyUpdate(TenantKeyUpdate):
    model_group_id: int | None = None
    quota_reset_day: int | None = Field(None, ge=1, le=31)
    window_limits: WindowLimits | None = None
    audit_policy: Literal["on", "off"] | None = None


class APIKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    quota_total: float
    quota_used: float
    quota_occupied: float = 0
    quota_remaining: float
    concurrent_limit: int
    rpm_limit: int
    tpm_limit: int
    allowed_models: list[str]
    allowed_ips: list[str]
    channel_ids: list[int] = Field(default_factory=list)
    model_group_id: int | None = None
    model_group_name: str | None = None
    tenant_id: int
    tenant_name: str | None = None
    tenant_is_system: bool = False
    is_enabled: bool
    is_revoked: bool = False
    audit_policy: str = "off"
    quota_reset_day: int | None = None
    quota_last_reset_at: datetime | None = None
    window_limits: dict[str, float] = Field(default_factory=dict)
    window_spend: dict[str, float] = Field(default_factory=dict)
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class APIKeyCreateResponse(APIKeyResponse):
    key: str
