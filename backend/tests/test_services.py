import asyncio
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.models import APIKey, Channel, ModelPrice, RequestLog
from app.providers.openai_provider import OpenAIProvider
from app.services.auth import hash_api_key
from app.services.concurrency import ConcurrencyExceeded, ConcurrencyLimiter
from app.services.failover import is_retryable_error, upstream_status
from app.routers.anthropic_proxy import (
    _extract_anthropic_usage,
    _passthrough_stream_with_usage,
)
from app.services.channel_health import is_channel_healthy, record_failure
from app.services.logging_service import cleanup_old_logs
from app.services.pricing import calculate_cost, catalog_prices
from app.services.settings_service import set_gateway_config
from app.services.sticky_session import make_session_key
from app.services.proxy import extract_openai_usage
from app.services.quota import check_quota, deduct_quota, reset_expired_quotas
from app.utils.secrets import decrypt_secret, encrypt_secret, mask_secret
from app.utils.upstream_url import upstream_url
import httpx

pytestmark = [pytest.mark.asyncio, pytest.mark.regression]


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


async def test_extract_openai_cache_write_tokens():
    usage = extract_openai_usage({
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 200},
            "cache_write_tokens": 300,
        }
    })
    assert usage["cached_tokens"] == 200
    assert usage["cache_write_tokens"] == 300


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
        "cache_write_tokens": 0,
    }


async def test_cache_writes_are_billed_as_input():
    await ModelPrice.create(
        model="cache-split-model",
        prompt_price=Decimal("10"),
        completion_price=Decimal("50"),
        cached_price=Decimal("1"),
        cache_write_price=Decimal("12.5"),
    )
    cost = await calculate_cost(
        "cache-split-model", 1000, 0, None,
        cached_tokens=200, cache_write_tokens=300,
    )
    # Writes stay in the 800 input tokens. The stored write price is ignored.
    expected = (800 * Decimal("10") + 200 * Decimal("1")) / Decimal("1000000")
    assert cost == expected.quantize(Decimal("0.000001"))


async def test_missing_channel_write_price_uses_prompt_price():
    await ModelPrice.create(
        model="channel-write-fallback",
        prompt_price=Decimal("1"),
        completion_price=Decimal("1"),
        cached_price=Decimal("1"),
        cache_write_price=Decimal("99"),
    )
    ch = await Channel.create(
        name="write-fallback",
        provider="anthropic",
        base_url="https://example.test",
        api_key="sk-x",
        models=["channel-write-fallback"],
        model_pricing={
            "channel-write-fallback": {"prompt": 10, "completion": 20, "cached": 1},
        },
    )
    cost = await calculate_cost(
        "channel-write-fallback", 1000, 0, ch, cache_write_tokens=400,
    )
    # The 400 write tokens stay inside the 1000 input tokens at $10, not the global $99.
    expected = (1000 * Decimal("10")) / Decimal("1000000")
    assert cost == expected.quantize(Decimal("0.000001"))


async def test_channel_write_price_does_not_change_the_bill():
    await ModelPrice.create(
        model="free-write-model",
        prompt_price=Decimal("10"),
        completion_price=Decimal("20"),
        cache_write_price=Decimal("12.5"),
    )
    ch = await Channel.create(
        name="free-write",
        provider="anthropic",
        base_url="https://example.test",
        api_key="sk-x",
        models=["free-write-model"],
        model_pricing={
            "free-write-model": {
                "prompt": 10, "completion": 20, "cached": 1, "cache_write": 0,
            },
        },
    )
    cost = await calculate_cost(
        "free-write-model", 1000, 0, ch, cache_write_tokens=400,
    )
    expected = (1000 * Decimal("10")) / Decimal("1000000")
    assert cost == expected.quantize(Decimal("0.000001"))


async def test_cache_tokens_above_prompt_do_not_make_negative_cost():
    await ModelPrice.create(
        model="clamp-model",
        prompt_price=Decimal("10"),
        completion_price=Decimal("0"),
        cached_price=Decimal("1"),
        cache_write_price=Decimal("12.5"),
    )
    cost = await calculate_cost(
        "clamp-model", 100, 0, None, cached_tokens=80, cache_write_tokens=50,
    )
    expected = (20 * Decimal("10") + 80 * Decimal("1")) / Decimal("1000000")
    assert cost == expected.quantize(Decimal("0.000001"))


async def test_inactive_price_is_not_billed():
    await ModelPrice.create(
        model="inactive-price",
        prompt_price=Decimal("10"),
        completion_price=Decimal("20"),
        is_active=False,
    )
    assert await calculate_cost("inactive-price", 1000, 500, None) == Decimal("0.000000")


async def test_catalog_write_price_matches_input_price():
    for model in ("claude-sonnet-4-6", "deepseek-v4-flash", "gpt-4o", "gpt-5.6"):
        prices = catalog_prices(model)
        assert prices["cache_write"] == prices["prompt"]


async def test_anthropic_usage_is_billed_on_openai_token_basis():
    await ModelPrice.create(
        model="claude-bill",
        prompt_price=Decimal("10"),
        completion_price=Decimal("50"),
        cached_price=Decimal("1"),
        cache_write_price=Decimal("12.5"),
    )
    usage = _extract_anthropic_usage({
        "usage": {
            "input_tokens": 500,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 300,
            "output_tokens": 40,
        }
    })
    assert usage == {
        "prompt_tokens": 1000,
        "completion_tokens": 40,
        "cached_tokens": 200,
        "cache_write_tokens": 300,
    }
    cost = await calculate_cost("claude-bill", usage["prompt_tokens"], usage["completion_tokens"], None,
                                 cached_tokens=usage["cached_tokens"],
                                 cache_write_tokens=usage["cache_write_tokens"])
    expected = (
        800 * Decimal("10") + 200 * Decimal("1") + 40 * Decimal("50")
    ) / Decimal("1000000")
    assert cost == expected.quantize(Decimal("0.000001"))


async def test_anthropic_stream_usage_keeps_cache_read_and_write():
    class _Stream:
        async def stream_anthropic_passthrough(self, _body, _headers):
            for line in (
                'event: message_start\n',
                'data: {"message":{"usage":{"input_tokens":500,"cache_read_input_tokens":200,"cache_creation_input_tokens":300}}}\n\n',
                'event: message_delta\n',
                'data: {"usage":{"output_tokens":40}}\n\n',
            ):
                yield line

    last = {}
    async for _line, usage in _passthrough_stream_with_usage(_Stream(), {}, None):
        last = usage
    assert last == {
        "prompt_tokens": 1000,
        "completion_tokens": 40,
        "cached_tokens": 200,
        "cache_write_tokens": 300,
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


async def test_saved_retention_deletes_only_older_logs():
    await set_gateway_config({
        "log_retention_days": 2,
        "channel_health_threshold": 3,
        "channel_health_check_interval": 60,
        "sticky_session_enabled": True,
        "sticky_session_ttl": 900,
    })
    old = await RequestLog.create(request_id="old-log", api_key_id=1, model_requested="m")
    recent = await RequestLog.create(request_id="recent-log", api_key_id=1, model_requested="m")
    await RequestLog.filter(id=old.id).update(
        created_at=datetime.utcnow() - timedelta(days=5)
    )
    assert await cleanup_old_logs() == 1
    assert await RequestLog.filter(id=old.id).exists() is False
    assert await RequestLog.filter(id=recent.id).exists() is True


async def test_gateway_settings_change_sticky_sessions_and_health():
    await set_gateway_config({
        "log_retention_days": 90,
        "channel_health_threshold": 1,
        "channel_health_check_interval": 60,
        "sticky_session_enabled": False,
        "sticky_session_ttl": 900,
    })
    assert await make_session_key(1, {"x-session-id": "chat-1"}, {}) is None
    await record_failure(7)
    assert await is_channel_healthy(7) is False


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
