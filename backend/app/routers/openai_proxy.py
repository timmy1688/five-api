import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.models import APIKey, ModelPrice
from app.providers.registry import list_available_models, resolve_candidates
from app.schemas.openai import ChatCompletionRequest, CompletionRequest, EmbeddingRequest
from app.services.audit import open_audit, security_exempt
from app.services.content_filter import collect_request_hits, format_hits
from app.services.auth import verify_api_key
from app.services.concurrency import ConcurrencyExceeded, concurrency_limiter
from app.services.quota import QuotaExceeded, begin_request_budget
from app.services.rate_limit import TPMExceeded
from app.services.pre_checks import get_effective_allowed_models, openai_error, run_pre_checks
from app.services.proxy import (
    execute_with_failover,
    extract_openai_usage,
    log_rejected_request,
    open_stream,
    stream_with_failover,
)
from app.services.error_detail import upstream_json_error
from app.services.sticky_session import get_sticky_channel, make_session_key
from app.utils.ip_check import get_client_ip

router = APIRouter(tags=["openai-proxy"])


def _openai_error_event(e: Exception) -> str:
    """生成 OpenAI 格式的 SSE 错误事件。上游 4xx JSON 原样放进事件。"""
    passed = upstream_json_error(e)
    err = passed[1] if passed is not None else {
        "error": {
            "message": f"Upstream error: {e}",
            "type": "server_error",
            "code": "upstream_error",
        }
    }
    return f"data: {json.dumps(err)}\n\ndata: [DONE]\n\n"


async def _proxy_endpoint(request: Request, body, endpoint: str, api_key: APIKey):
    """chat/completions/embeddings 共享的编排入口。"""
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()
    # Unset fields stay out, so the upstream applies its own defaults.
    body_dict = body.model_dump(exclude_unset=True)
    audit = await open_audit(api_key, body_dict)
    security_hits = await collect_request_hits(body_dict, exempt=security_exempt(api_key))

    try:
        await run_pre_checks(api_key, body.model)
        session_key = await make_session_key(api_key.id, request.headers, body_dict)
        sticky_channel_id = await get_sticky_channel(session_key)

        candidates = await resolve_candidates(
            body.model, preferred_protocol="openai",
            sticky_channel_id=sticky_channel_id,
        )
        if endpoint != "/v1/chat/completions":
            candidates = [
                candidate for candidate in candidates
                if candidate[0].provider == "openai"
            ]
            if not candidates:
                openai_error(
                    404, "invalid_request_error", "model_not_found",
                    f"No OpenAI-compatible channel supports {endpoint}",
                )
    except HTTPException as exc:
        await log_rejected_request(
            api_key, request_id, endpoint, body.model, exc.status_code,
            start_time, ip, str(exc.detail), audit=audit,
            security_hit=format_hits(security_hits),
        )
        raise

    budget = None
    try:
        budget = await begin_request_budget(api_key, request_id, body_dict)
        concurrency_lease_id = await concurrency_limiter.acquire(
            api_key.id, api_key.concurrent_limit
        )
    except ConcurrencyExceeded:
        if budget is not None:
            await budget.release()
        await log_rejected_request(
            api_key, request_id, endpoint, body.model, 429,
            start_time, ip, "Too many concurrent requests", audit=audit,
            security_hit=format_hits(security_hits),
        )
        openai_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")
    except (QuotaExceeded, TPMExceeded) as exc:
        message = (
            "Spending quota exceeded"
            if isinstance(exc, QuotaExceeded)
            else "Tokens per minute limit exceeded"
        )
        code = "quota_exceeded" if isinstance(exc, QuotaExceeded) else "tpm_limit"
        await log_rejected_request(
            api_key, request_id, endpoint, body.model, 429,
            start_time, ip, message, audit=audit,
            security_hit=format_hits(security_hits),
        )
        openai_error(429, "rate_limit_error", code, message)

    if getattr(body, "stream", False):
        async def _stream_fn(provider, channel):
            async for line in provider.send_stream(body_dict, endpoint):
                usage = {}
                if line.startswith("data: ") and not line.startswith("data: [DONE]"):
                    try:
                        usage = extract_openai_usage(json.loads(line[6:]))
                    except (json.JSONDecodeError, KeyError):
                        pass
                yield line, usage

        upstream_headers: dict[str, str] = {}
        return await open_stream(
            stream_with_failover(
                candidates, _stream_fn, api_key, endpoint, body.model,
                request_id, start_time, ip, _openai_error_event,
                concurrency_lease_id,
                session_key=session_key,
                audit=audit,
                security_hits=security_hits,
                budget=budget,
                upstream_headers=upstream_headers,
            ),
            upstream_headers,
        )

    async def _send_fn(provider, channel):
        result = await provider.send_request(body_dict, endpoint)
        return result, extract_openai_usage(result)

    return await execute_with_failover(
        candidates, _send_fn, api_key, endpoint, body.model,
        request_id, start_time, ip, openai_error,
        concurrency_lease_id,
        session_key=session_key,
        audit=audit,
        security_hits=security_hits,
        budget=budget,
    )


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    return await _proxy_endpoint(request, body, "/v1/chat/completions", api_key)


@router.post("/v1/completions")
async def completions(
    request: Request,
    body: CompletionRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    return await _proxy_endpoint(request, body, "/v1/completions", api_key)


@router.post("/v1/embeddings")
async def embeddings(
    request: Request,
    body: EmbeddingRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    return await _proxy_endpoint(request, body, "/v1/embeddings", api_key)


@router.get("/v1/models")
async def list_models(api_key: APIKey = Depends(verify_api_key)):
    models = await list_available_models()
    effective_models = await get_effective_allowed_models(api_key)
    if effective_models is not None:
        allowed_set = set(effective_models)
        models = [m for m in models if m["id"] in allowed_set]
    return {"object": "list", "data": models}


@router.get("/v1/me")
async def get_key_info(api_key: APIKey = Depends(verify_api_key)):
    """返回当前 API Key 的配额、可用模型及模型定价信息。"""
    total = float(api_key.quota_total)
    used = float(api_key.quota_used)
    remaining = -1.0 if total == -1 else max(0.0, total - used)

    models = await list_available_models()
    effective_models = await get_effective_allowed_models(api_key)
    if effective_models is not None:
        models = [m for m in models if m["id"] in effective_models]
    model_ids = [m["id"] for m in models]

    all_prices = await ModelPrice.filter(is_active=True)
    price_map = {
        mp.model: {
            "prompt": float(mp.prompt_price),
            "completion": float(mp.completion_price),
            "cached": float(mp.cached_price),
            "cache_write": float(mp.cache_write_price),
        }
        for mp in all_prices
    }
    model_prices = {mid: price_map[mid] for mid in model_ids if mid in price_map}

    return {
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "quota_total": total,
        "quota_used": used,
        "quota_remaining": remaining,
        "rpm_limit": api_key.rpm_limit,
        "tpm_limit": api_key.tpm_limit,
        "models": model_ids,
        "model_prices": model_prices,
        "model_prices_source": "global_defaults",
        "channel_overrides_may_apply": True,
    }
