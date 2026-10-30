"""SQL budgets for the hot path and dashboards, so N+1 queries and log scans fail fast."""
from decimal import Decimal

import httpx
import pytest
import respx
from starlette.requests import Request
from tortoise import Tortoise

from app.models import APIKey, Channel, ModelPrice, Settlement, Tenant
from app.services.auth import authenticate_api_key, hash_api_key
from app.services.quota import QuotaExceeded, begin_request_budget
from tests.conftest import auth_header, create_test_tenant

RAW = "sk-query-budget-key"
# Raise only after reviewing the new statements; the inference path runs for every token sold.
REQUEST_SQL_BUDGET = 26
BODY = {"model": "gpt-4o", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}
UPSTREAM = {"id": "1", "object": "chat.completion", "model": "gpt-4o", "choices": [],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}


@pytest.fixture
async def statements():
    captured: list[str] = []
    connection = Tortoise.get_connection("default")
    await connection.execute_query("SELECT 1")
    await connection._connection.set_trace_callback(captured.append)
    yield captured
    await connection._connection.set_trace_callback(None)


async def _gateway(channels: int) -> None:
    for index in range(channels):
        await Channel.create(name=f"pool-{index}", provider="openai", base_url=f"https://pool{index}.example.com",
                             api_key="sk-up", models=["gpt-4o"])
    await ModelPrice.create(model="gpt-4o", prompt_price=Decimal(1), completion_price=Decimal(1))
    tenant = await create_test_tenant()
    await APIKey.create(tenant_id=tenant.id, name="budget", key_hash=hash_api_key(RAW), key_prefix=RAW[:8],
                        quota_total=Decimal(100))


async def _measure(client, statements, body=BODY) -> list[str]:
    # The first request warms settings caches that a running gateway already holds.
    assert (await client.post("/v1/chat/completions", json=BODY, headers=auth_header(RAW))).status_code == 200
    statements.clear()
    response = await client.post("/v1/chat/completions", json=body, headers=auth_header(RAW))
    assert response.status_code == 200
    if body.get("stream"):
        await response.aread()
    return list(statements)


@respx.mock
@pytest.mark.parametrize("stream", [False, True])
async def test_inference_sql_is_bounded_and_independent_of_pool_size(client, statements, stream):
    respx.post(path="/v1/chat/completions").mock(return_value=httpx.Response(200, json=UPSTREAM))
    await _gateway(1)
    single = await _measure(client, statements, {**BODY, "stream": stream})
    for index in range(1, 8):
        await Channel.create(name=f"extra-{index}", provider="openai", base_url=f"https://x{index}.example.com",
                             api_key="sk-up", models=["gpt-4o"])
    pooled = await _measure(client, statements, {**BODY, "stream": stream})
    assert len(pooled) == len(single), "per-channel queries on the request path"
    assert len(single) <= REQUEST_SQL_BUDGET, "\n".join(single)
    reads = [sql for sql in single if "request_logs" in sql and not sql.startswith("INSERT")]
    assert not reads, reads
    assert _tenant_reads_before_reserve(single) == 1, "\n".join(single)


def _tenant_reads_before_reserve(sql: list[str]) -> int:
    unlocked = sql[:sql.index("BEGIN")]
    return sum(1 for statement in unlocked if statement.startswith("SELECT") and 'FROM "tenants"' in statement)


@respx.mock
async def test_anthropic_reads_tenant_once_before_reserve(client, statements):
    respx.post(path="/v1/messages").mock(return_value=httpx.Response(200, json={
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-x", "content": [],
        "stop_reason": "end_turn", "usage": {"input_tokens": 5, "output_tokens": 5},
    }))
    await Channel.create(name="claude", provider="anthropic", base_url="https://claude.example.com",
                         api_key="sk-up", models=["claude-x"])
    await ModelPrice.create(model="claude-x", prompt_price=Decimal(1), completion_price=Decimal(1))
    tenant = await create_test_tenant()
    await APIKey.create(tenant_id=tenant.id, name="budget", key_hash=hash_api_key(RAW), key_prefix=RAW[:8],
                        quota_total=Decimal(100))
    body = {"model": "claude-x", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}
    headers = {"x-api-key": RAW, "anthropic-version": "2023-06-01"}
    assert (await client.post("/v1/messages", json=body, headers=headers)).status_code == 200
    statements.clear()
    assert (await client.post("/v1/messages", json=body, headers=headers)).status_code == 200
    assert len(statements) <= REQUEST_SQL_BUDGET, "\n".join(statements)
    assert _tenant_reads_before_reserve(statements) == 1, "\n".join(statements)


async def test_tenant_disabled_after_authentication_is_still_denied(client):
    tenant = await create_test_tenant()
    await APIKey.create(tenant_id=tenant.id, name="budget", key_hash=hash_api_key(RAW), key_prefix=RAW[:8],
                        quota_total=Decimal(100))
    await ModelPrice.create(model="gpt-4o", prompt_price=Decimal(1), completion_price=Decimal(1))
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)})
    api_key = await authenticate_api_key(request, RAW)
    await Tenant.filter(id=tenant.id).update(is_enabled=False)
    with pytest.raises(QuotaExceeded) as denied:
        await begin_request_budget(api_key, "stale-tenant", BODY)
    assert denied.value.scope == "tenant_disabled"
    assert not await Settlement.exists(request_id="stale-tenant")


AGGREGATE_STATS = ["overview", "usage", "by-model", "by-key", "by-channel", "by-tenant", "cache", "error-rate"]
WINDOWED_STATS = ["latency", "throughput", "sessions"]


@pytest.mark.parametrize("name", AGGREGATE_STATS + WINDOWED_STATS)
async def test_dashboards_never_scan_the_whole_request_log(client, admin_token, statements, name):
    statements.clear()
    response = await client.get(f"/api/stats/{name}", headers=auth_header(admin_token))
    assert response.status_code == 200
    scans = [sql for sql in statements if "request_logs" in sql]
    if name in AGGREGATE_STATS:
        assert not scans, f"{name} must read usage_daily: {scans}"
    else:
        assert scans and all("created_at" in sql and ">=" in sql for sql in scans), scans
