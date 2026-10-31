import asyncio
import logging
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tortoise.transactions import in_transaction

from app.models import RequestLog, RequestLogAudit
from app.services.metrics import record_request_metrics
from app.services.usage_stats import record_daily_usage, _record_minute
from app.services.redaction import redact
from app.services.request_context import client_request_id as correlation_id

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
    cache_write_tokens: int = 0,
    is_stream: bool = False,
    status_code: int = 0,
    latency_ms: int = 0,
    error_message: str = "",
    error_origin: str = "",
    upstream_status_code: int = 0,
    upstream_error: str = "",
    ip_address: str = "",
    failed_over: bool = False,
    audit_request: str = "",
    security_hit: str = "",
    tenant_id: int = 0,
    session_id: str = "",
    cache_savings: Decimal = Decimal(0),
    cost_detail: dict | None = None,
    client_request_id: str = "",
    usage_source: str = "upstream",
    observed_at: str | None = None,
    observe: bool = True,
) -> RequestLog:
    try:
        audit_request = json.dumps(redact(json.loads(audit_request)), ensure_ascii=False) if audit_request else ""
    except (ValueError, TypeError):
        audit_request = redact(audit_request)
    has_audit = bool(audit_request)
    async with in_transaction():
        log = await RequestLog.create(
            request_id=request_id,
            client_request_id=client_request_id or correlation_id.get(),
            usage_source=usage_source,
            created_at=datetime.fromisoformat(observed_at) if observed_at else datetime.now(timezone.utc),
            api_key_id=api_key_id,
            tenant_id=tenant_id,
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
            cache_write_tokens=cache_write_tokens,
            cost=cost,
            is_stream=is_stream,
            status_code=status_code,
            latency_ms=latency_ms,
            error_message=redact(error_message),
            error_origin=error_origin,
            upstream_status_code=upstream_status_code,
            upstream_error=redact(upstream_error),
            ip_address=ip_address,
            failed_over=failed_over,
            has_audit=has_audit,
            security_hit=security_hit[:128],
            session_id=session_id[:32],
            cache_savings=cache_savings,
            cost_detail=cost_detail,
        )
        if has_audit:
            await RequestLogAudit.create(
                request_log=log,
                audit_request=audit_request,
            )

        await record_daily_usage(
            api_key_id=api_key_id,
            api_key_name=api_key_name,
            tenant_id=tenant_id,
            model=model_requested,
            channel_id=channel_id,
            channel_name=channel_name,
            status_code=status_code,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_savings=cache_savings,
            when=log.created_at, realtime=False,
        )
    if observe:
        await observe_request_log(log)
    return log


async def observe_request_log(log: RequestLog) -> None:
    try:
        await _record_minute(log.created_at)
        record_request_metrics(
            model=log.model_actual or log.model_requested, provider=log.provider,
            channel_name=log.channel_name, status_code=log.status_code, endpoint=log.endpoint,
            prompt_tokens=log.prompt_tokens, completion_tokens=log.completion_tokens,
            cached_tokens=log.cached_tokens, cost=float(log.cost), latency_seconds=log.latency_ms / 1000.0,
        )
    except Exception:
        logger.exception("Post-commit observation failed for request %s", log.request_id)


async def cleanup_old_logs(days: int | None = None) -> int:
    """删除超过保留天数的日志，分批删除避免锁表。返回删除总数。"""
    if days is None:
        from app.services.settings_service import gateway_config

        retention = (await gateway_config())["log_retention_days"]
    else:
        retention = days
    if retention <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
    total_deleted = 0
    batch_size = 10000
    while True:
        ids = await RequestLog.filter(created_at__lt=cutoff).limit(batch_size).values_list("id", flat=True)
        if not ids:
            break
        await RequestLogAudit.filter(request_log_id__in=ids).delete()
        deleted = await RequestLog.filter(id__in=ids).delete()
        total_deleted += deleted
    if total_deleted > 0:
        logger.info("Cleaned up %d logs older than %d days", total_deleted, retention)
    return total_deleted


async def log_cleanup_loop() -> None:
    """后台循环：所有 worker 合计每天清理一次过期日志。"""
    from app.services.cluster import claim
    while True:
        await asyncio.sleep(600)
        try:
            if await claim("log-cleanup", 86400):
                await cleanup_old_logs()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in log cleanup loop")
