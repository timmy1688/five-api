import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.models import APIKey
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import BaseProvider, forwardable_headers
from app.providers.registry import resolve_candidates
from app.schemas.anthropic import AnthropicMessagesRequest
from app.services.audit import open_audit, security_exempt
from app.services.content_filter import collect_request_hits, format_hits
from app.services.auth import verify_api_key_anthropic
from app.services.concurrency import ConcurrencyExceeded, concurrency_limiter
from app.services.quota import QuotaExceeded, begin_request_budget
from app.services.rate_limit import TPMExceeded
from app.services.failover import is_retryable_error, upstream_status
from app.services.pre_checks import anthropic_error, check_model_access, run_pre_checks
from app.services.pricing import estimate_request_tokens
from app.services.proxy import (
    execute_with_failover,
    log_rejected_request,
    open_stream,
    stream_with_failover,
)
from app.services.error_detail import upstream_json_error
from app.services.sticky_session import get_sticky_channel, make_session_key
from app.utils.ip_check import get_client_ip

router = APIRouter(tags=["anthropic-proxy"])


def _extract_anthropic_usage(resp: dict) -> dict:
    """从 Anthropic 响应中提取 usage。

    Anthropic 的 input_tokens 不含缓存 token，而计费按 OpenAI 口径（prompt_tokens
    含全部输入）。这里把 cache_read + cache_creation 补进 prompt_tokens，
    cached_tokens 只取 cache_read。cache_creation 单独按缓存写入价计。
    """
    usage = resp.get("usage", {})
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
    return {
        "prompt_tokens": (usage.get("input_tokens", 0) or 0) + cache_read + cache_creation,
        "completion_tokens": usage.get("output_tokens", 0) or 0,
        "cached_tokens": cache_read,
        "cache_write_tokens": cache_creation,
    }


def _anthropic_error_event(e: Exception) -> str:
    """生成 Anthropic 格式的 SSE 错误事件。上游 4xx JSON 原样放进事件。"""
    passed = upstream_json_error(e)
    err = passed[1] if passed is not None else {
        "type": "error",
        "error": {"type": "api_error", "message": f"Upstream error: {e}"},
    }
    return f"event: error\ndata: {json.dumps(err)}\n\n"


async def _passthrough_stream_with_usage(
    provider: AnthropicProvider,
    body: dict,
    extra_headers: dict[str, str] | None,
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (sse_line, usage_dict)，从 Anthropic SSE 流中提取 token 用量。

    Anthropic 的 input_tokens 不含缓存 token，计费按 OpenAI 口径补齐：
    prompt_tokens = input_tokens + cache_read + cache_creation。
    cached_tokens 取 cache_read。写入单独按缓存写入价计。
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
            "cache_write_tokens": cache_creation,
        }


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request: Request,
    api_key: APIKey = Depends(verify_api_key_anthropic),
):
    """Token count for Claude Code. Free, so it skips quota, RPM and logging.

    Anthropic-compatible upstreams without this endpoint get a local estimate.
    """
    try:
        raw_body = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raw_body = None
    model = raw_body.get("model") if isinstance(raw_body, dict) else None
    if not isinstance(model, str) or not model:
        anthropic_error(400, "invalid_request_error", "invalid_request", "model is required")

    await check_model_access(api_key, model, anthropic_error)
    candidates = await resolve_candidates(model, preferred_protocol="anthropic")
    extra_headers = {
        k: v for k, v in request.headers.items()
        if k.startswith("anthropic-")
    }
    for channel, provider_cls in candidates:
        provider = provider_cls(channel)
        if not isinstance(provider, AnthropicProvider):
            continue
        try:
            result = await provider.count_tokens(raw_body, extra_headers)
            return JSONResponse(content=result, headers=provider.response_headers)
        except Exception as exc:
            if upstream_status(exc) in (404, 405, 501) or is_retryable_error(exc):
                continue
            passed = upstream_json_error(exc)
            if passed is not None:
                status, error_body = passed
                return JSONResponse(
                    status_code=status, content=error_body,
                    headers=forwardable_headers(exc.response),
                )
            anthropic_error(502, "api_error", "upstream_error", f"Upstream error: {exc}")

    input_tokens, _ = estimate_request_tokens(raw_body)
    return {"input_tokens": input_tokens}


@router.post("/v1/messages")
async def messages(
    request: Request,
    body: AnthropicMessagesRequest,
    api_key: APIKey = Depends(verify_api_key_anthropic),
):
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()
    audit = await open_audit(api_key, body.model_dump())
    security_hits: list[str] = []

    try:
        await run_pre_checks(api_key, body.model, anthropic_error)

        raw_body = json.loads(await request.body())
        security_hits.extend(await collect_request_hits(raw_body, exempt=security_exempt(api_key)))
        if audit is not None:
            audit.set_request(raw_body)
        session_key = await make_session_key(api_key.id, request.headers, raw_body)
        sticky_channel_id = await get_sticky_channel(session_key)

        candidates = await resolve_candidates(
            body.model, preferred_protocol="anthropic",
            sticky_channel_id=sticky_channel_id,
        )
    except HTTPException as exc:
        await log_rejected_request(
            api_key, request_id, "/v1/messages", body.model, exc.status_code,
            start_time, ip, str(exc.detail), audit=audit,
            security_hit=format_hits(security_hits),
        )
        raise

    budget = None
    try:
        budget = await begin_request_budget(api_key, request_id, raw_body)
        concurrency_lease_id = await concurrency_limiter.acquire(
            api_key.id, api_key.concurrent_limit
        )
    except ConcurrencyExceeded:
        if budget is not None:
            await budget.release()
        await log_rejected_request(
            api_key, request_id, "/v1/messages", body.model, 429,
            start_time, ip, "Too many concurrent requests", audit=audit,
            security_hit=format_hits(security_hits),
        )
        anthropic_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")
    except (QuotaExceeded, TPMExceeded) as exc:
        message = (
            "Spending quota exceeded"
            if isinstance(exc, QuotaExceeded)
            else "Tokens per minute limit exceeded"
        )
        code = "quota_exceeded" if isinstance(exc, QuotaExceeded) else "tpm_limit"
        await log_rejected_request(
            api_key, request_id, "/v1/messages", body.model, 429,
            start_time, ip, message, audit=audit,
            security_hit=format_hits(security_hits),
        )
        anthropic_error(429, "rate_limit_error", code, message)

    extra_headers = {
        k: v for k, v in request.headers.items()
        if k.startswith("anthropic-")
    }

    if body.stream:
        async def _stream_fn(provider: BaseProvider, channel):
            if not isinstance(provider, AnthropicProvider):
                raise RuntimeError("messages endpoint only forwards to anthropic channels")
            async for line, usage in _passthrough_stream_with_usage(provider, raw_body, extra_headers):
                yield line, usage

        upstream_headers: dict[str, str] = {}
        return await open_stream(
            stream_with_failover(
                candidates, _stream_fn, api_key, "/v1/messages", body.model,
                request_id, start_time, ip, _anthropic_error_event,
                concurrency_lease_id,
                session_key=session_key,
                audit=audit,
                security_hits=security_hits,
                budget=budget,
                upstream_headers=upstream_headers,
            ),
            upstream_headers,
        )

    async def _send_fn(provider: BaseProvider, channel):
        if not isinstance(provider, AnthropicProvider):
            raise RuntimeError("messages endpoint only forwards to anthropic channels")
        result = await provider.send_anthropic_passthrough(raw_body, extra_headers)
        return JSONResponse(content=result), _extract_anthropic_usage(result)

    return await execute_with_failover(
        candidates, _send_fn, api_key, "/v1/messages", body.model,
        request_id, start_time, ip, anthropic_error,
        concurrency_lease_id,
        session_key=session_key,
        audit=audit,
        security_hits=security_hits,
        budget=budget,
    )
