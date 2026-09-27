import json
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse

from app.main import resolve_frontend_file
from app.services.audit import (
    AuditBuffer,
    MAX_AUDIT_CHARS,
    request_excerpt,
    response_visible_text,
    saved_transcript,
    security_exempt,
    sse_visible_text,
)
from app.services.ai_audit import build_excerpt


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


def test_request_excerpt_keeps_a_valid_tail_and_drops_tool_schemas():
    body = {
        "model": "deepseek-v4-pro",
        "tools": [{"name": "bash", "input_schema": {"type": "object", "description": "x" * 8000}}],
        "messages": [
            *[{"role": "user", "content": f"turn {index}"} for index in range(50)],
            {"role": "user", "content": "HEAD-MARKER " + ("a" * 20000) + " TAIL-MARKER"},
        ],
    }
    text = request_excerpt(body)
    saved = json.loads(text)
    assert len(text) <= MAX_AUDIT_CHARS
    assert "HEAD-MARKER" in text
    assert "TAIL-MARKER" in text
    assert "input_schema" not in text
    assert saved["tools"] == ["bash"]
    transcript = saved_transcript(text)
    assert "TAIL-MARKER" in transcript
    assert "turn 0" not in transcript


def test_saved_transcript_shows_raw_text_when_json_was_sliced():
    stored = '{"messages":[{"role":"user","content":"hello' + "\n…[truncated]"
    assert saved_transcript(stored) == stored


def test_review_excerpt_keeps_the_end_of_a_long_user_message():
    body = {
        "system": "policy " + ("p" * 2000),
        "messages": [{"role": "user", "content": "UNIQUE-HEAD " + ("x" * 3000) + " FINAL-QUESTION"}],
    }
    excerpt = build_excerpt(body)
    assert excerpt.startswith("system:\npolicy")
    assert "FINAL-QUESTION" in excerpt
    assert "UNIQUE-HEAD" not in excerpt


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
