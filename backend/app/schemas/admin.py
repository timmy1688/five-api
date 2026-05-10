from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminInfo(BaseModel):
    id: int
    username: str
    is_active: bool
    created_at: datetime


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
