import asyncio
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.models import APIKey, Channel, ModelPrice
from app.providers.openai_provider import OpenAIProvider
from app.services.auth import hash_api_key
from app.services.concurrency import ConcurrencyExceeded, ConcurrencyLimiter
from app.services.failover import is_retryable_error, upstream_status
from app.services.pricing import calculate_cost
from app.services.proxy import extract_openai_usage
from app.services.quota import check_quota, deduct_quota, reset_expired_quotas
from app.utils.secrets import decrypt_secret, encrypt_secret, mask_secret
from app.utils.upstream_url import upstream_url
import httpx

pytestmark = pytest.mark.asyncio


async def test_secret_round_trip_and_mask():
    encrypted = encrypt_secret("sk-super-secret-value")
    assert encrypted.startswith("fernet:")
    assert decrypt_secret(encrypted) == "sk-super-secret-value"
    assert mask_secret(encrypted) == "sk-s••••••••alue"


async def test_retryable_upstream_statuses():
    request = httpx.Request("POST", "https://upstream.test/v1/messages")
    rate_limited = httpx.Response(429, request=request)
    bad_request = httpx.Response(400, request=request)
    rate_error = httpx.HTTPStatusError("rate limited", request=request, response=rate_limited)
    bad_error = httpx.HTTPStatusError("bad request", request=request, response=bad_request)
    assert is_retryable_error(rate_error)
    assert upstream_status(rate_error) == 429
    assert not is_retryable_error(bad_error)


async def test_openai_compatible_channel_accepts_v1_base_url_without_key():
    channel = await Channel.create(
        name="local-vllm",
        provider="openai",
        base_url="http://127.0.0.1:8000/v1",
        api_key="",
        models=["local-model"],
    )
    provider = OpenAIProvider(channel)
    try:
        path, headers, body = provider.transform_request(
            {"model": "local-model", "messages": []},
            "/v1/chat/completions",
        )
        assert path == "chat/completions"
        assert "Authorization" not in headers
        assert body["model"] == "local-model"
        assert str(provider.client.build_request("POST", path).url) == (
            "http://127.0.0.1:8000/v1/chat/completions"
        )
    finally:
        await provider.close()


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


async def test_calculate_cost_explicit_zero_channel_override():
    await ModelPrice.create(
        model="free-channel-model",
        prompt_price=Decimal("3.0"),
        completion_price=Decimal("15.0"),
    )
    ch = await Channel.create(
        name="free-pricing-ch",
        provider="openai",
        base_url="https://example.test/v1",
        api_key="",
        models=["free-channel-model"],
        model_pricing={
            "free-channel-model": {
                "prompt": 0,
                "completion": 0,
                "cached": 0,
            }
        },
    )
    assert await calculate_cost(
        "free-channel-model", 1000, 500, ch
    ) == Decimal("0.000000")


async def test_calculate_cost_uses_mapped_alias_price():
    ch = await Channel.create(
        name="mapped-pricing",
        provider="openai",
        base_url="https://example.test",
        api_key="sk-x",
        models=["public-model"],
        model_mapping={"public-model": "upstream-model"},
        model_pricing={"public-model": {"prompt": 1.0, "completion": 2.0}},
    )
    assert await calculate_cost("upstream-model", 1000, 500, ch) == Decimal("0.002000")


async def test_calculate_cost_no_pricing():
    cost = await calculate_cost("unknown-model-xyz", 1000, 500, None)
    assert cost == Decimal("0.000000")


async def test_calculate_cost_zero_tokens():
    await ModelPrice.create(model="zero-tok-model", prompt_price=Decimal("3.0"), completion_price=Decimal("15.0"))
    cost = await calculate_cost("zero-tok-model", 0, 0, None)
    assert cost == Decimal("0.000000")


async def test_extract_deepseek_cache_usage():
    usage = extract_openai_usage({
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 40,
        }
    })
    assert usage == {
        "prompt_tokens": 120,
        "completion_tokens": 10,
        "cached_tokens": 80,
    }


async def test_upstream_url_avoids_duplicate_api_prefix():
    assert upstream_url(
        "http://vllm.test:8000/v1", "/v1/models"
    ) == "http://vllm.test:8000/v1/models"
    assert upstream_url(
        "https://api.example.test", "/v1/messages"
    ) == "https://api.example.test/v1/messages"


async def test_concurrency_uses_request_specific_leases():
    class LeaseRedis:
        def __init__(self):
            self.members = set()

        async def eval(self, script, _num_keys, _key, *args):
            if "ZREMRANGEBYSCORE" in script:
                limit, _ttl, member, _now = args
                if len(self.members) >= int(limit):
                    return 0
                self.members.add(member)
                return 1
            if "ZREM" in script:
                member = args[0]
                existed = member in self.members
                self.members.discard(member)
                return int(existed)
            return 1

    redis = LeaseRedis()
    limiter = ConcurrencyLimiter()
    with patch("app.services.concurrency.get_redis", return_value=redis):
        first = await limiter.acquire(42, 1)
        with pytest.raises(ConcurrencyExceeded):
            await limiter.acquire(42, 1)
        await limiter.release(42, first)
        second = await limiter.acquire(42, 1)
        assert second != first
        await limiter.release(42, second)

    assert redis.members == set()


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


async def test_concurrent_quota_deductions_are_not_lost():
    k = await APIKey.create(
        name="parallel-deduct",
        key_hash=hash_api_key("sk-parallel-deduct"),
        key_prefix="sk-paral",
        quota_total=Decimal("10"),
        quota_used=Decimal("0"),
    )
    await asyncio.gather(*[
        deduct_quota(k.id, Decimal("0.000001"))
        for _ in range(100)
    ])
    await k.refresh_from_db()
    assert k.quota_used == Decimal("0.000100")


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


async def test_reset_day_31_uses_last_day_of_short_month():
    k = await APIKey.create(
        name="month-end",
        key_hash=hash_api_key("sk-month-end"),
        key_prefix="sk-month",
        quota_total=Decimal("100"),
        quota_used=Decimal("50"),
        quota_reset_day=31,
        quota_last_reset_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )
    with patch("app.services.quota.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = datetime(
            2026, 2, 28, 12, 0, tzinfo=timezone.utc
        )
        assert await reset_expired_quotas() == 1
    await k.refresh_from_db()
    assert k.quota_used == Decimal("0")
