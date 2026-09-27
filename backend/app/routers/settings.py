from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models import User
from app.services.auth import require_permission
from app.services.settings_service import gateway_config, set_gateway_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


class GatewaySettingsBody(BaseModel):
    log_retention_days: int = Field(ge=0, le=3650)
    channel_health_threshold: int = Field(ge=1, le=100)
    channel_health_check_interval: int = Field(ge=10, le=86400)
    sticky_session_enabled: bool
    sticky_session_ttl: int = Field(ge=60, le=86400)


@router.get("")
async def get_settings(_: User = require_permission("setting:read")):
    return await gateway_config()


@router.put("")
async def update_settings(
    body: GatewaySettingsBody,
    _: User = require_permission("setting:write"),
):
    return await set_gateway_config(body.model_dump())
