"""Circuit breaker: open at the threshold, alert once, recover on success or probe."""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.models import Channel
from app.services import channel_health as health


@pytest.fixture
def alerts():
    with patch.object(health.alerts, "channel_opened", AsyncMock()) as opened, \
            patch.object(health.alerts, "channel_recovered", AsyncMock()) as recovered:
        yield opened, recovered


async def test_opens_at_threshold_and_alerts_once(alerts):
    opened, _ = alerts
    for _ in range(2):
        await health.record_failure(7)
    assert await health.is_channel_healthy(7)
    for _ in range(3):
        await health.record_failure(7)
    assert not await health.is_channel_healthy(7)
    opened.assert_awaited_once()
    status = (await health.get_health_status([7]))[7]
    assert status["healthy"] is False and status["fail_count"] == 5 and status["disabled_at"]


async def test_success_resets_and_alerts_recovery_only_after_an_outage(alerts):
    _, recovered = alerts
    await health.record_failure(8)
    await health.record_success(8)
    recovered.assert_not_awaited()
    assert (await health.get_health_status([8]))[8]["fail_count"] == 0
    for _ in range(3):
        await health.record_failure(8)
    await health.force_recover(8)
    recovered.assert_awaited_once()
    assert await health.is_channel_healthy(8)


async def test_rate_limit_cooldown_is_separate_from_failures():
    await health.record_rate_limit(9, seconds=0)
    assert not await health.is_channel_healthy(9)
    status = (await health.get_health_status([9]))[9]
    assert status["fail_count"] == 0 and status["cooldown_seconds"] > 0


async def test_alert_errors_do_not_break_request_accounting():
    with patch.object(health.alerts, "channel_opened", AsyncMock(side_effect=RuntimeError("webhook down"))):
        for _ in range(3):
            await health.record_failure(10)
    assert not await health.is_channel_healthy(10)


@respx.mock
async def test_probe_uses_native_protocol_and_treats_errors_as_down():
    openai = await Channel.create(name="o", provider="openai", base_url="https://o.example.com/v1",
                                  api_key="sk-o", models=["gpt-4o"])
    anthropic = await Channel.create(name="a", provider="anthropic", base_url="https://a.example.com",
                                     api_key="sk-a", models=["claude-x"], model_mapping={"claude-x": "claude-real"})
    models = respx.get("https://o.example.com/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    messages = respx.post("https://a.example.com/v1/messages").mock(return_value=httpx.Response(529))
    assert await health._probe_channel(openai) is True
    assert models.calls.last.request.headers["authorization"] == "Bearer sk-o"
    assert await health._probe_channel(anthropic) is False
    sent = messages.calls.last.request
    assert sent.headers["x-api-key"] == "sk-a" and b'"claude-real"' in sent.content and b'"max_tokens":1' in sent.content
    messages.mock(side_effect=httpx.ConnectTimeout("down"))
    assert await health._probe_channel(anthropic) is False


async def test_background_loop_probes_only_open_channels(alerts):
    up = await Channel.create(name="up", provider="openai", base_url="https://u.example.com", api_key="k")
    back = await Channel.create(name="back", provider="openai", base_url="https://b.example.com", api_key="k")
    still = await Channel.create(name="still", provider="openai", base_url="https://s.example.com", api_key="k")
    for channel in (back, still):
        for _ in range(3):
            await health.record_failure(channel.id)
    probed = []

    async def probe(channel):
        probed.append(channel.id)
        return channel.id == back.id

    sleeps = 0

    async def sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    with patch.object(health, "_probe_channel", probe), patch.object(health.asyncio, "sleep", sleep):
        with pytest.raises(asyncio.CancelledError):
            await health.health_check_loop()
    assert sorted(probed) == sorted([back.id, still.id]) and up.id not in probed
    assert await health.is_channel_healthy(back.id)
    assert not await health.is_channel_healthy(still.id)
