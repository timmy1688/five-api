"""Upstream credential failover, non-idempotent retries, cooling key pools,
in-flight budget holds, customer-visible prices and internal tenant stats."""
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx

from app.models import APIKey, Channel, ModelPrice, RequestLog, Settlement, Tenant, UsageDaily
from app.services.auth import hash_api_key
from app.services.channel_health import FAIL_KEY_PREFIX
from app.services.key_pool import cool_down
from tests.conftest import auth_header, create_test_tenant

RAW_KEY = "sk-rules-client-key"
CHAT = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
OK = {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
IMAGE_OK = {"data": [{"b64_json": "x"}]}


def _resp(status, payload):
    return httpx.Response(status, json=payload,
                          request=httpx.Request("POST", "https://api.openai.test/v1/chat/completions"))


def _http(*outcomes):
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(side_effect=list(outcomes))
    return http


def _sent_keys(http):
    return [call.kwargs["headers"]["Authorization"].removeprefix("Bearer ") for call in http.post.await_args_list]


async def _channel(name, keys, models=("gpt-4o",), priority=0, **extra):
    return await Channel.create(name=name, provider="openai", base_url="https://api.openai.test",
                                api_key=keys, models=list(models), timeout=60, priority=priority, **extra)


async def _key(tenant=None, **fields):
    tenant = tenant or await create_test_tenant()
    return await APIKey.create(tenant_id=tenant.id, name="rules-key", key_hash=hash_api_key(RAW_KEY),
                               key_prefix=RAW_KEY[:8], **{"quota_total": Decimal("-1"), **fields})


async def test_upstream_401_switches_channel_and_counts_failure(client, mock_redis):
    primary = await _channel("primary", "sk-a", priority=10)
    await _channel("backup", "sk-b")
    await ModelPrice.create(model="gpt-4o")
    await _key()
    http = _http(_resp(401, {"error": {"message": "invalid key sk-a"}}), _resp(200, OK))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert resp.status_code == 200
    assert _sent_keys(http) == ["sk-a", "sk-b"]
    assert mock_redis.data[f"{FAIL_KEY_PREFIX}{primary.id}"] == "1"


async def test_final_upstream_401_is_not_shown_as_customer_auth_error(client):
    await _channel("only", "sk-a", max_retries=0)
    await ModelPrice.create(model="gpt-4o")
    await _key()
    http = _http(_resp(401, {"error": {"message": "invalid key sk-a"}}))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert resp.status_code == 502
    assert "Upstream credentials unavailable" in resp.text
    assert "invalid key" not in resp.text
    log = await RequestLog.get()
    assert "invalid key" in log.upstream_error


async def test_fully_cooling_key_pool_skips_channel_without_calling_it(client):
    pooled = await _channel("pooled", "sk-a1\nsk-a2", priority=10)
    await _channel("backup", "sk-b")
    await ModelPrice.create(model="gpt-4o")
    await _key()
    for key in ("sk-a1", "sk-a2"):
        await cool_down(pooled.id, key, 600)
    http = _http(_resp(200, OK))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert resp.status_code == 200
    assert _sent_keys(http) == ["sk-b"]


async def test_last_channel_with_cooling_pool_returns_503_without_upstream_call(client):
    pooled = await _channel("pooled", "sk-a1\nsk-a2")
    await ModelPrice.create(model="gpt-4o")
    await _key()
    for key in ("sk-a1", "sk-a2"):
        await cool_down(pooled.id, key, 600)
    http = _http()
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert resp.status_code == 503
    assert http.post.await_count == 0


async def _image_env():
    await _channel("img-a", "sk-a", models=("gpt-image-1",), priority=10, max_retries=2)
    await _channel("img-b", "sk-b", models=("gpt-image-1",))
    await ModelPrice.create(model="gpt-image-1", request_price=Decimal("0.04"))
    await _key()


async def _generate_image(client, http):
    with patch("app.providers.base._shared_http_client", return_value=http):
        return await client.post("/v1/images/generations", json={"model": "gpt-image-1", "prompt": "cat"},
                                 headers=auth_header(RAW_KEY))


async def test_image_generation_is_not_resent_after_read_timeout(client):
    await _image_env()
    http = _http(httpx.ReadTimeout("slow"), _resp(200, IMAGE_OK))
    assert (await _generate_image(client, http)).status_code != 200
    assert http.post.await_count == 1


async def test_image_generation_is_not_resent_after_upstream_5xx(client):
    await _image_env()
    http = _http(_resp(503, {"error": {"message": "busy"}}), _resp(200, IMAGE_OK))
    assert (await _generate_image(client, http)).status_code != 200
    assert http.post.await_count == 1


async def test_image_generation_retries_when_upstream_was_never_reached(client):
    await _image_env()
    http = _http(httpx.ConnectError("refused"), _resp(200, IMAGE_OK))
    assert (await _generate_image(client, http)).status_code == 200
    assert http.post.await_count == 2


async def test_window_cap_counts_in_flight_holds(client):
    await _channel("w", "sk-a")
    await ModelPrice.create(model="gpt-4o")
    key = await _key(window_limits={"5h": 1})
    await Settlement.create(request_id="held", tenant_id=key.tenant_id, api_key_id=key.id,
                            occupied=Decimal("1"), state="pending")
    http = _http(_resp(200, OK))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert resp.status_code == 429
    assert "window_limit" in resp.text
    assert http.post.await_count == 0


async def test_budget_downgrade_counts_in_flight_holds(client):
    from app.services.settings_service import clear_settings_cache, set_gateway_config

    await _channel("d", "sk-a", models=("big-model", "small-model"))
    await ModelPrice.create(model="big-model")
    await ModelPrice.create(model="small-model")
    key = await _key(quota_total=Decimal("10"), quota_used=Decimal("7"))
    await Settlement.create(request_id="held", tenant_id=key.tenant_id, api_key_id=key.id,
                            occupied=Decimal("1.5"), state="pending")
    await set_gateway_config({"budget_downgrade": {"threshold": 0.8, "rules": {"big-model": "small-model"}}})
    http = _http(_resp(200, OK))
    with patch("app.providers.base._shared_http_client", return_value=http):
        resp = await client.post("/v1/chat/completions", json={**CHAT, "model": "big-model"},
                                 headers=auth_header(RAW_KEY))
    clear_settings_cache()
    assert resp.status_code == 200
    assert resp.headers["x-five-downgraded-to"] == "small-model"


async def test_me_shows_billed_prices_and_tenant_quota(client):
    await _channel("me", "sk-a", models=("gpt-4o", "gpt-5.6", "unpriced-model"),
                   model_mapping={"gpt-4o": "gpt-4o-2026"}, price_multiplier=Decimal("1.5"))
    await ModelPrice.create(model="gpt-4o-2026", prompt_price=Decimal("2"), completion_price=Decimal("8"))
    tenant = await Tenant.create(name="me-tenant", quota_total=Decimal("20"), quota_used=Decimal("15"))
    key = await _key(tenant, quota_total=Decimal("10"), quota_used=Decimal("1"))
    await Settlement.create(request_id="held", tenant_id=tenant.id, api_key_id=key.id,
                            occupied=Decimal("2"), state="pending")

    body = (await client.get("/v1/me", headers=auth_header(RAW_KEY))).json()
    assert body["model_prices"]["gpt-4o"]["prompt"] == 3.0
    assert body["model_prices"]["gpt-4o"]["completion"] == 12.0
    assert body["model_prices"]["gpt-5.6"]["prompt"] == 7.5
    assert "unpriced-model" not in body["model_prices"]
    assert body["model_prices_source"] == "selling_price"
    assert body["model_prices"]["gpt-4o"]["channels"][0]["channel_name"] == "me"
    assert (body["tenant_quota_total"], body["tenant_quota_used"]) == (20.0, 15.0)
    assert body["quota_remaining"] == 3.0


async def test_tenant_usage_ranking_leaves_out_internal_space(client, admin_token):
    internal = await Tenant.create(name="internal", is_system=True, quota_total=Decimal("-1"))
    customer = await Tenant.create(name="customer", quota_total=Decimal("-1"))
    for tenant, cost in ((internal, "50"), (customer, "5")):
        await UsageDaily.create(day=date.today(), api_key_id=tenant.id, tenant_id=tenant.id,
                                model="gpt-4o", request_count=1, cost=Decimal(cost))
    resp = await client.get("/api/stats/by-tenant", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert [row["tenant_name"] for row in resp.json()] == ["customer"]
