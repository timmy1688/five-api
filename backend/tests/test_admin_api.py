from decimal import Decimal

import pytest
import respx
from httpx import Response

from app.models import APIKey, Channel, ModelGroup, ModelPrice, Role, User
from app.services.auth import create_access_token, hash_api_key, hash_password
from tests.conftest import auth_header, create_admin

pytestmark = pytest.mark.asyncio


# ── auth ────────────────────────────────────────────────────

async def test_login_success(client):
    await create_admin("logintest", "pass123")
    resp = await client.post("/api/login", json={"username": "logintest", "password": "pass123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


async def test_login_wrong_password(client):
    await create_admin("loginwrong", "correct")
    resp = await client.post("/api/login", json={"username": "loginwrong", "password": "wrong"})
    assert resp.status_code == 401


async def test_login_nonexistent_user(client):
    resp = await client.post("/api/login", json={"username": "nobody", "password": "pw"})
    assert resp.status_code == 401


async def test_me(client):
    admin = await create_admin("metest", "pw")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.get("/api/me", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["username"] == "metest"


async def test_me_invalid_token(client):
    resp = await client.get("/api/me", headers=auth_header("invalid-token"))
    assert resp.status_code == 401


async def test_change_password(client):
    admin = await create_admin("chpw", "old123")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.put(
        "/api/password",
        json={"old_password": "old123", "new_password": "new456"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200


async def test_change_password_wrong_old(client):
    admin = await create_admin("chpwbad", "old123")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.put(
        "/api/password",
        json={"old_password": "wrong", "new_password": "new456"},
        headers=auth_header(token),
    )
    assert resp.status_code == 400


# ── channels ────────────────────────────────────────────────

async def test_channel_crud(client):
    admin = await create_admin("chcrud", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)

    # create
    resp = await client.post("/api/channels", json={
        "name": "test-ch", "provider": "openai", "base_url": "https://api.openai.com",
        "api_key": "sk-up", "models": ["gpt-4o"], "model_pricing": {"gpt-4o": {"prompt": 2.5, "completion": 10.0}},
    }, headers=h)
    assert resp.status_code == 201
    created = resp.json()
    ch_id = created["id"]
    assert "sk-up" not in created["api_key"]
    stored = await Channel.get(id=ch_id)
    assert stored.api_key.startswith("fernet:")

    # list
    resp = await client.get("/api/channels", headers=h)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(c["id"] == ch_id for c in data["items"])

    # get
    resp = await client.get(f"/api/channels/{ch_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-ch"
    assert resp.json()["model_pricing"]["gpt-4o"]["prompt"] == 2.5

    # update
    resp = await client.put(f"/api/channels/{ch_id}", json={"name": "renamed"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"

    # delete
    resp = await client.delete(f"/api/channels/{ch_id}", headers=h)
    assert resp.status_code == 200


async def test_channel_not_found(client):
    admin = await create_admin("ch404", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)
    resp = await client.get("/api/channels/99999", headers=h)
    assert resp.status_code == 404


async def test_self_hosted_openai_channel_does_not_require_api_key(client):
    admin = await create_admin("vllmadmin", "pw")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.post(
        "/api/channels",
        json={
            "name": "local-vllm",
            "provider": "openai",
            "base_url": "http://127.0.0.1:8000/v1",
            "models": ["local-model"],
        },
        headers=auth_header(token),
    )
    assert resp.status_code == 201
    assert resp.json()["api_key"] == ""


@respx.mock
async def test_self_hosted_model_discovery_without_auth_header(client):
    admin = await create_admin("vllmmodels", "pw")
    token = create_access_token({"sub": str(admin.id)})
    upstream = respx.get("http://vllm.test:8000/v1/models").mock(
        return_value=Response(
            200,
            json={"object": "list", "data": [{"id": "local-model"}]},
        )
    )
    resp = await client.post(
        "/api/channels/fetch-models-preview",
        json={
            "provider": "openai",
            "base_url": "http://vllm.test:8000/v1",
            "api_key": "",
        },
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json() == {"models": ["local-model"]}
    assert "authorization" not in upstream.calls[0].request.headers


# ── api keys ────────────────────────────────────────────────

async def test_key_crud(client):
    admin = await create_admin("keycrud", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)

    # create
    resp = await client.post("/api/keys", json={
        "name": "my-key", "quota_total": 50.0, "concurrent_limit": 3, "quota_reset_day": 15,
    }, headers=h)
    assert resp.status_code == 201
    data = resp.json()
    assert "key" in data
    assert data["key"].startswith("sk-")
    assert "key_raw" not in data
    assert data["quota_total"] == 50.0
    assert data["quota_remaining"] == 50.0
    assert data["quota_reset_day"] == 15
    assert data["quota_last_reset_at"] is not None
    key_id = data["id"]

    # list
    resp = await client.get("/api/keys", headers=h)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert "key_raw" not in resp.json()["items"][0]

    # get
    resp = await client.get(f"/api/keys/{key_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "my-key"

    # update
    resp = await client.put(f"/api/keys/{key_id}", json={"name": "renamed-key", "quota_reset_day": 1}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed-key"
    assert resp.json()["quota_reset_day"] == 1

    # reset quota
    resp = await client.post(f"/api/keys/{key_id}/reset-quota", headers=h)
    assert resp.status_code == 200

    # delete
    resp = await client.delete(f"/api/keys/{key_id}", headers=h)
    assert resp.status_code == 200


async def test_key_unlimited_remaining(client):
    admin = await create_admin("keyunlim", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)
    resp = await client.post("/api/keys", json={"name": "unlim", "quota_total": -1}, headers=h)
    assert resp.status_code == 201
    assert resp.json()["quota_remaining"] == -1.0


async def test_invalid_numeric_configuration_is_rejected(client):
    admin = await create_admin("validation", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)

    key_resp = await client.post(
        "/api/keys",
        json={"name": "bad-limit", "concurrent_limit": 0},
        headers=h,
    )
    price_resp = await client.post(
        "/api/model-prices",
        json={
            "model": "bad-price",
            "prompt_price": -1,
            "completion_price": 1,
        },
        headers=h,
    )
    channel_resp = await client.post(
        "/api/channels",
        json={
            "name": "bad-channel-price",
            "provider": "openai",
            "base_url": "https://example.test",
            "models": ["test-model"],
            "model_pricing": {
                "test-model": {"prompt": -0.1, "completion": 1}
            },
        },
        headers=h,
    )

    assert key_resp.status_code == 422
    assert price_resp.status_code == 422
    assert channel_resp.status_code == 422


# ── access safeguards ───────────────────────────────────────

async def test_assigned_model_group_cannot_be_deleted(client):
    admin = await create_admin("groupguard", "pw")
    token = create_access_token({"sub": str(admin.id)})
    group = await ModelGroup.create(name="assigned", models=["gpt-4o"])
    raw_key = "sk-groupguard123"
    await APIKey.create(
        name="group-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        model_group_id=group.id,
    )

    resp = await client.delete(
        f"/api/model-groups/{group.id}",
        headers=auth_header(token),
    )
    assert resp.status_code == 409
    assert await ModelGroup.exists(id=group.id)


async def test_admin_cannot_disable_or_delete_self(client):
    admin = await create_admin("selfguard", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)

    disable = await client.put(
        f"/api/users/{admin.id}",
        json={"is_active": False},
        headers=h,
    )
    delete = await client.delete(f"/api/users/{admin.id}", headers=h)

    assert disable.status_code == 400
    assert delete.status_code == 400


async def test_last_super_admin_cannot_be_deleted_by_manager(client):
    manager_role = await Role.create(
        name="Admin Manager",
        permissions=["user:read", "user:write"],
    )
    manager = await User.create(
        username="manager",
        hashed_password=hash_password("pw"),
        role=manager_role,
    )
    super_admin = await create_admin("onlysuper", "pw")
    token = create_access_token({"sub": str(manager.id)})

    resp = await client.delete(
        f"/api/users/{super_admin.id}",
        headers=auth_header(token),
    )
    assert resp.status_code == 409
    assert await User.exists(id=super_admin.id)


# ── model prices ────────────────────────────────────────────

async def test_model_price_crud(client):
    admin = await create_admin("mpcrud", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)

    # create
    resp = await client.post("/api/model-prices", json={
        "model": "test-model", "prompt_price": 3.0, "completion_price": 15.0,
    }, headers=h)
    assert resp.status_code == 201
    mp_id = resp.json()["id"]

    # list
    resp = await client.get("/api/model-prices", headers=h)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # get
    resp = await client.get(f"/api/model-prices/{mp_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["model"] == "test-model"

    # update
    resp = await client.put(f"/api/model-prices/{mp_id}", json={"prompt_price": 5.0}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["prompt_price"] == 5.0

    # duplicate model
    resp = await client.post("/api/model-prices", json={
        "model": "test-model", "prompt_price": 1.0, "completion_price": 1.0,
    }, headers=h)
    assert resp.status_code == 409

    # delete
    resp = await client.delete(f"/api/model-prices/{mp_id}", headers=h)
    assert resp.status_code == 200


async def test_model_price_sync_updates_only_builtin_prices(client):
    admin = await create_admin("mpsync", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)

    builtin = await ModelPrice.create(
        model="gpt-5-nano",
        prompt_price=999,
        completion_price=999,
        is_active=False,
    )
    custom = await ModelPrice.create(
        model="local-vllm-model",
        prompt_price=0.25,
        completion_price=0.5,
    )

    # Safe default only imports missing rows.
    resp = await client.post("/api/model-prices/sync-defaults", headers=h)
    assert resp.status_code == 200
    assert resp.json()["updated"] == 0
    await builtin.refresh_from_db()
    assert builtin.prompt_price == Decimal("999")

    # Explicit overwrite refreshes built-ins without touching custom rows/status.
    resp = await client.post(
        "/api/model-prices/sync-defaults?overwrite=true", headers=h
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["catalog_version"] == "2026-07-25"
    assert data["updated"] == 1
    assert data["total"] >= 70

    await builtin.refresh_from_db()
    await custom.refresh_from_db()
    assert builtin.prompt_price == Decimal("0.05")
    assert builtin.completion_price == Decimal("0.4")
    assert builtin.is_active is False
    assert custom.prompt_price == Decimal("0.25")


async def test_models_show_channel_specific_price_variants(client):
    admin = await create_admin("modelprices", "pw")
    token = create_access_token({"sub": str(admin.id)})
    await ModelPrice.create(
        model="shared-model",
        prompt_price=1,
        completion_price=2,
    )
    await Channel.create(
        name="global-price-channel",
        provider="openai",
        base_url="https://one.test",
        api_key="",
        models=["shared-model"],
    )
    await Channel.create(
        name="override-price-channel",
        provider="openai",
        base_url="https://two.test",
        api_key="",
        models=["shared-model"],
        model_pricing={
            "shared-model": {"prompt": 3, "completion": 4, "cached": 0}
        },
    )

    resp = await client.get(
        "/api/models",
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    model = next(
        item for item in resp.json()["items"]
        if item["model"] == "shared-model"
    )
    assert model["pricing"] is None
    assert model["pricing_varies"] is True
    assert {channel["pricing_source"] for channel in model["channels"]} == {
        "global",
        "channel",
    }


# ── logs ────────────────────────────────────────────────────

async def test_logs_list(client):
    admin = await create_admin("logtest", "pw")
    token = create_access_token({"sub": str(admin.id)})
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
    resp = await client.get("/api/logs", headers=h)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert "cost" in data["items"][0]


async def test_logs_filter_by_partial_key_name(client):
    admin = await create_admin("logfilter", "pw")
    token = create_access_token({"sub": str(admin.id)})
    h = auth_header(token)

    from app.models import RequestLog
    common = {
        "api_key_id": 1,
        "channel_id": 1,
        "channel_name": "ch",
        "model_requested": "gpt-4o",
        "model_actual": "gpt-4o",
        "provider": "openai",
        "endpoint": "/v1/chat/completions",
        "status_code": 200,
    }
    await RequestLog.create(
        request_id="log-key-alpha", api_key_name="Production-DeepSeek", **common
    )
    await RequestLog.create(
        request_id="log-key-beta", api_key_name="Staging-Qwen", **common
    )

    resp = await client.get(
        "/api/logs", params={"api_key_name": "deepseek"}, headers=h
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["api_key_name"] == "Production-DeepSeek"


async def test_logs_get_by_request_id(client):
    admin = await create_admin("logget", "pw")
    token = create_access_token({"sub": str(admin.id)})
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
    resp = await client.get("/api/logs/log-detail-001", headers=h)
    assert resp.status_code == 200
    assert resp.json()["request_id"] == "log-detail-001"


async def test_logs_not_found(client):
    admin = await create_admin("log404", "pw")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.get("/api/logs/nonexistent", headers=auth_header(token))
    assert resp.status_code == 404


# ── stats ───────────────────────────────────────────────────

async def test_stats_overview(client):
    admin = await create_admin("statov", "pw")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.get("/api/stats/overview", headers=auth_header(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_requests" in data
    assert "total_cost" in data
    assert "cost_today" in data


async def test_stats_usage(client):
    admin = await create_admin("statu", "pw")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.get("/api/stats/usage?days=7", headers=auth_header(token))
    assert resp.status_code == 200


async def test_stats_by_model(client):
    admin = await create_admin("statm", "pw")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.get("/api/stats/by-model?days=7", headers=auth_header(token))
    assert resp.status_code == 200


async def test_stats_by_key(client):
    admin = await create_admin("statk", "pw")
    token = create_access_token({"sub": str(admin.id)})
    resp = await client.get("/api/stats/by-key?days=7", headers=auth_header(token))
    assert resp.status_code == 200


# ── unauthenticated access ──────────────────────────────────

async def test_admin_endpoints_require_auth(client):
    endpoints = [
        ("GET", "/api/channels"),
        ("GET", "/api/keys"),
        ("GET", "/api/logs"),
        ("GET", "/api/model-prices"),
        ("GET", "/api/stats/overview"),
    ]
    for method, path in endpoints:
        resp = await client.request(method, path)
        assert resp.status_code in (401, 403), f"{method} {path} should require auth"
