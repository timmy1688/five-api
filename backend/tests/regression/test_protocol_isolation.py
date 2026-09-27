"""回归：请求只走同协议渠道，跨协议渠道不能成为故障转移。"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel, RequestLog
from app.providers.registry import resolve_candidates
from app.services.auth import hash_api_key
from tests.conftest import auth_header

pytestmark = [pytest.mark.asyncio, pytest.mark.regression]


class _Upstream:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


async def _key(raw: str) -> str:
    await APIKey.create(
        name=raw,
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("-1"),
    )
    return raw


async def test_candidates_stay_inside_one_protocol():
    await Channel.create(
        name="openai-shared",
        provider="openai",
        base_url="https://openai.test/v1",
        api_key="sk-up",
        models=["shared-model"],
        priority=1,
    )
    await Channel.create(
        name="anthropic-shared",
        provider="anthropic",
        base_url="https://anthropic.test",
        api_key="sk-ant",
        models=["shared-model"],
        priority=100,
    )

    openai = await resolve_candidates("shared-model", preferred_protocol="openai")
    anthropic = await resolve_candidates("shared-model", preferred_protocol="anthropic")
    assert [channel.provider for channel, _ in openai] == ["openai"]
    assert [channel.provider for channel, _ in anthropic] == ["anthropic"]


async def test_chat_does_not_fall_back_to_anthropic_channel(client):
    await Channel.create(
        name="only-anthropic",
        provider="anthropic",
        base_url="https://anthropic.test",
        api_key="sk-ant",
        models=["claude-only"],
        priority=100,
    )
    raw = await _key("sk-regression-chat")
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock()
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "claude-only", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw),
        )
    assert resp.status_code == 404
    http.post.assert_not_awaited()


async def test_messages_does_not_fall_back_to_openai_channel(client):
    await Channel.create(
        name="only-openai",
        provider="openai",
        base_url="https://openai.test/v1",
        api_key="sk-up",
        models=["gpt-only"],
        priority=100,
    )
    raw = await _key("sk-regression-messages")
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock()
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/messages",
            json={"model": "gpt-only", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw),
        )
    assert resp.status_code == 404
    http.post.assert_not_awaited()


async def test_failover_stays_on_openai_channels(client):
    primary = await Channel.create(
        name="openai-primary",
        provider="openai",
        base_url="https://primary.test/v1",
        api_key="sk-up",
        models=["gpt-4o"],
        priority=10,
        max_retries=0,
    )
    backup = await Channel.create(
        name="openai-backup",
        provider="openai",
        base_url="https://backup.test/v1",
        api_key="sk-up",
        models=["gpt-4o"],
        priority=1,
        max_retries=0,
    )
    await Channel.create(
        name="anthropic-higher",
        provider="anthropic",
        base_url="https://anthropic.test",
        api_key="sk-ant",
        models=["gpt-4o"],
        priority=50,
        max_retries=0,
    )
    raw = await _key("sk-regression-failover")
    calls = []

    async def post(path, json=None, headers=None):
        calls.append(path)
        if len(calls) == 1:
            raise httpx.ConnectError("primary down")
        return _Upstream({
            "choices": [{"message": {"role": "assistant", "content": "backup"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        })

    http = AsyncMock()
    http.is_closed = False
    http.post = post
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw),
        )

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "backup"
    assert calls == ["chat/completions", "chat/completions"]
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.failed_over is True
    assert log.channel_id == backup.id
    assert log.channel_id != primary.id
