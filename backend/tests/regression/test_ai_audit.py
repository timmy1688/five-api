from unittest.mock import AsyncMock, patch

import pytest

from app.models import RequestLog
from app.services.ai_audit import build_excerpt, parse_verdict
from app.services.auth import create_access_token
from app.services.settings_service import set_ai_audit_config, set_inference_audit_enabled
from tests.conftest import auth_header, create_admin
from tests.regression.test_content_filter import MOCK_COMPLETION_RESPONSE, _ready_key

pytestmark = pytest.mark.regression


def test_excerpt_keeps_system_and_latest_user_message_only():
    body = {
        "messages": [
            {"role": "system", "content": "follow the data policy"},
            {"role": "user", "content": "first turn mentions the warehouse layout"},
            {"role": "assistant", "content": "noted"},
            {"role": "user", "content": "latest message about the customer export file"},
        ],
    }
    excerpt = build_excerpt(body)
    assert "data policy" in excerpt
    assert "customer export" in excerpt
    assert "warehouse layout" not in excerpt
    assert len(excerpt) < 2000


def test_review_request_disables_thinking_before_a_larger_retry():
    from app.services.ai_audit import _message_text, _request_variants

    bodies = _request_variants("deepseek-v4-flash", "user:\nhello from the latest turn")
    assert bodies[0]["thinking"] == {"type": "disabled"}
    assert bodies[0]["max_tokens"] < bodies[1]["max_tokens"]
    assert "thinking" not in bodies[1]
    assert _message_text({"choices": [{"message": {"content": '{"block": false}'}}]}) == '{"block": false}'
    assert _message_text({"choices": [{"message": {"content": "", "reasoning_content": "still thinking"}}]}) == ""


def test_parse_verdict_ignores_unknown_category_text():
    block, category = parse_verdict('sure {"block": true, "category": "AKIASECRETKEY"}')
    assert block is True
    assert category == "other"


async def test_ai_review_is_manual_and_keeps_only_the_latest_turn(client):
    await set_inference_audit_enabled(True)
    await set_ai_audit_config(enabled=True, model="deepseek-v4-flash", fail_closed=False)
    calls: list[tuple[str, str]] = []

    async def fake_complete(model, excerpt):
        calls.append((model, excerpt))
        return '{"block": true, "category": "credential"}'

    channel, raw_key = await _ready_key()
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "follow the data policy"},
            {"role": "user", "content": "first turn mentions the warehouse layout"},
            {"role": "assistant", "content": "noted"},
            {"role": "user", "content": "latest message about the customer export file"},
        ],
    }
    admin = await create_admin("audit-reviewer", "pw")
    headers = auth_header(create_access_token({"sub": str(admin.id)}))

    with patch("app.services.ai_audit._complete", fake_complete), patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        resp = await client.post("/v1/chat/completions", json=payload, headers=auth_header(raw_key))
        again = await client.post("/v1/chat/completions", json=payload, headers=auth_header(raw_key))
        assert calls == []
        reviewed = await client.post(
            "/api/audit/review",
            json={"request_ids": [resp.headers["x-request-id"], again.headers["x-request-id"]]},
            headers=headers,
        )

    assert resp.status_code == 200
    assert again.status_code == 200
    request_id = resp.headers["x-request-id"]
    assert reviewed.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == "deepseek-v4-flash"
    assert "warehouse layout" not in calls[0][1]
    assert "customer export" in calls[0][1]
    assert provider.send_request.await_count == 2
    log = await RequestLog.get(request_id=request_id)
    assert log.ai_review == "flagged:credential"
    assert "customer export" not in log.ai_review
    people = await client.get("/api/audit/keys", headers=headers)
    assert people.status_code == 200
    assert any(item["request_count"] >= 1 for item in people.json()["items"])


async def test_ai_review_failure_does_not_change_the_request(client):
    await set_inference_audit_enabled(True)
    await set_ai_audit_config(enabled=True, model="deepseek-v4-flash", fail_closed=True)
    channel, raw_key = await _ready_key()
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "please summarize the quarterly customer export"}],
    }

    async def broken(*_args):
        raise TimeoutError("auditor down")

    admin = await create_admin("audit-failure", "pw")
    headers = auth_header(create_access_token({"sub": str(admin.id)}))
    with patch("app.services.ai_audit._complete", broken), patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        allowed = await client.post("/v1/chat/completions", json=payload, headers=auth_header(raw_key))
        reviewed = await client.post(
            "/api/audit/review",
            json={"request_ids": [allowed.headers["x-request-id"]]},
            headers=headers,
        )

    assert allowed.status_code == 200
    assert reviewed.status_code == 200
    assert reviewed.json()["items"][0]["ai_review"] == "unavailable"
    provider.send_request.assert_called_once()


async def test_ai_review_skips_short_text_and_rejects_a_large_batch(client):
    await set_inference_audit_enabled(True)
    await set_ai_audit_config(enabled=True, model="deepseek-v4-flash", fail_closed=False)
    channel, raw_key = await _ready_key()
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()
    calls: list[str] = []

    async def fake_complete(_model, excerpt):
        calls.append(excerpt)
        return '{"block": true, "category": "credential"}'

    admin = await create_admin("audit-short", "pw")
    headers = auth_header(create_access_token({"sub": str(admin.id)}))
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    with patch("app.services.ai_audit._complete", fake_complete), patch(
        "app.routers.openai_proxy.resolve_candidates",
        return_value=[(channel, lambda _: provider)],
    ):
        short = await client.post("/v1/chat/completions", json=payload, headers=auth_header(raw_key))
    reviewed = await client.post(
        "/api/audit/review",
        json={"request_ids": [short.headers["x-request-id"]]},
        headers=headers,
    )

    assert short.status_code == 200
    assert reviewed.status_code == 200
    assert reviewed.json()["items"][0]["ai_review"] == "skipped"
    assert calls == []
    too_many = await client.post(
        "/api/audit/review",
        json={"request_ids": [f"id-{i}" for i in range(21)]},
        headers=headers,
    )
    assert too_many.status_code == 422
    off = await set_ai_audit_config(enabled=False, model="deepseek-v4-flash", fail_closed=False)
    assert off["enabled"] is False
    denied = await client.post(
        "/api/audit/review",
        json={"request_ids": [short.headers["x-request-id"]]},
        headers=headers,
    )
    assert denied.status_code == 400
