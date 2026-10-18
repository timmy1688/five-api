"""How much of each capped budget a key and its team have used.

Budget downgrade and budget alerts read the same numbers: the key quota, the
team quota and every rolling window cap. Unlimited budgets are left out.
"""

from dataclasses import dataclass

from app.models import APIKey, Team
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


async def _owner_usages(scope: str, owner: APIKey | Team) -> list[BudgetUsage]:
    usages = []
    total = float(owner.quota_total)
    if total >= 0:
        usages.append(BudgetUsage(scope, owner.id, owner.name, "quota", float(owner.quota_used), total))
    caps = normalize_limits(owner.window_limits)
    if caps:
        spent = await window_spend(scope, owner.id)
        usages.extend(
            BudgetUsage(scope, owner.id, owner.name, window, spent[window], cap)
            for window, cap in caps.items()
        )
    return usages


async def budget_usages(api_key: APIKey) -> list[BudgetUsage]:
    usages = await _owner_usages("key", api_key)
    if api_key.team_id:
        team = await Team.get_or_none(id=api_key.team_id)
        if team is not None:
            usages.extend(await _owner_usages("team", team))
    return usages


async def budget_pressure(api_key: APIKey) -> float:
    """The highest used share of any capped budget, 0 when nothing is capped."""
    return max((usage.share for usage in await budget_usages(api_key)), default=0.0)
