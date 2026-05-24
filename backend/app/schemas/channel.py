from datetime import datetime

from pydantic import BaseModel


class ChannelCreate(BaseModel):
    name: str
    provider: str
    base_url: str
    api_key: str
    models: list[str] = []
    model_mapping: dict[str, str] = {}
    model_pricing: dict[str, dict[str, float]] = {}
    group: str = ""
    priority: int = 0
    weight: int = 1
    is_enabled: bool = True
    max_retries: int = 1
    timeout: int = 120


class ChannelUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    model_mapping: dict[str, str] | None = None
    model_pricing: dict[str, dict[str, float]] | None = None
    group: str | None = None
    priority: int | None = None
    weight: int | None = None
    is_enabled: bool | None = None
    max_retries: int | None = None
    timeout: int | None = None


class ChannelResponse(BaseModel):
    id: int
    name: str
    provider: str
    base_url: str
    api_key: str
    models: list[str]
    model_mapping: dict[str, str]
    model_pricing: dict[str, dict[str, float]]
    group: str
    priority: int
    weight: int
    is_enabled: bool
    max_retries: int
    timeout: int
    created_at: datetime
    updated_at: datetime
