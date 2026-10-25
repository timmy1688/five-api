import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.models import APIKey
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import forwardable_headers
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
from app.services.error_detail import client_message, upstream_json_error
from app.services.auto_cache import with_cache_control
from app.services.routing import plan_route
from app.services.settings_service import gateway_config
from app.utils.ip_check import get_client_ip
from app.services.unbilled_limits import guard_unbilled

router = APIRouter(tags=["anthropic-proxy"])


def _billing_usage(input_tokens: int, output_tokens: int, cache_read: int, cache_creation: int) -> dict:
    """Anthropic 的 input_tokens 不含缓存 token，而计费按 OpenAI 口径（prompt_tokens
    含全部输入）。这里把 cache_read + cache_creation 补进 prompt_tokens，
    cached_tokens 只取 cache_read。cache_creation 单独按缓存写入价计。
    """
    return {
        "prompt_tokens": input_tokens + cache_read + cache_creation,
        "completion_tokens": output_tokens,
        "cached_tokens": cache_read,
        "cache_write_tokens": cache_creation,
    }


def _extract_anthropic_usage(resp: dict) -> dict:
    usage = resp.get("usage", {})
    return _billing_usage(
        usage.get("input_tokens", 0) or 0,
        usage.get("output_tokens", 0) or 0,
        usage.get("cache_read_input_tokens", 0) or 0,
        usage.get("cache_creation_input_tokens", 0) or 0,
    )


def _anthropic_error_event(e: Exception) -> str:
    """生成 Anthropic 格式的 SSE 错误事件。上游 4xx JSON 原样放进事件。"""
    passed = upstream_json_error(e)
    err = passed[1] if passed is not None else {
        "type": "error",
        "error": {"type": "api_error", "message": client_message(e)},
    }
    return f"event: error\ndata: {json.dumps(err)}\n\n"


async def _passthrough_stream_with_usage(
    provider: AnthropicProvider,
    body: dict,
    extra_headers: dict[str, str] | None,
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (sse_line, usage_dict)，从 Anthropic SSE 流中提取 token 用量。"""
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_creation = 0
    reported_prompt = reported_completion = False

    async for line in provider.stream_anthropic_passthrough(body, extra_headers):
        stripped = line.strip()
        if stripped.startswith("data:"):
            try:
                data = json.loads(stripped[5:].strip())
                event_msg = data.get("message", {})
                if event_msg:
                    u = event_msg.get("usage", {})
                    reported_prompt = reported_prompt or "input_tokens" in u
                    input_tokens = u.get("input_tokens", input_tokens)
                    cache_read = u.get("cache_read_input_tokens", cache_read)
                    cache_creation = u.get("cache_creation_input_tokens", cache_creation)
                delta_usage = data.get("usage", {})
                if delta_usage:
                    reported_completion = reported_completion or "output_tokens" in delta_usage
                    output_tokens = delta_usage.get("output_tokens", output_tokens)
            except (json.JSONDecodeError, ValueError):
                pass

        yield line, {**_billing_usage(input_tokens, output_tokens, cache_read, cache_creation),
                     "reported_prompt": reported_prompt, "reported_completion": reported_completion}


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request: Request,
    api_key: APIKey = Depends(verify_api_key_anthropic),
):
    raw = await request.body()
    try:
        estimated, _ = estimate_request_tokens(json.loads(raw))
    except (ValueError, TypeError):
        estimated = 0
    async with guard_unbilled(api_key, estimated):
        return await _count_tokens(request, api_key)


async def _count_tokens(request: Request, api_key: APIKey):
    """Free token counting; tenant/key RPM, TPM and concurrency still apply.

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
            anthropic_error(502, "api_error", "upstream_error", client_message(exc))

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
        plan = await plan_route(api_key, body.model, "anthropic", request.headers, raw_body)
    except HTTPException as exc:
        await log_rejected_request(
            api_key, request_id, "/v1/messages", body.model, exc.status_code,
            start_time, ip, str(exc.detail), audit=audit,
            security_hit=format_hits(security_hits),
        )
        raise

    budget = None
    try:
        budget = await begin_request_budget(api_key, request_id, raw_body, candidates=plan.candidates)
        concurrency_lease_id = await concurrency_limiter.acquire(
            api_key.id, api_key.concurrent_limit
        )
    except ConcurrencyExceeded as exc:
        if budget is not None:
            await budget.release()
        await log_rejected_request(
            api_key, request_id, "/v1/messages", body.model, 429,
            start_time, ip, "Too many concurrent requests", audit=audit,
            security_hit=format_hits(security_hits),
        )
        anthropic_error(429, "rate_limit_error", "tenant_concurrent_limit" if exc.scope == "tenant" else "concurrent_limit", "Too many concurrent requests")
    except (QuotaExceeded, TPMExceeded) as exc:
        if isinstance(exc, QuotaExceeded):
            status, code, message = exc.status, exc.code, exc.message
        else:
            status, code, message = 429, "tenant_tpm_limit" if exc.scope == "tenant" else "tpm_limit", "Tokens per minute limit exceeded"
        error_type = "permission_error" if status == 403 else "rate_limit_error"
        await log_rejected_request(
            api_key, request_id, "/v1/messages", body.model, status,
            start_time, ip, message, audit=audit,
            security_hit=format_hits(security_hits),
        )
        anthropic_error(status, error_type, code, message)

    extra_headers = {
        k: v for k, v in request.headers.items()
        if k.startswith("anthropic-")
    }
    if (await gateway_config()).get("auto_cache_control"):
        raw_body, _ = with_cache_control(raw_body)

    if body.stream:
        async def _stream_fn(provider: AnthropicProvider, channel):
            async for line, usage in _passthrough_stream_with_usage(provider, raw_body, extra_headers):
                yield line, usage

        upstream_headers = plan.headers
        return await open_stream(
            stream_with_failover(
                plan.candidates, _stream_fn, api_key, "/v1/messages", body.model,
                request_id, start_time, ip, _anthropic_error_event,
                concurrency_lease_id,
                session_key=plan.session_key,
                session_id=plan.session_id,
                audit=audit,
                security_hits=security_hits,
                budget=budget,
                upstream_headers=upstream_headers,
            ),
            upstream_headers,
        )

    async def _send_fn(provider: AnthropicProvider, channel):
        result = await provider.send_anthropic_passthrough(raw_body, extra_headers)
        reported = result.get("usage") or {}
        return JSONResponse(content=result), {**_extract_anthropic_usage(result),
            "reported_prompt": "input_tokens" in reported, "reported_completion": "output_tokens" in reported}

    response = await execute_with_failover(
        plan.candidates, _send_fn, api_key, "/v1/messages", body.model,
        request_id, start_time, ip, anthropic_error,
        concurrency_lease_id,
        session_key=plan.session_key,
        session_id=plan.session_id,
        audit=audit,
        security_hits=security_hits,
        budget=budget,
    )
    return plan.mark(response)
