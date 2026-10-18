"""Per-channel load and latency, read by the least_busy and latency routing strategies."""

import logging

from app import dependencies

logger = logging.getLogger(__name__)

INFLIGHT_PREFIX = "five:ch_inflight:"
LATENCY_PREFIX = "five:ch_latency:"
# A crashed worker never decrements, so the counter expires on its own.
INFLIGHT_TTL = 600
LATENCY_TTL = 3600
# Weight of the newest sample in the moving average.
LATENCY_ALPHA = 0.2


async def begin_attempt(channel_id: int) -> None:
    try:
        r = await dependencies.get_redis()
        await r.incr(f"{INFLIGHT_PREFIX}{channel_id}")
        await r.expire(f"{INFLIGHT_PREFIX}{channel_id}", INFLIGHT_TTL)
    except Exception:
        logger.debug("inflight incr failed for channel %s", channel_id, exc_info=True)


async def end_attempt(channel_id: int) -> None:
    try:
        r = await dependencies.get_redis()
        await r.decr(f"{INFLIGHT_PREFIX}{channel_id}")
    except Exception:
        logger.debug("inflight decr failed for channel %s", channel_id, exc_info=True)


async def record_latency(channel_id: int, latency_ms: float) -> None:
    try:
        r = await dependencies.get_redis()
        key = f"{LATENCY_PREFIX}{channel_id}"
        previous = await r.get(key)
        value = float(latency_ms)
        if previous is not None:
            value = float(previous) * (1 - LATENCY_ALPHA) + value * LATENCY_ALPHA
        await r.set(key, f"{value:.1f}", ex=LATENCY_TTL)
    except Exception:
        logger.debug("latency record failed for channel %s", channel_id, exc_info=True)


async def load_scores(channel_ids: list[int], strategy: str) -> dict[int, float]:
    """Lower is better. Channels without data score 0, so new channels get traffic."""
    prefix = INFLIGHT_PREFIX if strategy == "least_busy" else LATENCY_PREFIX
    scores: dict[int, float] = {}
    try:
        r = await dependencies.get_redis()
        for channel_id in channel_ids:
            raw = await r.get(f"{prefix}{channel_id}")
            scores[channel_id] = max(float(raw), 0.0) if raw is not None else 0.0
    except Exception:
        logger.debug("channel stats read failed", exc_info=True)
        return {channel_id: 0.0 for channel_id in channel_ids}
    return scores
