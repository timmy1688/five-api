import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.models import APIKey, ModelPrice
from app.providers.registry import list_available_models, resolve_candidates
from app.schemas.openai import ChatCompletionRequest, CompletionRequest, EmbeddingRequest
from app.services.auth import verify_api_key
from app.services.concurrency import ConcurrencyExceeded, concurrency_limiter
from app.services.pre_checks import get_effective_allowed_models, openai_error, run_pre_checks
from app.services.proxy import execute_with_failover, extract_openai_usage, stream_with_failover
from app.services.sticky_session import get_sticky_channel, make_session_key
from app.utils.ip_check import get_client_ip

router = APIRouter(tags=["openai-proxy"])


def _openai_error_event(e: Exception) -> str:
    """生成 OpenAI 格式的 SSE 错误事件。"""
    err = {"error": {"message": f"Upstream error: {e}", "type": "server_error", "code": "upstream_error"}}
    return f"data: {json.dumps(err)}\n\ndata: [DONE]\n\n"


async def _proxy_endpoint(request: Request, body, endpoint: str, api_key: APIKey):
    """chat/completions/embeddings 共享的编排入口。"""
    await run_pre_checks(api_key, body.model)

    body_dict = body.model_dump()
    session_key = make_session_key(api_key.id, request.headers, body_dict)
    sticky_channel_id = await get_sticky_channel(session_key)

    candidates = await resolve_candidates(
        body.model, preferred_protocol="openai", sticky_channel_id=sticky_channel_id,
    )
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()

    try:
        await concurrency_limiter.acquire(api_key.id, api_key.concurrent_limit)
    except ConcurrencyExceeded:
        openai_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")

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

        return StreamingResponse(
            stream_with_failover(
                candidates, _stream_fn, api_key, endpoint, body.model,
                request_id, start_time, ip, _openai_error_event,
                session_key=session_key,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def _send_fn(provider, channel):
        result = await provider.send_request(body_dict, endpoint)
        return result, extract_openai_usage(result)

    return await execute_with_failover(
        candidates, _send_fn, api_key, endpoint, body.model,
        request_id, start_time, ip, openai_error,
        session_key=session_key,
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
    if effective_models:
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
    if effective_models:
        models = [m for m in models if m["id"] in effective_models]
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
