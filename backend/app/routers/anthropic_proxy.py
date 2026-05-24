import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.services.channel_health import record_failure, record_success
from app.services.concurrency import ConcurrencyExceeded, concurrency_limiter
from app.services.failover import is_retryable_error
from app.services.logging_service import save_request_log
from app.services.pre_checks import anthropic_error, run_pre_checks
from app.services.pricing import calculate_cost
from app.services.quota import deduct_quota
from app.utils.ip_check import get_client_ip

router = APIRouter(tags=["anthropic-proxy"])


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
    await run_pre_checks(api_key, body.model, anthropic_error)

    candidates = await resolve_candidates(body.model, api_key.channel_group)
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        anthropic_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")

    raw_body = json.loads(await request.body())
    extra_headers = {
        k: v for k, v in request.headers.items()
        if k.startswith("anthropic-")
    }

    if body.stream:
        return StreamingResponse(
            _stream_with_failover(
                candidates, raw_body, extra_headers, body, api_key,
                request_id, start_time, ip,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await _non_stream_with_failover(
        candidates, raw_body, extra_headers, body, api_key,
        request_id, start_time, ip,
    )


# ── Non-stream with failover ─────────────────────────────────────────────────

async def _non_stream_with_failover(
    candidates: list[tuple],
    raw_body: dict,
    extra_headers: dict[str, str],
    body: AnthropicMessagesRequest,
    api_key: APIKey,
    request_id: str,
    start_time: float,
    ip: str,
):
    try:
        for i, (channel, provider_cls) in enumerate(candidates):
            provider = provider_cls(channel)
            is_passthrough = channel.provider == "anthropic" and isinstance(provider, AnthropicProvider)

            try:
                if is_passthrough:
                    result = await provider.send_anthropic_passthrough(raw_body, extra_headers)
                    prompt_tokens, completion_tokens, cached_tokens = _extract_anthropic_usage(result)
                    model_actual = provider.apply_model_mapping(body.model)
                    response = JSONResponse(content=result)
                else:
                    openai_body = anthropic_to_openai_request(body.model_dump())
                    result = await provider.send_request(openai_body, "/v1/chat/completions")
                    usage = result.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)
                    cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                    model_actual = provider.apply_model_mapping(body.model)
                    response = openai_to_anthropic_response(result, body.model)

                latency_ms = int((time.monotonic() - start_time) * 1000)

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
                await record_success(channel.id)
                return response

            except HTTPException:
                raise
            except Exception as e:
                if is_retryable_error(e) and i < len(candidates) - 1:
                    await record_failure(channel.id)
                    continue
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
                anthropic_error(502, "api_error", "upstream_error", f"Upstream error: {e}")
            finally:
                await provider.close()
    finally:
        await concurrency_limiter.release(api_key.id)


# ── Stream with failover ─────────────────────────────────────────────────────

async def _stream_with_failover(
    candidates: list[tuple],
    raw_body: dict,
    extra_headers: dict[str, str],
    body: AnthropicMessagesRequest,
    api_key: APIKey,
    request_id: str,
    start_time: float,
    ip: str,
) -> AsyncIterator[str]:
    """Unified stream generator with failover for both passthrough and conversion paths."""
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    status_code = 200
    error_msg = ""
    channel = None
    provider: BaseProvider | None = None
    model_actual = body.model
    data_yielded = False

    try:
        last_error: Exception | None = None
        for i, (ch, provider_cls) in enumerate(candidates):
            prov = provider_cls(ch)
            is_passthrough = ch.provider == "anthropic" and isinstance(prov, AnthropicProvider)

            try:
                if is_passthrough:
                    async for line, pt, ct, cct in _passthrough_stream_with_usage(
                        prov, raw_body, extra_headers,
                    ):
                        if not data_yielded:
                            channel = ch
                            provider = prov
                            model_actual = prov.apply_model_mapping(body.model)
                            data_yielded = True
                        prompt_tokens, completion_tokens, cached_tokens = pt, ct, cct
                        yield line
                else:
                    openai_body = anthropic_to_openai_request(body.model_dump())
                    openai_sse = _raw_openai_stream(prov, openai_body, "/v1/chat/completions")
                    async for line in openai_stream_to_anthropic_stream(openai_sse, body.model):
                        if not data_yielded:
                            channel = ch
                            provider = prov
                            model_actual = prov.apply_model_mapping(body.model)
                            data_yielded = True
                        yield line

                if not data_yielded:
                    channel = ch
                    provider = prov
                    model_actual = prov.apply_model_mapping(body.model)
                last_error = None
                await record_success(ch.id)
                break

            except Exception as e:
                if not data_yielded and is_retryable_error(e) and i < len(candidates) - 1:
                    await record_failure(ch.id)
                    await prov.close()
                    last_error = e
                    continue
                channel = ch
                provider = prov
                model_actual = prov.apply_model_mapping(body.model)
                raise

        if last_error is not None:
            raise last_error

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
            channel_id=channel.id if channel else 0,
            channel_name=channel.name if channel else "",
            model_requested=body.model, model_actual=model_actual,
            provider=channel.provider if channel else "",
            endpoint="/v1/messages",
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost=cost, is_stream=True, status_code=status_code,
            latency_ms=latency_ms, error_message=error_msg,
            ip_address=ip,
        )
        if provider:
            await provider.close()


async def _raw_openai_stream(
    provider: BaseProvider, openai_request: dict, endpoint: str,
) -> AsyncIterator[str]:
    """Yield raw SSE lines from an OpenAI-format provider stream."""
    async for line in provider.send_stream(openai_request, endpoint):
        yield line
