"""Switch to a cheaper model once a key or its team nears a budget.

Pressure is the highest used share across the key quota, the team quota and
every rolling window cap. Past the threshold, models with a rule are served
by their cheaper target instead of failing later with a hard 429.
"""

from fastapi.responses import JSONResponse, Response

from app.models import APIKey, Team
from app.services.settings_service import gateway_config
from app.services.spend_windows import normalize_limits, window_spend


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


def _share(used: float, total: float) -> float:
    if total < 0:
        return 0.0
    if total == 0:
        return 1.0
    return used / total


async def _window_pressure(scope: str, owner_id: int, limits) -> float:
    caps = normalize_limits(limits)
    if not caps:
        return 0.0
    spent = await window_spend(scope, owner_id)
    return max(_share(spent[window], cap) for window, cap in caps.items())


async def budget_pressure(api_key: APIKey) -> float:
    pressure = _share(float(api_key.quota_used), float(api_key.quota_total))
    pressure = max(pressure, await _window_pressure("key", api_key.id, api_key.window_limits))
    if api_key.team_id:
        team = await Team.get_or_none(id=api_key.team_id)
        if team is not None:
            pressure = max(pressure, _share(float(team.quota_used), float(team.quota_total)))
            pressure = max(pressure, await _window_pressure("team", team.id, team.window_limits))
    return pressure


async def downgrade_target(api_key: APIKey, model: str, allowed_models: list[str] | None) -> str | None:
    config = (await gateway_config()).get("budget_downgrade") or {}
    target = (config.get("rules") or {}).get(model)
    if not target or (allowed_models is not None and target not in allowed_models):
        return None
    if await budget_pressure(api_key) < config.get("threshold", 0.8):
        return None
    return target
