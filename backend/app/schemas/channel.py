import math
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from app.utils.upstream_security import validate_upstream_base_url


PRICE_OVERRIDE_FIELDS = ("prompt", "completion", "cached", "cache_write", "request")


def _validate_price_overrides(value):
    """Fixed customer prices per model in USD per 1M tokens; request is USD per call."""
    if value is None:
        return value
    for model, prices in value.items():
        if not model or len(model) > 64:
            raise ValueError("price override keys must contain 1-64 characters")
        unknown = set(prices) - set(PRICE_OVERRIDE_FIELDS)
        if unknown:
            raise ValueError(f"{model}: unknown price fields {sorted(unknown)}")
        if "prompt" not in prices or "completion" not in prices:
            raise ValueError(f"{model}: input and output prices are required")
        for field, price in prices.items():
            if not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
                raise ValueError(f"{model}.{field} must be a non-negative number")
    return value


class ChannelCreate(BaseModel):
    _base_url = field_validator("base_url")(validate_upstream_base_url)
    name: str = Field(min_length=1, max_length=128)
    provider: Literal["openai", "anthropic"]
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = ""
    models: list[str] = Field(default_factory=list)
    model_mapping: dict[str, str] = Field(default_factory=dict)
    price_multiplier: float = Field(1, ge=0, le=100, allow_inf_nan=False)
    price_overrides: dict[str, dict[str, float]] = Field(default_factory=dict)
    priority: int = Field(0, ge=0)
    weight: int = Field(1, ge=0)
    is_enabled: bool = True
    max_retries: int = Field(1, ge=0, le=5)
    timeout: int = Field(120, ge=1, le=600)

    @field_validator("price_overrides")
    @classmethod
    def validate_overrides(cls, value):
        return _validate_price_overrides(value)


class ChannelUpdate(BaseModel):
    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        return validate_upstream_base_url(value) if value is not None else value

    name: str | None = None
    provider: Literal["openai", "anthropic"] | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    model_mapping: dict[str, str] | None = None
    price_multiplier: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    price_overrides: dict[str, dict[str, float]] | None = None
    priority: int | None = Field(None, ge=0)
    weight: int | None = Field(None, ge=0)
    is_enabled: bool | None = None
    max_retries: int | None = Field(None, ge=0, le=5)
    timeout: int | None = Field(None, ge=1, le=600)

    @field_validator("price_overrides")
    @classmethod
    def validate_overrides(cls, value):
        return _validate_price_overrides(value)


class ChannelResponse(BaseModel):
    id: int
    name: str
    provider: str
    base_url: str
    api_key: str
    key_count: int = 0
    models: list[str]
    model_mapping: dict[str, str]
    price_multiplier: float = 1
    price_overrides: dict[str, dict[str, float]]
    priority: int
    weight: int
    is_enabled: bool
    max_retries: int
    timeout: int
    created_at: datetime
    updated_at: datetime
