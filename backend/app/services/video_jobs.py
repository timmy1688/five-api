"""Channel, upstream key and owner of each video job.

A video is created once and then polled and downloaded by id, so every later
call has to reach the channel and upstream key that created it.
"""
import json

from app import dependencies
from app.services.key_pool import key_fingerprint

# Upstreams keep finished videos for a limited time; a week outlives that.
VIDEO_JOB_TTL = 7 * 86400


def _job_key(video_id: str, api_key_id: int) -> str:
    return f"five:video:{api_key_id}:{video_id}"


async def remember_video(
    video_id: str, *, channel_id: int, api_key_id: int, upstream_key: str, model: str, seconds: int,
) -> None:
    job = {
        "channel_id": channel_id,
        "api_key_id": api_key_id,
        "key": key_fingerprint(upstream_key),
        "model": model,
        "seconds": seconds,
    }
    r = await dependencies.get_redis()
    await r.set(_job_key(video_id, api_key_id), json.dumps(job), ex=VIDEO_JOB_TTL)


async def find_video(video_id: str, api_key_id: int) -> dict | None:
    """The job, or None when it is unknown or belongs to another key."""
    r = await dependencies.get_redis()
    raw = await r.get(_job_key(video_id, api_key_id))
    if not raw:
        # Existing jobs expire within a week; verify the owner before returning one.
        raw = await r.get(f"five:video:{video_id}")
    if not raw:
        return None
    job = json.loads(raw)
    return job if job.get("api_key_id") == api_key_id else None


async def forget_video(video_id: str, api_key_id: int) -> None:
    r = await dependencies.get_redis()
    await r.delete(_job_key(video_id, api_key_id))
    legacy_key = f"five:video:{video_id}"
    legacy = await r.get(legacy_key)
    if legacy and json.loads(legacy).get("api_key_id") == api_key_id:
        await r.delete(legacy_key)


def upstream_key_for(keys: list[str], fingerprint: str) -> str:
    """The pool key that created the job. A removed key falls back to the first."""
    for key in keys:
        if key_fingerprint(key) == fingerprint:
            return key
    return keys[0] if keys else ""
