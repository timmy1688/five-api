from decimal import Decimal

import pytest

from app.models import Admin, APIKey, Channel, ModelPrice
from app.services.auth import hash_password, create_access_token, hash_api_key
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


# ── auth ────────────────────────────────────────────────────

async def test_login_success(client):
    await Admin.create(username="logintest", hashed_password=hash_password("pass123"))
    resp = await client.post("/api/admin/login", json={"username": "logintest", "password": "pass123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


async def test_login_wrong_password(client):
    await Admin.create(username="loginwrong", hashed_password=hash_password("correct"))
    resp = await client.post("/api/admin/login", json={"username": "loginwrong", "password": "wrong"})
    assert resp.status_code == 401


async def test_login_nonexistent_user(client):
    resp = await client.post("/api/admin/login", json={"username": "nobody", "password": "pw"})
    assert resp.status_code == 401


async def test_me(client):
    admin = await Admin.create(username="metest", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    resp = await client.get("/api/admin/me", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["username"] == "metest"


async def test_me_invalid_token(client):
    resp = await client.get("/api/admin/me", headers=auth_header("invalid-token"))
    assert resp.status_code == 401


async def test_change_password(client):
    admin = await Admin.create(username="chpw", hashed_password=hash_password("old123"))
    token = create_access_token({"sub": admin.id})
    resp = await client.put(
        "/api/admin/password",
        json={"old_password": "old123", "new_password": "new456"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200


async def test_change_password_wrong_old(client):
    admin = await Admin.create(username="chpwbad", hashed_password=hash_password("old123"))
    token = create_access_token({"sub": admin.id})
    resp = await client.put(
        "/api/admin/password",
        json={"old_password": "wrong", "new_password": "new456"},
        headers=auth_header(token),
    )
    assert resp.status_code == 400


# ── channels ────────────────────────────────────────────────

async def test_channel_crud(client):
    admin = await Admin.create(username="chcrud", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    h = auth_header(token)

    # create
    resp = await client.post("/api/admin/channels", json={
        "name": "test-ch", "provider": "openai", "base_url": "https://api.openai.com",
        "api_key": "sk-up", "models": ["gpt-4o"], "model_pricing": {"gpt-4o": {"prompt": 2.5, "completion": 10.0}},
    }, headers=h)
    assert resp.status_code == 201
    ch_id = resp.json()["id"]

    # list
    resp = await client.get("/api/admin/channels", headers=h)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(c["id"] == ch_id for c in data["items"])

    # get
    resp = await client.get(f"/api/admin/channels/{ch_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-ch"
    assert resp.json()["model_pricing"]["gpt-4o"]["prompt"] == 2.5

    # update
    resp = await client.put(f"/api/admin/channels/{ch_id}", json={"name": "renamed"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"

    # delete
    resp = await client.delete(f"/api/admin/channels/{ch_id}", headers=h)
    assert resp.status_code == 200


async def test_channel_not_found(client):
    admin = await Admin.create(username="ch404", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    h = auth_header(token)
    resp = await client.get("/api/admin/channels/99999", headers=h)
    assert resp.status_code == 404


# ── api keys ────────────────────────────────────────────────

async def test_key_crud(client):
    admin = await Admin.create(username="keycrud", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    h = auth_header(token)

    # create
    resp = await client.post("/api/admin/keys", json={
        "name": "my-key", "quota_total": 50.0, "concurrent_limit": 3, "quota_reset_day": 15,
    }, headers=h)
    assert resp.status_code == 201
    data = resp.json()
    assert "key" in data
    assert data["key"].startswith("sk-")
    assert data["quota_total"] == 50.0
    assert data["quota_remaining"] == 50.0
    assert data["quota_reset_day"] == 15
    key_id = data["id"]

    # list
    resp = await client.get("/api/admin/keys", headers=h)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # get
    resp = await client.get(f"/api/admin/keys/{key_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "my-key"

    # update
    resp = await client.put(f"/api/admin/keys/{key_id}", json={"name": "renamed-key", "quota_reset_day": 1}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed-key"
    assert resp.json()["quota_reset_day"] == 1

    # reset quota
    resp = await client.post(f"/api/admin/keys/{key_id}/reset-quota", headers=h)
    assert resp.status_code == 200

    # delete
    resp = await client.delete(f"/api/admin/keys/{key_id}", headers=h)
    assert resp.status_code == 200


async def test_key_unlimited_remaining(client):
    admin = await Admin.create(username="keyunlim", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    h = auth_header(token)
    resp = await client.post("/api/admin/keys", json={"name": "unlim", "quota_total": -1}, headers=h)
    assert resp.status_code == 201
    assert resp.json()["quota_remaining"] == -1.0


# ── model prices ────────────────────────────────────────────

async def test_model_price_crud(client):
    admin = await Admin.create(username="mpcrud", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    h = auth_header(token)

    # create
    resp = await client.post("/api/admin/model-prices", json={
        "model": "test-model", "prompt_price": 3.0, "completion_price": 15.0,
    }, headers=h)
    assert resp.status_code == 201
    mp_id = resp.json()["id"]

    # list
    resp = await client.get("/api/admin/model-prices", headers=h)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # get
    resp = await client.get(f"/api/admin/model-prices/{mp_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["model"] == "test-model"

    # update
    resp = await client.put(f"/api/admin/model-prices/{mp_id}", json={"prompt_price": 5.0}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["prompt_price"] == 5.0

    # duplicate model
    resp = await client.post("/api/admin/model-prices", json={
        "model": "test-model", "prompt_price": 1.0, "completion_price": 1.0,
    }, headers=h)
    assert resp.status_code == 409

    # delete
    resp = await client.delete(f"/api/admin/model-prices/{mp_id}", headers=h)
    assert resp.status_code == 200


# ── logs ────────────────────────────────────────────────────

async def test_logs_list(client):
    admin = await Admin.create(username="logtest", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    h = auth_header(token)

    from app.models import RequestLog
    await RequestLog.create(
        request_id="log-001", api_key_id=1, api_key_name="k",
        channel_id=1, channel_name="ch", model_requested="gpt-4o",
        model_actual="gpt-4o", provider="openai",
        endpoint="/v1/chat/completions",
        prompt_tokens=100, completion_tokens=50, total_tokens=150,
        cost=Decimal("0.001"), is_stream=False, status_code=200, latency_ms=200,
    )
    resp = await client.get("/api/admin/logs", headers=h)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert "cost" in data["items"][0]


async def test_logs_get_by_request_id(client):
    admin = await Admin.create(username="logget", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    h = auth_header(token)

    from app.models import RequestLog
    await RequestLog.create(
        request_id="log-detail-001", api_key_id=1, api_key_name="k",
        channel_id=1, channel_name="ch", model_requested="gpt-4o",
        model_actual="gpt-4o", provider="openai",
        endpoint="/v1/chat/completions",
        prompt_tokens=50, completion_tokens=25, total_tokens=75,
        cost=Decimal("0.0005"), is_stream=False, status_code=200, latency_ms=100,
    )
    resp = await client.get("/api/admin/logs/log-detail-001", headers=h)
    assert resp.status_code == 200
    assert resp.json()["request_id"] == "log-detail-001"


async def test_logs_not_found(client):
    admin = await Admin.create(username="log404", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    resp = await client.get("/api/admin/logs/nonexistent", headers=auth_header(token))
    assert resp.status_code == 404


# ── stats ───────────────────────────────────────────────────

async def test_stats_overview(client):
    admin = await Admin.create(username="statov", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    resp = await client.get("/api/admin/stats/overview", headers=auth_header(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_requests" in data
    assert "total_cost" in data
    assert "cost_today" in data


async def test_stats_usage(client):
    admin = await Admin.create(username="statu", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    resp = await client.get("/api/admin/stats/usage?days=7", headers=auth_header(token))
    assert resp.status_code == 200


async def test_stats_by_model(client):
    admin = await Admin.create(username="statm", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    resp = await client.get("/api/admin/stats/by-model?days=7", headers=auth_header(token))
    assert resp.status_code == 200


async def test_stats_by_key(client):
    admin = await Admin.create(username="statk", hashed_password=hash_password("pw"))
    token = create_access_token({"sub": admin.id})
    resp = await client.get("/api/admin/stats/by-key?days=7", headers=auth_header(token))
    assert resp.status_code == 200


# ── unauthenticated access ──────────────────────────────────

async def test_admin_endpoints_require_auth(client):
    endpoints = [
        ("GET", "/api/admin/channels"),
        ("GET", "/api/admin/keys"),
        ("GET", "/api/admin/logs"),
        ("GET", "/api/admin/model-prices"),
        ("GET", "/api/admin/stats/overview"),
    ]
    for method, path in endpoints:
        resp = await client.request(method, path)
        assert resp.status_code in (401, 403), f"{method} {path} should require auth"
