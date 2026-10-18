from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import User
from app.services import alerts
from app.services.auth import require_permission
from app.services.settings_service import (
    gateway_config,
    metrics_token,
    reset_metrics_token,
    set_gateway_config,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class GatewaySettingsBody(BaseModel):
    log_retention_days: int = Field(ge=0, le=3650)
    channel_health_threshold: int = Field(ge=1, le=100)
    channel_health_check_interval: int = Field(ge=10, le=86400)
    sticky_session_enabled: bool
    sticky_session_ttl: int = Field(ge=60, le=86400)
    routing_strategy: Literal["weighted", "least_busy", "latency"] = "weighted"
    model_fallbacks: dict[str, list[str]] | None = None
    auto_cache_control: bool | None = None
    budget_downgrade: dict | None = None
    time_pricing: list[dict] | None = None


@router.get("")
async def get_settings(_: User = require_permission("setting:read")):
    return await gateway_config()


@router.put("")
async def update_settings(
    body: GatewaySettingsBody,
    _: User = require_permission("setting:write"),
):
    current = await gateway_config()
    return await set_gateway_config({**current, **body.model_dump(exclude_none=True)})


@router.get("/metrics-token")
async def get_metrics_token(_: User = require_permission("setting:read")):
    return {"token": await metrics_token()}


@router.post("/metrics-token/reset")
async def regenerate_metrics_token(_: User = require_permission("setting:write")):
    return {"token": await reset_metrics_token()}


class AlertWebhookBody(BaseModel):
    id: str = ""
    name: str = Field(default="", max_length=64)
    type: Literal["feishu", "dingtalk", "wecom", "generic"]
    url: str = Field(default="", max_length=1024)
    secret: str = Field(default="", max_length=256)
    clear_secret: bool = False


class AlertSettingsBody(BaseModel):
    enabled: bool
    webhooks: list[AlertWebhookBody] = Field(default_factory=list, max_length=10)
    events: dict[str, bool] = Field(default_factory=dict)
    budget_threshold: float = Field(default=0.9, ge=0.1, le=1.0)
    error_threshold: float = Field(default=0.5, ge=0.05, le=1.0)
    error_min_requests: int = Field(default=20, ge=1, le=10000)


class AlertTestBody(BaseModel):
    id: str = ""


@router.get("/alerts")
async def get_alerts(_: User = require_permission("setting:read")):
    return alerts.public_config(await alerts.alert_config())


@router.put("/alerts")
async def update_alerts(body: AlertSettingsBody, _: User = require_permission("setting:write")):
    return alerts.public_config(await alerts.save_config(body.model_dump()))


@router.post("/alerts/test")
async def test_alerts(body: AlertTestBody, _: User = require_permission("setting:write")):
    hooks = [
        hook for hook in (await alerts.alert_config())["webhooks"]
        if not body.id or hook["id"] == body.id
    ]
    if not hooks:
        raise HTTPException(status_code=404, detail="No saved webhook")
    results = await alerts.deliver(
        hooks, "test", "[Five API] 告警测试", "这是一条测试消息，收到说明 Webhook 配置正确。", {"test": True},
    )
    return {"items": results}
