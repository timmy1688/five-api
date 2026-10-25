from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("password", "old_password", "new_password", check_fields=False)
    @classmethod
    def password_bytes(cls, value):
        if value is not None and len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    must_change_password: bool = False


class UserInfo(BaseModel):
    id: int
    username: str
    role: Literal["platform_admin", "tenant"]
    tenant_id: int | None = None
    is_active: bool
    created_at: datetime
    must_change_password: bool = False


class ChangePasswordRequest(StrictModel):
    old_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserCreate(StrictModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(StrictModel):
    password: str | None = Field(None, min_length=8, max_length=128)
    is_active: bool | None = None
