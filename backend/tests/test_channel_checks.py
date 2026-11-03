"""Connection checks must distinguish discovery, native generation and complete streams."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.models import Channel, RequestLog, Settlement
from app.services import channel_checks, channel_health
from tests.conftest import auth_header, create_tenant_account


CHAT = {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
RESPONSE = {"status": "completed", "output": [{"type": "message", "content": [
    {"type": "output_text", "text": "OK"},
]}]}
CHAT_STREAM = 'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'
RESPONSES_STREAM = (
    'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"OK"}\n\n'
    'event: response.completed\ndata: ' + json.dumps({"type": "response.completed", "response": RESPONSE}) + '\n\n'
)
MESSAGES = {"type": "message", "content": [{"type": "text", "text": "OK"}]}
MESSAGES_STREAM = (
    'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"OK"}}\n\n'
    'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


def stream(text):
    return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})


@respx.mock
async def test_chat_works_while_responses_fails_without_changing_health(client, admin_token):
    channel = await Channel.create(name="chat-only", provider="openai", base_url="https://checks.test/v1",
                                   api_key="vendor-secret", models=["public-model"],
                                   model_mapping={"public-model": "gpt-6-mini"})
    respx.get("https://checks.test/v1/models").respond(200, json={"data": [{"id": "gpt-6-mini"}]})
    chat = respx.post("https://checks.test/v1/chat/completions").mock(side_effect=lambda request:
        stream(CHAT_STREAM) if json.loads(request.content)["stream"] else httpx.Response(200, json=CHAT))
    responses = respx.post("https://checks.test/v1/responses").respond(
        404, json={"error": {"message": "Responses endpoint is not available"}})
    for _ in range(3):
        await channel_health.record_failure(channel.id)
    before = await channel_health.get_health_status([channel.id])

    result = await client.post(f"/api/channels/{channel.id}/test", json={"model": "public-model"},
                               headers=auth_header(admin_token))
    assert result.status_code == 200
    data = result.json()
    assert data["success"] is False
    assert data["actual_model"] == "gpt-6-mini"
    checks = {item["kind"]: item for item in data["checks"]}
    assert [checks[k]["status"] for k in channel_checks.OPENAI_CHECKS] == [
        "passed", "passed", "passed", "failed", "failed",
    ]
    assert checks["responses"]["status_code"] == 404
    assert checks["responses"]["error"] == "Responses endpoint is not available"
    assert checks["chat_stream"]["first_text_ms"] is not None
    for call in (*chat.calls, *responses.calls):
        payload = json.loads(call.request.content)
        assert payload["model"] == "gpt-6-mini"
        assert call.request.headers["authorization"] == "Bearer vendor-secret"
        if "chat/completions" in str(call.request.url):
            assert payload["max_completion_tokens"] == 256
    assert await channel_health.get_health_status([channel.id]) == before
    assert await RequestLog.all().count() == await Settlement.all().count() == 0


@respx.mock
async def test_all_endpoints_pass_and_default_model_remains_supported(client, admin_token, channel):
    respx.get("https://api.openai.com/v1/models").respond(200, json={"data": []})
    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=lambda request:
        stream(CHAT_STREAM) if json.loads(request.content)["stream"] else httpx.Response(200, json=CHAT))
    respx.post("https://api.openai.com/v1/responses").mock(side_effect=lambda request:
        stream(RESPONSES_STREAM) if json.loads(request.content)["stream"] else httpx.Response(200, json=RESPONSE))
    result = await client.post(f"/api/channels/{channel.id}/test", headers=auth_header(admin_token))
    assert result.status_code == 200
    assert result.json()["success"] is True
    assert result.json()["model"] == "gpt-4o"
    assert all(check["status"] == "passed" for check in result.json()["checks"])


@respx.mock
async def test_anthropic_checks_native_messages_even_when_discovery_is_unavailable(client, admin_token):
    channel = await Channel.create(name="native", provider="anthropic", base_url="https://native.test/v1",
                                   api_key="anthropic-secret", models=["alias"], model_mapping={"alias": "claude-real"})
    respx.get("https://native.test/v1/models").respond(404)
    messages = respx.post("https://native.test/v1/messages").mock(side_effect=lambda request:
        stream(MESSAGES_STREAM) if json.loads(request.content)["stream"] else httpx.Response(200, json=MESSAGES))
    result = await client.post(f"/api/channels/{channel.id}/test", json={"model": "alias"},
                               headers=auth_header(admin_token))
    checks = {item["kind"]: item for item in result.json()["checks"]}
    assert set(checks) == set(channel_checks.ANTHROPIC_CHECKS)
    assert checks["models"]["status"] == "failed"
    assert checks["messages"]["status"] == checks["messages_stream"]["status"] == "passed"
    for call in messages.calls:
        assert call.request.headers["x-api-key"] == "anthropic-secret"
        assert json.loads(call.request.content)["model"] == "claude-real"


@pytest.mark.parametrize(("kind", "response", "error"), [
    ("models", httpx.Response(200, text="<html>Login required</html>"), "non-JSON"),
    ("models", httpx.Response(200, json={"data": "not a list"}), "model list"),
    ("chat", httpx.Response(200, json={"choices": []}), "no generated text"),
    ("chat", httpx.Response(200, json={"error": {"message": "busy"}}), "busy"),
    ("responses", httpx.Response(200, json={**RESPONSE, "status": "incomplete"}), "did not complete"),
    ("responses", httpx.Response(200, json={"status": "completed", "output": None}), "no generated text"),
    ("chat_stream", httpx.Response(200, json=CHAT), "text/event-stream"),
    ("chat_stream", stream('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'), "terminal event"),
    ("chat_stream", stream('data: [DONE]\n\n'), "without generated text"),
    ("chat_stream", stream('data: {"error":{"message":"overloaded"}}\n\n'), "overloaded"),
    ("chat_stream", stream('data: not-json\n\n'), "invalid JSON"),
    ("responses_stream", stream('data: {"type":"response.failed","response":{"error":{"message":"capacity"}}}\n\n'), "capacity"),
    ("responses_stream", stream('data: {"type":"response.completed"}\n\n'), "response object"),
    ("messages_stream", stream('data: {"type":"message_stop"}\n\n'), "without generated text"),
])
async def test_http_200_is_not_enough(kind, response, error):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response), base_url="https://checks.test") as http:
        provider = SimpleNamespace(
            channel=SimpleNamespace(provider="openai", timeout=1), client=http,
            prepare_request=lambda *args: ("/check", {}, {}),
            apply_model_mapping=lambda model: model,
        )
        if kind == "models":
            provider.channel.base_url = "https://checks.test"
            provider._auth_headers = lambda: {}
        result = await channel_checks._check(provider, "model", kind)
    assert result.status == "failed"
    assert result.status_code == 200
    assert error in result.error
    assert response.is_closed


class Heartbeats(httpx.AsyncByteStream):
    closed = False

    async def __aiter__(self):
        while True:
            yield b": ping\n\n"
            await asyncio.sleep(0.005)

    async def aclose(self):
        self.closed = True


async def test_heartbeats_cannot_keep_a_check_alive_forever():
    heartbeats = Heartbeats()
    response = httpx.Response(200, stream=heartbeats, headers={"content-type": "text/event-stream"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response), base_url="https://checks.test") as http:
        provider = SimpleNamespace(channel=SimpleNamespace(provider="openai", timeout=1), client=http,
                                   prepare_request=lambda *args: ("/check", {}, {}),
                                   apply_model_mapping=lambda model: model)
        with patch.object(channel_checks, "CHECK_TIMEOUT_SECONDS", 0.02):
            result = await channel_checks._check(provider, "model", "chat_stream")
    assert result.status == "timeout"
    assert result.status_code == 200
    assert heartbeats.closed


async def test_multiline_sse_data_and_heartbeats_are_accepted():
    response = stream(': ping\n\ndata: {"choices":\ndata: [{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response), base_url="https://checks.test") as http:
        provider = SimpleNamespace(channel=SimpleNamespace(provider="openai", timeout=1), client=http,
                                   prepare_request=lambda *args: ("/check", {}, {}),
                                   apply_model_mapping=lambda model: model)
        result = await channel_checks._check(provider, "model", "chat_stream")
    assert result.status == "passed"
    assert result.first_text_ms is not None


@respx.mock
async def test_upstream_error_credentials_are_redacted(channel):
    respx.route().respond(401, json={"error": {"message": "Bad credential: sk-upstream-key"}})
    checks = await channel_checks.run_channel_checks(channel, "gpt-4o")
    assert all(check.status == "failed" for check in checks)
    assert "sk-upstream-key" not in json.dumps([check.model_dump() for check in checks])
    assert "[REDACTED]" in checks[0].error


@respx.mock
async def test_all_cooling_keys_do_not_get_used(channel):
    channel.api_key = "first-key\nsecond-key"
    with patch("app.providers.base.available_keys", AsyncMock(return_value=[])):
        checks = await channel_checks.run_channel_checks(channel, "gpt-4o")
    assert not respx.calls
    assert all(check.status == "failed" and "cooling down" in check.error for check in checks)


async def test_channel_checks_are_admin_only_and_validate_the_selected_model(client, admin_token, channel):
    path = f"/api/channels/{channel.id}/test"
    assert (await client.post(path)).status_code == 401
    _, _, tenant_headers = await create_tenant_account()
    assert (await client.post(path, headers=tenant_headers)).status_code == 403
    headers = auth_header(admin_token)
    assert (await client.post(path, json={"model": "not-configured"}, headers=headers)).status_code == 422
    assert (await client.post(path, json={"model": "gpt-4o", "unknown": 1}, headers=headers)).status_code == 422
    assert (await client.post("/api/channels/999999/test", headers=headers)).status_code == 404
    await Channel.filter(id=channel.id).update(models=["text-embedding-3-small"])
    assert (await client.post(path, headers=headers)).status_code == 422


async def test_checks_share_probe_rate_limit(client, admin_token, channel):
    headers = auth_header(admin_token)
    with patch("app.routers.channels.run_channel_checks", AsyncMock(return_value=[
        channel_checks.ChannelCheckResult(kind="models", status="passed", status_code=200),
    ])):
        for _ in range(6):
            assert (await client.post(f"/api/channels/{channel.id}/test", headers=headers)).status_code == 200
        rejected = await client.post(f"/api/channels/{channel.id}/test", headers=headers)
    assert rejected.status_code == 429
    assert rejected.headers["retry-after"] == "60"
