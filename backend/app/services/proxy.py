import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal

from app.models import APIKey, Channel
from app.providers.base import BaseProvider
from app.services.concurrency import concurrency_limiter
from app.services.channel_health import record_failure, record_success
from app.services.failover import is_retryable_error
from app.services.logging_service import save_request_log
from app.services.pricing import calculate_cost
from app.services.quota import deduct_quota


async def stream_proxy(
    candidates: list[tuple[Channel, type[BaseProvider]]],
    openai_request: dict,
    endpoint: str,
    api_key: APIKey,
    request_id: str,
    start_time: float,
    ip_address: str = "",
) -> AsyncIterator[str]:
    model_requested = openai_request.get("model", "")
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    status_code = 200
    error_msg = ""
    channel: Channel | None = None
    provider: BaseProvider | None = None
    model_actual = model_requested
    data_yielded = False

    try:
        last_error: Exception | None = None
        for i, (ch, provider_cls) in enumerate(candidates):
            prov = provider_cls(ch)
            try:
                async for line in prov.send_stream(openai_request, endpoint):
                    if not data_yielded:
                        channel = ch
                        provider = prov
                        model_actual = prov.apply_model_mapping(model_requested)
                        data_yielded = True
                    yield line
                    if line.startswith("data: ") and not line.startswith("data: [DONE]"):
                        try:
                            chunk = json.loads(line[6:])
                            usage = chunk.get("usage")
                            if usage:
                                prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                                completion_tokens = usage.get("completion_tokens", completion_tokens)
                                cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", cached_tokens)
                        except (json.JSONDecodeError, KeyError):
                            pass
                if not data_yielded:
                    channel = ch
                    provider = prov
                    model_actual = prov.apply_model_mapping(model_requested)
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
                model_actual = prov.apply_model_mapping(model_requested)
                raise

        if last_error is not None:
            raise last_error

    except Exception as e:
        status_code = 500
        error_msg = str(e)
        err_chunk = {
            "error": {"message": f"Upstream error: {e}", "type": "server_error", "code": "upstream_error"}
        }
        yield f"data: {json.dumps(err_chunk)}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        await concurrency_limiter.release(api_key.id)
        latency_ms = int((time.monotonic() - start_time) * 1000)

        cost = Decimal(0)
        if prompt_tokens > 0 or completion_tokens > 0:
            cost = await calculate_cost(model_actual, prompt_tokens, completion_tokens, channel, cached_tokens=cached_tokens)
            if cost > 0:
                await deduct_quota(api_key.id, cost)

        await save_request_log(
            request_id=request_id,
            api_key_id=api_key.id,
            api_key_name=api_key.name,
            channel_id=channel.id if channel else 0,
            channel_name=channel.name if channel else "",
            model_requested=model_requested,
            model_actual=model_actual,
            provider=channel.provider if channel else "",
            endpoint=endpoint,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost=cost,
            is_stream=True,
            status_code=status_code,
            latency_ms=latency_ms,
            error_message=error_msg,
            ip_address=ip_address,
        )
        if provider:
            await provider.close()
