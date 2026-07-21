import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.models import APIKey
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import BaseProvider
from app.providers.registry import resolve_candidates
from app.schemas.anthropic import AnthropicMessagesRequest
from app.services.anthropic_compat import (
    anthropic_to_openai_request,
    openai_stream_to_anthropic_stream,
    openai_to_anthropic_response,
)
from app.services.auth import verify_api_key_anthropic
from app.services.concurrency import ConcurrencyExceeded, concurrency_limiter
from app.services.pre_checks import anthropic_error, run_pre_checks
from app.services.proxy import execute_with_failover, extract_openai_usage, stream_with_failover
from app.services.sticky_session import get_sticky_channel, make_session_key
from app.utils.ip_check import get_client_ip

router = APIRouter(tags=["anthropic-proxy"])


def _extract_anthropic_usage(resp: dict) -> dict:
    """从 Anthropic 响应中提取 usage。

    Anthropic 的 input_tokens 不含缓存 token，而计费按 OpenAI 口径（prompt_tokens
    含全部输入）。这里把 cache_read + cache_creation 补进 prompt_tokens，
    cached_tokens 只取 cache_read（享受缓存折扣价）。
    """
    usage = resp.get("usage", {})
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
    return {
        "prompt_tokens": (usage.get("input_tokens", 0) or 0) + cache_read + cache_creation,
        "completion_tokens": usage.get("output_tokens", 0) or 0,
        "cached_tokens": cache_read,
    }


def _anthropic_error_event(e: Exception) -> str:
    """生成 Anthropic 格式的 SSE 错误事件。"""
    err = {"type": "error", "error": {"type": "api_error", "message": f"Upstream error: {e}"}}
    return f"event: error\ndata: {json.dumps(err)}\n\n"


async def _passthrough_stream_with_usage(
    provider: AnthropicProvider,
    body: dict,
    extra_headers: dict[str, str] | None,
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (sse_line, usage_dict)，从 Anthropic SSE 流中提取 token 用量。

    Anthropic 的 input_tokens 不含缓存 token，计费按 OpenAI 口径补齐：
    prompt_tokens = input_tokens + cache_read + cache_creation，cached_tokens 取 cache_read。
    """
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_creation = 0

    async for line in provider.stream_anthropic_passthrough(body, extra_headers):
        stripped = line.strip()
        if stripped.startswith("data:"):
            try:
                data = json.loads(stripped[5:].strip())
                event_msg = data.get("message", {})
                if event_msg:
                    u = event_msg.get("usage", {})
                    input_tokens = u.get("input_tokens", input_tokens)
                    cache_read = u.get("cache_read_input_tokens", cache_read)
                    cache_creation = u.get("cache_creation_input_tokens", cache_creation)
                delta_usage = data.get("usage", {})
                if delta_usage:
                    output_tokens = delta_usage.get("output_tokens", output_tokens)
            except (json.JSONDecodeError, ValueError):
                pass

        yield line, {
            "prompt_tokens": input_tokens + cache_read + cache_creation,
            "completion_tokens": output_tokens,
            "cached_tokens": cache_read,
        }


@router.post("/v1/messages")
async def messages(
    request: Request,
    body: AnthropicMessagesRequest,
    api_key: APIKey = Depends(verify_api_key_anthropic),
):
    await run_pre_checks(api_key, body.model, anthropic_error)

    raw_body = json.loads(await request.body())
    session_key = make_session_key(api_key.id, request.headers, raw_body)
    sticky_channel_id = await get_sticky_channel(session_key)

    candidates = await resolve_candidates(
        body.model, preferred_protocol="anthropic", sticky_channel_id=sticky_channel_id,
    )
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        anthropic_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")

    extra_headers = {
        k: v for k, v in request.headers.items()
        if k.startswith("anthropic-")
    }

    if body.stream:
        async def _stream_fn(provider: BaseProvider, channel):
            is_passthrough = channel.provider == "anthropic" and isinstance(provider, AnthropicProvider)
            if is_passthrough:
                async for line, usage in _passthrough_stream_with_usage(provider, raw_body, extra_headers):
                    yield line, usage
            else:
                openai_body = anthropic_to_openai_request(raw_body)
                openai_sse = provider.send_stream(openai_body, "/v1/chat/completions")
                async for line, usage in openai_stream_to_anthropic_stream(openai_sse, body.model):
                    yield line, usage

        return StreamingResponse(
            stream_with_failover(
                candidates, _stream_fn, api_key, "/v1/messages", body.model,
                request_id, start_time, ip, _anthropic_error_event,
                session_key=session_key,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def _send_fn(provider: BaseProvider, channel):
        is_passthrough = channel.provider == "anthropic" and isinstance(provider, AnthropicProvider)
        if is_passthrough:
            result = await provider.send_anthropic_passthrough(raw_body, extra_headers)
            return JSONResponse(content=result), _extract_anthropic_usage(result)
        else:
            openai_body = anthropic_to_openai_request(raw_body)
            result = await provider.send_request(openai_body, "/v1/chat/completions")
            return openai_to_anthropic_response(result, body.model), extract_openai_usage(result)

    return await execute_with_failover(
        candidates, _send_fn, api_key, "/v1/messages", body.model,
        request_id, start_time, ip, anthropic_error,
        session_key=session_key,
    )
