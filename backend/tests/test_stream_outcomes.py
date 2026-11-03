"""Native stream errors must affect logs and health without replaying generated work."""
import asyncio
import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import Channel, ModelPrice, RequestLog, Settlement, UsageDaily
from app.services.channel_health import get_health_status, record_failure
from app.services.proxy import stream_with_failover
from app.services.stream_outcomes import StreamOutcome
from tests.conftest import auth_header
from tests.test_gateway_v03 import RAW_KEY, _env, _http, _sse


CASES = {
    "responses_failed": (
        "/v1/responses", "openai", "Selected model is at capacity", 503,
        'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"Partial"}\n\n'
        'event: response.failed\ndata: {"type":"response.failed","response":{"status":"failed",'
        '"error":{"code":"server_is_overloaded","message":"Selected model is at capacity"},'
        '"usage":{"input_tokens":10,"output_tokens":3}}}\n\n',
    ),
    "chat_error": (
        "/v1/chat/completions", "openai", "Upstream overloaded", 502,
        'data: {"error":{"type":"server_error","message":"Upstream overloaded"}}\n\n',
    ),
    "chat_partial_error": (
        "/v1/chat/completions", "openai", "Upstream overloaded", 502,
        'data: {"choices":[{"delta":{"content":"Partial"}}],"usage":{"prompt_tokens":10,"completion_tokens":3}}\n\n'
        'data: {"error":{"type":"server_error","message":"Upstream overloaded"}}\n\n',
    ),
    "anthropic_error": (
        "/v1/messages", "anthropic", "Overloaded", 529,
        'event: error\ndata: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n\n',
    ),
    "anthropic_partial_error": (
        "/v1/messages", "anthropic", "Overloaded", 529,
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":10}}}\n\n'
        'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":3}}\n\n'
        'event: error\ndata: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n\n',
    ),
    "premature_eof": (
        "/v1/chat/completions", "openai", "Upstream stream ended before a terminal event", 502,
        'data: {"choices":[{"delta":{"content":"Partial answer"}}]}\n\n',
    ),
    "responses_eof": (
        "/v1/responses", "openai", "Upstream stream ended before a terminal event", 502,
        'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"Partial"}\n\n',
    ),
    "anthropic_eof": (
        "/v1/messages", "anthropic", "Upstream stream ended before a terminal event", 502,
        'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Partial"}}\n\n',
    ),
}


def request_body(endpoint):
    if endpoint == "/v1/responses":
        return {"model": "gpt-4o", "input": "Hi", "stream": True, "max_output_tokens": 32}
    return {"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 32}


@pytest.mark.parametrize("case", CASES)
async def test_failed_streams_are_logged_and_do_not_reset_channel_failures(client, mock_redis, case):
    channel, key = await _env()
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=3)
    endpoint, protocol, message, status, events = CASES[case]
    await Channel.filter(id=channel.id).update(provider=protocol)
    await record_failure(channel.id)
    http = _http(stream=_sse(events))
    with patch("app.providers.base._shared_http_client", return_value=http):
        response = await client.post(endpoint, json=request_body(endpoint), headers=auth_header(RAW_KEY))
    assert response.status_code == 200  # The SSE response has already begun.
    assert response.text.count(message) == 1
    log = await RequestLog.get()
    assert log.status_code == status
    assert log.error_origin == "channel"
    assert log.upstream_status_code == 200
    assert message in log.error_message and message in log.upstream_error
    assert (await get_health_status([channel.id]))[channel.id]["fail_count"] == 2
    assert (await UsageDaily.get()).error_count == 1
    assert http.send.await_count == 1
    assert not any(name.startswith("five:sticky:") for name in mock_redis.data)
    settlement = await Settlement.get()
    assert settlement.state == "settled" and settlement.occupied == 0
    await key.refresh_from_db()
    assert key.quota_used == log.cost
    if case in {"responses_failed", "chat_partial_error", "anthropic_partial_error"}:
        assert (log.prompt_tokens, log.completion_tokens) == (10, 3)
        assert log.cost == Decimal("0.000029")
    elif case == "premature_eof":
        assert log.completion_tokens > 0
    if case == "anthropic_eof":
        error = json.loads(response.text.split("event: error\ndata: ", 1)[1].strip())
        assert error["type"] == "error" and error["error"]["code"] == "stream_incomplete"


@pytest.mark.parametrize(("error_type", "status", "expected_failures", "cooling"), [
    ("rate_limit_error", 429, 1, True),
    ("invalid_request_error", 400, 1, False),
    ("authentication_error", 502, 2, False),
])
async def test_native_error_types_follow_existing_health_and_credential_policy(client, error_type, status, expected_failures, cooling):
    channel, _ = await _env()
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=3)
    event = 'data: ' + json.dumps({"error": {"type": error_type, "message": "Failure: sk-up"}}) + '\n\n'
    upstream = _sse(event)
    upstream.headers["retry-after"] = "45"
    await record_failure(channel.id)
    with patch("app.providers.base._shared_http_client", return_value=_http(stream=upstream)):
        response = await client.post("/v1/chat/completions", json=request_body("/v1/chat/completions"),
                                     headers=auth_header(RAW_KEY))
    log = await RequestLog.get()
    assert log.status_code == status
    assert "sk-up" not in response.text and "sk-up" not in log.upstream_error
    health = (await get_health_status([channel.id]))[channel.id]
    assert health["fail_count"] == expected_failures
    assert (health["cooldown_seconds"] > 0) == cooling
    if error_type == "authentication_error":
        assert "Upstream credentials unavailable" in response.text


@pytest.mark.parametrize(("endpoint", "protocol", "events"), [
    ("/v1/chat/completions", "openai", 'data: [DONE]\n\n'),
    ("/v1/responses", "openai", 'event: response.completed\ndata: {"type":"response.completed","response":{"usage":{"input_tokens":10,"output_tokens":3}}}\n\n'),
    ("/v1/responses", "openai", 'event: response.incomplete\ndata: {"type":"response.incomplete","response":{"incomplete_details":{"reason":"max_output_tokens"},"usage":{"input_tokens":10,"output_tokens":3}}}\n\n'),
    ("/v1/messages", "anthropic", 'event: message_stop\ndata: {"type":"message_stop"}\n\n'),
])
async def test_terminal_event_finishes_and_closes_an_upstream_that_keeps_connection_open(client, endpoint, protocol, events):
    class Stalled(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield events.encode()
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    channel, _ = await _env()
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=3)
    await Channel.filter(id=channel.id).update(provider=protocol)
    stalled = Stalled()
    upstream = httpx.Response(200, stream=stalled, headers={"content-type": "text/event-stream"},
                              request=httpx.Request("POST", "https://api.openai.test/v1/x"))
    with patch("app.providers.base._shared_http_client", return_value=_http(stream=upstream)):
        response = await asyncio.wait_for(client.post(endpoint, json=request_body(endpoint),
                                                      headers=auth_header(RAW_KEY)), timeout=2)
    assert response.status_code == 200
    assert response.text.endswith("\n\n")
    assert stalled.closed
    assert (await RequestLog.get()).status_code == 200
    if endpoint == "/v1/responses":
        assert (await RequestLog.get()).cost == Decimal("0.000029")


async def test_empty_eof_keeps_unknown_work_occupied(client):
    channel, _ = await _env()
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=3)
    await Channel.filter(id=channel.id).update(max_retries=0)
    with patch("app.providers.base._shared_http_client", return_value=_http(stream=_sse(""))):
        response = await client.post("/v1/chat/completions", json=request_body("/v1/chat/completions"),
                                     headers=auth_header(RAW_KEY))
    assert response.status_code == 502
    settlement = await Settlement.get()
    assert settlement.state == "uncertain" and settlement.occupied > 0
    assert settlement.payload["status_code"] == 502
    assert await RequestLog.all().count() == 0


async def test_disconnect_immediately_after_native_error_still_logs_failure(client):
    channel, key = await _env()
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=3)
    provider = AsyncMock()
    provider.apply_model_mapping = lambda model: model

    async def stream_fn(*_):
        yield 'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n', {"prompt_tokens": 10, "completion_tokens": 3}
        yield 'data: {"error":{"type":"server_error","message":"stream failed"}}\n\n', {}

    events = stream_with_failover([(channel, lambda _: provider)], stream_fn, key, "/v1/chat/completions",
                                  "gpt-4o", "disconnect-on-error", time.monotonic(), "127.0.0.1", lambda _: "", "")
    assert "Hello" in await anext(events)
    assert "stream failed" in await anext(events)
    await events.aclose()
    log = await RequestLog.get(request_id="disconnect-on-error")
    assert log.status_code == 502 and log.error_origin == "channel"
    assert log.cost == Decimal("0.000029")


@pytest.mark.parametrize(("endpoint", "chunks", "finished", "failed"), [
    ("/v1/chat/completions", ['data: {"choices":[{"index":0,"delta":{"content":"message_stop [DONE] response.failed"}}]}\n\n'], False, False),
    ("/v1/chat/completions", ['data: {"choices":[{"index":0,"finish_reason":"stop"}]}\n\n'], True, False),
    ("/v1/chat/completions", ['data: {"choices":[{"index":0,"finish_reason":"stop"},{"index":1,"delta":{"content":"unfinished"}}]}\n\n'], False, False),
    ("/v1/chat/completions", [': ping\n\n', 'data: {"error":\n', 'data: {"message":"failed"}}\n\n'], False, True),
    ("/v1/messages", ['event: message_stop\n', 'data: {"type":"message_stop"}\n', '\n'], True, False),
    ("/v1/responses", ['data: [DONE]\n\n'], False, False),
    ("/v1/messages", ['data: {"type":"response.completed"}\n\n'], False, False),
])
def test_outcomes_respect_protocols_multiline_data_and_choice_completion(endpoint, chunks, finished, failed):
    outcome = StreamOutcome(endpoint)
    failure = None
    for chunk in chunks:
        failure = outcome.feed(chunk, {}) or failure
    assert outcome.finished == finished
    assert (failure is not None) == failed
