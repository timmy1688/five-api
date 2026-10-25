from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import jwt
from tortoise.exceptions import IntegrityError

from app.config import settings
from app.models import APIKey, ManagementEvent, RequestLog, Settlement, Tenant, User
from app.services.auth import create_access_token, hash_password
from app.services.pre_checks import get_effective_allowed_models
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


async def customer(name="customer", models=None):
    tenant = await Tenant.create(name=name, quota_total=Decimal("20"), allowed_models=models or [])
    user = await User.create(username=name, hashed_password=hash_password("customer-pass"),
                             role="tenant", tenant_id=tenant.id)
    return tenant, user, auth_header(create_access_token({"sub": str(user.id), "ver": user.token_version}))


async def test_atomic_provisioning_defaults_and_temporary_password(client, admin_token):
    headers = auth_header(admin_token)
    body = {"name": "alpha", "username": "alpha", "password": "temporary-pass"}
    created = await client.post("/api/tenants", json=body, headers=headers)
    assert created.status_code == 201
    assert Decimal(created.json()["quota_total"]) == 0
    assert created.json()["quota_reset_day"] is None
    user = await User.get(username="alpha")
    assert user.tenant_id == created.json()["id"] and user.role == "tenant"
    assert user.must_change_password
    duplicate = await client.post("/api/tenants", json={**body, "name": "other"}, headers=headers)
    assert duplicate.status_code == 409
    assert not await Tenant.exists(name="other")
    login = await client.post("/api/login", json={"username": "alpha", "password": "temporary-pass"})
    assert login.json()["expires_in"] == settings.JWT_EXPIRE_MINUTES * 60
    old_headers = auth_header(login.json()["access_token"])
    assert (await client.get("/api/me", headers=old_headers)).status_code == 200
    assert (await client.get("/api/keys", headers=old_headers)).status_code == 403
    changed = await client.put("/api/password", headers=old_headers,
                               json={"old_password": "temporary-pass", "new_password": "customer-new-pass"})
    assert changed.status_code == 200
    assert (await client.get("/api/me", headers=old_headers)).status_code == 401
    fresh = auth_header(changed.json()["access_token"])
    assert (await client.get("/api/keys", headers=fresh)).status_code == 200


async def test_cross_tenant_crud_and_usage_are_scoped(client):
    tenant_a, _, a = await customer("a")
    _, _, b = await customer("b")
    created = await client.post("/api/keys", json={"name": "a-key"}, headers=a)
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    raw = created.json()["key"]
    key_id = created.json()["id"]
    stored = await APIKey.get(id=key_id)
    assert stored.tenant_id == tenant_a.id and stored.key_hash != raw
    assert len(raw) >= 46
    assert "key" not in (await client.get(f"/api/keys/{key_id}", headers=a)).json()
    assert (await client.get("/api/keys", headers=b)).json()["total"] == 0
    for method, suffix, payload in [
        ("GET", "", None), ("PUT", "", {"name": "stolen"}), ("DELETE", "", None),
        ("GET", "/usage", None),
    ]:
        kwargs = {"headers": b}
        if payload is not None:
            kwargs["json"] = payload
        assert (await client.request(method, f"/api/keys/{key_id}{suffix}", **kwargs)).status_code == 404
    assert (await client.get(f"/api/keys?tenant_id={tenant_a.id}", headers=b)).status_code == 403
    await RequestLog.create(request_id="own", api_key_id=key_id, tenant_id=tenant_a.id, model_requested="m")
    await RequestLog.create(request_id="wrong-owner", api_key_id=key_id, tenant_id=999, model_requested="m")
    usage = await client.get(f"/api/keys/{key_id}/usage", headers=a)
    assert [row["request_id"] for row in usage.json()["items"]] == ["own"]
    assert (await client.get("/api/me", headers=auth_header(raw))).status_code == 401
    # A management JWT is never an inference credential.
    assert (await client.get("/v1/models", headers=a)).status_code == 401


@pytest.mark.parametrize("field,value", [
    ("tenant_id", 1), ("role", "platform_admin"), ("quota_used", 0),
    ("quota_reset_day", 1), ("model_group_id", 1), ("audit_policy", "on"),
    ("window_limits", {"1d": 1}), ("pricing", {"prompt": 0}),
])
async def test_tenant_key_write_allowlist_rejects_sensitive_fields(client, field, value):
    _, _, headers = await customer()
    key = await client.post("/api/keys", headers=headers, json={"name": "safe"})
    key_id = key.json()["id"]
    created = await client.post("/api/keys", headers=headers, json={"name": "injected", field: value})
    updated = await client.put(f"/api/keys/{key_id}", headers=headers, json={field: value})
    assert created.status_code == updated.status_code == 422
    assert (await APIKey.get(id=key_id)).name == "safe"


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/channels", None), ("GET", "/api/model-prices", None),
    ("GET", "/api/stats/overview", None), ("GET", "/api/logs", None),
    ("GET", "/api/settings", None), ("GET", "/api/audit/keys", None),
    ("GET", "/api/security", None), ("GET", "/api/users", None),
    ("GET", "/api/tenants/all", None), ("GET", "/api/model-groups/all", None),
    ("POST", "/api/users", {"username": "evil", "password": "evil-password"}),
    ("POST", "/api/tenants", {"name": "evil", "username": "evil", "password": "evil-password"}),
    ("GET", "/api/settlements", None),
    ("POST", "/api/settlements/1/retry", {}),
])
async def test_platform_endpoints_reject_tenant(client, method, path, body):
    _, _, headers = await customer()
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    response = await client.request(method, path, **kwargs)
    assert response.status_code == 403


async def test_role_routes_removed_and_bindings_immutable(client, admin_token):
    tenant, user, headers = await customer()
    platform = auth_header(admin_token)
    for path in ["/api/roles", "/api/roles/all", "/api/roles/permissions"]:
        assert (await client.get(path, headers=platform)).status_code == 404
    assert (await client.put(f"/api/users/{user.id}", headers=platform,
                             json={"role": "platform_admin", "tenant_id": None})).status_code == 422
    assert (await client.put(f"/api/tenants/{tenant.id}", headers=platform,
                             json={"quota_used": 0, "quota_total": 100})).status_code == 422
    own_key = await client.post("/api/keys", headers=platform, json={"name": "platform-own"})
    assert own_key.status_code == 201 and own_key.json()["tenant_is_system"]
    assert (await Tenant.get(id=own_key.json()["tenant_id"])).is_system
    assert (await client.post(f"/api/tenants/{tenant.id}/keys", headers=platform,
                             json={"name": "on-behalf"})).status_code == 405
    with pytest.raises(IntegrityError):
        await User.create(username="duplicate", hashed_password="hash", role="tenant", tenant_id=tenant.id)


async def test_quota_change_idempotence_and_occupied_balance(client, admin_token, mock_redis):
    tenant, _, headers = await customer()
    await Tenant.filter(id=tenant.id).update(quota_used=Decimal("3"))
    await Settlement.create(request_id="inflight", tenant_id=tenant.id, api_key_id=0, occupied=Decimal("2"))
    platform = auth_header(admin_token)
    path = f"/api/tenants/{tenant.id}/quota"
    op = str(uuid4())
    body = {"quota_total": 4, "reason": "cap decrease", "operation_id": op}
    assert (await client.put(path, headers=platform, json=body)).status_code == 409
    body["quota_total"] = 10
    first = await client.put(path, headers=platform, json=body)
    repeated = await client.put(path, headers=platform, json={**body, "quota_total": "10.000000"})
    assert first.status_code == repeated.status_code == 200
    assert await ManagementEvent.filter(operation_id=op).count() == 1
    changed = await client.put(path, headers=platform, json={**body, "quota_total": 11})
    assert changed.status_code == 409
    summary = (await client.get("/api/keys/summary", headers=headers)).json()
    assert Decimal(summary["quota_remaining"]) == 5
    assert Decimal(summary["quota_occupied"]) == 2
    assert (await client.put(path, headers=headers, json=body)).status_code == 403


async def test_key_replacement_preserves_history_and_revocation_is_permanent(client):
    tenant, _, headers = await customer()
    first = (await client.post("/api/keys", headers=headers, json={"name": "old"})).json()
    await APIKey.filter(id=first["id"]).update(quota_used=Decimal("4"))
    await Tenant.filter(id=tenant.id).update(quota_used=Decimal("4"))
    assert (await client.delete(f"/api/keys/{first['id']}", headers=headers)).status_code == 200
    assert (await client.put(f"/api/keys/{first['id']}", headers=headers,
                             json={"is_enabled": True})).status_code == 409
    second = (await client.post("/api/keys", headers=headers, json={"name": "new"})).json()
    assert second["quota_used"] == 0
    assert (await Tenant.get(id=tenant.id)).quota_used == Decimal("4")
    assert (await client.get("/v1/models", headers=auth_header(first["key"]))).status_code == 401


async def test_tenant_disable_and_manual_password_reset(client, admin_token):
    tenant, _, headers = await customer()
    key = (await client.post("/api/keys", headers=headers, json={"name": "app"})).json()
    platform = auth_header(admin_token)
    await client.put(f"/api/tenants/{tenant.id}", headers=platform, json={"is_enabled": False})
    assert (await client.get("/api/keys", headers=headers)).status_code == 403
    assert (await client.get("/v1/models", headers=auth_header(key["key"]))).status_code == 403
    await client.put(f"/api/tenants/{tenant.id}", headers=platform, json={"is_enabled": True})
    reset = await client.put(f"/api/tenants/{tenant.id}/password", headers=platform,
                             json={"password": "another-temporary-pass"})
    assert reset.status_code == 200
    assert (await client.get("/api/me", headers=headers)).status_code == 401
    login = await client.post("/api/login", json={"username": "customer", "password": "another-temporary-pass"})
    assert login.json()["must_change_password"] is True
    assert (await client.get("/v1/models", headers=auth_header(key["key"]))).status_code == 200


async def test_model_allowance_and_key_count(client):
    tenant, _, headers = await customer(models=["model-a"])
    assert (await client.post("/api/keys", headers=headers,
                              json={"name": "b", "allowed_models": ["model-b"]})).status_code == 403
    first = (await client.post("/api/keys", headers=headers, json={"name": "a"})).json()
    key = await APIKey.get(id=first["id"])
    assert await get_effective_allowed_models(key) == ["model-a"]
    await Tenant.filter(id=tenant.id).update(max_keys=1)
    assert (await client.post("/api/keys", headers=headers, json={"name": "overflow"})).status_code == 409
    await client.delete(f"/api/keys/{key.id}", headers=headers)
    assert (await client.post("/api/keys", headers=headers, json={"name": "replacement"})).status_code == 201


@pytest.mark.parametrize("claims", [
    {"sub": "not-a-number"}, {"sub": "1", "aud": "inference"},
    {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
])
async def test_malformed_expired_and_wrong_audience_jwts_are_rejected(client, admin, claims):
    base = {"sub": str(admin.id), "aud": "five-api-management",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=1)}
    token = jwt.encode({**base, **claims}, settings.SECRET_KEY, algorithm="HS256")
    assert (await client.get("/api/me", headers=auth_header(token))).status_code == 401


async def test_key_creation_rate_limit(client):
    _, _, headers = await customer()
    for i in range(20):
        assert (await client.post("/api/keys", headers=headers, json={"name": f"key-{i}"})).status_code == 201
    response = await client.post("/api/keys", headers=headers, json={"name": "overflow"})
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert (await client.get("/api/keys", headers=headers)).json()["total"] == 20


async def test_role_and_tenant_claims_do_not_override_database_binding(client):
    _, user, _ = await customer()
    forged_claims = create_access_token({"sub": str(user.id), "role": "platform_admin", "tenant_id": 999})
    headers = auth_header(forged_claims)
    assert (await client.get("/api/users", headers=headers)).status_code == 403
    assert (await client.get("/api/me", headers=headers)).json()["tenant_id"] == user.tenant_id


async def test_password_byte_limit_prevents_silent_bcrypt_truncation(client, admin_token):
    response = await client.post("/api/tenants", headers=auth_header(admin_token), json={
        "name": "too-long", "username": "too-long", "password": "长" * 30,
    })
    assert response.status_code == 422
    assert not await Tenant.exists(name="too-long")
