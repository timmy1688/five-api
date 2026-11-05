"""Server-side tools such as web search must pass through untouched, and their use must stay visible.

The gateway bills tokens only. Searches the upstream ran are recorded in cost_detail as unpriced,
so an operator can see how much usage is not charged to customers.
"""
import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel, ModelPrice, RequestLog
from app.routers.anthropic_proxy import _extract_anthropic_usage
from app.services.auth import hash_api_key
from tests.conftest import auth_header, create_test_tenant
from tests.test_gateway_v03 import _http, _json, _sse

pytestmark = pytest.mark.asyncio

MODEL = "claude-search"
RAW = "sk-server-tools-key"
SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 2}
SEARCH_BLOCKS = [
    {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "fastapi release"}},
    {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
        {"type": "web_search_result", "title": "fastapi", "url": "https://example.test/fastapi",
         "encrypted_content": "opaque-blob=="},
    ]},
    {"type": "text", "text": "The latest release is 1.2.3."},
]
# 500 input + 40 output tokens at 10 / 50 per million.
TOKEN_COST = ((Decimal(500) * 10 + Decimal(40) * 50) / Decimal(1_000_000)).quantize(Decimal("0.000001"))


async def anthropic_env():
    await Channel.create(name="search-channel", provider="anthropic", base_url="https://upstream.anthropic.test",
                         api_key="sk-ant", models=[MODEL])
    await ModelPrice.create(model=MODEL, prompt_price=Decimal("10"), completion_price=Decimal("50"))
    return await APIKey.create(tenant_id=(await create_test_tenant()).id, name="search-key",
                               key_hash=hash_api_key(RAW), key_prefix=RAW[:8], quota_total=Decimal("100"))


def message(searches: int | None):
    usage = {"input_tokens": 500, "output_tokens": 40}
    if searches is not None:
        usage["server_tool_use"] = {"web_search_requests": searches}
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": MODEL, "content": SEARCH_BLOCKS,
            "stop_reason": "end_turn", "usage": usage}


def request_body(**extra):
    return {"model": MODEL, "max_tokens": 64, "tools": [SEARCH_TOOL],
            "messages": [{"role": "user", "content": "Search the web for the latest FastAPI release"}], **extra}


async def test_search_tool_and_result_blocks_pass_through_unchanged(client):
    key = await anthropic_env()
    http = _http(response=_json(message(2)))
    with patch("app.providers.base._shared_http_client", return_value=http):
        response = await client.post("/v1/messages", json=request_body(), headers=auth_header(RAW))
    assert response.status_code == 200
    assert response.json()["content"] == SEARCH_BLOCKS
    assert response.json()["usage"]["server_tool_use"] == {"web_search_requests": 2}
    sent = http.post.await_args.kwargs["json"]
    assert sent["tools"] == [SEARCH_TOOL]
    assert key.id


async def test_searches_are_recorded_as_unpriced_and_tokens_are_still_billed(client):
    key = await anthropic_env()
    with patch("app.providers.base._shared_http_client", return_value=_http(response=_json(message(3)))):
        response = await client.post("/v1/messages", json=request_body(), headers=auth_header(RAW))
    assert response.status_code == 200
    log = await RequestLog.get(api_key_id=key.id)
    assert log.cost == TOKEN_COST
    assert log.cost_detail["unpriced_server_tools"] == {"web_search_requests": 3}
    await key.refresh_from_db()
    assert key.quota_used == TOKEN_COST


async def test_requests_without_searches_leave_no_server_tool_field(client):
    key = await anthropic_env()
    for searches in (None, 0):
        await RequestLog.all().delete()
        with patch("app.providers.base._shared_http_client", return_value=_http(response=_json(message(searches)))):
            response = await client.post("/v1/messages", json=request_body(), headers=auth_header(RAW))
        assert response.status_code == 200
        log = await RequestLog.get(api_key_id=key.id)
        assert log.cost == TOKEN_COST
        assert "unpriced_server_tools" not in log.cost_detail


async def test_streamed_searches_are_recorded_from_the_final_usage_event(client):
    key = await anthropic_env()
    events = (
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":500}}}\n\n'
        'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":'
        '{"type":"server_tool_use","id":"srvtoolu_1","name":"web_search","input":{}}}\n\n'
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":'
        '{"type":"text_delta","text":"The latest release is 1.2.3."}}\n\n'
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
        '"usage":{"output_tokens":40,"server_tool_use":{"web_search_requests":2}}}\n\n'
        'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )
    http = _http(stream=_sse(events))
    with patch("app.providers.base._shared_http_client", return_value=http):
        response = await client.post("/v1/messages", json=request_body(stream=True), headers=auth_header(RAW))
    assert response.status_code == 200
    assert "server_tool_use" in response.text and "The latest release is 1.2.3." in response.text
    log = await RequestLog.get(api_key_id=key.id)
    assert log.status_code == 200
    assert log.cost == TOKEN_COST
    assert log.cost_detail["unpriced_server_tools"] == {"web_search_requests": 2}


@pytest.mark.parametrize("server_tool_use", [None, "oops", [], {}, {"web_search_requests": None},
                                              {"web_search_requests": -1}, {"web_search_requests": "3"},
                                              {"web_search_requests": True}, {"web_search_requests": 1.5}])
async def test_malformed_server_tool_usage_is_ignored(server_tool_use):
    usage = _extract_anthropic_usage({"usage": {"input_tokens": 5, "output_tokens": 7,
                                                "server_tool_use": server_tool_use}})
    assert "web_search_requests" not in usage
    assert usage["prompt_tokens"] == 5 and usage["completion_tokens"] == 7


async def test_valid_server_tool_usage_is_extracted():
    usage = _extract_anthropic_usage({"usage": {"input_tokens": 5, "output_tokens": 7,
                                                "server_tool_use": {"web_search_requests": 4}}})
    assert usage["web_search_requests"] == 4


async def test_responses_web_search_tool_is_forwarded_to_the_upstream(client):
    """The OpenAI Responses `web_search` tool is the upstream's to run. Support depends on the upstream."""
    await Channel.create(name="responses-channel", provider="openai", base_url="https://api.openai.test",
                         api_key="sk-up", models=["gpt-search"])
    await ModelPrice.create(model="gpt-search", prompt_price=Decimal("2"), completion_price=Decimal("8"))
    await APIKey.create(tenant_id=(await create_test_tenant()).id, name="responses-key",
                        key_hash=hash_api_key(RAW), key_prefix=RAW[:8], quota_total=Decimal("100"))
    reply = {"id": "resp_1", "object": "response", "status": "completed", "output": [
        {"type": "web_search_call", "id": "ws_1", "status": "completed"},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "1.2.3"}]},
    ], "usage": {"input_tokens": 10, "output_tokens": 5}}
    http = _http(response=_json(reply))
    with patch("app.providers.base._shared_http_client", return_value=http):
        response = await client.post("/v1/responses", headers=auth_header(RAW), json={
            "model": "gpt-search", "input": "latest FastAPI?", "tools": [{"type": "web_search"}]})
    assert response.status_code == 200
    assert [item["type"] for item in response.json()["output"]] == ["web_search_call", "message"]
    sent = json.loads(http.post.await_args.kwargs["content"]) if "content" in http.post.await_args.kwargs \
        else http.post.await_args.kwargs["json"]
    assert sent["tools"] == [{"type": "web_search"}]
