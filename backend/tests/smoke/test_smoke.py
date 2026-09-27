"""发布前冒烟：登录、两条透传管道、鉴权失败和配额拒绝。"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models import APIKey, Channel, ModelPrice
from app.services.auth import hash_api_key
from tests.conftest import auth_header, create_admin

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]


class _Upstream:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _http(payload: dict) -> AsyncMock:
    client = AsyncMock()
    client.is_closed = False
    client.post = AsyncMock(return_value=_Upstream(payload))
    return client


async def _key(raw: str) -> str:
    await APIKey.create(
        name=raw,
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("-1"),
    )
    return raw


async def test_admin_can_log_in(client):
    await create_admin("smoke-admin", "smoke-pass")
    resp = await client.post(
        "/api/login",
        json={"username": "smoke-admin", "password": "smoke-pass"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_openai_chat_is_passthrough(client):
    await Channel.create(
        name="smoke-openai",
        provider="openai",
        base_url="https://upstream.openai.test/v1",
        api_key="sk-up",
        models=["gpt-4o"],
    )
    await ModelPrice.create(
        model="gpt-4o",
        prompt_price=Decimal("1"),
        completion_price=Decimal("2"),
    )
    raw = await _key("sk-smoke-openai")
    http = _http({
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    })
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hello"}],
        "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
    }
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post("/v1/chat/completions", json=body, headers=auth_header(raw))

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "ok"
    sent = http.post.await_args.kwargs["json"]
    assert sent["messages"] == body["messages"]
    assert sent["tools"] == body["tools"]
    assert http.post.await_args.args[0] == "chat/completions"


async def test_anthropic_messages_is_passthrough(client):
    await Channel.create(
        name="smoke-anthropic",
        provider="anthropic",
        base_url="https://upstream.anthropic.test",
        api_key="sk-ant",
        models=["claude-sonnet"],
    )
    await ModelPrice.create(
        model="claude-sonnet",
        prompt_price=Decimal("1"),
        completion_price=Decimal("2"),
    )
    raw = await _key("sk-smoke-anthropic")
    http = _http({
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 4, "output_tokens": 1},
    })
    body = {
        "model": "claude-sonnet",
        "max_tokens": 32,
        "messages": [{"role": "user", "content": "hello"}],
        "thinking": {"type": "enabled", "budget_tokens": 100},
    }
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/messages",
            json=body,
            headers={
                **auth_header(raw),
                "anthropic-beta": "interleaved-thinking-2025-05-14",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["content"][0]["text"] == "ok"
    sent = http.post.await_args.kwargs["json"]
    assert sent["thinking"] == body["thinking"]
    assert sent["messages"] == body["messages"]
    assert http.post.await_args.args[0] == "/v1/messages"
    assert "interleaved-thinking-2025-05-14" in http.post.await_args.kwargs["headers"]["anthropic-beta"]


async def test_invalid_key_is_rejected(client):
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header("sk-missing"),
    )
    assert resp.status_code == 401


async def test_quota_exceeded_does_not_call_upstream(client):
    await Channel.create(
        name="smoke-quota",
        provider="openai",
        base_url="https://upstream.openai.test/v1",
        api_key="sk-up",
        models=["gpt-4o"],
    )
    raw = "sk-smoke-quota"
    await APIKey.create(
        name="smoke-quota",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("1"),
        quota_used=Decimal("1"),
    )
    http = _http({})
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw),
        )
    assert resp.status_code == 429
    http.post.assert_not_awaited()
