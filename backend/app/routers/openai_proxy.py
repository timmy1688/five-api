import time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models import APIKey
from app.providers.registry import list_available_models, resolve_channel
from app.schemas.openai import ChatCompletionRequest, CompletionRequest, EmbeddingRequest
from app.services.auth import verify_api_key
from app.services.concurrency import ConcurrencyExceeded, concurrency_limiter
from app.services.logging_service import save_request_log
from app.services.pricing import calculate_cost
from app.services.proxy import stream_proxy
from app.services.quota import check_quota, deduct_quota

router = APIRouter(tags=["openai-proxy"])


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _check_model_access(api_key: APIKey, model: str) -> None:
    if api_key.allowed_models and model not in api_key.allowed_models:
        raise HTTPException(
            status_code=403,
            detail={"error": {"message": f"Model {model} not allowed for this key", "type": "invalid_request_error", "code": "model_not_allowed"}},
        )


async def _handle_non_stream(
    provider, body_dict: dict, endpoint: str, channel, api_key: APIKey,
    request_id: str, start_time: float, ip: str, model: str,
):
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
        return result
    except HTTPException:
        raise
    except Exception as e:
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
        await concurrency_limiter.release(api_key.id)
        await provider.close()


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    if not await check_quota(api_key):
        raise HTTPException(
            status_code=429,
            detail={"error": {"message": "Spending quota exceeded", "type": "rate_limit_error", "code": "quota_exceeded"}},
        )
    _check_model_access(api_key, body.model)

    channel, provider = await resolve_channel(body.model)
    request_id = getattr(request.state, "request_id", "")
    ip = _get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        await provider.close()
        raise HTTPException(
            status_code=429,
            detail={"error": {"message": "Too many concurrent requests", "type": "rate_limit_error", "code": "concurrent_limit"}},
        )

    if body.stream:
        return StreamingResponse(
            stream_proxy(provider, body.model_dump(), "/v1/chat/completions", channel, api_key, request_id, start_time, ip),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await _handle_non_stream(
        provider, body.model_dump(), "/v1/chat/completions",
        channel, api_key, request_id, start_time, ip, body.model,
    )


@router.post("/v1/completions")
async def completions(
    request: Request,
    body: CompletionRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    if not await check_quota(api_key):
        raise HTTPException(status_code=429, detail={"error": {"message": "Spending quota exceeded", "type": "rate_limit_error", "code": "quota_exceeded"}})
    _check_model_access(api_key, body.model)

    channel, provider = await resolve_channel(body.model)
    request_id = getattr(request.state, "request_id", "")
    ip = _get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        await provider.close()
        raise HTTPException(status_code=429, detail={"error": {"message": "Too many concurrent requests", "type": "rate_limit_error", "code": "concurrent_limit"}})

    if body.stream:
        return StreamingResponse(
            stream_proxy(provider, body.model_dump(), "/v1/completions", channel, api_key, request_id, start_time, ip),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await _handle_non_stream(
        provider, body.model_dump(), "/v1/completions",
        channel, api_key, request_id, start_time, ip, body.model,
    )


@router.post("/v1/embeddings")
async def embeddings(
    request: Request,
    body: EmbeddingRequest,
    api_key: APIKey = Depends(verify_api_key),
):
    if not await check_quota(api_key):
        raise HTTPException(status_code=429, detail={"error": {"message": "Spending quota exceeded", "type": "rate_limit_error", "code": "quota_exceeded"}})
    _check_model_access(api_key, body.model)

    channel, provider = await resolve_channel(body.model)
    request_id = getattr(request.state, "request_id", "")
    ip = _get_client_ip(request)
    start_time = time.monotonic()

    try:
        result = await provider.send_request(body.model_dump(), "/v1/embeddings")
        latency_ms = int((time.monotonic() - start_time) * 1000)
        usage = result.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        model_actual = provider.apply_model_mapping(body.model)

        cost = await calculate_cost(model_actual, prompt_tokens, 0, channel)
        if cost > 0:
            await deduct_quota(api_key.id, cost)

        await save_request_log(
            request_id=request_id, api_key_id=api_key.id, api_key_name=api_key.name,
            channel_id=channel.id, channel_name=channel.name,
            model_requested=body.model, model_actual=model_actual,
            provider=channel.provider, endpoint="/v1/embeddings",
            prompt_tokens=prompt_tokens, completion_tokens=0,
            cost=cost,
            is_stream=False, status_code=200, latency_ms=latency_ms, ip_address=ip,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        latency_ms = int((time.monotonic() - start_time) * 1000)
        await save_request_log(
            request_id=request_id, api_key_id=api_key.id, api_key_name=api_key.name,
            channel_id=channel.id, channel_name=channel.name,
            model_requested=body.model, model_actual=provider.apply_model_mapping(body.model),
            provider=channel.provider, endpoint="/v1/embeddings",
            prompt_tokens=0, completion_tokens=0, cost=Decimal(0),
            is_stream=False, status_code=500, latency_ms=latency_ms,
            error_message=str(e), ip_address=ip,
        )
        raise HTTPException(status_code=502, detail={"error": {"message": f"Upstream error: {e}", "type": "server_error", "code": "upstream_error"}})
    finally:
        await provider.close()


@router.get("/v1/models")
async def list_models(api_key: APIKey = Depends(verify_api_key)):
    models = await list_available_models()
    if api_key.allowed_models:
        models = [m for m in models if m["id"] in api_key.allowed_models]
    return {"object": "list", "data": models}
