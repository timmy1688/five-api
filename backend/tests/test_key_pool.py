from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel
from app.services.auth import hash_api_key
from app.services.channel_health import is_channel_healthy
from app.services.key_pool import available_keys, retry_after_seconds
from app.utils.secrets import encrypt_secret, mask_secret, split_keys
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio

RAW_KEY = "sk-pool-client-key"


def _resp(status, payload, headers=None):
    return httpx.Response(
        status, json=payload, headers=headers or {},
        request=httpx.Request("POST", "https://api.openai.test/v1/chat/completions"),
    )


def _http(*responses):
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(side_effect=list(responses))
    return http


async def _env(keys: str):
    ch = await Channel.create(
        name="pool", provider="openai", base_url="https://api.openai.test",
        api_key=encrypt_secret(keys), models=["gpt-4o"], timeout=60,
    )
    await APIKey.create(
        name="pool-key", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8],
        quota_total=Decimal("-1"),
    )
    return ch


def _sent_keys(http):
    return [call.kwargs["headers"]["Authorization"] for call in http.post.await_args_list]


OK = {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def test_split_and_mask():
    assert split_keys(" a1\n\nb2, a1\nc3 ") == ["a1", "b2", "c3"]
    assert mask_secret("sk-abcdefghijkl") == "sk-a••••••••ijkl"
    assert mask_secret("sk-abcdefghijkl\nsk-zzzzzzzzzzzz") == "sk-a••••••••ijkl (+1)"


def test_retry_after_parsing():
    def exc(headers):
        return httpx.HTTPStatusError("x", request=None, response=_resp(429, {}, headers))

    assert retry_after_seconds(exc({"retry-after": "12"})) == 13
    assert retry_after_seconds(exc({"retry-after-ms": "1500"})) == 2
    assert retry_after_seconds(exc({})) == 30
    assert retry_after_seconds(exc({"retry-after": "99999"})) == 3600


async def test_rate_limited_key_rotates_on_same_channel(client):
    ch = await _env("sk-first\nsk-second")
    http = _http(_resp(429, {"error": {"message": "slow"}}, {"retry-after": "120"}), _resp(200, OK))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    first, second = _sent_keys(http)
    assert first != second
    assert await is_channel_healthy(ch.id)
    ready = await available_keys(ch.id, ["sk-first", "sk-second"])
    assert ready == [second.removeprefix("Bearer ")]


async def test_all_keys_limited_cools_channel(client):
    ch = await _env("sk-first\nsk-second")
    limited = {"error": {"message": "slow"}}
    http = _http(_resp(429, limited, {"retry-after": "60"}), _resp(429, limited, {"retry-after": "60"}))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 429
    assert http.post.await_count == 2
    assert not await is_channel_healthy(ch.id)


async def test_channel_response_reports_key_count(client, admin_token):
    created = await client.post(
        "/api/channels",
        json={
            "name": "multi", "provider": "openai", "base_url": "https://api.openai.test",
            "api_key": "sk-aaaaaaaaaaaa\nsk-bbbbbbbbbbbb\n", "models": ["gpt-4o"],
        },
        headers=auth_header(admin_token),
    )
    assert created.status_code in (200, 201)
    body = created.json()
    assert body["key_count"] == 2
    assert body["api_key"].endswith("(+1)")


async def test_model_fallback_after_primary_fails(client, admin_token):
    from app.models import ModelPrice, RequestLog
    from app.services.settings_service import clear_settings_cache

    await Channel.create(
        name="opus", provider="openai", base_url="https://api.openai.test",
        api_key="sk-a", models=["big-model"], timeout=60, max_retries=0,
    )
    await Channel.create(
        name="sonnet", provider="openai", base_url="https://api.openai.test",
        api_key="sk-b", models=["small-model"], timeout=60,
        model_mapping={"small-model": "small-model-2026"},
    )
    await APIKey.create(
        name="fb-key", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8],
        quota_total=Decimal("-1"),
    )
    await ModelPrice.create(model="small-model-2026", prompt_price=Decimal("1000000"), completion_price=Decimal("0"))
    saved = await client.put(
        "/api/settings",
        json={
            "log_retention_days": 90, "channel_health_threshold": 3,
            "channel_health_check_interval": 60, "sticky_session_enabled": True,
            "sticky_session_ttl": 900,
            "model_fallbacks": {"big-model": ["small-model", "big-model", "small-model"]},
        },
        headers=auth_header(admin_token),
    )
    assert saved.json()["model_fallbacks"] == {"big-model": ["small-model"]}
    clear_settings_cache()

    http = _http(_resp(503, {"error": {"message": "overloaded"}}), _resp(200, OK))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "big-model", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    sent = [call.kwargs["json"]["model"] for call in http.post.await_args_list]
    assert sent == ["big-model", "small-model-2026"]
    log = await RequestLog.get()
    assert (log.model_requested, log.model_actual, log.failed_over) == ("big-model", "small-model-2026", True)
    assert log.cost == Decimal("1")

    keep = await client.put(
        "/api/settings",
        json={
            "log_retention_days": 30, "channel_health_threshold": 3,
            "channel_health_check_interval": 60, "sticky_session_enabled": True,
            "sticky_session_ttl": 900,
        },
        headers=auth_header(admin_token),
    )
    assert keep.json()["model_fallbacks"] == {"big-model": ["small-model"]}
