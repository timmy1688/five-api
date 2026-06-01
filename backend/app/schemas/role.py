from datetime import datetime

from pydantic import BaseModel


class RoleCreate(BaseModel):
    name: str
    description: str = ""
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


class RoleInfo(BaseModel):
    id: int
    name: str
    description: str
    permissions: list[str]
    is_builtin: bool
    created_at: datetime
    updated_at: datetime
