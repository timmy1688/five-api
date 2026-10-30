"""Every route is classified, guarded and actually rejects the wrong credential.

New routes fail here until they are given an explicit access class.
"""
import re
from decimal import Decimal

import pytest
from fastapi.routing import APIRoute

from app.main import create_app
from app.models import APIKey
from app.services.auth import hash_api_key
from tests.conftest import auth_header, create_tenant_account

PUBLIC = {("POST", "/api/login"), ("GET", "/healthz"), ("GET", "/metrics"), ("GET", "/{full_path:path}")}
# Any signed-in account, including one that still has to change its temporary password.
SELF_SERVICE = {("GET", "/api/me"), ("PUT", "/api/password")}
TENANT_PREFIX = "/api/keys"
ANTHROPIC_PREFIX = "/v1/messages"


def _flatten(routes, prefix=""):
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _flatten(route.original_router.routes, prefix + route.include_context.prefix)
        elif isinstance(route, APIRoute):
            yield prefix + route.path, route


def _dependencies(dependant, found=None) -> set[str]:
    found = set() if found is None else found
    for sub in dependant.dependencies:
        found.add(getattr(sub.call, "__name__", ""))
        _dependencies(sub, found)
    return found


def _routes() -> list[tuple[str, str, set[str]]]:
    rows = []
    for path, route in _flatten(create_app().routes):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows.append((method, path, _dependencies(route.dependant)))
    return rows


def _access(method: str, path: str) -> str:
    if (method, path) in PUBLIC:
        return "public"
    if (method, path) in SELF_SERVICE:
        return "self"
    if path.startswith(TENANT_PREFIX):
        return "account"
    if path.startswith(ANTHROPIC_PREFIX):
        return "anthropic"
    if path.startswith("/v1/"):
        return "inference"
    if path.startswith("/api/"):
        return "platform"
    return "unclassified"


ROUTES = _routes()
GUARDS = {
    "self": "get_current_admin",
    "account": "require_account",
    "platform": "require_platform_admin",
    "inference": "verify_api_key",
    "anthropic": "verify_api_key_anthropic",
}


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _ids(rows):
    return [f"{method} {path}" for method, path, _ in rows]


def test_route_inventory_is_complete():
    assert len(ROUTES) > 80
    unclassified = [(m, p) for m, p, _ in ROUTES if _access(m, p) == "unclassified"]
    assert not unclassified, f"Give these routes an access class: {unclassified}"


@pytest.mark.parametrize("method,path,deps", ROUTES, ids=_ids(ROUTES))
def test_route_declares_the_guard_for_its_class(method, path, deps):
    access = _access(method, path)
    if access == "public":
        assert not deps & set(GUARDS.values())
        return
    assert GUARDS[access] in deps, f"{method} {path} must depend on {GUARDS[access]}"
    if access in {"inference", "anthropic"}:
        assert "get_current_admin" not in deps
    else:
        assert not deps & {"verify_api_key", "verify_api_key_anthropic"}


GUARDED = [row for row in ROUTES if _access(row[0], row[1]) != "public"]
MANAGEMENT = [row for row in GUARDED if row[1].startswith("/api/")]
PLATFORM = [row for row in GUARDED if _access(row[0], row[1]) == "platform"]
INFERENCE = [row for row in GUARDED if row[1].startswith("/v1/")]


async def _call(client, method: str, path: str, headers: dict | None = None):
    kwargs = {"headers": headers or {}}
    if method != "GET":
        kwargs["json"] = {}
    return await client.request(method, _url(path), **kwargs)


@pytest.mark.parametrize("method,path,deps", GUARDED, ids=_ids(GUARDED))
async def test_missing_credentials_are_rejected(client, method, path, deps):
    response = await _call(client, method, path)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path,deps", PLATFORM, ids=_ids(PLATFORM))
async def test_tenant_account_cannot_reach_platform_routes(client, method, path, deps):
    _, _, headers = await create_tenant_account()
    response = await _call(client, method, path, headers)
    assert response.status_code == 403


@pytest.mark.parametrize("method,path,deps", MANAGEMENT, ids=_ids(MANAGEMENT))
async def test_inference_key_is_not_a_management_credential(client, method, path, deps):
    tenant, _, _ = await create_tenant_account()
    raw = "sk-route-guard-inference-key"
    await APIKey.create(tenant_id=tenant.id, name="guard", key_hash=hash_api_key(raw),
                        key_prefix=raw[:8], quota_total=Decimal("-1"))
    response = await _call(client, method, path, auth_header(raw))
    assert response.status_code == 401


@pytest.mark.parametrize("method,path,deps", INFERENCE, ids=_ids(INFERENCE))
async def test_management_token_is_not_an_inference_credential(client, admin_token, method, path, deps):
    headers = {**auth_header(admin_token), "x-api-key": admin_token}
    response = await _call(client, method, path, headers)
    assert response.status_code == 401
