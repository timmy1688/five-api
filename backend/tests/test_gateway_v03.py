from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel, ModelPrice, RequestLog, Team, UsageDaily
from app.services.auth import create_access_token, hash_api_key
from tests.conftest import auth_header, create_admin

pytestmark = pytest.mark.asyncio

RAW_KEY = "sk-v03-feature-key"


async def _env(models=("gpt-4o",), team: Team | None = None, quota="100"):
    ch = await Channel.create(
        name="v03-ch", provider="openai", base_url="https://api.openai.test",
        api_key="sk-up", models=list(models), timeout=60,
    )
    key = await APIKey.create(
        name="v03-key", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8],
        quota_total=Decimal(quota), team_id=team.id if team else None,
    )
    return ch, key


def _http(response: httpx.Response | None = None, stream: httpx.Response | None = None):
    http = AsyncMock()
    http.is_closed = False
    http.build_request = lambda *args, **kwargs: None
    if response is not None:
        http.post = AsyncMock(return_value=response)
        http.request = http.post
    if stream is not None:
        http.send = AsyncMock(return_value=stream)
    return http


def _json(payload, headers=None, status=200):
    return httpx.Response(
        status, json=payload, headers=headers or {},
        request=httpx.Request("POST", "https://api.openai.test/v1/x"),
    )


def _sse(text: str):
    return httpx.Response(
        200, content=text.encode(),
        headers={"content-type": "text/event-stream"},
        request=httpx.Request("POST", "https://api.openai.test/v1/x"),
    )


async def test_password_change_revokes_old_token(client):
    admin = await create_admin("revoke", "old-password")
    login = await client.post("/api/login", json={"username": "revoke", "password": "old-password"})
    old = login.json()["access_token"]
    changed = await client.put(
        "/api/password",
        json={"old_password": "old-password", "new_password": "new-password-1"},
        headers=auth_header(old),
    )
    assert changed.status_code == 200
    assert (await client.get("/api/me", headers=auth_header(old))).status_code == 401
    fresh = changed.json()["access_token"]
    assert (await client.get("/api/me", headers=auth_header(fresh))).status_code == 200
    assert admin.id


async def test_login_locks_after_repeated_failures(client):
    await create_admin("bruteforce", "right-password")
    for _ in range(10):
        resp = await client.post("/api/login", json={"username": "bruteforce", "password": "nope"})
        assert resp.status_code == 401
    blocked = await client.post("/api/login", json={"username": "bruteforce", "password": "right-password"})
    assert blocked.status_code == 429


async def test_stream_without_usage_bills_forwarded_text(client):
    await _env()
    await ModelPrice.create(model="gpt-4o", prompt_price=Decimal("1"), completion_price=Decimal("1000"))
    sse = (
        'data: {"choices":[{"delta":{"content":"abcdefgh"}}]}\n\n'
        'data: {"choices":[{"delta":{"reasoning_content":"你好"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    with patch("app.providers.base._shared_http_client", return_value=_http(stream=_sse(sse))):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "hello world"}]},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    log = await RequestLog.get()
    assert log.completion_tokens == 4
    assert log.prompt_tokens > 0
    assert log.cost > 0


async def test_responses_non_stream_and_stream_usage(client):
    await _env()
    payload = {
        "id": "resp_1", "object": "response", "output": [],
        "usage": {"input_tokens": 12, "output_tokens": 7, "input_tokens_details": {"cached_tokens": 2}},
    }
    http = _http(response=_json(payload))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/responses", json={"model": "gpt-4o", "input": "hi"}, headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    assert resp.json()["id"] == "resp_1"
    assert http.post.await_args.args[0] == "v1/responses"
    log = await RequestLog.get()
    assert (log.prompt_tokens, log.completion_tokens, log.cached_tokens) == (12, 7, 2)

    sse = (
        'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"Hi"}\n\n'
        'event: response.completed\ndata: {"type":"response.completed","response":'
        '{"usage":{"input_tokens":5,"output_tokens":3}}}\n\n'
    )
    stream_http = _http(stream=_sse(sse))
    with patch("app.providers.base._shared_http_client", return_value=stream_http):
        resp = await client.post(
            "/v1/responses", json={"model": "gpt-4o", "input": "hi", "stream": True},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    assert "event: response.completed\ndata:" in resp.text
    latest = await RequestLog.all().order_by("-id").first()
    assert (latest.prompt_tokens, latest.completion_tokens, latest.is_stream) == (5, 3, True)


async def test_image_generation_bills_per_image(client):
    await _env(models=("gpt-image-1",))
    await ModelPrice.create(model="gpt-image-1", request_price=Decimal("0.04"))
    http = _http(response=_json({"data": [{"b64_json": "x"}, {"b64_json": "y"}]}))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/images/generations",
            json={"model": "gpt-image-1", "prompt": "cat", "n": 2},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    log = await RequestLog.get()
    assert log.cost == Decimal("0.08")
    key = await APIKey.get(name="v03-key")
    assert key.quota_used == Decimal("0.08")


async def test_audio_speech_returns_binary(client):
    await _env(models=("tts-1",))
    await ModelPrice.create(model="tts-1", prompt_price=Decimal("15"))
    upstream = httpx.Response(
        200, content=b"ID3audio", headers={"content-type": "audio/mpeg"},
        request=httpx.Request("POST", "https://api.openai.test/v1/audio/speech"),
    )
    with patch("app.providers.base._shared_http_client", return_value=_http(response=upstream)):
        resp = await client.post(
            "/v1/audio/speech",
            json={"model": "tts-1", "input": "hello", "voice": "alloy"},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    assert resp.content == b"ID3audio"
    assert resp.headers["content-type"] == "audio/mpeg"
    log = await RequestLog.get()
    assert log.prompt_tokens == 5


async def test_transcription_forwards_multipart(client):
    ch, _ = await _env(models=("whisper-1",))
    ch.model_mapping = {"whisper-1": "whisper-large"}
    await ch.save()
    http = _http(response=_json({"text": "hello"}))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post(
            "/v1/audio/transcriptions",
            data={"model": "whisper-1"},
            files={"file": ("a.wav", b"RIFF", "audio/wav")},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    assert resp.json() == {"text": "hello"}
    kwargs = http.post.await_args.kwargs
    assert kwargs["data"] == {"model": "whisper-large"}
    assert kwargs["files"][0][1][0] == "a.wav"


async def test_rerank_uses_reported_usage(client):
    await _env(models=("rerank-v3",))
    payload = {"results": [{"index": 0, "relevance_score": 0.9}], "usage": {"total_tokens": 42}}
    with patch("app.providers.base._shared_http_client", return_value=_http(response=_json(payload))):
        resp = await client.post(
            "/v1/rerank",
            json={"model": "rerank-v3", "query": "q", "documents": ["a", "b"]},
            headers=auth_header(RAW_KEY),
        )
    assert resp.status_code == 200
    log = await RequestLog.get()
    assert log.prompt_tokens == 42


async def test_team_budget_blocks_and_accumulates(client):
    team = await Team.create(name="research", quota_total=Decimal("1"))
    await _env(team=team)
    await ModelPrice.create(model="gpt-4o", prompt_price=Decimal("1000"), completion_price=Decimal("1000"))
    payload = {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 100}}
    with patch("app.providers.base._shared_http_client", return_value=_http(response=_json(payload))):
        ok = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(RAW_KEY),
        )
        assert ok.status_code == 200
        await team.refresh_from_db()
        assert team.quota_used == Decimal("0.2")

        await Team.filter(id=team.id).update(quota_used=Decimal("1"))
        blocked = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(RAW_KEY),
        )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["error"]["code"] == "team_quota_exceeded"

    team.is_enabled = False
    await team.save()
    disabled = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(RAW_KEY),
    )
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["error"]["code"] == "team_disabled"


async def test_team_crud_and_stats(client):
    admin = await create_admin("teamadmin", "pw")
    headers = auth_header(create_access_token({"sub": str(admin.id)}))
    created = await client.post("/api/teams", json={"name": "ops", "quota_total": 50}, headers=headers)
    assert created.status_code == 201
    team_id = created.json()["id"]

    key = await client.post("/api/keys", json={"name": "ops-key", "team_id": team_id}, headers=headers)
    assert key.status_code == 201
    assert key.json()["team_name"] == "ops"
    assert (await client.delete(f"/api/teams/{team_id}", headers=headers)).status_code == 409

    await UsageDaily.create(
        day="2099-01-01", api_key_id=key.json()["id"], team_id=team_id, model="gpt-4o",
        request_count=3, total_tokens=30, cost=Decimal("1.5"),
    )
    with patch("app.routers.stats.start_day", return_value="2000-01-01"):
        stats = await client.get("/api/stats/by-team", headers=headers)
        overview = await client.get("/api/stats/overview", headers=headers)
    assert stats.json() == [{
        "team_id": team_id, "team_name": "ops", "total_tokens": 30, "request_count": 3, "cost": 1.5,
    }]
    assert overview.json()["total_requests"] == 3


async def test_usage_daily_tracks_each_request(client):
    await _env()
    payload = {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 6}}
    with patch("app.providers.base._shared_http_client", return_value=_http(response=_json(payload))):
        for _ in range(2):
            await client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
                headers=auth_header(RAW_KEY),
            )
    row = await UsageDaily.get()
    assert (row.request_count, row.total_tokens, row.error_count) == (2, 20, 0)


async def test_least_busy_routing_prefers_idle_channel(mock_redis):
    from app.providers.registry import resolve_candidates
    from app.services.settings_service import set_gateway_config

    busy = await Channel.create(name="busy", provider="openai", base_url="https://a", api_key="", models=["m"], weight=1000)
    idle = await Channel.create(name="idle", provider="openai", base_url="https://b", api_key="", models=["m"], weight=1)
    await set_gateway_config({"routing_strategy": "least_busy"})
    mock_redis.data[f"five:ch_inflight:{busy.id}"] = "7"
    for _ in range(5):
        order = [ch.id for ch, _ in await resolve_candidates("m", preferred_protocol="openai")]
        assert order == [idle.id, busy.id]


async def test_latency_routing_prefers_fast_channel(mock_redis):
    from app.providers.registry import resolve_candidates
    from app.services.channel_stats import record_latency
    from app.services.settings_service import set_gateway_config

    slow = await Channel.create(name="slow", provider="openai", base_url="https://a", api_key="", models=["m"], weight=1000)
    fast = await Channel.create(name="fast", provider="openai", base_url="https://b", api_key="", models=["m"], weight=1)
    await set_gateway_config({"routing_strategy": "latency"})
    await record_latency(slow.id, 3000)
    await record_latency(fast.id, 200)
    order = [ch.id for ch, _ in await resolve_candidates("m", preferred_protocol="openai")]
    assert order == [fast.id, slow.id]
