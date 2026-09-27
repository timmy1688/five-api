"""并发压测：成功突发、并发上限、安全过滤，以及密钥扫描耗时。"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models import APIKey, Channel, ModelPrice, RequestLog, SecurityKeyword
from app.services.auth import hash_api_key
from app.services.content_filter import match_secret
from app.services.settings_service import set_keyword_filter_enabled
from tests.conftest import auth_header

pytestmark = [pytest.mark.asyncio, pytest.mark.load]

BURST = 200
BODY = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]}


class _Upstream:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _payload() -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 0, "total_tokens": 1000},
    }


async def _ready(name: str, *, concurrent_limit: int = 1000, quota: str = "100") -> str:
    await Channel.create(
        name=name,
        provider="openai",
        base_url="https://upstream.openai.test/v1",
        api_key="sk-up",
        models=["gpt-4o"],
        max_retries=0,
    )
    await ModelPrice.create(
        model="gpt-4o",
        prompt_price=Decimal("1"),
        completion_price=Decimal("1"),
    )
    raw = f"sk-{name}"
    await APIKey.create(
        name=name,
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal(quota),
        concurrent_limit=concurrent_limit,
        rpm_limit=-1,
    )
    return raw


async def test_concurrent_chats_keep_exact_quota_and_logs(client):
    raw = await _ready("load-ok")
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(return_value=_Upstream(_payload()))
    with patch("app.providers.base._shared_http_client", return_value=http):
        responses = await asyncio.gather(*[
            client.post("/v1/chat/completions", json=BODY, headers=auth_header(raw))
            for _ in range(BURST)
        ])

    assert [resp.status_code for resp in responses] == [200] * BURST
    logs = await RequestLog.filter(api_key_name="load-ok")
    assert len(logs) == BURST
    key = await APIKey.get(name="load-ok")
    assert key.quota_used == sum((log.cost for log in logs), Decimal(0))
    assert key.quota_used == (Decimal(BURST) * Decimal("0.001")).quantize(Decimal("0.000001"))


async def test_concurrency_limit_sheds_the_overflow(client, mock_redis):
    raw = await _ready("load-cap", concurrent_limit=3)
    state = {"inflight": 0}
    release = asyncio.Event()
    entered = asyncio.Event()

    async def eval_script(script, *_args):
        if "ZCARD" in script and "ZADD" in script:
            if state["inflight"] >= 3:
                return 0
            state["inflight"] += 1
            if state["inflight"] == 3:
                entered.set()
            return 1
        if "ZREM" in script:
            state["inflight"] = max(0, state["inflight"] - 1)
            return 1
        return 1

    mock_redis.eval = eval_script

    async def post(*_args, **_kwargs):
        await release.wait()
        return _Upstream(_payload())

    http = AsyncMock()
    http.is_closed = False
    http.post = post

    async def one():
        return await client.post("/v1/chat/completions", json=BODY, headers=auth_header(raw))

    with patch("app.providers.base._shared_http_client", return_value=http):
        pending = asyncio.gather(*[one() for _ in range(40)])
        await asyncio.wait_for(entered.wait(), timeout=5)
        await asyncio.sleep(0.05)
        release.set()
        responses = await pending

    codes = sorted(resp.status_code for resp in responses)
    assert codes == [200] * 3 + [429] * 37
    for resp in responses:
        if resp.status_code == 429:
            assert resp.json()["detail"]["error"]["code"] == "concurrent_limit"


async def test_keyword_filter_stays_correct_under_concurrency(client):
    await SecurityKeyword.create(keyword="Project Atlas", keyword_key="project atlas", direction="request")
    await set_keyword_filter_enabled(True)
    channel = await Channel.create(
        name="load-filter",
        provider="openai",
        base_url="https://upstream.openai.test/v1",
        api_key="sk-up",
        models=["gpt-4o"],
        max_retries=0,
    )
    raw = "sk-load-filter"
    await APIKey.create(
        name="load-filter",
        key_hash=hash_api_key(raw),
        key_prefix=raw[:8],
        quota_total=Decimal("-1"),
        concurrent_limit=1000,
        rpm_limit=-1,
    )
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value={
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()

    async def send(blocked: bool):
        content = "notes about Project Atlas" if blocked else "hello"
        return await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": content}]},
            headers=auth_header(raw),
        )

    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        responses = await asyncio.gather(*[send(i % 2 == 0) for i in range(BURST)])

    assert [resp.status_code for resp in responses] == [200] * BURST
    assert provider.send_request.await_count == BURST
    hits = [log.security_hit for log in await RequestLog.filter(api_key_name="load-filter")]
    assert hits.count("project atlas") == BURST // 2
    assert hits.count("") == BURST // 2


async def test_secret_scan_stays_fast_on_a_large_body():
    filler = "a" * 256_000
    secret = "AKIAIOSFODNN7EXAMPLE"
    text = filler + secret
    started = time.perf_counter()
    found = None
    for _ in range(40):
        found = match_secret(text)
    elapsed = time.perf_counter() - started
    assert found == "aws_access_key"
    assert elapsed < 3
