import io
import logging
from unittest.mock import AsyncMock, patch

import httpx

from app.models import RequestLog, RequestLogAudit
from app.services.error_detail import upstream_json_error
from app.services.redaction import RedactingFormatter, configure_safe_logging, redact, redact_upstream_error
from app.services.settings_service import set_inference_audit_enabled
from tests.conftest import auth_header
from tests.regression.test_error_origin import MOCK_COMPLETION_RESPONSE, _key_and_channel

AWS = "AKIAIOSFODNN7EXAMPLE"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
SLACK = "xoxb-1234567890-abcdefABCDEF"
PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAexample\n-----END RSA PRIVATE KEY-----"


def test_scanned_secret_formats_are_redacted_with_their_type():
    text = f"aws {AWS} gh {GITHUB} slack {SLACK}\n{PRIVATE_KEY}\nafter"
    result = redact(text)
    for secret in (AWS, GITHUB, SLACK, "MIIEowIBAAKCAQEAexample"):
        assert secret not in result
    for label in ("aws_access_key", "github_token", "slack_token", "private_key"):
        assert f"[REDACTED:{label}]" in result
    assert result.endswith("after")


def test_truncated_private_key_is_redacted_to_the_end():
    result = redact("key:\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA")
    assert result == "key:\n[REDACTED:private_key]"


def test_ordinary_text_is_not_redacted():
    text = "AKIA1234 is too short, github_token is a word, Limit is a word"
    assert redact(text) == text
    assert redact_upstream_error(text) == text


def test_upstream_error_hides_platform_account_details():
    body = {"error": {
        "message": ("Rate limit reached for gpt-4o in organization org-AbC123xyz789 on tokens per min (TPM): "
                    "Limit 30000, Used 29,500, Requested 1200. Project proj_Q1w2E3r4T5y6."),
        "type": "tokens", "code": "rate_limit_exceeded",
    }}
    message = redact_upstream_error(body)["error"]["message"]
    for leaked in ("org-AbC123xyz789", "30000", "29,500", "proj_Q1w2E3r4T5y6"):
        assert leaked not in message
    assert "Requested 1200" in message
    assert "Rate limit reached for gpt-4o" in message


def test_anthropic_rate_limit_hides_organization_and_quota():
    message = ("This request would exceed the rate limit for your organization "
               "(8f2c1a34-1111-4222-8333-123456789abc) of 50,000 input tokens per minute.")
    result = redact_upstream_error(message)
    assert "8f2c1a34" not in result and "50,000" not in result
    assert "input tokens per minute" in result


def test_context_length_errors_keep_their_numbers():
    message = "This model's maximum context length is 128000 tokens. However, you requested 130000 tokens."
    assert redact_upstream_error(message) == message


def test_upstream_json_error_forwarded_to_client_is_scrubbed():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        429, request=request,
        json={"error": {"message": "in organization org-AbC123xyz789: Limit 100, Used 99", "type": "requests"}},
    )
    status, body = upstream_json_error(httpx.HTTPStatusError("429", request=request, response=response))
    assert status == 429
    assert "org-AbC123xyz789" not in body["error"]["message"]
    assert "Limit [REDACTED], Used [REDACTED]" in body["error"]["message"]


def test_app_logs_are_redacted_without_a_root_handler():
    app_logger = logging.getLogger("app")
    root = logging.getLogger()
    saved_app, saved_root = app_logger.handlers[:], root.handlers[:]
    app_logger.handlers, root.handlers = [], []
    try:
        configure_safe_logging()
        assert app_logger.handlers and isinstance(app_logger.handlers[0].formatter, RedactingFormatter)
        stream = io.StringIO()
        app_logger.handlers[0].setStream(stream)
        logging.getLogger("app.services.example").warning("upstream failed Bearer sk-live1234567890abcd %s", AWS)
        output = stream.getvalue()
        assert "sk-live1234567890abcd" not in output and AWS not in output
        assert "upstream failed" in output
    finally:
        app_logger.handlers, root.handlers = saved_app, saved_root


async def test_stored_audit_content_has_secrets_removed(client):
    await set_inference_audit_enabled(True)
    channel, raw_key = await _key_and_channel("https://api.openai.com")
    provider = AsyncMock()
    provider.send_request = AsyncMock(return_value=MOCK_COMPLETION_RESPONSE)
    provider.apply_model_mapping = lambda model: model
    provider.close = AsyncMock()

    with patch("app.services.routing.resolve_with_fallbacks", return_value=[(channel, lambda _: provider)]):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": f"deploy with {AWS} please"}]},
            headers=auth_header(raw_key),
        )

    assert resp.status_code == 200
    log = await RequestLog.get(request_id=resp.headers["x-request-id"])
    audit = await RequestLogAudit.get(request_log_id=log.id)
    assert AWS not in audit.audit_request
    assert "[REDACTED:aws_access_key]" in audit.audit_request
    assert "deploy with" in audit.audit_request
    sent = provider.send_request.await_args.args[0]
    assert AWS in str(sent)
