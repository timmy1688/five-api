from datetime import datetime

from pydantic import BaseModel


class ModelGroupCreate(BaseModel):
    name: str
    models: list[str] = []


class ModelGroupUpdate(BaseModel):
    name: str | None = None
    models: list[str] | None = None


class ModelGroupResponse(BaseModel):
    id: int
    name: str
    models: list[str]
    created_at: datetime
    updated_at: datetime
