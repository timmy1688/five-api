from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.user import PasswordReset, StrictModel, UserCreate


class TenantLimits(StrictModel):
    @field_validator("rpm_limit", "tpm_limit", "concurrent_limit", check_fields=False)
    @classmethod
    def valid_limit(cls, value):
        if value is not None and value != -1 and value < 1:
            raise ValueError("Limit must be -1 or positive")
        return value


class TenantCreate(UserCreate, TenantLimits):
    # Optional: the login username doubles as the tenant name unless a name is sent explicitly.
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str = Field("", max_length=256)
    quota_total: Decimal = Field(Decimal("0"), ge=0, max_digits=16, decimal_places=6)
    allowed_models: list[str] = Field(default_factory=list)
    max_keys: int = Field(100, ge=1, le=1000)
    rpm_limit: int = Field(120, ge=-1, le=1_000_000)
    tpm_limit: int = Field(100000, ge=-1, le=100_000_000)
    concurrent_limit: int = Field(10, ge=-1, le=1000)


class TenantUpdate(TenantLimits):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=256)
    is_enabled: bool | None = None
    allowed_models: list[str] | None = None
    max_keys: int | None = Field(None, ge=1, le=1000)
    rpm_limit: int | None = Field(None, ge=-1, le=1_000_000)
    tpm_limit: int | None = Field(None, ge=-1, le=100_000_000)
    concurrent_limit: int | None = Field(None, ge=-1, le=1000)


class TenantQuotaUpdate(StrictModel):
    quota_total: Decimal = Field(ge=0, max_digits=16, decimal_places=6)
    # Optional note kept in the management event; before and after totals are always recorded.
    reason: str = Field("", max_length=256)
    operation_id: UUID


TenantPasswordReset = PasswordReset


class TenantResponse(BaseModel):
    id: int
    name: str
    description: str
    username: str | None = None
    account_id: int | None = None
    quota_total: Decimal
    quota_used: Decimal
    quota_occupied: Decimal = Decimal("0")
    quota_remaining: Decimal
    quota_reset_day: int | None
    window_limits: dict[str, float] = Field(default_factory=dict)
    window_spend: dict[str, float] = Field(default_factory=dict)
    is_enabled: bool
    allowed_models: list[str]
    max_keys: int
    rpm_limit: int
    tpm_limit: int
    concurrent_limit: int
    key_count: int = 0
    created_at: datetime
    updated_at: datetime


class TenantCreated(TenantResponse):
    # Set only when the server generated the login password; shown once.
    temporary_password: str | None = None
