from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: int
    username: str
    role_id: int
    role_name: str = ""
    permissions: list[str] = []
    is_active: bool
    created_at: datetime


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UserCreate(BaseModel):
    username: str
    password: str
    role_id: int


class UserUpdate(BaseModel):
    username: str | None = None
    password: str | None = None
    role_id: int | None = None
    is_active: bool | None = None
