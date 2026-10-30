from tests.conftest import create_test_tenant
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx

from app.models import APIKey, Channel, ModelPrice, Tenant
from app.services.auth import hash_api_key
from app.services.spend_windows import normalize_limits
from tests.conftest import auth_header


RAW_KEY = "sk-window-client-key"
OK = {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 0}}


def _http():
    http = AsyncMock()
    http.is_closed = False
    http.post = AsyncMock(side_effect=lambda *a, **k: httpx.Response(
        200, json=OK, request=httpx.Request("POST", "https://api.openai.test/v1/chat/completions"),
    ))
    return http


async def _call(client):
    return await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers=auth_header(RAW_KEY),
    )


async def _env(key_limits=None, team_limits=None):
    await Channel.create(
        name="w", provider="openai", base_url="https://api.openai.test",
        api_key="sk-up", models=["gpt-4o"], timeout=60,
    )
    await ModelPrice.create(model="gpt-4o", prompt_price=Decimal("1000000"), completion_price=Decimal("0"))
    team = await Tenant.create(quota_total=Decimal("-1"), name="w-team", window_limits=team_limits or {}) if team_limits else None
    return await APIKey.create(
        name="w-key", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8],
        quota_total=Decimal("-1"), window_limits=key_limits or {},
        tenant_id=team.id if team else (await create_test_tenant()).id,
    ), team


def test_normalize_limits():
    assert normalize_limits({"5h": "2.5", "1d": None, "7d": -1, "1y": 9}) == {"5h": 2.5}
    assert normalize_limits(None) == {}


async def test_key_window_blocks_after_cap_and_reset_clears(client, admin_token):
    key, _ = await _env(key_limits={"5h": 0.5})
    with patch("app.providers.base._shared_http_client", return_value=_http()):
        assert (await _call(client)).status_code == 200
        blocked = await _call(client)
    assert blocked.status_code == 429
    assert "window_limit" in blocked.text and "5h" in blocked.text

    listed = await client.get(f"/api/keys/{key.id}", headers=auth_header(admin_token))
    assert listed.json()["window_spend"]["5h"] == 1.0
    assert listed.json()["window_limits"] == {"5h": 0.5}

    response = await client.post(f"/api/keys/{key.id}/reset-quota", headers=auth_header(admin_token))
    assert response.status_code == 405
    with patch("app.providers.base._shared_http_client", return_value=_http()):
        assert (await _call(client)).status_code == 429


async def test_team_window_blocks_every_key(client, admin_token):
    _, team = await _env(team_limits={"1d": 1})
    with patch("app.providers.base._shared_http_client", return_value=_http()):
        assert (await _call(client)).status_code == 200
        blocked = await _call(client)
    assert blocked.status_code == 429
    assert "tenant_window_limit" in blocked.text
    shown = await client.get(f"/api/tenants/{team.id}", headers=auth_header(admin_token))
    assert shown.json()["window_spend"]["1d"] == 1.0


async def test_key_form_round_trips_windows(client, admin_token):
    key, _ = await _env()
    created = await client.put(
        f"/api/keys/{key.id}", json={"window_limits": {"7d": 20, "5h": ""}},
        headers=auth_header(admin_token),
    )
    assert created.json()["window_limits"] == {"7d": 20.0}
    key_id = created.json()["id"]
    updated = await client.put(
        f"/api/keys/{key_id}", json={"window_limits": {}}, headers=auth_header(admin_token),
    )
    assert updated.json()["window_limits"] == {}


async def test_budget_downgrade_switches_model_past_threshold(client):
    await ModelPrice.create(model="big-model")
    await ModelPrice.create(model="small-model")
    from app.models import RequestLog
    from app.services.settings_service import clear_settings_cache, set_gateway_config

    await Channel.create(
        name="big", provider="openai", base_url="https://api.openai.test",
        api_key="sk-up", models=["big-model", "small-model"], timeout=60,
    )
    key = await APIKey.create(tenant_id=(await create_test_tenant()).id,
        name="d-key", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8],
        quota_total=Decimal("10"), quota_used=Decimal("7"),
    )
    await set_gateway_config({"budget_downgrade": {"threshold": 0.8, "rules": {"big-model": "small-model"}}})
    body = {"model": "big-model", "messages": [{"role": "user", "content": "hi"}]}

    http = _http()
    with patch("app.providers.base._shared_http_client", return_value=http):
        calm = await client.post("/v1/chat/completions", json=body, headers=auth_header(RAW_KEY))
        assert calm.status_code == 200 and "x-five-downgraded-to" not in calm.headers
        await APIKey.filter(id=key.id).update(quota_used=Decimal("8.5"))
        hot = await client.post("/v1/chat/completions", json=body, headers=auth_header(RAW_KEY))
    clear_settings_cache()
    assert hot.status_code == 200
    assert hot.headers["x-five-downgraded-to"] == "small-model"
    assert [c.kwargs["json"]["model"] for c in http.post.await_args_list] == ["big-model", "small-model"]
    last = await RequestLog.all().order_by("-id").first()
    assert (last.model_requested, last.model_actual) == ("big-model", "small-model")
