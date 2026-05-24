"""渠道健康监测：基于 Redis 记录连续失败次数，超阈值自动熔断，后台定期探测恢复。"""

import asyncio
import logging
import time

import httpx

from app.config import settings
from app.dependencies import get_redis

logger = logging.getLogger(__name__)

FAIL_KEY_PREFIX = "five:health:fail:"
DISABLED_KEY_PREFIX = "five:health:disabled:"
FAIL_TTL = 3600


async def record_success(channel_id: int) -> None:
    """请求成功时重置失败计数并清除熔断标记。"""
    r = await get_redis()
    await r.delete(f"{FAIL_KEY_PREFIX}{channel_id}")
    await r.delete(f"{DISABLED_KEY_PREFIX}{channel_id}")


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
    return await r.exists(f"{DISABLED_KEY_PREFIX}{channel_id}") == 0


async def get_health_status(channel_ids: list[int]) -> dict[int, dict]:
    """批量获取渠道健康状态，返回 {channel_id: {healthy, fail_count, disabled_at}}。"""
    r = await get_redis()
    result = {}
    for cid in channel_ids:
        fail_count = await r.get(f"{FAIL_KEY_PREFIX}{cid}")
        disabled_at = await r.get(f"{DISABLED_KEY_PREFIX}{cid}")
        result[cid] = {
            "healthy": disabled_at is None,
            "fail_count": int(fail_count) if fail_count else 0,
            "disabled_at": int(disabled_at) if disabled_at else None,
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
                url = f"{channel.base_url.rstrip('/')}/v1/messages"
                headers = {
                    "x-api-key": channel.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                resp = await client.post(
                    url, headers=headers,
                    json={"model": "claude-3-haiku-20240307", "max_tokens": 1,
                          "messages": [{"role": "user", "content": "hi"}]},
                )
            else:
                url = f"{channel.base_url.rstrip('/')}/v1/models"
                headers = {"Authorization": f"Bearer {channel.api_key}"}
                resp = await client.get(url, headers=headers)
            return resp.status_code < 400
    except Exception:
        return False


async def health_check_loop() -> None:
    """后台循环：主动探测所有启用渠道，发现不可用时记录失败，恢复可用时清除熔断。"""
    from app.models import Channel

    interval = settings.CHANNEL_HEALTH_CHECK_INTERVAL
    while True:
        await asyncio.sleep(interval)
        try:
            channels = await Channel.filter(is_enabled=True)
            for channel in channels:
                if await _probe_channel(channel):
                    await record_success(channel.id)
                else:
                    await record_failure(channel.id)
                    logger.warning("Channel %d (%s) failed health probe", channel.id, channel.name)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in health check loop")
