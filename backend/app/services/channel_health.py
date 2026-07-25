"""渠道健康监测：基于 Redis 记录连续失败次数，超阈值自动熔断，后台定期探测恢复。"""

import asyncio
import logging
import time

import httpx

from app.config import settings
from app.dependencies import get_redis
from app.utils.secrets import decrypt_secret
from app.utils.upstream_url import upstream_url

logger = logging.getLogger(__name__)

FAIL_KEY_PREFIX = "five:health:fail:"
DISABLED_KEY_PREFIX = "five:health:disabled:"
COOLDOWN_KEY_PREFIX = "five:health:cooldown:"
FAIL_TTL = 3600


async def record_success(channel_id: int) -> None:
    """请求成功时重置失败计数并清除熔断标记。"""
    r = await get_redis()
    await r.delete(f"{FAIL_KEY_PREFIX}{channel_id}")
    await r.delete(f"{DISABLED_KEY_PREFIX}{channel_id}")
    await r.delete(f"{COOLDOWN_KEY_PREFIX}{channel_id}")


async def record_failure(channel_id: int) -> None:
    """请求失败时累加计数，超阈值则熔断。"""
    r = await get_redis()
    fail_key = f"{FAIL_KEY_PREFIX}{channel_id}"
    count = await r.incr(fail_key)
    if count == 1:
        await r.expire(fail_key, FAIL_TTL)
    if count >= settings.CHANNEL_HEALTH_THRESHOLD:
        await r.set(f"{DISABLED_KEY_PREFIX}{channel_id}", str(int(time.time())))
        logger.warning("Channel %d disabled after %d consecutive failures", channel_id, count)


async def is_channel_healthy(channel_id: int) -> bool:
    """检查渠道是否健康（未被熔断）。"""
    r = await get_redis()
    return not await r.exists(
        f"{DISABLED_KEY_PREFIX}{channel_id}", f"{COOLDOWN_KEY_PREFIX}{channel_id}"
    )


async def record_rate_limit(channel_id: int, seconds: int = 30) -> None:
    """上游 429 时短暂冷却，避免连续击穿同一渠道。"""
    r = await get_redis()
    await r.set(f"{COOLDOWN_KEY_PREFIX}{channel_id}", "1", ex=max(1, seconds))


async def get_health_status(channel_ids: list[int]) -> dict[int, dict]:
    """批量获取渠道健康状态，返回 {channel_id: {healthy, fail_count, disabled_at}}。"""
    r = await get_redis()
    result = {}
    for cid in channel_ids:
        fail_count = await r.get(f"{FAIL_KEY_PREFIX}{cid}")
        disabled_at = await r.get(f"{DISABLED_KEY_PREFIX}{cid}")
        cooldown = await r.ttl(f"{COOLDOWN_KEY_PREFIX}{cid}")
        result[cid] = {
            "healthy": disabled_at is None and cooldown <= 0,
            "fail_count": int(fail_count) if fail_count else 0,
            "disabled_at": int(disabled_at) if disabled_at else None,
            "cooldown_seconds": max(cooldown, 0),
        }
    return result


async def force_recover(channel_id: int) -> None:
    """手动强制恢复渠道。"""
    await record_success(channel_id)
    logger.info("Channel %d force recovered", channel_id)


async def _probe_channel(channel) -> bool:
    """探测单个渠道是否可用，复用 test_channel 的逻辑。"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if channel.provider == "anthropic":
                url = upstream_url(channel.base_url, "/v1/messages")
                api_key = decrypt_secret(channel.api_key)
                headers = {
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                if api_key:
                    headers["x-api-key"] = api_key
                resp = await client.post(
                    url, headers=headers,
                    json={"model": channel.model_mapping.get(
                              (channel.models or [""])[0], (channel.models or [""])[0]
                          ), "max_tokens": 1,
                          "messages": [{"role": "user", "content": "hi"}]},
                )
            else:
                url = upstream_url(channel.base_url, "/v1/models")
                api_key = decrypt_secret(channel.api_key)
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get(url, headers=headers)
            return resp.status_code < 400
    except Exception:
        return False


async def health_check_loop() -> None:
    """后台循环：只探测已熔断/冷却的渠道，避免健康检查产生持续费用。"""
    from app.models import Channel

    interval = settings.CHANNEL_HEALTH_CHECK_INTERVAL
    while True:
        await asyncio.sleep(interval)
        try:
            channels = await Channel.filter(is_enabled=True)
            for channel in channels:
                if await is_channel_healthy(channel.id):
                    continue
                if await _probe_channel(channel):
                    await record_success(channel.id)
                else:
                    await record_failure(channel.id)
                    logger.warning("Channel %d (%s) failed health probe", channel.id, channel.name)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in health check loop")
