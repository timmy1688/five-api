import time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models import APIKey, ModelPrice
from app.providers.registry import list_available_models, resolve_candidates
from app.schemas.openai import ChatCompletionRequest, CompletionRequest, EmbeddingRequest
from app.services.auth import verify_api_key
from app.services.channel_health import record_failure, record_success
from app.services.concurrency import ConcurrencyExceeded, concurrency_limiter
from app.services.failover import is_retryable_error
from app.services.logging_service import save_request_log
from app.services.pre_checks import openai_error, run_pre_checks
from app.services.pricing import calculate_cost
from app.services.proxy import stream_proxy
from app.services.quota import deduct_quota
from app.utils.ip_check import get_client_ip

router = APIRouter(tags=["openai-proxy"])


async def _handle_non_stream(
    candidates: list, body_dict: dict, endpoint: str, api_key: APIKey,
    request_id: str, start_time: float, ip: str, model: str,
):
    try:
        for i, (channel, provider_cls) in enumerate(candidates):
            provider = provider_cls(channel)
            try:
                result = await provider.send_request(body_dict, endpoint)
                latency_ms = int((time.monotonic() - start_time) * 1000)
                usage = result.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                model_actual = provider.apply_model_mapping(model)

                cost = await calculate_cost(model_actual, prompt_tokens, completion_tokens, channel, cached_tokens=cached_tokens)
                if cost > 0:
                    await deduct_quota(api_key.id, cost)

                await save_request_log(
                    request_id=request_id,
                    api_key_id=api_key.id,
                    api_key_name=api_key.name,
                    channel_id=channel.id,
                    channel_name=channel.name,
                    model_requested=model,
                    model_actual=model_actual,
                    provider=channel.provider,
                    endpoint=endpoint,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    cost=cost,
                    is_stream=False,
                    status_code=200,
                    latency_ms=latency_ms,
                    ip_address=ip,
                )
                await record_success(channel.id)
                return result
            except HTTPException:
                raise
            except Exception as e:
                if is_retryable_error(e) and i < len(candidates) - 1:
                    await record_failure(channel.id)
                    continue
                latency_ms = int((time.monotonic() - start_time) * 1000)
                await save_request_log(
                    request_id=request_id,
                    api_key_id=api_key.id,
                    api_key_name=api_key.name,
                    channel_id=channel.id,
                    channel_name=channel.name,
                    model_requested=model,
                    model_actual=provider.apply_model_mapping(model),
                    provider=channel.provider,
                    endpoint=endpoint,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost=Decimal(0),
                    is_stream=False,
                    status_code=500,
                    latency_ms=latency_ms,
                    error_message=str(e),
                    ip_address=ip,
                )
                raise HTTPException(
                    status_code=502,
                    detail={"error": {"message": f"Upstream error: {e}", "type": "server_error", "code": "upstream_error"}},
                )
            finally:
                await provider.close()
    finally:
        await concurrency_limiter.release(api_key.id)


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    await run_pre_checks(api_key, body.model)

    candidates = await resolve_candidates(body.model, api_key.channel_group)
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        openai_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")

    if body.stream:
        return StreamingResponse(
            stream_proxy(candidates, body.model_dump(), "/v1/chat/completions", api_key, request_id, start_time, ip),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await _handle_non_stream(
        candidates, body.model_dump(), "/v1/chat/completions",
        api_key, request_id, start_time, ip, body.model,
    )


@router.post("/v1/completions")
async def completions(
    request: Request,
    body: CompletionRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    await run_pre_checks(api_key, body.model)

    candidates = await resolve_candidates(body.model, api_key.channel_group)
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        openai_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")

    if body.stream:
        return StreamingResponse(
            stream_proxy(candidates, body.model_dump(), "/v1/completions", api_key, request_id, start_time, ip),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await _handle_non_stream(
        candidates, body.model_dump(), "/v1/completions",
        api_key, request_id, start_time, ip, body.model,
    )


@router.post("/v1/embeddings")
async def embeddings(
    request: Request,
    body: EmbeddingRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    await run_pre_checks(api_key, body.model)

    candidates = await resolve_candidates(body.model, api_key.channel_group)
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        openai_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")

    return await _handle_non_stream(
        candidates, body.model_dump(), "/v1/embeddings",
        api_key, request_id, start_time, ip, body.model,
    )


@router.get("/v1/models")
async def list_models(api_key: APIKey = Depends(verify_api_key)):
    models = await list_available_models()
    if api_key.allowed_models:
        models = [m for m in models if m["id"] in api_key.allowed_models]
    return {"object": "list", "data": models}


@router.get("/v1/me")
async def get_key_info(api_key: APIKey = Depends(verify_api_key)):
    """返回当前 API Key 的配额、可用模型及模型定价信息。"""
    total = float(api_key.quota_total)
    used = float(api_key.quota_used)
    remaining = -1.0 if total == -1 else max(0.0, total - used)

    models = await list_available_models()
    if api_key.allowed_models:
        models = [m for m in models if m["id"] in api_key.allowed_models]
    model_ids = [m["id"] for m in models]

    all_prices = await ModelPrice.filter(is_active=True)
    price_map = {
        mp.model: {"prompt": float(mp.prompt_price), "completion": float(mp.completion_price), "cached": float(mp.cached_price)}
        for mp in all_prices
    }
    model_prices = {mid: price_map[mid] for mid in model_ids if mid in price_map}

    return {
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "quota_total": total,
        "quota_used": used,
        "quota_remaining": remaining,
        "models": model_ids,
        "model_prices": model_prices,
    }
