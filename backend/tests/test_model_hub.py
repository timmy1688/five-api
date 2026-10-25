import json
import re
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from app.models import Channel, ManagementEvent, ModelPrice, ModelProbe, RequestLog, Settlement
from app.services import settlements
from app.services.billing_quotes import selling_quote
from app.services.quota import begin_request_budget
from tests.conftest import auth_header, create_tenant_account
from tests.test_billing_reliability import BODY, MODEL, env, upstream, response

pytestmark = pytest.mark.asyncio


async def test_price_multipliers_are_snapshotted_and_upstream_discount_is_independent(client):
    _, keys, channel = await env()
    await ModelPrice.filter(model=MODEL).update(multiplier=Decimal("0.5"))
    await Channel.filter(id=channel.id).update(cost_multiplier=Decimal("0.2"))
    async def send(*args, **kwargs):
        await ModelPrice.filter(model=MODEL).update(multiplier=7)
        await Channel.filter(id=channel.id).update(cost_multiplier=7)
        return response()
    with patch("app.providers.base._shared_http_client", return_value=upstream(send)):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 200
    log = await RequestLog.get()
    assert log.cost == Decimal("0.000175") and log.upstream_cost == Decimal("0.000400")
    assert log.cost_detail["multiplier"] == "0.5"
    assert Decimal(log.cost_detail["upstream"]["multiplier"]) == Decimal("0.2")


async def test_selling_multiplier_is_included_in_sufficient_reservation(client):
    _, keys, _ = await env(quota="0.00005")
    await ModelPrice.filter(model=MODEL).update(multiplier=10)
    http = upstream()
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/v1/chat/completions", json=BODY, headers=auth_header(keys[0][1]))
    assert result.status_code == 429
    http.post.assert_not_awaited()


async def test_explicit_free_multiplier_and_alias_quote():
    await ModelPrice.create(model="friendly-alias", prompt_price=999, multiplier=0)
    quote = await selling_quote("gpt-4o", "friendly-alias")
    assert quote["source"] == "global" and quote["multiplier"] == "0"


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


async def test_bulk_price_import_never_overwrites_user_prices_or_multipliers(client, admin_token):
    row = await ModelPrice.create(model="gpt-4o", prompt_price=99, multiplier=Decimal("0.65"), is_active=False)
    headers = auth_header(admin_token)
    for query in ("", "?overwrite=true"):
        result = await client.post("/api/model-prices/sync-defaults" + query, headers=headers)
        assert result.status_code == 200 and result.json()["updated"] == 0
    await row.refresh_from_db()
    assert row.prompt_price == 99 and row.multiplier == Decimal("0.65") and not row.is_active


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
    two = await Channel.create(name="other", provider="openai", base_url="https://other.test", api_key="", models=["gpt-4o"])
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=4, multiplier=Decimal("0.8"))
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
    encoded = '{"model":"bad","multiplier":' + ("1e1000" if value == float("inf") else str(value)) + '}'
    result = await client.post("/api/model-prices", content=encoded, headers={
        **auth_header(admin_token), "Content-Type": "application/json"})
    assert result.status_code == 422


@pytest.mark.parametrize("url", ["http://public-example.com", "https://user:secret@vendor.com", "https://vendor.com?api_key=secret"])
async def test_public_upstreams_require_tls_and_no_url_credentials(client, admin_token, url):
    result = await client.post("/api/channels", json={"name": "insecure", "provider": "openai", "base_url": url},
                               headers=auth_header(admin_token))
    assert result.status_code == 422
