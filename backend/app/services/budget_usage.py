"""How much of each capped budget a key and its team have used.

Budget downgrade and budget alerts read the same numbers: the key quota, the
team quota and every rolling window cap. Unlimited budgets are left out.
Alerts report settled spend; downgrade also counts amounts held by in-flight
requests so a burst does not slip past the threshold.
"""

from dataclasses import dataclass

from app.models import APIKey, Tenant
from app.services import settlements
from app.services.auth import cached_tenant
from app.services.spend_windows import normalize_limits, window_spend


@dataclass(frozen=True)
class BudgetUsage:
    scope: str
    owner_id: int
    owner_name: str
    budget: str
    used: float
    limit: float

    @property
    def share(self) -> float:
        return self.used / self.limit if self.limit > 0 else 1.0


async def _owner_usages(scope: str, owner: APIKey | Tenant, include_in_flight: bool) -> list[BudgetUsage]:
    total = float(owner.quota_total)
    caps = normalize_limits(owner.window_limits)
    if total < 0 and not caps:
        return []
    held = 0.0
    if include_in_flight:
        held = float(await settlements.occupied("tenant" if scope == "team" else scope, owner.id))
    usages = []
    if total >= 0:
        usages.append(BudgetUsage(scope, owner.id, owner.name, "quota", float(owner.quota_used) + held, total))
    if caps:
        spent = await window_spend(scope, owner.id)
        usages.extend(
            BudgetUsage(scope, owner.id, owner.name, window, spent[window] + held, cap)
            for window, cap in caps.items()
        )
    return usages


async def budget_usages(api_key: APIKey, include_in_flight: bool = False) -> list[BudgetUsage]:
    usages = await _owner_usages("key", api_key, include_in_flight)
    if api_key.tenant_id:
        team = cached_tenant(api_key) or await Tenant.get_or_none(id=api_key.tenant_id)
        if team is not None:
            usages.extend(await _owner_usages("team", team, include_in_flight))
    return usages


async def budget_pressure(api_key: APIKey) -> float:
    """The highest share of any capped budget, counting in-flight holds, 0 when nothing is capped."""
    return max((usage.share for usage in await budget_usages(api_key, include_in_flight=True)), default=0.0)
