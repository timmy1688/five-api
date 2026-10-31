import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from tortoise import connections

from app.main import create_app
from app.models import APIKey, Channel, ModelPrice, RequestLog, Settlement, Tenant, UsageDaily, User
from app.services import settlements
from app.services.auth import hash_api_key, hash_password
from app.services.spend_windows import record_settlement_spend, window_spend
from tests.integration.conftest import serve

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
MODEL = "integration-model"
BODY = {"model": MODEL, "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}
DATA = 'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
USAGE = 'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\ndata: [DONE]\n\n'


async def ready(upstream_url, *, quota="10", **limits):
    tenant = await Tenant.create(name="real-tenant", quota_total=Decimal(quota), **limits)
    raws = []
    for index in range(2):
        raw = "sk-real-integration-client-" + str(index)
        await APIKey.create(tenant_id=tenant.id, name=f"real-{index}", key_hash=hash_api_key(raw),
                            key_prefix=raw[:8], quota_total=-1)
        raws.append(raw)
    await Channel.create(name="real-channel", provider="openai", base_url=upstream_url,
                         models=[MODEL], api_key="", max_retries=0, timeout=1, priority=10)
    await ModelPrice.create(model=MODEL, prompt_price=2, completion_price=3)
    return tenant, raws


def headers(raw):
    return {"Authorization": "Bearer " + raw}


def app_with_chat(handler):
    app = FastAPI()
    app.add_api_route("/v1/chat/completions", handler, methods=["POST"])
    return app


async def eventually(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.02)


async def test_real_http_stream_and_client_cancellation_releases_leases(gateway_url, mock_redis):
    async def chat():
        async def events():
            yield DATA
            await asyncio.sleep(60)
        return StreamingResponse(events(), media_type="text/event-stream")
    async with serve(app_with_chat(chat)) as origin:
        tenant, raws = await ready(origin)
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            async with client.stream("POST", gateway_url + "/v1/chat/completions",
                                     json={**BODY, "stream": True}, headers=headers(raws[0])) as stream:
                assert stream.status_code == 200
                line = await anext(stream.aiter_lines())
                assert "hello" in line
        await eventually(lambda: Settlement.filter(state="settled").exists())
        log = await RequestLog.get()
        assert log.status_code == 499 and log.completion_tokens > 0
        assert await mock_redis.zcard(f"five:concurrency:tenant:{tenant.id}") == 0
        assert await settlements.occupied("tenant", tenant.id) == 0


async def test_hang_up_after_final_event_is_a_success(gateway_url):
    async def chat():
        async def events():
            yield DATA
            yield USAGE
            await asyncio.sleep(60)
        return StreamingResponse(events(), media_type="text/event-stream")
    async with serve(app_with_chat(chat)) as origin:
        _, raws = await ready(origin)
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            async with client.stream("POST", gateway_url + "/v1/chat/completions",
                                     json={**BODY, "stream": True}, headers=headers(raws[0])) as stream:
                async for line in stream.aiter_lines():
                    if line == "data: [DONE]":
                        break
        await eventually(lambda: Settlement.filter(state="settled").exists())
        log = await RequestLog.get()
        assert log.status_code == 200 and log.usage_source == "upstream"
        assert log.cost == Decimal("0.000035")


async def test_first_byte_failure_fails_over_with_real_http(gateway_url):
    origin = FastAPI()
    @origin.post("/first/v1/chat/completions")
    async def first():
        return JSONResponse(status_code=503, content={"error": {"message": "try another"}})
    @origin.post("/second/v1/chat/completions")
    async def second():
        async def events():
            yield DATA
            yield USAGE
        return StreamingResponse(events(), media_type="text/event-stream")
    async with serve(origin) as upstream:
        _, raws = await ready(upstream + "/first")
        await Channel.create(name="fallback", provider="openai", base_url=upstream + "/second",
                             models=[MODEL], api_key="", priority=1, max_retries=0)
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            result = await client.post(gateway_url + "/v1/chat/completions",
                                       json={**BODY, "stream": True}, headers=headers(raws[0]))
        assert result.status_code == 200 and "[DONE]" in result.text
        log = await RequestLog.get()
        assert log.failed_over and log.usage_source == "upstream"
        assert log.cost == Decimal("0.000035")


async def test_disconnect_after_first_byte_does_not_replay_upstream(gateway_url):
    calls = []
    origin = FastAPI()
    @origin.post("/first/v1/chat/completions")
    async def first():
        calls.append("first")
        async def events():
            yield DATA
            await asyncio.sleep(0.05)
            raise RuntimeError("injected upstream disconnect")
        return StreamingResponse(events(), media_type="text/event-stream")
    @origin.post("/second/v1/chat/completions")
    async def second():
        calls.append("second")
        return {}
    async with serve(origin) as upstream:
        await ready(upstream + "/first")
        await Channel.create(name="fallback", provider="openai", base_url=upstream + "/second",
                             models=[MODEL], api_key="", priority=1, max_retries=0)
        raw = "sk-real-integration-client-0"
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            result = await client.post(gateway_url + "/v1/chat/completions",
                                       json={**BODY, "stream": True}, headers=headers(raw))
        assert result.status_code == 200 and "hello" in result.text and "error" in result.text
        assert calls == ["first"]
        log = await RequestLog.get()
        assert log.status_code == 502 and log.usage_source == "estimated"


async def test_timeout_keeps_unknown_work_occupied(gateway_url):
    async def chat():
        await asyncio.sleep(2)
        return {}
    async with serve(app_with_chat(chat)) as origin:
        tenant, raws = await ready(origin)
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            result = await client.post(gateway_url + "/v1/chat/completions", json=BODY, headers=headers(raws[0]))
        assert result.status_code == 502
        record = await Settlement.get()
        assert record.state == "uncertain" and record.occupied > 0
        assert await settlements.occupied("tenant", tenant.id) == record.occupied


async def test_real_lua_tenant_shared_limits_and_ttl(gateway_url, mock_redis):
    async def chat():
        return {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    async with serve(app_with_chat(chat)) as origin:
        tenant, raws = await ready(origin, rpm_limit=2)
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            for raw in raws:
                result = await client.post(gateway_url + "/v1/chat/completions", json=BODY, headers=headers(raw))
                assert result.status_code == 200
            denied = await client.post(gateway_url + "/v1/chat/completions", json=BODY, headers=headers(raws[0]))
        assert denied.status_code == 429 and denied.json()["error"]["code"] == "tenant_rpm_limit"
        ttl = await mock_redis.ttl(f"five:rpm:tenant:{tenant.id}")
        assert 0 < ttl <= 60


async def test_mysql_transaction_failure_and_recovery(gateway_url):
    async def chat():
        return {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    async with serve(app_with_chat(chat)) as origin:
        tenant, raws = await ready(origin)
        connection = connections.get("default")
        await connection.execute_script("ALTER TABLE tenants ADD CONSTRAINT reject_test_debit CHECK (quota_used=0);")
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            result = await client.post(gateway_url + "/v1/chat/completions", json=BODY, headers=headers(raws[0]))
        assert result.status_code == 200
        assert (await Tenant.get(id=tenant.id)).quota_used == 0
        assert (await APIKey.get(name="real-0")).quota_used == 0
        assert await RequestLog.all().count() == await UsageDaily.all().count() == 0
        record = await Settlement.get()
        assert record.state == "pending"
        await connection.execute_script("ALTER TABLE tenants DROP CHECK reject_test_debit;")
        await Settlement.filter(id=record.id).update(next_retry_at=None)
        await settlements.recover_once()
        await settlements.recover_once()
        assert (await Tenant.get(id=tenant.id)).quota_used == Decimal("0.000035")
        assert (await UsageDaily.get()).request_count == 1


async def test_mysql_unique_account_constraint_and_auth_state_failure(gateway_url):
    from tortoise.exceptions import IntegrityError
    tenant = await Tenant.create(name="unique-tenant")
    await User.create(username="first", role="tenant", tenant_id=tenant.id, hashed_password=hash_password("password"))
    with pytest.raises(IntegrityError):
        await User.create(username="second", role="tenant", tenant_id=tenant.id, hashed_password=hash_password("password"))


async def test_client_ip_is_only_taken_from_trusted_proxy(gateway_url):
    tenant = await Tenant.create(name="ip-tenant", quota_total=10)
    raw = "sk-allowlisted-integration-client"
    await APIKey.create(name="restricted", tenant_id=tenant.id, key_hash=hash_api_key(raw),
                        key_prefix=raw[:8], allowed_ips=["203.0.113.8"])
    request_headers = {**headers(raw), "X-Forwarded-For": "203.0.113.8"}
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        assert (await client.get(gateway_url + "/v1/models", headers=request_headers)).status_code == 403
        async with serve(create_app(), trusted="127.0.0.1") as trusted:
            assert (await client.get(trusted + "/v1/models", headers=request_headers)).status_code == 200
