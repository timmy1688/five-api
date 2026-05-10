from decimal import Decimal
from datetime import datetime, timezone, timedelta

import pytest

from app.models import APIKey, Channel, ModelPrice
from app.services.auth import hash_api_key
from app.services.pricing import calculate_cost
from app.services.quota import check_quota, deduct_quota, reset_expired_quotas

pytestmark = pytest.mark.asyncio


# ── pricing ─────────────────────────────────────────────────

async def test_calculate_cost_global_price():
    await ModelPrice.create(model="pricing-test-model", prompt_price=Decimal("3.0"), completion_price=Decimal("15.0"))
    cost = await calculate_cost("pricing-test-model", 1000, 500, None)
    expected = (1000 * Decimal("3.0") + 500 * Decimal("15.0")) / Decimal("1000000")
    assert cost == expected.quantize(Decimal("0.000001"))


async def test_calculate_cost_channel_override():
    ch = await Channel.create(
        name="pricing-ch",
        provider="openai",
        base_url="https://api.openai.com",
        api_key="sk-x",
        models=["override-model"],
        model_pricing={"override-model": {"prompt": 5.0, "completion": 20.0}},
    )
    cost = await calculate_cost("override-model", 2000, 1000, ch)
    expected = (2000 * Decimal("5.0") + 1000 * Decimal("20.0")) / Decimal("1000000")
    assert cost == expected.quantize(Decimal("0.000001"))


async def test_calculate_cost_no_pricing():
    cost = await calculate_cost("unknown-model-xyz", 1000, 500, None)
    assert cost == Decimal("0.000000")


async def test_calculate_cost_zero_tokens():
    await ModelPrice.create(model="zero-tok-model", prompt_price=Decimal("3.0"), completion_price=Decimal("15.0"))
    cost = await calculate_cost("zero-tok-model", 0, 0, None)
    assert cost == Decimal("0.000000")


# ── quota ───────────────────────────────────────────────────

async def test_check_quota_unlimited():
    k = await APIKey.create(
        name="unlim", key_hash=hash_api_key("sk-unlim"), key_prefix="sk-unlim",
        quota_total=Decimal("-1"), quota_used=Decimal("999"),
    )
    assert await check_quota(k) is True


async def test_check_quota_within_limit():
    k = await APIKey.create(
        name="within", key_hash=hash_api_key("sk-within"), key_prefix="sk-withi",
        quota_total=Decimal("10"), quota_used=Decimal("5"),
    )
    assert await check_quota(k) is True


async def test_check_quota_exceeded():
    k = await APIKey.create(
        name="over", key_hash=hash_api_key("sk-over"), key_prefix="sk-over0",
        quota_total=Decimal("10"), quota_used=Decimal("10"),
    )
    assert await check_quota(k) is False


async def test_deduct_quota():
    k = await APIKey.create(
        name="deduct", key_hash=hash_api_key("sk-deduct"), key_prefix="sk-deduc",
        quota_total=Decimal("10"), quota_used=Decimal("0"),
    )
    await deduct_quota(k.id, Decimal("2.5"))
    await k.refresh_from_db()
    assert k.quota_used == Decimal("2.5")


async def test_deduct_quota_zero_cost():
    k = await APIKey.create(
        name="zero", key_hash=hash_api_key("sk-zero-d"), key_prefix="sk-zero-",
        quota_total=Decimal("10"), quota_used=Decimal("3"),
    )
    await deduct_quota(k.id, Decimal("0"))
    await k.refresh_from_db()
    assert k.quota_used == Decimal("3")


# ── quota reset ─────────────────────────────────────────────

async def test_reset_expired_quotas_resets_on_day():
    now = datetime.now(timezone.utc)
    k = await APIKey.create(
        name="reset-test", key_hash=hash_api_key("sk-reset1"), key_prefix="sk-reset",
        quota_total=Decimal("100"), quota_used=Decimal("50"),
        quota_reset_day=now.day,
    )
    count = await reset_expired_quotas()
    assert count >= 1
    await k.refresh_from_db()
    assert k.quota_used == Decimal("0")
    assert k.quota_last_reset_at is not None


async def test_reset_expired_quotas_skips_future_day():
    now = datetime.now(timezone.utc)
    future_day = 28 if now.day < 28 else 1
    if future_day <= now.day:
        pytest.skip("Cannot create a future day in current month")
    k = await APIKey.create(
        name="no-reset", key_hash=hash_api_key("sk-nores1"), key_prefix="sk-nores",
        quota_total=Decimal("100"), quota_used=Decimal("50"),
        quota_reset_day=future_day,
    )
    await reset_expired_quotas()
    await k.refresh_from_db()
    assert k.quota_used == Decimal("50")


async def test_reset_expired_quotas_skips_already_reset():
    now = datetime.now(timezone.utc)
    k = await APIKey.create(
        name="already", key_hash=hash_api_key("sk-alrdy1"), key_prefix="sk-alrdy",
        quota_total=Decimal("100"), quota_used=Decimal("50"),
        quota_reset_day=now.day,
        quota_last_reset_at=now,
    )
    count_before = await reset_expired_quotas()
    await k.refresh_from_db()
    assert k.quota_used == Decimal("50")


async def test_reset_expired_quotas_no_reset_day():
    k = await APIKey.create(
        name="no-day", key_hash=hash_api_key("sk-noday1"), key_prefix="sk-noday",
        quota_total=Decimal("100"), quota_used=Decimal("50"),
    )
    await reset_expired_quotas()
    await k.refresh_from_db()
    assert k.quota_used == Decimal("50")
