"""基础网关行为：过期 Key、IP 白名单、RPM。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models import APIKey, Channel
from app.services.auth import hash_api_key
from tests.conftest import auth_header

pytestmark = [pytest.mark.asyncio, pytest.mark.regression]


async def _channel() -> Channel:
    return await Channel.create(
        name="basic-openai",
        provider="openai",
        base_url="https://upstream.openai.test/v1",
        api_key="sk-up",
        models=["gpt-4o"],
    )


async def test_expired_key_is_rejected(client):
    await _channel()
    raw = "sk-expired-basic"
    await APIKey.create(
        name="expired",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("-1"),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw),
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"]["code"] == "key_expired"


async def test_ip_whitelist_rejects_other_clients(client):
    await _channel()
    raw = "sk-ip-basic"
    await APIKey.create(
        name="ip-locked",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("-1"),
        allowed_ips=["10.1.1.1"],
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(raw),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"]["code"] == "ip_not_allowed"


async def test_rpm_limit_rejects_the_extra_request(client, mock_redis):
    await _channel()
    raw = "sk-rpm-basic"
    await APIKey.create(
        name="rpm",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("-1"),
        rpm_limit=1,
    )
    counts: dict[str, int] = {}

    async def eval_script(script, _numkeys, key, limit, *_rest):
        if "INCR" not in script:
            return 1
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > int(limit):
            counts[key] -= 1
            return 0
        return 1

    mock_redis.eval = eval_script
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(return_value=type("Resp", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    })())
    body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    with patch("app.providers.base._shared_http_client", return_value=http):
        first = await client.post("/v1/chat/completions", json=body, headers=auth_header(raw))
        second = await client.post("/v1/chat/completions", json=body, headers=auth_header(raw))
    assert first.status_code == 429 or second.status_code == 429
    blocked = second if second.status_code == 429 else first
    assert blocked.json()["detail"]["error"]["code"] == "rpm_limit"
