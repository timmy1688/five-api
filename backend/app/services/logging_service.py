import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from app.config import settings
from app.models import RequestLog
from app.services.metrics import record_request_metrics

logger = logging.getLogger(__name__)


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
    failed_over: bool = False,
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
        failed_over=failed_over,
    )

    record_request_metrics(
        model=model_actual or model_requested,
        provider=provider,
        channel_name=channel_name,
        status_code=status_code,
        endpoint=endpoint,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cost=float(cost),
        latency_seconds=latency_ms / 1000.0,
    )


async def cleanup_old_logs(days: int | None = None) -> int:
    """删除超过保留天数的日志，分批删除避免锁表。返回删除总数。"""
    retention = days if days is not None else settings.LOG_RETENTION_DAYS
    if retention <= 0:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=retention)
    total_deleted = 0
    batch_size = 10000
    while True:
        ids = await RequestLog.filter(created_at__lt=cutoff).limit(batch_size).values_list("id", flat=True)
        if not ids:
            break
        deleted = await RequestLog.filter(id__in=ids).delete()
        total_deleted += deleted
    if total_deleted > 0:
        logger.info("Cleaned up %d logs older than %d days", total_deleted, retention)
    return total_deleted


async def log_cleanup_loop() -> None:
    """后台循环：每天清理一次过期日志。"""
    while True:
        await asyncio.sleep(86400)
        try:
            await cleanup_old_logs()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in log cleanup loop")
