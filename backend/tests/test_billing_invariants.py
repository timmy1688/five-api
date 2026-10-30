"""Money invariants: holds cover charges, and each channel is billed at its own price."""
import random
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.models import APIKey, Channel, ModelPrice, Settlement, Tenant
from app.services import quota, settlements
from app.services.auth import hash_api_key
from app.services.billing_quotes import estimate_quotes, quote_cost, selling_quote, snapshot_quotes
from tests.conftest import auth_header, create_test_tenant


def _quote(rng: random.Random) -> dict:
    prompt = Decimal(rng.choice(["0", "0.1", "1", "2.5", "15"]))
    return {"model": "m", "source": "global", "multiplier": str(rng.choice(["0.5", "1", "1.2", "3"])), "prices": {
        "input": str(prompt),
        "output": str(rng.choice(["0", "0.4", "10", "75"])),
        "cache_read": str(prompt * Decimal(rng.choice(["0", "0.1", "0.5"]))),
        # Anthropic writes cost more than fresh input; the hold must still cover them.
        "cache_write": str(prompt * Decimal(rng.choice(["0", "1", "1.25", "2"]))),
        "request": str(rng.choice(["0", "0.04", "0.3"])),
    }}


def test_hold_covers_every_charge_within_the_estimate():
    rng = random.Random(20261030)
    for _ in range(3000):
        quotes = {f"c{i}": {"selling": _quote(rng)} for i in range(rng.randint(1, 3))}
        input_cap, output_cap, units = rng.randint(1, 200_000), rng.randint(0, 64_000), rng.randint(0, 4)
        hold = estimate_quotes(quotes, input_cap, output_cap, units)
        prompt = rng.randint(0, input_cap)
        cache_read = rng.randint(0, prompt)
        cache_write = rng.randint(0, prompt - cache_read)
        output = rng.randint(0, output_cap)
        for snapshot in quotes.values():
            charge = quote_cost(snapshot["selling"], prompt, output, cache_read, cache_write, units)["cost"]
            assert Decimal(0) <= charge <= hold, (snapshot, prompt, output, cache_read, cache_write, units)


@pytest.mark.parametrize("field", range(5))
def test_negative_usage_is_rejected(field):
    usage = [10, 10, 0, 0, 0]
    usage[field] = -1
    with pytest.raises(ValueError):
        quote_cost(_quote(random.Random(1)), *usage)


async def test_selling_quote_never_silently_prices_at_zero():
    with pytest.raises(HTTPException) as missing:
        await selling_quote("vendor-unknown-model")
    assert missing.value.status_code == 503
    await ModelPrice.create(model="paused", prompt_price=Decimal(1), completion_price=Decimal(1), is_active=False)
    with pytest.raises(HTTPException) as paused:
        await selling_quote("paused")
    assert paused.value.status_code == 503
    await ModelPrice.create(model="free", prompt_price=Decimal(0), completion_price=Decimal(0))
    free = await selling_quote("free")
    assert free["source"] == "global"
    assert quote_cost(free, 1000, 1000, 0, 0, 0)["cost"] == 0


async def test_each_channel_has_its_own_price_and_the_hold_covers_the_dearest():
    await ModelPrice.create(model="gpt-4o", prompt_price=Decimal("2.5"), completion_price=Decimal(10))
    cheap = await Channel.create(name="cheap", provider="openai", base_url="https://a.example.com",
                                 api_key="k", models=["gpt-4o"], price_multiplier=Decimal("0.5"))
    fixed = await Channel.create(name="fixed", provider="openai", base_url="https://b.example.com",
                                 api_key="k", models=["gpt-4o"], price_multiplier=Decimal("9"),
                                 price_overrides={"gpt-4o": {"prompt": 1, "completion": 4}})
    dear = await Channel.create(name="dear", provider="openai", base_url="https://c.example.com",
                                api_key="k", models=["gpt-4o"], price_multiplier=Decimal("2"))
    quotes = await snapshot_quotes("gpt-4o", [(cheap, object()), (fixed, object()), (dear, object())])
    assert set(quotes) == {f"{cheap.id}:gpt-4o", f"{fixed.id}:gpt-4o", f"{dear.id}:gpt-4o"}
    assert all(set(snapshot) == {"selling"} for snapshot in quotes.values())

    def charge(channel):
        return quote_cost(quotes[f"{channel.id}:gpt-4o"]["selling"], 1_000_000, 1_000_000, 0, 0, 0)["cost"]

    assert charge(cheap) == Decimal("6.25")
    # A fixed channel price is final; the channel multiplier does not apply on top.
    assert quotes[f"{fixed.id}:gpt-4o"]["selling"]["source"] == "channel"
    assert charge(fixed) == Decimal("5")
    assert charge(dear) == Decimal("25")
    assert estimate_quotes(quotes, 1_000_000, 1_000_000, 0) == Decimal("25")


async def test_end_to_end_charge_never_exceeds_the_reservation(client):
    channel = await Channel.create(name="e2e", provider="openai", base_url="https://e2e.example.com",
                                   api_key="k", models=["gpt-4o"], price_multiplier=Decimal("1.3"))
    await ModelPrice.create(model="gpt-4o", prompt_price=Decimal("2.5"), completion_price=Decimal(10),
                            cached_price=Decimal("1.25"))
    tenant = await create_test_tenant()
    raw = "sk-billing-invariant-key"
    key = await APIKey.create(tenant_id=tenant.id, name="inv", key_hash=hash_api_key(raw),
                              key_prefix=raw[:8], quota_total=Decimal("100"))
    body = {"model": "gpt-4o", "max_tokens": 300, "messages": [{"role": "user", "content": "x" * 4000}]}
    usage = {"prompt_tokens": 1000, "completion_tokens": 300, "total_tokens": 1300,
             "prompt_tokens_details": {"cached_tokens": 400}}
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value={"id": "1", "object": "chat.completion", "model": "gpt-4o",
                                                    "choices": [], "usage": usage})
    provider.apply_model_mapping = lambda model: model
    holds = []
    original = settlements.reserve

    async def capture(request_id, api_key, amount, quotes):
        holds.append(amount)
        return await original(request_id, api_key, amount, quotes)

    with patch("app.services.routing.resolve_with_fallbacks", return_value=[(channel, lambda _: provider)]), \
            patch.object(settlements, "reserve", capture):
        response = await client.post("/v1/chat/completions", json=body, headers=auth_header(raw))
    assert response.status_code == 200
    await key.refresh_from_db()
    await tenant.refresh_from_db()
    assert len(holds) == 1 and Decimal(0) < key.quota_used <= holds[0]
    assert tenant.quota_used == key.quota_used
    record = await Settlement.get()
    assert record.state == "settled" and record.occupied == 0 and record.cost == key.quota_used


class _FixedNow(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 2, 15, 12, tzinfo=timezone.utc)


async def test_monthly_reset_waits_for_open_reservations():
    tenant = await Tenant.create(name="reset", quota_total=Decimal(10), quota_used=Decimal(4), quota_reset_day=1)
    key = await APIKey.create(tenant_id=tenant.id, name="r", key_hash="h", key_prefix="sk-r",
                              quota_total=Decimal(10), quota_used=Decimal(4), quota_reset_day=31)
    await Settlement.create(request_id="open", tenant_id=tenant.id, api_key_id=key.id,
                            state="pending", occupied=Decimal(1), cost=Decimal(1))
    with patch.object(quota, "datetime", _FixedNow):
        assert await quota.reset_expired_quotas() == 0
        await Settlement.filter(request_id="open").update(state="settled", occupied=0)
        # Day 31 clamps to the last day of February, which is still ahead of the 15th.
        assert await quota.reset_expired_quotas() == 1
        assert await quota.reset_expired_quotas() == 0
    await tenant.refresh_from_db()
    await key.refresh_from_db()
    assert tenant.quota_used == 0 and key.quota_used == 4
