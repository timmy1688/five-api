from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import APIKey, Channel, RequestLog, RequestLogAudit
from app.services.auth import create_access_token, hash_api_key
from app.services.error_detail import classify_base_url, describe_upstream_failure
from app.services.settings_service import set_inference_audit_enabled
from tests.conftest import auth_header, create_admin

pytestmark = pytest.mark.regression

MOCK_COMPLETION_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "gpt-4o",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
}


def test_classify_official_and_reseller_hosts():
    assert classify_base_url("https://api.openai.com/v1") == "official"
    assert classify_base_url("https://api.deepseek.com/anthropic") == "official"
    assert classify_base_url("https://eastus.openai.azure.com") == "official"
    assert classify_base_url("https://relay.example.com/v1") == "reseller"


def test_upstream_http_error_keeps_vendor_body():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        401,
        json={"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}},
        request=request,
    )
    exc = httpx.HTTPStatusError("401", request=request, response=response)
    detail = describe_upstream_failure(exc, "https://api.openai.com")
    assert detail["error_origin"] == "official"
    assert detail["upstream_status_code"] == 401
    assert detail["error_message"] == "Incorrect API key provided"
    assert "Incorrect API key provided" in detail["upstream_error"]


async def _key_and_channel(base_url: str):
    channel = await Channel.create(
        name="origin-ch",
        provider="openai",
        base_url=base_url,
        api_key="sk-upstream",
        models=["gpt-4o"],
        max_retries=0,
    )
    raw_key = "sk-originlog123456"
    await APIKey.create(
        name="origin-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
    )
    return channel, raw_key


async def test_official_upstream_error_is_logged(client):
    channel, raw_key = await _key_and_channel("https://api.openai.com")
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        429,
        json={"error": {"message": "Rate limit reached", "type": "rate_limit_error"}},
        request=request,
    )
    provider = AsyncMock()
    provider.send_request = AsyncMock(
        side_effect=httpx.HTTPStatusError("429", request=request, response=response)
    )
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()

    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 429
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.error_origin == "official"
    assert log.status_code == 429
    assert log.upstream_status_code == 429
    assert log.error_message == "Rate limit reached"
    assert "Rate limit reached" in log.upstream_error


async def test_reseller_upstream_error_is_logged(client):
    channel, raw_key = await _key_and_channel("https://relay.example.com/v1")
    request = httpx.Request("POST", "https://relay.example.com/v1/chat/completions")
    response = httpx.Response(502, text="bad gateway from relay", request=request)
    provider = AsyncMock()
    provider.send_request = AsyncMock(
        side_effect=httpx.HTTPStatusError("502", request=request, response=response)
    )
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()

    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 502
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.error_origin == "reseller"
    assert log.upstream_status_code == 502
    assert "bad gateway from relay" in log.upstream_error


async def test_system_audit_switch_records_content(client):
    await set_inference_audit_enabled(True)
    channel, raw_key = await _key_and_channel("https://api.openai.com")
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()

    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "remember this"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    audit = await RequestLogAudit.get(request_log_id=log.id)
    assert "remember this" in audit.audit_request
    assert not hasattr(audit, "audit_response")
    assert log.has_audit is True
    assert log.error_origin == ""

    admin = await create_admin("audit-list", "pw")
    headers = auth_header(create_access_token({"sub": str(admin.id)}))
    listed = await client.get("/api/logs", headers=headers)
    assert listed.status_code == 200
    item = next(row for row in listed.json()["items"] if row["request_id"] == log.request_id)
    assert item["has_audit"] is True
    assert "audit_request" not in item
    assert "remember this" not in listed.text

    detail = await client.get(f"/api/logs/{log.request_id}", headers=headers)
    assert detail.status_code == 200
    assert "audit_request" not in detail.json()
    assert "remember this" not in detail.text
    assert "Hello!" not in detail.text

    audit_view = await client.get(f"/api/logs/{log.request_id}/audit", headers=headers)
    assert audit_view.status_code == 200
    assert "remember this" in audit_view.json()["audit_request"]
    assert "Hello!" not in audit_view.text


async def test_inference_audit_setting_persists(client):
    admin = await create_admin("settings-admin", "pw")
    token = create_access_token({"sub": str(admin.id)})
    denied = await client.get("/api/security")
    assert denied.status_code == 401

    current = await client.get("/api/security", headers=auth_header(token))
    assert current.status_code == 200
    assert current.json()["inference_audit_enabled"] is False

    updated = await client.put(
        "/api/security/inference-audit",
        json={"enabled": True},
        headers=auth_header(token),
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is True

    again = await client.get("/api/security", headers=auth_header(token))
    assert again.json()["inference_audit_enabled"] is True
