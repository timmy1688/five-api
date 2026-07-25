import math
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _validate_model_pricing(value):
    if value is None:
        return value
    for model, prices in value.items():
        if not model or len(model) > 64:
            raise ValueError("model pricing keys must contain 1-64 characters")
        for field in ("prompt", "completion", "cached"):
            price = prices.get(field, 0)
            if not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
                raise ValueError(f"{model}.{field} must be a non-negative number")
    return value


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: Literal["openai", "anthropic"]
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = ""
    models: list[str] = Field(default_factory=list)
    model_mapping: dict[str, str] = Field(default_factory=dict)
    model_pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    priority: int = Field(0, ge=0)
    weight: int = Field(1, ge=0)
    is_enabled: bool = True
    max_retries: int = Field(1, ge=0, le=5)
    timeout: int = Field(120, ge=1, le=600)

    @field_validator("model_pricing")
    @classmethod
    def validate_pricing(cls, value):
        return _validate_model_pricing(value)


class ChannelUpdate(BaseModel):
    name: str | None = None
    provider: Literal["openai", "anthropic"] | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    model_mapping: dict[str, str] | None = None
    model_pricing: dict[str, dict[str, float]] | None = None
    priority: int | None = Field(None, ge=0)
    weight: int | None = Field(None, ge=0)
    is_enabled: bool | None = None
    max_retries: int | None = Field(None, ge=0, le=5)
    timeout: int | None = Field(None, ge=1, le=600)

    @field_validator("model_pricing")
    @classmethod
    def validate_pricing(cls, value):
        return _validate_model_pricing(value)


class ChannelResponse(BaseModel):
    id: int
    name: str
    provider: str
    base_url: str
    api_key: str
    models: list[str]
    model_mapping: dict[str, str]
    model_pricing: dict[str, dict[str, float]]
    priority: int
    weight: int
    is_enabled: bool
    max_retries: int
    timeout: int
    created_at: datetime
    updated_at: datetime
