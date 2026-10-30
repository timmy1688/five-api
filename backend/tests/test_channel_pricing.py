"""Per-channel customer prices and API keys bound to chosen channels."""
import re
import sqlite3
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel, ModelPrice, RequestLog, Settlement
from app.services import settlements
from app.services.auth import hash_api_key
from tests.conftest import auth_header, create_tenant_account, create_test_tenant

pytestmark = pytest.mark.asyncio
RAW_KEY = "sk-channel-pricing-key"
CHAT = {"model": "gpt-4o", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]}
USAGE = {"prompt_tokens": 1000, "completion_tokens": 1000}


async def _channel(name, **extra):
    return await Channel.create(name=name, provider="openai", base_url=f"https://{name}.example.com",
                                api_key=f"{name}-upstream-secret", models=["gpt-4o"], timeout=30, **extra)


async def _key(channel_ids=(), tenant=None):
    tenant = tenant or await create_test_tenant()
    return await APIKey.create(tenant_id=tenant.id, name="bound", key_hash=hash_api_key(RAW_KEY),
                               key_prefix=RAW_KEY[:8], quota_total=Decimal("-1"), channel_ids=list(channel_ids))


def _served_by(kwargs) -> str:
    return kwargs["headers"]["Authorization"].removeprefix("Bearer ").removesuffix("-upstream-secret")


def _upstream(failing=()):
    """Answers by channel; channels named in failing return a retryable 503."""
    def reply(url, **kwargs):
        status = 503 if _served_by(kwargs) in failing else 200
        body = {"error": {"message": "down"}} if status == 503 else {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": USAGE}
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(side_effect=reply)
    return http


def _hosts(http):
    return [_served_by(call.kwargs) for call in http.post.await_args_list]


async def test_request_is_billed_at_the_serving_channels_multiplier(client):
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=8)
    dear = await _channel("dear", price_multiplier=Decimal("1.5"))
    await _key([dear.id])
    http = _upstream()
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert result.status_code == 200
    log = await RequestLog.get()
    # (1000 x $2 + 1000 x $8) / 1M x 1.5
    assert log.cost == Decimal("0.015") and log.channel_id == dear.id
    assert log.cost_detail["prices"]["input"] == "2" and Decimal(log.cost_detail["multiplier"]) == Decimal("1.5")


async def test_channel_fixed_price_wins_over_model_price_and_multiplier(client):
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=8)
    fixed = await _channel("fixed", price_multiplier=Decimal("3"),
                           price_overrides={"gpt-4o": {"prompt": 1, "completion": 1, "request": 0.01}})
    await _key([fixed.id])
    with patch("app.providers.base._shared_http_client", return_value=_upstream()):
        result = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert result.status_code == 200
    log = await RequestLog.get()
    assert log.cost == Decimal("0.002") and log.cost_detail["price_source"] == "channel"


async def test_failover_stays_inside_the_keys_channels_and_bills_the_one_that_served(client):
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=8)
    first = await _channel("first", priority=30)
    second = await _channel("second", priority=20, price_multiplier=Decimal("2"))
    await _channel("outside", priority=10, price_multiplier=Decimal("0.1"))
    await _key([first.id, second.id])
    http = _upstream(failing={"first"})
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert result.status_code == 200
    assert "outside" not in _hosts(http) and _hosts(http)[-1] == "second"
    log = await RequestLog.filter(status_code=200).get()
    assert log.channel_id == second.id and log.cost == Decimal("0.02")


async def test_failure_of_every_chosen_channel_never_falls_back_outside(client):
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=8)
    only = await _channel("only", priority=1)
    await _channel("spare", priority=0)
    await _key([only.id])
    http = _upstream(failing={"only"})
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert result.status_code >= 500
    assert set(_hosts(http)) == {"only"}
    assert await Settlement.filter(state__in=("reserved", "pending")).count() == 0


async def test_disabled_bound_channel_returns_explicit_error(client):
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=8)
    gone = await _channel("gone", is_enabled=False)
    await _channel("other")
    await _key([gone.id])
    http = _upstream()
    with patch("app.providers.base._shared_http_client", return_value=http):
        result = await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))
    assert result.status_code == 404
    assert "selected for this API key" in result.json()["error"]["message"]
    http.post.assert_not_awaited()


async def test_reservation_covers_the_dearest_candidate(client):
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=8)
    cheap = await _channel("cheap", priority=10)
    dear = await _channel("dear", priority=0, price_multiplier=Decimal("4"))
    key = await _key([cheap.id, dear.id])
    holds = []
    original = settlements.reserve

    async def capture(request_id, api_key, amount, quotes):
        holds.append((amount, quotes))
        return await original(request_id, api_key, amount, quotes)

    with patch("app.providers.base._shared_http_client", return_value=_upstream()), \
            patch.object(settlements, "reserve", capture):
        assert (await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))).status_code == 200
        await APIKey.filter(id=key.id).update(channel_ids=[cheap.id])
        assert (await client.post("/v1/chat/completions", json=CHAT, headers=auth_header(RAW_KEY))).status_code == 200
    (both, quotes), (cheap_only, _) = holds
    assert set(quotes) == {f"{cheap.id}:gpt-4o", f"{dear.id}:gpt-4o"}
    # The hold is sized for the dear channel even though the cheap one serves first.
    assert 4 * cheap_only - Decimal("0.000004") <= both <= 4 * cheap_only
    logs = await RequestLog.all()
    assert {log.channel_id for log in logs} == {cheap.id} and {log.cost for log in logs} == {Decimal("0.01")}


async def test_tenant_sees_safe_channel_list_and_can_only_bind_selectable_channels(client):
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=8)
    tenant, _, headers = await create_tenant_account()
    tenant.allowed_models = ["gpt-4o"]
    await tenant.save()
    shown = await _channel("shown", price_multiplier=Decimal("1.2"),
                           price_overrides={"gpt-4o": {"prompt": 1, "completion": 3}})
    disabled = await _channel("disabled", is_enabled=False)
    foreign = await Channel.create(name="foreign", provider="openai", base_url="https://foreign.example.com",
                                   api_key="upstream-secret", models=["other-model"])

    listing = await client.get("/api/keys/channels", headers=headers)
    assert listing.status_code == 200
    assert [item["name"] for item in listing.json()] == ["shown"]
    item = listing.json()[0]
    assert item["price_multiplier"] == 1.2 and item["healthy"] is True
    assert item["models"] == [{"model": "gpt-4o", "fixed_price": True, "prices": {
        "prompt": 1.0, "completion": 3.0, "cached": 0.0, "cache_write": 1.0, "request": 0.0}}]
    assert "example.com" not in listing.text and "upstream-secret" not in listing.text

    for bad in ([disabled.id], [foreign.id], [999999]):
        rejected = await client.post("/api/keys", json={"name": "k", "channel_ids": bad}, headers=headers)
        assert rejected.status_code == 422, bad
    created = await client.post("/api/keys", json={"name": "k", "channel_ids": [shown.id, shown.id]}, headers=headers)
    assert created.status_code == 201 and created.json()["channel_ids"] == [shown.id]
    key_id = created.json()["id"]
    moved = await client.put(f"/api/keys/{key_id}", json={"channel_ids": [disabled.id]}, headers=headers)
    assert moved.status_code == 422
    cleared = await client.put(f"/api/keys/{key_id}", json={"channel_ids": []}, headers=headers)
    assert cleared.status_code == 200 and cleared.json()["channel_ids"] == []
    other = await client.get("/api/keys/channels", params={"tenant_id": tenant.id + 1}, headers=headers)
    assert other.status_code == 403


async def test_channel_selected_by_a_live_key_cannot_be_deleted(client, admin_token):
    bound = await _channel("bound")
    key = await _key([bound.id])
    headers = auth_header(admin_token)
    blocked = await client.delete(f"/api/channels/{bound.id}", headers=headers)
    assert blocked.status_code == 409 and "bound" in blocked.json()["detail"]
    await APIKey.filter(id=key.id).update(is_revoked=True, is_enabled=False)
    assert (await client.delete(f"/api/channels/{bound.id}", headers=headers)).status_code == 200


async def test_me_and_models_follow_the_keys_channels(client):
    await ModelPrice.create(model="gpt-4o", prompt_price=2, completion_price=8)
    cheap = await _channel("cheap", price_multiplier=Decimal("0.5"))
    dear = await _channel("dear", price_multiplier=Decimal("2"))
    await Channel.create(name="hidden", provider="openai", base_url="https://hidden.example.com",
                         api_key="", models=["gpt-4o", "hidden-model"])
    await _key([cheap.id, dear.id])

    me = (await client.get("/v1/me", headers=auth_header(RAW_KEY))).json()
    assert me["channel_ids"] == [cheap.id, dear.id] and me["models"] == ["gpt-4o"]
    price = me["model_prices"]["gpt-4o"]
    assert price["prompt"] == 4.0 and price["varies_by_route"] is True
    assert {entry["channel_name"]: entry["prompt"] for entry in price["channels"]} == {"cheap": 1.0, "dear": 4.0}
    models = (await client.get("/v1/models", headers=auth_header(RAW_KEY))).json()
    assert [item["id"] for item in models["data"]] == ["gpt-4o"]


async def test_pending_settlement_from_older_release_still_settles():
    tenant = await create_test_tenant()
    key = await _key(tenant=tenant)
    payload = {"request_id": "legacy-pending", "api_key_id": key.id, "api_key_name": key.name,
               "tenant_id": tenant.id, "channel_id": None, "channel_name": "", "model_requested": "gpt-4o",
               "model_actual": "gpt-4o", "provider": "", "endpoint": "/v1/chat/completions",
               "prompt_tokens": 10, "completion_tokens": 10, "status_code": 200,
               "cost": "0.5", "upstream_cost": "0.2", "cache_savings": "0"}
    await Settlement.create(request_id="legacy-pending", tenant_id=tenant.id, api_key_id=key.id,
                            state="pending", occupied=Decimal("0.5"), cost=Decimal("0.5"), payload=payload)
    assert await settlements.apply("legacy-pending") is True
    assert (await RequestLog.get(request_id="legacy-pending")).cost == Decimal("0.5")
    await key.refresh_from_db()
    assert key.quota_used == Decimal("0.5")


def _migration_sql(direction: str) -> str:
    path = next(Path(__file__).parents[1].glob("migrations/models/24_*_channel_selling_price.py"))
    source = path.read_text()
    body = source.split(f"async def {direction}(")[1]
    return re.search(r'return """(.*?)"""', body, re.S).group(1)


def test_migration_folds_model_multiplier_so_charges_do_not_change():
    sql = _migration_sql("upgrade")
    fold = sql.split("ALTER TABLE")[0].replace("`", '"')
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE model_prices (model TEXT, prompt_price NUMERIC, completion_price NUMERIC, "
               "cached_price NUMERIC, cache_write_price NUMERIC, request_price NUMERIC, multiplier NUMERIC)")
    rows = [("half", "3", "15", "0.3", "3.75", "0.04", "0.5"),
            ("same", "2.5", "10", "1.25", "2.5", "0", "1"),
            ("odd", "0.123457", "1", "0", "0", "0", "1.3333")]
    db.executemany("INSERT INTO model_prices VALUES (?,?,?,?,?,?,?)", rows)
    before = {model: [Decimal(v) * Decimal(m) for v in values] for model, *values, m in rows}
    db.executescript(fold)
    after = {model: [Decimal(str(v)) for v in values]
             for model, *values in db.execute("SELECT model, prompt_price, completion_price, cached_price, "
                                              "cache_write_price, request_price FROM model_prices")}
    for model, prices in before.items():
        assert after[model] == [p.quantize(Decimal("0.000001")) for p in prices], model
    assert "RENAME" not in sql.upper() and "cost_multiplier` DECIMAL" not in sql
    assert sql.index("UPDATE `model_prices`") < sql.index("DROP COLUMN `multiplier`")
