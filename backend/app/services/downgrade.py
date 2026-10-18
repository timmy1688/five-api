"""Switch to a cheaper model once a key or its team nears a budget.

Pressure is the highest used share across the key quota, the team quota and
every rolling window cap. Past the threshold, models with a rule are served
by their cheaper target instead of failing later with a hard 429.
"""

from fastapi.responses import JSONResponse, Response

from app.models import APIKey
from app.services.budget_usage import budget_pressure
from app.services.settings_service import gateway_config


DOWNGRADE_HEADER = "x-five-downgraded-to"


def downgrade_headers(target: str | None) -> dict[str, str]:
    return {DOWNGRADE_HEADER: target} if target else {}


def mark_downgraded(response, target: str | None):
    if not target:
        return response
    if isinstance(response, Response):
        response.headers.update(downgrade_headers(target))
        return response
    return JSONResponse(content=response, headers=downgrade_headers(target))


async def downgrade_target(api_key: APIKey, model: str, allowed_models: list[str] | None) -> str | None:
    config = (await gateway_config()).get("budget_downgrade") or {}
    target = (config.get("rules") or {}).get(model)
    if not target or (allowed_models is not None and target not in allowed_models):
        return None
    if await budget_pressure(api_key) < config.get("threshold", 0.8):
        return None
    return target
