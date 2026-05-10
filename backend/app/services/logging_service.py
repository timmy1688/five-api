from decimal import Decimal

from app.models import RequestLog


async def save_request_log(
    request_id: str,
    api_key_id: int,
    api_key_name: str,
    channel_id: int | None,
    channel_name: str,
    model_requested: str,
    model_actual: str,
    provider: str,
    endpoint: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost: Decimal = Decimal(0),
    cached_tokens: int = 0,
    is_stream: bool = False,
    status_code: int = 0,
    latency_ms: int = 0,
    error_message: str = "",
    ip_address: str = "",
) -> None:
    await RequestLog.create(
        request_id=request_id,
        api_key_id=api_key_id,
        api_key_name=api_key_name,
        channel_id=channel_id,
        channel_name=channel_name,
        model_requested=model_requested,
        model_actual=model_actual,
        provider=provider,
        endpoint=endpoint,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cached_tokens=cached_tokens,
        cost=cost,
        is_stream=is_stream,
        status_code=status_code,
        latency_ms=latency_ms,
        error_message=error_message,
        ip_address=ip_address,
    )
