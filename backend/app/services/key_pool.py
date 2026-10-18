"""Several upstream keys on one channel. Each key cools down on its own."""

import email.utils
import hashlib
import logging
import time

import httpx

from app import dependencies

logger = logging.getLogger(__name__)

COOL_PREFIX = "five:keycool:"
ROUND_ROBIN_PREFIX = "five:keyrr:"
DEFAULT_RATE_LIMIT_COOLDOWN = 30
AUTH_FAILURE_COOLDOWN = 600
MAX_COOLDOWN = 3600
# Statuses that belong to one key rather than to the whole channel.
KEY_STATUSES = {401, 403, 429}


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _cool_key(channel_id: int, key: str) -> str:
    return f"{COOL_PREFIX}{channel_id}:{key_fingerprint(key)}"


def retry_after_seconds(exc: Exception, default: int = DEFAULT_RATE_LIMIT_COOLDOWN) -> int:
    """Seconds from Retry-After or retry-after-ms, capped at an hour."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not isinstance(headers, (httpx.Headers, dict)):
        return default
    lowered = {k.lower(): v for k, v in headers.items()}
    try:
        if "retry-after-ms" in lowered:
            return min(max(int(float(lowered["retry-after-ms"]) / 1000) + 1, 1), MAX_COOLDOWN)
        raw = lowered.get("retry-after")
        if raw is None:
            return default
        try:
            seconds = float(raw)
        except ValueError:
            parsed = email.utils.parsedate_to_datetime(raw)
            seconds = parsed.timestamp() - time.time()
        return min(max(int(seconds) + 1, 1), MAX_COOLDOWN)
    except (TypeError, ValueError, OverflowError):
        return default


def cooldown_for(exc: Exception) -> int:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429:
        return retry_after_seconds(exc)
    return AUTH_FAILURE_COOLDOWN


async def available_keys(channel_id: int, keys: list[str]) -> list[str]:
    if len(keys) <= 1:
        return list(keys)
    r = await dependencies.get_redis()
    ready = []
    for key in keys:
        if not await r.exists(_cool_key(channel_id, key)):
            ready.append(key)
    return ready


async def pick_key(channel_id: int, keys: list[str], session_key: str | None = None) -> str:
    """Same session, same key, so the upstream prompt cache stays warm."""
    if not keys:
        return ""
    if len(keys) == 1:
        return keys[0]
    ready = await available_keys(channel_id, keys) or keys
    if session_key:
        index = int(hashlib.sha256(session_key.encode()).hexdigest(), 16) % len(ready)
        return ready[index]
    r = await dependencies.get_redis()
    counter = await r.incr(f"{ROUND_ROBIN_PREFIX}{channel_id}")
    return ready[counter % len(ready)]


async def cool_down(channel_id: int, key: str, seconds: int) -> None:
    r = await dependencies.get_redis()
    await r.set(_cool_key(channel_id, key), str(int(time.time()) + seconds), ex=max(seconds, 1))
    logger.info("Key %s on channel %d cooling for %ds", key_fingerprint(key), channel_id, seconds)


async def pool_status(channel_id: int, keys: list[str]) -> dict:
    ready = await available_keys(channel_id, keys)
    return {"keys_total": len(keys), "keys_cooling": len(keys) - len(ready)}
