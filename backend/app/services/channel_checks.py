"""On-demand native endpoint checks; results never change health or customer billing."""
import asyncio
import json
import time

import anyio
import httpx

from app.models import Channel
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import read_error_body
from app.providers.openai_provider import OpenAIProvider
from app.schemas.channel import ChannelCheckResult
from app.services.redaction import redact
from app.utils.upstream_url import upstream_url

CHECK_TIMEOUT_SECONDS = 15
OPENAI_CHECKS = ("models", "chat", "chat_stream", "responses", "responses_stream")
ANTHROPIC_CHECKS = ("models", "messages", "messages_stream")


class CheckFailed(Exception):
    pass


def _text_content(content) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and any(
        isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"].strip()
        for part in content
    )


def _has_text(data: dict, kind: str) -> bool:
    if kind.startswith("responses"):
        output = data.get("output")
        return isinstance(output, list) and any(
            isinstance(item, dict) and _text_content(item.get("content"))
            for item in output
        )
    if kind.startswith("messages"):
        return _text_content(data.get("content"))
    choices = data.get("choices")
    return isinstance(choices, list) and any(
        isinstance(choice, dict) and isinstance(choice.get("message"), dict)
        and _text_content(choice["message"].get("content")) for choice in choices
    )


def _error_message(data: dict, fallback: str) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or fallback)
    return str(error or data.get("message") or fallback)


def _payload(provider, model: str, kind: str) -> dict:
    if kind.startswith("responses"):
        return {"model": model, "input": "Reply with OK.", "max_output_tokens": 256,
                "stream": kind.endswith("_stream")}
    body = {"model": model, "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": kind.endswith("_stream")}
    actual = provider.apply_model_mapping(model).lower()
    if kind.startswith("chat") and actual.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
        body["max_completion_tokens"] = 256
    else:
        body["max_tokens"] = 64
    return body


def _request(provider, model: str, kind: str) -> httpx.Request:
    anthropic = provider.channel.provider == "anthropic"
    if kind == "models":
        headers = provider._anthropic_headers() if anthropic else provider._auth_headers()
        return provider.client.build_request(
            "GET", upstream_url(provider.channel.base_url, "/v1/models"), headers=headers,
        )
    body = _payload(provider, model, kind)
    if anthropic:
        body["model"] = provider.apply_model_mapping(model)
        path, headers = provider._path("messages"), provider._anthropic_headers()
    else:
        endpoint = "/v1/responses" if kind.startswith("responses") else "/v1/chat/completions"
        path, headers, body = provider.prepare_request(body, endpoint)
    return provider.client.build_request("POST", path, json=body, headers=headers)


def _validate_json(data, kind: str) -> None:
    if not isinstance(data, dict):
        raise CheckFailed("Expected a JSON object from the upstream")
    if data.get("error"):
        raise CheckFailed(_error_message(data, "Upstream returned an error"))
    if kind == "models":
        models = data.get("data")
        if not isinstance(models, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in models
        ):
            raise CheckFailed("Expected a model list in data[]")
    else:
        if kind.startswith("responses") and data.get("status") != "completed":
            raise CheckFailed("Response did not complete: " + str(data.get("status") or "missing status"))
        if not _has_text(data, kind):
            raise CheckFailed("HTTP succeeded but the response contains no generated text")


async def _sse_payloads(response: httpx.Response):
    parts = []
    async for line in response.aiter_lines():
        if not line and parts:
            yield "\n".join(parts)
            parts = []
        elif line.startswith("data:"):
            parts.append(line[5:].removeprefix(" "))
    if parts:
        yield "\n".join(parts)


async def _validate_stream(response: httpx.Response, kind: str, started: float) -> int | None:
    if "text/event-stream" not in response.headers.get("content-type", "").lower():
        raise CheckFailed("Expected text/event-stream from a streaming request")
    terminal = False
    first_text_ms = None
    async for raw in _sse_payloads(response):
        raw = raw.strip()
        if raw == "[DONE]" and kind == "chat_stream":
            terminal = True
            break
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            raise CheckFailed("Stream contains invalid JSON data") from None
        if not isinstance(data, dict):
            raise CheckFailed("Stream contains a non-object data event")
        event = data.get("type")
        if data.get("error") or event in {"error", "response.failed", "response.incomplete"}:
            failure = data.get("response") if isinstance(data.get("response"), dict) else data
            raise CheckFailed(_error_message(failure, str(event or "Upstream stream error")))
        has_text = False
        if kind == "chat_stream":
            choices = data.get("choices")
            if isinstance(choices, list):
                has_text = any(
                    isinstance(choice, dict) and isinstance(choice.get("delta"), dict)
                    and _text_content(choice["delta"].get("content")) for choice in choices
                )
        elif kind == "responses_stream":
            has_text = event == "response.output_text.delta" and _text_content(data.get("delta"))
            terminal = event == "response.completed"
            if terminal:
                result = data.get("response")
                if not isinstance(result, dict):
                    raise CheckFailed("response.completed is missing its response object")
                _validate_json(result, "responses")
                has_text = True
        else:
            delta = data.get("delta")
            has_text = isinstance(delta, dict) and _text_content(delta.get("text"))
            terminal = event == "message_stop"
        if has_text and first_text_ms is None:
            first_text_ms = round((time.monotonic() - started) * 1000)
        if terminal:
            break
    if not terminal:
        raise CheckFailed("Stream ended without its terminal event")
    if first_text_ms is None:
        raise CheckFailed("Stream completed without generated text")
    return first_text_ms


def _failure(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.json()
        except ValueError:
            body = None
        fallback = f"Upstream HTTP {exc.response.status_code}"
        message = _error_message(body, fallback) if isinstance(body, dict) else fallback
    elif isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        message = "Upstream check timed out"
    elif isinstance(exc, httpx.RequestError):
        message = "Unable to connect to the upstream"
    elif isinstance(exc, (CheckFailed, ValueError)):
        message = str(exc)
    else:
        message = "Upstream check failed"
    return redact(message)[:500]


async def _check(provider, model: str, kind: str) -> ChannelCheckResult:
    started = time.monotonic()
    response = None
    first_text_ms = None
    status = "passed"
    error = ""
    try:
        async with asyncio.timeout(min(provider.channel.timeout, CHECK_TIMEOUT_SECONDS)):
            stream = kind.endswith("_stream")
            response = await provider.client.send(_request(provider, model, kind), stream=stream)
            await read_error_body(response)
            if stream:
                first_text_ms = await _validate_stream(response, kind, started)
            else:
                try:
                    data = response.json()
                except ValueError:
                    raise CheckFailed("Expected JSON, received a non-JSON response") from None
                _validate_json(data, kind)
    except Exception as exc:
        status = "timeout" if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else "failed"
        error = _failure(exc)
    finally:
        if response is not None:
            with anyio.move_on_after(1, shield=True):
                await response.aclose()
    return ChannelCheckResult(
        kind=kind, status=status, status_code=response.status_code if response is not None else None,
        latency_ms=round((time.monotonic() - started) * 1000), first_text_ms=first_text_ms, error=error,
    )


async def run_channel_checks(channel: Channel, model: str) -> list[ChannelCheckResult]:
    """One available upstream key, one model, no failover; each check is bounded to 15s."""
    kinds = ANTHROPIC_CHECKS if channel.provider == "anthropic" else OPENAI_CHECKS
    provider = None
    try:
        provider = AnthropicProvider(channel) if channel.provider == "anthropic" else OpenAIProvider(channel)
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            if not await provider.has_ready_key():
                raise CheckFailed("All upstream keys on this channel are cooling down")
            await provider.select_key()
        return [await _check(provider, model, kind) for kind in kinds]
    except Exception as exc:
        status = "timeout" if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else "failed"
        return [ChannelCheckResult(kind=kind, status=status, error=_failure(exc)) for kind in kinds]
    finally:
        if provider is not None:
            await provider.close()
