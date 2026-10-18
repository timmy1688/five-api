from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel, ModelPrice, RequestLog
from app.services.auth import hash_api_key
from app.services.pricing import cost_breakdown
from app.services.sticky_session import session_identity
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio

RAW_KEY = "sk-insight-client"


def _http(payload):
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(side_effect=lambda *a, **k: httpx.Response(
        200, json=payload, request=httpx.Request("POST", "https://api.anthropic.test/v1/messages"),
    ))
    return http


def test_session_identity_sources():
    assert session_identity({"x-session-id": " abc "}, {}) == "abc"
    body = {"metadata": {"user_id": "user_x_account_y_session_1234-uuid"}}
    assert session_identity({}, body) == "1234-uuid"
    convo = {"messages": [{"role": "user", "content": "first"}]}
    later = {"messages": [{"role": "user", "content": "first"}, {"role": "assistant", "content": "a"}]}
    assert session_identity({}, convo) == session_identity({}, later)


async def test_cost_breakdown_lines_and_savings():
    await ModelPrice.create(
        model="claude-x", prompt_price=Decimal("3"), completion_price=Decimal("15"),
        cached_price=Decimal("0.3"), cache_write_price=Decimal("3.75"),
    )
    out = await cost_breakdown("claude-x", 1_000_000, 100_000, cached_tokens=600_000, cache_write_tokens=100_000)
    detail = out["detail"]
    assert detail["price_source"] == "global"
    assert detail["tokens"]["input"] == 300_000
    assert detail["lines"] == {"input": 0.9, "cache_read": 0.18, "cache_write": 0.375, "output": 1.5}
    assert out["cost"] == Decimal("2.955")
    assert out["cache_savings"] == Decimal("1.545")


async def test_session_and_cache_stats(client, admin_token):
    await Channel.create(
        name="a", provider="anthropic", base_url="https://api.anthropic.test",
        api_key="sk-up", models=["claude-x"], timeout=60,
    )
    await ModelPrice.create(
        model="claude-x", prompt_price=Decimal("3"), completion_price=Decimal("15"),
        cached_price=Decimal("0.3"), cache_write_price=Decimal("3.75"),
    )
    await APIKey.create(
        name="cc", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8], quota_total=Decimal("-1"),
    )
    reply = {
        "id": "msg", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 10},
    }
    body = {
        "model": "claude-x", "max_tokens": 50,
        "metadata": {"user_id": "user_a_account_b_session_s1"},
        "messages": [{"role": "user", "content": "hi"}],
    }
    with patch("app.providers.base._shared_http_client", return_value=_http(reply)):
        for _ in range(2):
            resp = await client.post("/v1/messages", json=body, headers={"x-api-key": RAW_KEY})
            assert resp.status_code == 200

    log = await RequestLog.first()
    assert log.session_id and log.cost_detail["tokens"]["cache_read"] == 900
    assert log.cache_savings == Decimal("0.00243")

    sessions = (await client.get("/api/stats/sessions", headers=auth_header(admin_token))).json()
    assert sessions["total"] == 1
    row = sessions["items"][0]
    assert row["requests"] == 2 and row["hit_rate"] == 0.9 and row["api_key_name"] == "cc"

    detail = await client.get(f"/api/stats/sessions/{row['session_id']}", headers=auth_header(admin_token))
    assert len(detail.json()["items"]) == 2

    cache = (await client.get("/api/stats/cache", headers=auth_header(admin_token))).json()
    assert cache["total"]["cached_tokens"] == 1800
    assert cache["total"]["hit_rate"] == 0.9
    assert cache["by_model"][0]["model"] == "claude-x"
    assert cache["total"]["cache_savings"] == pytest.approx(0.00486)


def test_auto_cache_marks_tools_system_and_last_message():
    from app.services.auto_cache import with_cache_control

    body = {
        "system": "You are helpful",
        "tools": [{"name": "a"}, {"name": "b"}],
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "x"}, {"type": "thinking", "thinking": "t"}]},
        ],
    }
    out, changed = with_cache_control(body)
    assert changed
    assert "cache_control" not in body["tools"][-1]
    assert out["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert out["system"][0]["cache_control"] == {"type": "ephemeral"}
    last = out["messages"][-1]["content"]
    assert "cache_control" in last[0] and "cache_control" not in last[1]

    managed = {"system": [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}], "messages": []}
    assert with_cache_control(managed) == (managed, False)


async def test_auto_cache_applies_when_enabled(client, admin_token):
    from app.services.settings_service import clear_settings_cache, set_gateway_config

    await Channel.create(
        name="a", provider="anthropic", base_url="https://api.anthropic.test",
        api_key="sk-up", models=["claude-x"], timeout=60,
    )
    await APIKey.create(
        name="cc", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8], quota_total=Decimal("-1"),
    )
    await set_gateway_config({"auto_cache_control": True})
    reply = {"id": "m", "type": "message", "role": "assistant", "content": [], "usage": {"input_tokens": 1, "output_tokens": 1}}
    http = _http(reply)
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/messages",
            json={"model": "claude-x", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": RAW_KEY},
        )
    clear_settings_cache()
    assert resp.status_code == 200
    sent = http.post.await_args.kwargs["json"]
    assert sent["messages"][-1]["content"][0]["cache_control"] == {"type": "ephemeral"}
