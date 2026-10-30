import json
import re
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from app.models import Channel, ManagementEvent, ModelPrice, ModelProbe, RequestLog, Settlement
from app.services import settlements
from app.services.billing_quotes import quote_cost, selling_quote
from app.services.quota import begin_request_budget
from tests.conftest import auth_header, create_tenant_account
from tests.test_billing_reliability import BODY, MODEL, env, upstream, response

pytestmark = pytest.mark.asyncio


async def test_channel_multiplier_is_billed_and_snapshotted(client):
    _, keys, channel = await env()
    await Channel.filter(id=channel.id).update(price_multiplier=Decimal("0.5"))
    async def send(*args, **kwargs):
        await Channel.filter(id=channel.id).update(price_multiplier=7)
        return response()
    with patch("app.providers.base._shared_http_client", return_value=upstream(send)):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 200
    log = await RequestLog.get()
    # 100 input x $2 + 50 output x $3 per 1M = 0.00035, at half price.
    assert log.cost == Decimal("0.000175")
    assert Decimal(log.cost_detail["multiplier"]) == Decimal("0.5")
    assert log.channel_id == channel.id


async def test_channel_multiplier_is_included_in_sufficient_reservation(client):
    _, keys, channel = await env(quota="0.00005")
    await Channel.filter(id=channel.id).update(price_multiplier=10)
    http = upstream()
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 429
    http.post.assert_not_awaited()


async def test_explicit_free_channel_and_alias_quote():
    await ModelPrice.create(model="friendly-alias", prompt_price=999)
    free = Channel(id=1, name="free", price_multiplier=Decimal(0), price_overrides={})
    quote = await selling_quote("gpt-4o", "friendly-alias", free)
    assert quote["source"] == "global" and Decimal(quote["multiplier"]) == 0
    assert quote_cost(quote, 1000, 1000, 0, 0, 0)["cost"] == 0


async def test_alias_price_overrides_upstream_model_price():
    from app.services.billing_quotes import public_selling_prices

    await ModelPrice.create(model="up-model", prompt_price=10, completion_price=20)
    await ModelPrice.create(model="up-model-lite", prompt_price=2, completion_price=4)

    lite = await selling_quote("up-model", "up-model-lite")
    assert lite["model"] == "up-model" and Decimal(lite["prices"]["input"]) == 2
    unpriced_alias = await selling_quote("up-model", "up-model-other")
    assert Decimal(unpriced_alias["prices"]["input"]) == 10

    channel = Channel(id=1, name="c", price_multiplier=Decimal(1), price_overrides={})
    public = await public_selling_prices({"up-model": [(channel, "up-model")], "up-model-lite": [(channel, "up-model")]})
    assert public["up-model"]["prompt"] == 10 and public["up-model-lite"]["prompt"] == 2


@pytest.mark.parametrize("stream", [False, True])
async def test_dispatch_record_failure_returns_503_without_calling_upstream(client, stream):
    _, keys, _ = await env()
    http = upstream()
    with patch("app.providers.base._shared_http_client", return_value=http), patch(
            "app.services.settlements.mark_dispatched", side_effect=RuntimeError("DB unavailable")):
        result = await client.post("/v1/chat/completions", json={**BODY, "stream": stream},
                                   headers=auth_header(keys[0][1]))
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "accounting_unavailable"
    http.post.assert_not_awaited()
    assert await Settlement.filter(state__in=("reserved", "pending", "uncertain")).count() == 0


async def test_unknown_outcome_requires_reason_and_is_resolved_once(client, admin_token):
    _, keys, _ = await env()
    lease = await begin_request_budget(keys[0][0], "review-request", BODY)
    await lease.before_send()
    await lease.release()
    record = await Settlement.get()
    assert record.state == "uncertain"
    headers = auth_header(admin_token)
    assert (await client.post(f"/api/settlements/{record.id}/resolve", json={
        "action": "charge_estimate", "reason": ""}, headers=headers)).status_code == 422
    result = await client.post(f"/api/settlements/{record.id}/resolve", json={
        "action": "charge_estimate", "reason": "confirmed bill; actual usage unavailable"}, headers=headers)
    assert result.status_code == 200
    await settlements.recover_once()
    await settlements.recover_once()
    assert (await RequestLog.get()).cost == record.occupied
    assert (await client.post(f"/api/settlements/{record.id}/resolve", json={
        "action": "charge_estimate", "reason": "duplicate"}, headers=headers)).status_code == 409
    assert await ManagementEvent.filter(action="settlement.resolve").count() == 1


async def test_scoped_settings_update_does_not_overwrite_other_groups(client, admin_token):
    headers = auth_header(admin_token)
    await client.put("/api/settings", json={"sticky_session_ttl": 1200, "routing_strategy": "latency"}, headers=headers)
    result = await client.put("/api/settings", json={"log_retention_days": 7}, headers=headers)
    assert result.status_code == 200
    assert result.json()["sticky_session_ttl"] == 1200 and result.json()["routing_strategy"] == "latency"


async def test_bulk_price_import_never_overwrites_user_prices(client, admin_token):
    row = await ModelPrice.create(model="gpt-4o", prompt_price=99, is_active=False)
    headers = auth_header(admin_token)
    for query in ("", "?overwrite=true"):
        result = await client.post("/api/model-prices/sync-defaults" + query, headers=headers)
        assert result.status_code == 200 and result.json()["updated"] == 0
    await row.refresh_from_db()
    assert row.prompt_price == 99 and not row.is_active


async def probe_channel(provider="openai", model="gpt-4o"):
    return await Channel.create(name="probe", provider=provider, base_url="https://probe.test", models=[model],
                                api_key="upstream-credential-that-must-stay-private")


def synthetic_response(body, anthropic=False, wrong=False):
    prompt = body["messages"][0]["content"]
    if body.get("tools"):
        match = re.search(r"(\d+) \* (\d+) \+ (\d+)", prompt)
        a, b, c = map(int, match.groups())
        answer = {"answer": a*b+c}
        if anthropic:
            return {"content": [{"type": "tool_use", "name": "report_result", "id": "tool-1", "input": answer}]}
        return {"choices": [{"message": {"content": None, "tool_calls": [{"type": "function",
                    "function": {"name": "report_result", "arguments": json.dumps(answer)}}]}}]}
    if "JSON object" in prompt:
        match = re.search(r"(\d+) \* (\d+) \+ (\d+)", prompt)
        a, b, c = map(int, match.groups())
        nonce = re.search(r"FIVE_[a-z0-9]+", prompt).group()
        text = json.dumps({"answer": a*b+c, "marker": nonce})
    elif "FIVE_" in prompt:
        text = re.search(r"FIVE_[a-z0-9]+", prompt).group()
    else:
        text = "OK"
    if wrong:
        text = "wrong answer"
    return {"content": [{"type": "text", "text": text}]} if anthropic else {"choices": [{"message": {"content": text}}]}


@pytest.mark.parametrize("provider,model", [("openai", "gpt-4o"), ("anthropic", "claude-sonnet-4-6")])
async def test_capability_checks_execute_real_protocol_and_persist_evidence(client, admin_token, provider, model):
    channel = await probe_channel(provider, model)
    def respond(_url, **kwargs):
        body = kwargs["json"]
        assert body["model"] == model
        return httpx.Response(200, json=synthetic_response(body, provider == "anthropic"),
                              request=httpx.Request("POST", "https://probe.test"))
    http = upstream(respond)
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/api/models/probe", json={"channel_id": channel.id, "model": model, "kind": "capability"},
                                   headers=auth_header(admin_token))
    assert result.status_code == 200
    assert result.json()["score"] == 100 and result.json()["status"] == "passed"
    assert len(result.json()["checks"]) == http.post.await_count == 3
    assert "upstream-credential" not in json.dumps(result.json())
    history = await client.get("/api/models/probes", params={"channel_id": channel.id, "model": model},
                                headers=auth_header(admin_token))
    assert len(history.json()["items"]) == 1


async def test_capability_failure_is_a_reference_and_does_not_disable_channel(client, admin_token):
    channel = await probe_channel()
    def respond(url, **kwargs):
        return httpx.Response(200, json=synthetic_response(kwargs["json"], wrong=True), request=httpx.Request("POST", url))
    with patch("app.providers.base._shared_http_client", return_value=upstream(respond)):
        result = await client.post("/api/models/probe", json={"channel_id": channel.id, "model": "gpt-4o", "kind": "capability"},
                                   headers=auth_header(admin_token))
    assert result.json()["score"] == 33 and result.json()["status"] == "review"
    assert (await Channel.get(id=channel.id)).is_enabled


async def test_model_health_is_scoped_and_customer_prices_include_multiplier(client, admin_token):
    one = await probe_channel()
    await Channel.filter(id=one.id).update(price_multiplier=Decimal("0.8"))
    two = await Channel.create(name="other", provider="openai", base_url="https://other.test", api_key="", models=["gpt-4o"],
                               price_multiplier=Decimal("0.8"))
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=4)
    await ModelProbe.create(channel_id=one.id, model="gpt-4o", actual_model="gpt-4o", kind="health",
                             status="healthy", actor_id=1)
    await ModelProbe.create(channel_id=two.id, model="gpt-4o", actual_model="gpt-4o", kind="health",
                             status="unavailable", actor_id=1)
    result = await client.get("/api/models", headers=auth_header(admin_token))
    model = result.json()["items"][0]
    assert model["health"] == "healthy" and model["pricing"]["prompt"] == 1.6 and model["pricing"]["completion"] == 3.2
    assert {entry["health"]["status"] for entry in model["channels"]} == {"healthy", "unavailable"}


async def test_model_health_rejects_hidden_or_foreign_models_and_tenants(client, admin_token):
    channel = await probe_channel()
    _, _, tenant_headers = await create_tenant_account()
    payload = {"channel_id": channel.id, "model": "gpt-4o"}
    assert (await client.post("/api/models/probe", json=payload, headers=tenant_headers)).status_code == 403
    assert (await client.post("/api/models/probe", json={**payload, "model": "foreign"}, headers=auth_header(admin_token))).status_code == 404
    assert (await client.post("/api/reconcile", headers=auth_header(admin_token))).status_code in (404, 405)


@pytest.mark.parametrize("value", [-1, 101, float("inf")])
async def test_price_multipliers_reject_invalid_values(client, admin_token, value):
    encoded = ('{"name":"bad","provider":"openai","base_url":"https://bad.example.com","price_multiplier":'
               + ("1e1000" if value == float("inf") else str(value)) + '}')
    result = await client.post("/api/channels", content=encoded, headers={
        **auth_header(admin_token), "Content-Type": "application/json"})
    assert result.status_code == 422


@pytest.mark.parametrize("url", ["http://public-example.com", "https://user:secret@vendor.com", "https://vendor.com?api_key=secret"])
async def test_public_upstreams_require_tls_and_no_url_credentials(client, admin_token, url):
    result = await client.post("/api/channels", json={"name": "insecure", "provider": "openai", "base_url": url},
                               headers=auth_header(admin_token))
    assert result.status_code == 422


async def test_probe_history_is_paged_and_filtered_by_kind(client, admin_token):
    channel = await probe_channel()
    for index in range(23):
        await ModelProbe.create(channel_id=channel.id, model="gpt-4o", actual_model="gpt-4o",
                                kind="capability" if index % 8 == 0 else "health",
                                status="healthy", actor_id=1)
    headers = auth_header(admin_token)
    params = {"channel_id": channel.id, "model": "gpt-4o"}
    first = (await client.get("/api/models/probes", params=params, headers=headers)).json()
    assert first["total"] == 23 and len(first["items"]) == 10
    last = (await client.get("/api/models/probes", params={**params, "page": 3}, headers=headers)).json()
    assert len(last["items"]) == 3
    seen = {item["id"] for item in first["items"]} | {item["id"] for item in last["items"]}
    assert len(seen) == 13
    capability = (await client.get("/api/models/probes", params={**params, "kind": "capability"},
                                   headers=headers)).json()
    assert capability["total"] == 3 and {item["kind"] for item in capability["items"]} == {"capability"}
    too_big = await client.get("/api/models/probes", params={**params, "size": 500}, headers=headers)
    assert too_big.status_code == 422
