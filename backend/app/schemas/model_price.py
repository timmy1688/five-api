from datetime import datetime

from pydantic import BaseModel, Field


class ModelPriceCreate(BaseModel):
    model: str = Field(min_length=1, max_length=64)
    prompt_price: float = Field(0, ge=0, allow_inf_nan=False)
    completion_price: float = Field(0, ge=0, allow_inf_nan=False)
    cached_price: float = Field(0, ge=0, allow_inf_nan=False)
    currency: str = Field("USD", min_length=1, max_length=8)
    is_active: bool = True


class ModelPriceUpdate(BaseModel):
    model: str | None = Field(None, min_length=1, max_length=64)
    prompt_price: float | None = Field(None, ge=0, allow_inf_nan=False)
    completion_price: float | None = Field(None, ge=0, allow_inf_nan=False)
    cached_price: float | None = Field(None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(None, min_length=1, max_length=8)
    is_active: bool | None = None


class ModelPriceResponse(BaseModel):
    id: int
    model: str
    prompt_price: float
    completion_price: float
    cached_price: float
    currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
