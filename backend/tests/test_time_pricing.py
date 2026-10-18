from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models import ModelPrice
from app.services.pricing import cost_breakdown
from app.services.settings_service import clear_settings_cache, set_gateway_config
from app.services.time_pricing import match_rule, normalize_rules, peak_multiplier

RULES = normalize_rules([
    {"name": "night", "models": ["deepseek-*"], "start": "16:30", "end": "00:30", "utc_offset": 0, "multiplier": 0.5},
    {"name": "peak", "channel_ids": [2], "start": "09:00", "end": "18:00", "utc_offset": 8, "multiplier": 1.5},
    {"start": "bad", "end": "10:00"},
    {"start": "10:00", "end": "10:00"},
])


def at(hour, minute=0):
    return datetime(2026, 10, 1, hour, minute, tzinfo=timezone.utc)


def test_normalize_drops_invalid_and_names_rules():
    assert [r["name"] for r in RULES] == ["night", "peak"]
    assert normalize_rules([{"start": "01:00", "end": "02:00", "multiplier": 99}])[0] == {
        "name": "01:00-02:00", "models": [], "channel_ids": [], "start": "01:00",
        "end": "02:00", "utc_offset": 0, "multiplier": 10.0,
    }


def test_window_wraps_midnight_and_follows_offset():
    assert match_rule(RULES, "deepseek-chat", 1, at(23))["name"] == "night"
    assert match_rule(RULES, "deepseek-chat", 1, at(0, 15))["name"] == "night"
    assert match_rule(RULES, "deepseek-chat", 1, at(0, 30)) is None
    assert match_rule(RULES, "gpt-4o", 1, at(23)) is None
    # 02:00 UTC is 10:00 at UTC+8.
    assert match_rule(RULES, "gpt-4o", 2, at(2))["name"] == "peak"
    assert match_rule(RULES, "gpt-4o", 1, at(2)) is None
    assert peak_multiplier(RULES, "gpt-4o", at(2)) == 1.5
    assert peak_multiplier(RULES, "deepseek-chat", at(23)) == 1.0


@pytest.mark.asyncio
async def test_cost_breakdown_applies_multiplier():
    await ModelPrice.create(model="deepseek-chat", prompt_price=Decimal("1"), completion_price=Decimal("2"), cached_price=Decimal("0.1"))
    await set_gateway_config({"time_pricing": RULES})
    clear_settings_cache()
    try:
        night = await cost_breakdown("deepseek-chat", 1_000_000, 1_000_000, cached_tokens=500_000, at=at(20))
        day = await cost_breakdown("deepseek-chat", 1_000_000, 1_000_000, cached_tokens=500_000, at=at(10))
    finally:
        await set_gateway_config({})
        clear_settings_cache()
    assert day["cost"] == Decimal("2.55")
    assert day["detail"]["time_rule"] is None
    assert night["cost"] == Decimal("1.275")
    assert night["cache_savings"] == Decimal("0.225")
    assert night["detail"]["time_rule"] == {"name": "night", "multiplier": 0.5}
