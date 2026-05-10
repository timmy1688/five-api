from datetime import datetime

from pydantic import BaseModel


class StatsOverview(BaseModel):
    total_requests: int
    total_tokens: int
    total_cost: float
    active_keys: int
    active_channels: int
    requests_today: int
    tokens_today: int
    cost_today: float


class UsagePoint(BaseModel):
    date: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    request_count: int
    cost: float


class ModelUsage(BaseModel):
    model: str
    total_tokens: int
    request_count: int
    cost: float


class KeyUsage(BaseModel):
    key_id: int
    key_name: str
    total_tokens: int
    request_count: int
    cost: float
