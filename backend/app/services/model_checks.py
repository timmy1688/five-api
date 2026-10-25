"""Small synthetic probes. Scores describe these checks, never model identity."""
import asyncio
import json
import secrets
import time

import httpx

from app.models import Channel, ModelProbe, User
from app.providers.openai_provider import OpenAIProvider
from app.providers.anthropic_provider import AnthropicProvider
from app.services.redaction import redact

SUITE_VERSION = "mvp-v1"


def supports_capability(model: str) -> bool:
    return model.lower().startswith(("gpt-", "claude-", "o1", "o3", "o4"))


def _text(data, anthropic):
    if anthropic:
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    message = (data.get("choices") or [{}])[0].get("message", {})
    return message.get("content") or ""


def _tool(data, anthropic):
    if anthropic:
        block = next((block for block in data.get("content", []) if block.get("type") == "tool_use"), {})
        return block.get("name"), block.get("input", {})
    calls = (data.get("choices") or [{}])[0].get("message", {}).get("tool_calls") or []
    function = calls[0].get("function", {}) if calls else {}
    try:
        arguments = json.loads(function.get("arguments", "{}"))
    except (ValueError, TypeError):
        arguments = {}
    return function.get("name"), arguments


async def _send(provider, model, prompt, *, tool=False, health=False):
    anthropic = provider.channel.provider == "anthropic"
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    if anthropic:
        body["max_tokens"] = 64 if health else 1024
    elif provider.apply_model_mapping(model).lower().startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
        body["max_completion_tokens"] = 256 if health else 1024
    else:
        body["max_tokens"] = 64 if health else 1024
    if tool:
        parameters = {"type": "object", "properties": {"answer": {"type": "integer"}},
                      "required": ["answer"], "additionalProperties": False}
        if anthropic:
            body["tools"] = [{"name": "report_result", "description": "Submit the answer", "input_schema": parameters}]
            body["tool_choice"] = {"type": "tool", "name": "report_result"}
        else:
            body["tools"] = [{"type": "function", "function": {
                "name": "report_result", "description": "Submit the answer", "parameters": parameters}}]
            body["tool_choice"] = {"type": "function", "function": {"name": "report_result"}}
    async with asyncio.timeout(min(provider.channel.timeout, 20)):
        if anthropic:
            return await provider.send_anthropic_passthrough(body)
        return await provider.send_request(body, "/v1/chat/completions")


def _failure(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Upstream HTTP {exc.response.status_code}"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "Upstream timeout"
    if isinstance(exc, httpx.RequestError):
        return "Upstream connection unavailable"
    return type(exc).__name__


async def run_probe(channel: Channel, model: str, kind: str, actor: User | None, source="manual") -> ModelProbe:
    actual = (channel.model_mapping or {}).get(model, model)
    provider = AnthropicProvider(channel) if channel.provider == "anthropic" else OpenAIProvider(channel)
    checks = []
    failure = ""
    started = time.monotonic()
    anthropic = channel.provider == "anthropic"
    try:
        await provider.select_key()
        if kind == "health":
            data = await _send(provider, model, "Reply with OK.", health=True)
            # A successful HTTP response must contain the native message shape.
            ok = isinstance(data.get("content" if anthropic else "choices"), list) and bool(
                data.get("content" if anthropic else "choices"))
            checks.append({"name": "inference", "passed": ok, "expected": "valid message response",
                           "actual": redact(_text(data, anthropic))[:160]})
        else:
            nonce = "FIVE_" + secrets.token_hex(4)
            a, b, c = secrets.randbelow(60) + 23, secrets.randbelow(40) + 13, secrets.randbelow(90) + 1
            expected = a * b + c
            cases = [
                ("instruction", f"Output exactly {nonce}. No quotes, explanation or punctuation.", False),
                ("reasoning", f"Compute {a} * {b} + {c}. Output only a JSON object with integer answer and marker \"{nonce}\".", False),
                ("tool_use", f"Call report_result with the integer result of {a} * {b} + {c}. Do not answer in text.", True),
            ]
            for name, prompt, tool in cases:
                data = await _send(provider, model, prompt, tool=tool)
                text = _text(data, anthropic)
                if name == "instruction":
                    ok, evidence = text.strip() == nonce, text
                elif name == "reasoning":
                    try:
                        answer = json.loads(text)
                        ok = type(answer.get("answer")) is int and answer.get("answer") == expected and answer.get("marker") == nonce
                    except (ValueError, TypeError, AttributeError):
                        ok = False
                    evidence = text
                else:
                    tool_name, arguments = _tool(data, anthropic)
                    ok = tool_name == "report_result" and isinstance(arguments, dict) and type(arguments.get("answer")) is int and arguments.get("answer") == expected
                    evidence = json.dumps({"tool": tool_name, "arguments": arguments})
                checks.append({"name": name, "passed": ok, "expected": nonce if name == "instruction" else str(expected),
                               "actual": redact(evidence)[:160]})
    except Exception as exc:
        failure = _failure(exc)
    finally:
        await provider.close()
    score = round(100 * sum(bool(check["passed"]) for check in checks) / 3) if kind == "capability" and not failure else None
    if failure:
        status = "unavailable"
    elif kind == "health":
        status = "healthy" if checks[0]["passed"] else "unavailable"
    else:
        status = "passed" if score == 100 else "review"
    return await ModelProbe.create(
        channel_id=channel.id, model=model, actual_model=actual, kind=kind, status=status,
        suite_version=SUITE_VERSION, latency_ms=round((time.monotonic()-started)*1000), score=score,
        checks=checks, error=failure, actor_id=actor.id if actor else 0, run_source=source,
    )


def probe_response(record):
    return {field: getattr(record, field) for field in (
        "id", "channel_id", "model", "actual_model", "kind", "status", "suite_version", "run_source",
        "latency_ms", "score", "checks", "error", "created_at",
    )}
