from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import httpx

from app.models import APIKey, Channel, ModelGroup, ModelPrice, RequestLog, RequestLogAudit
from app.services.auth import hash_api_key
from app.services.settings_service import set_inference_audit_enabled
from tests.conftest import auth_header

pytestmark = [pytest.mark.asyncio, pytest.mark.regression]


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

    mock_provider_cls = lambda channel: mock_provider

    with patch("app.routers.openai_proxy.resolve_candidates", return_value=[(ch, mock_provider_cls)]):
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


async def test_openai_cache_read_is_deducted_and_logged(client):
    ch, api_key, raw_key = await _setup_proxy_env()
    price = await ModelPrice.get(model="gpt-4o")
    price.cached_price = Decimal("0.25")
    await price.save()
    response = {
        **MOCK_COMPLETION_RESPONSE,
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 10,
            "total_tokens": 1010,
            "prompt_tokens_details": {"cached_tokens": 200},
        },
    }
    mock_provider = AsyncMock()
    mock_provider.send_request = AsyncMock(return_value=response)
    mock_provider.apply_model_mapping = lambda model: model
    mock_provider.close = AsyncMock()

    with patch("app.routers.openai_proxy.resolve_candidates", return_value=[(ch, lambda _: mock_provider)]):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    expected = (800 * Decimal("2.5") + 200 * Decimal("0.25") + 10 * Decimal("10")) / Decimal("1000000")
    expected = expected.quantize(Decimal("0.000001"))
    await api_key.refresh_from_db()
    assert api_key.quota_used == expected
    log = await RequestLog.get(api_key_id=api_key.id)
    assert log.prompt_tokens == 1000
    assert log.cached_tokens == 200
    assert log.cache_write_tokens == 0
    assert log.cost == expected


class _Upstream:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


async def test_anthropic_cache_read_and_write_are_deducted(client):
    await Channel.create(
        name="bill-anthropic",
        provider="anthropic",
        base_url="https://upstream.anthropic.test",
        api_key="sk-ant",
        models=["claude-bill"],
    )
    await ModelPrice.create(
        model="claude-bill",
        prompt_price=Decimal("10"),
        completion_price=Decimal("50"),
        cached_price=Decimal("1"),
        cache_write_price=Decimal("12.5"),
    )
    raw = "sk-anthropic-bill"
    api_key = await APIKey.create(
        name="anthropic-bill",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("100"),
        quota_used=Decimal("0"),
    )
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(return_value=_Upstream({
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 500,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 300,
            "output_tokens": 40,
        },
    }))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/messages",
            json={
                "model": "claude-bill",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=auth_header(raw),
        )

    assert resp.status_code == 200
    expected = (
        800 * Decimal("10") + 200 * Decimal("1") + 40 * Decimal("50")
    ) / Decimal("1000000")
    expected = expected.quantize(Decimal("0.000001"))
    await api_key.refresh_from_db()
    assert api_key.quota_used == expected
    log = await RequestLog.get(api_key_id=api_key.id)
    assert log.prompt_tokens == 1000
    assert log.cached_tokens == 200
    assert log.cache_write_tokens == 300
    assert log.cost == expected


async def test_channel_retry_before_failover(client):
    ch, _, raw_key = await _setup_proxy_env()
    ch.max_retries = 1
    await ch.save()
    mock_provider = AsyncMock()
    mock_provider.send_request = AsyncMock(
        side_effect=[httpx.ReadTimeout("timeout"), MOCK_COMPLETION_RESPONSE]
    )
    mock_provider.apply_model_mapping = lambda model: model
    mock_provider.close = AsyncMock()

    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(ch, lambda _: mock_provider)],
    ):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    assert mock_provider.send_request.await_count == 2


async def test_cross_channel_failover_is_logged(client):
    first, _, raw_key = await _setup_proxy_env()
    first.max_retries = 0
    await first.save()
    second = await Channel.create(
        name="proxy-fallback",
        provider="openai",
        base_url="https://fallback.test",
        api_key="sk-upstream-2",
        models=["gpt-4o"],
        max_retries=0,
    )
    failing = AsyncMock()
    failing.send_request = AsyncMock(side_effect=httpx.ConnectError("down"))
    failing.apply_model_mapping = lambda model: model
    failing.close = AsyncMock()
    working = AsyncMock()
    working.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    working.apply_model_mapping = lambda model: model
    working.close = AsyncMock()

    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[
            (first, lambda _: failing),
            (second, lambda _: working),
        ],
    ):
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.channel_id == second.id
    assert log.failed_over is True


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
    body = resp.json()
    error = body.get("error") or body.get("detail", {}).get("error", {})
    assert "quota" in error.get("message", "").lower()
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.status_code == 429
    assert log.channel_id is None
    assert log.error_origin == "gateway"
    assert log.upstream_status_code == 0
    assert log.upstream_error == ""


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


async def test_empty_model_group_denies_all_models(client):
    group = await ModelGroup.create(name="empty-group", models=[])
    raw_key = "sk-emptygroup123"
    await APIKey.create(
        name="empty-group-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
        model_group_id=group.id,
    )
    await Channel.create(
        name="empty-group-ch",
        provider="openai",
        base_url="https://api.openai.com",
        api_key="sk-up",
        models=["gpt-4o"],
    )

    models = await client.get("/v1/models", headers=auth_header(raw_key))
    assert models.status_code == 200
    assert models.json()["data"] == []

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        },
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

    mock_provider_cls = lambda channel: mock_provider

    with patch("app.routers.openai_proxy.resolve_candidates", return_value=[(ch, mock_provider_cls)]):
        resp = await client.post(
            "/v1/embeddings",
            json={"model": "text-embedding-3-small", "input": "hello"},
            headers=auth_header(raw_key),
        )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["embedding"] == [0.1, 0.2]


async def test_embeddings_rejects_anthropic_only_channel(client):
    await Channel.create(
        name="anthropic-embed",
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-ant",
        models=["embedding-lookalike"],
    )
    raw_key = "sk-anthropicembed"
    await APIKey.create(
        name="anthropic-embed-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
    )
    resp = await client.post(
        "/v1/embeddings",
        json={"model": "embedding-lookalike", "input": "hello"},
        headers=auth_header(raw_key),
    )
    assert resp.status_code == 404


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


async def test_inference_audit_records_only_when_enabled(client):
    ch, _api_key, raw_key = await _setup_proxy_env()
    mock_provider = AsyncMock()
    mock_provider.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    mock_provider.apply_model_mapping = lambda model: model
    mock_provider.close = AsyncMock()
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}

    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(ch, lambda _: mock_provider)],
    ):
        quiet = await client.post(
            "/v1/chat/completions", json=payload, headers=auth_header(raw_key),
        )
        assert quiet.status_code == 200
        await set_inference_audit_enabled(True)
        audited = await client.post(
            "/v1/chat/completions", json=payload, headers=auth_header(raw_key),
        )

    assert audited.status_code == 200
    quiet_log = await RequestLog.get(request_id=quiet.headers["x-request-id"])
    audited_log = await RequestLog.get(request_id=audited.headers["x-request-id"])
    assert quiet_log.has_audit is False
    assert await RequestLogAudit.get_or_none(request_log_id=quiet_log.id) is None
    assert audited_log.has_audit is True
    audit = await RequestLogAudit.get(request_log_id=audited_log.id)
    assert "hi" in audit.audit_request
    assert not hasattr(audit, "audit_response")
