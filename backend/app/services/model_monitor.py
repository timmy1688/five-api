"""Periodic model probes shared by all workers; SQL history survives restarts."""
import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import anyio
from tortoise.functions import Max

from app import dependencies
from app.models import Channel, ModelProbe
from app.services.concurrency import concurrency_limiter
from app.services.model_checks import run_probe, supports_capability
from app.services.settings_service import gateway_config

logger = logging.getLogger(__name__)
SWEEP_SECONDS = 30
RUNTIME_KEY = "five:model_monitor:runtime"


async def scheduler_status() -> dict:
    """The worker that ran the latest sweep records it; missing for two periods means stopped."""
    raw = await (await dependencies.get_redis()).get(RUNTIME_KEY)
    if not raw:
        return {"running": False, "last_sweep_at": None, "next_sweep_at": None}
    return {"running": True, **json.loads(raw)}


def supports_health(model):
    return not any(word in model.lower() for word in ("embedding", "whisper", "tts", "sora", "dall-e", "image", "rerank"))


def next_check(record, interval):
    return record.created_at + timedelta(seconds=interval) if record else None


@asynccontextmanager
async def probe_slot(channel_id, model, kind):
    redis = await dependencies.get_redis()
    digest = hashlib.sha256(model.encode()).hexdigest()[:20]
    name = f"five:model_probe:lock:{channel_id}:{digest}:{kind}"
    from uuid import uuid4
    token = uuid4().hex
    if not await redis.set(name, token, nx=True, ex=120):
        yield False
        return
    lease = ""
    try:
        lease = await concurrency_limiter.acquire(0, 2, scope="model_probe_global")
        yield True
    finally:
        with anyio.move_on_after(5, shield=True):
            if lease:
                await concurrency_limiter.release(0, lease, scope="model_probe_global")
            # The bounded probe runs for at most 60s; the 120s lock cannot be stolen by a valid run.
            if await redis.get(name) == token:
                await redis.delete(name)


async def latest_probes():
    ids = await ModelProbe.annotate(latest_id=Max("id")).group_by(
        "channel_id", "model", "actual_model", "kind",
    ).values_list("latest_id", flat=True)
    return {(row.channel_id, row.model, row.actual_model, row.kind): row
            for row in await ModelProbe.filter(id__in=ids)}


async def run_due_once(*, now=None, limit=10):
    now = now or datetime.now(timezone.utc)
    config = (await gateway_config())["model_checks"]
    if not config["health_enabled"] and not config["capability_enabled"]:
        return 0
    latest = await latest_probes()
    due = []
    for channel in await Channel.filter(is_enabled=True):
        for model in channel.models or []:
            actual = (channel.model_mapping or {}).get(model, model)
            if not supports_health(actual):
                continue
            for kind in ("health", "capability"):
                if not config[kind + "_enabled"] or (kind == "capability" and not supports_capability(actual)):
                    continue
                record = latest.get((channel.id, model, actual, kind))
                deadline = next_check(record, config[kind + "_interval_seconds"])
                if deadline is None or deadline <= now:
                    due.append((deadline or datetime.min.replace(tzinfo=timezone.utc), channel, model, kind))
    due.sort(key=lambda item: (item[0], item[1].id, item[2], item[3]))
    async def check(item):
        _, channel, model, kind = item
        try:
            async with probe_slot(channel.id, model, kind) as acquired:
                if not acquired:
                    return 0
                # Manual checks may have completed since the sweep began.
                actual = (channel.model_mapping or {}).get(model, model)
                recent = await ModelProbe.filter(channel_id=channel.id, model=model, actual_model=actual, kind=kind).order_by("-id").first()
                if recent and next_check(recent, config[kind + "_interval_seconds"]) > now:
                    return 0
                await run_probe(channel, model, kind, None, source="scheduled")
                return 1
        except Exception:
            logger.exception("Scheduled model check unavailable channel=%s model=%s", channel.id, model)
            return 0
    completed = 0
    # Two at a time, also shared with manual probes through a Redis lease.
    for index in range(0, min(limit, len(due)), 2):
        completed += sum(await asyncio.gather(*(check(item) for item in due[index:index+2])))
    return completed


async def model_check_loop():
    from app.services.cluster import claim
    await asyncio.sleep(15)
    while True:
        try:
            # Probes also hold per-model locks; the claim keeps the due-list query to one worker.
            if await claim("model-sweep", SWEEP_SECONDS - 5):
                started = datetime.now(timezone.utc)
                try:
                    await run_due_once()
                except Exception:
                    logger.exception("Model check scheduler unavailable")
                status = {"last_sweep_at": started.isoformat(),
                          "next_sweep_at": (datetime.now(timezone.utc) + timedelta(seconds=SWEEP_SECONDS)).isoformat()}
                await (await dependencies.get_redis()).set(RUNTIME_KEY, json.dumps(status), ex=SWEEP_SECONDS * 2 + 15)
        except Exception:
            logger.exception("Model check scheduler unavailable")
        await asyncio.sleep(SWEEP_SECONDS)
