"""Channel plan for one proxied request: session binding, budget downgrade, fallbacks."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.models import APIKey
from app.providers.registry import resolve_with_fallbacks
from app.services.downgrade import downgrade_headers, downgrade_target, mark_downgraded
from app.services.pre_checks import get_effective_allowed_models
from app.services.sticky_session import get_sticky_channel, make_session_key, session_log_id


@dataclass
class RoutePlan:
    candidates: list
    session_key: str | None
    session_id: str
    downgraded_to: str | None

    @property
    def headers(self) -> dict[str, str]:
        return downgrade_headers(self.downgraded_to)

    def mark(self, response: Any) -> Any:
        return mark_downgraded(response, self.downgraded_to)


async def plan_route(
    api_key: APIKey, model: str, protocol: str, headers: Mapping[str, str], body: dict,
) -> RoutePlan:
    session_key = await make_session_key(api_key.id, headers, body)
    allowed_models = await get_effective_allowed_models(api_key)
    downgraded_to = await downgrade_target(api_key, model, allowed_models)
    candidates = await resolve_with_fallbacks(
        model, preferred_protocol=protocol,
        sticky_channel_id=await get_sticky_channel(session_key),
        allowed_models=allowed_models,
        serve_as=downgraded_to,
    )
    return RoutePlan(
        candidates=candidates,
        session_key=session_key,
        session_id=session_log_id(api_key.id, headers, body),
        downgraded_to=downgraded_to,
    )
