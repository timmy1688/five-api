"""通用代理编排：故障转移、计费、日志。

所有代理路由共享此模块，协议差异通过 send_fn / stream_fn 回调注入。
"""

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from app.models import APIKey, Channel
from app.providers.base import BaseProvider
from app.services.channel_health import record_failure, record_rate_limit, record_success
from app.services.concurrency import concurrency_limiter
from app.services.failover import is_retryable_error, upstream_status
from app.services.logging_service import save_request_log
from app.services.pricing import calculate_cost
from app.services.quota import deduct_quota
from app.services.sticky_session import bind_sticky_channel

logger = logging.getLogger(__name__)


async def _quiet(awaitable, operation: str):
    """辅助操作失败不能覆盖已经成功的上游响应。"""
    try:
        return await awaitable
    except Exception:
        logger.exception("%s failed", operation)
        return None


def extract_openai_usage(data: dict) -> dict:
    """从 OpenAI 格式响应/chunk 中提取 usage。"""
    usage = data.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        # OpenAI-compatible providers expose cache usage under either the
        # OpenAI nested field or DeepSeek's top-level field.
        "cached_tokens": prompt_details.get(
            "cached_tokens",
            usage.get("prompt_cache_hit_tokens", 0),
        ),
    }


async def _bill_and_log(
    model_actual: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
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
    failed_over: bool = False,
):
    """计费 + 扣费 + 写日志。"""
    latency_ms = int((time.monotonic() - start_time) * 1000)
    cost = Decimal(0)
    try:
        if prompt_tokens > 0 or completion_tokens > 0:
            cost = await calculate_cost(
                model_actual, prompt_tokens, completion_tokens, channel,
                cached_tokens=cached_tokens,
            )
            if cost > 0:
                await deduct_quota(api_key.id, cost)
    except Exception:
        logger.exception("billing failed for request %s", request_id)

    try:
        await save_request_log(
            request_id=request_id,
            api_key_id=api_key.id,
            api_key_name=api_key.name,
            channel_id=channel.id if channel else None,
            channel_name=channel.name if channel else "",
            model_requested=model_requested,
            model_actual=model_actual,
            provider=channel.provider if channel else "",
            endpoint=endpoint,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost=cost,
            is_stream=is_stream,
            status_code=status_code,
            latency_ms=latency_ms,
            error_message=error_message,
            ip_address=ip,
            failed_over=failed_over,
        )
    except Exception:
        logger.exception("request logging failed for request %s", request_id)


async def log_rejected_request(
    api_key: APIKey,
    request_id: str,
    endpoint: str,
    model: str,
    status_code: int,
    start_time: float,
    ip: str,
    error_message: str,
) -> None:
    """Record an authenticated request rejected before reaching an upstream."""
    await _bill_and_log(
        model, 0, 0, 0, None, api_key, request_id, endpoint, model,
        is_stream=False, status_code=status_code, start_time=start_time, ip=ip,
        error_message=error_message,
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
) -> Any:
    """非流式通用编排：故障转移 → 计费 → 日志。

    send_fn(provider, channel) -> (response, usage_dict)
      usage_dict = {"prompt_tokens": int, "completion_tokens": int, "cached_tokens": int}
    format_error(status_code, error_type, code, message) -> raises HTTPException
    """
    try:
        for i, (channel, provider_cls) in enumerate(candidates):
            provider = provider_cls(channel)
            try:
                for attempt in range(channel.max_retries + 1):
                    try:
                        response, usage = await send_fn(provider, channel)
                        break
                    except Exception as exc:
                        status_code = upstream_status(exc)
                        if status_code == 429:
                            await _quiet(record_rate_limit(channel.id), "rate-limit cooldown")
                        elif is_retryable_error(exc):
                            await _quiet(record_failure(channel.id), "failure tracking")
                        can_retry_same = (
                            is_retryable_error(exc)
                            and status_code != 429
                            and attempt < channel.max_retries
                        )
                        if not can_retry_same:
                            raise

                model_actual = provider.apply_model_mapping(model_requested)
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                cached_tokens = usage.get("cached_tokens", 0)

                await _bill_and_log(
                    model_actual, prompt_tokens, completion_tokens, cached_tokens,
                    channel, api_key, request_id, endpoint, model_requested,
                    is_stream=False, status_code=200, start_time=start_time, ip=ip,
                    failed_over=i > 0,
                )
                await _quiet(record_success(channel.id), "health reset")
                await _quiet(bind_sticky_channel(session_key, channel.id), "sticky binding")
                return response

            except HTTPException:
                raise
            except Exception as e:
                if is_retryable_error(e) and i < len(candidates) - 1:
                    continue

                model_actual = provider.apply_model_mapping(model_requested)
                status_code = upstream_status(e) or 502
                await _bill_and_log(
                    model_actual, 0, 0, 0,
                    channel, api_key, request_id, endpoint, model_requested,
                    is_stream=False, status_code=status_code, start_time=start_time, ip=ip,
                    error_message=str(e),
                    failed_over=i > 0,
                )
                format_error(status_code, "api_error", "upstream_error", f"Upstream error: {e}")
            finally:
                await _quiet(provider.close(), "provider close")
    finally:
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
    status_code = 200
    error_msg = ""
    channel: Channel | None = None
    provider: BaseProvider | None = None
    model_actual = model_requested
    data_yielded = False
    failed_over = False

    try:
        last_error: Exception | None = None
        for i, (ch, provider_cls) in enumerate(candidates):
            prov = provider_cls(ch)
            try:
                for attempt in range(ch.max_retries + 1):
                    try:
                        async for line, usage in stream_fn(prov, ch):
                            if not data_yielded:
                                channel = ch
                                provider = prov
                                model_actual = prov.apply_model_mapping(model_requested)
                                data_yielded = True
                            if usage:
                                prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                                completion_tokens = usage.get("completion_tokens", completion_tokens)
                                cached_tokens = usage.get("cached_tokens", cached_tokens)
                            yield line
                        break
                    except Exception as exc:
                        last_error = exc
                        code = upstream_status(exc)
                        if code == 429:
                            await _quiet(record_rate_limit(ch.id), "rate-limit cooldown")
                        elif is_retryable_error(exc):
                            await _quiet(record_failure(ch.id), "failure tracking")
                        if data_yielded or not is_retryable_error(exc) or code == 429 or attempt >= ch.max_retries:
                            raise

                if not data_yielded:
                    channel = ch
                    provider = prov
                    model_actual = prov.apply_model_mapping(model_requested)
                last_error = None
                await _quiet(record_success(ch.id), "health reset")
                await _quiet(bind_sticky_channel(session_key, ch.id), "sticky binding")
                break

            except Exception as e:
                if not data_yielded and is_retryable_error(e) and i < len(candidates) - 1:
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

    except Exception as e:
        status_code = upstream_status(e) or 502
        error_msg = str(e)
        yield format_error_event(e)
    finally:
        await _quiet(
            concurrency_limiter.release(api_key.id, concurrency_lease_id),
            "concurrency release",
        )
        await _bill_and_log(
            model_actual, prompt_tokens, completion_tokens, cached_tokens,
            channel, api_key, request_id, endpoint, model_requested,
            is_stream=True, status_code=status_code, start_time=start_time, ip=ip,
            error_message=error_msg,
            failed_over=failed_over,
        )
        if provider:
            await _quiet(provider.close(), "provider close")
