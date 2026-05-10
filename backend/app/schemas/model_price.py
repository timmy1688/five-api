from datetime import datetime

from pydantic import BaseModel


class ModelPriceCreate(BaseModel):
    model: str
    prompt_price: float = 0
    completion_price: float = 0
    cached_price: float = 0
    currency: str = "USD"
    is_active: bool = True


class ModelPriceUpdate(BaseModel):
    model: str | None = None
    prompt_price: float | None = None
    completion_price: float | None = None
    cached_price: float | None = None
    currency: str | None = None
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
