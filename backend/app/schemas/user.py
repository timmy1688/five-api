from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.services.passwords import password_problem


def _acceptable_password(value: str) -> str:
    problem = password_problem(value)
    if problem:
        raise ValueError(problem)
    return value


# A password being set. Login and old-password fields are never checked against the policy.
NewPassword = Annotated[str, Field(max_length=128), AfterValidator(_acceptable_password)]


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


class UserCreated(UserInfo):
    # Set only when the server generated the password; shown once and never stored in plain text.
    temporary_password: str | None = None


class ChangePasswordRequest(StrictModel):
    old_password: str = Field(max_length=128)
    new_password: NewPassword


class PasswordReset(StrictModel):
    # Omit to let the server generate a one-time temporary password.
    password: NewPassword | None = None


class UserCreate(PasswordReset):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")


class UserUpdate(StrictModel):
    password: NewPassword | None = None
    is_active: bool | None = None
