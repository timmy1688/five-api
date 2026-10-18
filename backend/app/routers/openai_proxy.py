import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.models import APIKey, ModelPrice
from app.providers.registry import list_available_models, resolve_with_fallbacks
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


def _responses_error_event(e: Exception) -> str:
    passed = upstream_json_error(e)
    error = (passed[1].get("error") if passed is not None else None) or {}
    event = {
        "type": "error",
        "code": error.get("code") or "upstream_error",
        "message": error.get("message") or f"Upstream error: {e}",
        "param": error.get("param"),
    }
    return f"event: error\ndata: {json.dumps(event)}\n\n"


def _sse_data(event: str) -> dict | None:
    """JSON payload of one SSE event, which may carry an event: line first."""
    for line in event.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    return None
                return data if isinstance(data, dict) else None
    return None


def extract_responses_usage(data: dict) -> dict:
    """Responses API, image generation and transcription share these field names."""
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return {}
    details = usage.get("input_tokens_details") or {}
    return {
        "prompt_tokens": int(usage.get("input_tokens") or 0),
        "completion_tokens": int(usage.get("output_tokens") or 0),
        "cached_tokens": int(details.get("cached_tokens") or 0),
    }


def _rerank_usage(data: dict) -> dict:
    usage = data.get("usage") or {}
    billed = (data.get("meta") or {}).get("billed_units") or {}
    prompt = usage.get("prompt_tokens") or usage.get("total_tokens") or usage.get("input_tokens") or 0
    return {
        "prompt_tokens": int(prompt),
        "request_units": int(billed.get("search_units") or 1),
    }


def _raw_response(resp) -> Response:
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
    )


def _json_or_empty(resp) -> dict:
    if "json" not in resp.headers.get("content-type", ""):
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _proxy(
    request: Request,
    api_key: APIKey,
    endpoint: str,
    model: str,
    body_dict: dict,
    *,
    send_fn,
    stream_fn=None,
    error_event=_openai_error_event,
    default_output: int | None = None,
    request_units: int = 0,
):
    """所有 OpenAI 兼容端点共享的编排入口。只有 chat 可以落到其他协议的渠道。"""
    request_id = getattr(request.state, "request_id", "")
    ip = get_client_ip(request)
    start_time = time.monotonic()
    audit = await open_audit(api_key, body_dict)
    security_hits = await collect_request_hits(body_dict, exempt=security_exempt(api_key))

    try:
        if not model:
            openai_error(400, "invalid_request_error", "model_required", "model is required")
        await run_pre_checks(api_key, model)
        session_key = await make_session_key(api_key.id, request.headers, body_dict)
        sticky_channel_id = await get_sticky_channel(session_key)

        candidates = await resolve_with_fallbacks(
            model, preferred_protocol="openai",
            sticky_channel_id=sticky_channel_id,
            allowed_models=await get_effective_allowed_models(api_key),
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
            api_key, request_id, endpoint, model, exc.status_code,
            start_time, ip, str(exc.detail), audit=audit,
            security_hit=format_hits(security_hits),
        )
        raise

    budget = None
    try:
        budget = await begin_request_budget(
            api_key, request_id, body_dict,
            default_output=default_output, request_units=request_units,
        )
        concurrency_lease_id = await concurrency_limiter.acquire(
            api_key.id, api_key.concurrent_limit
        )
    except ConcurrencyExceeded:
        if budget is not None:
            await budget.release()
        await log_rejected_request(
            api_key, request_id, endpoint, model, 429,
            start_time, ip, "Too many concurrent requests", audit=audit,
            security_hit=format_hits(security_hits),
        )
        openai_error(429, "rate_limit_error", "concurrent_limit", "Too many concurrent requests")
    except (QuotaExceeded, TPMExceeded) as exc:
        if isinstance(exc, QuotaExceeded):
            status, code, message = exc.status, exc.code, exc.message
        else:
            status, code, message = 429, "tpm_limit", "Tokens per minute limit exceeded"
        await log_rejected_request(
            api_key, request_id, endpoint, model, status,
            start_time, ip, message, audit=audit,
            security_hit=format_hits(security_hits),
        )
        error_type = "permission_error" if status == 403 else "rate_limit_error"
        openai_error(status, error_type, code, message)

    if stream_fn is not None:
        upstream_headers: dict[str, str] = {}
        return await open_stream(
            stream_with_failover(
                candidates, stream_fn, api_key, endpoint, model,
                request_id, start_time, ip, error_event,
                concurrency_lease_id,
                session_key=session_key,
                audit=audit,
                security_hits=security_hits,
                budget=budget,
                upstream_headers=upstream_headers,
            ),
            upstream_headers,
        )

    return await execute_with_failover(
        candidates, send_fn, api_key, endpoint, model,
        request_id, start_time, ip, openai_error,
        concurrency_lease_id,
        session_key=session_key,
        audit=audit,
        security_hits=security_hits,
        budget=budget,
    )


async def _proxy_endpoint(request: Request, body, endpoint: str, api_key: APIKey):
    """chat/completions/embeddings：请求体已由 Pydantic 校验。"""
    # Unset fields stay out, so the upstream applies its own defaults.
    body_dict = body.model_dump(exclude_unset=True)

    async def _send_fn(provider, channel):
        result = await provider.send_request(body_dict, endpoint)
        return result, extract_openai_usage(result)

    async def _stream_fn(provider, channel):
        async for line in provider.send_stream(body_dict, endpoint):
            usage = {}
            if line.startswith("data: ") and not line.startswith("data: [DONE]"):
                try:
                    usage = extract_openai_usage(json.loads(line[6:]))
                except (json.JSONDecodeError, KeyError):
                    pass
            yield line, usage

    return await _proxy(
        request, api_key, endpoint, body.model, body_dict,
        send_fn=_send_fn,
        stream_fn=_stream_fn if getattr(body, "stream", False) else None,
    )


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        openai_error(400, "invalid_request_error", "invalid_json", "Request body must be JSON")
    if not isinstance(body, dict):
        openai_error(400, "invalid_request_error", "invalid_json", "Request body must be a JSON object")
    return body


async def _multipart_body(request: Request) -> tuple[dict[str, str], list]:
    """Text fields and files of a multipart upload, ready for httpx."""
    form = await request.form()
    fields: dict[str, str] = {}
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for name, value in form.multi_items():
        if isinstance(value, str):
            fields[name] = value
        else:
            files.append((
                name,
                (value.filename or name, await value.read(), value.content_type or "application/octet-stream"),
            ))
    return fields, files


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


@router.post("/v1/responses")
async def responses(request: Request, api_key: APIKey = Depends(verify_api_key)):
    body = await _json_body(request)
    endpoint = "/v1/responses"

    async def _send_fn(provider, channel):
        result = await provider.send_request(body, endpoint)
        return result, extract_responses_usage(result)

    async def _stream_fn(provider, channel):
        async for event in provider.send_event_stream(body, endpoint):
            usage = {}
            data = _sse_data(event)
            if data and data.get("type") in {"response.completed", "response.incomplete", "response.failed"}:
                usage = extract_responses_usage(data.get("response") or {})
            yield event, usage

    return await _proxy(
        request, api_key, endpoint, str(body.get("model") or ""), body,
        send_fn=_send_fn,
        stream_fn=_stream_fn if body.get("stream") else None,
        error_event=_responses_error_event,
        # Responses has no max_output_tokens default, so reserve a full reply.
        default_output=4096,
    )


def _image_count(value) -> int:
    try:
        return max(int(value or 1), 1)
    except (TypeError, ValueError):
        return 1


@router.post("/v1/images/generations")
async def image_generations(request: Request, api_key: APIKey = Depends(verify_api_key)):
    body = await _json_body(request)
    endpoint = "/v1/images/generations"
    units = _image_count(body.get("n"))

    async def _send_fn(provider, channel):
        result = await provider.send_request(body, endpoint)
        return result, {**extract_responses_usage(result), "request_units": units}

    return await _proxy(
        request, api_key, endpoint, str(body.get("model") or ""), body,
        send_fn=_send_fn, default_output=0, request_units=units,
    )


async def _multipart_proxy(request: Request, api_key: APIKey, endpoint: str, *, units_field: str | None):
    fields, files = await _multipart_body(request)
    units = _image_count(fields.get(units_field)) if units_field else 1

    async def _send_fn(provider, channel):
        resp = await provider.send_raw(endpoint, form=fields, files=files)
        data = _json_or_empty(resp)
        return _raw_response(resp), {**extract_responses_usage(data), "request_units": units}

    return await _proxy(
        request, api_key, endpoint, fields.get("model", ""), fields,
        send_fn=_send_fn, default_output=0, request_units=units,
    )


@router.post("/v1/images/edits")
async def image_edits(request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await _multipart_proxy(request, api_key, "/v1/images/edits", units_field="n")


@router.post("/v1/images/variations")
async def image_variations(request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await _multipart_proxy(request, api_key, "/v1/images/variations", units_field="n")


@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await _multipart_proxy(request, api_key, "/v1/audio/transcriptions", units_field=None)


@router.post("/v1/audio/translations")
async def audio_translations(request: Request, api_key: APIKey = Depends(verify_api_key)):
    return await _multipart_proxy(request, api_key, "/v1/audio/translations", units_field=None)


@router.post("/v1/audio/speech")
async def audio_speech(request: Request, api_key: APIKey = Depends(verify_api_key)):
    body = await _json_body(request)
    endpoint = "/v1/audio/speech"
    # Speech is priced per input character, so characters go in the input bucket.
    characters = len(str(body.get("input") or ""))

    async def _send_fn(provider, channel):
        resp = await provider.send_raw(endpoint, json_body=body)
        return _raw_response(resp), {"prompt_tokens": characters, "request_units": 1}

    return await _proxy(
        request, api_key, endpoint, str(body.get("model") or ""), body,
        send_fn=_send_fn, default_output=0, request_units=1,
    )


@router.post("/v1/rerank")
async def rerank(request: Request, api_key: APIKey = Depends(verify_api_key)):
    body = await _json_body(request)
    endpoint = "/v1/rerank"

    async def _send_fn(provider, channel):
        result = await provider.send_request(body, endpoint)
        return result, _rerank_usage(result)

    return await _proxy(
        request, api_key, endpoint, str(body.get("model") or ""), body,
        send_fn=_send_fn, default_output=0, request_units=1,
    )


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
            "request": float(mp.request_price),
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
