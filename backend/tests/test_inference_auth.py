"""Both inference entry points reject bad keys before any upstream work."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models import APIKey, Channel, ModelPrice, Settlement, Tenant
from app.services.auth import hash_api_key
from app.utils.ip_check import check_ip_allowed
from tests.conftest import create_test_tenant

RAW = "sk-inference-auth-test-key"

ENDPOINTS = {
    "openai": ("/v1/chat/completions", "gpt-4o",
               lambda key: {"Authorization": f"Bearer {key}"}),
    "anthropic": ("/v1/messages", "claude-sonnet-5",
                  lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"}),
}

CASES = {
    "missing": (None, 401),
    "unknown": ({"raw": "sk-not-a-real-key"}, 401),
    "disabled": ({"is_enabled": False}, 401),
    "revoked": ({"is_revoked": True}, 401),
    "expired": ({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}, 401),
    "ip_denied": ({"allowed_ips": ["203.0.113.0/24"]}, 403),
    "tenant_disabled": ({"tenant_enabled": False}, 403),
}


async def _setup(case: dict | None) -> str | None:
    await Channel.create(name="oa", provider="openai", base_url="https://oa.example.com/v1",
                         api_key="sk-up", models=["gpt-4o"])
    await Channel.create(name="an", provider="anthropic", base_url="https://an.example.com",
                         api_key="sk-up", models=["claude-sonnet-5"])
    for model in ("gpt-4o", "claude-sonnet-5"):
        await ModelPrice.create(model=model, prompt_price=Decimal(1), completion_price=Decimal(1))
    if case is None:
        return None
    tenant = await create_test_tenant()
    fields = {k: v for k, v in case.items() if k not in {"raw", "tenant_enabled"}}
    await APIKey.create(tenant_id=tenant.id, name="auth", key_hash=hash_api_key(RAW),
                        key_prefix=RAW[:8], quota_total=Decimal("-1"), **fields)
    if case.get("tenant_enabled") is False:
        await Tenant.filter(id=tenant.id).update(is_enabled=False)
    return case.get("raw", RAW)


def _no_upstream(*_args, **_kwargs):
    raise AssertionError("a rejected request must not be routed upstream")


@pytest.mark.parametrize("protocol", ENDPOINTS)
@pytest.mark.parametrize("case", CASES)
async def test_rejected_keys_never_reach_routing_or_billing(client, protocol, case):
    path, model, headers_for = ENDPOINTS[protocol]
    fields, expected = CASES[case]
    raw = await _setup(fields)
    headers = headers_for(raw) if raw else {"anthropic-version": "2023-06-01"}
    body = {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}
    with patch("app.services.routing.resolve_with_fallbacks", side_effect=_no_upstream):
        response = await client.post(path, json=body, headers=headers)
    assert response.status_code == expected
    if protocol == "anthropic":
        assert response.json()["type"] == "error"
        assert response.json()["error"]["type"] in {"authentication_error", "permission_error"}
    else:
        assert "error" in response.json()
    assert RAW not in response.text
    assert not await Settlement.exists()


@pytest.mark.parametrize("protocol", ENDPOINTS)
async def test_forwarded_for_header_cannot_satisfy_an_ip_allowlist(client, protocol):
    path, model, headers_for = ENDPOINTS[protocol]
    await _setup({"allowed_ips": ["198.51.100.7"]})
    headers = {**headers_for(RAW), "X-Forwarded-For": "198.51.100.7", "X-Real-IP": "198.51.100.7"}
    with patch("app.services.routing.resolve_with_fallbacks", side_effect=_no_upstream):
        response = await client.post(path, headers=headers, json={
            "model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 403


@pytest.mark.parametrize("allowed,client_ip,expected", [
    ([], "203.0.113.9", True),
    (["203.0.113.9"], "203.0.113.9", True),
    (["203.0.113.0/24"], "203.0.113.200", True),
    (["203.0.113.0/24"], "203.0.114.1", False),
    (["2001:db8::/32"], "2001:db8::1", True),
    (["2001:db8::/32"], "2001:db9::1", False),
    (["not-an-ip", "203.0.113.9"], "203.0.113.9", True),
    (["not-an-ip"], "203.0.113.9", False),
    (["203.0.113.9"], "", False),
    (["203.0.113.9"], "testclient", False),
    (["0.0.0.0/0"], "::1", False),
])
def test_ip_allowlist_edges(allowed, client_ip, expected):
    assert check_ip_allowed(allowed, client_ip) is expected
