"""Password policy and one-time temporary passwords for tenant and platform accounts."""
import pytest

from app.models import ManagementEvent, Tenant, User
from app.services.auth import hash_password
from app.services.passwords import generate_temporary_password, password_problem, resolve_new_password
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio

STRONG = "Correct-Horse-9"


# ── policy ──────────────────────────────────────────────────

@pytest.mark.parametrize("value", [STRONG, "abcdefgh1234AB", "纯中文密码也可以1234Aa", "a" * 8 + "B1!x"])
async def test_policy_accepts_strong_passwords(value):
    assert password_problem(value) is None


@pytest.mark.parametrize("value, fragment", [
    ("Short-1a", "at least 12"),
    ("alllowercaseletters", "at least three"),
    ("ALLUPPERCASE1234", "at least three"),
    ("lowercase-only-here", "at least three"),
    ("12345678901234567", "at least three"),
    ("Ab1-" + "x" * 80, "72"),
])
async def test_policy_rejects_weak_passwords(value, fragment):
    assert fragment in password_problem(value)


async def test_generated_passwords_satisfy_the_policy_and_differ():
    passwords = {generate_temporary_password() for _ in range(200)}
    assert len(passwords) == 200
    assert all(password_problem(value) is None for value in passwords)
    sample = next(iter(passwords))
    assert len(sample) == 19 and sample.count("-") == 3
    # Look-alike characters never appear, so a printed password can be typed back.
    assert not set("0O1lI") & {char for value in passwords for char in value}


async def test_resolve_prefers_explicit_password():
    assert resolve_new_password(STRONG) == (STRONG, False)
    generated, flag = resolve_new_password(None)
    assert flag is True and password_problem(generated) is None


# ── tenants ─────────────────────────────────────────────────

async def test_tenant_created_without_password_gets_a_one_time_password(client, admin_token):
    created = await client.post("/api/tenants", json={"name": "gen", "username": "gen"},
                                headers=auth_header(admin_token))
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    password = created.json()["temporary_password"]
    assert password_problem(password) is None

    user = await User.get(username="gen")
    assert user.must_change_password and user.hashed_password != password
    login = await client.post("/api/login", json={"username": "gen", "password": password})
    assert login.status_code == 200 and login.json()["must_change_password"] is True

    # The plain text is not retrievable afterwards, nor stored in the audit trail.
    listing = await client.get("/api/tenants", headers=auth_header(admin_token))
    assert "temporary_password" not in listing.json()["items"][0]
    events = await ManagementEvent.filter(action="tenant.create").values_list("detail", flat=True)
    assert password not in str(list(events))
    assert list(events)[0]["password_generated"] is True


async def test_tenant_created_with_password_does_not_echo_it(client, admin_token):
    created = await client.post("/api/tenants", json={"name": "typed", "username": "typed", "password": STRONG},
                                headers=auth_header(admin_token))
    assert created.status_code == 201
    assert created.json()["temporary_password"] is None
    assert created.headers.get("cache-control") != "no-store"
    assert (await client.post("/api/login", json={"username": "typed", "password": STRONG})).status_code == 200


async def test_tenant_creation_rejects_weak_password_without_side_effects(client, admin_token):
    weak = await client.post("/api/tenants", json={"name": "weak", "username": "weak", "password": "password1"},
                             headers=auth_header(admin_token))
    assert weak.status_code == 422
    assert not await Tenant.exists(name="weak") and not await User.exists(username="weak")


async def test_tenant_reset_generates_and_revokes_sessions(client, admin_token):
    headers = auth_header(admin_token)
    await client.post("/api/tenants", json={"name": "rst", "username": "rst", "password": STRONG}, headers=headers)
    tenant = await Tenant.get(name="rst")
    session = (await client.post("/api/login", json={"username": "rst", "password": STRONG})).json()["access_token"]
    version = (await User.get(username="rst")).token_version

    reset = await client.put(f"/api/tenants/{tenant.id}/password", json={}, headers=headers)
    assert reset.status_code == 200 and reset.headers["cache-control"] == "no-store"
    password = reset.json()["temporary_password"]
    assert password_problem(password) is None and password != STRONG
    assert (await User.get(username="rst")).token_version == version + 1
    assert (await client.get("/api/me", headers=auth_header(session))).status_code == 401
    assert (await client.post("/api/login", json={"username": "rst", "password": STRONG})).status_code == 401
    login = await client.post("/api/login", json={"username": "rst", "password": password})
    assert login.json()["must_change_password"] is True
    event = await ManagementEvent.filter(action="tenant.password_reset").first()
    assert password not in str(event.detail) and event.detail["password_generated"] is True


async def test_tenant_reset_with_chosen_password_enforces_policy(client, admin_token):
    headers = auth_header(admin_token)
    await client.post("/api/tenants", json={"name": "pick", "username": "pick"}, headers=headers)
    tenant = await Tenant.get(name="pick")
    assert (await client.put(f"/api/tenants/{tenant.id}/password", json={"password": "weakpass"},
                             headers=headers)).status_code == 422
    chosen = await client.put(f"/api/tenants/{tenant.id}/password", json={"password": STRONG}, headers=headers)
    assert chosen.status_code == 200 and "temporary_password" not in chosen.json()


# ── platform administrators ─────────────────────────────────

async def test_admin_created_without_password_gets_a_one_time_password(client, admin_token):
    created = await client.post("/api/users", json={"username": "second"}, headers=auth_header(admin_token))
    assert created.status_code == 201 and created.headers["cache-control"] == "no-store"
    password = created.json()["temporary_password"]
    assert password_problem(password) is None
    login = await client.post("/api/login", json={"username": "second", "password": password})
    assert login.json()["must_change_password"] is True
    listing = await client.get("/api/users", headers=auth_header(admin_token))
    assert all("temporary_password" not in item for item in listing.json()["items"])


async def test_admin_reset_password_endpoint(client, admin_token):
    headers = auth_header(admin_token)
    created = await client.post("/api/users", json={"username": "other", "password": STRONG}, headers=headers)
    admin_id = created.json()["id"]
    version = (await User.get(id=admin_id)).token_version

    reset = await client.put(f"/api/users/{admin_id}/password", json={}, headers=headers)
    assert reset.status_code == 200 and reset.headers["cache-control"] == "no-store"
    password = reset.json()["temporary_password"]
    assert (await User.get(id=admin_id)).token_version == version + 1
    assert (await client.post("/api/login", json={"username": "other", "password": STRONG})).status_code == 401
    assert (await client.post("/api/login", json={"username": "other", "password": password})).status_code == 200
    event = await ManagementEvent.filter(action="admin.update", target_id=admin_id).first()
    assert password not in str(event.detail) and event.detail["password_reset"] is True


async def test_admin_reset_only_targets_platform_accounts(client, admin_token):
    headers = auth_header(admin_token)
    await client.post("/api/tenants", json={"name": "notadmin", "username": "notadmin"}, headers=headers)
    tenant_account = await User.get(username="notadmin")
    missing = await client.put(f"/api/users/{tenant_account.id}/password", json={}, headers=headers)
    assert missing.status_code == 404
    assert (await client.put("/api/users/99999/password", json={}, headers=headers)).status_code == 404


async def test_admin_password_update_enforces_policy(client, admin_token):
    headers = auth_header(admin_token)
    assert (await client.post("/api/users", json={"username": "weakadmin", "password": "short"},
                              headers=headers)).status_code == 422
    created = await client.post("/api/users", json={"username": "okadmin"}, headers=headers)
    admin_id = created.json()["id"]
    assert (await client.put(f"/api/users/{admin_id}", json={"password": "alllowercase1234"},
                             headers=headers)).status_code == 422
    assert (await client.put(f"/api/users/{admin_id}", json={"password": STRONG},
                             headers=headers)).status_code == 200


# ── self service ────────────────────────────────────────────

async def test_change_password_applies_policy_to_the_new_password_only(client, admin_token):
    headers = auth_header(admin_token)
    # The current password is only verified, never held to the policy (legacy passwords stay usable).
    weak = await client.put("/api/password", json={"old_password": "testpass123", "new_password": "newpassword12"},
                            headers=headers)
    assert weak.status_code == 422
    ok = await client.put("/api/password", json={"old_password": "testpass123", "new_password": STRONG},
                          headers=headers)
    assert ok.status_code == 200


async def test_change_password_refuses_reusing_the_current_one(client):
    await User.create(username="reuse", hashed_password=hash_password(STRONG), role="platform_admin")
    token = (await client.post("/api/login", json={"username": "reuse", "password": STRONG})).json()["access_token"]
    same = await client.put("/api/password", json={"old_password": STRONG, "new_password": STRONG},
                            headers=auth_header(token))
    assert same.status_code == 400


async def test_login_still_accepts_legacy_short_passwords(client):
    await User.create(username="legacy", hashed_password=hash_password("pw12"), role="platform_admin")
    assert (await client.post("/api/login", json={"username": "legacy", "password": "pw12"})).status_code == 200
