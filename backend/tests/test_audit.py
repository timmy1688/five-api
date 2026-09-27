from pathlib import Path

import pytest
from fastapi.responses import JSONResponse

from app.main import resolve_frontend_file
from app.services.audit import (
    AuditBuffer,
    request_excerpt,
    response_visible_text,
    security_exempt,
    sse_visible_text,
)


def test_request_excerpt_drops_inline_image_payload():
    body = {
        "model": "gpt-4o",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + ("A" * 500)}},
            ],
        }],
    }
    text = request_excerpt(body)
    assert "describe this" in text
    assert "A" * 200 not in text
    assert "omitted" in text


def test_response_visible_text_reads_openai_and_anthropic():
    openai = {
        "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
    }
    assert response_visible_text(openai) == "Hello!"
    anthropic = JSONResponse(content={
        "content": [
            {"type": "text", "text": "Hi"},
            {"type": "tool_use", "name": "lookup", "input": {"q": "x"}},
        ],
    })
    text = response_visible_text(anthropic)
    assert "Hi" in text
    assert "lookup" in text


def test_sse_visible_text_assembles_both_protocols():
    openai_line = 'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
    anthropic_line = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}\n\n'
    usage_line = 'data: {"usage":{"prompt_tokens":3}}\n\n'
    assert sse_visible_text(openai_line) == "Hel"
    assert sse_visible_text(anthropic_line) == "lo"
    assert sse_visible_text(usage_line) == ""
    audit = AuditBuffer({"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]})
    assert "hi" in audit.request_text


def test_security_exempt_is_only_explicitly_off():
    class Off:
        audit_policy = "off"

    class On:
        audit_policy = "on"

    assert security_exempt(Off()) is True
    assert security_exempt(On()) is False
    assert security_exempt(object()) is False


def test_frontend_files_do_not_swallow_api_routes(tmp_path: Path):
    static = tmp_path / "static"
    assets = static / "assets"
    assets.mkdir(parents=True)
    script = assets / "app.js"
    script.write_text("console.log(1)", encoding="utf-8")
    (static / "index.html").write_text("<html></html>", encoding="utf-8")

    assert resolve_frontend_file(static, "assets/app.js") == script.resolve()
    assert resolve_frontend_file(static, "channels") is None
    assert resolve_frontend_file(static, "") is None
    with pytest.raises(LookupError):
        resolve_frontend_file(static, "api/keys")
    with pytest.raises(LookupError):
        resolve_frontend_file(static, "v1/messages")
    assert resolve_frontend_file(static, "assets/../../etc/passwd") is None
