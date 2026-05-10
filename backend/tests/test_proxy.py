from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models import APIKey, Channel, ModelPrice
from app.services.auth import hash_api_key
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


async def _setup_proxy_env():
    """Create channel + api key + pricing for proxy tests."""
    ch = await Channel.create(
        name="proxy-ch", provider="openai",
        base_url="https://api.openai.com",
        api_key="sk-upstream",
        models=["gpt-4o"],
        model_mapping={},
        model_pricing={},
        is_enabled=True, timeout=60,
    )
    await ModelPrice.create(model="gpt-4o", prompt_price=Decimal("2.5"), completion_price=Decimal("10.0"))
    raw_key = "sk-proxytest123456"
    api_key = await APIKey.create(
        name="proxy-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("100"),
        quota_used=Decimal("0"),
        concurrent_limit=5,
    )
    return ch, api_key, raw_key


MOCK_COMPLETION_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "gpt-4o",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


async def test_chat_completions_non_stream(client):
    ch, api_key, raw_key = await _setup_proxy_env()

    mock_provider = AsyncMock()
    mock_provider.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    mock_provider.apply_model_mapping = lambda m: m
    mock_provider.close = AsyncMock()

    with patch("app.routers.openai_proxy.resolve_channel", return_value=(ch, mock_provider)):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "Hello!"
    assert data["usage"]["total_tokens"] == 15

    mock_provider.send_request.assert_called_once()
    mock_provider.close.assert_called_once()

    # verify quota was deducted
    await api_key.refresh_from_db()
    assert api_key.quota_used > Decimal("0")


async def test_chat_completions_quota_exceeded(client):
    raw_key = "sk-quotaexceeded123"
    await APIKey.create(
        name="over-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("1"),
        quota_used=Decimal("1"),
        concurrent_limit=5,
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw_key),
    )
    assert resp.status_code == 429
    assert "quota" in resp.json()["error"]["message"].lower()


async def test_chat_completions_model_not_allowed(client):
    raw_key = "sk-modelforbid123"
    await APIKey.create(
        name="restricted-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
        concurrent_limit=5,
        allowed_models=["gpt-3.5-turbo"],
    )
    await Channel.create(
        name="restrict-ch", provider="openai",
        base_url="https://api.openai.com",
        api_key="sk-up", models=["gpt-4o"],
        is_enabled=True, timeout=60,
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw_key),
    )
    assert resp.status_code == 403


async def test_chat_completions_invalid_key(client):
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header("sk-invalid-key-that-does-not-exist"),
    )
    assert resp.status_code == 401


async def test_chat_completions_disabled_key(client):
    raw_key = "sk-disabledkey123"
    await APIKey.create(
        name="disabled",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
        is_enabled=False,
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw_key),
    )
    assert resp.status_code == 401


async def test_list_models(client):
    await Channel.create(
        name="models-ch", provider="openai",
        base_url="https://api.openai.com", api_key="sk-up",
        models=["gpt-4o", "gpt-4o-mini"], is_enabled=True, timeout=60,
    )
    raw_key = "sk-listmodels123"
    await APIKey.create(
        name="list-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
    )
    resp = await client.get("/v1/models", headers=auth_header(raw_key))
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    model_ids = [m["id"] for m in data["data"]]
    assert "gpt-4o" in model_ids


async def test_list_models_filtered_by_allowed(client):
    await Channel.create(
        name="filter-ch", provider="openai",
        base_url="https://api.openai.com", api_key="sk-up",
        models=["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"], is_enabled=True, timeout=60,
    )
    raw_key = "sk-filtermodels123"
    await APIKey.create(
        name="filter-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
        allowed_models=["gpt-4o"],
    )
    resp = await client.get("/v1/models", headers=auth_header(raw_key))
    assert resp.status_code == 200
    model_ids = [m["id"] for m in resp.json()["data"]]
    assert "gpt-4o" in model_ids
    assert "gpt-4o-mini" not in model_ids


async def test_embeddings_non_stream(client):
    ch = await Channel.create(
        name="embed-ch", provider="openai",
        base_url="https://api.openai.com", api_key="sk-up",
        models=["text-embedding-3-small"], is_enabled=True, timeout=60,
    )
    raw_key = "sk-embed123456"
    api_key = await APIKey.create(
        name="embed-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
    )

    mock_response = {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }
    mock_provider = AsyncMock()
    mock_provider.send_request = AsyncMock(return_value=mock_response)
    mock_provider.apply_model_mapping = lambda m: m
    mock_provider.close = AsyncMock()

    with patch("app.routers.openai_proxy.resolve_channel", return_value=(ch, mock_provider)):
        resp = await client.post(
            "/v1/embeddings",
            json={"model": "text-embedding-3-small", "input": "hello"},
            headers=auth_header(raw_key),
        )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["embedding"] == [0.1, 0.2]


async def test_no_channel_for_model(client):
    raw_key = "sk-nomodel123456"
    await APIKey.create(
        name="nomodel-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "nonexistent-model", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw_key),
    )
    assert resp.status_code == 404
