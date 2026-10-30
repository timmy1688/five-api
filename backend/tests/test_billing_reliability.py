import asyncio
from contextlib import nullcontext
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from tortoise.queryset import QuerySet

from app.models import APIKey, Channel, ModelPrice, RequestLog, Settlement, Tenant, UsageDaily
from app.services import settlements
from app.services.auth import hash_api_key
from app.services.quota import begin_request_budget
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio
MODEL = "billing-test-model"
BODY = {"model": MODEL, "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}


async def env(quota="100", **limits):
    tenant = await Tenant.create(name="billing-tenant", quota_total=Decimal(quota), **limits)
    keys = []
    for index in range(2):
        raw = "sk-billing-test-" + str(index)
        key = await APIKey.create(tenant_id=tenant.id, name=f"key-{index}",
                                  key_hash=hash_api_key(raw), key_prefix=raw[:8], quota_total=-1)
        keys.append((key, raw))
    channel = await Channel.create(
        name="billing-channel", provider="openai", base_url="https://billing.upstream.test",
        api_key="upstream-secret-do-not-expose", models=[MODEL], timeout=5,
    )
    await ModelPrice.create(model=MODEL, prompt_price=2, completion_price=3)
    return tenant, keys, channel


def response(prompt=100, output=50):
    return httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": "hello"}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": output},
    }, request=httpx.Request("POST", "https://billing.upstream.test/v1/chat/completions"))


def upstream(callback=None):
    client = AsyncMock()
    client.is_closed = False
    client.post = AsyncMock(side_effect=callback) if callback else AsyncMock(return_value=response())
    return client


async def test_selling_price_is_snapshotted_before_the_upstream_call(client):
    tenant, keys, channel = await env()

    async def send(*_args, **_kwargs):
        await ModelPrice.filter(model=MODEL).update(prompt_price=999, completion_price=999)
        await Channel.filter(id=channel.id).update(price_multiplier=9, price_overrides={MODEL: {"prompt": 1, "completion": 1}})
        return response()

    with patch("app.providers.base._shared_http_client", return_value=upstream(send)):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 200
    log = await RequestLog.get()
    assert log.cost == Decimal("0.000350")
    assert log.cost_detail["prices"]["input"] == "2"
    assert log.cost_detail["price_source"] == "global" and Decimal(log.cost_detail["multiplier"]) == 1
    assert "upstream" not in log.cost_detail
    assert (await Tenant.get(id=tenant.id)).quota_used == log.cost


@pytest.mark.parametrize("failure", ["tenant", "log", "daily"])
async def test_accounting_rolls_back_and_recovers_exactly_once(client, failure):
    tenant, keys, _ = await env()
    original_update = QuerySet.update

    def injected_update(query, **values):
        if query.model is Tenant and "quota_used" in values:
            raise RuntimeError("injected tenant debit failure")
        return original_update(query, **values)

    faults = {
        "tenant": patch.object(QuerySet, "update", new=injected_update),
        "log": patch.object(RequestLog, "create", new=AsyncMock(side_effect=RuntimeError("log write failure"))),
        "daily": patch("app.services.logging_service.record_daily_usage", new=AsyncMock(side_effect=RuntimeError("daily failure"))),
    }
    with patch("app.providers.base._shared_http_client", return_value=upstream()), faults[failure]:
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 200  # Completed upstream work is not replayed because accounting needs recovery.
    assert (await APIKey.get(id=keys[0][0].id)).quota_used == 0
    assert (await Tenant.get(id=tenant.id)).quota_used == 0
    assert await RequestLog.all().count() == await UsageDaily.all().count() == 0
    record = await Settlement.get()
    assert record.state == "pending" and record.cost == Decimal("0.000350")
    assert await settlements.occupied("tenant", tenant.id) == record.cost
    assert keys[0][1] not in str(record.payload)
    await Settlement.filter(id=record.id).update(next_retry_at=None)
    assert await settlements.recover_once() == 1
    assert await settlements.apply(record.request_id) is False
    assert (await Tenant.get(id=tenant.id)).quota_used == Decimal("0.000350")
    assert (await APIKey.get(id=keys[0][0].id)).quota_used == Decimal("0.000350")
    assert await RequestLog.all().count() == 1
    daily = await UsageDaily.get()
    assert daily.request_count == 1 and daily.cost == Decimal("0.000350")
    assert await settlements.occupied("tenant", tenant.id) == 0


async def test_identical_client_ids_are_independent_financial_requests(client):
    tenant, keys, _ = await env()
    with patch("app.providers.base._shared_http_client", return_value=upstream()):
        responses = await asyncio.gather(*[
            client.post("/v1/chat/completions", json=BODY,
                        headers={**auth_header(raw), "X-Request-ID": "same-client-id"})
            for _, raw in keys
        ])
    assert all(result.status_code == 200 for result in responses)
    internal_ids = {result.headers["x-request-id"] for result in responses}
    assert len(internal_ids) == 2 and "same-client-id" not in internal_ids
    assert await Settlement.filter(state="settled").count() == 2
    assert await RequestLog.filter(client_request_id="same-client-id").count() == 2
    assert (await Tenant.get(id=tenant.id)).quota_used == Decimal("0.000700")


async def test_shared_budget_requires_the_full_estimate_before_dispatch(client):
    _, keys, _ = await env(quota="0.000050")
    entered, finish = asyncio.Event(), asyncio.Event()

    async def send(*_args, **_kwargs):
        entered.set()
        await finish.wait()
        return response(prompt=1, output=10)

    http = upstream(send)
    with patch("app.providers.base._shared_http_client", return_value=http):
        first = asyncio.create_task(client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1])))
        await asyncio.wait_for(entered.wait(), timeout=3)
        denied = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[1][1]))
        finish.set()
        assert (await first).status_code == 200
    assert denied.status_code == 429 and denied.json()["error"]["code"] == "tenant_quota_exceeded"
    assert http.post.await_count == 1


async def test_unpriced_model_does_not_reach_upstream(client):
    _, keys, _ = await env()
    await ModelPrice.all().delete()
    http = upstream()
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 503 and result.json()["error"]["code"] == "pricing_unavailable"
    http.post.assert_not_awaited()
    assert await Settlement.all().count() == 0


async def test_tenant_rpm_is_shared_by_all_keys(client):
    _, keys, _ = await env(rpm_limit=2)
    assert (await client.get("/v1/models", headers=auth_header(keys[0][1]))).status_code == 200
    assert (await client.get("/v1/models", headers=auth_header(keys[1][1]))).status_code == 200
    denied = await client.get("/v1/models", headers=auth_header(keys[1][1]))
    assert denied.status_code == 429 and denied.json()["error"]["code"] == "tenant_rpm_limit"


@pytest.mark.parametrize("kind", ["tpm", "concurrent"])
async def test_tenant_active_limits_are_shared_by_all_keys(client, kind):
    limits = {"tpm_limit": 20} if kind == "tpm" else {"concurrent_limit": 1}
    _, keys, _ = await env(**limits)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def send(*_args, **_kwargs):
        entered.set()
        await finish.wait()
        return response(prompt=1, output=10)

    http = upstream(send)
    with patch("app.providers.base._shared_http_client", return_value=http):
        first = asyncio.create_task(client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1])))
        await asyncio.wait_for(entered.wait(), timeout=3)
        denied = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[1][1]))
        finish.set()
        assert (await first).status_code == 200
    expected = "tenant_tpm_limit" if kind == "tpm" else "tenant_concurrent_limit"
    assert denied.status_code == 429 and denied.json()["error"]["code"] == expected
    assert http.post.await_count == 1


async def test_explicit_zero_usage_is_not_replaced_with_estimates(client):
    _, keys, _ = await env()
    with patch("app.providers.base._shared_http_client", return_value=upstream(lambda *_a, **_k: response(0, 0))):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 200
    log = await RequestLog.get()
    assert log.prompt_tokens == log.completion_tokens == 0
    assert log.usage_source == "upstream" and log.cost == 0


async def test_cancelled_dispatch_retains_an_explainable_reservation(client):
    tenant, keys, _ = await env()
    entered = asyncio.Event()

    async def send(*_args, **_kwargs):
        entered.set()
        await asyncio.Event().wait()

    with patch("app.providers.base._shared_http_client", return_value=upstream(send)):
        task = asyncio.create_task(client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1])))
        await asyncio.wait_for(entered.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    record = await Settlement.get()
    assert record.state == "uncertain" and record.dispatched
    assert await settlements.occupied("tenant", tenant.id) > 0
    assert (await Tenant.get(id=tenant.id)).quota_used == 0


async def test_window_recovery_does_not_duplicate_spend(client, mock_redis):
    _, keys, _ = await env()
    with patch("app.providers.base._shared_http_client", return_value=upstream()):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 200
    record = await Settlement.get()
    before = {key: value for key, value in mock_redis.data.items() if key.startswith("five:spend:")}
    await Settlement.filter(id=record.id).update(windows_recorded=False)
    await settlements.recover_once()
    after = {key: value for key, value in mock_redis.data.items() if key.startswith("five:spend:")}
    assert before == after


@pytest.mark.parametrize("path,body,expected", [
    ("/v1/chat/completions", {}, 400), ("/v1/messages", {}, 400),
])
async def test_protocol_validation_errors_are_native_and_do_not_echo_input(client, path, body, expected):
    _, keys, _ = await env()
    result = await client.post(path, json=body, headers=auth_header(keys[0][1]))
    assert result.status_code == expected
    assert "error" in result.json() and "detail" not in result.json()
    if path == "/v1/messages":
        assert result.json()["type"] == "error"


async def test_upstream_error_credentials_are_redacted(client):
    _, keys, channel = await env()
    secret = channel.api_key
    request = httpx.Request("POST", "https://billing.upstream.test/v1/chat/completions")
    bad = httpx.Response(400, json={"error": {"type": "invalid_request_error",
                                             "message": f"Invalid key {secret} Authorization: Bearer {keys[0][1]}"}},
                        request=request)
    http = upstream()
    http.post = AsyncMock(return_value=bad)
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 400
    log = await RequestLog.get()
    for value in (result.text, log.error_message, log.upstream_error):
        assert secret not in value and keys[0][1] not in value
