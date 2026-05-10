import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.models import APIKey
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.registry import resolve_channel
from app.schemas.anthropic import AnthropicMessagesRequest
from app.services.anthropic_compat import (
    anthropic_to_openai_request,
    openai_stream_to_anthropic_stream,
    openai_to_anthropic_response,
)
from app.services.auth import verify_api_key_anthropic
from app.services.concurrency import ConcurrencyExceeded, concurrency_limiter
from app.services.logging_service import save_request_log
from app.services.pricing import calculate_cost
from app.services.proxy import stream_proxy
from app.services.quota import check_quota, deduct_quota

router = APIRouter(tags=["anthropic-proxy"])


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _anthropic_error(status_code: int, error_type: str, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"type": "error", "error": {"type": error_type, "message": message}},
    )


def _extract_anthropic_usage(resp: dict) -> tuple[int, int, int]:
    """Extract (input_tokens, output_tokens, cached_tokens) from Anthropic response."""
    usage = resp.get("usage", {})
    return (
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("cache_read_input_tokens", 0),
    )


async def _passthrough_stream_with_usage(
    provider: AnthropicProvider,
    body: dict,
    extra_headers: dict[str, str] | None,
) -> AsyncIterator[tuple[str, int, int, int]]:
    """Yield (sse_line, input_tokens, output_tokens, cached_tokens).

    Token counts are cumulative; only updated when relevant SSE events arrive.
    The caller should use the final values after iteration completes.
    """
    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0

    async for line in provider.stream_anthropic_passthrough(body, extra_headers):
        stripped = line.strip()
        if stripped.startswith("data:"):
            data_str = stripped[5:].strip()
            try:
                data = json.loads(data_str)
                event_msg = data.get("message", {})
                if event_msg:
                    u = event_msg.get("usage", {})
                    input_tokens = u.get("input_tokens", input_tokens)
                    cached_tokens = u.get("cache_read_input_tokens", cached_tokens)
                delta_usage = data.get("usage", {})
                if delta_usage:
                    output_tokens = delta_usage.get("output_tokens", output_tokens)
            except (json.JSONDecodeError, ValueError):
                pass

        yield line, input_tokens, output_tokens, cached_tokens


@router.post("/v1/messages")
async def messages(
    request: Request,
    body: AnthropicMessagesRequest,
    api_key: APIKey = Depends(verify_api_key_anthropic),
):
    if not await check_quota(api_key):
        _anthropic_error(429, "rate_limit_error", "Spending quota exceeded")

    if api_key.allowed_models and body.model not in api_key.allowed_models:
        _anthropic_error(403, "invalid_request_error", f"Model {body.model} not allowed for this key")

    channel, provider = await resolve_channel(body.model)
    request_id = getattr(request.state, "request_id", "")
    ip = _get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        await provider.close()
        _anthropic_error(429, "rate_limit_error", "Too many concurrent requests")

    if channel.provider == "anthropic" and isinstance(provider, AnthropicProvider):
        raw_body = json.loads(await request.body())
        extra_headers = {
            k: v for k, v in request.headers.items()
            if k.startswith("anthropic-")
        }
        return await _handle_anthropic_passthrough(
            provider, raw_body, extra_headers, body, channel, api_key,
            request_id, start_time, ip,
        )

    # ── Fallback: convert Anthropic → OpenAI and route through normal pipeline ──
    openai_body = anthropic_to_openai_request(body.model_dump())

    if body.stream:
        openai_sse = stream_proxy(
            provider, openai_body, "/v1/chat/completions",
            channel, api_key, request_id, start_time, ip,
        )
        anthropic_sse = openai_stream_to_anthropic_stream(openai_sse, body.model)
        return StreamingResponse(
            anthropic_sse,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await provider.send_request(openai_body, "/v1/chat/completions")
        latency_ms = int((time.monotonic() - start_time) * 1000)
        usage = result.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        model_actual = provider.apply_model_mapping(body.model)

        cost = await calculate_cost(model_actual, prompt_tokens, completion_tokens, channel, cached_tokens=cached_tokens)
        if cost > 0:
            await deduct_quota(api_key.id, cost)

        await save_request_log(
            request_id=request_id,
            api_key_id=api_key.id, api_key_name=api_key.name,
            channel_id=channel.id, channel_name=channel.name,
            model_requested=body.model, model_actual=model_actual,
            provider=channel.provider, endpoint="/v1/messages",
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost=cost, is_stream=False, status_code=200,
            latency_ms=latency_ms, ip_address=ip,
        )
        return openai_to_anthropic_response(result, body.model)

    except HTTPException:
        raise
    except Exception as e:
        latency_ms = int((time.monotonic() - start_time) * 1000)
        await save_request_log(
            request_id=request_id,
            api_key_id=api_key.id, api_key_name=api_key.name,
            channel_id=channel.id, channel_name=channel.name,
            model_requested=body.model,
            model_actual=provider.apply_model_mapping(body.model),
            provider=channel.provider, endpoint="/v1/messages",
            prompt_tokens=0, completion_tokens=0, cost=Decimal(0),
            is_stream=False, status_code=500, latency_ms=latency_ms,
            error_message=str(e), ip_address=ip,
        )
        _anthropic_error(502, "api_error", f"Upstream error: {e}")
    finally:
        await concurrency_limiter.release(api_key.id)
        await provider.close()


# ── Anthropic native pass-through handlers ──────────────────────────────────


async def _handle_anthropic_passthrough(
    provider: AnthropicProvider,
    raw_body: dict,
    extra_headers: dict[str, str],
    body: AnthropicMessagesRequest,
    channel,
    api_key: APIKey,
    request_id: str,
    start_time: float,
    ip: str,
):
    """Route Anthropic requests directly to an Anthropic-compatible upstream."""
    model_actual = provider.apply_model_mapping(body.model)

    if body.stream:
        return StreamingResponse(
            _passthrough_stream_generator(
                provider, raw_body, extra_headers, body, channel,
                api_key, request_id, start_time, ip, model_actual,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await provider.send_anthropic_passthrough(raw_body, extra_headers)
        latency_ms = int((time.monotonic() - start_time) * 1000)
        prompt_tokens, completion_tokens, cached_tokens = _extract_anthropic_usage(result)

        cost = await calculate_cost(
            model_actual, prompt_tokens, completion_tokens, channel,
            cached_tokens=cached_tokens,
        )
        if cost > 0:
            await deduct_quota(api_key.id, cost)

        await save_request_log(
            request_id=request_id,
            api_key_id=api_key.id, api_key_name=api_key.name,
            channel_id=channel.id, channel_name=channel.name,
            model_requested=body.model, model_actual=model_actual,
            provider=channel.provider, endpoint="/v1/messages",
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost=cost, is_stream=False, status_code=200,
            latency_ms=latency_ms, ip_address=ip,
        )
        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        latency_ms = int((time.monotonic() - start_time) * 1000)
        await save_request_log(
            request_id=request_id,
            api_key_id=api_key.id, api_key_name=api_key.name,
            channel_id=channel.id, channel_name=channel.name,
            model_requested=body.model, model_actual=model_actual,
            provider=channel.provider, endpoint="/v1/messages",
            prompt_tokens=0, completion_tokens=0, cost=Decimal(0),
            is_stream=False, status_code=500, latency_ms=latency_ms,
            error_message=str(e), ip_address=ip,
        )
        _anthropic_error(502, "api_error", f"Upstream error: {e}")
    finally:
        await concurrency_limiter.release(api_key.id)
        await provider.close()


async def _passthrough_stream_generator(
    provider: AnthropicProvider,
    raw_body: dict,
    extra_headers: dict[str, str],
    body: AnthropicMessagesRequest,
    channel,
    api_key: APIKey,
    request_id: str,
    start_time: float,
    ip: str,
    model_actual: str,
) -> AsyncIterator[str]:
    """Stream Anthropic SSE pass-through, extract usage for billing in finally."""
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    status_code = 200
    error_msg = ""

    try:
        async for line, pt, ct, cct in _passthrough_stream_with_usage(
            provider, raw_body, extra_headers,
        ):
            prompt_tokens, completion_tokens, cached_tokens = pt, ct, cct
            yield line
    except Exception as e:
        status_code = 500
        error_msg = str(e)
        err_event = {
            "type": "error",
            "error": {"type": "api_error", "message": f"Upstream error: {e}"},
        }
        yield f"event: error\ndata: {json.dumps(err_event)}\n\n"
    finally:
        await concurrency_limiter.release(api_key.id)
        latency_ms = int((time.monotonic() - start_time) * 1000)

        cost = Decimal(0)
        if prompt_tokens > 0 or completion_tokens > 0:
            cost = await calculate_cost(
                model_actual, prompt_tokens, completion_tokens, channel,
                cached_tokens=cached_tokens,
            )
            if cost > 0:
                await deduct_quota(api_key.id, cost)

        await save_request_log(
            request_id=request_id,
            api_key_id=api_key.id, api_key_name=api_key.name,
            channel_id=channel.id, channel_name=channel.name,
            model_requested=body.model, model_actual=model_actual,
            provider=channel.provider, endpoint="/v1/messages",
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost=cost, is_stream=True, status_code=status_code,
            latency_ms=latency_ms, error_message=error_msg,
            ip_address=ip,
        )
        await provider.close()
