"""通用代理编排：故障转移、计费、日志。

所有代理路由共享此模块，协议差异通过 send_fn / stream_fn 回调注入。
"""

import json
import asyncio
from datetime import datetime, timezone
import logging
import time
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

import anyio
import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.models import APIKey, Channel, Settlement
from app.providers.base import BaseProvider, forwardable_headers
from app.services import alerts
from app.services.channel_health import record_failure, record_rate_limit, record_success
from app.services.channel_stats import begin_attempt, end_attempt, record_latency
from app.services.concurrency import concurrency_limiter
from app.services.failover import (
    NoReadyUpstreamKey, is_credential_error, is_retryable_error, never_reached_upstream,
    should_switch_channel, upstream_status,
)
from app.services.audit import AuditBuffer, security_exempt
from app.services.content_filter import (
    collect_response_hits,
    format_hits,
    open_response_scanner,
    remember_hit,
    visible_sse_text,
)
from app.services.error_detail import (
    client_message,
    client_status,
    describe_upstream_failure,
    gateway_failure,
    upstream_json_error,
    outcome_uncertain,
)
from app.services.key_pool import KEY_STATUSES, retry_after_seconds
from app.services.logging_service import save_request_log
from app.services.pricing import count_text_tokens
from app.services.quota import RequestLease
from app.services import settlements
from app.services.billing_quotes import quote_cost, selling_quote
from app.services.redaction import redact
from app.services.request_context import client_request_id
from app.services.sticky_session import bind_sticky_channel

logger = logging.getLogger(__name__)


async def _quiet(awaitable, operation: str):
    """辅助操作失败不能覆盖已经成功的上游响应。"""
    try:
        return await awaitable
    except Exception:
        logger.exception("%s failed", operation)
        return None


def _first_count(*values) -> int:
    """First reported count. None means the field is absent, 0 is a real zero."""
    for value in values:
        if value is not None:
            return int(value or 0)
    return 0


def extract_openai_usage(data: dict) -> dict:
    """从 OpenAI 格式响应/chunk 中提取 usage。"""
    usage = data.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    return {
        "reported_prompt": "prompt_tokens" in usage,
        "reported_completion": "completion_tokens" in usage,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        # OpenAI-compatible providers expose cache usage under either the
        # OpenAI nested field or DeepSeek's top-level field.
        "cached_tokens": prompt_details.get(
            "cached_tokens",
            usage.get("prompt_cache_hit_tokens", 0),
        ),
        # A write is its own bucket when the upstream reports one. DeepSeek
        # has no write field, so the count stays 0 and the write price is unused.
        "cache_write_tokens": _first_count(
            usage.get("cache_write_tokens"),
            prompt_details.get("cache_write_tokens"),
            usage.get("cache_creation_input_tokens"),
        ),
    }


FINAL_EVENT_TYPES = {"message_stop", "response.completed", "response.incomplete"}


def is_final_sse_event(line: str) -> bool:
    """Whether an SSE event ends a successful answer in any supported protocol.

    Clients such as Codex hang up right after it, before the upstream closes the stream.
    """
    if "[DONE]" not in line and not any(name in line for name in FINAL_EVENT_TYPES):
        return False
    for part in line.splitlines():
        if not part.startswith("data:"):
            continue
        payload = part[5:].strip()
        if payload == "[DONE]":
            return True
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return False
        return isinstance(data, dict) and data.get("type") in FINAL_EVENT_TYPES
    return False


def sse_billable_text(line: str) -> str:
    """Generated text in one SSE line, including reasoning and tool arguments.

    Used to estimate output tokens when a stream ends without a usage event.
    """
    payload = next(
        (part[5:].strip() for part in line.splitlines() if part.startswith("data:")),
        "",
    )
    if not payload or payload == "[DONE]":
        return ""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""

    pieces: list[str] = []
    for choice in data.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        for name in ("content", "reasoning_content", "reasoning"):
            value = delta.get(name)
            if isinstance(value, str):
                pieces.append(value)
        for call in delta.get("tool_calls") or []:
            if isinstance(call, dict):
                arguments = (call.get("function") or {}).get("arguments")
                if isinstance(arguments, str):
                    pieces.append(arguments)

    delta = data.get("delta")
    if isinstance(delta, dict):
        for name in ("text", "thinking", "partial_json"):
            value = delta.get(name)
            if isinstance(value, str):
                pieces.append(value)
    elif isinstance(delta, str) and str(data.get("type", "")).endswith(".delta"):
        pieces.append(delta)
    return "".join(pieces)


class _OutputMeter:
    """Running output-token estimate, same rule as count_text_tokens."""

    def __init__(self):
        self.cjk = 0
        self.other = 0

    def feed(self, text: str) -> None:
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                self.cjk += 1
            else:
                self.other += 1

    @property
    def tokens(self) -> int:
        return self.cjk + (self.other + 3) // 4


async def _select_key(provider: Any, session_key: str | None) -> None:
    if isinstance(provider, BaseProvider):
        if not await provider.has_ready_key():
            raise NoReadyUpstreamKey(provider.channel.id)
        await _quiet(provider.select_key(session_key), "key selection")


async def _try_next_key(provider: Any, exc: Exception, rotations: int) -> bool:
    """Retry on the same channel with another key after a key-level error."""
    if not isinstance(provider, BaseProvider) or upstream_status(exc) not in KEY_STATUSES:
        return False
    if rotations >= len(provider.keys) - 1:
        return False
    return bool(await _quiet(provider.rotate_key(exc), "key rotation"))


async def _record_attempt_failure(channel_id: int, exc: Exception) -> int | None:
    status_code = upstream_status(exc)
    if status_code == 429:
        await _quiet(record_rate_limit(channel_id, retry_after_seconds(exc)), "rate-limit cooldown")
    elif is_retryable_error(exc) or is_credential_error(exc):
        await _quiet(record_failure(channel_id), "failure tracking")
    return status_code


def _provider_headers(provider: Any) -> dict[str, str]:
    headers = getattr(provider, "response_headers", None)
    return headers if isinstance(headers, dict) else {}


def _with_headers(response: Any, headers: dict[str, str]) -> Any:
    if not headers:
        return response
    if isinstance(response, Response):
        response.headers.update(headers)
        return response
    return JSONResponse(content=response, headers=headers)


class _UpstreamStream(StreamingResponse):
    """Closes the upstream stream once the response ends, however it ends.

    On client disconnect Starlette cancels the send loop and leaves the body
    generator suspended, so its cleanup (billing, log, concurrency release)
    would wait for garbage collection. anyio also keeps cancelling every await
    in that task, hence the shield.
    """

    def __init__(self, events: AsyncIterator[str], first: str | None, headers: dict[str, str]):
        self._events = events

        async def body():
            if first is not None:
                yield first
            async for chunk in events:
                yield chunk

        super().__init__(body(), media_type="text/event-stream", headers=headers)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.move_on_after(30, shield=True):
                await self.body_iterator.aclose()
                await self._events.aclose()


async def open_stream(events: AsyncIterator[str], upstream_headers: dict[str, str]) -> StreamingResponse:
    """Read the first SSE chunk before sending headers.

    Response headers go out before the body, so the upstream rate-limit
    headers are only known once the first chunk has arrived.
    """
    first: str | None = None
    try:
        first = await events.__anext__()
    except StopAsyncIteration:
        pass
    return _UpstreamStream(
        events, first,
        {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", **upstream_headers},
    )


async def _bill_and_log(
    model_actual: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    cache_write_tokens: int,
    channel: Channel | None,
    api_key: APIKey,
    request_id: str,
    endpoint: str,
    model_requested: str,
    is_stream: bool,
    status_code: int,
    start_time: float,
    ip: str,
    error_message: str = "",
    error_origin: str = "",
    upstream_status_code: int = 0,
    upstream_error: str = "",
    failed_over: bool = False,
    audit: AuditBuffer | None = None,
    security_hit: str = "",
    budget: RequestLease | None = None,
    request_units: int = 0,
    session_id: str = "",
    usage_source: str = "upstream",
    uncertain: bool = False,
):
    latency_ms = int((time.monotonic() - start_time) * 1000)
    payload = dict(
        request_id=request_id, client_request_id=client_request_id.get(),
        api_key_id=api_key.id, api_key_name=api_key.name, tenant_id=api_key.tenant_id,
        channel_id=channel.id if channel else None, channel_name=channel.name if channel else "",
        model_requested=model_requested, model_actual=model_actual, provider=channel.provider if channel else "",
        endpoint=endpoint, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        cached_tokens=cached_tokens, cache_write_tokens=cache_write_tokens,
        is_stream=is_stream, status_code=status_code, latency_ms=latency_ms,
        error_message=error_message, error_origin=error_origin, upstream_status_code=upstream_status_code,
        upstream_error=upstream_error, ip_address=ip, failed_over=failed_over,
        audit_request=audit.request_text if audit else "", security_hit=security_hit,
        session_id=session_id, usage_source=usage_source,
        observed_at=datetime.now(timezone.utc).isoformat(), cost="0", cache_savings="0",
    )
    payload = redact(payload)
    if uncertain and budget is not None:
        try:
            await Settlement.filter(request_id=request_id, state="reserved").update(
                state="uncertain", payload={**payload, "usage_source": "unknown"},
                last_error="Upstream outcome unknown; manual reconciliation required",
            )
        finally:
            await budget.finish(budget.estimated_tokens)
        return
    has_usage = any((prompt_tokens, completion_tokens, cached_tokens, cache_write_tokens, request_units))
    if budget is None and not has_usage:
        await save_request_log(**payload)
        return
    cost = Decimal(0)
    price_error = ""
    try:
        snapshots = budget.quotes if budget is not None else {}
        selected = snapshots.get(f"{channel.id}:{model_actual}") if channel else None
        selected = selected or snapshots.get("default")
        if selected is None:
            if budget is not None:
                raise ValueError("Missing immutable price snapshot")
            selected = {"selling": await selling_quote(model_actual, model_requested, channel)}
        customer = quote_cost(selected["selling"], prompt_tokens, completion_tokens, cached_tokens,
                              cache_write_tokens, request_units)
        cost = customer["cost"]
        payload.update(cost=str(cost), cache_savings=str(customer["cache_savings"]),
                       cost_detail={**customer["detail"], "usage_source": usage_source})
    except Exception as exc:
        cost = None
        price_error = type(exc).__name__
        logger.error("Billing requires review request_id=%s error=%s", request_id, price_error)
    try:
        if budget is None:
            # Internal callers that already reached the upstream still get a durable accounting record.
            await Settlement.get_or_create(request_id=request_id, defaults={
                "tenant_id": api_key.tenant_id, "api_key_id": api_key.id,
                "occupied": cost or Decimal(0), "owner_id": settlements.OWNER_ID,
            })
        await settlements.persist_usage(request_id, payload, cost, price_error)
        try:
            await settlements.apply(request_id, (api_key.tenant_id, api_key.id))
        except Exception as exc:
            await settlements.note_failure(request_id, exc)
        await _quiet(alerts.record_outcome(status_code), "outcome observation")
        if cost and cost > 0:
            await _quiet(alerts.check_budget(api_key.id), "budget alert")
    finally:
        if budget is not None:
            await budget.finish(max(0, prompt_tokens + completion_tokens))


async def log_rejected_request(
    api_key: APIKey,
    request_id: str,
    endpoint: str,
    model: str,
    status_code: int,
    start_time: float,
    ip: str,
    error_message: str,
    audit: AuditBuffer | None = None,
    security_hit: str = "",
) -> None:
    """Record an authenticated request rejected before reaching an upstream."""
    failure = gateway_failure(error_message)
    await _bill_and_log(
        model, 0, 0, 0, 0, None, api_key, request_id, endpoint, model,
        is_stream=False, status_code=status_code, start_time=start_time, ip=ip,
        audit=audit,
        security_hit=security_hit,
        **failure,
    )


async def execute_with_failover(
    candidates: list[tuple[Channel, type[BaseProvider]]],
    send_fn: Callable,
    api_key: APIKey,
    endpoint: str,
    model_requested: str,
    request_id: str,
    start_time: float,
    ip: str,
    format_error: Callable,
    concurrency_lease_id: str,
    session_key: str | None = None,
    audit: AuditBuffer | None = None,
    session_id: str = "",
    security_hits: list[str] | None = None,
    budget: RequestLease | None = None,
    idempotent: bool = True,
) -> Any:
    """非流式通用编排：故障转移 → 计费 → 日志。

    send_fn(provider, channel) -> (response, usage_dict)
      usage_dict = {"prompt_tokens": int, "completion_tokens": int, "cached_tokens": int}
    format_error(status_code, error_type, code, message) -> raises HTTPException
    idempotent=False resends only when the upstream never started the work.
    """
    try:
        for i, (channel, provider_cls) in enumerate(candidates):
            provider = provider_cls(channel)
            try:
                await _select_key(provider, session_key)
                attempt = 0
                rotations = 0
                while True:
                    attempt_start = time.monotonic()
                    await begin_attempt(channel.id)
                    try:
                        if budget is not None:
                            await budget.before_send()
                        response, usage = await send_fn(provider, channel)
                        await record_latency(channel.id, (time.monotonic() - attempt_start) * 1000)
                        break
                    except HTTPException:
                        raise
                    except Exception as exc:
                        if await _try_next_key(provider, exc, rotations):
                            rotations += 1
                            continue
                        status_code = await _record_attempt_failure(channel.id, exc)
                        can_retry_same = (
                            is_retryable_error(exc)
                            and status_code != 429
                            and attempt < channel.max_retries
                            and (idempotent or never_reached_upstream(exc))
                        )
                        if not can_retry_same:
                            raise
                        attempt += 1
                    finally:
                        await end_attempt(channel.id)

                model_actual = provider.apply_model_mapping(model_requested)
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                cached_tokens = usage.get("cached_tokens", 0)
                cache_write_tokens = usage.get("cache_write_tokens", 0)
                request_units = usage.get("request_units", 0)
                reported_prompt = usage.get("reported_prompt", "prompt_tokens" in usage)
                reported_output = usage.get("reported_completion", "completion_tokens" in usage)
                provenance = usage.get("usage_source", "upstream")
                if budget is not None:
                    if not reported_prompt:
                        prompt_tokens = budget.estimated_input
                    if not reported_output:
                        generated = response
                        if isinstance(response, Response):
                            try:
                                generated = json.loads(response.body)
                            except (ValueError, AttributeError):
                                generated = {}
                        if isinstance(generated, dict):
                            pieces = []
                            for choice in generated.get("choices") or []:
                                message = choice.get("message") or {}
                                pieces.extend([message.get("content"), message.get("reasoning_content"),
                                               message.get("tool_calls"), choice.get("text")])
                            pieces.extend(generated.get("output") or [])
                            completion_tokens = count_text_tokens(pieces)
                    if not (reported_prompt and reported_output):
                        provenance = "mixed" if reported_prompt or reported_output else "estimated"

                hits = security_hits if security_hits is not None else []
                for label in await collect_response_hits(response, exempt=security_exempt(api_key)):
                    remember_hit(hits, label)
                await _bill_and_log(
                    model_actual, prompt_tokens, completion_tokens, cached_tokens, cache_write_tokens,
                    channel, api_key, request_id, endpoint, model_requested,
                    is_stream=False, status_code=200,
                    start_time=start_time, ip=ip,
                    failed_over=i > 0,
                    audit=audit,
                    security_hit=format_hits(hits),
                    budget=budget,
                    session_id=session_id,
                    request_units=request_units, usage_source=provenance,
                )
                await _quiet(record_success(channel.id), "health reset")
                await _quiet(bind_sticky_channel(session_key, channel.id), "sticky binding")
                return _with_headers(response, _provider_headers(provider))

            except HTTPException:
                raise
            except Exception as e:
                if should_switch_channel(e) and (idempotent or never_reached_upstream(e)) and i < len(candidates) - 1:
                    continue

                model_actual = provider.apply_model_mapping(model_requested)
                status_code = client_status(e)
                failure = describe_upstream_failure(e)
                await _bill_and_log(
                    model_actual, 0, 0, 0, 0,
                    channel, api_key, request_id, endpoint, model_requested,
                    is_stream=False, status_code=status_code, start_time=start_time, ip=ip,
                    failed_over=i > 0,
                    audit=audit,
                    security_hit=format_hits(security_hits),
                    budget=budget,
                    uncertain=outcome_uncertain(e),
                    session_id=session_id,
                    **failure,
                )
                passed = upstream_json_error(e)
                if passed is not None:
                    return JSONResponse(
                        status_code=status_code, content=passed[1],
                        headers=forwardable_headers(e.response),
                    )
                format_error(status_code, "api_error", "upstream_error", client_message(e))
            finally:
                await _quiet(provider.close(), "provider close")
    finally:
        if budget is not None:
            await _quiet(budget.release(), "budget release")
        await _quiet(
            concurrency_limiter.release(api_key.id, concurrency_lease_id),
            "concurrency release",
        )


async def stream_with_failover(
    candidates: list[tuple[Channel, type[BaseProvider]]],
    stream_fn: Callable,
    api_key: APIKey,
    endpoint: str,
    model_requested: str,
    request_id: str,
    start_time: float,
    ip: str,
    format_error_event: Callable,
    concurrency_lease_id: str,
    session_key: str | None = None,
    audit: AuditBuffer | None = None,
    session_id: str = "",
    security_hits: list[str] | None = None,
    budget: RequestLease | None = None,
    upstream_headers: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """流式通用编排：故障转移 → 逐行 yield → 计费 → 日志。

    stream_fn(provider, channel) -> AsyncIterator[(sse_line, usage_dict)]
      每行 yield (sse_line_str, {"prompt_tokens": ..., "completion_tokens": ..., "cached_tokens": ...})
      usage_dict 为增量或累计值，最后一次的值会被使用。
    format_error_event(error) -> str  (一个或多个 SSE 事件字符串)
    """
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    cache_write_tokens = 0
    status_code = 200
    error_msg = ""
    error_origin = ""
    upstream_status_code = 0
    upstream_error = ""
    channel: Channel | None = None
    provider: BaseProvider | None = None
    model_actual = model_requested
    data_yielded = False
    completed = answered = False
    reported_prompt = reported_output = False
    failed_over = False
    hits = security_hits if security_hits is not None else []
    scanner = await open_response_scanner(exempt=security_exempt(api_key))
    meter = _OutputMeter()
    active_channel_id: int | None = None
    uncertain = False

    try:
        last_error: Exception | None = None
        for i, (ch, provider_cls) in enumerate(candidates):
            prov = provider_cls(ch)
            try:
                await _select_key(prov, session_key)
                attempt = 0
                rotations = 0
                while True:
                    attempt_start = time.monotonic()
                    if active_channel_id is not None:
                        await end_attempt(active_channel_id)
                    await begin_attempt(ch.id)
                    active_channel_id = ch.id
                    try:
                        if budget is not None:
                            await budget.before_send()
                        async for line, usage in stream_fn(prov, ch):
                            if not data_yielded:
                                channel = ch
                                provider = prov
                                model_actual = prov.apply_model_mapping(model_requested)
                                data_yielded = True
                                await record_latency(ch.id, (time.monotonic() - attempt_start) * 1000)
                                if upstream_headers is not None:
                                    upstream_headers.update(_provider_headers(prov))
                            if usage:
                                reported_prompt = reported_prompt or usage.get("reported_prompt", "prompt_tokens" in usage)
                                reported_output = reported_output or usage.get("reported_completion", "completion_tokens" in usage)
                                if usage.get("reported_prompt", "prompt_tokens" in usage):
                                    prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                                    cached_tokens = usage.get("cached_tokens", cached_tokens)
                                    cache_write_tokens = usage.get("cache_write_tokens", cache_write_tokens)
                                if usage.get("reported_completion", "completion_tokens" in usage):
                                    completion_tokens = usage.get("completion_tokens", completion_tokens)
                            meter.feed(sse_billable_text(line))
                            if scanner is not None:
                                remember_hit(hits, scanner.feed(visible_sse_text(line)))
                            yield line
                            answered = answered or is_final_sse_event(line)
                        break
                    except HTTPException:
                        raise
                    except Exception as exc:
                        last_error = exc
                        if not data_yielded and await _try_next_key(prov, exc, rotations):
                            rotations += 1
                            continue
                        code = await _record_attempt_failure(ch.id, exc)
                        if data_yielded or not is_retryable_error(exc) or code == 429 or attempt >= ch.max_retries:
                            raise
                        attempt += 1

                if not data_yielded:
                    channel = ch
                    provider = prov
                    model_actual = prov.apply_model_mapping(model_requested)
                last_error = None
                await _quiet(record_success(ch.id), "health reset")
                await _quiet(bind_sticky_channel(session_key, ch.id), "sticky binding")
                break

            except Exception as e:
                if not data_yielded and should_switch_channel(e) and i < len(candidates) - 1:
                    await _quiet(prov.close(), "provider close")
                    last_error = e
                    failed_over = True
                    continue
                channel = ch
                provider = prov
                model_actual = prov.apply_model_mapping(model_requested)
                raise

        if last_error is not None:
            raise last_error
        completed = True

    except Exception as e:
        if isinstance(e, HTTPException):
            status_code = e.status_code
            error_msg, error_origin = "Accounting unavailable before upstream dispatch", "gateway"
            raise
        status_code = client_status(e)
        uncertain = not data_yielded and outcome_uncertain(e)
        if channel is not None:
            failure = describe_upstream_failure(e)
        else:
            failure = gateway_failure(str(e))
        error_msg = failure["error_message"]
        error_origin = failure["error_origin"]
        upstream_status_code = failure["upstream_status_code"]
        upstream_error = failure["upstream_error"]
        if upstream_headers is not None and not data_yielded and isinstance(e, httpx.HTTPStatusError):
            upstream_headers.update(forwardable_headers(e.response))
        if not data_yielded:
            passed = upstream_json_error(e)
            detail = passed[1] if passed else {"error": {"type": "api_error", "message": client_message(e), "code": "upstream_error"}}
            raise HTTPException(status_code=status_code, detail=detail,
                                headers=forwardable_headers(e.response) if isinstance(e, httpx.HTTPStatusError) else {})
        yield format_error_event(e)
    finally:
        # A client disconnect cancels this generator mid-await, and anyio then
        # cancels every later await too, so cleanup runs shielded.
        with anyio.move_on_after(30, shield=True):
            if active_channel_id is not None:
                await _quiet(end_attempt(active_channel_id), "attempt end")
            await _quiet(
                concurrency_limiter.release(api_key.id, concurrency_lease_id),
                "concurrency release",
            )
            # A client disconnect or a missing usage event would bill nothing.
            # Fall back to what was actually forwarded.
            if not completed and not answered and status_code == 200:
                status_code, error_origin, error_msg = 499, "client", "Client disconnected"
            if data_yielded and not reported_output:
                completion_tokens = meter.tokens
            if data_yielded and not reported_prompt and budget is not None:
                prompt_tokens = budget.estimated_input
            await _bill_and_log(
                model_actual, prompt_tokens, completion_tokens, cached_tokens, cache_write_tokens,
                channel, api_key, request_id, endpoint, model_requested,
                is_stream=True, status_code=status_code, start_time=start_time, ip=ip,
                error_message=error_msg,
                error_origin=error_origin,
                upstream_status_code=upstream_status_code,
                upstream_error=upstream_error,
                failed_over=failed_over,
                audit=audit,
                security_hit=format_hits(hits),
                budget=budget,
                session_id=session_id,
                usage_source="upstream" if reported_prompt and reported_output else "mixed" if reported_prompt or reported_output else "estimated",
                uncertain=uncertain,
            )
            if budget is not None:
                await _quiet(budget.release(), "budget release")
            if provider:
                await _quiet(provider.close(), "provider close")
