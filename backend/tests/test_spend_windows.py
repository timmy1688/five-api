from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel, ModelPrice, Team
from app.services.auth import hash_api_key
from app.services.spend_windows import normalize_limits
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio

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
    team = await Team.create(name="w-team", window_limits=team_limits or {}) if team_limits else None
    return await APIKey.create(
        name="w-key", key_hash=hash_api_key(RAW_KEY), key_prefix=RAW_KEY[:8],
        quota_total=Decimal("-1"), window_limits=key_limits or {},
        team_id=team.id if team else None,
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

    await client.post(f"/api/keys/{key.id}/reset-quota", headers=auth_header(admin_token))
    with patch("app.providers.base._shared_http_client", return_value=_http()):
        assert (await _call(client)).status_code == 200


async def test_team_window_blocks_every_key(client, admin_token):
    _, team = await _env(team_limits={"1d": 1})
    with patch("app.providers.base._shared_http_client", return_value=_http()):
        assert (await _call(client)).status_code == 200
        blocked = await _call(client)
    assert blocked.status_code == 429
    assert "team_window_limit" in blocked.text
    shown = await client.get(f"/api/teams/{team.id}", headers=auth_header(admin_token))
    assert shown.json()["window_spend"]["1d"] == 1.0


async def test_key_form_round_trips_windows(client, admin_token):
    created = await client.post(
        "/api/keys", json={"name": "wk", "window_limits": {"7d": 20, "5h": ""}},
        headers=auth_header(admin_token),
    )
    assert created.json()["window_limits"] == {"7d": 20.0}
    key_id = created.json()["id"]
    updated = await client.put(
        f"/api/keys/{key_id}", json={"window_limits": {}}, headers=auth_header(admin_token),
    )
    assert updated.json()["window_limits"] == {}
