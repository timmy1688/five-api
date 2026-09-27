from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models import APIKey, Channel, RequestLog, Role, SecurityKeyword, User
from app.services.auth import create_access_token, hash_api_key, hash_password
from app.services.content_filter import ResponseScanner, match_secret, request_text
from app.services.settings_service import (
    set_inference_audit_enabled,
    set_keyword_filter_enabled,
    set_secret_scan_enabled,
)
from tests.conftest import auth_header, create_admin

pytestmark = pytest.mark.regression

MOCK_COMPLETION_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "gpt-4o",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "the launch code is 4491"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 4, "completion_tokens": 4, "total_tokens": 8},
}


def test_request_text_reads_conversation_and_skips_model_name():
    body = {
        "model": "secret-model",
        "messages": [
            {"role": "system", "content": "keep Project Atlas private"},
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ],
    }
    text = request_text(body)
    assert "Project Atlas" in text
    assert "hello" in text
    assert "secret-model" not in text


def test_response_scanner_matches_across_chunks():
    scanner = ResponseScanner(("project atlas",))
    assert scanner.feed("please review pro") is None
    assert scanner.feed("ject atlas now") == "project atlas"


def test_secret_patterns_match_known_tokens_and_ignore_lookalikes():
    private_key = "-----BEGIN RSA PRIVATE KEY-----"
    github = "ghp_" + "a" * 20
    slack = "xoxb-1234567890-abcdef"
    aws = "AKIAIOSFODNN7EXAMPLE"
    assert match_secret(private_key) == "private_key"
    assert match_secret(f"token {github}") == "github_token"
    assert match_secret(slack) == "slack_token"
    assert match_secret(aws) == "aws_access_key"
    assert match_secret("AKIA1234567890ABCD") is None
    assert match_secret("sk-xxxxxxx") is None
    assert match_secret("sk-proj-example-key-for-local-development") is None
    assert match_secret("not-a-secret") is None


def test_secret_scanner_matches_a_split_access_key():
    scanner = ResponseScanner((), secrets=True)
    assert scanner.feed("key AKIA1234") is None
    assert scanner.feed("5678ABCD9012 rest") == "aws_access_key"


async def _ready_key():
    channel = await Channel.create(
        name="filter-ch",
        provider="openai",
        base_url="https://api.openai.com",
        api_key="sk-upstream",
        models=["gpt-4o"],
        max_retries=0,
    )
    raw_key = "sk-filterkey123456"
    await APIKey.create(
        name="filter-key",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        quota_total=Decimal("-1"),
    )
    return channel, raw_key


async def test_keyword_filter_marks_the_request_and_still_forwards(client):
    await SecurityKeyword.create(keyword="Project Atlas", keyword_key="project atlas", direction="request")
    await set_keyword_filter_enabled(True)
    channel, raw_key = await _ready_key()
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
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "notes about Project Atlas"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    assert "4491" in resp.text
    provider.send_request.assert_called_once()
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.status_code == 200
    assert log.error_origin == ""
    assert log.channel_id == channel.id
    assert log.security_hit == "project atlas"


async def test_keyword_filter_does_not_block_a_reply(client):
    await SecurityKeyword.create(keyword="4491", keyword_key="4491", direction="request")
    await set_keyword_filter_enabled(True)
    channel, raw_key = await _ready_key()
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
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    assert "4491" in resp.text
    provider.send_request.assert_called_once()


async def test_secret_scan_marks_the_request_without_logging_the_secret(client):
    await set_secret_scan_enabled(True)
    secret = "AKIAIOSFODNN7EXAMPLE"
    channel, raw_key = await _ready_key()
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
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": f"use {secret} please"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    assert secret not in resp.text
    provider.send_request.assert_called_once()
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.security_hit == "aws_access_key"
    assert secret not in log.error_message
    assert secret not in log.security_hit


async def test_disabled_filter_does_not_block(client):
    await SecurityKeyword.create(keyword="Project Atlas", keyword_key="project atlas", direction="both")
    channel, raw_key = await _ready_key()
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value={
        **MOCK_COMPLETION_RESPONSE,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    })
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()

    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Project Atlas"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200


async def test_security_api_requires_permission(client):
    admin = await create_admin("security-admin", "pw")
    token = create_access_token({"sub": str(admin.id)})
    denied = await client.get("/api/security")
    assert denied.status_code == 401

    created = await client.post(
        "/api/security/keywords",
        json={"keyword": "internal codename", "direction": "both"},
        headers=auth_header(token),
    )
    assert created.status_code == 201
    updated = await client.put(
        "/api/security",
        json={"enabled": True},
        headers=auth_header(token),
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is True

    current = await client.get("/api/security", headers=auth_header(token))
    assert current.json()["keywords"][0]["keyword"] == "internal codename"


def _provider(content: str = "ok"):
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value={
        **MOCK_COMPLETION_RESPONSE,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    })
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()
    return provider


async def _post(client, channel, provider, raw_key: str, content: str):
    with patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        return await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": content}]},
            headers=auth_header(raw_key),
        )


async def test_request_keyword_does_not_block_the_reply(client):
    await SecurityKeyword.create(keyword="Project Atlas", keyword_key="project atlas", direction="request")
    await set_keyword_filter_enabled(True)
    channel, raw_key = await _ready_key()
    provider = _provider("the reply mentions Project Atlas")
    resp = await _post(client, channel, provider, raw_key, "hello")
    assert resp.status_code == 200
    assert "Project Atlas" in resp.text
    provider.send_request.assert_called_once()


async def test_disabled_keyword_is_ignored(client):
    await SecurityKeyword.create(
        keyword="Project Atlas",
        keyword_key="project atlas",
        direction="both",
        is_enabled=False,
    )
    await set_keyword_filter_enabled(True)
    channel, raw_key = await _ready_key()
    provider = _provider()
    resp = await _post(client, channel, provider, raw_key, "Project Atlas")
    assert resp.status_code == 200
    provider.send_request.assert_called_once()


async def test_secret_scan_marks_the_response_and_still_returns_it(client):
    await set_secret_scan_enabled(True)
    secret = "ghp_" + "b" * 24
    channel, raw_key = await _ready_key()
    provider = _provider(f"use {secret}")
    resp = await _post(client, channel, provider, raw_key, "hi")
    assert resp.status_code == 200
    assert secret in resp.text
    provider.send_request.assert_called_once()
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.status_code == 200
    assert log.security_hit == "github_token"
    assert secret not in log.error_message
    assert secret not in log.security_hit


async def test_exempt_key_skips_checks_and_request_storage(client):
    await SecurityKeyword.create(keyword="Project Atlas", keyword_key="project atlas", direction="request")
    await set_keyword_filter_enabled(True)
    await set_inference_audit_enabled(True)
    channel, raw_key = await _ready_key()
    key = await APIKey.get(key_hash=hash_api_key(raw_key))
    key.audit_policy = "off"
    await key.save()
    provider = _provider("ok")
    resp = await _post(client, channel, provider, raw_key, "notes about Project Atlas")
    assert resp.status_code == 200
    provider.send_request.assert_called_once()
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    assert log.has_audit is False
    assert log.security_hit == ""


async def test_secret_scan_off_allows_the_token(client):
    secret = "AKIAIOSFODNN7EXAMPLE"
    channel, raw_key = await _ready_key()
    provider = _provider("ok")
    resp = await _post(client, channel, provider, raw_key, f"key {secret}")
    assert resp.status_code == 200
    provider.send_request.assert_called_once()


async def test_security_writes_require_more_than_read(client):
    role = await Role.create(name="Security Reader", permissions=["security:read"])
    reader = await User.create(
        username="security-reader",
        hashed_password=hash_password("pw"),
        role=role,
    )
    headers = auth_header(create_access_token({"sub": str(reader.id)}))
    listed = await client.get("/api/security", headers=headers)
    assert listed.status_code == 200
    denied = await client.put("/api/security", json={"enabled": True}, headers=headers)
    assert denied.status_code == 403
    denied_audit = await client.put(
        "/api/security/inference-audit",
        json={"enabled": True},
        headers=headers,
    )
    assert denied_audit.status_code == 403

    admin = await create_admin("security-writer", "pw")
    admin_headers = auth_header(create_access_token({"sub": str(admin.id)}))
    secret = await client.put(
        "/api/security/secret-scan",
        json={"enabled": True},
        headers=admin_headers,
    )
    assert secret.status_code == 200
    assert secret.json()["enabled"] is True
    audit = await client.put(
        "/api/security/ai-audit",
        json={"enabled": False, "model": "deepseek-v4-flash", "fail_closed": True},
        headers=admin_headers,
    )
    assert audit.status_code == 200
    assert audit.json()["enabled"] is False
    assert audit.json()["fail_closed"] is True
    current = await client.get("/api/security", headers=admin_headers)
    assert current.json()["secret_scan_enabled"] is True
    assert current.json()["ai_audit"]["model"] == "deepseek-v4-flash"
