from tests.conftest import create_test_tenant
import time
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import anyio
import httpx
import pytest

from app.models import APIKey, Channel, ModelGroup, ModelPrice, RequestLog, RequestLogAudit
from app.services.auth import hash_api_key
from app.services.proxy import stream_with_failover
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
    api_key = await APIKey.create(tenant_id=(await create_test_tenant()).id,
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

    with patch("app.services.routing.resolve_with_fallbacks", return_value=[(ch, mock_provider_cls)]):
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

    with patch("app.services.routing.resolve_with_fallbacks", return_value=[(ch, lambda _: mock_provider)]):
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
    api_key = await APIKey.create(tenant_id=(await create_test_tenant()).id,
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
        500 * Decimal("10") + 200 * Decimal("1") + 300 * Decimal("12.5") + 40 * Decimal("50")
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
        "app.services.routing.resolve_with_fallbacks",
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
        "app.services.routing.resolve_with_fallbacks",
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


async def test_quota_hold_rejects_a_request_larger_than_the_remainder(client):
    ch, _, _ = await _setup_proxy_env()
    raw = "sk-hold-small"
    key = await APIKey.create(tenant_id=(await create_test_tenant()).id,
        name="hold-small",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("0.01"),
        quota_used=Decimal("0"),
    )
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    provider.apply_model_mapping = lambda m: m
    provider.close = AsyncMock()
    with patch("app.services.routing.resolve_with_fallbacks", return_value=[(ch, lambda _: provider)]):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw),
        )
    assert resp.status_code == 429
    provider.send_request.assert_not_awaited()
    await key.refresh_from_db()
    assert key.quota_used == 0


async def test_tpm_limit_rejects_before_upstream(client):
    await _setup_proxy_env()
    raw = "sk-tpm-reject"
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
        name="tpm-reject",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("-1"),
        tpm_limit=10,
    )
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(return_value=type("Resp", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: MOCK_COMPLETION_RESPONSE,
    })())
    with patch("app.providers.base._shared_http_client", return_value=http):
        blocked = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw),
        )
        allowed = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=auth_header(raw),
        )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "tpm_limit"
    assert allowed.status_code == 200
    http.post.assert_awaited()


async def test_chat_completions_quota_exceeded(client):
    raw_key = "sk-quotaexceeded123"
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
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
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
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
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
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
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
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
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
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
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
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


async def test_embeddings_and_completions_accept_token_arrays(client):
    await ModelPrice.create(model="text-embedding-3-small")
    await ModelPrice.create(model="gpt-3.5-turbo")
    ch = await Channel.create(
        name="token-ch", provider="openai",
        base_url="https://api.openai.com", api_key="sk-up",
        models=["text-embedding-3-small", "gpt-3.5-turbo"],
        is_enabled=True, timeout=60,
    )
    raw_key = "sk-tokenarrays"
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
        name="token-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
    )
    seen = []

    async def send_request(body, endpoint):
        seen.append((endpoint, body.get("input"), body.get("prompt")))
        if endpoint == "/v1/embeddings":
            return {
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1]}],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            }
        return MOCK_COMPLETION_RESPONSE

    provider = AsyncMock()
    provider.send_request = AsyncMock(side_effect=send_request)
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()
    with patch("app.services.routing.resolve_with_fallbacks", return_value=[(ch, lambda _: provider)]):
        embedded = await client.post(
            "/v1/embeddings",
            json={"model": "text-embedding-3-small", "input": [[11, 22], [33]]},
            headers=auth_header(raw_key),
        )
        completed = await client.post(
            "/v1/completions",
            json={"model": "gpt-3.5-turbo", "prompt": [5, 6, 7]},
            headers=auth_header(raw_key),
        )
    assert embedded.status_code == 200
    assert completed.status_code == 200
    assert seen[0][1] == [[11, 22], [33]]
    assert seen[1][2] == [5, 6, 7]


async def test_unknown_anthropic_beta_is_forwarded(client):
    await ModelPrice.create(model="claude-sonnet")
    await Channel.create(
        name="beta-ch",
        provider="anthropic",
        base_url="https://upstream.anthropic.test",
        api_key="sk-ant",
        models=["claude-sonnet"],
    )
    raw = "sk-beta-forward"
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
        name="beta-key",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("-1"),
    )
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(return_value=_Upstream({
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={
                **auth_header(raw),
                "anthropic-beta": "claude-code-20250219, interleaved-thinking-2025-05-14",
            },
        )
    assert resp.status_code == 200
    sent = http.post.await_args.kwargs["headers"]["anthropic-beta"]
    assert sent == "claude-code-20250219, interleaved-thinking-2025-05-14"


async def test_stream_forwards_upstream_4xx_json(client):
    ch, _, raw_key = await _setup_proxy_env()
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        400,
        json={"error": {"message": "max_tokens is too large", "type": "invalid_request_error", "code": "invalid_request_error"}},
        request=request,
    )

    async def send_stream(_body, _endpoint):
        raise httpx.HTTPStatusError("400", request=request, response=response)
        yield ""

    provider = AsyncMock()
    provider.send_stream = send_stream
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()
    with patch("app.services.routing.resolve_with_fallbacks", return_value=[(ch, lambda _: provider)]):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw_key),
        )
    assert resp.status_code == 400
    assert "max_tokens is too large" in resp.text
    assert "Upstream error" not in resp.text


def _http_response(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://upstream.test/v1/x")
    return httpx.Response(status, json=payload, headers=headers or {}, request=request)


async def test_openai_forwards_only_sent_fields_and_rate_limit_headers(client):
    await _setup_proxy_env()
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(return_value=_http_response(200, MOCK_COMPLETION_RESPONSE, {
        "x-ratelimit-remaining-requests": "99",
        "x-request-id": "req_upstream",
        "set-cookie": "secret=1",
    }))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header("sk-proxytest123456"),
        )
    assert resp.status_code == 200
    sent = http.post.await_args.kwargs["json"]
    assert set(sent) == {"model", "messages"}
    assert resp.headers["x-ratelimit-remaining-requests"] == "99"
    assert resp.headers["x-upstream-request-id"] == "req_upstream"
    assert resp.headers["x-request-id"] != "req_upstream"
    assert "set-cookie" not in resp.headers


async def _anthropic_env(base_url: str = "https://upstream.anthropic.test") -> str:
    await ModelPrice.create(model="claude-sonnet")
    await Channel.create(
        name="ant-ch", provider="anthropic", base_url=base_url,
        api_key="sk-ant", models=["claude-sonnet"],
    )
    raw = "sk-anthropic-env"
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
        name="ant-key", key_hash=hash_api_key(raw), key_prefix=raw[:8],
        quota_total=Decimal("-1"),
    )
    return raw


async def test_anthropic_stream_passes_rate_limit_headers(client):
    raw = await _anthropic_env()
    sse = (
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":3}}}\n\n'
        'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":2}}\n\n'
        'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )
    upstream = httpx.Response(
        200, content=sse.encode(),
        headers={"anthropic-ratelimit-tokens-remaining": "5000", "request-id": "req_ant"},
        request=httpx.Request("POST", "https://upstream.anthropic.test/v1/messages"),
    )
    http = AsyncMock()
    http.is_closed = False
    http.build_request = lambda *args, **kwargs: None
    http.send = AsyncMock(return_value=upstream)
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet", "max_tokens": 16, "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=auth_header(raw),
        )
    assert resp.status_code == 200
    assert "message_stop" in resp.text
    assert resp.headers["anthropic-ratelimit-tokens-remaining"] == "5000"
    assert resp.headers["request-id"] == "req_ant"


async def test_count_tokens_forwards_to_anthropic_channel(client):
    raw = await _anthropic_env("https://upstream.anthropic.test/v1")
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(return_value=_http_response(200, {"input_tokens": 42}))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/messages/count_tokens",
            json={"model": "claude-sonnet", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw),
        )
    assert resp.status_code == 200
    assert resp.json() == {"input_tokens": 42}
    assert http.post.await_args.args[0] == "/messages/count_tokens"
    assert await RequestLog.all().count() == 0


async def test_count_tokens_estimates_when_upstream_lacks_it(client):
    raw = await _anthropic_env()
    http = AsyncMock()
    http.is_closed = False
    missing = _http_response(404, {"error": "not found"})
    http.post = AsyncMock(return_value=missing)
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/messages/count_tokens",
            json={"model": "claude-sonnet", "messages": [{"role": "user", "content": "你好"}]},
            headers=auth_header(raw),
        )
    assert resp.status_code == 200
    assert resp.json()["input_tokens"] >= 2


async def test_embeddings_non_stream(client):
    await ModelPrice.create(model="text-embedding-3-small")
    ch = await Channel.create(
        name="embed-ch", provider="openai",
        base_url="https://api.openai.com", api_key="sk-up",
        models=["text-embedding-3-small"], is_enabled=True, timeout=60,
    )
    raw_key = "sk-embed123456"
    api_key = await APIKey.create(tenant_id=(await create_test_tenant()).id,
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

    with patch("app.services.routing.resolve_with_fallbacks", return_value=[(ch, mock_provider_cls)]):
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
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
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
    await APIKey.create(tenant_id=(await create_test_tenant()).id,
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
        "app.services.routing.resolve_with_fallbacks",
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


async def test_stream_cleanup_survives_client_disconnect(client):
    ch, api_key, _ = await _setup_proxy_env()
    stalled = anyio.Event()

    async def stream_fn(_provider, _channel):
        yield 'data: {"choices":[{"delta":{"content":"hello world"}}]}\n\n', {}
        await stalled.wait()

    provider = AsyncMock()
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()
    events = stream_with_failover(
        [(ch, lambda _: provider)], stream_fn, api_key, "/v1/chat/completions", "gpt-4o",
        "req-disconnect", time.monotonic(), "127.0.0.1", lambda _e: "", "lease-1",
    )
    with patch("app.services.proxy.concurrency_limiter.release", new=AsyncMock()) as release:
        # Starlette cancels the response task while the stream awaits upstream.
        with anyio.CancelScope() as scope:
            async for _ in events:
                scope.cancel()

    release.assert_awaited_once()
    provider.close.assert_awaited()
    log = await RequestLog.get(request_id="req-disconnect")
    assert log.completion_tokens > 0
    assert log.cost > 0


def _relay_http(response: httpx.Response) -> AsyncMock:
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(return_value=response)
    return http


async def test_error_body_in_200_keeps_client_error_status(client):
    await _setup_proxy_env()
    error = {"error": {"message": "Invalid value: 'image_url'", "type": "invalid_request_error"}}
    http = _relay_http(_http_response(200, error))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header("sk-proxytest123456"),
        )
    assert resp.status_code == 400
    assert resp.json() == error
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.status_code == 400
    assert log.upstream_status_code == 200


async def test_error_body_in_200_fails_over(client):
    ch, _, _ = await _setup_proxy_env()
    ch.priority = 10
    await ch.save()
    backup = await Channel.create(
        name="backup", provider="openai", base_url="https://backup.test",
        api_key="sk-b", models=["gpt-4o"], is_enabled=True, timeout=60,
    )
    relay = _relay_http(_http_response(200, {"error": {"message": "No available channel", "type": "new_api_error"}}))
    good = _relay_http(_http_response(200, MOCK_COMPLETION_RESPONSE))
    with patch("app.providers.base._shared_http_client", side_effect=lambda c: good if c.id == backup.id else relay):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header("sk-proxytest123456"),
        )
    assert resp.status_code == 200
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.failed_over is True
    assert log.channel_id == backup.id


async def test_stream_answered_with_json_error_is_an_error(client):
    await _setup_proxy_env()
    error = {"error": {"message": "bad key", "type": "authentication_error"}}
    stream = _http_response(200, error)
    http = AsyncMock()
    http.is_closed = False
    http.build_request = lambda *args, **kwargs: None
    http.send = AsyncMock(return_value=stream)
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header("sk-proxytest123456"),
        )
    assert "bad key" in resp.text
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.status_code == 401
